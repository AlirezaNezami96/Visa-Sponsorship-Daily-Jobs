"""Regression tests for image worker CardJob contract, landmark sourcing, and Wikimedia circuit breaker."""
from unittest.mock import MagicMock, patch
import pytest

from job_radar.social.card_renderer import CardJob
from job_radar.pipeline.image_worker import render_and_upload


class MockImageSupabase:
    def __init__(self, job_data=None):
        self.job_data = job_data
        self.circuits = {}
        self.metrics = []
        self.storage_uploads = []

    def table(self, name):
        mock_t = MagicMock()
        if name == "jobs":
            mock_t.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = self.job_data
            mock_t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        elif name == "job_processing":
            mock_t.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
                "job_id": "test-job-1",
                "image_status": "processing",
            }
            mock_t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        elif name == "service_circuits":
            mock_t.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = self.circuits.get("wikimedia")
            mock_t.insert.return_value.execute.return_value = MagicMock()
            mock_t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        elif name == "metrics_daily":
            mock_t.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
            mock_t.insert.return_value.execute.return_value = MagicMock()
            mock_t.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock()
        return mock_t

    @property
    def storage(self):
        mock_s = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.upload.side_effect = lambda path, b, **kw: self.storage_uploads.append((path, b))
        mock_s.from_.return_value = mock_bucket
        return mock_s

    def rpc(self, name, params):
        mock_r = MagicMock()
        mock_r.execute.return_value = MagicMock()
        return mock_r


def test_render_and_upload_with_card_job_contract():
    """Verify render_and_upload constructs CardJob and successfully renders and uploads PNG."""
    job_row = {
        "id": "11111111-2222-3333-4444-555555555555",
        "title": "Staff Backend Engineer",
        "company": "Stripe",
        "country": "Germany",
        "city": "Berlin",
        "location": "Berlin, Germany",
        "work_mode": "hybrid",
        "salary_min": 100000,
        "salary_max": 140000,
        "salary_currency": "EUR",
        "visa_sponsorship_verified": True,
        "visa_sponsorship_confidence": 95,
        "skills": ["Python", "Go", "Distributed Systems"],
    }
    client = MockImageSupabase(job_data=job_row)

    with patch("job_radar.pipeline.image_worker.fetch_landmark_photo", return_value=(b"fake_landmark_png", {"license": "CC-BY"})):
        res = render_and_upload("11111111-2222-3333-4444-555555555555", client=client)

    assert res["ok"] is True
    assert "cards/11111111-2222-3333-4444-555555555555.png" in res["image_url"]
    assert len(client.storage_uploads) == 1


def test_render_and_upload_landmark_fallback():
    """Verify clean fallback when landmark photo is not found or returns (None, None)."""
    job_row = {
        "id": "22222222-3333-4444-5555-666666666666",
        "title": "Frontend Lead",
        "company": "Spotify",
        "country": "Sweden",
        "city": "Stockholm",
        "work_mode": "remote",
        "visa_sponsorship_verified": True,
        "visa_sponsorship_confidence": 80,
    }
    client = MockImageSupabase(job_data=job_row)

    with patch("job_radar.pipeline.image_worker.fetch_landmark_photo", return_value=(None, None)):
        res = render_and_upload("22222222-3333-4444-5555-666666666666", client=client)

    assert res["ok"] is True
    assert len(client.storage_uploads) == 1


def test_wikimedia_circuit_breaker_skips_when_open():
    """Verify landmark fetching is bypassed when wikimedia circuit is open."""
    job_row = {
        "id": "33333333-4444-5555-6666-777777777777",
        "title": "DevOps Engineer",
        "company": "Klarna",
        "country": "Sweden",
        "city": "Stockholm",
    }
    client = MockImageSupabase(job_data=job_row)
    from datetime import datetime, timezone
    client.circuits["wikimedia"] = {
        "name": "wikimedia",
        "state": "open",
        "consecutive_failures": 5,
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }

    with patch("job_radar.pipeline.image_worker.fetch_landmark_photo") as mock_fetch:
        res = render_and_upload("33333333-4444-5555-6666-777777777777", client=client)
        # Sourcing should be skipped because circuit is open
        mock_fetch.assert_not_called()

    assert res["ok"] is True
