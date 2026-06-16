"""TON testnet провайдер (опционально).

Депозиты: пользователь отправляет tTON на горячий кошелёк бота с комментарием,
равным своему Telegram ID. Фоновый воркер опрашивает toncenter v3, находит
входящие переводы, сопоставляет комментарий с пользователем и зачисляет баланс
(c дедупликацией по хэшу транзакции).

Вывод: бот подписывает и отправляет перевод с горячего кошелька.

Требует: pip install tonutils ; переменные TON_MNEMONIC, TON_API_KEY.
Сеть — ТОЛЬКО testnet (монеты без реальной ценности).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

from ..units import format_ton, from_nano
from .base import WalletProvider, WithdrawResult

log = logging.getLogger("casino.wallet.ton")

TONCENTER_TESTNET = "https://testnet.toncenter.com/api/v3"
POLL_INTERVAL_SEC = 12


class TonTestnetWallet(WalletProvider):
    supports_onchain = True
    name = "ton-testnet"

    def __init__(self, mnemonic: str, api_key: Optional[str], db, min_withdraw: float):
        self._mnemonic = mnemonic
        self._api_key = api_key
        self._db = db
        self._min_withdraw = min_withdraw
        self._wallet = None
        self._address: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._bot = None

    async def start(self, bot) -> None:
        # Ленивая загрузка tonutils — нужна только в режиме ton.
        from tonutils.client import ToncenterV3Client
        from tonutils.wallet import WalletV4R2

        self._bot = bot
        client = ToncenterV3Client(api_key=self._api_key, is_testnet=True)
        self._wallet, _pub, _priv, _mn = WalletV4R2.from_mnemonic(
            client, self._mnemonic.split()
        )
        self._address = self._wallet.address.to_str()
        self._session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._watch_deposits())
        log.info("TON testnet кошелёк готов: %s", self._address)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self._session:
            await self._session.close()

    async def deposit_instructions(self, user_id: int) -> str:
        return (
            "🪙 <b>Депозит из TON testnet</b>\n\n"
            f"Отправь tTON на адрес кошелька бота, указав <b>комментарий</b> ровно:\n"
            f"<code>{user_id}</code>\n\n"
            f"Адрес: <code>{self._address}</code>\n\n"
            "⚠️ Сеть <b>testnet</b>. Депозит зачислится автоматически в течение минуты.\n"
            "Тестовые tTON бери у testnet-крана @testgiver_ton_bot."
        )

    async def withdraw(self, user_id: int, address: str, amount_nano: int) -> WithdrawResult:
        if self._wallet is None:
            return WithdrawResult(False, "Кошелёк не инициализирован.")
        amount_ton = from_nano(amount_nano)
        if float(amount_ton) < self._min_withdraw:
            return WithdrawResult(
                False, f"Минимальная сумма вывода: {self._min_withdraw:g} tTON."
            )
        try:
            tx_hash = await self._wallet.transfer(
                destination=address,
                amount=float(amount_ton),
                body=f"Casino withdraw #{user_id}",
            )
        except Exception as exc:  # noqa: BLE001 — показываем причину пользователю
            log.exception("Ошибка вывода")
            return WithdrawResult(False, f"Ошибка перевода: {exc}")
        return WithdrawResult(True, f"Отправлено {format_ton(amount_nano)} на {address}", tx_hash)

    # --- фоновый опрос депозитов ---

    async def _watch_deposits(self) -> None:
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — не роняем воркер на одной ошибке
                log.exception("Ошибка опроса депозитов")
            await asyncio.sleep(POLL_INTERVAL_SEC)

    async def _poll_once(self) -> None:
        assert self._session is not None and self._address is not None
        params = {"account": self._address, "limit": 50, "sort": "desc"}
        headers = {"X-API-Key": self._api_key} if self._api_key else {}
        async with self._session.get(
            f"{TONCENTER_TESTNET}/transactions", params=params, headers=headers
        ) as resp:
            if resp.status != 200:
                log.warning("toncenter %s", resp.status)
                return
            data = await resp.json()

        for tx in data.get("transactions", []):
            await self._handle_tx(tx)

    async def _handle_tx(self, tx: dict) -> None:
        in_msg = tx.get("in_msg") or {}
        value = in_msg.get("value")
        source = in_msg.get("source")
        if not value or not source:  # исходящие / служебные пропускаем
            return
        comment = self._extract_comment(in_msg)
        if comment is None:
            return
        try:
            user_id = int(comment.strip())
        except ValueError:
            return
        user = await self._db.get_user(user_id)
        if not user:
            return

        tx_hash = tx.get("hash") or in_msg.get("hash")
        if not tx_hash or await self._db.is_deposit_processed(tx_hash):
            return
        amount_nano = int(value)
        await self._db.mark_deposit_processed(tx_hash, user_id, amount_nano)
        await self._db.credit(user_id, amount_nano, "deposit", tx_hash)
        log.info("Депозит %s от %s", format_ton(amount_nano), user_id)
        if self._bot is not None:
            try:
                await self._bot.send_message(
                    user_id,
                    f"✅ Депозит зачислен: <b>{format_ton(amount_nano)}</b>",
                )
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _extract_comment(in_msg: dict) -> Optional[str]:
        """Достаёт текстовый комментарий из in_msg toncenter v3."""
        content = in_msg.get("message_content") or {}
        decoded = content.get("decoded") or {}
        if decoded.get("type") in ("text_comment", "comment"):
            return decoded.get("comment")
        return in_msg.get("comment")
