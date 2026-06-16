"""Интеграционный тест рантайма раундов Crash (нужен установленный aiogram).

Запуск: python3 tests/integration_test.py
Проверяет списание ставки, выигрышный cashout, проигрышный краш, запись раундов
и отсутствие двойного начисления — с фейковым ботом, без Telegram.
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from casino.db import Database
from casino.services.games import CrashGame, GameManager
from casino.units import to_nano

_passed = 0
_failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok   {name}")
    else:
        _failed += 1
        print(f"  FAIL {name}")


class FakeBot:
    """Минимальная заглушка: запоминает последний текст по message_id."""

    def __init__(self):
        self.last = {}
        self.sent = []

    async def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
        self.last[message_id] = text
        self.sent.append(text)


def make_game(user_id, bet, crash_point, growth, msg_id=100):
    return CrashGame(
        user_id=user_id, chat_id=1, message_id=msg_id, game_id="g1",
        bet=bet, crash_point=crash_point,
        server_seed="s" * 64, server_seed_hash="h" * 64,
        client_seed="c", nonce=1, growth=growth,
    )


async def setup_user(db, uid, balance_ton):
    await db.get_or_create_user(uid, "tester")
    await db.credit(uid, to_nano(balance_ton), "faucet")


async def main():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = Database(tmp.name)
    await db.connect()

    # === Тест 1: выигрышный cashout ===
    print("cashout (win):")
    bot = FakeBot()
    games = GameManager(bot, db)
    uid = 1001
    await setup_user(db, uid, 100)            # баланс 100 tTON
    bet = to_nano(10)
    bal_after_debit = await db.try_debit(uid, bet, "bet", "crash")
    check("ставка списана (90 tTON)", bal_after_debit == to_nano(90))

    game = make_game(uid, bet, crash_point=50.0, growth=1.0)  # не крашнется быстро
    await games.start(game)
    await asyncio.sleep(0.5)                   # множитель ~ exp(0.5) ≈ 1.65x
    win = await games.cashout(uid, "g1")
    check("cashout вернул True", win is True)
    check("игра удалена из активных", not games.is_active(uid))

    bal = await db.get_balance(uid)
    check("баланс вырос после выигрыша (> 90)", bal > to_nano(90))
    check("есть текст с 'Забрал' в сообщении", any("Забрал" in t for t in bot.sent))

    # двойной cashout не проходит
    win2 = await games.cashout(uid, "g1")
    check("повторный cashout = False", win2 is False)

    # === Тест 2: проигрышный краш ===
    print("crash (lose):")
    bot2 = FakeBot()
    games2 = GameManager(bot2, db)
    uid2 = 1002
    await setup_user(db, uid2, 100)
    bet2 = to_nano(20)
    await db.try_debit(uid2, bet2, "bet", "crash")
    bal_before = await db.get_balance(uid2)    # 80 tTON
    # growth=5 -> на первом тике (1.6s) множитель огромный, crash_point=1.01 => краш
    game2 = make_game(uid2, bet2, crash_point=1.01, growth=5.0, msg_id=200)
    game2.game_id = "g2"
    await games2.start(game2)
    await asyncio.sleep(2.0)                    # ждём первый тик
    check("игра завершилась крашем (не активна)", not games2.is_active(uid2))
    bal_after = await db.get_balance(uid2)
    check("баланс не изменился (ставка сгорела)", bal_after == bal_before)
    check("есть текст 'CRASH' в сообщении", any("CRASH" in t for t in bot2.sent))
    # поздний cashout после краша = False
    late = await games2.cashout(uid2, "g2")
    check("cashout после краша = False", late is False)

    # === Тест 3: защита от овердрафта ===
    print("overdraft:")
    uid3 = 1003
    await db.get_or_create_user(uid3, "poor")
    res = await db.try_debit(uid3, to_nano(5), "bet", "crash")
    check("списание без средств -> None", res is None)
    check("баланс остался 0", await db.get_balance(uid3) == 0)

    # === Тест 4: записи раундов в БД ===
    print("rounds persisted:")
    import aiosqlite
    async with aiosqlite.connect(tmp.name) as conn:
        conn.row_factory = aiosqlite.Row
        rows = [dict(r) for r in await (await conn.execute(
            "SELECT outcome, payout, bet FROM rounds ORDER BY id")).fetchall()]
    outcomes = [r["outcome"] for r in rows]
    check("записан win-раунд", "win" in outcomes)
    check("записан lose-раунд", "lose" in outcomes)
    win_row = next(r for r in rows if r["outcome"] == "win")
    check("payout выигрыша > ставки", win_row["payout"] > win_row["bet"])

    await db.close()
    os.unlink(tmp.name)
    print()
    print(f"Итог: {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
