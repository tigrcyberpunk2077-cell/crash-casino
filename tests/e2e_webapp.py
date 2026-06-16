"""End-to-end проверка Mini App: реальный aiohttp-сервер + WebSocket-клиент.

Поднимает сервер на свободном порту и проходит полный сценарий игры.
Запуск: python3 tests/e2e_webapp.py
"""

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp

from casino.config import load_config
from casino.db import Database
from casino.units import to_nano
from casino.webapp.server import start_webapp

PORT = 8099
_passed = _failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1; print(f"  ok   {name}")
    else:
        _failed += 1; print(f"  FAIL {name}")


async def recv_until(ws, types, timeout=5.0):
    """Ждём сообщение одного из типов."""
    async def _r():
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") in types:
                    return data
        return None
    return await asyncio.wait_for(_r(), timeout)


async def main():
    cfg = load_config()
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    cfg.db_path = tmp.name
    cfg.webapp_host = "127.0.0.1"
    cfg.webapp_port = PORT
    cfg.webapp_allow_guest = True
    cfg.faucet_cooldown_sec = 0
    cfg.multiplier_growth = 0.05  # медленно — успеем забрать

    db = Database(cfg.db_path); await db.connect()
    runner = await start_webapp(cfg, db)
    await asyncio.sleep(0.3)

    base = f"http://127.0.0.1:{PORT}"
    async with aiohttp.ClientSession() as sess:
        print("http:")
        async with sess.get(base + "/") as r:
            html = await r.text()
            check("GET / -> 200", r.status == 200)
            check("в HTML есть canvas", "<canvas" in html)
        async with sess.get(base + "/static/app.js") as r:
            check("статика app.js отдаётся", r.status == 200)
        async with sess.get(base + "/api/state", headers={"X-Guest-Id": "tester1"}) as r:
            st = await r.json()
            check("GET /api/state (гость) -> баланс 0", r.status == 200 and st["balance"] == 0)

        print("websocket игра:")
        async with sess.ws_connect(base + "/ws") as ws:
            await ws.send_json({"type": "auth", "guest": "tester1"})
            state = await recv_until(ws, {"state"})
            check("auth -> state получен", state is not None)

            await ws.send_json({"type": "faucet"})
            st2 = await recv_until(ws, {"state"})
            check("faucet начислил баланс", st2 and st2["balance"] == to_nano(cfg.faucet_amount))

            await ws.send_json({"type": "bet", "amount": 5})
            started = await recv_until(ws, {"started"})
            check("bet -> started", started is not None and "hash" in started)
            check("баланс списан на ставку", started["balance"] == to_nano(cfg.faucet_amount) - to_nano(5))

            tick = await recv_until(ws, {"tick", "crash"})
            check("пошли тики множителя", tick is not None)

            await ws.send_json({"type": "cashout"})
            res = await recv_until(ws, {"cashout", "crash"})
            check("получен итог раунда", res is not None)
            check("раскрыт server_seed (provably fair)", res and len(res.get("serverSeed", "")) == 64)
            # арифметика баланса
            final = await db.get_balance(state and 0 or 0) if False else None
            uid_balance = res["balance"]
            check("итоговый баланс согласован",
                  uid_balance == to_nano(cfg.faucet_amount) - to_nano(5) + res["payout"])
            if res["type"] == "cashout":
                check("выигрыш: payout > 0", res["payout"] > 0)

    await runner.cleanup()
    await db.close(); os.unlink(tmp.name)
    print()
    print(f"Итог: {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
