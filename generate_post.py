#!/usr/bin/env python3
"""LinkedIn Post Generator (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.social.generator import (
    COVER_FILE,
    PENDING_FILE,
    STATE_DIR,
    call_gemini_text_api,
    ensure_telegram_webhook,
    generate_and_dispatch_post,
    send_telegram_alert,
    send_telegram_draft,
)

if __name__ == "__main__":
    generate_and_dispatch_post()
