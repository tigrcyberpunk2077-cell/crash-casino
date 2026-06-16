"""Инлайн-клавиатуры."""

from __future__ import annotations

from typing import List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Быстрые ставки (в tTON)
QUICK_BETS: List[float] = [0.5, 1, 5, 10, 25]


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Играть в Crash", callback_data="menu:crash")
    kb.button(text="💰 Баланс", callback_data="menu:balance")
    kb.button(text="🪙 Депозит", callback_data="menu:deposit")
    kb.button(text="🏧 Вывод", callback_data="menu:withdraw")
    kb.button(text="🎲 Честность (Provably Fair)", callback_data="menu:fair")
    kb.button(text="ℹ️ Помощь", callback_data="menu:help")
    kb.adjust(1, 2, 1, 1)
    return kb.as_markup()


def bet_menu(balance_text: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for b in QUICK_BETS:
        kb.button(text=f"{b:g} tTON", callback_data=f"bet:{b}")
    kb.button(text="✏️ Своя ставка", callback_data="bet:custom")
    kb.button(text="⬅️ В меню", callback_data="menu:home")
    kb.adjust(3, 2, 1, 1)
    return kb.as_markup()


def cashout_kb(game_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="💸 ЗАБРАТЬ", callback_data=f"cashout:{game_id}")
        ]]
    )


def play_again_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔁 Ещё раз", callback_data="menu:crash")
    kb.button(text="⬅️ В меню", callback_data="menu:home")
    kb.adjust(2)
    return kb.as_markup()


def back_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В меню", callback_data="menu:home")
    return kb.as_markup()


def deposit_kb(provider: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if provider == "faucet":
        kb.button(text="🚰 Получить из крана", callback_data="faucet:claim")
    kb.button(text="⬅️ В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()
