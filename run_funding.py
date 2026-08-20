#!/usr/bin/env python3
"""Newly Fund-Raised Companies Scanner (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.cli.funding_cmd import (
    SEEN_FUNDING_FILE,
    SEEN_MAX_AGE,
    _load_seen_funding,
    _save_seen_funding,
    build_funding_html,
    dedupe_funding,
    main,
    run,
    send_funding_email,
)

if __name__ == "__main__":
    main()
