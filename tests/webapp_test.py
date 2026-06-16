"""Тесты серверной логики Mini App: стор раундов Crash и валидация initData.

Запуск: python3 tests/webapp_test.py  (нужен установленный aiohttp/aiogram-стек)
"""

import asyncio
import hashlib
import hmac
import os
import sys
import tempfile
import time
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from casino.db import Database
from casino.units import to_nano
from casino.webapp.auth import validate_init_data
from casino.webapp.crash_session import WebCrashStore

_passed = _failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1; print(f"  ok   {name}")
    else:
        _failed += 1; print(f"  FAIL {name}")


def make_init_data(bot_token, user_id=42):
    """Собирает валидно подписанный initData как это делает Telegram."""
    params = {"auth_date": str(int(time.time())), "user": f'{{"id":{user_id},"username":"tester"}}'}
    dcs = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(params)


async def main():
    print("auth (initData):")
    token = "123456:ABCfaketokenfaketokenfaketoken"
    good = make_init_data(token, 42)
    user = validate_init_data(good, token)
    check("валидный initData принят", user is not None and user["id"] == 42)
    check("чужой токен отклонён", validate_init_data(good, "999:other") is None)
    check("подделка hash отклонена", validate_init_data(good[:-4] + "0000", token) is None)
    check("пустой initData -> None", validate_init_data("", token) is None)

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    db = Database(tmp.name); await db.connect()

    print("crash store:")
    # growth большой -> раунды быстрые; min/max широкие
    store = WebCrashStore(db, min_bet=to_nano(0.1), max_bet=to_nano(100), growth=1.0)
    uid = 7
    await db.get_or_create_user(uid, "tester")
    await db.credit(uid, to_nano(100), "faucet")

    # ставка списывает баланс
    rnd, err = await store.place_bet(uid, to_nano(10))
    check("ставка принята", err is None and rnd is not None)
    check("баланс списан до 90", await db.get_balance(uid) == to_nano(90))
    check("commitment-хэш есть", len(rnd.server_seed_hash) == 64)
    check("второй раунд запрещён", (await store.place_bet(uid, to_nano(5)))[1] is not None)

    # моментальный cashout (множитель ~1.0x) -> выигрыш, баланс восстановлен ~до 100
    s = await store.cashout(uid)
    check("cashout вернул settlement", s is not None and s.outcome == "win")
    check("раунд снят с активных", store.active_round(uid) is None)
    check("баланс вырос после выигрыша (>90)", await db.get_balance(uid) > to_nano(90))
    check("повторный cashout -> None", await store.cashout(uid) is None)

    # принудительный краш: ставим, ждём прохождения crash_time
    store2 = WebCrashStore(db, min_bet=to_nano(0.1), max_bet=to_nano(100), growth=8.0)
    rnd2, _ = await store2.place_bet(uid, to_nano(10))
    bal_mid = await db.get_balance(uid)
    # ждём, пока время краша точно пройдёт
    while not rnd2.is_crashed():
        await asyncio.sleep(0.02)
    s2 = await store2.settle_if_crashed(uid)
    check("settle_if_crashed -> lose", s2 is not None and s2.outcome == "lose")
    check("баланс не вырос при крахе", await db.get_balance(uid) == bal_mid)

    # недостаточно средств
    poor = 8
    await db.get_or_create_user(poor, "poor")
    check("ставка без денег отклонена", (await store.place_bet(poor, to_nano(5)))[1] == "Недостаточно средств")
    # вне диапазона
    await db.credit(poor, to_nano(1000), "faucet")
    check("слишком большая ставка отклонена", (await store.place_bet(poor, to_nano(999)))[1] is not None)

    await db.close(); os.unlink(tmp.name)
    print()
    print(f"Итог: {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
