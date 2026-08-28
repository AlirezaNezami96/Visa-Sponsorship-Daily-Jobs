"""Tests for SourceAdapter implementations with mocked HTTP responses."""
import asyncio
import time
from unittest.mock import MagicMock, patch

from job_radar.models.config import JobSearchConfig
from job_radar.sources.greenhouse import GreenhouseAdapter
from job_radar.sources.jobicy import JobicyAdapter
from job_radar.sources.lever import LeverAdapter
from job_radar.sources.registry import SOURCE_REGISTRY, get_enabled_sources


def test_source_registry_contains_all_adapters():
    expected = [
        "greenhouse", "lever", "ashby", "workable", "smartrecruiters", "personio",
        "remoteok", "remotive", "arbeitnow", "himalayas", "hn_whoshiring", "jobicy"
    ]
    for name in expected:
        assert name in SOURCE_REGISTRY

    config = JobSearchConfig(sources=["greenhouse", "lever"])
    enabled = get_enabled_sources(config)
    assert len(enabled) == 2
    assert [a.name for a in enabled] == ["greenhouse", "lever"]


def test_greenhouse_adapter_mocked():
    async def _test():
        adapter = GreenhouseAdapter()
        config = JobSearchConfig(company_urls=["https://boards.greenhouse.io/stripe"])

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jobs": [
                {
                    "id": 12345,
                    "title": "Software Engineer",
                    "absolute_url": "https://boards.greenhouse.io/stripe/jobs/12345",
                    "location": {"name": "Remote"},
                    "updated_at": "2026-08-20T00:00:00Z",
                    "content": "<p>Build global payments</p>",
                }
            ]
        }

        with patch("job_radar.fetchers.ats._session") as mock_sess:
            mock_sess.return_value.get.return_value = mock_response
            jobs = await adapter.fetch(config)
            assert len(jobs) == 1
            assert jobs[0].title == "Software Engineer"
            assert jobs[0].source == "greenhouse"

    asyncio.run(_test())


def test_lever_adapter_mocked():
    async def _test():
        adapter = LeverAdapter()
        config = JobSearchConfig(company_urls=["https://jobs.lever.co/example"])

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": "lever-123",
                "text": "Machine Learning Engineer",
                "hostedUrl": "https://jobs.lever.co/example/123",
                "categories": {"location": "Remote"},
                "createdAt": int(time.time() * 1000),
                "description": "<p>ML platform</p>",
            }
        ]

        with patch("job_radar.fetchers.ats._session") as mock_sess:
            mock_sess.return_value.get.return_value = mock_response
            jobs = await adapter.fetch(config)
            assert len(jobs) == 1
            assert jobs[0].title == "Machine Learning Engineer"
            assert jobs[0].source == "lever"

    asyncio.run(_test())


def test_jobicy_adapter_mocked():
    async def _test():
        adapter = JobicyAdapter()
        config = JobSearchConfig(max_per_source=10)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jobs": [
                {
                    "jobTitle": "Lead Python Developer",
                    "companyName": "TechCo",
                    "url": "https://jobicy.com/jobs/123",
                    "jobGeo": "Worldwide",
                    "jobDescription": "Python backend development",
                    "pubDate": "2026-08-20",
                }
            ]
        }

        with patch("job_radar.fetchers.public_apis._session") as mock_sess:
            mock_sess.return_value.get.return_value = mock_response
            jobs = await adapter.fetch(config)
            assert len(jobs) == 1
            assert jobs[0].title == "Lead Python Developer"
            assert jobs[0].company == "TechCo"
            assert jobs[0].source == "jobicy"

    asyncio.run(_test())
