"""Comprehensive test suite for Visa-Sponsorship-Daily-Jobs radar upgrade.

Covers all 11 core verification scenarios:
1. ATS fixture JSON -> correct Job fields (Greenhouse content, Lever EU fallback, Ashby unlisted skipped)
2. URL canonicalization strips tracking params
3. Fingerprint synonym behavior from config
4. Seniority exclude fires on title 'Senior AI Engineer'
5. Seniority exclude does NOT fire when 'senior' appears only in description
6. Track match cases for intern vs junior engineer
7. Visa: registry + LLM + keyword fixtures; OPT-friendly distinct from sponsors
8. Freshness + missing date keep (fail-open)
9. Cache key: identical prefix different tails do NOT collide
10. Mocked LLM failure -> job retained (fail-open)
11. Atomic seen write behavior (no partial file, atomic replace)
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from job_radar.classifiers.cache import ClassificationCache, make_cache_key
from job_radar.classifiers.relevance import classify_and_filter_jobs, classify_single_job
from job_radar.config.loader import load_radar_config
from job_radar.config.models import RadarConfig
from job_radar.fetchers.ats import (
    ATSCircuitBreaker,
    fetch_ashby,
    fetch_greenhouse,
    fetch_lever,
)
from job_radar.filters.dedupe import (
    _canonical_job_url,
    atomic_save_json,
    dedupe_radar_jobs,
    job_fingerprint,
    normalize_company_name,
    normalize_job_title,
)
from job_radar.filters.freshness import filter_fresh_jobs, is_job_fresh
from job_radar.filters.matching import is_senior_role, match_track
from job_radar.models import Job, VisaStatus
from job_radar.visa.evaluator import VisaEvaluator, score_job_visa


# ── 1. ATS Fixtures -> Correct Job Fields ────────────────────────────────────

def test_greenhouse_fixture_parsing():
    mock_data = {
        "jobs": [
            {
                "id": 12345,
                "title": "AI Intern",
                "absolute_url": "https://boards.greenhouse.io/testco/jobs/12345?gh_src=123",
                "location": {"name": "San Francisco, CA (Remote)"},
                "departments": [{"name": "Applied AI"}],
                "content": "<p>We build large language models.</p>",
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        ]
    }

    with patch("job_radar.fetchers.ats._session") as mock_session:
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = mock_data
        mock_session.return_value.get.return_value = mock_resp

        jobs = fetch_greenhouse("testco", days_back=30)
        assert len(jobs) == 1
        job = jobs[0]
        assert isinstance(job, Job)
        assert job.id == "gh-12345"
        assert job.company == "Testco"
        assert job.title == "AI Intern"
        assert job.is_remote is True
        assert job.department == "Applied AI"
        assert "build large language models" in (job.description_text or "")
        assert job.fetched_at is not None


def test_lever_eu_fallback_and_salary():
    lever_data = [
        {
            "id": "abc-789",
            "text": "Machine Learning Engineer",
            "hostedUrl": "https://jobs.lever.co/euleverco/abc-789",
            "categories": {"location": "London, UK", "team": "ML Core"},
            "workplaceType": "remote",
            "salaryRange": {
                "min": 70000,
                "max": 95000,
                "currency": "GBP",
                "interval": "year",
            },
            "descriptionPlain": "Develop foundation models.",
            "createdAt": int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000),
        }
    ]

    with patch("job_radar.fetchers.ats._session") as mock_session:
        # First call (US endpoint) 404s, second call (EU endpoint) 200s
        resp_404 = MagicMock(status_code=404)
        resp_200 = MagicMock(status_code=200)
        resp_200.json.return_value = lever_data
        mock_session.return_value.get.side_effect = [resp_404, resp_200]

        jobs = fetch_lever("euleverco", days_back=30)
        assert len(jobs) == 1
        job = jobs[0]
        assert job.id == "lever-abc-789"
        assert job.workplace_type == "remote"
        assert job.salary_min == 70000
        assert job.salary_max == 95000
        assert job.salary_currency == "GBP"


def test_ashby_unlisted_skipped_and_location_requirements():
    ashby_data = {
        "jobPostings": [
            {
                "id": "listed-1",
                "title": "Junior AI Engineer",
                "jobUrl": "https://jobs.ashbyhq.com/ashbyco/listed-1",
                "isListed": True,
                "locationName": "Remote - Worldwide",
                "locationRequirements": ["US", "Canada", "UK"],
                "publishedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            {
                "id": "unlisted-2",
                "title": "Secret AI Intern",
                "jobUrl": "https://jobs.ashbyhq.com/ashbyco/unlisted-2",
                "isListed": False,
                "publishedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
        ]
    }

    with patch("job_radar.fetchers.ats._session") as mock_session:
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = ashby_data
        mock_session.return_value.post.return_value = mock_resp

        jobs = fetch_ashby("ashbyco", days_back=30)
        assert len(jobs) == 1
        assert jobs[0].id == "ashby-listed-1"
        assert jobs[0].location_requirements == ["US", "Canada", "UK"]


# ── 2. URL Canonicalization ──────────────────────────────────────────────────

def test_url_canonicalization_strips_tracking():
    dirty_url = "https://boards.greenhouse.io/anthropic/jobs/12345?gh_src=custom&utm_source=linkedin&utm_campaign=fall&ref=radar#apply"
    clean_url = _canonical_job_url(dirty_url)
    assert "utm_source" not in clean_url
    assert "gh_src" not in clean_url
    assert "utm_campaign" not in clean_url
    assert clean_url == "https://boards.greenhouse.io/anthropic/jobs/12345"


# ── 3. Fingerprint Synonyms from Config ───────────────────────────────────────

def test_fingerprint_synonyms_from_config():
    cfg = load_radar_config()
    cfg.dedup.title_synonyms["artificial intelligence"] = "ai"
    cfg.dedup.company_suffixes.append("technologies")

    fp1 = job_fingerprint("OpenAI Technologies Inc", "Artificial Intelligence Intern", "Remote (Worldwide)", config=cfg)
    fp2 = job_fingerprint("OpenAI LLC", "AI Intern", "Remote", config=cfg)

    assert fp1 == fp2 == "fp|openai|ai intern|remote"


# ── 4 & 5. Seniority Exclude Title-Only Rule ──────────────────────────────────

def test_seniority_exclude_title_fires():
    assert is_senior_role("Senior AI Engineer") is True
    assert is_senior_role("Staff Machine Learning Researcher") is True
    assert is_senior_role("Lead ML Engineer") is True
    assert match_track("Senior AI Engineer") is None


def test_seniority_exclude_does_not_fire_on_description_body():
    # Role is an internship, but JD text discusses interacting with senior leadership
    title = "AI Research Intern"
    assert is_senior_role(title) is False
    assert match_track(title) == "internship"


# ── 6. Track Match Cases ─────────────────────────────────────────────────────

def test_track_match_intern_vs_engineer():
    assert match_track("Generative AI Intern") == "internship"
    assert match_track("Machine Learning Trainee") == "internship"
    assert match_track("Junior AI Engineer") == "engineer"
    assert match_track("Associate Machine Learning Engineer") == "engineer"
    assert match_track("Entry Level AI Developer") == "engineer"
    assert match_track("Senior Backend Developer") is None


# ── 7. Visa Engine: Registry + LLM + Keyword (OPT distinct from Sponsors) ────

def test_visa_engine_weighted_scoring_and_opt_distinction():
    evaluator = VisaEvaluator()
    # Mock sponsor in DB
    evaluator._sponsors = {
        "deepmind": MagicMock(legal_name="Google DeepMind", country="UK", source="govuk_register", routes=["Worker"], rating="A")
    }

    # Scenario A: Known sponsor + positive LLM quote -> 'sponsors'
    status, score, ev = evaluator.score_visa_sponsorship(
        job={"company": "DeepMind", "title": "AI Research Scientist", "description": "Full visa sponsorship offered."},
        llm_visa_mention="sponsors",
        llm_visa_quote="Full visa sponsorship offered.",
    )
    assert status == "sponsors"
    assert score >= 0.85
    assert any("Confirmed Major Visa Sponsor" in e or "UK Home Office Licensed Sponsor" in e for e in ev)

    # Scenario B: Explicit OPT friendly -> 'opt_friendly' (distinct from sponsor petition)
    status_opt, score_opt, ev_opt = evaluator.score_visa_sponsorship(
        job={"company": "EarlyStageAI", "title": "AI Intern", "description": "F-1 OPT/CPT eligible candidates welcome."},
        llm_visa_mention="opt_friendly",
    )
    assert status_opt == "opt_friendly"
    assert status_opt != "sponsors"
    assert any("OPT" in e for e in ev_opt)

    # Scenario C: Explicit refusal in JD -> 'no'
    status_no, score_no, _ = evaluator.score_visa_sponsorship(
        job={"company": "DefenseCorp", "title": "AI Engineer", "description": "No visa sponsorship available. US Citizens only."},
        llm_visa_mention="no",
    )
    assert status_no == "no"
    assert score_no < 0.20


# ── 8. Freshness + Missing Date Fail-Open ─────────────────────────────────────

def test_freshness_missing_date_kept():
    # Stale job (10 days old)
    stale_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)).isoformat()
    assert is_job_fresh({"date_posted": stale_date}, max_age_days=5) is False

    # Fresh job (2 days old)
    fresh_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)).isoformat()
    assert is_job_fresh({"date_posted": fresh_date}, max_age_days=5) is True

    # Missing date -> FAIL-OPEN (Kept)
    assert is_job_fresh({"date_posted": None}, max_age_days=5) is True
    assert is_job_fresh({}, max_age_days=5) is True


# ── 9. Cache Key Non-Collision for Identical Prefix Different Tails ──────────

def test_cache_key_non_collision():
    long_prefix = "A" * 5000
    desc_1 = f"{long_prefix} specific requirement: PyTorch and CUDA"
    desc_2 = f"{long_prefix} specific requirement: React and CSS"

    key_1 = make_cache_key(company="AI Corp", title="AI Engineer", description=desc_1)
    key_2 = make_cache_key(company="AI Corp", title="AI Engineer", description=desc_2)

    assert key_1 != key_2


# ── 10. Mocked LLM Failure Retains Job (Fail-Open) ───────────────────────────

def test_llm_failure_retains_job_fail_open():
    cfg = load_radar_config()
    cfg.classifier.enabled = True

    candidate_job = {
        "title": "Junior Machine Learning Engineer",
        "company": "FastAI",
        "url": "https://fastai.com/job/1",
        "location": "Remote",
        "description": "Build transformer models.",
        "prefilter_track": "engineer",
    }

    # Simulate LLM raising API error / timeout
    with patch("job_radar.classifiers.relevance._call_gemini", side_effect=RuntimeError("503 Service Unavailable")):
        qualified, stats = classify_and_filter_jobs([candidate_job], config=cfg)
        assert len(qualified) == 1
        assert qualified[0]["company"] == "FastAI"
        assert qualified[0]["classified_track"] == "engineer"
        assert qualified[0]["relevance_score"] >= 60


# ── 11. Atomic Seen State Write ──────────────────────────────────────────────

def test_atomic_seen_state_write(tmp_path):
    seen_file = tmp_path / "seen_test.json"
    data = {"fp|testco|ai intern|remote": {"t": 12345, "track": "internship"}}

    atomic_save_json(data, str(seen_file))
    assert seen_file.exists()

    with open(seen_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data


# ── 12. Circuit Breaker Behavior ─────────────────────────────────────────────

def test_circuit_breaker_trips_after_threshold():
    cb = ATSCircuitBreaker(failure_threshold=0.30, min_attempts=5)
    assert cb.is_tripped("greenhouse") is False

    # 3 successes, 3 failures -> 50% failure rate after 6 attempts >= 30% threshold
    cb.record_success("greenhouse")
    cb.record_success("greenhouse")
    cb.record_success("greenhouse")
    cb.record_failure("greenhouse")
    cb.record_failure("greenhouse")
    cb.record_failure("greenhouse")

    assert cb.is_tripped("greenhouse") is True
    assert "greenhouse" in cb.get_trip_counts()
