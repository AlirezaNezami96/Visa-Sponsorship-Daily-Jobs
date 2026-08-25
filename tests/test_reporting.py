"""Tests for the reusable run-report layer (src/job_radar/reporting).

Covers: summary aggregation, top-job ranking, country/company/source/visa
aggregation, opportunity scoring + reasons, empty / one-job / large / malformed
sets, JSON + HTML rendering, and the Apify Key-Value Store writer (stubbed).
"""
from __future__ import annotations

import datetime
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.reporting.aggregations import (
    aggregate_companies,
    aggregate_countries,
    aggregate_sources,
    aggregate_visa,
    country_flag,
    detect_country,
    format_salary,
    is_visa_positive,
    is_visa_strong,
    opportunity_reasons,
    opportunity_score,
    rank_top_jobs,
    source_trust,
    time_ago,
    top_match_count,
    visa_info,
)
from job_radar.reporting.model import build_run_report
from job_radar.reporting.render_html import render_report_html
from job_radar.reporting.render_json import report_to_dict, report_to_json_string

_UTC = datetime.timezone.utc


def _job(
    idx: int,
    *,
    source: str = "greenhouse",
    company: str = "Acme",
    title: str = "Engineer",
    location: str = "Berlin, Germany",
    country: Optional[str] = "Germany",
    remote: bool = False,
    signal: str = "on_sponsor_list",
    score: float = 0.8,
    salary_min: Optional[float] = 70000,
    salary_max: Optional[float] = 90000,
    currency: str = "EUR",
    seniority: str = "senior",
    apply_url: Optional[str] = None,
    posted_hours_ago: Optional[float] = 12,
    category: Optional[str] = None,
    technologies: Optional[List[str]] = None,
) -> Job:
    posted = None
    if posted_hours_ago is not None:
        posted = datetime.datetime.now(_UTC) - datetime.timedelta(hours=posted_hours_ago)
    metadata: Dict[str, Any] = {}
    if category:
        metadata = {"overseas": True, "source_category": category, "source_domain": "x.example"}
    return Job(
        id=f"job-{idx}",
        source=source,
        title=f"{title} {idx}",
        company=f"{company} {idx}",
        location=location,
        country=country,
        remote=remote,
        visa_confidence=signal,
        composite_score=score,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        seniority=seniority,
        apply_url=apply_url or f"https://example.com/jobs/{idx}",
        posted_at=posted,
        technologies=technologies or ["Python"],
        metadata=metadata,
        description=f"Description for role {idx} working on python systems.",
    )


# --------------------------------------------------------------------------- #
# Aggregations
# --------------------------------------------------------------------------- #

def test_detect_country_explicit_then_location_then_city_then_remote():
    assert detect_country(_job(1, country="Germany")) == "Germany"
    assert detect_country(_job(2, country=None, location="Paris, France")) == "France"
    assert detect_country(_job(3, country=None, location="Amsterdam")) == "Netherlands"
    assert detect_country(_job(4, country=None, location="Nowhere", remote=True)) == "Remote"
    assert detect_country(_job(5, country=None, location="Nowhere", remote=False)) == "Other"


def test_country_flag_known_and_unknown():
    assert country_flag("Germany") == "🇩🇪"
    assert country_flag("Atlantis") == ""


def test_visa_info_tones():
    assert visa_info("stated_in_jd")["tone"] == "strong"
    assert visa_info("on_sponsor_list")["tone"] == "strong"
    assert visa_info("employer_sponsored_region")["tone"] == "possible"
    assert visa_info("historical_filings")["tone"] == "possible"
    assert visa_info("unknown")["tone"] == "neutral"
    assert visa_info("explicit_no")["tone"] == "negative"
    assert visa_info(None)["tone"] == "neutral"
    assert visa_info("not_a_signal")["tone"] == "neutral"
    assert is_visa_positive("on_sponsor_list") is True
    assert is_visa_positive("unknown") is False
    assert is_visa_strong("stated_in_jd") is True
    assert is_visa_strong("employer_sponsored_region") is False


def test_source_trust_baseline_and_overseas():
    assert source_trust(_job(1, source="greenhouse")) == "Company career page"
    assert source_trust(_job(2, source="remoteok")) == "Remote job board"
    assert source_trust(_job(3, source="overseas", category="government")) == "Government job portal"
    assert source_trust(_job(4, source="overseas", category="manpower_agency")) == "Recruitment agency"


