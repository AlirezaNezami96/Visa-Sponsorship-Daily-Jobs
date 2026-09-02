"""
Automated unit and integration test suite for VisaLane Phase 3 Backend API.
Verifies employer aggregation, directory thresholds, shareable match reports,
dynamic live re-counting, and extended event tracking.
"""
import datetime
import pytest
from fastapi.testclient import TestClient

from engine.api.main import app
from engine.api.cache import clear_all_caches
from engine.api.jobs_models import CENTRAL_LEGAL_DISCLAIMER
from engine.api.jobs_routes import (
    clear_mock_stores,
    get_mock_events_store,
    set_mock_jobs_store,
)


@pytest.fixture(autouse=True)
def setup_phase3_jobs():
    """Seed sample jobs with multiple companies and listing counts."""
    clear_all_caches()
    clear_mock_stores()

    now = datetime.datetime.now(datetime.timezone.utc)
    one_day_ago = (now - datetime.timedelta(days=1)).isoformat()
    three_days_ago = (now - datetime.timedelta(days=3)).isoformat()
    five_days_ago = (now - datetime.timedelta(days=5)).isoformat()

    sample_jobs = [
        # Spotify (3 active jobs -> passes min_jobs=3 threshold)
        {
            "id": "11111111-0000-0000-0000-000000000001",
            "title": "Senior Android Engineer",
            "companies": {"name": "Spotify", "logo_url": "https://img.logo/spotify.png", "website": "https://spotify.com", "ats_type": "lever"},
            "company_name": "Spotify",
            "location_raw": "Berlin, Germany",
            "city": "Berlin",
            "country": "Germany",
            "country_code": "DE",
            "work_mode": "hybrid",
            "contract_type": "full_time",
            "salary_min": 85000,
            "salary_max": 110000,
            "salary_currency": "EUR",
            "description_text": "Android development with Kotlin Coroutines in Berlin.",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 98,
            "visa_types": ["EU Blue Card"],
            "apply_url": "https://spotify.jobs/1",
            "posted_at": one_day_ago,
            "created_at": one_day_ago,
            "status": "active",
        },
        {
            "id": "11111111-0000-0000-0000-000000000002",
            "title": "Staff Backend Engineer - Audio Platform",
            "companies": {"name": "Spotify", "logo_url": "https://img.logo/spotify.png", "website": "https://spotify.com", "ats_type": "lever"},
            "company_name": "Spotify",
            "location_raw": "Stockholm, Sweden",
            "city": "Stockholm",
            "country": "Sweden",
            "country_code": "SE",
            "work_mode": "hybrid",
            "contract_type": "full_time",
            "salary_min": 90000,
            "salary_max": 120000,
            "salary_currency": "EUR",
            "description_text": "Distributed backend systems in Java/C++.",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 95,
            "visa_types": ["EU Blue Card"],
            "apply_url": "https://spotify.jobs/2",
            "posted_at": three_days_ago,
            "created_at": three_days_ago,
            "status": "active",
        },
        {
            "id": "11111111-0000-0000-0000-000000000003",
            "title": "Machine Learning Engineer - Personalization",
            "companies": {"name": "Spotify", "logo_url": "https://img.logo/spotify.png", "website": "https://spotify.com", "ats_type": "lever"},
            "company_name": "Spotify",
            "location_raw": "London, UK",
            "city": "London",
            "country": "United Kingdom",
            "country_code": "GB",
            "work_mode": "onsite",
            "contract_type": "full_time",
            "salary_min": 95000,
            "salary_max": 130000,
            "salary_currency": "GBP",
            "description_text": "Ranking and recommendation systems with PyTorch.",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 92,
            "visa_types": ["Skilled Worker"],
            "apply_url": "https://spotify.jobs/3",
            "posted_at": five_days_ago,
            "created_at": five_days_ago,
            "status": "active",
        },
        # Stripe (2 active jobs -> fails min_jobs=3 threshold)
        {
            "id": "22222222-0000-0000-0000-000000000001",
            "title": "Staff Payments Engineer",
            "companies": {"name": "Stripe", "logo_url": "https://img.logo/stripe.png", "website": "https://stripe.com", "ats_type": "greenhouse"},
            "company_name": "Stripe",
            "location_raw": "San Francisco, CA, USA",
            "city": "San Francisco",
            "country": "United States",
            "country_code": "US",
            "work_mode": "remote",
            "contract_type": "full_time",
            "salary_min": 190000,
            "salary_max": 240000,
            "salary_currency": "USD",
            "description_text": "Core payments infrastructure in Go.",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 94,
            "visa_types": ["H-1B", "O-1"],
            "apply_url": "https://stripe.com/1",
            "posted_at": one_day_ago,
            "created_at": one_day_ago,
            "status": "active",
        },
        {
            "id": "22222222-0000-0000-0000-000000000002",
            "title": "Infrastructure Security Lead",
            "companies": {"name": "Stripe", "logo_url": "https://img.logo/stripe.png", "website": "https://stripe.com", "ats_type": "greenhouse"},
            "company_name": "Stripe",
            "location_raw": "Dublin, Ireland",
            "city": "Dublin",
            "country": "Ireland",
            "country_code": "IE",
            "work_mode": "hybrid",
            "contract_type": "full_time",
            "salary_min": 115000,
            "salary_max": 145000,
            "salary_currency": "EUR",
            "description_text": "Cloud security architecture.",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 96,
            "visa_types": ["Critical Skills Employment Permit"],
            "apply_url": "https://stripe.com/2",
            "posted_at": three_days_ago,
            "created_at": three_days_ago,
            "status": "active",
        },
    ]
    set_mock_jobs_store(sample_jobs)
    yield
    clear_all_caches()
    clear_mock_stores()


