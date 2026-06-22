"""Тесты соцфич и напоминаний: рефералы (привязка один раз, без самоприглашения),
счётчик, активность и выборка «кому напомнить».

Запуск: python3 tests/social_test.py
"""

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from casino.db import Database

_passed = _failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1; print(f"  ok   {name}")
    else:
        _failed += 1; print(f"  FAIL {name}")


async def main():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    db = Database(tmp.name); await db.connect()

    print("активность:")
    a = await db.get_or_create_user(100, "A")
    await db.get_or_create_user(200, "B")
    await db.get_or_create_user(300, "C")
    check("last_active проставлен при создании", int(a["last_active"]) > 0)

    print("рефералы:")
    check("привязка реферера B->A", await db.set_referrer(200, 100) is True)
    check("повторная привязка отклонена", await db.set_referrer(200, 100) is False)
    check("самоприглашение отклонено", await db.set_referrer(100, 100) is False)
    check("привязка C->A", await db.set_referrer(300, 100) is True)
    check("у A двое приглашённых", await db.count_referrals(100) == 2)
    check("у B никого", await db.count_referrals(200) == 0)

    print("напоминания:")
    old = int(time.time()) - 100000
    await db._exec("UPDATE users SET last_active=? WHERE id=?", (old, 100))     # A давно неактивен
    await db.get_or_create_user(-5, "guest")                                    # гость
    await db._exec("UPDATE users SET last_active=? WHERE id=?", (old, -5))
    due = await db.due_for_remind(3600, 10)
    check("A попал в напоминания", 100 in due)
    check("активные B/C не попали", 200 not in due and 300 not in due)
    check("гость (id<0) исключён", -5 not in due)

    await db.mark_reminded([100])
    due2 = await db.due_for_remind(3600, 10)
    check("после отметки A больше не напоминаем", 100 not in due2)

    print("статистика:")
    await db.credit(200, 1000, "faucet")
    await db.try_debit(200, 300, "bet", "slot")
    await db.try_debit(200, 200, "bet", "crash")
    ov = await db.stats_overview(50)
    check("в сводке учтены ставки (2)", ov["betCount"] == 2)
    check("оборот = 500", ov["totalBet"] == 500)
    check("игроки в списке есть", len(ov["players"]) >= 3)
    b = next((p for p in ov["players"] if p["id"] == 200), None)
    check("у игрока B 2 ставки и оборот 500", b and b["bets"] == 2 and b["wagered"] == 500)

    await db.close(); os.unlink(tmp.name)
    print()
    print(f"Итог: {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