def test_opportunity_score_and_clamp():
    assert opportunity_score(_job(1, score=0.91)) == 91
    assert opportunity_score(_job(2, score=None)) == 0
    assert opportunity_score(_job(3, score=1.7)) == 100
    assert opportunity_score(_job(4, score=-0.5)) == 0


def test_opportunity_reasons_are_data_backed():
    cfg = JobSearchConfig(keywords=["python"], countries=["Germany"], seniority_levels=["senior"])
    j = _job(1, signal="on_sponsor_list", location="Berlin, Germany", country="Germany",
             seniority="senior", posted_hours_ago=5, salary_max=90000)
    reasons = opportunity_reasons(j, cfg)
    joined = " | ".join(reasons).lower()
    assert "strong sponsorship evidence" in joined
    assert "python" in joined
    assert "germany" in joined
    assert "seniority" in joined
    assert "salary" in joined
    # No fabricated claims beyond 6 reasons.
    assert len(reasons) <= 6


def test_format_salary_variants():
    assert format_salary(_job(1, salary_min=75000, salary_max=95000, currency="EUR")) == "€75k–95k"
    assert format_salary(_job(2, salary_min=None, salary_max=None)) == ""
    assert format_salary(_job(3, salary_min=50000, salary_max=50000, currency="USD")) == "$50k"


def test_time_ago_buckets():
    assert time_ago(datetime.datetime.now(_UTC) - datetime.timedelta(hours=1)) == "1 hour ago"
    assert time_ago(datetime.datetime.now(_UTC) - datetime.timedelta(days=2)) == "2 days ago"
    assert time_ago(None) == ""


def test_top_match_count_sizing():
    assert top_match_count(0) == 0
    assert top_match_count(5) == 5
    assert top_match_count(12) == 10
    assert top_match_count(50) == 20
    assert top_match_count(5000) == 20


def test_rank_top_jobs_orders_by_score_desc():
    jobs = [_job(i, score=s) for i, s in enumerate([0.5, 0.9, 0.7])]
    top = rank_top_jobs(jobs, 3)
    assert [j.composite_score for j in top] == [0.9, 0.7, 0.5]


def test_aggregate_countries_counts_and_flags():
    jobs = [
        _job(1, country="Germany", signal="on_sponsor_list"),
        _job(2, country="Germany", signal="unknown"),
        _job(3, country="France", signal="stated_in_jd"),
    ]
    rows = aggregate_countries(jobs)
    by = {r["country"]: r for r in rows}
    assert by["Germany"]["jobs"] == 2
    assert by["Germany"]["visaPositive"] == 1
    assert by["Germany"]["highConfidence"] == 1  # on_sponsor_list is strong
    assert by["France"]["jobs"] == 1
    assert by["France"]["highConfidence"] == 1  # stated_in_jd is strong
    assert by["Germany"]["flag"] == "🇩🇪"


def test_aggregate_companies_groups_and_scores():
    # Build jobs with explicit company names (not idx-suffixed) to test grouping.
    j1 = Job(id="c1", source="greenhouse", title="Eng A", company="Acme",
             location="Berlin, Germany", country="Germany", visa_confidence="on_sponsor_list",
             composite_score=0.9)
    j2 = Job(id="c2", source="greenhouse", title="Eng B", company="Acme GmbH",
             location="Berlin, Germany", country="Germany", visa_confidence="unknown",
             composite_score=0.7)
    j3 = Job(id="c3", source="greenhouse", title="Eng C", company="Zeta",
             location="Paris, France", country="France", visa_confidence="unknown",
             composite_score=0.5)
    rows = aggregate_companies([j1, j2, j3])
    # "Acme" and "Acme GmbH" normalize to the same company ("acme").
    acme = next(r for r in rows if r["company"].lower().startswith("acme"))
    assert acme["jobs"] == 2
    assert acme["visaPositive"] == 1
    assert acme["highestScore"] == 90
    assert acme["countryCount"] == 1


def test_aggregate_sources_includes_failures():
    jobs = [_job(1, source="greenhouse"), _job(2, source="greenhouse"), _job(3, source="lever")]
    rows = aggregate_sources(jobs, ["greenhouse"], [{"name": "ashby", "error": "timeout"}])
    by = {r["source"]: r for r in rows}
    assert by["greenhouse"]["jobs"] == 2
    assert by["greenhouse"]["status"] == "ok"
    assert by["lever"]["jobs"] == 1
    assert by["ashby"]["jobs"] == 0
    assert by["ashby"]["status"] == "failed"
    assert by["ashby"]["error"] == "timeout"


