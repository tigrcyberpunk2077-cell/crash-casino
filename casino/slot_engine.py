"""Движок слота «Дикий Запад» — ways-слот с каскадами и растущим множителем.

Механика (как в Wanted-подобных слотах):
- Сетка 5 барабанов × 4 ряда, выплаты по «ways» (888 ways при 4 рядах ≈ 4^5 неточно,
  но считаем все совпадения слева направо).
- Выигрыш = ценность символа × число «ways» × текущий множитель.
- После КАЖДОГО выигрыша множитель удваивается (x1→x2→x4… до x1024).
- Выигравшие символы взрываются, остальные падают, сверху досыпаются новые (каскад),
  пока есть выигрыши.
- 3+ скаттера запускают фриспины: там множитель НЕ сбрасывается между спинами.

Честность: вся раздача детерминирована из HMAC(server_seed, "client_seed:nonce"),
поэтому результат проверяем и не подделывается.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Dict, List, Optional, Tuple

REELS = 5
ROWS = 3
MULT_CAP = 128
MAX_WIN_CAP = 5000.0     # потолок выигрыша за раздачу, ×ставки (как в реальных слотах)
PAY_SCALE = 0.71         # общий регулятор RTP (подобран тестом -> ~0.94)
BUY_COST = 60.0          # стоимость Feature Buy в ставках
FREE_SPINS = {3: 8, 4: 12, 5: 20}

# id символа -> (вес в генерации, {кол-во: выплата ×ставки за 1 way})
PAYING = ["J", "Q", "K", "A", "H3", "H2", "H1"]
WILD = "W"
SCATTER = "S"

WEIGHTS: Dict[str, int] = {
    "J": 30, "Q": 28, "K": 24, "A": 20,
    "H3": 13, "H2": 9, "H1": 6,
    WILD: 5, SCATTER: 3,
}
PAYTABLE: Dict[str, Dict[int, float]] = {
    "J":  {3: 0.04, 4: 0.10, 5: 0.20},
    "Q":  {3: 0.04, 4: 0.10, 5: 0.20},
    "K":  {3: 0.06, 4: 0.15, 5: 0.30},
    "A":  {3: 0.08, 4: 0.20, 5: 0.40},
    "H3": {3: 0.15, 4: 0.40, 5: 0.80},
    "H2": {3: 0.25, 4: 0.60, 5: 1.30},
    "H1": {3: 0.40, 4: 1.00, 5: 2.20},
}


class Rng:
    """Портируемый xorshift128, сид из HMAC-хэша (детерминирован и проверяем)."""

    def __init__(self, hexdigest: str):
        s = []
        for i in range(4):
            chunk = hexdigest[i * 8:(i + 1) * 8] or "1"
            s.append((int(chunk, 16) & 0xFFFFFFFF) or 0x9E3779B9)
        self.s = s

    def next_u32(self) -> int:
        s = self.s
        t = s[3] & 0xFFFFFFFF
        t ^= (t << 11) & 0xFFFFFFFF
        t ^= t >> 8
        s[3] = s[2]; s[2] = s[1]; s[1] = s[0]
        w = s[0]
        w ^= w >> 19
        s[0] = (t ^ w) & 0xFFFFFFFF
        return s[0]

    def random(self) -> float:
        return self.next_u32() / 0x100000000

    def weighted(self, items: List[str], weights: List[int]) -> str:
        total = sum(weights)
        r = self.random() * total
        acc = 0
        for it, w in zip(items, weights):
            acc += w
            if r < acc:
                return it
        return items[-1]


_SYMS = list(WEIGHTS.keys())
_WS = [WEIGHTS[s] for s in _SYMS]


def rng_from(server_seed: str, client_seed: str, nonce: int) -> Rng:
    msg = f"{client_seed}:{nonce}".encode()
    digest = hmac.new(server_seed.encode(), msg, hashlib.sha256).hexdigest()
    return Rng(digest)


def _draw(rng: Rng) -> str:
    return rng.weighted(_SYMS, _WS)


def random_grid(rng: Rng) -> List[List[str]]:
    return [[_draw(rng) for _ in range(ROWS)] for _ in range(REELS)]


def count_scatter(grid: List[List[str]]) -> int:
    return sum(cell == SCATTER for reel in grid for cell in reel)


def evaluate(grid: List[List[str]]) -> List[dict]:
    """Все выигрыши по ways (символы слева направо, минимум 3 барабана)."""
    wins = []
    for sym in PAYING:
        counts = []
        positions: List[List[Tuple[int, int]]] = []
        has_real = []
        for reel in range(REELS):
            cells = [r for r in range(ROWS) if grid[reel][r] == sym or grid[reel][r] == WILD]
            if not cells:
                break
            counts.append(len(cells))
            positions.append([(reel, r) for r in cells])
            has_real.append(any(grid[reel][r] == sym for r in cells))
        n = len(counts)
        if n < 3:
            continue
        # должен быть хотя бы один «настоящий» символ (не только вайлды).
        if not any(has_real[:n]):
            continue
        ways = 1
        for c in counts:
            ways *= c
        amount = PAYTABLE[sym][n] * ways * PAY_SCALE
        pos = [p for sub in positions for p in sub]
        wins.append({"sym": sym, "reels": n, "ways": ways, "amount": amount, "pos": pos})
    return wins


def cascade(grid: List[List[str]], wins: List[dict], rng: Rng) -> List[List[str]]:
    """Убираем выигравшие символы, остальные падают, сверху новые."""
    dead = set()
    for w in wins:
        for p in w["pos"]:
            dead.add(p)
    new = []
    for reel in range(REELS):
        kept = [grid[reel][r] for r in range(ROWS) if (reel, r) not in dead]
        need = ROWS - len(kept)
        col = [_draw(rng) for _ in range(need)] + kept  # новые сверху
        new.append(col)
    return new


def _play_round(rng: Rng, start_mult: int) -> Tuple[List[dict], float, int, int]:
    """Один спин с каскадами. Возвращает (кадры, выплата×ставки, скаттеры, конечный mult)."""
    grid = random_grid(rng)
    scatters = count_scatter(grid)
    mult = start_mult
    pay = 0.0
    frames = []
    while True:
        wins = evaluate(grid)
        win_units = sum(w["amount"] for w in wins)
        step_pay = win_units * mult
        frames.append({
            "grid": [col[:] for col in grid],
            "wins": wins,
            "mult": mult,
            "win": round(step_pay, 6),
        })
        if not wins:
            break
        pay += step_pay
        mult = min(mult * 2, MULT_CAP)
        grid = cascade(grid, wins, rng)
    return frames, pay, scatters, mult


def play(server_seed: str, client_seed: str, nonce: int) -> dict:
    """Полная раздача: базовый спин (+ фриспины при 3+ скаттерах)."""
    rng = rng_from(server_seed, client_seed, nonce)
    rounds = []
    total = 0.0

    frames, pay, scatters, _ = _play_round(rng, start_mult=1)
    rounds.append({"type": "base", "frames": frames})
    total += pay

    free = FREE_SPINS.get(min(scatters, 5), 0) if scatters >= 3 else 0
    if free:
        mult = 1  # в фриспинах множитель НЕ сбрасывается между спинами
        for _ in range(free):
            frames, pay, _sc, mult = _play_round(rng, start_mult=mult)
            rounds.append({"type": "free", "frames": frames})
            total += pay

    total = min(total, MAX_WIN_CAP)
    return {"rounds": rounds, "total": round(total, 6), "scatters": scatters,
            "free_spins": free}


def play_bonus(server_seed: str, client_seed: str, nonce: int, spins: int = 10) -> dict:
    """Feature Buy: сразу фриспины (с персистентным множителем)."""
    rng = rng_from(server_seed, client_seed, nonce)
    rounds = []
    total = 0.0
    mult = 1
    for _ in range(spins):
        frames, pay, _sc, mult = _play_round(rng, start_mult=mult)
        rounds.append({"type": "free", "frames": frames})
        total += pay
    total = min(total, MAX_WIN_CAP)
    return {"rounds": rounds, "total": round(total, 6), "scatters": 0, "free_spins": spins}
