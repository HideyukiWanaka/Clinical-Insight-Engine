"""
Application settings — loaded from environment variables via pydantic-settings
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────
    app_name: str = "Clinical Insight Engine"
    version: str = "1.0.0"
    log_level: str = "info"
    secret_key: str = "changeme"
    allowed_origins: List[str] = ["http://localhost:3000"]

    # ── Database (PostgreSQL) ──────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:password@postgres:5432/cie_db"

    # ── Redis (ephemeral clinical data) ───────────────────
    redis_url: str = "redis://redis:6379/0"

    # ── Anthropic Claude API ───────────────────────────────
    anthropic_api_key: str = ""

    # ── Google OAuth ───────────────────────────────────────
    google_client_id: str = ""
    google_client_secret: str = ""

    # ── R Engine ──────────────────────────────────────────
    r_engine_url: str = "http://r-engine:8001"
    r_engine_timeout_seconds: int = 30  # SRD §10: EXECUTION_TIMEOUT


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