client = TestClient(app)


def test_company_summary_with_disclaimer():
    """Verify GET /api/v1/companies/{slug}/summary returns accurate metrics & legal disclaimer."""
    response = client.get("/api/v1/companies/spotify/summary")
    assert response.status_code == 200
    data = response.json()

    assert data["company"]["name"] == "Spotify"
    assert data["company"]["slug"] == "spotify"
    assert data["total_active_jobs"] == 3
    assert data["total_historical_jobs"] == 3
    assert data["sponsorship_confidence_score"] >= 90
    assert data["verified_sponsorship_rate"] == 100.0

    # Visa types supported
    assert "EU Blue Card" in data["supported_visa_types"]
    assert "Skilled Worker" in data["supported_visa_types"]

    # Hiring countries
    country_names = [c["name"] for c in data["hiring_countries"]]
    assert "Germany" in country_names
    assert "United Kingdom" in country_names

    # Top roles
    assert len(data["top_roles"]) == 3
    assert any("Android" in r["title"] for r in data["top_roles"])

    # Recent jobs
    assert len(data["recent_jobs"]) == 3

    # CRITICAL: Legal disclaimer is present and non-empty
    assert data["disclaimer"] == CENTRAL_LEGAL_DISCLAIMER
    assert "verification@visalane.com" in data["disclaimer"]


def test_companies_directory_filtering_and_threshold():
    """Verify GET /api/v1/companies with min_jobs=3 threshold guard."""
    # Default (min_jobs=1): returns both Spotify (3 jobs) and Stripe (2 jobs)
    res_all = client.get("/api/v1/companies?min_jobs=1")
    assert res_all.status_code == 200
    data_all = res_all.json()
    assert data_all["total_count"] == 2
    assert data_all["results"][0]["name"] == "Spotify"

    # Threshold (min_jobs=3): only surfaces Spotify
    res_guard = client.get("/api/v1/companies?min_jobs=3")
    assert res_guard.status_code == 200
    data_guard = res_guard.json()
    assert data_guard["total_count"] == 1
    assert data_guard["results"][0]["name"] == "Spotify"

    # Search filter
    res_search = client.get("/api/v1/companies?search=stripe")
    assert res_search.status_code == 200
    assert res_search.json()["total_count"] == 1
    assert res_search.json()["results"][0]["name"] == "Stripe"


