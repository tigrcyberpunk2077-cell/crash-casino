"""Тесты ядра игры — запуск без зависимостей: python3 tests/run_tests.py

Проверяем provably-fair, кривую Crash и денежные единицы.
"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from casino import crash_engine as ce
from casino import provably_fair as pf
from casino import units

_passed = 0
_failed = 0


def check(name, condition):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ok   {name}")
    else:
        _failed += 1
        print(f"  FAIL {name}")


print("provably_fair:")
seed = pf.generate_server_seed()
check("server_seed длиной 64 hex", len(seed) == 64)
check("хэш детерминирован", pf.hash_server_seed(seed) == pf.hash_server_seed(seed))

cp = pf.crash_point(seed, "player1", 1)
check("crash_point >= 1.00", cp >= 1.00)
check("crash_point детерминирован", cp == pf.crash_point(seed, "player1", 1))
check("разный nonce -> другой раунд",
      pf.crash_point(seed, "player1", 1) != pf.crash_point(seed, "player1", 2)
      or pf.crash_point(seed, "player1", 3) != pf.crash_point(seed, "player1", 4))

# verify() — честный раунд проходит, подделка нет.
h = pf.hash_server_seed(seed)
check("verify честного раунда", pf.verify(seed, h, "player1", 1, cp))
check("verify ловит подделку crash", not pf.verify(seed, h, "player1", 1, cp + 5))
check("verify ловит подделку seed", not pf.verify(seed, "deadbeef", "player1", 1, cp))

# Распределение: house edge ~1% мгновенных крашей, медиана около 2x.
N = 20000
points = [pf.crash_point(seed, "c", n) for n in range(N)]
instant = sum(1 for p in points if p <= 1.00)
share = instant / N
check(f"house edge ~1% (факт {share:.3%})", 0.006 < share < 0.014)
above_2x = sum(1 for p in points if p >= 2.0) / N
check(f"доля >=2x около 49% (факт {above_2x:.1%})", 0.44 < above_2x < 0.54)

print("crash_engine:")
check("multiplier_at(0) == 1.00", ce.multiplier_at(0) == 1.00)
check("множитель растёт", ce.multiplier_at(5) > ce.multiplier_at(1) > 1.0)
# Обратимость: elapsed_for и multiplier_at согласованы.
target = 3.5
t = ce.elapsed_for(target)
check("elapsed_for/multiplier_at согласованы", abs(ce.multiplier_at(t) - target) < 1e-6)
check("round_duration > 0 для 2x", ce.round_duration(2.0) > 0)
check("format 1.0 -> '1.00x'", ce.format_multiplier(1.0) == "1.00x")

print("units:")
check("to_nano(1) == 1e9", units.to_nano(1) == 1_000_000_000)
check("to_nano('0.5') == 5e8", units.to_nano("0.5") == 500_000_000)
check("round-trip", units.to_nano(units.from_nano(123456789)) == 123456789)
check("parse '2.5'", units.parse_amount("2.5") == units.to_nano("2.5"))
check("parse запятая '1,5'", units.parse_amount("1,5") == units.to_nano("1.5"))
check("parse отрицательное -> None", units.parse_amount("-3") is None)
check("parse мусор -> None", units.parse_amount("abc") is None)
check("parse ноль -> None", units.parse_amount("0") is None)
check("format_ton(1e9) содержит tTON", "tTON" in units.format_ton(1_000_000_000))

print()
print(f"Итог: {_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
