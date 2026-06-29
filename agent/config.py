"""Конфигурация агента из переменных окружения (.env).

Простой режим: всё делает один бот (от @BotFather) — и присылает черновики,
и сам публикует в каналы, где он добавлен админом. Аккаунт/телефон/коды
Telegram не нужны.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

log = logging.getLogger("agent.config")


class ConfigError(RuntimeError):
    """Не хватает обязательной переменной окружения."""


@dataclass
class Config:
    # --- Управляющий бот (от @BotFather) — он же публикует в каналы ---
    bot_token: str
    admin_id: int           # твой Telegram user-id: только ты одобряешь и управляешь

    # --- Генерация текста ---
    llm_provider: str       # "gemini" (бесплатно) | "claude" (платный API)
    anthropic_api_key: Optional[str]
    anthropic_model: str
    gemini_api_keys: List[str]   # можно несколько (через запятую) — ротация умножает бесплатный лимит
    gemini_model: str

    # --- Голос для видео (ElevenLabs; пусто → бесплатный edge-tts) ---
    elevenlabs_api_key: Optional[str]
    elevenlabs_voice_id: str
    # Pexels — реальные видео-клипы на фон (бесплатно). Пусто → статичные ИИ-картинки.
    pexels_api_key: Optional[str]

    # --- Контент: каналы-персоны (персона/ниша задаются на каждый канал) ---
    default_persona: str
    default_niche: str
    cta_link: str           # необязательная ссылка для призыва. Пусто — без ссылок

    # --- Режим работы ---
    # auto_post=False (по умолчанию): бот НЕ постит сам по таймеру — ты присылаешь
    # фото (+ опц. «про что»), он пишет текст и шлёт на одобрение. auto_post=True:
    # планировщик сам генерит посты (с картинкой) в «лучшее время».
    auto_post: bool

    # --- Картинки к постам ---
    images_enabled: bool
    media_dir: str

    # --- Расписание / «лучшее время» ---
    default_interval_min: int
    scheduler_tick_sec: int
    utc_offset: int
    active_start: int
    active_end: int
    peak_hours: Tuple[int, ...]

    # --- Сидинг каналов (чтобы переживать редеплой) ---
    channels_seed: List[dict]

    db_path: str


def _req(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        raise ConfigError(
            f"Не задана переменная {name}. Заполни её в .env "
            f"(шаблон — в .env.example, раздел «ИИ-агент каналов»)."
        )
    return val


def _opt(name: str, default: str = "") -> Optional[str]:
    val = os.getenv(name, default).strip()
    return val or None


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _window(name: str, default: Tuple[int, int]) -> Tuple[int, int]:
    """Парсит '10-23' → (10, 23). Окно может быть «через полночь» (22-2)."""
    raw = os.getenv(name, "").strip()
    if not raw or "-" not in raw:
        return default
    try:
        a, b = (int(x) % 24 for x in raw.split("-", 1))
        return a, b
    except ValueError:
        return default


def _hours_list(name: str) -> Tuple[int, ...]:
    """Парсит '12,15,19,21' → (12, 15, 19, 21). Пусто → ()."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return ()
    out = []
    for p in raw.replace(" ", "").split(","):
        if p.isdigit():
            out.append(int(p) % 24)
    return tuple(out)


def _channels_seed() -> List[dict]:
    raw = os.getenv("AGENT_CHANNELS", "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict) and d.get("ref")]
    except json.JSONDecodeError:
        log.warning("AGENT_CHANNELS — некорректный JSON, пропускаю сидинг каналов")
    return []


def load_config() -> Config:
    try:  # .env подхватывается автоматически, если установлен python-dotenv
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # noqa: BLE001 — dotenv необязателен
        pass

    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    if provider not in ("claude", "gemini"):
        raise ConfigError("LLM_PROVIDER должен быть 'claude' или 'gemini'.")

    cfg = Config(
        bot_token=_req("AGENT_BOT_TOKEN"),
        admin_id=int(_req("AGENT_ADMIN_ID")),
        llm_provider=provider,
        anthropic_api_key=_opt("ANTHROPIC_API_KEY"),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5").strip(),
        gemini_api_keys=[k.strip() for k in os.getenv("GEMINI_API_KEY", "").split(",") if k.strip()],
        gemini_model=os.getenv(
            "GEMINI_MODEL",
            # список через запятую — перебор при лимите (умножает бесплатную квоту)
            "gemini-flash-latest,gemini-2.5-flash-lite,gemini-2.0-flash,gemini-2.5-flash",
        ).strip(),
        elevenlabs_api_key=_opt("ELEVENLABS_API_KEY"),
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL").strip(),
        pexels_api_key=_opt("PEXELS_API_KEY"),
        default_persona=os.getenv(
            "AGENT_DEFAULT_PERSONA",
            "Алина, 26 — тёплый наставник. Говорит просто, делится опытом, поддерживает новичков.",
        ).strip(),
        default_niche=os.getenv("AGENT_DEFAULT_NICHE", "трейдинг для новичков").strip(),
        cta_link=os.getenv("AGENT_CTA_LINK", os.getenv("AGENT_BOT_LINK", "")).strip(),
        auto_post=_bool("AGENT_AUTO", False),
        images_enabled=_bool("AGENT_IMAGES", True),
        media_dir=os.getenv("AGENT_MEDIA_DIR", "agent_media").strip(),
        default_interval_min=_int("AGENT_INTERVAL_MIN", 180),
        scheduler_tick_sec=_int("AGENT_TICK_SEC", 60),
        utc_offset=_int("AGENT_UTC_OFFSET", 0),
        active_start=_window("AGENT_ACTIVE_HOURS", (10, 23))[0],
        active_end=_window("AGENT_ACTIVE_HOURS", (10, 23))[1],
        peak_hours=_hours_list("AGENT_PEAK_HOURS"),
        channels_seed=_channels_seed(),
        db_path=os.getenv("AGENT_DB_PATH", "agent.db").strip(),
    )

    if cfg.llm_provider == "claude" and not cfg.anthropic_api_key:
        raise ConfigError("LLM_PROVIDER=claude, но не задан ANTHROPIC_API_KEY.")
    if cfg.llm_provider == "gemini" and not cfg.gemini_api_keys:
        raise ConfigError("LLM_PROVIDER=gemini, но не задан GEMINI_API_KEY.")
    return cfg
