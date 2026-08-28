"""Tests for the overseas extraction ladder (RSS, JSON-LD, DOM cards)."""
from pathlib import Path

from job_radar.sources.overseas.extractors import (
    STRATEGY_DOM,
    STRATEGY_JSONLD,
    STRATEGY_RSS,
    discover_feed_urls,
    extract_all,
    extract_dom_cards,
    extract_jsonld,
    extract_rss,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "overseas"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_rss_feed_yields_five_jobs_with_mapped_fields():
    content = _read("feed.xml")
    jobs = extract_rss(content, "https://overseasjobs.example")
    assert len(jobs) == 5
    first = jobs[0]
    assert first.strategy == STRATEGY_RSS
    assert first.title == "Scaffolder – Dubai walk-in interview"
    assert first.apply_url == "https://overseasjobs.example/jobs/scaffolder-dubai"
    assert "scaffolders" in first.description.lower()
    assert "<" not in first.description  # HTML stripped
    assert first.posted_at is not None
    assert first.posted_at.tzinfo is not None
    assert first.posted_at.year == 2026
    # dc:creator that looks like an employer becomes the company
    assert first.company == "Emirates Workforce Recruitment LLC"
    # generic author falls back to feed title
    assert jobs[2].company == "Overseas Jobs Daily – Gulf Edition"
    # location resolved via destination lexicon
    assert first.location == "UAE"
    assert jobs[1].location == "Saudi Arabia"
    # salary parsed from summary
    assert first.salary_min == 2100.0
    assert first.salary_currency == "AED"


def test_jsonld_jobposting_extraction():
    content = _read("detail_jsonld.html")
    jobs = extract_jsonld(content, "https://alrashid.example")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.strategy == STRATEGY_JSONLD
    assert job.title == "Heavy Equipment Operator"
    assert job.company == "Al Rashid Manpower Services"
    assert "Doha" in (job.location or "")
    assert job.salary_min == 3000.0
    assert job.salary_max == 4000.0
    assert job.salary_currency == "QAR"
    assert job.salary_period == "monthly"
    assert job.posted_at is not None and job.posted_at.year == 2026
    assert job.apply_url == "https://alrashid.example/jobs/heavy-equipment-operator"
    assert "<b>" not in job.description
    assert "Heavy Equipment Operator" in job.description


def test_dom_cards_wordpress_style_list():
    content = _read("wp_agency_list.html")
    jobs = extract_dom_cards(content, "https://gulfmanpower.example")
    assert len(jobs) == 8
    assert all(j.strategy == STRATEGY_DOM for j in jobs)
    assert all(j.apply_url.startswith("https://gulfmanpower.example/vacancies/") for j in jobs)
    assert all(len(j.description) > 0 for j in jobs)
    titles = [j.title for j in jobs]
    assert any("Mason" in t and "Dubai" in t for t in titles)
    # nav links must not appear
    for j in jobs:
        assert "Home" != j.title and "About Us" != j.title and "Contact" != j.title
    mason = next(j for j in jobs if "Mason" in j.title)
    assert mason.company == "Al Rashid Manpower"
    assert mason.location == "UAE"
    assert mason.salary_min == 2500.0
    assert mason.salary_currency == "AED"
    assert mason.posted_at is not None and mason.posted_at.month == 8


def test_dom_cards_list_cluster():
    content = _read("card_cluster.html")
    jobs = extract_dom_cards(content, "https://eastasia.example")
    assert len(jobs) == 6
    assert all(j.apply_url.startswith("https://eastasia.example/jobs/") for j in jobs)
    assert all(len(j.description) > 0 for j in jobs)
    welder = next(j for j in jobs if "Welder" in j.title)
    assert welder.company == "Nihon Staffing Partners"
    assert welder.location == "Japan"


def test_no_jobs_page_is_empty():
    content = _read("no_jobs.html")
    assert extract_dom_cards(content, "https://gulfmanpower.example") == []
    jobs, strategy = extract_all(content, "https://gulfmanpower.example")
    assert jobs == []
    assert strategy is None


def test_ladder_prefers_jsonld_over_dom_and_rss_first():
    detail = _read("detail_jsonld.html")
    jobs, strategy = extract_all(detail, "https://alrashid.example", content_type="text/html")
    assert strategy == STRATEGY_JSONLD
    assert len(jobs) == 1

    feed = _read("feed.xml")
    jobs, strategy = extract_all(feed, "https://overseasjobs.example", content_type="application/rss+xml")
    assert strategy == STRATEGY_RSS
    assert len(jobs) == 5

    wp = _read("wp_agency_list.html")
    jobs, strategy = extract_all(wp, "https://gulfmanpower.example", content_type="text/html")
    assert strategy == STRATEGY_DOM
    assert len(jobs) == 8


def test_feed_url_autodiscovery():
    html = (
        "<html><head>"
        '<link rel="alternate" type="application/rss+xml" href="/feed/">'
        "</head><body></body></html>"
    )
    urls = discover_feed_urls(html, "https://example.org")
    assert urls == ["https://example.org/feed/"]
    assert discover_feed_urls("<html></html>", "https://example.org") == []
