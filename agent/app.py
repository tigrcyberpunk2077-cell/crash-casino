"""Основной процесс агента (простой режим: всё делает один бот aiogram).

Бот (@BotFather) одновременно:
  • присылает тебе черновики с кнопками ✅/✏️/❌ и слушает команды;
  • сам публикует одобренные посты в каналы, где он добавлен админом.

Никакого аккаунта/телефона/кодов Telegram не нужно. Плюс планировщик: по
«лучшему времени» (окно активных часов + пиковые часы) предлагает новый пост.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import shutil
import uuid
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

from . import db
from .config import Config, load_config
from .content import make_draft, make_reel
from .images import make_image
from .video import make_clip_video, make_video

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("agent")

SEP = "─" * 22
CAPTION_LIMIT = 1024  # лимит подписи к фото в Telegram

# Куда (в какой канал) складывать фото, которые присылает админ: {admin_id: channel_id}
_photo_target: dict = {}


# --- утилиты ---------------------------------------------------------------

def _target(ref: str):
    """Превращает сохранённый ref в chat_id для aiogram (@username или int)."""
    s = ref.strip()
    if s.lstrip("-").isdigit():
        return int(s)
    return s


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _rm(path) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def _media_path(cfg: Config, draft_id: int) -> str:
    return os.path.join(cfg.media_dir, f"draft_{draft_id}.jpg")


def _local_hour(cfg: Config) -> int:
    return (datetime.now(timezone.utc).hour + cfg.utc_offset) % 24


def _interval_elapsed(channel) -> bool:
    last = channel["last_posted_at"]
    if not last:
        return True
    try:
        prev = datetime.fromisoformat(last)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - prev).total_seconds() >= channel["interval_min"] * 60


def _should_post(channel, cfg: Config) -> bool:
    h = _local_hour(cfg)
    s, e = cfg.active_start, cfg.active_end
    in_window = (s <= h <= e) if s <= e else (h >= s or h <= e)  # окно может идти через полночь
    if not in_window:
        return False
    if not _interval_elapsed(channel):
        return False
    if cfg.peak_hours and h not in cfg.peak_hours:
        return False
    return True


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)


def _to_html(text: str) -> str:
    """Готовит текст поста к HTML-отправке: первая строка — жирный заголовок,
    **фразы** → жирный, всё остальное экранируется."""
    esc = html.escape(text, quote=False)
    esc = _BOLD_RE.sub(r"<b>\1</b>", esc)
    lines = esc.split("\n")
    for i, ln in enumerate(lines):
        if ln.strip():  # первую непустую строку делаем заголовком (жирным)
            lines[i] = "<b>" + ln.replace("<b>", "").replace("</b>", "") + "</b>"
            break
    return "\n".join(lines)


def _preview(channel_title: str, text: str, draft_id: int, angle: str) -> str:
    """HTML-подпись черновика для одобрения (мета + отформатированный пост)."""
    meta = html.escape(f"🆕 Черновик #{draft_id} → «{channel_title}»  (угол: {angle})", quote=False)
    return f"{meta}\n{SEP}\n\n{_to_html(_clip(text, 900))}"


def _kb(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"pub:{draft_id}"),
            InlineKeyboardButton(text="✏️ Другой вариант", callback_data=f"reg:{draft_id}"),
        ],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej:{draft_id}")],
    ])


# --- отправка черновика на одобрение ---------------------------------------

async def _send_approval(bot: Bot, admin_id: int, title: str, draft) -> Message:
    caption = _preview(title, draft["text"], draft["id"], draft["angle"])
    img = draft["image_path"]
    if img and os.path.exists(img):
        return await bot.send_photo(admin_id, FSInputFile(img), caption=caption,
                                    parse_mode="HTML", reply_markup=_kb(draft["id"]))
    return await bot.send_message(admin_id, caption, parse_mode="HTML",
                                  reply_markup=_kb(draft["id"]))


async def generate_and_send(bot: Bot, cfg: Config, channel) -> None:
    cid = channel["id"]
    title = channel["title"] or channel["ref"]
    niche = channel["topic"] or ""
    persona = channel["persona"] or ""
    try:
        recent = db.recent_published_texts(cid)
        text, angle = await make_draft(cfg, niche, persona, recent)
    except Exception as e:  # noqa: BLE001
        log.exception("Не удалось сгенерировать пост для канала %s", channel["ref"])
        await bot.send_message(cfg.admin_id, f"⚠️ Ошибка генерации для «{title}»: {e}")
        return

    draft_id = db.create_draft(cid, text, angle)
    if cfg.images_enabled:
        path = _media_path(cfg, draft_id)
        if await make_image(cfg, text, path, niche, persona):
            db.set_draft_image(draft_id, path)

    draft = db.get_draft(draft_id)
    msg = await _send_approval(bot, cfg.admin_id, title, draft)
    db.set_approval_msg(draft_id, msg.chat.id, msg.message_id)
    log.info("Черновик #%s для %s отправлен на одобрение", draft_id, channel["ref"])


# --- планировщик -----------------------------------------------------------

async def scheduler_loop(bot: Bot, cfg: Config) -> None:
    log.info(
        "Планировщик запущен | окно %02d–%02d (UTC%+d) | пики: %s | тик %s c",
        cfg.active_start, cfg.active_end, cfg.utc_offset,
        cfg.peak_hours or "любой час", cfg.scheduler_tick_sec,
    )
    while True:
        try:
            for ch in db.list_channels(only_active=True):
                if db.has_pending(ch["id"]):
                    continue
                if _should_post(ch, cfg):
                    await generate_and_send(bot, cfg, ch)
        except Exception:  # noqa: BLE001
            log.exception("Сбой в планировщике")
        await asyncio.sleep(cfg.scheduler_tick_sec)


# --- публикация в канал -----------------------------------------------------

async def _publish(bot: Bot, channel, draft) -> None:
    target = _target(channel["ref"])
    img, text = draft["image_path"], draft["text"]
    if img and os.path.exists(img):
        await bot.send_photo(target, FSInputFile(img),
                             caption=_to_html(_clip(text, 950)), parse_mode="HTML")
    else:
        await bot.send_message(target, _to_html(text),
                               parse_mode="HTML", disable_web_page_preview=True)


async def _finalize_msg(cb: CallbackQuery, status_plain: str, post_text: str) -> None:
    """Убирает кнопки и показывает итог (учитывая, что сообщение может быть фото)."""
    meta = html.escape(status_plain, quote=False)
    content = f"{meta}\n{SEP}\n\n{_to_html(_clip(post_text, 900))}"
    if cb.message.photo:
        await cb.message.edit_caption(caption=content, parse_mode="HTML", reply_markup=None)
    else:
        await cb.message.edit_text(content, parse_mode="HTML", reply_markup=None)


# --- обработчики -----------------------------------------------------------

def register_handlers(dp: Dispatcher, bot: Bot, cfg: Config) -> None:
    admin = F.from_user.id == cfg.admin_id

    @dp.callback_query(admin, F.data.regexp(r"^(pub|reg|rej):\d+$"))
    async def on_button(cb: CallbackQuery) -> None:
        action, raw = cb.data.split(":")
        draft_id = int(raw)
        draft = db.get_draft(draft_id)
        if draft is None:
            await cb.answer("Черновик не найден", show_alert=True)
            return
        channel = db.get_channel(draft["channel_id"])
        title = (channel["title"] or channel["ref"]) if channel else "?"

        if action == "pub":
            if draft["status"] != "pending":
                await cb.answer("Уже обработан")
                return
            try:
                await _publish(bot, channel, draft)
            except Exception as e:  # noqa: BLE001
                log.exception("Публикация не удалась")
                await cb.answer("Ошибка публикации", show_alert=True)
                await _finalize_msg(cb, f"❌ Не удалось в «{title}»: {e}", draft["text"])
                return
            db.mark_published(draft_id)
            db.touch_posted(draft["channel_id"])
            _rm(draft["image_path"])
            await _finalize_msg(cb, f"✅ Опубликовано в «{title}»", draft["text"])
            await cb.answer("Опубликовано")

        elif action == "rej":
            db.mark_rejected(draft_id)
            db.touch_posted(draft["channel_id"])
            _rm(draft["image_path"])
            await _finalize_msg(cb, f"❌ Отклонено (для «{title}»)", draft["text"])
            await cb.answer("Отклонено")

        elif action == "reg":
            # Переписываем только ТЕКСT (на ту же тему), фото остаётся прежним.
            niche = (channel["topic"] or "") if channel else ""
            persona = (channel["persona"] or "") if channel else ""
            try:
                recent = db.recent_published_texts(draft["channel_id"])
                text, angle = await make_draft(
                    cfg, niche, persona, recent,
                    exclude_angle=draft["angle"], brief=draft["brief"],
                )
            except Exception:  # noqa: BLE001
                await cb.answer("Ошибка генерации", show_alert=True)
                return
            db.set_draft_text(draft_id, text, angle)
            caption = _preview(title, text, draft_id, angle)
            if cb.message.photo:
                await cb.message.edit_caption(caption=caption, parse_mode="HTML",
                                              reply_markup=_kb(draft_id))
            else:
                await cb.message.edit_text(caption, parse_mode="HTML", reply_markup=_kb(draft_id))
            await cb.answer("Готов новый вариант")

    @dp.message(admin, Command("start", "help"))
    async def on_help(message: Message) -> None:
        await message.answer(
            "🤖 Агент каналов-персон\n\n"
            "Как работает: ты присылаешь боту ФОТО (в подписи можешь указать, про что пост) — "
            "бот пишет текст в голосе персоны канала и шлёт черновик. Жмёшь ✅ — публикует.\n\n"
            "Старт:\n"
            "1) добавь канал: перешли мне любой пост из канала (дам готовую команду) или\n"
            "   /addchannel @канал | ниша | персона\n"
            "2) /photos <id> — выбери канал для фото\n"
            "3) шли фото 📸 → одобряй черновики ✅/✏️/❌\n\n"
            "Команды:\n"
            "/channels — список каналов\n"
            "/persona <id> <описание> — изменить персону\n"
            "/photos <id> — куда слать фото\n"
            "/now <id> — пост с ИИ-картинкой (без твоего фото)\n"
            "/factory <id> [сколько] <тема> — пачка коротких видео (Reels/TikTok) с озвучкой\n"
            "/interval <id> <мин>, /pause <id>, /resume <id>"
        )

    @dp.message(admin, Command("addchannel"))
    async def on_add(message: Message, command: CommandObject) -> None:
        arg = (command.args or "").strip()
        if not arg:
            await message.answer(
                "Формат: /addchannel @канал | ниша | персона\n"
                "Пример: /addchannel @my | ставки на спорт | Кристина, 27, азартная и честная, "
                "учит управлять банком"
            )
            return
        parts = [p.strip() for p in arg.split("|")]
        ref = parts[0]
        niche = parts[1] if len(parts) > 1 else ""
        persona = parts[2] if len(parts) > 2 else ""
        title = ref
        try:
            chat = await bot.get_chat(_target(ref))
            title = chat.title or ref
        except Exception as e:  # noqa: BLE001
            await message.answer(
                f"⚠️ Не вижу канал {ref} ({e}).\n"
                "Добавь @{0} админом канала (право «Публикация сообщений»), потом повтори.".format(
                    (await bot.get_me()).username
                )
            )
            return
        cid = db.add_channel(ref, title, niche, persona, cfg.default_interval_min)
        await message.answer(
            f"✅ Канал «{title}» добавлен (#{cid}). Интервал: {cfg.default_interval_min} мин.\n"
            f"Ниша: {niche or '— (дефолт)'}\n"
            f"Персона: {persona or '— (дефолт)'}\n\n"
            f"Проверь сразу:  /now {cid}\n"
            "(убедись, что бот — админ канала с правом постить)"
        )

    @dp.message(admin, Command("persona"))
    async def on_persona(message: Message, command: CommandObject) -> None:
        arg = (command.args or "").strip()
        parts = arg.split(maxsplit=1)
        if len(parts) != 2 or not parts[0].isdigit():
            await message.answer("Формат: /persona <id канала> <описание персоны>")
            return
        cid = int(parts[0])
        if db.get_channel(cid) is None:
            await message.answer("Канал не найден")
            return
        db.set_persona(cid, parts[1].strip())
        await message.answer(f"✅ Персона канала #{cid} обновлена.")

    @dp.message(admin, Command("channels"))
    async def on_list(message: Message) -> None:
        rows = db.list_channels()
        if not rows:
            await message.answer("Каналов пока нет. Добавь: /addchannel @канал | ниша | персона")
            return
        lines = []
        for r in rows:
            flag = "🟢" if r["active"] else "⏸"
            lines.append(
                f"{flag} #{r['id']} «{r['title'] or r['ref']}» ({r['ref']}) · {r['interval_min']} мин\n"
                f"    ниша: {r['topic'] or '—'}\n"
                f"    персона: {_clip(r['persona'] or '—', 80)}\n"
                f"    посл.: {r['last_posted_at'] or '—'}"
            )
        await message.answer("\n".join(lines))

    @dp.message(admin, Command("interval"))
    async def on_interval(message: Message, command: CommandObject) -> None:
        parts = (command.args or "").split()
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            await message.answer("Формат: /interval <id> <минуты>")
            return
        db.set_interval(int(parts[0]), int(parts[1]))
        await message.answer(f"✅ Интервал канала #{parts[0]} → {parts[1]} мин")

    @dp.message(admin, Command("pause"))
    async def on_pause(message: Message, command: CommandObject) -> None:
        arg = (command.args or "").strip()
        if not arg.isdigit():
            await message.answer("Формат: /pause <id>")
            return
        db.set_active(int(arg), False)
        await message.answer(f"⏸ На паузе: канал #{arg}")

    @dp.message(admin, Command("resume"))
    async def on_resume(message: Message, command: CommandObject) -> None:
        arg = (command.args or "").strip()
        if not arg.isdigit():
            await message.answer("Формат: /resume <id>")
            return
        db.set_active(int(arg), True)
        await message.answer(f"🟢 Включён: канал #{arg}")

    @dp.message(admin, Command("now"))
    async def on_now(message: Message, command: CommandObject) -> None:
        arg = (command.args or "").strip()
        if not arg.isdigit():
            await message.answer("Формат: /now <id>")
            return
        ch = db.get_channel(int(arg))
        if ch is None:
            await message.answer("Канал не найден")
            return
        await message.answer("⏳ Генерирую…")
        await generate_and_send(bot, cfg, ch)

    @dp.message(admin, Command("factory"))
    async def on_factory(message: Message, command: CommandObject) -> None:
        parts = (command.args or "").split()
        if not parts or not parts[0].isdigit():
            await message.answer(
                "Формат: /factory <id> [сколько] <тема>\n"
                "Пример: /factory 1 3 ошибки новичков в трейдинге\n"
                "Сделаю пачку коротких видео (Reels/TikTok) с озвучкой и субтитрами."
            )
            return
        cid = int(parts[0])
        rest = parts[1:]
        n = 3
        if rest and rest[0].isdigit():
            n = max(1, min(5, int(rest[0])))
            rest = rest[1:]
        brief = " ".join(rest) or None
        ch = db.get_channel(cid)
        if ch is None:
            await message.answer("Канал не найден (список — /channels).")
            return
        niche, persona = ch["topic"] or "", ch["persona"] or ""
        fdir = os.path.join(cfg.media_dir, f"factory_ch{cid}")
        os.makedirs(fdir, exist_ok=True)

        mode = "видео-клипы Pexels" if cfg.pexels_api_key else "статичные картинки"
        await message.answer(f"🏭 Делаю {n} видео по теме «{brief or 'разное'}» ({mode}). Пару минут…")
        made = 0
        for i in range(n):
            try:
                script = await make_reel(cfg, niche, persona, brief=brief)
            except Exception as e:  # noqa: BLE001
                await message.answer(f"⚠️ Видео {i + 1}: ошибка текста: {e}")
                continue
            out = os.path.join(fdir, f"reel_{uuid.uuid4().hex}.mp4")
            work = os.path.join(fdir, f"w_{i}")
            bg = None
            if cfg.pexels_api_key:
                ok = await make_clip_video(
                    script, niche, out, el_key=cfg.elevenlabs_api_key,
                    el_voice=cfg.elevenlabs_voice_id, pexels_key=cfg.pexels_api_key, work_dir=work,
                )
            else:
                bg = os.path.join(fdir, f"bg_{uuid.uuid4().hex}.jpg")
                if not (cfg.images_enabled and await make_image(cfg, script, bg, niche, persona)):
                    await message.answer(f"⚠️ Видео {i + 1}: не вышла картинка, пропускаю")
                    continue
                ok = await make_video(script, [bg], out, work_dir=work,
                                      el_key=cfg.elevenlabs_api_key, el_voice=cfg.elevenlabs_voice_id)
            if ok:
                made += 1
                await bot.send_video(cfg.admin_id, FSInputFile(out),
                                     caption=_clip(f"🎬 {i + 1}/{n}\n\n{script}", 1000))
                _rm(out)
            else:
                await message.answer(f"⚠️ Видео {i + 1}: не собралось")
            _rm(bg)
            shutil.rmtree(work, ignore_errors=True)
        await message.answer(
            f"🏭 Готово: {made}/{n}. Скачивай, заливай в Reels/TikTok, "
            "трендовый звук накинь в приложении."
        )

    @dp.message(admin, F.forward_origin)
    async def on_forward(message: Message) -> None:
        """Переслал пост из канала → подсказываем его id и готовую команду."""
        chat = getattr(message.forward_origin, "chat", None)
        if chat is None or chat.type not in ("channel", "supergroup"):
            return
        title = chat.title or str(chat.id)
        ref = f"@{chat.username}" if chat.username else str(chat.id)
        await message.answer(
            f"📡 Это канал «{title}» (id {chat.id}).\n\n"
            "Чтобы добавить — скопируй и поправь нишу/персону:\n"
            f"/addchannel {ref} | трейдинг для новичков | Алина, 26, тёплый наставник, объясняет просто"
        )

    @dp.message(admin, Command("photos"))
    async def on_photos(message: Message, command: CommandObject) -> None:
        arg = (command.args or "").strip()
        if not arg.isdigit():
            await message.answer(
                "Формат: /photos <id канала> — потом просто шли мне фото для этого канала.\n"
                "В подписи к фото можешь написать, ПРО ЧТО пост (или без подписи — придумаю тему сам).\n"
                "Список каналов — /channels."
            )
            return
        cid = int(arg)
        if db.get_channel(cid) is None:
            await message.answer("Канал не найден (список — /channels).")
            return
        _photo_target[message.from_user.id] = cid
        await message.answer(
            f"📸 Ок! Шли фото для канала #{cid}.\n"
            "К каждому фото я напишу текст в голосе персоны и пришлю черновик на одобрение.\n"
            "Подпись к фото = про что пост (необязательно)."
        )

    @dp.message(admin, F.photo)
    async def on_photo(message: Message) -> None:
        cid = _photo_target.get(message.from_user.id)
        if cid is None:
            rows = db.list_channels()
            if len(rows) == 1:
                cid = rows[0]["id"]
        ch = db.get_channel(cid) if cid else None
        if ch is None:
            await message.answer(
                "Для какого канала это фото? Сначала укажи: /photos <id> (список — /channels)."
            )
            return

        brief = (message.caption or "").strip() or None
        await message.answer("⏳ Пишу текст к фото…")

        # Сохраняем присланное фото (берём максимальное разрешение).
        dirp = os.path.join(cfg.media_dir, f"ch{cid}")
        os.makedirs(dirp, exist_ok=True)
        path = os.path.join(dirp, f"{uuid.uuid4().hex}.jpg")
        try:
            await bot.download(message.photo[-1], destination=path)
        except Exception as e:  # noqa: BLE001
            await message.answer(f"⚠️ Не смог скачать фото: {e}")
            return

        try:
            recent = db.recent_published_texts(cid)
            text, angle = await make_draft(
                cfg, ch["topic"] or "", ch["persona"] or "", recent, brief=brief
            )
        except Exception as e:  # noqa: BLE001
            _rm(path)
            await message.answer(f"⚠️ Ошибка генерации текста: {e}")
            return

        draft_id = db.create_draft(cid, text, angle, brief=brief)
        db.set_draft_image(draft_id, path)
        fresh = db.get_draft(draft_id)
        msg = await _send_approval(bot, cfg.admin_id, ch["title"] or ch["ref"], fresh)
        db.set_approval_msg(draft_id, msg.chat.id, msg.message_id)


# --- сидинг каналов (для переживания редеплоя на сервере) ------------------

async def seed_channels(bot: Bot, cfg: Config) -> None:
    for entry in cfg.channels_seed:
        ref = str(entry["ref"]).strip()
        if db.channel_exists(ref):
            continue
        niche = str(entry.get("topic", "") or entry.get("niche", "")).strip()
        persona = str(entry.get("persona", "")).strip()
        try:
            interval = int(entry.get("interval", cfg.default_interval_min))
        except (TypeError, ValueError):
            interval = cfg.default_interval_min
        title = ref
        try:
            chat = await bot.get_chat(_target(ref))
            title = chat.title or ref
        except Exception as e:  # noqa: BLE001 — добавим всё равно
            log.warning("seed: не вижу канал %s (%s) — добавлю по ref", ref, e)
        db.add_channel(ref, title, niche, persona, interval)
        log.info("seed: канал %s добавлен", ref)


# --- точка входа -----------------------------------------------------------

async def run() -> None:
    cfg = load_config()
    db.init_db(cfg.db_path)

    bot = Bot(cfg.bot_token)
    dp = Dispatcher()
    register_handlers(dp, bot, cfg)
    await seed_channels(bot, cfg)

    me = await bot.get_me()
    log.info("Бот: @%s | LLM: %s | авто-постинг: %s",
             me.username, cfg.llm_provider, "вкл" if cfg.auto_post else "выкл (жду фото)")
    try:
        await bot.send_message(cfg.admin_id, "🤖 Агент запущен. Команды — /help")
    except Exception as e:  # noqa: BLE001 — бот не может писать первым, если не нажал Start
        log.warning("Не смог написать админу (%s). Открой бота и нажми Start.", e)

    if cfg.auto_post:
        if cfg.peak_hours:
            s, e = cfg.active_start, cfg.active_end
            in_win = (lambda h: s <= h <= e) if s <= e else (lambda h: h >= s or h <= e)
            if not any(in_win(h) for h in cfg.peak_hours):
                log.warning(
                    "Пиковые часы %s вне окна %02d–%02d — посты НЕ будут выходить! "
                    "Поправь AGENT_PEAK_HOURS / AGENT_ACTIVE_HOURS.",
                    cfg.peak_hours, s, e,
                )
        asyncio.create_task(scheduler_loop(bot, cfg))
    else:
        log.info("Авто-постинг выключен — присылай фото боту; /now — сгенерировать вручную.")

    await dp.start_polling(bot)


def main() -> None:
    asyncio.run(run())
