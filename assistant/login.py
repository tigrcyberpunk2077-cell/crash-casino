"""Одноразовый логин аккаунта → TG_SESSION.   python -m assistant.login"""

from __future__ import annotations

import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession

from . import config


async def _run() -> None:
    cfg = config.load(require_session=False)
    client = TelegramClient(StringSession(), cfg.api_id, cfg.api_hash)
    await client.start(phone=cfg.phone)
    me = await client.get_me()
    print("\n" + "=" * 60)
    print(f"Вошёл как: {me.first_name} (@{me.username})")
    print("Скопируй строку ниже целиком в .env:\n")
    print(f"TG_SESSION={client.session.save()}")
    print("=" * 60)
    await client.disconnect()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
