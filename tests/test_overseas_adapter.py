"""Tests for OverseasAdapter with fully mocked HTTP (no network)."""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import httpx

from job_radar.models.config import JobSearchConfig
from job_radar.sources.base import SourceAdapter
from job_radar.sources.overseas.adapter import OverseasAdapter
from job_radar.sources.overseas.registry import OverseasSource

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "overseas"
WP_HTML = (FIXTURES / "wp_agency_list.html").read_text(encoding="utf-8")


def _source(domain: str, url: str = None) -> OverseasSource:
    return OverseasSource(
        domain=domain,
        start_urls=(url or f"https://{domain}/jobs",),
        category="manpower_agency",
        tier="tier2_board",
        enabled=True,
        country="UAE",
        rss_capable=False,
        sitemap_capable=False,
        wordpress=False,
    )


class FakeStreamResponse:
    def __init__(self, status_code, body=b"", content_type="text/html", exc=None):
        self.status_code = status_code
        self.headers = {"content-type": content_type} if content_type else {}
        self._body = body
        self._exc = exc

    async def __aenter__(self):
        if self._exc:
            raise self._exc
        return self

    async def __aexit__(self, *args):
        return False

    async def aiter_bytes(self):
        if self._body:
            yield self._body


class FakeRobotsResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeClient:
    """Minimal stand-in for httpx.AsyncClient."""

    def __init__(self, pages=None, robots=None, **kwargs):
        self.pages = pages or {}
        self.robots = robots or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, method, url, **kwargs):
        if url in self.pages:
            status, body, ct, exc = self.pages[url]
            return FakeStreamResponse(status, body, ct, exc)
        return FakeStreamResponse(404, b"", "text/html")

    async def get(self, url, **kwargs):
        for domain, (status, text) in self.robots.items():
            if url == f"https://{domain}/robots.txt":
                return FakeRobotsResponse(status, text)
        return FakeRobotsResponse(404, "")


def _make_fake_client_class(pages=None, robots=None):
    def factory(**kwargs):
        return FakeClient(pages=pages, robots=robots, **kwargs)
    return factory


def test_adapter_satisfies_source_adapter_interface():
    adapter = OverseasAdapter(JobSearchConfig(overseas_max_sources_per_run=5))
    assert isinstance(adapter, SourceAdapter)
    assert adapter.name == "overseas"
    assert adapter.source_type == "aggregator"
    assert adapter.supports_company_urls() is False
    assert adapter.fetch_timeout_secs == 600


def _run_adapter(adapter, config):
    return asyncio.run(adapter.fetch(config))


def test_mixed_success_and_failure_sources_do_not_raise():
    adapter = OverseasAdapter(JobSearchConfig(overseas_max_sources_per_run=10))
    adapter.sources = [
        _source("good.example", "https://good.example/jobs"),
        _source("bad.example", "https://bad.example/jobs"),
    ]
    pages = {
        "https://good.example/jobs": (200, WP_HTML.encode("utf-8"), "text/html", None),
        "https://bad.example/jobs": (500, b"", "text/html", httpx.ConnectError("connection reset")),
    }
    config = JobSearchConfig(max_results=50, respect_robots_txt=False)
    with patch("job_radar.sources.overseas.adapter.httpx.AsyncClient", _make_fake_client_class(pages)):
        jobs = _run_adapter(adapter, config)

    assert len(jobs) == 8
    failed_domains = {f["domain"] for f in adapter.failed_sources}
    assert "bad.example" in failed_domains
    assert "good.example" not in failed_domains
    job = jobs[0]
    assert job.source == "overseas"
    assert job.ats == "good.example"
    assert job.id.startswith("ov-good.example-")
    assert job.metadata["overseas"] is True
    assert job.metadata["source_category"] == "manpower_agency"
    assert job.metadata["source_domain"] == "good.example"
    assert "extraction_strategy" in job.metadata
    assert job.metadata["description_source"] == "list_card"
    # visa fields are not left by the adapter itself
    assert job.visa_sponsorship is None
    assert job.visa_type is None


def test_robots_disallow_skips_source():
    adapter = OverseasAdapter(JobSearchConfig(overseas_max_sources_per_run=10))
    adapter.sources = [_source("deny.example", "https://deny.example/jobs")]
    pages = {"https://deny.example/jobs": (200, WP_HTML.encode("utf-8"), "text/html", None)}
    robots = {"deny.example": (200, "User-agent: *\nDisallow: /\n")}
    config = JobSearchConfig(max_results=50, respect_robots_txt=True)
    with patch("job_radar.sources.overseas.adapter.httpx.AsyncClient", _make_fake_client_class(pages, robots)):
        jobs = _run_adapter(adapter, config)

    assert jobs == []
    assert any(s["domain"] == "deny.example" and s["error"] == "robots_disallowed" for s in adapter.skipped_sources)


