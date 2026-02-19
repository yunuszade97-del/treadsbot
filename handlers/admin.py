"""
Admin-only bot handlers (Router).

Commands
--------
/admin_promote <telegram_id> — grant Pro status to a user.
"""

from __future__ import annotations

import logging

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from sqlalchemy import select

from config import settings
from database.models import User
from database.session import async_session

logger = logging.getLogger(__name__)
router = Router(name="admin")


def _is_admin(user_id: int) -> bool:
    """Check whether *user_id* is listed in ADMIN_IDS."""
    return user_id in settings.admin_ids_list


# ── /admin_promote ──────────────────────────────────────────────────────


@router.message(Command("admin_promote"))
async def cmd_admin_promote(message: types.Message) -> None:
    """Set a target user to Pro status.

    Usage: ``/admin_promote 123456789``
    """
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для этой команды.")
        return

    args = (message.text or "").partition(" ")[2].strip()

    if not args:
        await message.answer(
            "Использование: <code>/admin_promote &lt;telegram_id&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_tg_id = int(args)
    except ValueError:
        await message.answer("⚠️ Укажите корректный числовой Telegram ID.")
        return

    async with async_session() as session:
        stmt = select(User).where(User.telegram_id == target_tg_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            await message.answer(
                f"❌ Пользователь с Telegram ID <code>{target_tg_id}</code> не найден.\n"
                "Ему нужно сначала написать /start боту.",
                parse_mode=ParseMode.HTML,
            )
            return

        if user.is_pro:
            await message.answer(
                f"ℹ️ Пользователь <code>{target_tg_id}</code> уже Pro.",
                parse_mode=ParseMode.HTML,
            )
            return

        user.is_pro = True
        await session.commit()

        logger.info(
            "Admin %s promoted user %s to Pro",
            message.from_user.id,
            target_tg_id,
        )

        await message.answer(
            f"✅ Пользователь <code>{target_tg_id}</code> получил статус <b>Pro</b>!",
            parse_mode=ParseMode.HTML,
        )
