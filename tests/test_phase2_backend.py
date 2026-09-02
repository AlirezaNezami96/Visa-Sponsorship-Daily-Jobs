"""
Automated unit and integration test suite for VisaLane Phase 2 Backend API.
Verifies schema.org JobPosting compliance, JSON-LD generation, job status expiry,
country and visa summary endpoints, and XML sitemap generation.
"""
import datetime
import xml.etree.ElementTree as ET
import pytest
from fastapi.testclient import TestClient

from engine.api.main import app
from engine.api.cache import clear_all_caches
from engine.api.jobs_models import to_job_posting_json_ld
from engine.api.jobs_routes import (
    clear_mock_stores,
    set_mock_jobs_store,
)


@pytest.fixture(autouse=True)
def setup_phase2_jobs():
    """Seed comprehensive sample jobs for Phase 2 validation."""
    clear_all_caches()
    clear_mock_stores()

    now = datetime.datetime.now(datetime.timezone.utc)
    one_day_ago = (now - datetime.timedelta(days=1)).isoformat()
    three_days_ago = (now - datetime.timedelta(days=3)).isoformat()
    five_days_ago = (now - datetime.timedelta(days=5)).isoformat()
    past_date = (now - datetime.timedelta(days=20)).isoformat()

    sample_jobs = [
        # Job 1: German Hybrid Role with full salary
        {
            "id": "11111111-1111-1111-1111-111111111111",
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
            "posted_at": one_day_ago,
            "created_at": one_day_ago,
            "status": "active",
        },
        # Job 2: US Remote Role with USD salary
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "title": "Staff Backend Engineer",
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
            "description_text": "Join our core payments infrastructure team using Go and Distributed Systems.",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 92,
            "visa_types": ["H-1B", "O-1"],
            "apply_url": "https://stripe.com/jobs/backend-2",
            "posted_at": three_days_ago,
            "created_at": three_days_ago,
            "status": "active",
        },
        # Job 3: UK Onsite Role without salary
        {
            "id": "33333333-3333-3333-3333-333333333333",
            "title": "Senior Frontend Developer",
            "companies": {"name": "Monzo", "logo_url": "https://img.logo/monzo.png", "website": "https://monzo.com", "ats_type": "workable"},
            "company_name": "Monzo",
            "location_raw": "London, UK",
            "city": "London",
            "country": "United Kingdom",
            "country_code": "GB",
            "work_mode": "onsite",
            "contract_type": "contract",
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "description_text": "Build next-generation banking web apps with React and TypeScript.",
            "visa_sponsorship_verified": False,
            "visa_sponsorship_confidence": 75,
            "visa_types": ["Skilled Worker"],
            "apply_url": "https://monzo.com/jobs/frontend-3",
            "posted_at": five_days_ago,
            "created_at": five_days_ago,
            "status": "active",
        },
        # Job 4: Ireland Role with Critical Skills
        {
            "id": "44444444-4444-4444-4444-444444444444",
            "title": "Cloud Security Architect",
            "companies": {"name": "Workday", "logo_url": "https://img.logo/workday.png", "website": "https://workday.com"},
            "company_name": "Workday",
            "location_raw": "Dublin, Ireland",
            "city": "Dublin",
            "country": "Ireland",
            "country_code": "IE",
            "work_mode": "hybrid",
            "contract_type": "full_time",
            "salary_min": 105000,
            "salary_max": 130000,
            "salary_currency": "EUR",
            "description_text": "Design enterprise zero-trust cloud architectures in Dublin.",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 95,
            "visa_types": ["Critical Skills Employment Permit"],
            "apply_url": "https://workday.jobs/sec-4",
            "posted_at": five_days_ago,
            "created_at": five_days_ago,
            "status": "active",
        },
        # Job 5: Netherlands Role with HSM
        {
            "id": "55555555-5555-5555-5555-555555555555",
            "title": "Lead Machine Learning Engineer",
            "companies": {"name": "Booking.com", "logo_url": "https://img.logo/booking.png", "website": "https://booking.com"},
            "company_name": "Booking.com",
            "location_raw": "Amsterdam, Netherlands",
            "city": "Amsterdam",
            "country": "Netherlands",
            "country_code": "NL",
            "work_mode": "hybrid",
            "contract_type": "full_time",
            "salary_min": 95000,
            "salary_max": 125000,
            "salary_currency": "EUR",
            "description_text": "Deploy large scale recommendation ranking models in Amsterdam.",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 96,
            "visa_types": ["Highly Skilled Migrant"],
            "apply_url": "https://booking.jobs/ml-5",
            "posted_at": one_day_ago,
            "created_at": one_day_ago,
            "status": "active",
        },
        # Job 6: Expired / Closed Job
        {
            "id": "66666666-6666-6666-6666-666666666666",
            "title": "Expired Test Role",
            "companies": {"name": "OldCo"},
            "company_name": "OldCo",
            "country": "Germany",
            "country_code": "DE",
            "status": "expired",
            "apply_url": "https://oldco.jobs/expired",
            "posted_at": past_date,
            "created_at": past_date,
        },
    ]
    set_mock_jobs_store(sample_jobs)
    yield
    clear_all_caches()
    clear_mock_stores()


