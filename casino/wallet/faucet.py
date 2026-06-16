"""Faucet-провайдер: тестовые монеты выдаются командой /faucet, без блокчейна.

Режим по умолчанию — бот работает сразу, без настройки сети. Идеален для
изучения игровой логики. Реальных переводов нет, поэтому вывод недоступен.
"""

from __future__ import annotations

from .base import WalletProvider, WithdrawResult


class FaucetWallet(WalletProvider):
    supports_onchain = False
    name = "faucet"

    def __init__(self, faucet_amount: float):
        self._amount = faucet_amount

    async def start(self, bot) -> None:  # noqa: D102
        return None

    async def stop(self) -> None:  # noqa: D102
        return None

    async def deposit_instructions(self, user_id: int) -> str:
        return (
            "🚰 <b>Тестовый кран (faucet)</b>\n\n"
            f"Это демо-режим на виртуальных монетах <b>tTON</b> (без реальной ценности).\n"
            f"Нажми «Получить из крана» и тебе начислят <b>{self._amount:g} tTON</b>.\n\n"
            "Чтобы подключить реальные депозиты из тестовой сети TON, переключи "
            "<code>WALLET_PROVIDER=ton</code> в .env (см. README)."
        )

    async def withdraw(self, user_id: int, address: str, amount_nano: int) -> WithdrawResult:
        return WithdrawResult(
            ok=False,
            message=(
                "В демо-режиме (faucet) вывод недоступен — это виртуальные фишки.\n"
                "Включи провайдер TON testnet, чтобы выводить тестовые монеты on-chain."
            ),
        )
