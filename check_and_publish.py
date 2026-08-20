#!/usr/bin/env python3
"""LinkedIn Approval & Publisher (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.social.publisher import (
    COVER_FILE,
    PENDING_FILE,
    STATE_DIR,
    answer_callback_query,
    check_and_publish_post,
    cleanup_state_files,
    edit_telegram_message,
    get_linkedin_api_version,
    publish_to_linkedin,
    send_telegram_message,
    trigger_generate_workflow,
    upload_image_to_linkedin,
)

if __name__ == "__main__":
    check_and_publish_post()
