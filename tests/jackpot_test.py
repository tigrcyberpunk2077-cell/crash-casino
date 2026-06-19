"""Тесты мультиплеер-джекпота «Забег»: честность точки поимки, выбор победителя
по доле ставки, списание/начисление и сохранность общего баланса.

Запуск: python3 tests/jackpot_test.py  (нужен установленный стек)
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from casino.db import Database
from casino.provably_fair import generate_server_seed, hash_server_seed
from casino.units import to_nano
from casino.webapp.jackpot import (Entry, JackpotGame, pick_winner,
                                    verify_fraction, winning_fraction)

_passed = _failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1; print(f"  ok   {name}")
    else:
        _failed += 1; print(f"  FAIL {name}")


async def main():
    print("provably-fair (точка поимки):")
    seed = generate_server_seed()
    rid = "abc123"
    f = winning_fraction(seed, rid)
    check("f в [0,1)", 0.0 <= f < 1.0)
    check("f детерминирована", f == winning_fraction(seed, rid))
    check("другой round_id -> другая f", f != winning_fraction(seed, "other"))
    h = hash_server_seed(seed)
    check("verify честной f", verify_fraction(seed, h, rid, f))
    check("verify ловит подделку seed", not verify_fraction(seed, "dead", rid, f))
    check("verify ловит подделку f", not verify_fraction(seed, h, rid, f + 0.1))

    print("выбор победителя по доле:")
    order = [Entry(1, "a", "r", 10), Entry(2, "b", "r", 30)]  # доли 25% / 75%
    w0, total = pick_winner(order, 0.0)
    check("f=0 -> первый кусок", w0.user_id == 1 and total == 40)
    w_mid, _ = pick_winner(order, 0.20)            # 0.20*40=8 < 10 -> первый
    check("f=0.20 -> первый (в его доле)", w_mid.user_id == 1)
    w_hi, _ = pick_winner(order, 0.50)             # 0.50*40=20 > 10 -> второй
    check("f=0.50 -> второй (большая доля)", w_hi.user_id == 2)
    w_last, _ = pick_winner(order, 0.999)
    check("f≈1 -> последний", w_last.user_id == 2)
    check("пустое поле -> нет победителя", pick_winner([], 0.5) == (None, 0))

    # Грубая проверка взвешенности: при долях 25/75 второй выигрывает ~чаще.
    wins2 = 0
    for n in range(400):
        s = generate_server_seed()
        ww, _ = pick_winner(order, winning_fraction(s, f"r{n}"))
        if ww.user_id == 2:
            wins2 += 1
    check(f"75%-кусок выигрывает чаще (факт {wins2/400:.0%})", 0.65 < wins2 / 400 < 0.85)

    print("движок раунда (списание/начисление):")
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    db = Database(tmp.name); await db.connect()
    for uid in (101, 102):
        await db.get_or_create_user(uid, f"u{uid}")
        await db.credit(uid, to_nano(100), "faucet")
    start_total = await db.get_balance(101) + await db.get_balance(102)

    game = JackpotGame(db, min_bet=to_nano(0.1), max_bet=to_nano(100), round_seconds=30)
    ok, err, bal = await game.place_bet(101, "u101", to_nano(10), "samir")
    check("ставка принята", ok and err is None)
    check("баланс списан до 90", await db.get_balance(101) == to_nano(90))
    check("фаза стала collecting", game._phase == "collecting")
    await game.place_bet(102, "u102", to_nano(30), "gold")
    check("банк = 40", game._pot == to_nano(40))
    check("в снимке двое игроков", len(game.snapshot()["players"]) == 2)

    ok2, err2, _ = await game.place_bet(102, "u102", to_nano(999), "gold")
    check("слишком большая ставка отклонена", not ok2 and err2 is not None)
    poor_ok, poor_err, _ = await game.place_bet(101, "u101", to_nano(95), "samir")
    check("ставка без денег отклонена", not poor_ok and poor_err == "Недостаточно средств")

    pot = game._pot
    await game._settle()
    check("после расчёта фаза reveal", game._phase == "reveal")
    end_total = await db.get_balance(101) + await db.get_balance(102)
    check("общий баланс сохранён (банк целиком у победителя)", end_total == start_total)
    check("есть запись в recent", len(game._recent) == 1)

    await game._reset()
    check("после reset фаза waiting", game._phase == "waiting")
    check("банк обнулён", game._pot == 0)
    check("новый round_id/commit готов", len(game.snapshot()["hash"]) == 64)

    await db.close(); os.unlink(tmp.name)
    print()
    print(f"Итог: {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
