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
from aiogram.filters import Command, CommandObject
from aiogram.types import FSInputFile, Message

from ..config import Config
from ..db import Database
from ..llm import gemini_reply
from ..voice import tts_ogg

router = Router(name="group")
log = logging.getLogger("casino.baran")

# chat_id -> {"last": ts последнего сообщения, "idle": ts последнего idle-вброса}
GROUP_ACTIVITY: dict = {}
_last_reply: dict = {}     # chat_id -> ts последнего ответа (анти-спам)
CHATTY: set = set()        # чаты с «болтливым режимом» (Баран лезет сам и пишет в тишине)


async def load_chatty(db: Database) -> None:
    """Подгружает из БД чаты, где включён болтливый режим (переживает рестарты)."""
    try:
        for k in await db.kv_keys_prefix("baran:"):
            try:
                CHATTY.add(int(k.split(":", 1)[1]))
            except ValueError:
                pass
    except Exception:  # noqa: BLE001
        log.debug("load_chatty error", exc_info=True)
COOLDOWN = 16.0
KEYWORDS = ("баран", "казино", "11a", "11а", "крёстный", "мафи")
FALLBACKS = [
    "🐏 Меее! Чё пишешь — иди лучше в «11A» фишки спускать, салага.",
    "🐏 Я ИИ Баран, занят — кручу банк в казино «11A». Залетай, не ссы.",
    "🐏 Бе-е, скучно. Го в Crash или Мафию «11A», там веселее.",
    "🐏 Зови меня ИИ Бараном. И двигай в «11A» — удача сама себя не проиграет.",
]
NO_KEY_HINT = ("🐏 Меее! Мозги мне ещё не подключили (нет GEMINI_API_KEY). Скажи "
               "хозяину вписать ключ Gemini на Render — и я разойдусь по полной.")

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


@router.message(Command("baran"))
async def cmd_baran(message: Message, command: CommandObject, db: Database) -> None:
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.answer("🐏 Я ИИ Баран. Команда работает в группах: /baran on, /baran off")
        return
    arg = (command.args or "").strip().lower()
    cid = message.chat.id
    if arg == "on":
        CHATTY.add(cid)
        await db.kv_set(f"baran:{cid}", "1")
        await message.reply("🐏 Болтливый режим ВКЛ — теперь лезу сам и пишу, когда тихо.\n"
                            "Чтобы я слышал весь чат — выключи Privacy у бота: @BotFather → Bot Settings → "
                            "Group Privacy → Turn off, потом перезайди в группу.")
    elif arg == "off":
        CHATTY.discard(cid)
        await db.kv_del(f"baran:{cid}")
        await message.reply("🐏 Болтливый режим ВЫКЛ — отвечаю только когда тегаете @ или отвечаете мне.")
    else:
        st = "ВКЛ ✅" if cid in CHATTY else "ВЫКЛ ❌"
        await message.reply(f"🐏 Болтливый режим: {st}\nКоманды: /baran on — лезть самому, /baran off — только по тегу.")


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def on_group_message(message: Message, config: Config) -> None:
    now = time.time()
    GROUP_ACTIVITY.setdefault(message.chat.id, {"last": 0.0, "idle": 0.0})["last"] = now

    txt = message.text or message.caption
    if not txt or txt.startswith("/"):
        return
    me = (config.bot_username or "").lower()
    low = txt.lower()
    mentioned = bool(me) and ("@" + me) in low
    replied = bool(
        message.reply_to_message and message.reply_to_message.from_user
        and (message.reply_to_message.from_user.username or "").lower() == me
    )
    kw = any(w in low for w in KEYWORDS)
    addressed = mentioned or replied
    chatty = config.ai_baran_all or (message.chat.id in CHATTY)
    rnd = chatty and random.random() < config.ai_baran_chance
    if not (addressed or kw or rnd):
        return
    # на прямой тег/ответ — отвечаем всегда; «фоновые» триггеры держим на кулдауне
    if not addressed and now - _last_reply.get(message.chat.id, 0) < COOLDOWN:
        return
    _last_reply[message.chat.id] = now

    if not config.gemini_api_key:
        if addressed:
            await _deliver(message.bot, message.chat.id, NO_KEY_HINT, config)
        return
    link = f"https://t.me/{config.bot_username}" if config.bot_username else ""
    who = (message.from_user.first_name if message.from_user else "") or "игрок"
    reply = await _generate(config, f"Игрок {who} написал: «{txt}».\n"
                                    f"Ответь как ИИ Баран (коротко, дерзко). Ссылка-зазыв: {link}")
    if not reply and addressed:
        reply = random.choice(FALLBACKS)
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
        if not (config.ai_baran_all or chat_id in CHATTY):
            continue
        if now - info["last"] < idle_sec or now - info["idle"] < cooldown:
            continue
        info["idle"] = now
        info["last"] = now
        reply = await _generate(config, "В чате тишина, все притихли. Напиши задорную "
                                        "провокационную фразу как ИИ Баран, чтобы расшевелить "
                                        f"чат и зазвать в «11A». Ссылка: {link}")
        await _deliver(bot, chat_id, reply, config)