client = TestClient(app)


def test_schema_required_fields_on_job_detail():
    """Verify all 5 required Google JobPosting schema fields are resolved."""
    job_id = "11111111-1111-1111-1111-111111111111"
    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()

    # 1. title
    assert data["title"] == "Senior Android Engineer"
    # 2. description (full text, not teaser)
    assert len(data["description"]) > 20
    # 3. datePosted
    assert data["date_posted"] is not None
    # 4. hiringOrganization
    assert data["hiring_organization"]["name"] == "Spotify"
    # 5. jobLocation
    assert data["job_location"] is not None
    assert data["job_location"]["country"] == "Germany"

    # Status
    assert data["job_status"] == "Open"


def test_remote_job_schema_location():
    """Verify remote job uses TELECOMMUTE and applicantLocationRequirements."""
    job_id = "22222222-2222-2222-2222-222222222222"
    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["remote"] is True
    assert data["applicant_location_requirements"] == "United States"

    # Convert to JSON-LD and check Google Schema requirements
    from engine.api.jobs_models import JobDetail
    detail = JobDetail(**data)
    json_ld = to_job_posting_json_ld(detail)

    assert json_ld["@type"] == "JobPosting"
    assert json_ld["jobLocationType"] == "TELECOMMUTE"
    assert json_ld["applicantLocationRequirements"]["name"] == "United States"
    assert json_ld["hiringOrganization"]["name"] == "Stripe"
    assert json_ld["baseSalary"]["currency"] == "USD"
    assert json_ld["baseSalary"]["value"]["minValue"] == 190000


def test_recommended_fields_omitted_when_unknown():
    """Verify baseSalary is strictly omitted/null when unknown (never fabricated)."""
    job_id = "33333333-3333-3333-3333-333333333333"
    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["base_salary"] is None

    from engine.api.jobs_models import JobDetail
    detail = JobDetail(**data)
    json_ld = to_job_posting_json_ld(detail)

    # Must NOT have baseSalary in JSON-LD
    assert "baseSalary" not in json_ld


def test_closed_job_status_and_sitemap_exclusion():
    """Verify expired/closed jobs are marked 'Closed' and omitted from sitemap.xml."""
    job_id = "66666666-6666-6666-6666-666666666666"
    res_detail = client.get(f"/api/v1/jobs/{job_id}")
    assert res_detail.status_code == 200
    assert res_detail.json()["job_status"] == "Closed"

    # Sitemap XML check
    res_sitemap = client.get("/api/v1/sitemap.xml")
    assert res_sitemap.status_code == 200
    xml_text = res_sitemap.text

    # Closed job slug should NOT appear in sitemap
    assert "expired-test-role" not in xml_text
    assert "66666666" not in xml_text

    # Active jobs SHOULD appear in sitemap
    assert "spotify" in xml_text or "senior-android-engineer" in xml_text


