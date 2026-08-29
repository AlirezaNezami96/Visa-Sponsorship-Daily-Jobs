"""Golden-snapshot test for the brand-card renderer.

The renderer is deterministic by contract; this test catches silent layout
regressions. A fixture (job + fixed-color photo) is rendered and compared
byte-by-byte against a checked-in golden PNG under tests/goldens/card.png.

If the golden is intentionally updated (layout change), regenerate it with:
    python -m tests.update_golden_card
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageChops

from job_radar.social.card_renderer import CardJob, render_card_png

FIXTURE_PHOTO_PATH = Path(__file__).parent / "fixtures" / "photo.png"
GOLDEN_PATH = Path(__file__).parent / "goldens" / "card.png"

FIXTURE_JOB = CardJob(
    title="Senior Android Developer",
    country="Spain",
    city="Barcelona",
    visa_sponsorship_verified=True,
    visa_sponsorship_confidence=90,
)


def test_card_renderer_matches_golden():
    assert FIXTURE_PHOTO_PATH.is_file(), f"missing fixture photo: {FIXTURE_PHOTO_PATH}"
    assert GOLDEN_PATH.is_file(), f"missing golden card: {GOLDEN_PATH}"

    photo_bytes = FIXTURE_PHOTO_PATH.read_bytes()
    rendered_png = render_card_png(FIXTURE_JOB, photo_bytes)
    golden_png = GOLDEN_PATH.read_bytes()

    if rendered_png == golden_png:
        return

    rendered_img = Image.open(io.BytesIO(rendered_png)).convert("RGB")
    golden_img = Image.open(io.BytesIO(golden_png)).convert("RGB")

    assert rendered_img.size == golden_img.size
    diff = ImageChops.difference(rendered_img, golden_img)
    assert diff.getbbox() is None, "Rendered card differs from golden card snapshot"


def test_card_renderer_deterministic():
    assert FIXTURE_PHOTO_PATH.is_file(), f"missing fixture photo: {FIXTURE_PHOTO_PATH}"
    photo_bytes = FIXTURE_PHOTO_PATH.read_bytes()
    first = render_card_png(FIXTURE_JOB, photo_bytes)
    second = render_card_png(FIXTURE_JOB, photo_bytes)
    assert first == second
