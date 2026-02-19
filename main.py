"""
Threads Copilot Bot — entry point.

Initialises the database, registers routers, and starts long-polling.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

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


async def main() -> None:
    """Application entry-point coroutine."""
    logger.info("Initialising database…")
    await init_db()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Register routers — admin first so its commands take priority
    dp.include_router(admin_router)
    dp.include_router(user_router)

    # Public command menu (visible to all users)
    await bot.set_my_commands([
        BotCommand(command="start", description="🚀 Запустить бота"),
        BotCommand(command="chats", description="📋 Мои чаты"),
        BotCommand(command="switch", description="🔀 Сменить чат"),
        BotCommand(command="clear", description="🗑 Очистить контекст"),
        BotCommand(command="pro_status", description="📊 Статус подписки"),
    ])

    # Extended menu for admins
    admin_commands = [
        BotCommand(command="start", description="🚀 Запустить бота"),
        BotCommand(command="chats", description="📋 Мои чаты"),
        BotCommand(command="switch", description="🔀 Сменить чат"),
        BotCommand(command="clear", description="🗑 Очистить контекст"),
        BotCommand(command="pro_status", description="📊 Статус подписки"),
        BotCommand(command="admin_promote", description="👑 Выдать Pro (админ)"),
    ]
    for admin_id in settings.admin_ids_list:
        await bot.set_my_commands(
            admin_commands,
            scope=BotCommandScopeChat(chat_id=admin_id),
        )

    logger.info("Starting polling…")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
