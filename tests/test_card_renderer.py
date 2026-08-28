"""Tests for the deterministic brand-card renderer + landmark sourcing."""

from __future__ import annotations

import datetime
import io
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

from job_radar.social import brand
from job_radar.social.card_renderer import (
    BADGE_SHIFT,
    CardJob,
    compute_layout,
    render_card,
    render_card_png,
)
from job_radar.social.landmark import fetch_landmark_photo, license_allowed

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "cards"
GOLDEN_PATH = FIXTURES_DIR / "golden_card.png"

FIXTURE_JOB = CardJob(
    title="Senior Android Developer",
    city="Barcelona",
    country="Spain",
    visa_sponsorship_verified=True,
    visa_sponsorship_confidence=88,
)


def fixture_photo_bytes() -> bytes:
    """Deterministic solid-color stand-in for a landmark photo."""
    img = Image.new("RGB", (1500, 1000), (70, 110, 150))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def pixel_diff_ratio(a: Image.Image, b: Image.Image) -> float:
    assert a.size == b.size
    pa, pb = a.convert("RGB").load(), b.convert("RGB").load()
    diff = 0
    for y in range(0, a.size[1], 2):
        row_a = [pa[x, y] for x in range(0, a.size[0], 2)]
        row_b = [pb[x, y] for x in range(0, a.size[0], 2)]
        diff += sum(1 for x, y_ in zip(row_a, row_b) if x != y_)
    sampled = (a.size[0] // 2) * (a.size[1] // 2)
    return diff / sampled if sampled else 0.0


class TestCardGoldenSnapshot(unittest.TestCase):
    """Golden PNG pins the reference layout (tolerance for antialiasing)."""

    def test_matches_golden(self):
        rendered = Image.open(io.BytesIO(render_card_png(FIXTURE_JOB, fixture_photo_bytes())))
        self.assertTrue(GOLDEN_PATH.is_file(), f"golden missing: {GOLDEN_PATH}")
        golden = Image.open(GOLDEN_PATH)
        self.assertEqual(rendered.size, golden.size)
        self.assertLessEqual(pixel_diff_ratio(rendered, golden), 0.005)

    def test_deterministic_bytes(self):
        first = render_card_png(FIXTURE_JOB, fixture_photo_bytes())
        second = render_card_png(FIXTURE_JOB, fixture_photo_bytes())
        self.assertEqual(first, second)


class TestCardLayout(unittest.TestCase):
    def test_title_wraps_two_lines_and_autofits(self):
        long_title = "Staff Platform Engineer — Kotlin Multiplatform, Cloud Infrastructure & Developer Experience"
        from job_radar.social.card_renderer import _fit_title

        lines, size = _fit_title(long_title, brand.CONTENT_WIDTH)
        self.assertLessEqual(len(lines), 2)
        self.assertIn(size, (96, 80, 66))
        # long title must shrink below the max size
        self.assertLess(size, 96)

    def test_short_title_keeps_max_size(self):
        from job_radar.social.card_renderer import _fit_title

        lines, size = _fit_title("Android Dev", brand.CONTENT_WIDTH)
        self.assertEqual(len(lines), 1)
        self.assertEqual(size, 96)

    def test_badge_hidden_below_confidence_threshold(self):
        job = CardJob(title="X", country="Y", visa_sponsorship_confidence=59)
        layout = compute_layout(job)
        self.assertFalse(layout.show_badge)

    def test_badge_shown_when_verified_or_high_confidence(self):
        verified = CardJob(title="X", country="Y", visa_sponsorship_verified=True)
        confident = CardJob(title="X", country="Y", visa_sponsorship_confidence=60)
        self.assertTrue(compute_layout(verified).show_badge)
        self.assertTrue(compute_layout(confident).show_badge)

    def test_rows_shift_up_when_badge_hidden(self):
        shown = compute_layout(CardJob(title="X", country="Y", visa_sponsorship_verified=True))
        hidden = compute_layout(CardJob(title="X", country="Y", visa_sponsorship_confidence=10))
        self.assertEqual(shown.apply_y - hidden.apply_y, BADGE_SHIFT)
        self.assertEqual(shown.footer_y - hidden.footer_y, BADGE_SHIFT)

    def test_remote_location_variants(self):
        from job_radar.social.card_renderer import _location_parts

        self.assertEqual(
            _location_parts(CardJob(title="t", country="Germany", work_mode="remote")),
            (None, "Remote — Germany"),
        )
        self.assertEqual(
            _location_parts(CardJob(title="t", country="", work_mode="remote")),
            (None, "Remote (Worldwide)"),
        )

    def test_location_variants(self):
        from job_radar.social.card_renderer import _location_parts

        self.assertEqual(
            _location_parts(CardJob(title="t", city="Berlin", country="Germany")),
            ("Berlin, ", "Germany"),
        )
        self.assertEqual(_location_parts(CardJob(title="t", city="Berlin")), ("Berlin", None))
        self.assertEqual(_location_parts(CardJob(title="t", country="Germany")), (None, "Germany"))

    def test_content_never_overlaps_photo_zone(self):
        """Invariant: the panel's slanted edge stays left of CONTENT_X at all y."""
        top_x = brand.WHITE_POLYGON[0][0]
        bottom_x = brand.WHITE_POLYGON[3][0]
        for y in range(0, brand.CARD_HEIGHT, 50):
            edge_x = top_x + (bottom_x - top_x) * (y / brand.CARD_HEIGHT)
            self.assertLess(edge_x, brand.CONTENT_X, f"edge crosses content at y={y}")

    def test_footer_right_aligned(self):
        img = render_card(FIXTURE_JOB, fixture_photo_bytes())
        layout = compute_layout(FIXTURE_JOB)
        px = img.convert("RGB").load()
        footer_rows = range(layout.footer_y, layout.footer_y + 32)
        rightmost = 0
        for y in footer_rows:
            for x in range(brand.CONTENT_RIGHT, brand.CONTENT_X, -1):
                if px[x, y] != (255, 255, 255):
                    rightmost = max(rightmost, x)
                    break
        # Red footer text should reach the right margin (within 6px).
        self.assertGreaterEqual(rightmost, brand.CONTENT_RIGHT - 6)

    def test_fallback_background_on_garbage_photo(self):
        png = render_card_png(FIXTURE_JOB, b"definitely-not-an-image")
        self.assertGreater(len(png), 1000)

    def test_fallback_background_on_missing_photo(self):
        img = render_card(FIXTURE_JOB, None)
        px = img.convert("RGB").load()
        # Left zone shows the deterministic navy + red band, not a photo.
        self.assertEqual(px[40, 300], tuple(int(brand.NAVY[i : i + 2], 16) for i in (1, 3, 5)))


class TestCardJobFromRow(unittest.TestCase):
    def test_maps_postgrest_row(self):
        from job_radar.social.card_renderer import card_job_from_row

        row = {
            "title": "Backend Engineer",
            "city": "Munich",
            "country": "Germany",
            "work_mode": "hybrid",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 91,
        }
        card = card_job_from_row(row)
        self.assertEqual(card.title, "Backend Engineer")
        self.assertEqual(card.city, "Munich")
        self.assertTrue(card.visa_sponsorship_verified)
        self.assertEqual(card.visa_sponsorship_confidence, 91)


class TestLicenseFilter(unittest.TestCase):
    def test_allowlist(self):
        for ok in [
            "Public Domain",
            "Public domain",
            "CC0",
            "CC0 1.0",
            "CC BY 2.0",
            "CC BY 4.0",
            "CC BY-SA 3.0",
            "CC BY-SA 4.0",
        ]:
            self.assertTrue(license_allowed(ok), ok)

    def test_rejects_non_allowlist(self):
        for bad in [
            None,
            "",
            "CC BY-NC 4.0",
            "CC BY-NC-SA 4.0",
            "CC BY-ND 4.0",
            "CC BY-SA-NC 2.0",
            "GFDL",
            "All rights reserved",
            "MIT",
        ]:
            self.assertFalse(license_allowed(bad), str(bad))


class _FakeResponse:
    def __init__(self, status_code=200, content=b"", json_data=None):
        self.status_code = status_code
        self.content = content
        self._json = json_data

    def json(self):
        return self._json


class _FakeSession:
    """Records calls; returns queued responses per URL keyword."""

    def __init__(self, responses: dict[str, _FakeResponse]):
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        for key, resp in self.responses.items():
            if key in url:
                return resp
        return _FakeResponse(status_code=404)


def _search_json(license_short: str, width: int = 2500) -> dict:
    return {
        "query": {
            "pages": {
                "1": {
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/full.jpg",
                            "thumburl": "https://upload.wikimedia.org/thumb.jpg",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:x",
                            "width": width,
                            "height": 1600,
                            "extmetadata": {
                                "LicenseShortName": {"value": license_short},
                                "Artist": {"value": "<a href='#'>Photographer Name</a>"},
                            },
                        }
                    ]
                }
            }
        }
    }


