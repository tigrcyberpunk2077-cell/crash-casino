"""Рантайм активных раундов Crash: живой множитель + атомарное завершение."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from ..crash_engine import format_multiplier, multiplier_at
from ..db import Database
from ..keyboards import cashout_kb, play_again_kb
from ..units import format_ton

log = logging.getLogger("casino.games")

TICK_SEC = 1.6  # частота обновления множителя (безопасно по лимитам Telegram)


@dataclass
class CrashGame:
    user_id: int
    chat_id: int
    message_id: int
    game_id: str
    bet: int
    crash_point: float
    server_seed: str
    server_seed_hash: str
    client_seed: str
    nonce: int
    growth: float
    started_at: float = field(default_factory=time.monotonic)
    status: str = "running"  # running | cashed | crashed
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: Optional[asyncio.Task] = None


class GameManager:
    def __init__(self, bot: Bot, db: Database):
        self._bot = bot
        self._db = db
        self._games: Dict[int, CrashGame] = {}

    def is_active(self, user_id: int) -> bool:
        return user_id in self._games

    async def start(self, game: CrashGame) -> None:
        self._games[game.user_id] = game
        async with game.lock:
            await self._render_running(game, 1.00)
        game.task = asyncio.create_task(self._run(game))

    async def cashout(self, user_id: int, game_id: str) -> bool:
        """Забрать выигрыш. True если успешно засчитан вывод."""
        game = self._games.get(user_id)
        if not game or game.game_id != game_id:
            return False
        async with game.lock:
            if game.status != "running":
                return False
            elapsed = time.monotonic() - game.started_at
            mult = multiplier_at(elapsed, game.growth)
            if mult >= game.crash_point:
                # Не успел на мгновение — это краш.
                await self._finalize_locked(game, "crashed", game.crash_point)
                done_win = False
            else:
                await self._finalize_locked(game, "cashed", mult)
                done_win = True
        self._cancel_and_drop(game)
        return done_win

    async def _run(self, game: CrashGame) -> None:
        try:
            while True:
                await asyncio.sleep(TICK_SEC)
                async with game.lock:
                    if game.status != "running":
                        return
                    elapsed = time.monotonic() - game.started_at
                    mult = multiplier_at(elapsed, game.growth)
                    if mult >= game.crash_point:
                        await self._finalize_locked(game, "crashed", game.crash_point)
                        return
                    await self._render_running(game, mult)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Сбой раунда")
        finally:
            self._games.pop(game.user_id, None)

    # --- завершение раунда (вызывать под game.lock, status == running) ---

    async def _finalize_locked(self, game: CrashGame, outcome: str, mult: float) -> None:
        if outcome == "cashed":
            payout = int(game.bet * mult)
            await self._db.credit(game.user_id, payout, "win", f"crash {mult:.2f}x")
            cashout: Optional[float] = round(mult, 2)
            db_outcome = "win"
            game.status = "cashed"
        else:
            payout = 0
            cashout = None
            db_outcome = "lose"
            game.status = "crashed"

        await self._db.record_round(
            user_id=game.user_id, bet=game.bet, crash_point=game.crash_point,
            cashout=cashout, payout=payout, server_seed=game.server_seed,
            server_seed_hash=game.server_seed_hash, client_seed=game.client_seed,
            nonce=game.nonce, outcome=db_outcome,
        )
        await self._render_result(game, outcome, mult, payout)

    # --- рендер сообщений ---

    async def _render_running(self, game: CrashGame, mult: float) -> None:
        potential = int(game.bet * mult)
        text = (
            "🚀 <b>CRASH</b>\n\n"
            f"Множитель: <b>{format_multiplier(mult)}</b>\n"
            f"Ставка: {format_ton(game.bet)}\n"
            f"Заберёшь сейчас: <b>{format_ton(potential)}</b>\n\n"
            "Жми «ЗАБРАТЬ», пока не крашнулось 👇"
        )
        await self._safe_edit(game, text, cashout_kb(game.game_id))

    async def _render_result(self, game: CrashGame, outcome: str, mult: float, payout: int) -> None:
        reveal = (
            "\n\n<b>Проверка честности:</b>\n"
            f"crash point: {game.crash_point:.2f}x\n"
            f"server seed: <code>{game.server_seed}</code>\n"
            f"client seed: <code>{game.client_seed}</code> | nonce: {game.nonce}\n"
            f"hash: <code>{game.server_seed_hash}</code>"
        )
        if outcome == "cashed":
            profit = payout - game.bet
            head = (
                f"💸 <b>Забрал на {format_multiplier(mult)}!</b>\n\n"
                f"Выплата: <b>{format_ton(payout)}</b>\n"
                f"Профит: <b>+{format_ton(max(profit, 0))}</b>\n"
                f"Краш был бы на {game.crash_point:.2f}x"
            )
        else:
            head = (
                f"💥 <b>CRASH на {game.crash_point:.2f}x</b>\n\n"
                f"Ставка {format_ton(game.bet)} сгорела. Не успел забрать."
            )
        await self._safe_edit(game, head + reveal, play_again_kb())

    async def _safe_edit(self, game: CrashGame, text: str, keyboard) -> None:
        try:
            await self._bot.edit_message_text(
                text=text, chat_id=game.chat_id, message_id=game.message_id,
                reply_markup=keyboard,
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                log.debug("edit failed: %s", exc)
        except Exception:  # noqa: BLE001
            log.debug("edit failed", exc_info=True)

    def _cancel_and_drop(self, game: CrashGame) -> None:
        if game.task and not game.task.done():
            game.task.cancel()
        self._games.pop(game.user_id, None)
