"""Фабрика провайдера кошелька по конфигу."""

from __future__ import annotations

from ..config import Config
from ..db import Database
from .base import WalletProvider, WithdrawResult
from .faucet import FaucetWallet

__all__ = ["WalletProvider", "WithdrawResult", "build_wallet"]


def build_wallet(config: Config, db: Database) -> WalletProvider:
    if config.wallet_provider == "ton":
        if not config.ton_mnemonic:
            raise RuntimeError(
                "WALLET_PROVIDER=ton, но не задан TON_MNEMONIC (сид-фраза горячего кошелька)."
            )
        from .ton import TonTestnetWallet  # ленивый импорт (требует tonutils)

        return TonTestnetWallet(
            mnemonic=config.ton_mnemonic,
            api_key=config.ton_api_key,
            db=db,
            min_withdraw=config.ton_min_withdraw,
        )
    return FaucetWallet(faucet_amount=config.faucet_amount)
