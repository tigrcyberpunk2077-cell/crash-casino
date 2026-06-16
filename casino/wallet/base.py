"""Абстракция кошелька: faucet (по умолчанию) и реальный TON testnet."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Optional


@dataclass
class WithdrawResult:
    ok: bool
    message: str
    tx_hash: Optional[str] = None


class WalletProvider(abc.ABC):
    """Интерфейс источника тестовых монет."""

    #: Поддерживает ли провайдер реальные on-chain операции.
    supports_onchain: bool = False
    name: str = "base"

    @abc.abstractmethod
    async def start(self, bot) -> None:
        """Инициализация (например, запуск воркера слежения за депозитами)."""

    @abc.abstractmethod
    async def stop(self) -> None:
        ...

    @abc.abstractmethod
    async def deposit_instructions(self, user_id: int) -> str:
        """Текст: как пополнить баланс."""

    @abc.abstractmethod
    async def withdraw(self, user_id: int, address: str, amount_nano: int) -> WithdrawResult:
        """Вывести amount_nano на адрес. Списание баланса делает вызывающий код."""
