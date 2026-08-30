"""Telegram approval callback handler for LinkedIn/X manual review posts.

Exposes `handle_approval_callback(client, callback_data)` which transitions
the state machine from `manual_review` -> `done` (or `failed`) and mirrors
`jobs.{platform}_post_published = True`.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def handle_approval_callback(client: Any, callback_data: str) -> Dict[str, Any]:
    """Handle Telegram callback from manual review buttons."""
    from job_radar.pipeline.state_machine import transition_stage
    from job_radar.pipeline.metrics import record_metric

    parts = callback_data.split("_", 2)
    if len(parts) != 3:
        return {"ok": False, "error": f"invalid callback format: {callback_data}"}

    action, platform, job_id = parts[0], parts[1], parts[2]

    if action == "approve":
        # Transition stage from manual_review to done
        transition_stage(
            client,
            job_id,
            platform,
            "done",
            url="manual_approval",
            metrics_fn=lambda n, o, d: record_metric(client, n, o, d),
        )

        # Mirror publication flag in jobs table
        mirror_col = f"{platform}_post_published"
        client.table("jobs").update({mirror_col: True}).eq("id", job_id).execute()
        record_metric(client, f"post:{platform}:approved", True, 0)
        logger.info("Manually approved and marked %s done for job %s", platform, job_id)

        return {"ok": True, "action": "approved", "job_id": job_id, "platform": platform}

    elif action == "reject":
        # Transition stage from manual_review to failed
        transition_stage(
            client,
            job_id,
            platform,
            "failed",
            error="manually rejected by admin",
            metrics_fn=lambda n, o, d: record_metric(client, n, o, d),
        )
        record_metric(client, f"post:{platform}:rejected", True, 0)
        logger.info("Manually rejected %s for job %s", platform, job_id)

        return {"ok": True, "action": "rejected", "job_id": job_id, "platform": platform}

    return {"ok": False, "error": f"unknown action: {action}"}
