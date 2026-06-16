"""Работа с суммами в наименьших единицах (nanoTON).

Балансы хранятся в БД как целые nanoTON (1 TON = 1e9 nano), чтобы избежать
ошибок округления float. Для отображения и ввода конвертируем в TON.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Optional

DECIMALS = 9
ONE_TON = 10 ** DECIMALS


def to_nano(amount_ton) -> int:
    """TON (число/строка) -> целые nanoTON."""
    return int((Decimal(str(amount_ton)) * ONE_TON).to_integral_value(rounding=ROUND_DOWN))


def from_nano(nano: int) -> Decimal:
    """nanoTON -> Decimal TON."""
    return (Decimal(nano) / ONE_TON).quantize(Decimal("0.000000001"))


def parse_amount(text: str) -> Optional[int]:
    """Парсинг пользовательского ввода суммы в nanoTON. None если невалидно/<=0."""
    try:
        value = Decimal(text.replace(",", ".").strip())
    except (InvalidOperation, AttributeError):
        return None
    if value <= 0:
        return None
    return to_nano(value)


def format_ton(nano: int) -> str:
    """Красивое отображение: убираем лишние нули, минимум 2 знака."""
    value = from_nano(nano).normalize()
    text = f"{value:.9f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".00"
    return f"{text} tTON"
