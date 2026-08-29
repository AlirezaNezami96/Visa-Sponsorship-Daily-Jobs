"""Helper script to regenerate the golden card image for test_card_renderer_golden.py."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from job_radar.social.card_renderer import CardJob, render_card_png

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLDENS_DIR = Path(__file__).parent / "goldens"
FIXTURE_PHOTO_PATH = FIXTURES_DIR / "photo.png"
GOLDEN_PATH = GOLDENS_DIR / "card.png"

FIXTURE_JOB = CardJob(
    title="Senior Android Developer",
    country="Spain",
    city="Barcelona",
    visa_sponsorship_verified=True,
    visa_sponsorship_confidence=90,
)


def ensure_fixture_photo() -> bytes:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    if not FIXTURE_PHOTO_PATH.is_file():
        img = Image.new("RGB", (2000, 1200), (70, 110, 150))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        FIXTURE_PHOTO_PATH.write_bytes(buf.getvalue())
    return FIXTURE_PHOTO_PATH.read_bytes()


def update_golden() -> None:
    photo_bytes = ensure_fixture_photo()
    GOLDENS_DIR.mkdir(parents=True, exist_ok=True)
    png_bytes = render_card_png(FIXTURE_JOB, photo_bytes)
    GOLDEN_PATH.write_bytes(png_bytes)
    print(f"Updated golden card snapshot at {GOLDEN_PATH} ({len(png_bytes)} bytes)")


if __name__ == "__main__":
    update_golden()
