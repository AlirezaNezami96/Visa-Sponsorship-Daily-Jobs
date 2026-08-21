#!/usr/bin/env python3
"""JustJoin.it Daily Job Scraper (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.cli.justjoin_cmd import (
    JUSTJOIN_SEEN_FILE,
    dedupe_justjoin,
    main,
    run,
)

if __name__ == "__main__":
    main()