def test_aggregate_visa_order_and_counts():
    jobs = [
        _job(1, signal="stated_in_jd"),
        _job(2, signal="on_sponsor_list"),
        _job(3, signal="on_sponsor_list"),
        _job(4, signal="unknown"),
    ]
    rows = aggregate_visa(jobs)
    order = [r["signal"] for r in rows]
    assert order.index("stated_in_jd") < order.index("on_sponsor_list") < order.index("unknown")
    by = {r["signal"]: r for r in rows}
    assert by["on_sponsor_list"]["count"] == 2


# --------------------------------------------------------------------------- #
# build_run_report: sizes and edge cases
# --------------------------------------------------------------------------- #

def _stats(**kw) -> Dict[str, Any]:
    base = {
        "totalFetched": 100, "totalFiltered": 50, "totalDeduplicated": 5,
        "simhashDuplicates": 0, "visaEnrichedJobs": 10, "aiClassifiedJobs": 0,
        "successfulSources": ["greenhouse"], "failedSources": [],
        "durationSeconds": 12.34,
    }
    base.update(kw)
    return base


def test_report_with_ten_jobs():
    jobs = [_job(i) for i in range(10)]
    r = build_run_report(jobs, JobSearchConfig(), _stats(), ["greenhouse"], [])
    assert r.status == "completed"
    assert r.empty is False
    assert len(r.topJobs) == 10
    assert r.summary["jobsEmitted"] == 10
    assert r.summary["visaRelevant"] == 10
    json.loads(report_to_json_string(r))


def test_report_one_job():
    r = build_run_report([_job(1)], JobSearchConfig(), _stats(), ["greenhouse"], [])
    assert len(r.topJobs) == 1
    assert r.topJobs[0].rank == 1


def test_report_empty_result_has_suggestions():
    cfg = JobSearchConfig(keywords=["android"], countries=["Germany"],
                          visa_sponsorship_only=True, min_visa_confidence="on_sponsor_list")
    r = build_run_report([], cfg, _stats(totalFetched=900), ["greenhouse"], [])
    assert r.status == "completed_empty"
    assert r.empty is True
    assert len(r.suggestions) > 0
    assert any("visa" in s.lower() for s in r.suggestions)
    html = render_report_html(r)
    assert "No matching jobs" in html


def test_report_large_set_is_bounded_and_fast():
    import time
    jobs = [_job(i, score=0.5 + (i % 50) / 100.0) for i in range(1200)]
    t0 = time.perf_counter()
    r = build_run_report(jobs, JobSearchConfig(), _stats(totalFetched=5000), ["greenhouse"], [])
    html = render_report_html(r)
    elapsed = time.perf_counter() - t0
    assert len(r.topJobs) == 20  # bounded, not 1200
    assert r.summary["jobsEmitted"] == 1200
    assert elapsed < 10.0, f"report generation too slow: {elapsed}s"
    assert "<!DOCTYPE html>" in html


def test_report_malformed_jobs_do_not_raise():
    # Pydantic validates required fields, so "malformed" here means jobs built
    # with only defaults / missing optional enrichment fields.
    messy = [
        Job(id="m1"),  # all defaults: title/company/description fall back
        Job(id="m2", source="greenhouse", title="Dev", company="Acme",
            composite_score=None, visa_confidence="unknown", posted_at=None, apply_url=None),
        _job(3),
    ]
    r = build_run_report(messy, JobSearchConfig(), _stats(), ["greenhouse"], [])
    assert r.status == "completed"
    html = render_report_html(r)
    assert "<!DOCTYPE html>" in html
    json.loads(report_to_json_string(r))


def test_failed_sources_become_warnings_not_traces():
    r = build_run_report([_job(1)], JobSearchConfig(), _stats(),
                         ["greenhouse"], [{"name": "lever", "error": "Traceback ... secret"}])
    assert any("lever" in w for w in r.warnings)
    assert all("Traceback" not in w for w in r.warnings)


def test_report_dict_is_json_serializable():
    r = build_run_report([_job(1)], JobSearchConfig(), _stats(), ["greenhouse"], [])
    d = report_to_dict(r)
    assert isinstance(d, dict)
    json.dumps(d)  # must not raise
    assert d["summary"]["jobsEmitted"] == 1