def test_match_report_lifecycle_and_recount():
    """Verify match report creation, persistent URL, and dynamic live re-counting."""
    # 1. Create a match report for Germany + Android
    create_payload = {
        "country": "germany",
        "role": "android",
        "title": "German Android Roles",
    }
    create_res = client.post("/api/v1/match-reports", json=create_payload)
    assert create_res.status_code == 200
    create_data = create_res.json()

    slug = create_data["slug"]
    assert slug.startswith("mr_")
    assert create_data["original_match_count"] == 1  # only Spotify Android job
    assert f"/matches/{slug}" in create_data["share_url"]

    # 2. Retrieve the report
    get_res = client.get(f"/api/v1/match-reports/{slug}")
    assert get_res.status_code == 200
    report_data = get_res.json()

    assert report_data["slug"] == slug
    assert report_data["original_match_count"] == 1
    assert report_data["current_match_count"] == 1
    assert "1 sponsorship-verified jobs" in report_data["human_summary"]
    assert "Germany" in report_data["human_summary"]
    assert len(report_data["results_sample"]) == 1
    assert report_data["results_sample"][0]["title"] == "Senior Android Engineer"

    # 3. Simulate adding a second matching job (N26 Android Developer in Berlin)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    new_job = {
        "id": "33333333-0000-0000-0000-000000000001",
        "title": "Lead Android Developer",
        "companies": {"name": "N26", "logo_url": "https://img.logo/n26.png"},
        "company_name": "N26",
        "location_raw": "Berlin, Germany",
        "city": "Berlin",
        "country": "Germany",
        "country_code": "DE",
        "work_mode": "hybrid",
        "description_text": "Build core banking android app.",
        "visa_sponsorship_verified": True,
        "visa_sponsorship_confidence": 95,
        "visa_types": ["EU Blue Card"],
        "apply_url": "https://n26.jobs/1",
        "posted_at": now,
        "created_at": now,
        "status": "active",
    }
    # Update mock store with new job
    current_store = [
        # existing jobs + new job
        *client.app.state.__dict__.get("mock_jobs", []),
    ]
    # We directly update the mock jobs store
    from engine.api.jobs_routes import _MOCK_JOBS_STORE
    _MOCK_JOBS_STORE.append(new_job)

    # 4. Fetch the same match report again -> verify current count updated, original count stayed 1
    recount_res = client.get(f"/api/v1/match-reports/{slug}")
    assert recount_res.status_code == 200
    recount_data = recount_res.json()

    assert recount_data["original_match_count"] == 1  # Fixed at creation time
    assert recount_data["current_match_count"] == 2   # Live updated count
    assert len(recount_data["results_sample"]) == 2
    assert "2 sponsorship-verified jobs" in recount_data["human_summary"]


def test_extended_event_logging_share_tracking():
    """Verify extended event logging for share_clicked and match_report_viewed."""
    clear_mock_stores()

    # Share clicked event
    share_payload = {
        "event_type": "share_clicked",
        "session_id": "sess_user_777",
        "metadata": {
            "platform": "whatsapp",
            "report_slug": "mr_test123",
            "source": "match_report_card",
        },
    }
    res1 = client.post("/api/v1/events", json=share_payload)
    assert res1.status_code == 200
    assert res1.json()["success"] is True

    # Match report viewed event
    view_payload = {
        "event_type": "match_report_viewed",
        "session_id": "sess_user_888",
        "metadata": {
            "report_slug": "mr_test123",
            "referrer": "https://whatsapp.com",
        },
    }
    res2 = client.post("/api/v1/events", json=view_payload)
    assert res2.status_code == 200
    assert res2.json()["success"] is True

    # Check background store
    events = get_mock_events_store()
    assert len(events) >= 2
    types = [e["event_type"] for e in events]
    assert "share_clicked" in types
    assert "match_report_viewed" in types


def test_match_report_rate_limiting():
    """Verify rate limiter blocks excessive match report creations (20/hour limit)."""
    payload = {"country": "germany", "role": "android"}
    # Fire requests up to rate limit
    blocked = False
    for i in range(25):
        res = client.post("/api/v1/match-reports", json=payload)
        if res.status_code == 429:
            blocked = True
            break

    assert blocked is True
