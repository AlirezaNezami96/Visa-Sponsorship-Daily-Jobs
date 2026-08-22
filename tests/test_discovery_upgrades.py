"""Unit tests for Phase 3 discovery upgrades: Jobicy, Arbeitnow UK, Adzuna, and funding watch."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_radar.fetchers.public_apis import fetch_jobicy, fetch_arbeitnow_uk, fetch_adzuna
from job_radar.fetchers.funding_watch import FundingWatchlist


def test_jobicy_parsing():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jobs": [
            {
                "id": 101,
                "jobTitle": "Senior AI Infrastructure Engineer",
                "companyName": "TensorFlow Scale",
                "url": "https://jobicy.com/jobs/101",
                "jobGeo": "Worldwide",
                "jobExcerpt": "Scale LLM training clusters...",
                "jobDescription": "Full details on scaling...",
                "pubDate": "2026-08-20T10:00:00Z"
            }
        ]
    }
    with patch("requests.Session.get", return_value=mock_resp):
        jobs = fetch_jobicy(count=1)
        assert len(jobs) == 1
        assert jobs[0]["title"] == "Senior AI Infrastructure Engineer"
        assert jobs[0]["company"] == "TensorFlow Scale"
        assert jobs[0]["remote_scope"] == "worldwide"
        assert jobs[0]["source"] == "jobicy"


def test_arbeitnow_uk_parsing():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {
                "title": "Machine Learning Engineer",
                "company_name": "London AI Labs",
                "url": "https://arbeitnow.co.uk/jobs/202",
                "location": "London",
                "remote": True,
                "description": "Build agentic LLM systems in UK."
            }
        ]
    }
    with patch("requests.Session.get", return_value=mock_resp):
        jobs = fetch_arbeitnow_uk()
        assert len(jobs) == 1
        assert jobs[0]["company"] == "London AI Labs"
        assert jobs[0]["source"] == "arbeitnow_uk"
        assert jobs[0]["allowed_regions"] == ["UK"]


def test_funding_watchlist(tmp_path):
    storage = tmp_path / "test_watchlist.json"
    wl = FundingWatchlist(storage_path=storage)

    wl.add_funded_company("Cognition AI", round_name="Series A", amount_usd=21000000)

    # Check match
    is_watched, desc = wl.check_company("Cognition AI Inc")
    assert is_watched is True
    assert "Series A" in desc

    # Non-funded company
    is_watched, desc = wl.check_company("Random Corp")
    assert is_watched is False
    assert desc is None
