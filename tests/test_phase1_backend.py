"""
Automated unit and integration test suite for VisaLane Phase 1 Backend API.
Verifies open access, query-parameter search, facets, JobPosting schema compliance,
reference endpoints, sitemap generation, caching, and event logging.
"""
import datetime
import uuid
import pytest
from fastapi.testclient import TestClient

from engine.api.main import app
from engine.api.cache import clear_all_caches
from engine.api.jobs_routes import (
    clear_mock_stores,
    get_mock_events_store,
    set_mock_jobs_store,
)


@pytest.fixture(autouse=True)
def setup_test_jobs():
    """Seed test jobs and clear caches before each test."""
    clear_all_caches()
    clear_mock_stores()

    now = datetime.datetime.now(datetime.timezone.utc)
    twelve_hours_ago = (now - datetime.timedelta(hours=12)).isoformat()
    three_days_ago = (now - datetime.timedelta(days=3)).isoformat()
    ten_days_ago = (now - datetime.timedelta(days=10)).isoformat()

    job1_id = "00000000-0000-0000-0000-000000000001"
    job2_id = "00000000-0000-0000-0000-000000000002"
    job3_id = "00000000-0000-0000-0000-000000000003"
    job4_id = "00000000-0000-0000-0000-000000000004"

    sample_jobs = [
        {
            "id": job1_id,
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
            "description_text": "We are seeking a Senior Android Engineer to build modern UI with Jetpack Compose and Kotlin Coroutines in Berlin.",
            "description_html": "<p>We are seeking a Senior Android Engineer...</p>",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 98,
            "visa_types": ["EU Blue Card", "Skilled Immigration Act"],
            "apply_url": "https://spotify.jobs/android-1",
            "source_url": "https://spotify.jobs/android-1",
            "posted_at": twelve_hours_ago,
            "created_at": twelve_hours_ago,
            "status": "active",
        },
        {
            "id": job2_id,
            "title": "Staff Backend Engineer - Distributed Systems",
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
            "description_text": "Join our core payments infrastructure team using Go and Distributed Consensus.",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 92,
            "visa_types": ["H-1B", "O-1"],
            "apply_url": "https://stripe.com/jobs/backend-2",
            "source_url": "https://stripe.com/jobs/backend-2",
            "posted_at": three_days_ago,
            "created_at": three_days_ago,
            "status": "active",
        },
        {
            "id": job3_id,
            "title": "Senior Frontend Developer",
            "companies": {"name": "Monzo", "logo_url": "https://img.logo/monzo.png", "website": "https://monzo.com", "ats_type": "workable"},
            "company_name": "Monzo",
            "location_raw": "London, UK",
            "city": "London",
            "country": "United Kingdom",
            "country_code": "GB",
            "work_mode": "onsite",
            "contract_type": "contract",
            # No salary information provided on purpose
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "description_text": "Build next-generation banking web apps with React and TypeScript.",
            "visa_sponsorship_verified": False,
            "visa_sponsorship_confidence": 75,
            "visa_types": ["Skilled Worker"],
            "apply_url": "https://monzo.com/jobs/frontend-3",
            "source_url": "https://monzo.com/jobs/frontend-3",
            "posted_at": ten_days_ago,
            "created_at": ten_days_ago,
            "status": "active",
        },
        {
            "id": job4_id,
            "title": "Expired Test Role",
            "companies": {"name": "OldCo"},
            "company_name": "OldCo",
            "country": "Germany",
            "country_code": "DE",
            "status": "expired",
            "apply_url": "https://oldco.jobs/expired",
        }
    ]
    set_mock_jobs_store(sample_jobs)
    yield
    clear_all_caches()
    clear_mock_stores()


client = TestClient(app)


def test_unauthenticated_jobs_list():
    """Verify GET /api/v1/jobs works with no auth header and returns valid structure."""
    response = client.get("/api/v1/jobs")
    assert response.status_code == 200
    data = response.json()

    assert "results" in data
    assert "total_count" in data
    assert "page" in data
    assert "page_size" in data
    assert "facets" in data

    # 3 active jobs, 1 expired excluded
    assert data["total_count"] == 3
    assert len(data["results"]) == 3

    # Check facets shape
    facets = data["facets"]
    assert "countries" in facets
    assert "visa_types" in facets
    assert any(c["slug"] == "germany" and c["count"] >= 1 for c in facets["countries"])
    assert any(c["slug"] == "united-states" and c["count"] >= 1 for c in facets["countries"])
    assert any(v["slug"] == "eu-blue-card" and v["count"] >= 1 for v in facets["visa_types"])


