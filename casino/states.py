"""FSM-состояния."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class CrashStates(StatesGroup):
    waiting_bet = State()        # ждём сумму ставки (своё значение)


class WithdrawStates(StatesGroup):
    waiting_address = State()
    waiting_amount = State()


class SeedStates(StatesGroup):
    waiting_seed = State()       # ждём новый client_seed
