"""Конфигурация из переменных окружения (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

try:  # .env подхватывается автоматически, если установлен python-dotenv
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001 — dotenv необязателен
    pass


@dataclass
class Config:
    bot_token: str
    wallet_provider: str  # "faucet" | "ton"
    db_path: str
    turso_url: Optional[str]      # libsql://… облачная база (Turso) — балансы не пропадают
    turso_token: Optional[str]
    faucet_amount: float          # сколько tTON выдаёт /faucet
    faucet_cooldown_sec: int
    min_bet: float
    max_bet: float
    multiplier_growth: float      # скорость кривой Crash
    # --- TON testnet (нужно только при wallet_provider == "ton") ---
    ton_api_key: Optional[str]
    ton_mnemonic: Optional[str]   # сид-фраза горячего кошелька (24 слова)
    ton_min_withdraw: float
    # --- Mini App (WebApp) ---
    webapp_enabled: bool
    webapp_host: str
    webapp_port: int
    webapp_url: Optional[str]      # публичный https-URL для кнопки в боте
    webapp_allow_guest: bool       # пускать без Telegram initData (для теста в браузере)
    use_webhook: bool              # режим webhook вместо polling (для хостинга)
    # --- соцфичи / удержание ---
    referral_bonus: float          # бонус обоим за приглашённого друга
    reminder_idle_hours: int       # через сколько простоя напоминать игроку
    reminder_interval_min: int     # как часто крутить рассылку напоминаний
    reminder_batch: int            # максимум сообщений за один проход
    admin_ids: tuple = ()          # Telegram ID владельцев — им виден раздел «Статистика»
    bot_username: Optional[str] = None  # заполняется в рантайме (getMe) для ссылок-приглашений
    # --- «ИИ Баран»: ответы в группах через Gemini ---
    gemini_api_key: str = ""       # ключ Gemini (бесплатно, AI Studio) — без него Баран молчит
    gemini_model: str = "gemini-flash-latest"
    ai_baran_all: bool = False     # отвечать на ВСЕ сообщения (нужен privacy off), а не только на упоминания
    ai_baran_chance: float = 0.10  # вероятность ответа на «левое» сообщение (если ai_baran_all)
    ai_baran_idle_min: int = 12    # через сколько минут тишины Баран сам пишет в чат
    ai_baran_voice_chance: float = 0.35  # доля голосовых ответов (если задан голос)
    elevenlabs_api_key: str = ""   # ключ ElevenLabs для голоса-клона (без него — только текст)
    elevenlabs_voice_id: str = ""  # id клонированного голоса


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return int(default)


def _b(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# Telegram ID владельцев (через запятую в ADMIN_IDS), либо вшитые ниже —
# чтобы статистику было видно без правки переменных на хостинге.
ADMIN_IDS_BUILTIN = ()


def _ids(name: str) -> tuple:
    out = list(ADMIN_IDS_BUILTIN)
    for p in os.getenv(name, "").replace(",", " ").split():
        try:
            out.append(int(p))
        except ValueError:
            pass
    return tuple(dict.fromkeys(out))


def load_config() -> Config:
    return Config(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        wallet_provider=os.getenv("WALLET_PROVIDER", "faucet").strip().lower(),
        turso_url=os.getenv("TURSO_DATABASE_URL") or None,
        turso_token=os.getenv("TURSO_AUTH_TOKEN") or None,
        db_path=os.getenv("DB_PATH", "casino.db"),
        faucet_amount=_f("FAUCET_AMOUNT", 100.0),
        faucet_cooldown_sec=_i("FAUCET_COOLDOWN_SEC", 6 * 3600),
        min_bet=_f("MIN_BET", 0.1),
        max_bet=_f("MAX_BET", 50.0),
        multiplier_growth=_f("MULTIPLIER_GROWTH", 0.12),
        ton_api_key=os.getenv("TON_API_KEY") or None,
        ton_mnemonic=os.getenv("TON_MNEMONIC") or None,
        ton_min_withdraw=_f("TON_MIN_WITHDRAW", 1.0),
        webapp_enabled=_b("WEBAPP_ENABLED", True),
        webapp_host=os.getenv("WEBAPP_HOST", "0.0.0.0"),
        # Хостинги (Railway/Render/Fly/Heroku…) задают порт через $PORT.
        webapp_port=_i("PORT", _i("WEBAPP_PORT", 8080)),
        # Публичный адрес: ручной WEBAPP_URL, либо автоматом от хостинга
        # (Render -> RENDER_EXTERNAL_URL, Koyeb -> KOYEB_PUBLIC_DOMAIN).
        webapp_url=(
            os.getenv("WEBAPP_URL")
            or os.getenv("RENDER_EXTERNAL_URL")
            or (f"https://{os.getenv('KOYEB_PUBLIC_DOMAIN')}" if os.getenv("KOYEB_PUBLIC_DOMAIN") else None)
        ),
        webapp_allow_guest=_b("WEBAPP_ALLOW_GUEST", True),
        use_webhook=_b("USE_WEBHOOK", False),
        referral_bonus=_f("REFERRAL_BONUS", 50.0),
        reminder_idle_hours=_i("REMINDER_IDLE_HOURS", 20),
        reminder_interval_min=_i("REMINDER_INTERVAL_MIN", 30),
        reminder_batch=_i("REMINDER_BATCH", 25),
        admin_ids=_ids("ADMIN_IDS"),
        gemini_api_key=(os.getenv("GEMINI_API_KEY", "").split(",")[0].strip()),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip(),
        ai_baran_all=_b("AI_BARAN_ALL", False),
        ai_baran_chance=_f("AI_BARAN_CHANCE", 0.10),
        ai_baran_idle_min=_i("AI_BARAN_IDLE_MIN", 12),
        ai_baran_voice_chance=_f("AI_BARAN_VOICE_CHANCE", 0.35),
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", "").strip(),
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", "").strip(),
    )
