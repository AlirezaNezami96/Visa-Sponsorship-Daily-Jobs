#!/usr/bin/env python3
"""Remote-job scanner (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.cli.remote_cmd import (
    REMOTE_COMPANIES_FILE,
    REMOTE_SEEN_FILE,
    load_remote_companies,
    main,
    run,
    send_remote_email,
)

if __name__ == "__main__":
    main()
