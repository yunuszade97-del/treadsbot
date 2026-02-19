"""
Async SQLAlchemy engine & session factory.

Usage
-----
    from database.session import async_session, init_db

    async with async_session() as session:
        ...

Call ``init_db()`` once at application startup to create tables.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings
from database.models import Base

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    # SQLite-specific: allow the same connection across coroutines.
    connect_args={"check_same_thread": False}
    if settings.DATABASE_URL.startswith("sqlite")
    else {},
)

async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Create all tables that do not yet exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
