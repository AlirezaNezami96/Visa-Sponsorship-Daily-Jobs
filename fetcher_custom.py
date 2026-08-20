"""Custom career page fetchers (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.fetchers.custom import (
    HEADERS,
    USER_AGENT,
    extract_jobs_from_html,
    fetch_custom_many_sync,
    fetch_custom_sync,
    fetch_with_playwright,
)

__all__ = [
    "HEADERS",
    "USER_AGENT",
    "fetch_custom_sync",
    "fetch_custom_many_sync",
    "fetch_with_playwright",
    "extract_jobs_from_html",
]