def test_jobs_filter_by_country_and_visa_type():
    """Verify filtering by country slug/code and visa type slug."""
    # Filter by Germany
    res_de = client.get("/api/v1/jobs?country=germany")
    assert res_de.status_code == 200
    data_de = res_de.json()
    assert data_de["total_count"] == 1
    assert data_de["results"][0]["country_code"] == "DE"
    assert data_de["results"][0]["company"]["name"] == "Spotify"

    # Filter by ISO code 'de'
    res_code = client.get("/api/v1/jobs?country=de")
    assert res_code.status_code == 200
    assert res_code.json()["total_count"] == 1

    # Filter by visa_type
    res_visa = client.get("/api/v1/jobs?visa_type=h-1b")
    assert res_visa.status_code == 200
    data_visa = res_visa.json()
    assert data_visa["total_count"] == 1
    assert data_visa["results"][0]["company"]["name"] == "Stripe"


def test_jobs_filter_by_recency_and_role():
    """Verify filtering by recency shorthand and role keyword."""
    # 24h: only Spotify job posted 1 day ago
    res_24h = client.get("/api/v1/jobs?posted_since=24h")
    assert res_24h.status_code == 200
    assert res_24h.json()["total_count"] >= 1

    # 7d: Spotify and Stripe jobs (1d and 3d), but not Monzo (10d)
    res_7d = client.get("/api/v1/jobs?posted_since=7d")
    assert res_7d.status_code == 200
    assert res_7d.json()["total_count"] == 2

    # Role keyword search in title
    res_role = client.get("/api/v1/jobs?role=android")
    assert res_role.status_code == 200
    assert res_role.json()["total_count"] == 1
    assert "Android" in res_role.json()["results"][0]["title"]

    # Role keyword search in description
    res_desc = client.get("/api/v1/jobs?role=consensus")
    assert res_desc.status_code == 200
    assert res_desc.json()["total_count"] == 1
    assert res_desc.json()["results"][0]["company"]["name"] == "Stripe"


def test_jobs_pagination_and_sorting():
    """Verify page and page_size pagination and sort ordering."""
    # Page size 1
    res_p1 = client.get("/api/v1/jobs?page=1&page_size=1")
    assert res_p1.status_code == 200
    data_p1 = res_p1.json()
    assert len(data_p1["results"]) == 1
    assert data_p1["total_count"] == 3

    res_p2 = client.get("/api/v1/jobs?page=2&page_size=1")
    assert res_p2.status_code == 200
    data_p2 = res_p2.json()
    assert len(data_p2["results"]) == 1
    assert data_p1["results"][0]["id"] != data_p2["results"][0]["id"]

    # Sort by salary
    res_sal = client.get("/api/v1/jobs?sort=salary")
    assert res_sal.status_code == 200
    data_sal = res_sal.json()
    assert data_sal["results"][0]["company"]["name"] == "Stripe"  # highest salary


def test_job_detail_schema_org_compliance():
    """Verify GET /api/v1/jobs/{slug_or_id} returns all required schema.org fields."""
    job_id = "00000000-0000-0000-0000-000000000001"
    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == job_id
    assert "slug" in data
    assert data["title"] == "Senior Android Engineer"
    assert "We are seeking a Senior Android Engineer" in data["description"]
    assert data["date_posted"] is not None
    assert data["hiring_organization"]["name"] == "Spotify"
    assert data["hiring_organization"]["logo_url"] == "https://img.logo/spotify.png"

    # Location
    assert data["job_location"]["country"] == "Germany"
    assert data["job_location"]["country_code"] == "DE"
    assert data["job_location"]["city"] == "Berlin"

    # Base salary when known
    assert data["base_salary"] is not None
    assert data["base_salary"]["currency"] == "EUR"
    assert data["base_salary"]["value"]["min"] == 85000
    assert data["base_salary"]["value"]["max"] == 110000

    # Sponsorship & confidence factors
    assert "EU Blue Card" in data["visa_types_supported"]
    assert data["confidence_score"] >= 90
    assert len(data["confidence_factors"]) >= 2
    assert any("Verified" in f["label"] or "Sponsorship" in f["label"] for f in data["confidence_factors"])


