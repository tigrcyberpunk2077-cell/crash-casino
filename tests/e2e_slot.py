"""E2E слота: реальный сервер + WS-клиент. python3 tests/e2e_slot.py"""

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

PORT = 8097
_p = _f = 0


def check(n, c):
    global _p, _f
    if c:
        _p += 1; print(f"  ok   {n}")
    else:
        _f += 1; print(f"  FAIL {n}")


async def recv(ws, types, timeout=6):
    async def _r():
        async for m in ws:
            if m.type == aiohttp.WSMsgType.TEXT:
                d = json.loads(m.data)
                if d.get("type") in types:
                    return d
    return await asyncio.wait_for(_r(), timeout)


async def main():
    cfg = load_config()
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    cfg.db_path = tmp.name; cfg.webapp_host = "127.0.0.1"; cfg.webapp_port = PORT
    cfg.webapp_allow_guest = True; cfg.faucet_cooldown_sec = 0; cfg.faucet_amount = 100000
    db = Database(cfg.db_path); await db.connect()
    runner = await start_webapp(cfg, db)
    await asyncio.sleep(0.3)

    async with aiohttp.ClientSession() as s:
        check("статика символа h1.png", (await s.get(f"http://127.0.0.1:{PORT}/static/slot/h1.png")).status == 200)
        check("audio.js отдаётся", (await s.get(f"http://127.0.0.1:{PORT}/static/audio.js?v=4")).status == 200)
        check("slot.js отдаётся", (await s.get(f"http://127.0.0.1:{PORT}/static/slot.js?v=4")).status == 200)

        async with s.ws_connect(f"http://127.0.0.1:{PORT}/ws") as ws:
            await ws.send_json({"type": "auth", "guest": "slottester"})
            await recv(ws, {"state"})
            await ws.send_json({"type": "faucet"})
            st = await recv(ws, {"state"})
            start_bal = st["balance"]
            check("баланс пополнен", start_bal > 0)

            await ws.send_json({"type": "slot_spin", "amount": 1})
            r = await recv(ws, {"slot_result"})
            check("slot_result получен", r is not None)
            check("есть базовый раунд с кадрами", r["rounds"] and r["rounds"][0]["frames"])
            grid = r["rounds"][0]["frames"][0]["grid"]
            check("сетка 5x3", len(grid) == 5 and all(len(c) == 3 for c in grid))
            check("раскрыт server_seed", len(r["serverSeed"]) == 64)
            check("баланс изменился консистентно",
                  r["balance"] == start_bal - to_nano(1) + r["payout"])

            # Feature Buy
            bal_before_buy = r["balance"]
            await ws.send_json({"type": "slot_buy", "amount": 1})
            rb = await recv(ws, {"slot_result"})
            check("feature buy -> результат с фриспинами", rb["rounds"] and len(rb["rounds"]) >= 1)
            check("buy списал 60x и начислил выигрыш",
                  rb["balance"] == bal_before_buy - to_nano(60) + rb["payout"])

    await runner.cleanup(); await db.close(); os.unlink(tmp.name)
    print(f"\nИтог: {_p} passed, {_f} failed")
    return 1 if _f else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
