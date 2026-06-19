"""End-to-end проверка мультиплеер-«Забега»: реальный aiohttp-сервер + ДВА
WebSocket-клиента в одном общем раунде.

Проверяем: общий раунд видят оба, ставки складываются в банк, по таймеру
сервер рассылает всем один и тот же результат (один победитель), банк целиком
уходит победителю, общий баланс сохраняется.

Запуск: python3 tests/e2e_jackpot.py
"""

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp
from aiohttp import web

from casino.config import load_config
from casino.db import Database
from casino.units import to_nano
from casino.webapp.server import WebAppServer

PORT = 8097
_passed = _failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1; print(f"  ok   {name}")
    else:
        _failed += 1; print(f"  FAIL {name}")


async def recv_until(ws, types, timeout=8.0):
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
    cfg.webapp_host = "127.0.0.1"; cfg.webapp_port = PORT
    cfg.webapp_allow_guest = True; cfg.faucet_cooldown_sec = 0

    db = Database(cfg.db_path); await db.connect()
    server = WebAppServer(cfg, db)
    server._jackpot.ROUND_SEC = 2          # короткий раунд для теста
    server._jackpot.REVEAL_SEC = 0.5
    runner = web.AppRunner(server.build_app())
    await runner.setup()                    # запускает фоновый цикл (on_startup)
    site = web.TCPSite(runner, cfg.webapp_host, PORT); await site.start()
    await asyncio.sleep(0.3)

    base = f"http://127.0.0.1:{PORT}"
    async with aiohttp.ClientSession() as sess:
        async with sess.get(base + "/static/race.js") as r:
            check("race.js отдаётся сервером", r.status == 200)

        print("websocket: два игрока в общем раунде:")
        async with sess.ws_connect(base + "/ws") as wsA, sess.ws_connect(base + "/ws") as wsB:
            # вход + кран обоим
            await wsA.send_json({"type": "auth", "guest": "playerA"})
            stA = await recv_until(wsA, {"state"}); a_id = stA["userId"]
            await wsB.send_json({"type": "auth", "guest": "playerB"})
            stB = await recv_until(wsB, {"state"}); b_id = stB["userId"]
            check("у игроков разные id", a_id != b_id)
            for ws in (wsA, wsB):
                await ws.send_json({"type": "faucet"})
                await recv_until(ws, {"state"})

            # оба подписываются на общий раунд
            await wsA.send_json({"type": "jackpot_join"})
            snapA = await recv_until(wsA, {"jackpot"})
            check("join -> снимок раунда (фаза waiting)", snapA and snapA["phase"] == "waiting")
            await wsB.send_json({"type": "jackpot_join"})
            await recv_until(wsB, {"jackpot"})

            # A ставит 10 (роль samir) -> раунд стартует; B видит обновление
            await wsA.send_json({"type": "jackpot_bet", "amount": 10, "role": "samir"})
            snapB = await recv_until(wsB, {"jackpot"})
            check("ставка A видна второму игроку (broadcast)", snapB and snapB["pot"] == to_nano(10))
            check("раунд перешёл в collecting", snapB["phase"] == "collecting")

            # B ставит 30 (роль gold) -> банк 40, двое в поле
            await wsB.send_json({"type": "jackpot_bet", "amount": 30, "role": "gold"})
            snap2 = await recv_until(wsA, {"jackpot"})
            while snap2 and snap2["pot"] != to_nano(40):       # дождаться снимка с банком 40
                snap2 = await recv_until(wsA, {"jackpot"})
            check("банк собрал 40 на двоих", snap2 and snap2["pot"] == to_nano(40))
            check("в поле два куска", len(snap2["players"]) == 2)

            # ждём забег: оба получают ОДИН и тот же результат
            revA, revB = await asyncio.gather(
                recv_until(wsA, {"jackpot_reveal"}, 10),
                recv_until(wsB, {"jackpot_reveal"}, 10),
            )
            check("A получил результат забега", revA is not None)
            check("B получил результат забега", revB is not None)
            check("победитель один и тот же у обоих", revA["winnerId"] == revB["winnerId"])
            check("раскрыт server_seed (provably fair)", len(revA.get("serverSeed", "")) == 64)
            check("точка поимки f в [0,1)", 0.0 <= revA["f"] < 1.0)
            check("банк-приз = 40", revA["pot"] == to_nano(40))

        # деньги: банк целиком у победителя, общий баланс сохранён
        await asyncio.sleep(0.2)
        bal_a = await db.get_balance(a_id)
        bal_b = await db.get_balance(b_id)
        winner_id = revA["winnerId"]
        win_bal = bal_a if winner_id == a_id else bal_b
        lose_bal = bal_b if winner_id == a_id else bal_a
        check("у победителя баланс > 100 (забрал банк)", win_bal > to_nano(100))
        check("у проигравшего баланс < 100", lose_bal < to_nano(100))
        check("общий баланс сохранён (200)", bal_a + bal_b == to_nano(200))

    await runner.cleanup()
    await db.close(); os.unlink(tmp.name)
    print()
    print(f"Итог: {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
