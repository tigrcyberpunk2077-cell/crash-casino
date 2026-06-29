"""«ИИ Баран» — дерзкий ИИ-зазывала в групповых чатах (через Gemini).

Бот отвечает игрокам грубовато-понтово, зовёт в казино «11A» и просит звать себя
«ИИ Бараном». Чтобы отвечать на ВСЕ сообщения в группе, у бота должен быть
выключен privacy mode (@BotFather → /setprivacy → Disable). На упоминания и
ответы-на-бота отвечает в любом случае.
"""

from __future__ import annotations

import logging
import random
import time

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from ..config import Config
from ..llm import gemini_reply

router = Router(name="group")
log = logging.getLogger("casino.baran")

_last: dict = {}          # chat_id -> ts последнего ответа (анти-спам)
COOLDOWN = 16.0
KEYWORDS = ("баран", "казино", "11a", "11а", "крёстный", "мафи")

SYSTEM = (
    "Ты — «ИИ Баран» 🐏, дерзкий уличный ИИ-зазывала подпольного неон-казино «11A» "
    "(год 2099, киберпанк). Отвечай ОЧЕНЬ коротко (1–2 предложения), на русском, с "
    "понтами и лёгкими подколами/грубоватым тоном — но БЕЗ мата и БЕЗ оскорблений по "
    "национальности, религии, полу или внешности. Это шутка и маркетинг, не будь "
    "по-настоящему токсичным. Зазывай играть в «11A»: Crash, неон-слот, Забег барана, "
    "Мафию. Гордо называй себя «ИИ Бараном» и иногда проси так себя звать. Иногда "
    "вставляй приглашение зайти по ссылке, если она дана."
)


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def on_group_message(message: Message, config: Config) -> None:
    txt = message.text or message.caption
    if not txt or txt.startswith("/") or not config.gemini_api_key:
        return
    me = (config.bot_username or "").lower()
    low = txt.lower()
    mentioned = bool(me) and ("@" + me) in low
    replied = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and (message.reply_to_message.from_user.username or "").lower() == me
    )
    kw = any(w in low for w in KEYWORDS)
    rnd = config.ai_baran_all and random.random() < config.ai_baran_chance
    if not (mentioned or replied or kw or rnd):
        return

    now = time.time()
    if now - _last.get(message.chat.id, 0) < COOLDOWN:
        return
    _last[message.chat.id] = now

    link = f"https://t.me/{config.bot_username}" if config.bot_username else ""
    who = (message.from_user.first_name if message.from_user else "") or "игрок"
    prompt = (f"Игрок {who} написал в чате: «{txt}».\n"
              f"Ответь как ИИ Баран (коротко, дерзко). Ссылка-зазыв, если уместно: {link}")
    reply = await gemini_reply(config.gemini_api_key, config.gemini_model, SYSTEM, prompt)
    if reply:
        try:
            await message.reply(reply[:600])
        except Exception:  # noqa: BLE001
            log.debug("send fail", exc_info=True)
