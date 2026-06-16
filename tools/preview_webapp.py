"""Dev-сервер ТОЛЬКО для Mini App (без Telegram-бота и токена).

Удобно смотреть/тестировать дизайн в браузере: открой http://localhost:8080
Гостевой режим включён, баланс начисляется автоматически. Наполняет демо-данными.

Запуск: python3 tools/preview_webapp.py
"""

import asyncio
import os
import random
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
# Вендоренные зависимости (aiohttp, aiosqlite) — чтобы работало и системным python.
_VENDOR = os.path.join(_ROOT, "vendor")
if os.path.isdir(_VENDOR):
    sys.path.insert(0, _VENDOR)

from casino.config import load_config
from casino.db import Database
from casino.provably_fair import generate_server_seed, hash_server_seed
from casino.units import to_nano
from casino.webapp.server import start_webapp

DEMO_NAMES = ["SBE | Desta", "Фатима", "PIRATE Bums", "kolyan", "moonboy",
              "ToToshka", "Lucky777", "crashking"]


async def seed(db: Database) -> None:
    if (await db.top_players(1)):
        return  # уже наполнено
    for i, name in enumerate(DEMO_NAMES):
        uid = 900000 + i
        await db.get_or_create_user(uid, name)
        await db.credit(uid, to_nano(random.randint(50, 9999)), "faucet")
    # история крашей
    for n in range(14):
        cp = round(random.choice([1.0, 1.2, 1.5, 1.9, 2.3, 3.1, 5.7, 1.1, 8.2, 14.8, 27.0]), 2)
        seed_v = generate_server_seed()
        await db.record_round(
            user_id=900000, bet=to_nano(1), crash_point=cp,
            cashout=(cp if cp >= 2 else None), payout=0,
            server_seed=seed_v, server_seed_hash=hash_server_seed(seed_v),
            client_seed="demo", nonce=n, outcome=("win" if cp >= 2 else "lose"),
        )


async def main() -> None:
    config = load_config()
    config.db_path = os.path.join(tempfile.gettempdir(), "casino_webapp_demo.db")  # демо-БД
    config.webapp_allow_guest = True
    db = Database(config.db_path)
    await db.connect()
    await seed(db)
    await start_webapp(config, db)
    print(f"Mini App превью: http://localhost:{config.webapp_port}")
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
