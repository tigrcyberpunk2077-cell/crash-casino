"""Серверный стор раундов Crash для Mini App.

Сервер — единственный источник правды: точка краша определяется при ставке
(provably-fair) и НЕ раскрывается клиенту до конца раунда, поэтому подделать
множитель из браузера невозможно. Множитель — функция от прошедшего времени.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ..crash_engine import multiplier_at, round_duration
from ..db import Database
from ..provably_fair import crash_point, generate_server_seed, hash_server_seed


@dataclass
class WebRound:
    user_id: int
    round_id: str
    bet: int
    crash_point: float
    crash_time: float          # секунд от старта до краша
    growth: float
    server_seed: str
    server_seed_hash: str
    client_seed: str
    nonce: int
    start: float               # time.monotonic() старта
    settled: bool = False

    def elapsed(self) -> float:
        return time.monotonic() - self.start

    def multiplier_now(self) -> float:
        return multiplier_at(self.elapsed(), self.growth)

    def is_crashed(self) -> bool:
        return self.elapsed() >= self.crash_time


@dataclass
class Settlement:
    outcome: str               # "win" | "lose"
    multiplier: float          # на каком множителе зафиксировано
    crash_point: float
    payout: int
    balance: int
    server_seed: str
    server_seed_hash: str
    client_seed: str
    nonce: int


class WebCrashStore:
    def __init__(self, db: Database, min_bet: int, max_bet: int, growth: float):
        self._db = db
        self._min = min_bet
        self._max = max_bet
        self._growth = growth
        self._rounds: Dict[int, WebRound] = {}
        self._lock = asyncio.Lock()

    def active_round(self, user_id: int) -> Optional[WebRound]:
        return self._rounds.get(user_id)

    async def place_bet(self, user_id: int, bet_nano: int) -> Tuple[Optional[WebRound], Optional[str]]:
        async with self._lock:
            if user_id in self._rounds:
                return None, "Раунд уже идёт"
            if bet_nano < self._min or bet_nano > self._max:
                return None, "Ставка вне допустимого диапазона"
            new_balance = await self._db.try_debit(user_id, bet_nano, "bet", "crash-webapp")
            if new_balance is None:
                return None, "Недостаточно средств"

            user = await self._db.get_user(user_id)
            client_seed = user["client_seed"]
            nonce = await self._db.next_nonce(user_id)
            seed = generate_server_seed()
            cp = crash_point(seed, client_seed, nonce)
            rnd = WebRound(
                user_id=user_id,
                round_id=uuid.uuid4().hex[:12],
                bet=bet_nano,
                crash_point=cp,
                crash_time=round_duration(cp, self._growth),
                growth=self._growth,
                server_seed=seed,
                server_seed_hash=hash_server_seed(seed),
                client_seed=client_seed,
                nonce=nonce,
                start=time.monotonic(),
            )
            self._rounds[user_id] = rnd
            return rnd, None

    async def cashout(self, user_id: int) -> Optional[Settlement]:
        """Игрок жмёт «Забрать». None если раунда нет/уже завершён."""
        async with self._lock:
            rnd = self._rounds.get(user_id)
            if rnd is None or rnd.settled:
                return None
            if rnd.is_crashed():
                return await self._finalize(rnd, "lose", rnd.crash_point)
            return await self._finalize(rnd, "win", rnd.multiplier_now())

    async def settle_if_crashed(self, user_id: int) -> Optional[Settlement]:
        """Вызывается тикером: если время краша наступило — фиксируем проигрыш."""
        async with self._lock:
            rnd = self._rounds.get(user_id)
            if rnd is None or rnd.settled or not rnd.is_crashed():
                return None
            return await self._finalize(rnd, "lose", rnd.crash_point)

    async def abandon(self, user_id: int) -> None:
        """Игрок отключился, не забрав — фиксируем проигрыш."""
        async with self._lock:
            rnd = self._rounds.get(user_id)
            if rnd is not None and not rnd.settled:
                await self._finalize(rnd, "lose", rnd.crash_point)

    async def _finalize(self, rnd: WebRound, outcome: str, mult: float) -> Settlement:
        rnd.settled = True
        if outcome == "win":
            payout = int(rnd.bet * mult)
            balance = await self._db.credit(rnd.user_id, payout, "win", f"crash {mult:.2f}x")
            cashout_mult: Optional[float] = round(mult, 2)
        else:
            payout = 0
            balance = await self._db.get_balance(rnd.user_id)
            cashout_mult = None

        await self._db.record_round(
            user_id=rnd.user_id, bet=rnd.bet, crash_point=rnd.crash_point,
            cashout=cashout_mult, payout=payout, server_seed=rnd.server_seed,
            server_seed_hash=rnd.server_seed_hash, client_seed=rnd.client_seed,
            nonce=rnd.nonce, outcome=outcome,
        )
        self._rounds.pop(rnd.user_id, None)
        return Settlement(
            outcome=outcome, multiplier=round(mult, 2), crash_point=rnd.crash_point,
            payout=payout, balance=balance, server_seed=rnd.server_seed,
            server_seed_hash=rnd.server_seed_hash, client_seed=rnd.client_seed,
            nonce=rnd.nonce,
        )