def test_robots_allowed_source_fetches_normally():
    adapter = OverseasAdapter(JobSearchConfig(overseas_max_sources_per_run=10))
    adapter.sources = [_source("fine.example", "https://fine.example/jobs")]
    pages = {"https://fine.example/jobs": (200, WP_HTML.encode("utf-8"), "text/html", None)}
    robots = {"fine.example": (200, "User-agent: *\nAllow: /\n")}
    config = JobSearchConfig(max_results=50, respect_robots_txt=True)
    with patch("job_radar.sources.overseas.adapter.httpx.AsyncClient", _make_fake_client_class(pages, robots)):
        jobs = _run_adapter(adapter, config)
    assert len(jobs) == 8


def test_per_domain_cap_is_honored():
    cards = "".join(
        f'<div class="job-card"><a href="/vacancies/job-{i}/">Warehouse Worker Job {i} – Dubai</a>'
        f'<p>Salary: AED 20{i:02d}0 per month</p></div>'
        for i in range(60)
    )
    html = f"<html><body><div class='cards'>{cards}</div></body></html>"

    adapter = OverseasAdapter(JobSearchConfig(overseas_max_sources_per_run=10))
    adapter.sources = [_source("big.example", "https://big.example/jobs")]
    pages = {"https://big.example/jobs": (200, html.encode("utf-8"), "text/html", None)}
    config = JobSearchConfig(max_results=500, respect_robots_txt=False)
    with patch("job_radar.sources.overseas.adapter.httpx.AsyncClient", _make_fake_client_class(pages)):
        jobs = _run_adapter(adapter, config)
    assert len(jobs) == 50  # PER_DOMAIN_JOB_CAP


def test_total_raw_cap_is_max_results_times_three():
    cards = "".join(
        f'<div class="job-card"><a href="/vacancies/job-{i}/">Warehouse Worker Job {i} – Dubai</a>'
        f'<p>Salary: AED 20{i:02d}0 per month</p></div>'
        for i in range(60)
    )
    html = f"<html><body><div class='cards'>{cards}</div></body></html>"

    adapter = OverseasAdapter(JobSearchConfig(overseas_max_sources_per_run=10))
    adapter.sources = [
        _source("one.example", "https://one.example/jobs"),
        _source("two.example", "https://two.example/jobs"),
    ]
    pages = {
        "https://one.example/jobs": (200, html.encode("utf-8"), "text/html", None),
        "https://two.example/jobs": (200, html.encode("utf-8"), "text/html", None),
    }
    config = JobSearchConfig(max_results=10, respect_robots_txt=False)
    with patch("job_radar.sources.overseas.adapter.httpx.AsyncClient", _make_fake_client_class(pages)):
        jobs = _run_adapter(adapter, config)
    # raw cap = 10 * 3 = 30, applied before Job building
    assert len(jobs) <= 30


def test_destination_filter_drops_known_non_matching_and_keeps_unknown():
    html = (
        "<html><body><div class='cards'>"
        "<div class='job-card'><a href='/vacancies/1/'>Mason Job – Dubai UAE</a><p>Salary: AED 2500</p></div>"
        "<div class='job-card'><a href='/vacancies/2/'>Mason Job – Riyadh Saudi Arabia</a><p>Salary: SAR 1500</p></div>"
        "<div class='job-card'><a href='/vacancies/3/'>Helper Job – overseas project</a><p>Salary: USD 900</p></div>"
        "</div></body></html>"
    )
    adapter = OverseasAdapter(JobSearchConfig(overseas_max_sources_per_run=10))
    adapter.sources = [_source("dest.example", "https://dest.example/jobs")]
    pages = {"https://dest.example/jobs": (200, html.encode("utf-8"), "text/html", None)}
    config = JobSearchConfig(
        max_results=50, respect_robots_txt=False, overseas_destination_countries=["UAE"]
    )
    with patch("job_radar.sources.overseas.adapter.httpx.AsyncClient", _make_fake_client_class(pages)):
        jobs = _run_adapter(adapter, config)

    countries = [j.country for j in jobs]
    assert "UAE" in countries
    assert "Saudi Arabia" not in countries  # known non-matching dropped
    assert None in countries  # unknown destination kept
    assert adapter.stats["dropped_destination_filter"] == 1
