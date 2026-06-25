"""Тесты движка «Ночи 11A» (мафия): раздача ролей, ночь/день, победа, полная партия.

Запуск: python3 tests/mafia_test.py
"""

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from casino.webapp.mafia import (CIVILIAN, DETECTIVE, DOCTOR, MAFIA, MafiaRoom,
                                  roles_for, _most_common)

_passed = _failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1; print(f"  ok   {name}")
    else:
        _failed += 1; print(f"  FAIL {name}")


def force(room):
    room.phase_ends = time.monotonic() - 1


print("раскладка ролей:")
r6 = roles_for(6)
check("6 игроков: 1 мафия", r6.count(MAFIA) == 1)
check("6 игроков: есть доктор и комиссар", DOCTOR in r6 and DETECTIVE in r6)
check("6 игроков: всего 6 ролей", len(r6) == 6)
check("12 игроков: 3 мафии", roles_for(12).count(MAFIA) == 3)
check("_most_common берёт частое", _most_common([1, 2, 2, 3]) == 2)
check("_most_common пусто -> None", _most_common([]) is None)

print("ночь — убийство и лечение:")
room = MafiaRoom(code="T", host_id=1)
for i in range(1, 7):
    room.add_player(i, f"p{i}", bot=False)
# назначим роли вручную
room.players[1].role = MAFIA
room.players[2].role = DOCTOR
for i in range(3, 7):
    room.players[i].role = CIVILIAN
room.phase = "night"
room.set_night_target(1, 3)   # мафия бьёт p3
room.set_night_target(2, 4)   # доктор лечит p4 (не того)
room._resolve_night()
check("незащищённую жертву убили", room.players[3].alive is False)
check("остальные живы", room.players[5].alive and room.players[6].alive)

room2 = MafiaRoom(code="T2", host_id=1)
for i in range(1, 7):
    room2.add_player(i, f"p{i}")
room2.players[1].role = MAFIA; room2.players[2].role = DOCTOR
for i in range(3, 7):
    room2.players[i].role = CIVILIAN
room2.phase = "night"
room2.set_night_target(1, 3)
room2.set_night_target(2, 3)   # доктор лечит того же
room2._resolve_night()
check("доктор спас жертву", room2.players[3].alive is True)

print("день — голосование выгоняет:")
room2.phase = "day"
for i in [1, 2, 4, 5]:
    room2.set_vote(i, 6)       # большинство за p6
room2._resolve_day()
check("выгнали игрока с большинством голосов", room2.players[6].alive is False)

print("активности в локациях:")
ra = MafiaRoom(code="A", host_id=1)
for i in range(1, 5):
    ra.add_player(i, f"p{i}")
ra.players[1].house = "bar"
ra.phase = "night"
check("активность даёт результат", ra.do_activity(1) is True and ra.players[1].activity_result != "")
check("вторая активность за ночь отклонена", ra.do_activity(1) is False)
check("без локации активности нет", ra.do_activity(2) is False)

print("победа:")
rw = MafiaRoom(code="W", host_id=1)
for i in range(1, 5):
    rw.add_player(i, f"p{i}")
rw.players[1].role = MAFIA
for i in range(2, 5):
    rw.players[i].role = CIVILIAN
rw.players[1].alive = False
check("мафия выбита -> город побеждает", rw._check_winner() == "city")
rw.players[1].alive = True
for i in (2, 3):
    rw.players[i].alive = False
check("мафия >= город -> мафия побеждает", rw._check_winner() == "mafia")

print("полная партия с ботами (терминируется, есть победитель):")
random.seed(7)
full = MafiaRoom(code="F", host_id=100, night_sec=30, day_sec=60)
full.add_player(100, "Хост")
full.add_bots(6)
check("в комнате 7 участников", len(full.players) == 7)
check("старт удался", full.start() is True)
check("после старта — фаза город (выбор дома)", full.phase == "city")
roles_assigned = [p.role for p in full.players.values()]
check("роли розданы (есть мафия)", MAFIA in roles_assigned)
steps = 0
while full.phase != "ended" and steps < 100:
    force(full)
    full.tick()
    steps += 1
check("партия завершилась", full.phase == "ended")
check("есть победитель", full.winner in ("city", "mafia"))
check("не больше 7 ночей", full.night <= 7)

print()
print(f"Итог: {_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
