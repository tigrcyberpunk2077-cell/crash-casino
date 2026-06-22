"""Старт, меню, помощь, provably-fair."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, WebAppInfo)

from ..config import Config
from ..db import Database
from ..keyboards import back_menu, main_menu
from ..provably_fair import generate_server_seed, hash_server_seed
from ..states import SeedStates
from ..units import format_ton, to_nano

router = Router(name="common")

WELCOME = (
    "🎰 <b>Crash Casino</b> (учебный демо-бот)\n\n"
    "⚠️ Это <b>не</b> азартная игра на реальные деньги. Валюта — тестовые "
    "монеты <b>tTON</b> без какой-либо ценности. Проект для изучения игровой "
    "логики, provably-fair и работы Telegram-бота.\n\n"
    "Игра <b>Crash</b>: множитель растёт от 1.00x — успей нажать «Забрать» до "
    "краша. Забрал на 2.00x → ставка ×2.\n\n"
    "Баланс: <b>{balance}</b>"
)

HELP = (
    "ℹ️ <b>Как играть</b>\n\n"
    "1. Пополни баланс тестовыми монетами (Депозит).\n"
    "2. Открой Crash, выбери ставку — начнётся раунд.\n"
    "3. Множитель растёт. Жми «Забрать» до краша, чтобы зафиксировать выигрыш.\n"
    "4. Не успел до краша — ставка сгорает.\n\n"
    "<b>Команды:</b> /start /crash /balance /help\n\n"
    "🎲 <b>Честность.</b> Перед раундом известен SHA-256 от server_seed. Точка "
    "краша = функция(server_seed, client_seed, nonce). После раунда server_seed "
    "раскрывается — можно проверить, что результат не подделан. House edge ~1%.\n\n"
    "🛟 Игра на реальные деньги может вызывать зависимость. Здесь её нет — только демо."
)


async def _menu_text(db: Database, user_id: int) -> str:
    bal = await db.get_balance(user_id)
    return WELCOME.format(balance=format_ton(bal))


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, db: Database, config: Config) -> None:
    user = message.from_user
    await db.get_or_create_user(user.id, user.username or user.full_name)
    arg = (command.args or "").strip()
    if arg.startswith("ref_"):
        await _apply_referral(message, db, config, user, arg[4:])
    await message.answer(await _menu_text(db, user.id), reply_markup=main_menu())


async def _apply_referral(message: Message, db: Database, config: Config, user, ref_str: str) -> None:
    """Бонус обоим за приглашение + уведомление пригласившему (один раз на игрока)."""
    try:
        ref_id = int(ref_str)
    except ValueError:
        return
    if ref_id <= 0 or ref_id == user.id:
        return
    if not await db.get_user(ref_id):
        return                                   # пригласивший не существует
    if not await db.set_referrer(user.id, ref_id):
        return                                   # реферер уже был — повторно не начисляем
    bonus = to_nano(config.referral_bonus)
    await db.credit(user.id, bonus, "referral", "приглашён другом")
    await db.credit(ref_id, bonus, "referral", f"пригласил {user.id}")
    await message.answer(f"🎁 Бонус за приглашение: <b>+{config.referral_bonus:g} tTON</b>!")
    try:
        await message.bot.send_message(
            ref_id,
            f"🎉 Твой друг присоединился к казино! Тебе начислено "
            f"<b>+{config.referral_bonus:g} tTON</b>. Зови ещё — бонус за каждого друга!",
        )
    except Exception:  # noqa: BLE001 — мог заблокировать бота
        pass


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, reply_markup=back_menu())


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(
        f"🪪 Твой Telegram ID: <code>{message.from_user.id}</code>\n\n"
        "Пришли его мне — включу для тебя раздел «Статистика»."
    )


@router.message(Command("app"))
async def cmd_app(message: Message, config: Config) -> None:
    url = config.webapp_url
    if url and url.startswith("https"):
        # Открываем по пути /play (синоним той же страницы): inline-кнопка сохраняет
        # путь, поэтому это всегда «новый» URL для Telegram — кэш WebView не подсунет
        # старую версию. Меню-кнопка так не умеет (Telegram режет путь к корню).
        fresh = url.rstrip("/") + "/play"
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🎰 Открыть казино", web_app=WebAppInfo(url=fresh))
        ]])
        await message.answer("Жми кнопку — откроется Mini App с анимацией 🚀", reply_markup=kb)
    else:
        await message.answer(
            "🎰 <b>Mini App</b>\n\n"
            "Чтобы открыть красивую веб-версию <b>внутри Telegram</b>, нужен публичный "
            "<b>https</b>-адрес (Telegram не пускает http/localhost).\n\n"
            "Локально проще всего через туннель cloudflared (см. README, раздел «Mini App»):\n"
            "1. <code>brew install cloudflared</code>\n"
            f"2. <code>cloudflared tunnel --url http://localhost:{config.webapp_port}</code>\n"
            "3. Полученный https-адрес впиши в <code>WEBAPP_URL</code> в .env и перезапусти бота.\n\n"
            f"А прямо сейчас дизайн можно посмотреть в браузере: "
            f"<code>http://localhost:{config.webapp_port}</code>"
        )


@router.callback_query(F.data == "menu:home")
async def cb_home(call: CallbackQuery, db: Database) -> None:
    await db.get_or_create_user(call.from_user.id, call.from_user.username or "")
    await call.message.edit_text(await _menu_text(db, call.from_user.id), reply_markup=main_menu())
    await call.answer()


@router.callback_query(F.data == "menu:help")
async def cb_help(call: CallbackQuery) -> None:
    await call.message.edit_text(HELP, reply_markup=back_menu())
    await call.answer()


@router.callback_query(F.data == "menu:fair")
async def cb_fair(call: CallbackQuery, db: Database) -> None:
    user = await db.get_or_create_user(call.from_user.id, call.from_user.username or "")
    # Покажем текущий commitment следующего раунда (демо seed).
    sample_seed = generate_server_seed()
    text = (
        "🎲 <b>Provably Fair</b>\n\n"
        f"Твой <b>client_seed</b>: <code>{user['client_seed']}</code>\n"
        f"Сыграно раундов (nonce): <b>{user['nonce']}</b>\n\n"
        "Точка краша считается так:\n"
        "<code>HMAC_SHA256(server_seed, \"client_seed:nonce\")</code>\n"
        "→ берём 13 hex, по формуле получаем множитель.\n\n"
        "Перед каждым раундом ты видишь SHA-256(server_seed). После — сам seed, "
        "и можешь пересчитать результат. Подделать невозможно.\n\n"
        f"Пример commitment: <code>{hash_server_seed(sample_seed)}</code>\n\n"
        "Отправь команду /seed чтобы задать свой client_seed."
    )
    await call.message.edit_text(text, reply_markup=back_menu())
    await call.answer()


@router.message(Command("seed"))
async def cmd_seed(message: Message, state: FSMContext) -> None:
    await state.set_state(SeedStates.waiting_seed)
    await message.answer("Отправь новый client_seed (любая строка до 64 символов):",
                         reply_markup=back_menu())


@router.message(SeedStates.waiting_seed, F.text)
async def set_seed(message: Message, state: FSMContext, db: Database) -> None:
    seed = message.text.strip()[:64]
    if not seed:
        await message.answer("Пустой seed. Попробуй ещё раз.")
        return
    await db.set_client_seed(message.from_user.id, seed)
    await state.clear()
    await message.answer(f"✅ client_seed обновлён: <code>{seed}</code>", reply_markup=main_menu())
