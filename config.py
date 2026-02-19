"""
Application configuration loaded from environment variables.

Uses pydantic-settings to validate and parse .env values at startup.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Bot-wide settings sourced from .env / environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Telegram ────────────────────────────────────────────────
    BOT_TOKEN: str

    # ── OpenRouter / AI ─────────────────────────────────────────
    OPENROUTER_API_KEY: str
    AI_MODEL: str = "anthropic/claude-sonnet-4.6"

    # ── Admin ───────────────────────────────────────────────────
    ADMIN_IDS: str = ""  # comma-separated Telegram user IDs

    # ── Database ────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./bot.db"

    # ── Limits ──────────────────────────────────────────────────
    DAILY_FREE_LIMIT: int = 5

    # ── Helpers ─────────────────────────────────────────────────
    @property
    def admin_ids_list(self) -> list[int]:
        """Parse ADMIN_IDS into a list of integers."""
        if not self.ADMIN_IDS.strip():
            return []
        return [int(uid.strip()) for uid in self.ADMIN_IDS.split(",") if uid.strip()]


settings = Settings()  # type: ignore[call-arg]
