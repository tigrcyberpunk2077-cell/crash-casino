"""Кривая множителя Crash во времени (чистые функции, без I/O).

Множитель растёт экспоненциально от 1.00x:

    multiplier(t) = exp(GROWTH * t)

Чем дольше игрок не забирает выигрыш, тем выше множитель — но раунд крашится
в заранее определённой (provably-fair) точке. Забрал до краша → выигрыш =
ставка * множитель. Не успел → ставка сгорает.
"""

from __future__ import annotations

import math

# Скорость роста множителя. 0.12 => ~6с до 2x, ~19с до 10x.
DEFAULT_GROWTH = 0.12


def multiplier_at(elapsed: float, growth: float = DEFAULT_GROWTH) -> float:
    """Множитель через ``elapsed`` секунд после старта раунда."""
    if elapsed <= 0:
        return 1.00
    return math.exp(growth * elapsed)


def elapsed_for(multiplier: float, growth: float = DEFAULT_GROWTH) -> float:
    """Сколько секунд нужно, чтобы множитель достиг ``multiplier``."""
    if multiplier <= 1.0:
        return 0.0
    return math.log(multiplier) / growth


def round_duration(crash_pt: float, growth: float = DEFAULT_GROWTH) -> float:
    """Полная длительность раунда до краша, секунды."""
    return elapsed_for(crash_pt, growth)


def format_multiplier(multiplier: float) -> str:
    """Отображение множителя: 1.00x, 12.34x."""
    return f"{multiplier:.2f}x"
