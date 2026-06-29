"""Конфиг личного авто-ответчика.

Переиспользует конфиг агента (Gemini-ключи, токен управляющего бота, admin_id),
добавляет данные для userbot (твой аккаунт) и ElevenLabs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from agent.config import ConfigError, load_config as _load_agent


@dataclass
class AConfig:
    agent: object              # cfg агента: LLM (Gemini), admin_id
    bot_token: str             # свой бот ассистента (ASSISTANT_BOT_TOKEN); fallback — бот агента
    api_id: int
    api_hash: str
    session: str
    phone: Optional[str]
    elevenlabs_api_key: Optional[str]
    db_path: str


def _req(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise ConfigError(f"Не задана {name} (см. .env, раздел «личный авто-ответчик»).")
    return v


def load(require_session: bool = True) -> AConfig:
    agent = _load_agent()  # bot_token, admin_id, gemini_api_keys и т.д.

    session = os.getenv("TG_SESSION", "").strip()
    if require_session and not session:
        raise ConfigError("Нет TG_SESSION. Сначала: python -m assistant.login — и впиши в .env.")

    # api_id/api_hash необязательны: без них ассистент поднимется в ТЕСТ-режиме
    # (бот-песочница), а полный режим (userbot) включится, когда они появятся.
    api_id_raw = os.getenv("TG_API_ID", "").strip()
    api_id = int(api_id_raw) if api_id_raw.isdigit() else 0

    return AConfig(
        agent=agent,
        bot_token=os.getenv("ASSISTANT_BOT_TOKEN", "").strip() or agent.bot_token,
        api_id=api_id,
        api_hash=os.getenv("TG_API_HASH", "").strip(),
        session=session,
        phone=os.getenv("TG_PHONE", "").strip() or None,
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", "").strip() or None,
        db_path=os.getenv("ASSISTANT_DB_PATH", "assistant.db").strip(),
    )