class TestLandmarkFetch(unittest.TestCase):
    def _fake_client(self, media_rows=None):
        client = MagicMock()
        table = MagicMock()
        query = MagicMock()
        client.table.return_value = table
        table.select.return_value = query
        query.select.return_value = query
        query.eq.return_value = query
        query.execute.return_value = MagicMock(data=media_rows or [])
        table.upsert.return_value = query
        return client

    def _fake_storage(self, photo: bytes | None = None):
        storage = MagicMock()
        storage.read_storage_bytes.return_value = photo
        storage.upload_storage_file.return_value = {"storage_path": "landmarks/x.jpg"}
        return storage

    def test_fresh_fetch_uploads_and_records_metadata(self):
        client = self._fake_client()
        session = _FakeSession(
            {
                "commons.wikimedia.org/w/api.php": _FakeResponse(json_data=_search_json("CC BY-SA 4.0")),
                "thumb.jpg": _FakeResponse(content=b"JPEGDATA"),
            }
        )
        storage = self._fake_storage()

        photo, meta = fetch_landmark_photo(client, "Barcelona", "Spain", storage=storage, session=session)

        self.assertEqual(photo, b"JPEGDATA")
        self.assertEqual(meta["license"], "CC BY-SA 4.0")
        self.assertEqual(meta["attribution"], "Photographer Name")
        storage.upload_storage_file.assert_called_once()
        args, _kwargs = storage.upload_storage_file.call_args
        self.assertEqual(args[0], "media")
        self.assertTrue(args[1].startswith("landmarks/"))
        client.table.assert_any_call("media_assets")

    def test_rejects_unlicensed_image(self):
        client = self._fake_client()
        session = _FakeSession(
            {"commons.wikimedia.org/w/api.php": _FakeResponse(json_data=_search_json("CC BY-NC-SA 4.0"))}
        )
        storage = self._fake_storage()

        photo, meta = fetch_landmark_photo(client, "Barcelona", "Spain", storage=storage, session=session)

        self.assertIsNone(photo)
        self.assertIsNone(meta)
        storage.upload_storage_file.assert_not_called()

    def test_cache_hit_avoids_network(self):
        fresh = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=2)).isoformat()
        client = self._fake_client(
            media_rows=[
                {
                    "storage_path": "landmarks/spain-barcelona.jpg",
                    "source_url": "https://commons.wikimedia.org/wiki/File:x",
                    "license": "CC BY 4.0",
                    "attribution": "Someone",
                    "fetched_at": fresh,
                }
            ]
        )
        session = _FakeSession({})
        storage = self._fake_storage(photo=b"CACHED")

        photo, meta = fetch_landmark_photo(client, "Barcelona", "Spain", storage=storage, session=session)

        self.assertEqual(photo, b"CACHED")
        self.assertEqual(meta["license"], "CC BY 4.0")
        self.assertEqual(session.calls, [])
        storage.upload_storage_file.assert_not_called()

    def test_stale_cache_refetches(self):
        stale = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=45)).isoformat()
        client = self._fake_client(
            media_rows=[
                {
                    "storage_path": "landmarks/spain-barcelona.jpg",
                    "license": "CC BY 4.0",
                    "fetched_at": stale,
                }
            ]
        )
        session = _FakeSession(
            {
                "commons.wikimedia.org/w/api.php": _FakeResponse(json_data=_search_json("CC0 1.0")),
                "thumb.jpg": _FakeResponse(content=b"FRESH"),
            }
        )
        photo, meta = fetch_landmark_photo(client, "Barcelona", "Spain", storage=self._fake_storage(), session=session)
        self.assertEqual(photo, b"FRESH")
        self.assertEqual(meta["license"], "CC0 1.0")

    def test_missing_city_or_country_returns_none(self):
        photo, meta = fetch_landmark_photo(self._fake_client(), "", "Spain")
        self.assertEqual((photo, meta), (None, None))

    def test_never_raises_on_network_failure(self):
        class BoomSession:
            def get(self, *a, **k):
                raise OSError("network down")

        photo, meta = fetch_landmark_photo(
            self._fake_client(), "X", "Y", storage=self._fake_storage(), session=BoomSession()
        )
        self.assertEqual((photo, meta), (None, None))


