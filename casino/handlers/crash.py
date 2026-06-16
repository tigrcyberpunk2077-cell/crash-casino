"""Игра Crash: выбор ставки, запуск раунда, вывод выигрыша."""

from __future__ import annotations

import uuid

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import Config
from ..db import Database
from ..keyboards import bet_menu, main_menu
from ..provably_fair import crash_point, generate_server_seed, hash_server_seed
from ..services.games import CrashGame, GameManager
from ..states import CrashStates
from ..units import format_ton, parse_amount, to_nano

router = Router(name="crash")


async def _bet_prompt(db: Database, user_id: int, config: Config) -> str:
    bal = await db.get_balance(user_id)
    return (
        "🚀 <b>CRASH</b>\n\n"
        f"Баланс: <b>{format_ton(bal)}</b>\n"
        f"Ставка: от {config.min_bet:g} до {config.max_bet:g} tTON\n\n"
        "Выбери ставку:"
    )


@router.message(Command("crash"))
async def cmd_crash(message: Message, db: Database, config: Config, games: GameManager) -> None:
    await db.get_or_create_user(message.from_user.id, message.from_user.username or "")
    if games.is_active(message.from_user.id):
        await message.answer("У тебя уже идёт раунд — заверши его сначала.")
        return
    await message.answer(await _bet_prompt(db, message.from_user.id, config),
                         reply_markup=bet_menu(""))


@router.callback_query(F.data == "menu:crash")
async def cb_crash(call: CallbackQuery, db: Database, config: Config, games: GameManager) -> None:
    if games.is_active(call.from_user.id):
        await call.answer("У тебя уже идёт раунд.", show_alert=True)
        return
    await db.get_or_create_user(call.from_user.id, call.from_user.username or "")
    await call.message.edit_text(await _bet_prompt(db, call.from_user.id, config),
                                 reply_markup=bet_menu(""))
    await call.answer()


@router.callback_query(F.data.startswith("bet:"))
async def cb_bet(call: CallbackQuery, state: FSMContext, bot: Bot, db: Database,
                 config: Config, games: GameManager) -> None:
    payload = call.data.split(":", 1)[1]
    if payload == "custom":
        await state.set_state(CrashStates.waiting_bet)
        await call.message.edit_text("✏️ Введи сумму ставки в tTON:")
        await call.answer()
        return
    bet_nano = to_nano(payload)
    await call.answer()
    await _launch(bot, db, games, config, call.from_user.id, call.message, bet_nano,
                  edit=True)


@router.message(CrashStates.waiting_bet, F.text)
async def custom_bet(message: Message, state: FSMContext, bot: Bot, db: Database,
                     config: Config, games: GameManager) -> None:
    bet_nano = parse_amount(message.text)
    await state.clear()
    if bet_nano is None:
        await message.answer("Неверная сумма. Введи положительное число.",
                             reply_markup=main_menu())
        return
    placeholder = await message.answer("🚀 Запускаю раунд…")
    await _launch(bot, db, games, config, message.from_user.id, placeholder, bet_nano,
                  edit=True)


@router.callback_query(F.data.startswith("cashout:"))
async def cb_cashout(call: CallbackQuery, games: GameManager) -> None:
    game_id = call.data.split(":", 1)[1]
    win = await games.cashout(call.from_user.id, game_id)
    await call.answer("💸 Забрал!" if win else "Поздно — раунд завершён.",
                      show_alert=not win)


async def _launch(bot: Bot, db: Database, games: GameManager, config: Config,
                  user_id: int, game_message: Message, bet_nano: int, *, edit: bool) -> None:
    """Проверки, списание ставки и старт живого раунда в game_message."""
    if games.is_active(user_id):
        await game_message.edit_text("У тебя уже идёт раунд.", reply_markup=main_menu())
        return

    min_bet, max_bet = to_nano(config.min_bet), to_nano(config.max_bet)
    if bet_nano < min_bet or bet_nano > max_bet:
        await game_message.edit_text(
            f"Ставка должна быть от {config.min_bet:g} до {config.max_bet:g} tTON.",
            reply_markup=main_menu(),
        )
        return

    new_balance = await db.try_debit(user_id, bet_nano, "bet", "crash")
    if new_balance is None:
        await game_message.edit_text(
            f"Недостаточно средств. Ставка {format_ton(bet_nano)} превышает баланс.\n"
            "Пополни через «Депозит».",
            reply_markup=main_menu(),
        )
        return

    # Provably-fair параметры раунда.
    user = await db.get_user(user_id)
    client_seed = user["client_seed"]
    nonce = await db.next_nonce(user_id)
    server_seed = generate_server_seed()
    cp = crash_point(server_seed, client_seed, nonce)

    game = CrashGame(
        user_id=user_id,
        chat_id=game_message.chat.id,
        message_id=game_message.message_id,
        game_id=uuid.uuid4().hex[:8],
        bet=bet_nano,
        crash_point=cp,
        server_seed=server_seed,
        server_seed_hash=hash_server_seed(server_seed),
        client_seed=client_seed,
        nonce=nonce,
        growth=config.multiplier_growth,
    )
    await games.start(game)
