"""aiohttp-сервер Mini App: раздача статики + WebSocket для real-time Crash."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from typing import Optional

from aiohttp import WSMsgType, web

from .. import slot_engine
from ..config import Config
from ..db import Database
from ..provably_fair import generate_server_seed, hash_server_seed
from ..units import format_ton, parse_amount, to_nano
from .auth import validate_init_data
from .crash_session import Settlement, WebCrashStore
from .jackpot import JackpotGame

log = logging.getLogger("casino.webapp")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TICK_SEC = 0.1


def _guest_user_id(token: str) -> int:
    """Стабильный отрицательный id для гостя (не пересекается с Telegram id)."""
    h = int(hashlib.sha1(token.encode()).hexdigest()[:12], 16)
    return -(h % 1_000_000_000 + 1)


class WebAppServer:
    def __init__(self, config: Config, db: Database):
        self._config = config
        self._db = db
        self._store = WebCrashStore(
            db,
            min_bet=to_nano(config.min_bet),
            max_bet=to_nano(config.max_bet),
            growth=config.multiplier_growth,
        )
        self._jackpot = JackpotGame(
            db,
            min_bet=to_nano(config.min_bet),
            max_bet=to_nano(config.max_bet),
        )

    def build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/ws", self.ws_handler)
        app.router.add_get("/api/state", self.http_state)
        app.router.add_static("/static/", STATIC_DIR, show_index=False)
        # Общий раунд «Забега» крутится в фоне — стартуем/глушим вместе с приложением
        # (работает и в polling, и в webhook, т.к. оба идут через build_app).
        app.on_startup.append(self._on_startup)
        app.on_cleanup.append(self._on_cleanup)
        return app

    async def _on_startup(self, _app: web.Application) -> None:
        self._jackpot.start()

    async def _on_cleanup(self, _app: web.Application) -> None:
        await self._jackpot.stop()

    # --- HTTP ---

    async def index(self, request: web.Request) -> web.Response:
        return web.FileResponse(os.path.join(STATIC_DIR, "index.html"))

    async def http_state(self, request: web.Request) -> web.Response:
        user = await self._authenticate(
            request.headers.get("X-Init-Data", "") or request.query.get("initData", ""),
            request.headers.get("X-Guest-Id", "") or request.query.get("guest", ""),
        )
        if not user:
            return web.json_response({"error": "auth"}, status=401)
        return web.json_response(await self._state_payload(user["id"]))

    # --- аутентификация ---

    async def _authenticate(self, init_data: str, guest_token: str) -> Optional[dict]:
        if init_data:
            # max_age=0 — не считаем initData протухшим (Telegram держит сессию долго).
            tg = validate_init_data(init_data, self._config.bot_token, 0)
            if tg and tg.get("id"):
                name = tg.get("username") or tg.get("first_name") or "player"
                return await self._db.get_or_create_user(int(tg["id"]), name)
            # Есть initData, но невалиден — НЕ сбрасываем в гостя (иначе сменится id и слетят деньги).
            return None
        if self._config.webapp_allow_guest and guest_token:
            uid = _guest_user_id(guest_token)
            return await self._db.get_or_create_user(uid, "guest")
        return None

    async def _state_payload(self, user_id: int) -> dict:
        balance = await self._db.get_balance(user_id)
        history = await self._db.recent_crash_points(14)
        leaders = await self._db.top_players(10)
        return {
            "type": "state",
            "userId": user_id,
            "balance": balance,
            "balanceStr": format_ton(balance),
            "history": [round(p, 2) for p in history],
            "leaderboard": [
                {"name": (l["username"] or "player"), "balanceStr": format_ton(l["balance"])}
                for l in leaders
            ],
            "config": {
                "min": self._config.min_bet,
                "max": self._config.max_bet,
                "growth": self._config.multiplier_growth,
                "faucet": self._config.faucet_amount,
            },
        }

    # --- WebSocket игра ---

    async def ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        user: Optional[dict] = None
        ticker: Optional[asyncio.Task] = None
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                kind = data.get("type")

                if kind == "auth":
                    user = await self._authenticate(data.get("initData", ""), data.get("guest", ""))
                    if not user:
                        await self._safe_send(ws, {"type": "error", "message": "Не удалось авторизоваться"})
                        await ws.close()
                        return ws
                    await self._safe_send(ws, {"type": "dbg", "msg": f"auth uid={user['id']}"})
                    await self._safe_send(ws, await self._state_payload(user["id"]))

                elif kind == "bet":
                    if not user:
                        continue
                    amount = parse_amount(str(data.get("amount", "")))
                    if amount is None:
                        await self._safe_send(ws, {"type": "error", "message": "Неверная сумма ставки"})
                        continue
                    rnd, err = await self._store.place_bet(user["id"], amount)
                    if err:
                        await self._safe_send(ws, {"type": "error", "message": err})
                        continue
                    balance = await self._db.get_balance(user["id"])
                    await self._safe_send(ws, {
                        "type": "started", "roundId": rnd.round_id, "hash": rnd.server_seed_hash,
                        "bet": rnd.bet, "betStr": format_ton(rnd.bet),
                        "balance": balance, "balanceStr": format_ton(balance),
                        "clientSeed": rnd.client_seed, "nonce": rnd.nonce,
                    })
                    await self._safe_send(ws, {"type": "dbg", "msg": f"bet uid={user['id']} round={rnd.round_id}"})
                    if ticker:
                        ticker.cancel()
                    ticker = asyncio.create_task(self._run_ticker(ws, user["id"], rnd.round_id))

                elif kind == "faucet":
                    if not user:
                        continue
                    left = await self._db.faucet_seconds_left(user["id"], self._config.faucet_cooldown_sec)
                    if left > 0:
                        mins = left // 60
                        await self._safe_send(ws, {"type": "error",
                                                   "message": f"Кран будет доступен через {mins} мин"})
                        continue
                    await self._db.credit(user["id"], to_nano(self._config.faucet_amount), "faucet")
                    await self._db.mark_faucet(user["id"])
                    await self._safe_send(ws, {"type": "toast", "message": f"+{self._config.faucet_amount:g} tTON"})
                    await self._safe_send(ws, await self._state_payload(user["id"]))

                elif kind in ("slot_spin", "slot_buy"):
                    if not user:
                        continue
                    await self._handle_slot(ws, user["id"], data, buy=(kind == "slot_buy"))

                elif kind == "jackpot_join":
                    if not user:
                        continue
                    self._jackpot.add_sub(ws)
                    await self._safe_send(ws, self._jackpot.snapshot())

                elif kind == "jackpot_bet":
                    if not user:
                        continue
                    amount = parse_amount(str(data.get("amount", "")))
                    if amount is None:
                        await self._safe_send(ws, {"type": "error", "message": "Неверная сумма ставки"})
                        continue
                    role = str(data.get("role", "")).strip()[:24] or "default"
                    name = user.get("username") or "player"
                    self._jackpot.add_sub(ws)
                    ok, err, balance = await self._jackpot.place_bet(user["id"], name, amount, role)
                    if not ok:
                        await self._safe_send(ws, {"type": "error", "message": err})
                        continue
                    await self._safe_send(ws, await self._state_payload(user["id"]))

                elif kind == "cashout":
                    if not user:
                        continue
                    settlement = await self._store.cashout(user["id"])
                    await self._safe_send(ws, {"type": "dbg",
                        "msg": f"cashout uid={user['id']} found={settlement is not None} active={list(self._store._rounds.keys())}"})
                    if settlement is None:
                        continue
                    if ticker:
                        ticker.cancel()
                    await self._send_settlement(ws, user["id"], settlement)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            if ticker:
                ticker.cancel()
            self._jackpot.remove_sub(ws)
            if user:
                await self._store.abandon(user["id"])
        return ws

    async def _run_ticker(self, ws: web.WebSocketResponse, user_id: int, round_id: str) -> None:
        try:
            while True:
                await asyncio.sleep(TICK_SEC)
                rnd = self._store.active_round(user_id)
                if rnd is None or rnd.round_id != round_id or rnd.settled:
                    return
                if rnd.is_crashed():
                    settlement = await self._store.settle_if_crashed(user_id)
                    if settlement is not None:
                        await self._send_settlement(ws, user_id, settlement)
                    return
                if not await self._safe_send(ws, {"type": "tick", "m": round(rnd.multiplier_now(), 2)}):
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.debug("ticker error", exc_info=True)

    async def _send_settlement(self, ws: web.WebSocketResponse, user_id: int, s: Settlement) -> None:
        await self._safe_send(ws, {
            "type": "cashout" if s.outcome == "win" else "crash",
            "outcome": s.outcome,
            "m": s.multiplier,
            "crashPoint": round(s.crash_point, 2),
            "payout": s.payout,
            "payoutStr": format_ton(s.payout),
            "balance": s.balance,
            "balanceStr": format_ton(s.balance),
            "serverSeed": s.server_seed,
            "hash": s.server_seed_hash,
            "clientSeed": s.client_seed,
            "nonce": s.nonce,
        })
        # Обновлённые история/лидерборд.
        await self._safe_send(ws, await self._state_payload(user_id))

    async def _handle_slot(self, ws: web.WebSocketResponse, user_id: int, data: dict, buy: bool) -> None:
        amount = parse_amount(str(data.get("amount", "")))
        if amount is None:
            await self._safe_send(ws, {"type": "error", "message": "Неверная ставка"})
            return
        if amount < to_nano(self._config.min_bet) or amount > to_nano(self._config.max_bet):
            await self._safe_send(ws, {"type": "error", "message": "Ставка вне диапазона"})
            return
        cost = int(amount * slot_engine.BUY_COST) if buy else amount
        new_balance = await self._db.try_debit(user_id, cost, "bet", "slot")
        if new_balance is None:
            await self._safe_send(ws, {"type": "error", "message": "Недостаточно средств"})
            return

        user = await self._db.get_user(user_id)
        client_seed = user["client_seed"]
        nonce = await self._db.next_nonce(user_id)
        seed = generate_server_seed()
        result = (slot_engine.play_bonus if buy else slot_engine.play)(seed, client_seed, nonce)

        payout = int(amount * result["total"])
        balance = (await self._db.credit(user_id, payout, "win", "slot")
                   if payout > 0 else await self._db.get_balance(user_id))

        await self._safe_send(ws, {
            "type": "slot_result",
            "bet": amount, "betStr": format_ton(amount), "cost": cost,
            "rounds": result["rounds"], "total": result["total"],
            "payout": payout, "payoutStr": format_ton(payout),
            "scatters": result["scatters"], "freeSpins": result["free_spins"],
            "balance": balance, "balanceStr": format_ton(balance),
            "serverSeed": seed, "hash": hash_server_seed(seed),
            "clientSeed": client_seed, "nonce": nonce,
        })
        await self._safe_send(ws, await self._state_payload(user_id))

    @staticmethod
    async def _safe_send(ws: web.WebSocketResponse, payload: dict) -> bool:
        if ws.closed:
            return False
        try:
            await ws.send_json(payload)
            return True
        except (ConnectionResetError, RuntimeError):
            return False


async def start_webapp(config: Config, db: Database) -> web.AppRunner:
    server = WebAppServer(config, db)
    runner = web.AppRunner(server.build_app())
    await runner.setup()
    site = web.TCPSite(runner, config.webapp_host, config.webapp_port)
    await site.start()
    log.info("Mini App сервер: http://%s:%s", config.webapp_host, config.webapp_port)
    return runner
