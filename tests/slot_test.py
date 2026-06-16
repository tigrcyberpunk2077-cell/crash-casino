"""Тесты слот-движка + симуляция RTP. Запуск: python3 tests/slot_test.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from casino import slot_engine as se

_p = _f = 0


def check(name, cond):
    global _p, _f
    if cond:
        _p += 1; print(f"  ok   {name}")
    else:
        _f += 1; print(f"  FAIL {name}")


print("структура:")
r = se.play("seed" * 16, "player", 1)
check("есть базовый раунд", r["rounds"] and r["rounds"][0]["type"] == "base")
g = r["rounds"][0]["frames"][0]["grid"]
check("сетка 5x4", len(g) == se.REELS and all(len(c) == se.ROWS for c in g))
check("total >= 0", r["total"] >= 0)
check("детерминизм", se.play("seed" * 16, "player", 1)["total"] == r["total"])
check("разный nonce -> другой результат",
      se.play("seed" * 16, "player", 1)["total"] != se.play("seed" * 16, "player", 7)["total"]
      or se.play("seed" * 16, "p", 2)["total"] != se.play("seed" * 16, "p", 3)["total"])

# Каскад сохраняет размер сетки
rng = se.rng_from("s" * 16, "c", 5)
grid = se.random_grid(rng)
wins = se.evaluate(grid)
if wins:
    g2 = se.cascade(grid, wins, rng)
    check("после каскада сетка та же 5x4", len(g2) == 5 and all(len(c) == 4 for c in g2))
else:
    check("после каскада сетка та же 5x4 (нет выигрыша — пропуск)", True)

# evaluate на подготовленной сетке: 3 барабана с A в одном ряду
test_grid = [["A", "J", "Q", "K"], ["A", "J", "Q", "K"], ["A", "J", "Q", "K"],
             ["J", "J", "Q", "K"], ["Q", "Q", "Q", "K"]]
ev = se.evaluate(test_grid)
syms = {w["sym"] for w in ev}
check("находит выигрыш A x3", "A" in syms)
check("находит выигрыш Q (4 барабана)", any(w["sym"] == "Q" and w["reels"] >= 4 for w in ev))

print("\nсимуляция RTP (это займёт пару секунд):")
N = 120000
total_ret = 0.0
bonus_hits = 0
max_win = 0.0
for n in range(N):
    res = se.play("rtp-seed-xyz" * 4, "sim", n)
    total_ret += res["total"]
    if res["free_spins"]:
        bonus_hits += 1
    if res["total"] > max_win:
        max_win = res["total"]
rtp = total_ret / N
print(f"  RTP = {rtp:.4f}  (хотим ~0.90–0.96)")
print(f"  частота бонуса = 1 / {N / max(bonus_hits,1):.0f} спинов")
print(f"  макс. выигрыш за спин = {max_win:.1f}x ставки")
print(f"  PAY_SCALE сейчас = {se.PAY_SCALE}")
print(f"  -> чтобы RTP=0.94, поставь PAY_SCALE = {0.94 / rtp * se.PAY_SCALE:.4f}")
check("RTP в разумных пределах (0.5–1.2)", 0.5 < rtp < 1.2)

print()
print(f"Итог: {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
