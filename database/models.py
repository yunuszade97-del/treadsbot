"""
SQLAlchemy ORM models for the Threads Copilot bot.

Tables
------
- **users** — registered Telegram users with billing state.
- **threads_profiles** — per-user chat slots (max 5), each with persona & context.
"""

from __future__ import annotations

import datetime
import json

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base class shared by all models."""


class User(Base):
    """Telegram user with billing / usage tracking."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    is_pro: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requests_today: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_request_date: Mapped[datetime.date] = mapped_column(
        Date, default=datetime.date.today, nullable=False
    )
    active_profile_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("threads_profiles.id", ondelete="SET NULL"), nullable=True
    )

    # One-to-many: user → profiles
    profiles: Mapped[list[ThreadsProfile]] = relationship(
        "ThreadsProfile", back_populates="user", cascade="all, delete-orphan",
        foreign_keys="ThreadsProfile.user_id",
    )

    def __repr__(self) -> str:
        return (
            f"<User id={self.id} tg={self.telegram_id} "
            f"pro={self.is_pro} active={self.active_profile_id}>"
        )


class ThreadsProfile(Base):
    """A chat slot: named persona with system prompt and conversation context."""

    __tablename__ = "threads_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    profile_name: Mapped[str] = mapped_column(String(128), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    user: Mapped[User] = relationship(
        "User", back_populates="profiles", foreign_keys=[user_id]
    )

    # ── Context helpers ─────────────────────────────────────────────
    MAX_CONTEXT_MESSAGES: int = 10  # pairs (user+assistant = 2 entries each)

    def get_context(self) -> list[dict[str, str]]:
        """Deserialize stored context."""
        try:
            return json.loads(self.context_json or "[]")
        except json.JSONDecodeError:
            return []

    def add_to_context(self, user_msg: str, assistant_msg: str) -> None:
        """Append a user/assistant pair and trim to MAX_CONTEXT_MESSAGES pairs."""
        ctx = self.get_context()
        ctx.append({"role": "user", "content": user_msg})
        ctx.append({"role": "assistant", "content": assistant_msg})
        # Keep last N*2 entries (N pairs)
        max_entries = self.MAX_CONTEXT_MESSAGES * 2
        if len(ctx) > max_entries:
            ctx = ctx[-max_entries:]
        self.context_json = json.dumps(ctx, ensure_ascii=False)

    def clear_context(self) -> None:
        """Reset conversation context."""
        self.context_json = "[]"

    def __repr__(self) -> str:
        return f"<ThreadsProfile id={self.id} name={self.profile_name!r}>"
