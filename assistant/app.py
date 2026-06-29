"""Личный авто-ответчик: Telethon userbot (твой аккаунт) + управляющий бот (aiogram).

Друг из whitelist пишет тебе → ИИ готовит ответ → бот присылает черновик с
кнопками ✅ Текстом / 🎤 Голосом / ✏️ Переписать / ✖️ Пропустить.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from agent.llm import generate_post

from . import config, db
from .reply import make_reply
from .voicegen import clone_voice, tts_ogg

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("assistant")


def _kb(did: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Текстом", callback_data=f"t:{did}"),
         InlineKeyboardButton(text="🎤 Голосом", callback_data=f"v:{did}")],
        [InlineKeyboardButton(text="✏️ Переписать", callback_data=f"r:{did}"),
         InlineKeyboardButton(text="✖️ Пропустить", callback_data=f"x:{did}")],
    ])


async def run() -> None:
    cfg = config.load(require_session=False)   # без сессии → тест-режим (бот-песочница)
    db.init(cfg.db_path)
    acfg = cfg.agent
    admin = acfg.admin_id
    workdir = os.path.dirname(os.path.abspath(cfg.db_path)) or "."

    # клиент создаём всегда (нужен для регистрации обработчика), но подключаем —
    # только в полном режиме (есть сессия и api_id). Иначе работает тест-режим.
    user = TelegramClient(StringSession(cfg.session), cfg.api_id or 1, cfg.api_hash or "0" * 32)
    bot = Bot(cfg.bot_token)
    dp = Dispatcher()

    me = None
    full = bool(cfg.session and cfg.api_id and cfg.api_hash)
    if full:
        try:
            await user.connect()
            if await user.is_user_authorized():
                me = await user.get_me()
            else:
                full = False
                log.warning("Сессия недействительна → ТЕСТ-режим. Перелогинься: python -m assistant.login")
        except Exception as e:  # noqa: BLE001
            full = False
            log.warning("Userbot не поднялся (%s) → ТЕСТ-режим.", e)

    # ---------- Telethon: входящие сообщения от друзей ----------
    @user.on(events.NewMessage(incoming=True))
    async def on_incoming(event):  # noqa: ANN001
        if not event.is_private or event.out:
            return
        sid = event.sender_id
        if not db.is_allowed(sid):
            if not db.kv_get(f"seen:{sid}"):           # уведомить один раз про нового
                db.kv_set(f"seen:{sid}", "1")
                try:
                    s = await event.get_sender()
                    nm = (getattr(s, "first_name", "") or "")
                    if getattr(s, "username", None):
                        nm += f" @{s.username}"
                except Exception:  # noqa: BLE001
                    nm = str(sid)
                await bot.send_message(
                    admin, f"✉️ Тебе пишет {nm or sid} (id {sid}).\n"
                           f"Включить авто-ответы для него? — /allow {sid}")
            return
        if db.kv_get("enabled", "1") != "1":
            return

        history = []
        async for m in user.iter_messages(event.chat_id, limit=12):
            if m.text:
                history.append((bool(m.out), m.text))
        history.reverse()
        try:
            s = await event.get_sender()
            name = getattr(s, "first_name", "") or "друг"
        except Exception:  # noqa: BLE001
            name = "друг"
        try:
            reply = await make_reply(acfg, db.kv_get("profile", ""), name, history)
        except Exception as e:  # noqa: BLE001
            log.exception("Ошибка генерации ответа")
            await bot.send_message(admin, f"⚠️ Не смог придумать ответ для {name}: {e}")
            return
        did = db.add_draft(event.chat_id, name, event.raw_text or "", reply)
        await bot.send_message(
            admin, f"💬 {name}: {(event.raw_text or '')[:300]}\n\n📝 Ответ:\n{reply}",
            reply_markup=_kb(did))

    # ---------- aiogram: кнопки под черновиком ----------
    @dp.callback_query(F.from_user.id == admin, F.data.regexp(r"^[tvrx]:\d+$"))
    async def on_btn(cb: CallbackQuery) -> None:
        act, raw = cb.data.split(":")
        d = db.get_draft(int(raw))
        if d is None:
            await cb.answer("Черновик не найден", show_alert=True)
            return
        did, chat_id, name, reply = d["id"], d["chat_id"], d["name"], d["reply"]

        if act == "t":
            try:
                async with user.action(chat_id, "typing"):   # «печатает…» + пауза для естественности
                    await asyncio.sleep(min(2 + len(reply) * 0.04, 7) + random.uniform(0, 1.5))
                await user.send_message(chat_id, reply)
            except Exception as e:  # noqa: BLE001
                await cb.answer("Ошибка отправки", show_alert=True)
                await cb.message.edit_text(f"⚠️ Не отправилось ({name}): {e}")
                return
            db.set_draft(did, status="sent")
            await cb.message.edit_text(f"✅ Отправлено {name}:\n{reply}")
            await cb.answer("Отправлено")

        elif act == "v":
            vid = db.kv_get("voice_id")
            if not vid:
                await cb.answer("Сначала склонируй голос: /clonevoice", show_alert=True)
                return
            ogg = os.path.join(workdir, f"voice_{did}.ogg")
            if not await tts_ogg(cfg.elevenlabs_api_key, vid, reply, ogg, workdir):
                await cb.answer("Ошибка озвучки", show_alert=True)
                return
            try:
                async with user.action(chat_id, "record-voice"):   # «записывает голосовое…» + пауза
                    await asyncio.sleep(min(2 + len(reply) * 0.03, 6) + random.uniform(0, 1.5))
                await user.send_file(chat_id, ogg, voice_note=True)
            except Exception as e:  # noqa: BLE001
                await cb.answer("Ошибка отправки", show_alert=True)
                await cb.message.edit_text(f"⚠️ Голосовое не отправилось ({name}): {e}")
                return
            finally:
                try:
                    os.remove(ogg)
                except OSError:
                    pass
            db.set_draft(did, status="sent_voice")
            await cb.message.edit_text(f"🎤 Голосовое отправлено {name}:\n{reply}")
            await cb.answer("Отправлено голосом")

        elif act == "r":
            try:
                new = (await generate_post(
                    acfg,
                    "Перефразируй сообщение от первого лица: другой короткий дружеский вариант "
                    "того же смысла, живым разговорным языком. Только текст ответа.",
                    reply,
                )).strip()
            except Exception:  # noqa: BLE001
                await cb.answer("Ошибка генерации", show_alert=True)
                return
            db.set_draft(did, reply=new)
            await cb.message.edit_text(
                f"💬 {name}: {(d['incoming'] or '')[:300]}\n\n📝 Ответ:\n{new}", reply_markup=_kb(did))
            await cb.answer("Новый вариант")

        elif act == "x":
            db.set_draft(did, status="skipped")
            await cb.message.edit_text(f"✖️ Пропущено ({name})")
            await cb.answer("Ок")

    # ---------- команды ----------
    @dp.message(F.from_user.id == admin, Command("start", "help"))
    async def on_help(m: Message) -> None:
        await m.answer(
            "🤖 Личный авто-ответчик\n\n"
            "Друзья из списка пишут тебе → я предлагаю ответ → жмёшь ✅ текстом или 🎤 голосом.\n\n"
            "/allow <id или @user> — вести этого друга\n"
            "/deny <id> — убрать\n"
            "/list — кого веду\n"
            "/me <текст> — что про тебя учитывать (стиль, факты, занятость)\n"
            "/clonevoice — затем пришли голосовое 1–2 мин, склонирую твой голос\n"
            "/on  /off — включить/выключить предложку ответов\n\n"
            "Когда тебе напишет новый человек — я разово спрошу, добавлять ли его."
        )

    @dp.message(F.from_user.id == admin, Command("allow"))
    async def on_allow(m: Message, command: CommandObject) -> None:
        arg = (command.args or "").strip()
        if not arg:
            await m.answer("Формат: /allow <id или @username>")
            return
        try:
            target = int(arg) if arg.lstrip("-").isdigit() else arg
            ent = await user.get_entity(target)
            nm = getattr(ent, "first_name", "") or str(getattr(ent, "id", arg))
            db.allow(ent.id, nm)
            await m.answer(f"✅ Веду {nm} (id {ent.id})")
        except Exception as e:  # noqa: BLE001
            await m.answer(f"Не нашёл {arg}: {e}")

    @dp.message(F.from_user.id == admin, Command("deny"))
    async def on_deny(m: Message, command: CommandObject) -> None:
        arg = (command.args or "").strip()
        if not arg.lstrip("-").isdigit():
            await m.answer("Формат: /deny <id>")
            return
        db.deny(int(arg))
        await m.answer(f"Убрал id {arg} из авто-ответов")

    @dp.message(F.from_user.id == admin, Command("list"))
    async def on_list(m: Message) -> None:
        rows = db.list_allowed()
        await m.answer("\n".join(f"• {r['name']} — id {r['chat_id']}" for r in rows)
                       or "Список пуст. Добавь: /allow <id или @user>")

    @dp.message(F.from_user.id == admin, Command("me"))
    async def on_me(m: Message, command: CommandObject) -> None:
        db.kv_set("profile", (command.args or "").strip())
        await m.answer("✅ Обновил, что про тебя учитывать.")

    @dp.message(F.from_user.id == admin, Command("on"))
    async def on_on(m: Message) -> None:
        db.kv_set("enabled", "1")
        await m.answer("🟢 Предложка ответов включена")

    @dp.message(F.from_user.id == admin, Command("off"))
    async def on_off(m: Message) -> None:
        db.kv_set("enabled", "0")
        await m.answer("⏸ Предложка ответов выключена")

    @dp.message(F.from_user.id == admin, Command("clonevoice"))
    async def on_clonevoice(m: Message) -> None:
        if not cfg.elevenlabs_api_key:
            await m.answer("Нет ELEVENLABS_API_KEY в .env")
            return
        db.kv_set("await_clone", "1")
        await m.answer("🎤 Пришли голосовое сообщение на 1–2 минуты (начитай любой текст) — склонирую твой голос.")

    @dp.message(F.from_user.id == admin, F.voice | F.audio)
    async def on_voice(m: Message) -> None:
        if db.kv_get("await_clone") != "1":
            return
        db.kv_set("await_clone", "0")
        await m.answer("⏳ Клонирую голос…")
        src = os.path.join(workdir, "voice_sample.ogg")
        try:
            await bot.download(m.voice or m.audio, destination=src)
        except Exception as e:  # noqa: BLE001
            await m.answer(f"⚠️ Не смог скачать запись: {e}")
            return
        vid = await clone_voice(cfg.elevenlabs_api_key, f"Tigran_{admin}", src)
        if vid:
            db.kv_set("voice_id", vid)
            await m.answer("✅ Голос склонирован! Теперь кнопка 🎤 «Голосом» работает.")
        else:
            await m.answer("⚠️ Не вышло. Нужна запись ~1–2 минуты чистого голоса. Повтори: /clonevoice")

    # ТЕСТ-песочница: админ пишет боту как «друг» → бот отвечает твоим стилем (и голосом).
    # Регистрируем последним, чтобы команды ловились своими хэндлерами.
    @dp.message(F.from_user.id == admin, F.text)
    async def on_test(m: Message) -> None:
        if (m.text or "").startswith("/"):
            return
        try:
            reply = await make_reply(acfg, db.kv_get("profile", ""), "друг", [(False, m.text)])
        except Exception as e:  # noqa: BLE001
            await m.answer(f"⚠️ Ошибка: {e}")
            return
        await m.answer(f"📝 Так бы ответил ты:\n{reply}")
        vid = db.kv_get("voice_id")
        if vid and cfg.elevenlabs_api_key:
            from aiogram.types import FSInputFile
            ogg = os.path.join(workdir, "test_voice.ogg")
            if await tts_ogg(cfg.elevenlabs_api_key, vid, reply, ogg, workdir):
                try:
                    await bot.send_voice(admin, FSInputFile(ogg))
                except Exception:  # noqa: BLE001
                    pass
                try:
                    os.remove(ogg)
                except OSError:
                    pass

    if full:
        mode = "полный режим — отвечаю твоим друзьям из списка"
    else:
        mode = ("ТЕСТ-режим 🧪 — напиши мне что-нибудь, как будто ты друг, и я отвечу твоим стилем.\n"
                "Полные ответы реальным друзьям включатся после входа аккаунтом (api_id/hash + логин).")
    try:
        await bot.send_message(admin, f"🤖 Личный авто-ответчик запущен.\n{mode}\n\n/help — команды")
    except Exception as e:  # noqa: BLE001
        log.warning("Не смог написать админу: %s", e)
    log.info("assistant up | режим: %s", "full" if full else "test")

    if full:
        await asyncio.gather(user.run_until_disconnected(), dp.start_polling(bot))
    else:
        await dp.start_polling(bot)


def main() -> None:
    asyncio.run(run())
