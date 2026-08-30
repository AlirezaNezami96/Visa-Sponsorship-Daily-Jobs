"""Image generation worker — queued image rendering for social cards.

Runs as: python -m job_radar.pipeline.image_worker

Claims `image_status='pending'` jobs, renders social cards via the existing
card_renderer (Pillow/PIL, deterministic, no AI), uploads to Supabase Storage,
and sets `jobs.image_url`.

Budget-aware: max 25 per run. Failures increment attempts, quarantine after 3.
"""
from __future__ import annotations

import logging
import os
import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger(__name__)

BATCH_SIZE = int(os.getenv("IMAGE_BATCH_SIZE", "25"))
THREAD_POOL_SIZE = int(os.getenv("IMAGE_THREADS", "4"))


def _create_client() -> Any:
    """Create a Supabase service-role client."""
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def render_and_upload(client: Any, job_id: str) -> dict[str, Any]:
    """Render a social card and upload to Storage.

    Uses the existing card_renderer module (frozen — never rewritten).
    """
    from job_radar.pipeline.state_machine import transition_stage
    from job_radar.pipeline.metrics import record_metric

    start = time.time()

    # Fetch job data
    resp = (
        client.table("jobs")
        .select("id, title, company, country, country_code, location, "
                "work_mode, salary_min, salary_max, salary_currency, "
                "visa_sponsorship_verified, skills, company_logo_url")
        .eq("id", job_id)
        .maybe_single()
        .execute()
    )
    if not resp or not resp.data:
        transition_stage(client, job_id, "image", "failed", error="job not found")
        return {"ok": False, "error": "job not found"}

    job = resp.data

    try:
        from job_radar.social.card_renderer import render_card

        # Build card data payload
        card_data = {
            "title": job.get("title", "Unknown Position"),
            "company": job.get("company", "Unknown Company"),
            "location": job.get("location") or job.get("country") or "",
            "country_code": job.get("country_code", ""),
            "work_mode": job.get("work_mode", ""),
            "visa": bool(job.get("visa_sponsorship_verified")),
            "skills": (job.get("skills") or [])[:6],
            "salary_min": job.get("salary_min"),
            "salary_max": job.get("salary_max"),
            "salary_currency": job.get("salary_currency"),
            "company_logo_url": job.get("company_logo_url"),
        }

        # Render card to bytes
        img = render_card(card_data)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        image_bytes = buf.read()

        # Upload to Storage
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

    client = _create_client()

    # Ensure storage bucket exists
    try:
        buckets = client.storage.list_buckets()
        if not any(b.name == "job-cards" for b in buckets):
            client.storage.create_bucket("job-cards", options={"public": True})
    except Exception:
        pass  # Bucket may already exist

    claimed = claim_pending(
        client, "image", limit=BATCH_SIZE,
        prerequisite_stage="metadata",
    )

    if not claimed:
        logger.info("No pending jobs for image generation")
        update_pipeline_health(client, "image", backlog=0)
        return {"processed": 0, "succeeded": 0, "failed": 0}

    logger.info("Claimed %d jobs for image generation", len(claimed))
    succeeded = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE) as pool:
        futures = {pool.submit(render_and_upload, client, jid): jid for jid in claimed}
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
        client, "image",
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
