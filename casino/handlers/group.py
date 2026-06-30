"""«ИИ Баран» — дерзкий ИИ-зазывала в группах (Gemini + голос-клон ElevenLabs).

- Отвечает на упоминание/ответ-боту/ключевые слова, опц. на все сообщения (privacy off + AI_BARAN_ALL).
- Сам лезет в чат, когда тишина (баран-idle-loop в main.py зовёт baran_idle_tick).
- Иногда отвечает голосовым (если задан ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID).
"""

from __future__ import annotations

import logging
import os
import random
import time

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import FSInputFile, Message

from ..config import Config
from ..llm import gemini_reply
from ..voice import tts_ogg

router = Router(name="group")
log = logging.getLogger("casino.baran")

# chat_id -> {"last": ts последнего сообщения, "idle": ts последнего idle-вброса}
GROUP_ACTIVITY: dict = {}
_last_reply: dict = {}     # chat_id -> ts последнего ответа (анти-спам)
COOLDOWN = 16.0
KEYWORDS = ("баран", "казино", "11a", "11а", "крёстный", "мафи")

SYSTEM = (
    "Ты — «ИИ Баран» 🐏, дерзкий уличный ИИ-зазывала подпольного неон-казино «11A» "
    "(год 2099, киберпанк). Отвечай ОЧЕНЬ коротко (1–2 предложения), на русском, с "
    "понтами и лёгкими подколами/грубоватым тоном — но БЕЗ мата и БЕЗ оскорблений по "
    "национальности, религии, полу или внешности. Это шутка и маркетинг, не будь "
    "по-настоящему токсичным. Зазывай играть в «11A»: Crash, неон-слот, Забег барана, "
    "Мафию. Гордо называй себя «ИИ Бараном». Иногда вставляй приглашение зайти по ссылке."
)


async def _generate(config: Config, prompt: str) -> str:
    return await gemini_reply(config.gemini_api_key, config.gemini_model, SYSTEM, prompt)


async def _deliver(bot: Bot, chat_id: int, text: str, config: Config) -> None:
    """Отправляет голосом (иногда) или текстом."""
    if not text:
        return
    if (config.elevenlabs_api_key and config.elevenlabs_voice_id
            and random.random() < config.ai_baran_voice_chance):
        ogg = await tts_ogg(config.elevenlabs_api_key, config.elevenlabs_voice_id, text)
        if ogg:
            try:
                await bot.send_voice(chat_id, FSInputFile(ogg))
                return
            except Exception:  # noqa: BLE001
                log.debug("voice send fail", exc_info=True)
            finally:
                try:
                    os.remove(ogg)
                except OSError:
                    pass
    try:
        await bot.send_message(chat_id, text[:600])
    except Exception:  # noqa: BLE001
        log.debug("text send fail", exc_info=True)


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def on_group_message(message: Message, config: Config) -> None:
    now = time.time()
    GROUP_ACTIVITY.setdefault(message.chat.id, {"last": 0.0, "idle": 0.0})["last"] = now

    txt = message.text or message.caption
    if not txt or txt.startswith("/") or not config.gemini_api_key:
        return
    me = (config.bot_username or "").lower()
    low = txt.lower()
    mentioned = bool(me) and ("@" + me) in low
    replied = bool(
        message.reply_to_message and message.reply_to_message.from_user
        and (message.reply_to_message.from_user.username or "").lower() == me
    )
    kw = any(w in low for w in KEYWORDS)
    rnd = config.ai_baran_all and random.random() < config.ai_baran_chance
    if not (mentioned or replied or kw or rnd):
        return
    if now - _last_reply.get(message.chat.id, 0) < COOLDOWN:
        return
    _last_reply[message.chat.id] = now

    link = f"https://t.me/{config.bot_username}" if config.bot_username else ""
    who = (message.from_user.first_name if message.from_user else "") or "игрок"
    reply = await _generate(config, f"Игрок {who} написал: «{txt}».\n"
                                    f"Ответь как ИИ Баран (коротко, дерзко). Ссылка-зазыв: {link}")
    await _deliver(message.bot, message.chat.id, reply, config)


async def baran_idle_tick(bot: Bot, config: Config) -> None:
    """Зовётся из фонового цикла: где в чате давно тишина — Баран сам вбрасывает фразу."""
    if not config.gemini_api_key:
        return
    now = time.time()
    idle_sec = max(120, config.ai_baran_idle_min * 60)
    cooldown = max(idle_sec, 30 * 60)
    link = f"https://t.me/{config.bot_username}" if config.bot_username else ""
    for chat_id, info in list(GROUP_ACTIVITY.items()):
        if now - info["last"] < idle_sec or now - info["idle"] < cooldown:
            continue
        info["idle"] = now
        info["last"] = now
        reply = await _generate(config, "В чате тишина, все притихли. Напиши задорную "
                                        "провокационную фразу как ИИ Баран, чтобы расшевелить "
                                        f"чат и зазвать в «11A». Ссылка: {link}")
        await _deliver(bot, chat_id, reply, config)
