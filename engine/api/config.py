"""
Application configuration loaded from environment variables.
Uses pydantic-settings for type-safe config with .env file support.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Gemini ──────────────────────────────────────────────────────────────
    gemini_api_key: str = Field(..., env="GEMINI_API_KEY")
    gemini_pro_model: str = Field("gemini-2.5-pro", env="GEMINI_PRO_MODEL")
    gemini_flash_model: str = Field("gemini-2.0-flash", env="GEMINI_FLASH_MODEL")

    # ── Session ──────────────────────────────────────────────────────────────
    session_ttl_seconds: int = Field(7200, env="SESSION_TTL_SECONDS")
    session_secret: str = Field(..., env="SESSION_SECRET")  # for HMAC tokens

    # ── PDF Storage ──────────────────────────────────────────────────────────
    pdf_output_dir: str = Field("/tmp/engine_docs", env="PDF_OUTPUT_DIR")
    pdf_ttl_seconds: int = Field(7200, env="PDF_TTL_SECONDS")

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    rate_limit_per_hour: int = Field(10, env="RATE_LIMIT_PER_HOUR")

    # ── CORS ──────────────────────────────────────────────────────────────────
    allowed_origins: List[str] = Field(
        default=["chrome-extension://*", "http://localhost:*"],
        env="ALLOWED_ORIGINS",
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = Field("INFO", env="LOG_LEVEL")

    @field_validator("session_secret")
    @classmethod
    def validate_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SESSION_SECRET must be at least 32 characters.")
        return v

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
