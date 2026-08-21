"""
Application configuration loaded from environment variables.
Uses pydantic-settings for type-safe config with .env file support.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Union

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


from pathlib import Path

# Load .env from engine/ directory or root directory if present
_ENGINE_DIR = Path(__file__).resolve().parent.parent
_ENV_PATHS = (str(_ENGINE_DIR / ".env"), ".env")


class Settings(BaseSettings):
    # ── Gemini ──────────────────────────────────────────────────────────────
    gemini_api_key: str = Field(
        default_factory=lambda: os.environ.get("GEMINI_API_KEY", ""),
    )
    gemini_pro_model: str = Field("gemini-3.7-flash")
    gemini_flash_model: str = Field("gemini-3.7-flash")

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def clean_api_key(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.strip().strip("'\"").strip()
        return str(v or "").strip()

    # ── Session ──────────────────────────────────────────────────────────────
    session_ttl_seconds: int = Field(7200)
    session_secret: str = Field(
        default_factory=lambda: os.environ.get(
            "SESSION_SECRET",
            "dev-default-session-secret-change-in-production-min-32-chars",
        )
    )

    # ── PDF Storage ──────────────────────────────────────────────────────────
    pdf_output_dir: str = Field("/tmp/engine_docs")
    pdf_ttl_seconds: int = Field(7200)

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    rate_limit_per_hour: int = Field(10)

    # ── CORS ──────────────────────────────────────────────────────────────────
    allowed_origins: Union[str, List[str]] = Field(
        default=["chrome-extension://*", "http://localhost:*"],
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = Field("INFO")

    @property
    def allowed_origins_list(self) -> List[str]:
        if isinstance(self.allowed_origins, str):
            val = self.allowed_origins.strip()
            if val.startswith("[") and val.endswith("]"):
                try:
                    import json
                    return json.loads(val)
                except Exception:
                    pass
            return [o.strip() for o in val.split(",") if o.strip()]
        return list(self.allowed_origins)

    @field_validator("session_secret")
    @classmethod
    def validate_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SESSION_SECRET must be at least 32 characters.")
        return v

    model_config = {
        "env_file": _ENV_PATHS,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
