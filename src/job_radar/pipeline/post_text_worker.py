"""Post text generation worker.

Runs as: python -m job_radar.pipeline.post_text_worker

Claims jobs where `image_status='done'` and `post_text_status='pending'`.
Generates the platform post texts via `post_text.py` and stores the payload
in `job_processing.post_text`.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

BATCH_SIZE = int(os.getenv("POST_TEXT_BATCH_SIZE", "25"))


def _create_client() -> Any:
    """Create a Supabase service-role client."""
    from supabase import create_client  # type: ignore[attr-defined]
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def process_post_text_for_job(client: Any, job_id: str) -> dict[str, Any]:
    """Generate and store social post texts for a job."""
    from job_radar.pipeline.state_machine import transition_stage
    from job_radar.pipeline.metrics import record_metric
    from job_radar.social.post_text import build_platform_post_text

    start = time.time()

    # Fetch job
    resp = client.table("jobs").select("*").eq("id", job_id).maybe_single().execute()
    if not resp or not resp.data:
        transition_stage(client, job_id, "post_text", "failed", error="job not found")
        return {"ok": False, "error": "job not found"}

    job = resp.data

    try:
        # Build platform payload
        texts = {
            "telegram": build_platform_post_text(job, "telegram"),
            "discord": build_platform_post_text(job, "discord"),
            "slack": build_platform_post_text(job, "slack"),
            "x": build_platform_post_text(job, "x"),
            "linkedin": build_platform_post_text(job, "linkedin"),
            "bluesky": build_platform_post_text(job, "bluesky"),
            "mastodon": build_platform_post_text(job, "mastodon"),
        }

        # Store JSON payload in job_processing.post_text
        serialized = json.dumps(texts)
        transition_stage(
            client,
            job_id,
            "post_text",
            "done",
            post_text=serialized,
            metrics_fn=lambda n, o, d: record_metric(client, n, o, d),
        )

        duration_ms = int((time.time() - start) * 1000)
        record_metric(client, "post_text:generated", True, duration_ms)
        return {"ok": True, "job_id": job_id, "duration_ms": duration_ms}

    except Exception as e:
        err_msg = str(e)[:500]
        logger.error("Post text generation failed for job %s: %s", job_id, err_msg)
        transition_stage(
            client,
            job_id,
            "post_text",
            "failed",
            error=err_msg,
            metrics_fn=lambda n, o, d: record_metric(client, n, o, d),
        )
        record_metric(client, "post_text:failed", False, int((time.time() - start) * 1000))
        return {"ok": False, "error": err_msg}


def run_post_text_batch() -> dict[str, Any]:
    """Run one post text generation batch."""
    from job_radar.pipeline.state_machine import claim_pending
    from job_radar.pipeline.metrics import update_pipeline_health

    client = _create_client()
    claimed = claim_pending(
        client,
        "post_text",
        limit=BATCH_SIZE,
        prerequisite_stage="image",
    )

    if not claimed:
        logger.info("No jobs pending post text generation")
        update_pipeline_health(client, "post_text", backlog=0)
        return {"processed": 0, "succeeded": 0, "failed": 0}

    logger.info("Claimed %d jobs for post text generation", len(claimed))
    succeeded = 0
    failed = 0

    for jid in claimed:
        res = process_post_text_for_job(client, jid)
        if res.get("ok"):
            succeeded += 1
        else:
            failed += 1

    update_pipeline_health(
        client,
        "post_text",
        success=succeeded > 0,
        error=f"{failed} jobs failed" if failed else None,
    )

    logger.info(
        "Post text batch: %d processed, %d succeeded, %d failed",
        len(claimed), succeeded, failed,
    )
    return {"processed": len(claimed), "succeeded": succeeded, "failed": failed}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    result = run_post_text_batch()
    logger.info("Result: %s", result)
