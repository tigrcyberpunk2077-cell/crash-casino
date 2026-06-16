"""Баланс, депозит, faucet, вывод."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import Config
from ..db import Database
from ..keyboards import back_menu, deposit_kb, main_menu
from ..states import WithdrawStates
from ..units import format_ton, parse_amount, to_nano
from ..wallet import WalletProvider

router = Router(name="balance")


def _fmt_kind(kind: str) -> str:
    return {
        "faucet": "🚰 кран", "deposit": "🪙 депозит", "withdraw": "🏧 вывод",
        "bet": "🎯 ставка", "win": "💸 выигрыш",
    }.get(kind, kind)


async def _balance_text(db: Database, user_id: int) -> str:
    bal = await db.get_balance(user_id)
    txs = await db.recent_transactions(user_id, 8)
    lines = [f"💰 <b>Баланс:</b> {format_ton(bal)}\n"]
    if txs:
        lines.append("Последние операции:")
        for t in txs:
            sign = "+" if t["amount"] >= 0 else "−"
            lines.append(f"  {_fmt_kind(t['kind'])}: {sign}{format_ton(abs(t['amount']))}")
    else:
        lines.append("Операций пока нет. Пополни баланс через «Депозит».")
    return "\n".join(lines)


@router.message(Command("balance"))
async def cmd_balance(message: Message, db: Database) -> None:
    await db.get_or_create_user(message.from_user.id, message.from_user.username or "")
    await message.answer(await _balance_text(db, message.from_user.id), reply_markup=main_menu())


@router.callback_query(F.data == "menu:balance")
async def cb_balance(call: CallbackQuery, db: Database) -> None:
    await call.message.edit_text(await _balance_text(db, call.from_user.id), reply_markup=main_menu())
    await call.answer()


@router.callback_query(F.data == "menu:deposit")
async def cb_deposit(call: CallbackQuery, wallet: WalletProvider, config: Config) -> None:
    text = await wallet.deposit_instructions(call.from_user.id)
    await call.message.edit_text(text, reply_markup=deposit_kb(config.wallet_provider))
    await call.answer()


@router.callback_query(F.data == "faucet:claim")
async def cb_faucet(call: CallbackQuery, db: Database, config: Config) -> None:
    user_id = call.from_user.id
    await db.get_or_create_user(user_id, call.from_user.username or "")
    left = await db.faucet_seconds_left(user_id, config.faucet_cooldown_sec)
    if left > 0:
        hrs = left // 3600
        mins = (left % 3600) // 60
        await call.answer(f"Кран будет доступен через {hrs}ч {mins}м", show_alert=True)
        return
    amount = to_nano(config.faucet_amount)
    new_balance = await db.credit(user_id, amount, "faucet")
    await db.mark_faucet(user_id)
    await call.message.edit_text(
        f"🚰 Начислено <b>{format_ton(amount)}</b>!\n"
        f"Баланс: <b>{format_ton(new_balance)}</b>",
        reply_markup=main_menu(),
    )
    await call.answer("Монеты получены!")


# --- вывод (только для on-chain провайдера) ---

@router.callback_query(F.data == "menu:withdraw")
async def cb_withdraw(call: CallbackQuery, wallet: WalletProvider, state: FSMContext) -> None:
    if not wallet.supports_onchain:
        await call.message.edit_text(
            "🏧 В демо-режиме (faucet) вывод недоступен — это виртуальные фишки.\n\n"
            "Чтобы выводить тестовые монеты on-chain, включи провайдер TON testnet "
            "(см. README).",
            reply_markup=back_menu(),
        )
        await call.answer()
        return
    await state.set_state(WithdrawStates.waiting_address)
    await call.message.edit_text(
        "🏧 <b>Вывод tTON</b>\n\nОтправь адрес получателя в сети TON testnet:",
        reply_markup=back_menu(),
    )
    await call.answer()


@router.message(WithdrawStates.waiting_address, F.text)
async def withdraw_address(message: Message, state: FSMContext) -> None:
    address = message.text.strip()
    if len(address) < 40:
        await message.answer("Похоже, это не адрес TON. Отправь корректный адрес.")
        return
    await state.update_data(address=address)
    await state.set_state(WithdrawStates.waiting_amount)
    await message.answer("Сумма вывода в tTON:")


@router.message(WithdrawStates.waiting_amount, F.text)
async def withdraw_amount(message: Message, state: FSMContext, db: Database,
                          wallet: WalletProvider) -> None:
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer("Неверная сумма. Введи положительное число.")
        return
    data = await state.get_data()
    address = data["address"]
    await state.clear()

    user_id = message.from_user.id
    # Сначала резервируем (списываем) средства, затем шлём on-chain.
    new_balance = await db.try_debit(user_id, amount, "withdraw", address)
    if new_balance is None:
        await message.answer("Недостаточно средств для вывода.", reply_markup=main_menu())
        return

    result = await wallet.withdraw(user_id, address, amount)
    if not result.ok:
        # Возврат средств при неудаче.
        await db.credit(user_id, amount, "win", "withdraw refund")
        await message.answer(f"❌ {result.message}\nСредства возвращены на баланс.",
                             reply_markup=main_menu())
        return
    await message.answer(
        f"✅ {result.message}\n"
        + (f"tx: <code>{result.tx_hash}</code>\n" if result.tx_hash else "")
        + f"Остаток: <b>{format_ton(new_balance)}</b>",
        reply_markup=main_menu(),
    )
