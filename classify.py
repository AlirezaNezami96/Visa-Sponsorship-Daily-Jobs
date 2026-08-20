"""ATS classification for company careers URLs (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.fetchers.classify import (
    ATS_PATTERNS,
    classify,
)

__all__ = [
    "ATS_PATTERNS",
    "classify",
]
