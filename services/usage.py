"""
Usage-tracking service for the freemium billing model.

Provides ``check_and_track_usage`` which enforces daily request limits
for free users while allowing unlimited access for Pro subscribers.
"""

from __future__ import annotations

import datetime
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import User

logger = logging.getLogger(__name__)


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
) -> User:
    """Return the existing user or create a new one."""
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            telegram_id=telegram_id,
            is_pro=False,
            requests_today=0,
            last_request_date=datetime.date.today(),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        logger.info("Registered new user tg_id=%s", telegram_id)

    return user


async def check_and_track_usage(
    session: AsyncSession,
    telegram_id: int,
) -> bool:
    """Check whether the user may make a request.  If yes, increment the
    counter and return ``True``; otherwise return ``False``.

    Rules
    -----
    1. If ``last_request_date`` is before today → reset ``requests_today``
       to 0 (new day).
    2. Pro users → always allowed.
    3. Free users with ``requests_today < DAILY_FREE_LIMIT`` → allowed.
    4. Otherwise → denied.
    """
    user = await get_or_create_user(session, telegram_id)
    today = datetime.date.today()

    # Admins always bypass limits (survives DB reset)
    if telegram_id in settings.admin_ids_list:
        user.requests_today += 1
        user.last_request_date = today
        await session.commit()
        return True

    # Reset counter on a new calendar day
    if user.last_request_date < today:
        user.requests_today = 0
        user.last_request_date = today

    # Pro users bypass limits
    if user.is_pro:
        user.requests_today += 1
        await session.commit()
        return True

    # Free-tier check
    if user.requests_today < settings.DAILY_FREE_LIMIT:
        user.requests_today += 1
        await session.commit()
        return True

    # Limit reached
    return False


async def get_remaining_requests(
    session: AsyncSession,
    telegram_id: int,
) -> tuple[bool, int]:
    """Return ``(is_pro, remaining_requests_today)`` for a user.

    For Pro users ``remaining`` is set to ``-1`` (unlimited).
    """
    user = await get_or_create_user(session, telegram_id)
    today = datetime.date.today()

    used = user.requests_today if user.last_request_date >= today else 0

    if user.is_pro:
        return True, -1

    remaining = max(settings.DAILY_FREE_LIMIT - used, 0)
    return False, remaining
