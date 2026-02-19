"""
Threads Copilot Bot — entry point.

Supports both Long Polling (local) and Webhooks (production).
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from config import settings
from database.session import init_db
from handlers.admin import router as admin_router
from handlers.user import router as user_router

# ── Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def setup_commands(bot: Bot) -> None:
    """Register bot commands."""
    # Public command menu
    await bot.set_my_commands([
        BotCommand(command="start", description="🚀 Запустить бота"),
        BotCommand(command="chats", description="📋 Мои чаты"),
        BotCommand(command="switch", description="🔀 Сменить чат"),
        BotCommand(command="clear", description="🗑 Очистить контекст"),
        BotCommand(command="pro_status", description="📊 Статус подписки"),
    ])

    # Admin commands
    admin_commands = [
        BotCommand(command="start", description="🚀 Запустить бота"),
        BotCommand(command="chats", description="📋 Мои чаты"),
        BotCommand(command="switch", description="🔀 Сменить чат"),
        BotCommand(command="clear", description="🗑 Очистить контекст"),
        BotCommand(command="pro_status", description="📊 Статус подписки"),
        BotCommand(command="admin_promote", description="👑 Выдать Pro (админ)"),
    ]
    for admin_id in settings.admin_ids_list:
        try:
            await bot.set_my_commands(
                admin_commands,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            logger.warning("Could not set commands for admin %s", admin_id)


async def on_startup(bot: Bot) -> None:
    """Startup hook for Webhook mode."""
    logger.info("Starting up (Webhook mode)...")
    await init_db()
    await setup_commands(bot)
    
    webhook_url = f"{settings.WEBHOOK_URL}/webhook"
    logger.info("Setting webhook: %s", webhook_url)
    await bot.set_webhook(
        webhook_url,
        drop_pending_updates=True,
    )


def main() -> None:
    """Application entry-point."""
    # Common setup
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_router)
    dp.include_router(user_router)

    # ── Webhook Mode ────────────────────────────────────────────────────
    if settings.WEBHOOK_URL:
        dp.startup.register(on_startup)
        
        app = web.Application()
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
        setup_application(app, dp, bot=bot)
        
        logger.info("Starting Webhook server on port %s...", settings.PORT)
        web.run_app(app, host="0.0.0.0", port=settings.PORT)

    # ── Polling Mode ────────────────────────────────────────────────────
    else:
        logger.info("Starting Polling mode...")
        
        async def run_polling():
            logger.info("Initialising database…")
            await init_db()
            await setup_commands(bot)
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

        asyncio.run(run_polling())


if __name__ == "__main__":
    main()