def test_country_summary_endpoint():
    """Verify GET /api/v1/countries/{country}/summary returns rich SEO copy data."""
    response = client.get("/api/v1/countries/germany/summary")
    assert response.status_code == 200
    data = response.json()

    assert data["country"]["slug"] == "germany"
    assert data["country"]["code"] == "DE"
    assert data["job_count"] == 1
    assert len(data["top_roles"]) >= 1
    assert data["top_roles"][0]["title"] == "Senior Android Engineer"
    assert len(data["sample_employers"]) >= 1
    assert data["sample_employers"][0]["name"] == "Spotify"
    assert any(v["name"] == "EU Blue Card" for v in data["visa_types_available"])
    assert "Spotify" in data["meta_description_suggestion"]
    assert "Germany" in data["meta_description_suggestion"]

    # Also test with ISO code
    res_code = client.get("/api/v1/countries/de/summary")
    assert res_code.status_code == 200
    assert res_code.json()["country"]["slug"] == "germany"


def test_country_visa_summary_endpoint():
    """Verify GET /api/v1/countries/{country}/visa-types/{visa_type}/summary."""
    response = client.get("/api/v1/countries/germany/visa-types/eu-blue-card/summary")
    assert response.status_code == 200
    data = response.json()

    assert data["country"]["slug"] == "germany"
    assert data["visa_type"]["slug"] == "eu-blue-card"
    assert data["job_count"] == 1
    assert "EU Blue Card" in data["meta_description_suggestion"]
    assert "Germany" in data["meta_description_suggestion"]


def test_sitemap_xml_validity_and_tags():
    """Verify sitemap.xml produces valid XML with lastmod and zero empty pages."""
    response = client.get("/api/v1/sitemap.xml")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]

    # Parse XML to verify well-formed syntax
    root = ET.fromstring(response.text)
    assert root.tag.endswith("urlset")

    urls = root.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url")
    assert len(urls) >= 5  # Homepage + country pages + pair pages + job pages

    locs = [u.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc").text for u in urls]
    
    # Homepage
    assert any(loc.endswith(".com/") or loc.endswith("visalane.com/") for loc in locs)
    # Country page
    assert any("/jobs/germany" in loc for loc in locs)
    # Country-visa page
    assert any("/jobs/germany/eu-blue-card" in loc for loc in locs)
    # Zero-job countries (e.g. Australia/Singapore which have 0 in this mock) must NOT appear
    assert not any("/jobs/australia" in loc for loc in locs)
    assert not any("/jobs/singapore" in loc for loc in locs)


def test_json_ld_generation_5_sample_jobs():
    """Generate and validate JSON-LD structured blocks for 5 sample jobs."""
    job_ids = [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
        "44444444-4444-4444-4444-444444444444",
        "55555555-5555-5555-5555-555555555555",
    ]

    from engine.api.jobs_models import JobDetail

    generated_blocks = []
    for jid in job_ids:
        res = client.get(f"/api/v1/jobs/{jid}")
        assert res.status_code == 200
        detail = JobDetail(**res.json())
        json_ld = to_job_posting_json_ld(detail)
        
        # Verify 5 mandatory Google JobPosting fields
        assert json_ld["@context"] == "https://schema.org"
        assert json_ld["@type"] == "JobPosting"
        assert json_ld["title"]
        assert json_ld["description"]
        assert json_ld["datePosted"]
        assert json_ld["hiringOrganization"]["name"]
        assert "jobLocation" in json_ld or "jobLocationType" in json_ld

        generated_blocks.append(json_ld)

    assert len(generated_blocks) == 5
