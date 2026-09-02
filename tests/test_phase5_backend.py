"""
Automated unit and integration test suite for VisaLane Phase 5 Backend API.
Verifies company name normalization, trigram fuzzy matching with hard fixture boundaries,
extension lookup endpoint (/api/v1/extension/lookup), extension-safe rate limiting,
caching, and extension badge event tracking.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient

from engine.api.main import app
from engine.api.cache import clear_all_caches
from engine.api.company_matcher import (
    calculate_token_similarity,
    calculate_trigram_similarity,
    generate_trigrams,
    match_company_fuzzy,
    normalize_company_name,
)
from engine.api.jobs_routes import (
    clear_mock_stores,
    get_mock_events_store,
    limiter,
    set_mock_jobs_store,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_phase5_data():
    """Seed sample employer and job dataset for extension tests."""
    try:
        limiter.reset()
    except Exception:
        pass
    clear_all_caches()
    clear_mock_stores()

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    jobs = [
        # Google jobs
        {
            "id": "g-001",
            "title": "Senior Software Engineer",
            "company_name": "Google",
            "country": "Germany",
            "country_code": "DE",
            "visa_types": ["EU Blue Card"],
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 98,
            "status": "active",
            "posted_at": now,
        },
        {
            "id": "g-002",
            "title": "Site Reliability Engineer",
            "company_name": "Google",
            "country": "United States",
            "country_code": "US",
            "visa_types": ["H-1B"],
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 95,
            "status": "active",
            "posted_at": now,
        },
        # Spotify jobs
        {
            "id": "s-001",
            "title": "Backend Developer",
            "company_name": "Spotify",
            "country": "Sweden",
            "country_code": "SE",
            "visa_types": ["EU Blue Card"],
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 92,
            "status": "active",
            "posted_at": now,
        },
        # Amazon jobs
        {
            "id": "a-001",
            "title": "Cloud Architect",
            "company_name": "Amazon",
            "country": "United Kingdom",
            "country_code": "GB",
            "visa_types": ["Skilled Worker"],
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 94,
            "status": "active",
            "posted_at": now,
        },
        # Stripe jobs
        {
            "id": "st-001",
            "title": "Staff Infrastructure Engineer",
            "company_name": "Stripe",
            "country": "Ireland",
            "country_code": "IE",
            "visa_types": ["Critical Skills Employment Permit"],
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 96,
            "status": "active",
            "posted_at": now,
        },
        # Zalando jobs
        {
            "id": "z-001",
            "title": "Data Scientist",
            "company_name": "Zalando",
            "country": "Germany",
            "country_code": "DE",
            "visa_types": ["EU Blue Card"],
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 88,
            "status": "active",
            "posted_at": now,
        },
    ]
    set_mock_jobs_store(jobs)

    yield

    try:
        limiter.reset()
    except Exception:
        pass
    clear_all_caches()
    clear_mock_stores()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Unit Tests: Normalization & Legal Suffix Stripping
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_company_name_basic_legal_suffixes():
    """Verify standard legal suffixes and acronyms are cleanly stripped."""
    assert normalize_company_name("Google LLC") == "google"
    assert normalize_company_name("Google Inc.") == "google"
    assert normalize_company_name("Google, Incorporated") == "google"
    assert normalize_company_name("Google Ltd.") == "google"
    assert normalize_company_name("Google GmbH") == "google"
    assert normalize_company_name("Google Corp.") == "google"
    assert normalize_company_name("Google B.V.") == "google"
    assert normalize_company_name("Google Pte. Ltd.") == "google"
    assert normalize_company_name("Google Pty. Ltd.") == "google"
    assert normalize_company_name("Google S.A.") == "google"
    assert normalize_company_name("Google S.R.L.") == "google"


def test_normalize_company_name_parentheticals_and_regional_suffixes():
    """Verify bracketed annotations and regional suffixes are cleanly removed."""
    assert normalize_company_name("Amazon Web Services (AWS)") == "amazon"
    assert normalize_company_name("Datadog [HQ]") == "datadog"
    assert normalize_company_name("Revolut (UK)") == "revolut"
    assert normalize_company_name("Stripe Payments Europe, Ltd.") == "stripe"
    assert normalize_company_name("Spotify AB") == "spotify"
    assert normalize_company_name("Spotify USA Inc") == "spotify"
    assert normalize_company_name("Meta Platforms, Inc.") == "meta"
    assert normalize_company_name("Siemens AG") == "siemens"
    assert normalize_company_name("Zalando SE") == "zalando"


def test_normalize_company_name_accents_and_punctuation():
    """Verify accents and non-alphanumeric punctuation are sanitized."""
    assert normalize_company_name("Société Générale S.A.") == "societe generale"
    assert normalize_company_name("L'Oréal S.A.") == "l oreal"
    assert normalize_company_name("McKinsey & Company") == "mckinsey"
    assert normalize_company_name("") == ""
    assert normalize_company_name(None) == ""


# ─────────────────────────────────────────────────────────────────────────────
# 2. Hard Fixture Matching & False-Positive Boundary Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_fuzzy_matching_hard_fixture_matches():
    """
    Test deliberately messy real-world variations against candidate database.
    All of these must successfully match their respective canonical employer.
    """
    candidates = [
        {"name": "Google", "slug": "google"},
        {"name": "Spotify", "slug": "spotify"},
        {"name": "Amazon", "slug": "amazon"},
        {"name": "Stripe", "slug": "stripe"},
        {"name": "Zalando", "slug": "zalando"},
        {"name": "Siemens", "slug": "siemens"},
        {"name": "Meta", "slug": "meta"},
        {"name": "Apple", "slug": "apple"},
    ]

    # Test cases: (Input Query, Expected Target Slug, Minimum Similarity Score)
    fixture_matches = [
        ("Google LLC", "google", 1.0),
        ("Google, Inc.", "google", 1.0),
        ("Google UK Limited", "google", 0.70),
        ("Google Ireland Ltd", "google", 0.70),
        ("Google Deutschland GmbH", "google", 0.70),
        ("Spotify USA Inc.", "spotify", 1.0),
        ("Spotify AB", "spotify", 1.0),
        ("Amazon Web Services (AWS)", "amazon", 1.0),
        ("AWS (Amazon Web Services)", "amazon", 1.0),
        ("Stripe Payments Europe, Ltd.", "stripe", 1.0),
        ("Zalando SE", "zalando", 1.0),
        ("Siemens AG", "siemens", 1.0),
        ("Meta Platforms, Inc.", "meta", 1.0),
        ("Facebook (Meta)", "meta", 1.0),
    ]

    for query, expected_slug, min_score in fixture_matches:
        match, score, norm = match_company_fuzzy(query, candidates, threshold=0.70)
        assert match is not None, f"Expected match for '{query}', but got None"
        assert match["slug"] == expected_slug, f"For query '{query}', expected slug '{expected_slug}', got '{match['slug']}'"
        assert score >= min_score, f"For query '{query}', expected score >= {min_score}, got {score}"


def test_fuzzy_matching_hard_fixture_non_matches_and_false_positive_guards():
    """
    Test boundary cases that MUST NOT match to prevent false-positive claims.
    Low-confidence guesses must strictly return None.
    """
    candidates = [
        {"name": "Google", "slug": "google"},
        {"name": "Apple", "slug": "apple"},
        {"name": "Amazon", "slug": "amazon"},
        {"name": "Meta", "slug": "meta"},
        {"name": "Uber", "slug": "uber"},
    ]

    # Test cases: (Input Query, Reason for Non-Match)
    fixture_non_matches = [
        ("Alphabet Inc.", "Holding company without direct alias match"),
        ("Pineapple Technologies LLC", "Substring match guard for short name 'Apple'"),
        ("Appleby Law Firm", "Unrelated firm starting with 'Apple'"),
        ("Amazing Software LLC", "Trigram difference with 'Amazon'"),
        ("Metal Alloys Corp", "Unrelated word starting with 'Meta'"),
        ("Huber Financial Advisory", "Similar sound to 'Uber' but different company"),
        ("Random Unregistered Startup Inc", "Completely unrepresented employer"),
        ("ByteDance", "Not in candidate database"),
    ]

    for query, reason in fixture_non_matches:
        match, score, norm = match_company_fuzzy(query, candidates, threshold=0.70)
        assert match is None, f"False positive detected for '{query}' ({reason}). Got match: {match} with score {score}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Integration Tests: GET /api/v1/extension/lookup
# ─────────────────────────────────────────────────────────────────────────────

def test_extension_lookup_exact_and_messy_matches():
    """Verify GET /api/v1/extension/lookup returns verified company summary."""
    # 1. Clean query
    res = client.get("/api/v1/extension/lookup?company=Google")
    assert res.status_code == 200
    data = res.json()
    assert data["match"] is True
    assert data["company"]["name"] == "Google"
    assert data["company"]["slug"] == "google"
    assert data["company"]["active_job_count"] == 2
    assert data["company"]["sponsorship_confidence_score"] >= 95
    assert "EU Blue Card" in data["company"]["supported_visa_types"]
    assert "https://visalane.com/companies/google" in data["company"]["profile_url"]

    # 2. Messy LinkedIn query with legal suffix & location
    res_messy = client.get("/api/v1/extension/lookup?company=Spotify%20USA%20Inc.")
    assert res_messy.status_code == 200
    data_messy = res_messy.json()
    assert data_messy["match"] is True
    assert data_messy["company"]["name"] == "Spotify"
    assert data_messy["company"]["slug"] == "spotify"

    # 3. AWS alias query
    res_aws = client.get("/api/v1/extension/lookup?company=Amazon%20Web%20Services%20(AWS)")
    assert res_aws.status_code == 200
    data_aws = res_aws.json()
    assert data_aws["match"] is True
    assert data_aws["company"]["name"] == "Amazon"


def test_extension_lookup_explicit_no_match():
    """Verify unrepresented employers explicitly return match: false (never fake data)."""
    res = client.get("/api/v1/extension/lookup?company=Unknown%20Stealth%20Startup%20LLC")
    assert res.status_code == 200
    data = res.json()
    assert data["match"] is False
    assert data["company"] is None
    assert "No verified visa sponsorship track record" in data["message"]


def test_extension_lookup_caching():
    """Verify lookup responses are cached for 30 minutes."""
    res1 = client.get("/api/v1/extension/lookup?company=Zalando%20SE")
    assert res1.status_code == 200
    assert res1.json()["match"] is True

    # Mutate in-memory store to prove second response comes from cache
    set_mock_jobs_store([])

    res2 = client.get("/api/v1/extension/lookup?company=Zalando%20SE")
    assert res2.status_code == 200
    assert res2.json()["match"] is True
    assert res2.json()["company"]["name"] == "Zalando"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Rate Limiting Tests (Tuned for Extension Browsing Bursts)
# ─────────────────────────────────────────────────────────────────────────────

def test_extension_rate_limiting_allows_feed_scrolling_burst():
    """
    Simulate user scrolling LinkedIn or Indeed feed with 25 rapid job cards.
    All 25 lookups must succeed without 429 throttling.
    """
    try:
        limiter.reset()
    except Exception:
        pass
    clear_all_caches()

    companies = [
        "Google", "Spotify", "Amazon", "Stripe", "Zalando",
        "Google LLC", "Spotify AB", "Amazon Web Services", "Stripe Inc", "Zalando SE",
        "Company A", "Company B", "Company C", "Company D", "Company E",
        "Company F", "Company G", "Company H", "Company I", "Company J",
        "Company K", "Company L", "Company M", "Company N", "Company O",
    ]

    for c in companies:
        res = client.get(f"/api/v1/extension/lookup?company={c}")
        assert res.status_code == 200, f"Throttled unexpectedly on query '{c}': {res.text}"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Extension Analytics Event Tracking
# ─────────────────────────────────────────────────────────────────────────────

def test_extension_badge_events_logging():
    """Verify extension badge display and click events are accepted and recorded."""
    # 1. Badge shown on LinkedIn
    payload_shown = {
        "event_type": "extension_badge_shown",
        "session_id": "ext-session-12345",
        "metadata": {
            "source_platform": "linkedin",
            "company_slug": "google",
            "match_found": True,
            "confidence_score": 98,
        },
    }
    res_shown = client.post("/api/v1/events", json=payload_shown)
    assert res_shown.status_code == 200
    assert res_shown.json()["success"] is True

    # 2. Badge clicked on Indeed
    payload_clicked = {
        "event_type": "extension_badge_clicked",
        "session_id": "ext-session-12345",
        "metadata": {
            "source_platform": "indeed",
            "company_slug": "spotify",
            "destination_url": "https://visalane.com/companies/spotify",
        },
    }
    res_clicked = client.post("/api/v1/events", json=payload_clicked)
    assert res_clicked.status_code == 200
    assert res_clicked.json()["success"] is True

    # Verify events in mock store
    events = get_mock_events_store()
    event_types = [e["event_type"] for e in events]
    assert "extension_badge_shown" in event_types
    assert "extension_badge_clicked" in event_types
