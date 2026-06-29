"""Точка входа: сборка и запуск бота."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (BotCommand, InlineKeyboardButton,
                           InlineKeyboardMarkup, MenuButtonWebApp, WebAppInfo)

from .config import load_config
from .db import Database
from .handlers import (balance_router, common_router, crash_router,
                       group_router)
from .services.games import GameManager
from .wallet import build_wallet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("casino")


async def _set_commands(bot: Bot) -> None:
    await bot.set_my_commands([
        BotCommand(command="start", description="Меню"),
        BotCommand(command="app", description="🎰 Открыть казино (Mini App)"),
        BotCommand(command="crash", description="Играть в Crash (в чате)"),
        BotCommand(command="balance", description="Баланс"),
        BotCommand(command="seed", description="Сменить client_seed"),
        BotCommand(command="help", description="Помощь и честность"),
    ])


async def _setup_menu_button(bot: Bot, url) -> None:
    """Кнопка-меню рядом с полем ввода, открывающая Mini App (нужен https-URL)."""
    if url and url.startswith("https"):
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="🎰 Казино", web_app=WebAppInfo(url=url))
        )


REMIND_TEXT = (
    "🤠 Соскучились по «Дикому Западу»?\n\n"
    "Залетай — крутани слот 🎰, рискни в Crash 🚀 или поставь в «Забеге» 🐏. "
    "Удача ждёт!"
)


async def _reminder_loop(bot: Bot, db: Database, config) -> None:
    """Раз в N минут пишет неактивным игрокам «возвращайся» (анти-спам: 1 раз в idle)."""
    idle = config.reminder_idle_hours * 3600
    kb = None
    if config.webapp_url and config.webapp_url.startswith("https"):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="🎰 Открыть казино",
            web_app=WebAppInfo(url=config.webapp_url.rstrip("/") + "/play"))]])
    while True:
        await asyncio.sleep(max(60, config.reminder_interval_min * 60))
        try:
            ids = await db.due_for_remind(idle, config.reminder_batch)
            if not ids:
                continue
            for uid in ids:
                try:
                    await bot.send_message(uid, REMIND_TEXT, reply_markup=kb)
                except Exception:  # noqa: BLE001 — заблокировал бота / нет чата
                    pass
                await asyncio.sleep(0.05)
            await db.mark_reminded(ids)
            log.info("Напоминания отправлены: %d игрокам", len(ids))
        except Exception:  # noqa: BLE001
            log.debug("reminder loop error", exc_info=True)


async def _run_polling(bot: Bot, dp: Dispatcher, db: Database, config, wallet) -> None:
    """Локальный режим: бот сам опрашивает Telegram, веб-сервер — отдельно."""
    runner = None
    if config.webapp_enabled:
        from .webapp.server import start_webapp
        runner = await start_webapp(config, db)
    log.info("Режим polling. Кошелёк: %s | Mini App: %s",
             config.wallet_provider,
             config.webapp_url or f"http://localhost:{config.webapp_port} (локально)")
    try:
        await dp.start_polling(bot)
    finally:
        if runner is not None:
            await runner.cleanup()
        await wallet.stop()
        await db.close()
        await bot.session.close()


async def _run_webhook(bot: Bot, dp: Dispatcher, db: Database, config, wallet) -> None:
    """Серверный режим: один веб-сервер отдаёт Mini App и принимает webhook Telegram."""
    import hashlib

    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    from .webapp.server import WebAppServer

    app = WebAppServer(config, db).build_app()
    secret = hashlib.sha256(config.bot_token.encode()).hexdigest()[:24]
    path = f"/tg/{secret}"
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=path)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.webapp_host, config.webapp_port)
    await site.start()

    webhook_url = config.webapp_url.rstrip("/") + path
    await bot.set_webhook(webhook_url, drop_pending_updates=True,
                          allowed_updates=dp.resolve_used_update_types())
    log.info("Режим webhook. Порт :%s | Mini App: %s", config.webapp_port, config.webapp_url)
    try:
        await asyncio.Event().wait()
    finally:
        await bot.delete_webhook()
        await runner.cleanup()
        await wallet.stop()
        await db.close()
        await bot.session.close()


async def run() -> None:
    config = load_config()
    if not config.bot_token:
        raise SystemExit(
            "Не задан BOT_TOKEN. Скопируй .env.example в .env и впиши токен от @BotFather."
        )

    db = Database(config.turso_url or config.db_path, config.turso_token)
    await db.connect()

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    wallet = build_wallet(config, db)
    games = GameManager(bot, db)

    # Зависимости, инжектируемые в хэндлеры по имени параметра.
    dp["db"] = db
    dp["wallet"] = wallet
    dp["games"] = games
    dp["config"] = config

    dp.include_router(common_router)
    dp.include_router(balance_router)
    dp.include_router(crash_router)
    dp.include_router(group_router)        # «ИИ Баран» в группах — последним

    await wallet.start(bot)
    await _set_commands(bot)
    await _setup_menu_button(bot, config.webapp_url)
    try:
        me = await bot.get_me()
        config.bot_username = me.username        # для ссылок-приглашений
    except Exception:  # noqa: BLE001
        pass
    asyncio.create_task(_reminder_loop(bot, db, config))

    if config.use_webhook and config.webapp_url and config.webapp_url.startswith("https"):
        await _run_webhook(bot, dp, db, config, wallet)
    else:
        await _run_polling(bot, dp, db, config, wallet)


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit) as exc:
        log.info("Остановка: %s", exc)


if __name__ == "__main__":
    main()
