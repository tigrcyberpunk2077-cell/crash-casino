"""Мультиплеер-джекпот «Забег барана».

Один общий раунд на всех подключённых игроков. Каждый игрок ставит и выбирает
роль (тема-украшение его куска поля). Чем больше суммарная ставка игрока — тем
больше его кусок поля и выше шанс. Когда таймер истёк, по полю «бежит баран»,
пастух ловит его в точке f∈[0,1) — кусок, на который попала точка, забирает
весь банк.

Provably-fair (commit-reveal): server_seed генерируется и его SHA-256 хэш
публикуется ДО приёма ставок (в фазе ожидания). Точка поимки
f = HMAC-SHA256(server_seed, round_id) — детерминирована сидом, который сервер
зафиксировал до того, как узнал распределение ставок, поэтому исход подделать
нельзя. После раунда server_seed раскрывается и любой может проверить.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..db import Database
from ..provably_fair import generate_server_seed, hash_server_seed
from ..units import format_ton

log = logging.getLogger("casino.jackpot")


def winning_fraction(server_seed: str, round_id: str) -> float:
    """Детерминированная точка поимки f ∈ [0, 1)."""
    digest = hmac.new(server_seed.encode(), round_id.encode(), hashlib.sha256).hexdigest()
    h = int(digest[:13], 16)        # 52 бита
    return h / float(2 ** 52)


def verify_fraction(server_seed: str, server_seed_hash: str, round_id: str,
                    claimed_f: float) -> bool:
    """Проверка точки поимки игроком после раскрытия server_seed."""
    if hash_server_seed(server_seed) != server_seed_hash:
        return False
    return abs(winning_fraction(server_seed, round_id) - claimed_f) < 1e-9


@dataclass
class Entry:
    user_id: int
    name: str
    role: str
    amount: int = 0           # суммарная ставка игрока в nanoTON


@dataclass
class Winner:
    name: str
    role: str
    amount_str: str


def pick_winner(order: List[Entry], f: float) -> Tuple[Optional[Entry], int]:
    """По точке f∈[0,1) и порядку кусков возвращает (победитель, общий банк)."""
    total = sum(e.amount for e in order)
    if total <= 0:
        return None, 0
    target = f * total
    acc = 0
    for e in order:
        acc += e.amount
        if target < acc:
            return e, total
    return order[-1], total       # на случай краевого f≈1


@dataclass
class _Pending:
    round_id: str
    server_seed: str
    server_seed_hash: str


class JackpotGame:
    """Общий раунд + фоновый цикл фаз. Источник правды — сервер."""

    def __init__(self, db: Database, *, min_bet: int, max_bet: int,
                 round_seconds: int = 30, reveal_seconds: float = 10.5):
        self._db = db
        self._min = min_bet
        self._max = max_bet
        self.ROUND_SEC = round_seconds
        self.REVEAL_SEC = reveal_seconds

        self._lock = asyncio.Lock()
        self._subs: set = set()                    # подписанные WebSocketResponse
        self._bets: Dict[int, Entry] = {}          # uid -> Entry (порядок = очередь входа)
        self._pot = 0
        self._phase = "waiting"                    # waiting | collecting | reveal
        self._ends_at = 0.0                        # time.monotonic() конца сбора
        self._recent: List[Winner] = []
        self._task: Optional[asyncio.Task] = None
        self._pending = self._new_pending()

    @staticmethod
    def _new_pending() -> _Pending:
        seed = generate_server_seed()
        return _Pending(uuid.uuid4().hex[:12], seed, hash_server_seed(seed))

    # --- подписка ws ---

    def add_sub(self, ws) -> None:
        self._subs.add(ws)

    def remove_sub(self, ws) -> None:
        self._subs.discard(ws)

    # --- жизненный цикл фонового цикла ---

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    # --- ставка ---

    async def place_bet(self, user_id: int, name: str, amount: int, role: str
                        ) -> Tuple[bool, Optional[str], int]:
        """Ставит/докидывает. Возвращает (ok, ошибка, новый_баланс)."""
        async with self._lock:
            if self._phase == "reveal":
                return False, "Раунд завершается — подожди следующий", await self._db.get_balance(user_id)
            if amount < self._min or amount > self._max:
                return False, "Ставка вне допустимого диапазона", await self._db.get_balance(user_id)
            new_balance = await self._db.try_debit(user_id, amount, "bet", "race")
            if new_balance is None:
                return False, "Недостаточно средств", await self._db.get_balance(user_id)

            entry = self._bets.get(user_id)
            if entry is None:
                entry = Entry(user_id=user_id, name=name, role=role)
                self._bets[user_id] = entry
            entry.amount += amount
            entry.role = role or entry.role
            entry.name = name or entry.name
            self._pot += amount

            if self._phase == "waiting":
                self._phase = "collecting"
                self._ends_at = time.monotonic() + self.ROUND_SEC

        await self._broadcast(self.snapshot())
        return True, None, new_balance

    # --- снимок состояния ---

    def _ordered(self) -> List[Entry]:
        return list(self._bets.values())

    def snapshot(self) -> dict:
        order = self._ordered()
        total = self._pot or 1
        ends_in = max(0.0, self._ends_at - time.monotonic()) if self._phase == "collecting" else 0.0
        return {
            "type": "jackpot",
            "phase": self._phase,
            "roundId": self._pending.round_id,
            "hash": self._pending.server_seed_hash,
            "endsIn": round(ends_in, 1),
            "roundSec": self.ROUND_SEC,
            "pot": self._pot,
            "potStr": format_ton(self._pot),
            "players": [
                {
                    "id": e.user_id, "name": e.name, "role": e.role,
                    "amount": e.amount, "amountStr": format_ton(e.amount),
                    "pct": round(100.0 * e.amount / total, 2),
                }
                for e in order
            ],
            "minBet": self._min, "maxBet": self._max,
            "recent": [{"name": w.name, "role": w.role, "amountStr": w.amount_str} for w in self._recent],
        }

    # --- фоновый цикл фаз ---

    async def _run(self) -> None:
        last_tick = 0.0
        while True:
            try:
                await asyncio.sleep(0.2)
                now = time.monotonic()
                settle = False
                async with self._lock:
                    if self._phase == "collecting" and now >= self._ends_at:
                        settle = True
                if settle:
                    await self._settle()
                    await asyncio.sleep(self.REVEAL_SEC)
                    await self._reset()
                elif self._phase == "collecting" and now - last_tick >= 1.0:
                    last_tick = now
                    await self._broadcast({
                        "type": "jackpot_timer",
                        "endsIn": round(max(0.0, self._ends_at - now), 1),
                    })
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.debug("jackpot loop error", exc_info=True)

    async def _settle(self) -> None:
        async with self._lock:
            if self._phase != "collecting":
                return
            self._phase = "reveal"
            order = self._ordered()
            seed = self._pending.server_seed
            seed_hash = self._pending.server_seed_hash
            round_id = self._pending.round_id
            f = winning_fraction(seed, round_id)
            winner, total = pick_winner(order, f)
            if winner is None:
                return
            balance = await self._db.credit(winner.user_id, total, "win", "race")
            self._recent.insert(0, Winner(winner.name, winner.role, format_ton(total)))
            self._recent = self._recent[:8]
            total_for_pct = total or 1
            payload = {
                "type": "jackpot_reveal",
                "roundId": round_id,
                "f": f,
                "winnerId": winner.user_id,
                "winnerName": winner.name,
                "winnerRole": winner.role,
                "pot": total, "potStr": format_ton(total),
                "payoutStr": format_ton(total),
                "serverSeed": seed, "hash": seed_hash,
                "players": [
                    {
                        "id": e.user_id, "name": e.name, "role": e.role,
                        "amount": e.amount, "amountStr": format_ton(e.amount),
                        "pct": round(100.0 * e.amount / total_for_pct, 2),
                    }
                    for e in order
                ],
            }
        await self._broadcast(payload)
        # Победителю отдельно обновим баланс через его подписку — он придёт в его
        # state по запросу клиента; здесь достаточно reveal с potStr.
        log.info("jackpot winner uid=%s pot=%s f=%.4f", winner.user_id, total, f)

    async def _reset(self) -> None:
        async with self._lock:
            self._bets.clear()
            self._pot = 0
            self._phase = "waiting"
            self._ends_at = 0.0
            self._pending = self._new_pending()
        await self._broadcast(self.snapshot())

    # --- рассылка ---

    async def _broadcast(self, payload: dict) -> None:
        if not self._subs:
            return
        dead = []
        for ws in list(self._subs):
            if getattr(ws, "closed", True):
                dead.append(ws)
                continue
            try:
                await ws.send_json(payload)
            except (ConnectionResetError, RuntimeError):
                dead.append(ws)
        for ws in dead:
            self._subs.discard(ws)
