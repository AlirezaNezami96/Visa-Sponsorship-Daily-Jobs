"""AI Company list builder (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.builders.ai import (
    CURATED_AI,
    build_ai_companies,
)

__all__ = [
    "CURATED_AI",
    "build_ai_companies",
]

if __name__ == "__main__":
    out = build_ai_companies("ai_companies.json")
    print(f"Generated ai_companies.json: {len(out['scrapable'])} API scrapable, {len(out['custom_ats'])} custom ATS")