def test_html_escapes_user_content():
    evil = _job(1, title="<script>alert(1)</script>", company="A&B \"quoted\"")
    r = build_run_report([evil], JobSearchConfig(), _stats(), ["greenhouse"], [])
    html = render_report_html(r)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# --------------------------------------------------------------------------- #
# Apify Key-Value Store writer (stubbed SDK)
# --------------------------------------------------------------------------- #

def _install_fake_apify(monkeypatch):
    calls: Dict[str, Any] = {}

    class _FakeLog:
        def info(self, *a, **k):
            pass

        def warning(self, *a, **k):
            pass

        def error(self, *a, **k):
            pass

    class _FakeActor:
        log = _FakeLog()

        @staticmethod
        async def set_value(key, value, content_type=None):
            calls[key] = {"value": value, "content_type": content_type}

    fake_module = types.ModuleType("apify")
    fake_module.Actor = _FakeActor
    monkeypatch.setitem(sys.modules, "apify", fake_module)
    return calls


def test_report_writer_writes_json_and_html(monkeypatch):
    calls = _install_fake_apify(monkeypatch)
    from apify_actor.report_writer import write_apify_reports
    import asyncio

    written = asyncio.run(write_apify_reports(
        config=JobSearchConfig(),
        jobs=[_job(1), _job(2)],
        stats=_stats(),
        successful_sources=["greenhouse"],
        failed_sources=[],
        status="completed",
    ))
    assert written["reportJson"] == "REPORT.json"
    assert written["reportHtml"] == "REPORT.html"
    assert "REPORT.json" in calls and "REPORT.html" in calls
    assert calls["REPORT.html"]["content_type"].startswith("text/html")
    # JSON value must be a dict (Apify serializes it); HTML a string.
    assert isinstance(calls["REPORT.json"]["value"], dict)
    assert isinstance(calls["REPORT.html"]["value"], str)


def test_report_writer_never_raises(monkeypatch):
    class _Boom:
        log = type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})()

        @staticmethod
        async def set_value(*a, **k):
            raise RuntimeError("kvs down")

    fake = types.ModuleType("apify")
    fake.Actor = _Boom
    monkeypatch.setitem(sys.modules, "apify", fake)

    from apify_actor.report_writer import write_apify_reports
    import asyncio

    # Must swallow the failure and return {} — never propagate.
    written = asyncio.run(write_apify_reports(
        config=JobSearchConfig(), jobs=[_job(1)], stats=_stats(),
        successful_sources=["greenhouse"], failed_sources=[], status="completed",
    ))
    assert written == {}


# --------------------------------------------------------------------------- #
# Actor schema files
# --------------------------------------------------------------------------- #

def test_output_schema_links_dataset_and_kvs_records():
    data = json.loads(Path(".actor/output_schema.json").read_text(encoding="utf-8"))
    assert data["actorOutputSchemaVersion"] == 1
    props = data["properties"]
    assert "results" in props and "reportHtml" in props and "reportJson" in props
    assert "{{links.apiDefaultDatasetUrl}}/items" == props["results"]["template"]
    assert props["reportHtml"]["template"].endswith("/records/REPORT.html")
    assert props["reportJson"]["template"].endswith("/records/REPORT.json")


def test_actor_json_references_output_schema():
    data = json.loads(Path(".actor/actor.json").read_text(encoding="utf-8"))
    assert data.get("output") == "./output_schema.json"


def test_dataset_schema_modern_views_format():
    data = json.loads(Path(".actor/dataset_schema.json").read_text(encoding="utf-8"))
    assert data.get("actorSpecification") == 1
    assert "views" in data and "overview" in data["views"]
    assert data["views"]["overview"]["display"]["component"] == "table"
    # opportunityScore should be the leading, link-formatted apply column present.
    fields = data["views"]["overview"]["transformation"]["fields"]
    assert fields[0] == "opportunityScore"
    assert "applyUrl" in fields
    assert data["fields"]["properties"]["opportunityScore"]["type"] == "integer"


def test_opportunity_score_in_dataset_item():
    j = _job(1, score=0.77)
    out = j.to_apify_dict()
    assert out["opportunityScore"] == 77
    assert out["compositeScore"] == 0.77


def test_opportunity_score_absent_when_unscored():
    j = _job(1, score=None)
    out = j.to_apify_dict()
    assert "opportunityScore" not in out  # None values are stripped
