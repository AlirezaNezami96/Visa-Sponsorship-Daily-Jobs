"""Image generation worker — queued image rendering for social cards.

Runs as: python -m job_radar.pipeline.image_worker

Claims `image_status='pending'` jobs, renders social cards via the existing
card_renderer (Pillow/PIL, deterministic, no AI), optionally fetching a licensed
landmark photo for the city (wrapped in a circuit breaker), uploads to Supabase
Storage bucket `job-cards`, and sets `jobs.image_url`.

Budget-aware: max 25 per run. Failures increment attempts, quarantine after 3.
"""
from __future__ import annotations

import io
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from job_radar.pipeline.circuit_breaker import CircuitBreaker
from job_radar.pipeline.metrics import record_metric
from job_radar.pipeline.state_machine import transition_stage
from job_radar.social.card_renderer import card_job_from_row, render_card_png
from job_radar.social.landmark import fetch_landmark_photo

logger = logging.getLogger(__name__)

BATCH_SIZE = int(os.getenv("IMAGE_BATCH_SIZE", "25"))
THREAD_POOL_SIZE = int(os.getenv("IMAGE_THREADS", "4"))


def _create_client() -> Any:
    """Create a Supabase service-role client."""
    from supabase import create_client  # type: ignore[attr-defined]
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def render_and_upload(job_id: str, client: Any = None) -> dict[str, Any]:
    """Render a social card and upload to Storage using a per-thread Supabase client.

    Uses the existing card_renderer module and landmark photo fetcher with circuit breakers.
    """

    if client is None:
        client = _create_client()

    cb = CircuitBreaker(client)
    start = time.time()

    # Fetch job data
    resp = (
        client.table("jobs")
        .select("id, title, company, country, country_code, city, location, "
                "work_mode, salary_min, salary_max, salary_currency, "
                "visa_sponsorship_verified, visa_sponsorship_confidence, skills, company_logo_url")
        .eq("id", job_id)
        .maybe_single()
        .execute()
    )
    if not resp or not resp.data:
        transition_stage(client, job_id, "image", "failed", error="job not found")
        return {"ok": False, "error": "job not found"}

    job = resp.data

    try:
        card = card_job_from_row(job)
        photo: bytes | None = None

        if card.city:
            if not cb.is_open("wikimedia"):
                try:
                    photo, meta = fetch_landmark_photo(client, card.city, card.country)
                    if photo is not None:
                        cb.record_success("wikimedia")
                except Exception as e:
                    cb.record_failure("wikimedia")
                    logger.debug("Wikimedia landmark fetch failed: %s", e)
            else:
                record_metric(client, "circuit:open:wikimedia", True, 0)
                logger.debug("Wikimedia circuit open, skipping landmark fetch for %s", card.city)

        # Render deterministic PNG
        image_bytes = render_card_png(card, photo)

        # Upload to Storage bucket
        path = f"cards/{job_id}.png"
        client.storage.from_("job-cards").upload(
            path, image_bytes,
            file_options={"content-type": "image/png", "upsert": "true"},
        )

        # Construct public URL
        supabase_url = os.environ.get("SUPABASE_URL", "")
        image_url = f"{supabase_url}/storage/v1/object/public/job-cards/{path}"

        # Update job with image URL
        client.table("jobs").update({
            "image_url": image_url,
        }).eq("id", job_id).execute()

        # Transition to done
        transition_stage(client, job_id, "image", "done",
                        metrics_fn=lambda n, o, d: record_metric(client, n, o, d))

        duration_ms = int((time.time() - start) * 1000)
        record_metric(client, "image:generated", True, duration_ms)

        return {"ok": True, "image_url": image_url, "duration_ms": duration_ms}

    except Exception as e:
        error_msg = str(e)[:500]
        logger.error("Image generation failed for job %s: %s", job_id, error_msg)
        transition_stage(client, job_id, "image", "failed", error=error_msg,
                        metrics_fn=lambda n, o, d: record_metric(client, n, o, d))
        record_metric(client, "image:failed", False, int((time.time() - start) * 1000))
        return {"ok": False, "error": error_msg}


def run_image_batch() -> dict[str, Any]:
    """Run one image generation batch. Entry point for GitHub Actions."""
    from job_radar.pipeline.state_machine import claim_pending
    from job_radar.pipeline.metrics import update_pipeline_health

    main_client = _create_client()

    # Ensure storage bucket exists
    try:
        buckets = main_client.storage.list_buckets()
        if not any(b.name == "job-cards" for b in buckets):
            main_client.storage.create_bucket("job-cards", options={"public": True})
    except Exception:
        pass  # Bucket may already exist

    claimed = claim_pending(
        main_client, "image", limit=BATCH_SIZE,
        prerequisite_stage="metadata",
    )

    if not claimed:
        logger.info("No pending jobs for image generation")
        update_pipeline_health(main_client, "image", backlog=0)
        return {"processed": 0, "succeeded": 0, "failed": 0}

    logger.info("Claimed %d jobs for image generation", len(claimed))
    succeeded = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE) as pool:
        # Per-thread execution (render_and_upload instantiates its own Supabase client)
        futures = {pool.submit(render_and_upload, jid): jid for jid in claimed}
        for future in as_completed(futures):
            jid = futures[future]
            try:
                result = future.result()
                if result["ok"]:
                    succeeded += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error("Image render crashed for job %s: %s", jid, e)
                failed += 1

    update_pipeline_health(
        main_client, "image",
        success=succeeded > 0,
        error=f"{failed} jobs failed" if failed else None,
    )

    logger.info(
        "Image batch: %d processed, %d succeeded, %d failed",
        len(claimed), succeeded, failed,
    )
    return {"processed": len(claimed), "succeeded": succeeded, "failed": failed}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    result = run_image_batch()
    logger.info("Result: %s", result)