def test_job_detail_omits_salary_when_unknown():
    """Verify base_salary is strictly None / omitted when unknown (Monzo role)."""
    job_id = "00000000-0000-0000-0000-000000000003"
    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()

    # STRICT REQUIREMENT: never fabricate placeholder salary
    assert data["base_salary"] is None


def test_job_detail_by_slug_and_404():
    """Verify job detail lookup by generated slug and 404 for unknown job."""
    res_list = client.get("/api/v1/jobs")
    slug = res_list.json()["results"][0]["slug"]

    # Lookup by slug
    res_slug = client.get(f"/api/v1/jobs/{slug}")
    assert res_slug.status_code == 200
    assert res_slug.json()["slug"] == slug

    # 404 for unknown job
    res_404 = client.get("/api/v1/jobs/nonexistent-job-slug-999")
    assert res_404.status_code == 404


def test_countries_canonical_reference():
    """Verify GET /api/v1/countries returns canonical list with active counts."""
    response = client.get("/api/v1/countries")
    assert response.status_code == 200
    countries = response.json()

    assert len(countries) >= 10
    slugs = [c["slug"] for c in countries]
    assert "united-states" in slugs
    assert "germany" in slugs
    assert "united-kingdom" in slugs

    # Check live counts
    de_item = next(c for c in countries if c["slug"] == "germany")
    assert de_item["count"] == 1


def test_visa_types_canonical_reference():
    """Verify GET /api/v1/visa-types returns canonical list with active counts."""
    response = client.get("/api/v1/visa-types")
    assert response.status_code == 200
    visa_types = response.json()

    assert len(visa_types) >= 15
    slugs = [v["slug"] for v in visa_types]
    assert "eu-blue-card" in slugs
    assert "h-1b" in slugs
    assert "skilled-worker" in slugs

    blue_card = next(v for v in visa_types if v["slug"] == "eu-blue-card")
    assert blue_card["count"] == 1


def test_sitemap_data_only_non_empty():
    """Verify GET /api/v1/sitemap-data returns only non-empty pairs."""
    response = client.get("/api/v1/sitemap-data")
    assert response.status_code == 200
    data = response.json()

    assert "countries" in data
    assert "visa_types" in data
    assert "country_visa_pairs" in data
    assert "job_slugs" in data

    # Only countries and visa types with active jobs
    assert "germany" in data["countries"]
    assert "united-states" in data["countries"]
    assert "united-kingdom" in data["countries"]

    # Pairs must all have count >= 1
    for pair in data["country_visa_pairs"]:
        assert pair["count"] >= 1

    # Active job slugs count matches active jobs
    assert len(data["job_slugs"]) == 3


def test_caching_layer_hits():
    """Verify caching layer stores responses and avoids redundant computations."""
    clear_all_caches()
    # 1. First call populates cache
    res1 = client.get("/api/v1/countries")
    assert res1.status_code == 200

    # 2. Modify mock store underneath
    set_mock_jobs_store([])

    # 3. Second call returns cached data
    res2 = client.get("/api/v1/countries")
    assert res2.status_code == 200
    de_item = next(c for c in res2.json() if c["slug"] == "germany")
    assert de_item["count"] == 1

    # 4. Clearing cache reveals new store state
    clear_all_caches()
    res3 = client.get("/api/v1/countries")
    assert res3.status_code == 200
    de_item_cleared = next(c for c in res3.json() if c["slug"] == "germany")
    assert de_item_cleared["count"] == 0


def test_first_party_events_logging():
    """Verify POST /api/v1/events records events without blocking."""
    clear_mock_stores()
    payload = {
        "event_type": "page_view",
        "session_id": "sess_abc123",
        "metadata": {
            "page": "/jobs/germany",
            "referrer": "https://google.com",
        },
    }
    response = client.post("/api/v1/events", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    # Check background event store
    events = get_mock_events_store()
    assert len(events) >= 1
    assert events[0]["event_type"] == "page_view"
    assert events[0]["session_id"] == "sess_abc123"
    assert events[0]["metadata"]["page"] == "/jobs/germany"
