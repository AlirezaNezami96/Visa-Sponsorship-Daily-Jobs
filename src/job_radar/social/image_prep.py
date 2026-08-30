"""Image download and adaptive compression ladder for social platforms.

Ensures media adheres to platform-specific payload size ceilings
(e.g., Bluesky 976KB, Discord 8MB, etc.) while failing open to text-only on any issue.
"""
from __future__ import annotations

import io
import logging

import requests
from PIL import Image

logger = logging.getLogger(__name__)

WIDTH_LADDER = [1600, 1280, 1024, 800, 640]
QUALITY_LADDER = [85, 75, 65, 55, 45]


def prepare_image_for_platform(
    image_url: str | None,
    max_bytes: int | None = None,
    timeout: int = 20,
) -> bytes | None:
    """Download image and compress it if necessary to fit within max_bytes.

    Never raises; returns None on failure or if image cannot be compressed below limit.
    """
    if not image_url:
        return None

    try:
        res = requests.get(image_url, timeout=timeout)
        if res.status_code != 200 or not res.content:
            logger.warning("Failed to fetch image from %s: HTTP %s", image_url, res.status_code)
            return None

        raw_bytes = res.content
        if max_bytes is None or len(raw_bytes) <= max_bytes:
            return raw_bytes

        # Run compression ladder
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        orig_w, orig_h = img.size

        for width in WIDTH_LADDER:
            if width < orig_w:
                ratio = width / float(orig_w)
                height = max(1, int(orig_h * ratio))
                resized = img.resize((width, height), Image.Resampling.LANCZOS)
            else:
                resized = img

            for quality in QUALITY_LADDER:
                buf = io.BytesIO()
                resized.save(buf, format="JPEG", quality=quality, optimize=True)
                candidate_bytes = buf.getvalue()
                if len(candidate_bytes) <= max_bytes:
                    logger.debug(
                        "Image compressed to %d bytes (width=%d, quality=%d)",
                        len(candidate_bytes),
                        width,
                        quality,
                    )
                    return candidate_bytes

        logger.warning("Image could not be compressed below %d bytes ceiling", max_bytes)
        return None
    except Exception as e:
        logger.warning("Image preparation error for %s: %s", image_url, e)
        return None