class _InsertRecorder:
    """Minimal supabase-like client recording social_post_queue inserts."""

    def __init__(self):
        self.rows: list[dict] = []

    class _Table:
        def __init__(self, outer: _InsertRecorder):
            self._outer = outer

        def insert(self, payload):
            self._outer.rows.extend(payload if isinstance(payload, list) else [payload])

            class _Query:
                def execute(self_inner):
                    return MagicMock(data=list(self._outer.rows))

            return _Query()

    def table(self, name):
        assert name == "social_post_queue"
        return _InsertRecorder._Table(self)


class TestSocialQueueCardFactory(unittest.TestCase):
    def test_enqueue_with_card_factory_sets_image_path(self):
        from job_radar.visalane.social_queue import enqueue_jobs

        client = _InsertRecorder()
        jobs = [
            {"job_db_id": "job-1", "title": "A", "company": "C1", "country": "Germany"},
            {"job_db_id": "job-2", "title": "B", "company": "C2", "country": "France"},
        ]
        factory_calls: list[list[dict]] = []

        def factory(batch):
            factory_calls.append(batch)
            return f"cards/{batch[0]['job_db_id']}.png"

        created = enqueue_jobs(client, jobs, platforms=["telegram"], card_factory=factory)

        self.assertEqual(created, 1)
        self.assertEqual(client.rows[0]["image_path"], "cards/job-1.png")
        self.assertEqual(len(factory_calls), 1)

    def test_card_factory_failure_falls_back_to_none(self):
        from job_radar.visalane.social_queue import enqueue_jobs

        client = _InsertRecorder()
        jobs = [{"job_db_id": "job-9", "title": "A", "company": "C", "country": "Germany"}]

        def factory(batch):
            raise RuntimeError("render exploded")

        created = enqueue_jobs(client, jobs, platforms=["telegram"], card_factory=factory)
        self.assertEqual(created, 1)
        self.assertIsNone(client.rows[0]["image_path"])


if __name__ == "__main__":
    unittest.main()
