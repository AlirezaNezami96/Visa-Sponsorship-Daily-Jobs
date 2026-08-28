"""Card rendering inside the social staging pipeline.

For each social_post_queue batch we render ONE digest card featuring the top
job (deterministic Pillow renderer — no AI), optionally sourcing a licensed
landmark photo for its city, and upload the PNG to the public
`social-images` bucket under `cards/{job_id}.png`. The resulting path lands in
`social_post_queue.image_path`; auto-posting channels attach it, LinkedIn/X
stay manual_review. Rendering failures must never block queueing.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from job_radar.social.card_renderer import CardJob, render_card_png
from job_radar.social.landmark import fetch_landmark_photo

logger = logging.getLogger(__name__)

CARD_IMAGE_BUCKET = "social-images"


def _cards_enabled() -> bool:
    return os.environ.get("VISALANE_SOCIAL_CARDS", "1").strip() != "0"


def _card_job(job: dict[str, Any]) -> CardJob:
    """Map a pipeline job dict onto the minimal card payload."""
    return CardJob(
        title=str(job.get("title") or "Untitled role"),
        country=str(job.get("country") or job.get("country_code") or ""),
        city=job.get("city"),
        work_mode=job.get("work_mode"),
        visa_sponsorship_verified=bool(job.get("visa_sponsorship_verified")),
        visa_sponsorship_confidence=int(job.get("visa_sponsorship_confidence") or 0),
    )


def render_batch_card(
    client,
    batch: list[dict[str, Any]],
    *,
    storage=None,
    session=None,
) -> str | None:
    """Render + upload the digest card for a batch. Returns the storage path.

    Returns None (text-only post fallback) on any failure or when storage is
    unavailable — card rendering must never break social queueing.
    """
    if not batch:
        return None
    top = batch[0]
    job_id = top.get("job_db_id") or top.get("id")
    if not job_id or storage is None:
        return None

    try:
        card_job = _card_job(top)
        photo, meta = fetch_landmark_photo(
            client,
            card_job.city,
            card_job.country,
            storage=storage,
            session=session,
        )
        if meta and meta.get("license"):
            logger.info(
                "card landmark %s/%s: license=%s source=%s",
                card_job.city,
                card_job.country,
                meta["license"],
                meta.get("source_url"),
            )
        png = render_card_png(card_job, photo)
        path = f"cards/{job_id}.png"
        uploaded = storage.upload_storage_file(CARD_IMAGE_BUCKET, path, png, mime_type="image/png")
        if not uploaded:
            return None
        return path
    except Exception as exc:
        logger.warning("digest card render/upload failed for %s: %s", job_id, exc)
        return None


def make_card_factory(
    client,
    *,
    storage=None,
    session=None,
) -> Callable[[list[dict[str, Any]]], str | None] | None:
    """Factory used by social_queue.enqueue_jobs (None when cards disabled)."""
    if not _cards_enabled():
        return None

    def factory(batch: list[dict[str, Any]]) -> str | None:
        return render_batch_card(client, batch, storage=storage, session=session)

    return factory
