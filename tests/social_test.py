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

    await db.close(); os.unlink(tmp.name)
    print()
    print(f"Итог: {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
