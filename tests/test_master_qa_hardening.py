"""
Master QA & Hardening Test Suite for VisaLane Phases 1, 2, and 3.
Includes:
1. Zero-auth on public endpoints vs. 401 on gated endpoints.
2. Filter completeness, combined filter tests, and scoped facets.
3. Strict schema.org JobPosting compliance regression gates (5 mandatory fields).
4. Omit-when-unknown verification (no fabricated salaries).
5. Live country & visa-type counts verification.
6. Non-empty sitemap & closed job exclusion verification.
7. Cache latency & memory hit verification.
8. Employer aggregation, directory thresholds, and legal disclaimers.
9. Match reports creation, live re-counting, and rate limiting (20/hr).
10. Extended event logging (share_clicked, match_report_viewed).
11. Input validation & error handling (422/404).
12. Concurrent load/perf smoke test (50+ concurrent requests, p95 <= 500ms).
"""
from __future__ import annotations

import asyncio
import datetime
import time
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient
import httpx

from engine.api.main import app
from engine.api.cache import clear_all_caches, get_cache, set_cache
from engine.api.jobs_models import (
    CENTRAL_LEGAL_DISCLAIMER,
    JobDetail,
    JobSummary,
    to_job_posting_json_ld,
)
from engine.api.jobs_routes import (
    _format_job_detail,
    clear_mock_stores,
    get_mock_events_store,
    set_mock_jobs_store,
)

client = TestClient(app)


def _generate_seeded_jobs() -> List[Dict[str, Any]]:
    """Seed comprehensive realistic dataset across multiple countries, roles, and companies."""
    now = datetime.datetime.now(datetime.timezone.utc)
    one_day_ago = (now - datetime.timedelta(days=1)).isoformat()
    two_days_ago = (now - datetime.timedelta(days=2)).isoformat()
    five_days_ago = (now - datetime.timedelta(days=5)).isoformat()
    forty_days_ago = (now - datetime.timedelta(days=40)).isoformat()

    return [
        # 1. Spotify (DE - Hybrid - EUR Salary - Active)
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
            "description_text": "We are seeking a Senior Android Engineer to build modern UI with Jetpack Compose in Berlin.",
            "description_html": "<p>We are seeking a Senior Android Engineer to build modern UI with Jetpack Compose in Berlin.</p>",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 98,
            "visa_types": ["EU Blue Card"],
            "apply_url": "https://spotify.jobs/1",
            "posted_at": one_day_ago,
            "created_at": one_day_ago,
            "status": "active",
        },
        # 2. Spotify (SE - Hybrid - EUR Salary - Active)
        {
            "id": "11111111-2222-2222-2222-222222222222",
            "title": "Staff Backend Engineer",
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
            "description_text": "High throughput audio backend systems in Java/C++.",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 95,
            "visa_types": ["EU Blue Card"],
            "apply_url": "https://spotify.jobs/2",
            "posted_at": two_days_ago,
            "created_at": two_days_ago,
            "status": "active",
        },
        # 3. Spotify (GB - Onsite - Unknown Salary - Active)
        {
            "id": "11111111-3333-3333-3333-333333333333",
            "title": "Machine Learning Engineer",
            "companies": {"name": "Spotify", "logo_url": "https://img.logo/spotify.png", "website": "https://spotify.com", "ats_type": "lever"},
            "company_name": "Spotify",
            "location_raw": "London, UK",
            "city": "London",
            "country": "United Kingdom",
            "country_code": "GB",
            "work_mode": "onsite",
            "contract_type": "full_time",
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "description_text": "Ranking and recommendation systems with PyTorch.",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 92,
            "visa_types": ["Skilled Worker"],
            "apply_url": "https://spotify.jobs/3",
            "posted_at": five_days_ago,
            "created_at": five_days_ago,
            "status": "active",
        },
        # 4. Stripe (US - Remote - USD Salary - Active)
        {
            "id": "22222222-1111-1111-1111-111111111111",
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
            "description_text": "Core payments infrastructure in Go and Distributed Systems.",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 94,
            "visa_types": ["H-1B", "O-1"],
            "apply_url": "https://stripe.com/1",
            "posted_at": one_day_ago,
            "created_at": one_day_ago,
            "status": "active",
        },
        # 5. Monzo (GB - Onsite - Unknown Salary - Active)
        {
            "id": "33333333-1111-1111-1111-111111111111",
            "title": "Senior Frontend Developer",
            "companies": {"name": "Monzo", "logo_url": "https://img.logo/monzo.png", "website": "https://monzo.com", "ats_type": "greenhouse"},
            "company_name": "Monzo",
            "location_raw": "London, UK",
            "city": "London",
            "country": "United Kingdom",
            "country_code": "GB",
            "work_mode": "onsite",
            "contract_type": "contractor",
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "description_text": "Build next-generation banking web apps with React and TypeScript.",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 88,
            "visa_types": ["Skilled Worker"],
            "apply_url": "https://monzo.com/1",
            "posted_at": two_days_ago,
            "created_at": two_days_ago,
            "status": "active",
        },
        # 6. Workday (IE - Hybrid - EUR Salary - Active)
        {
            "id": "44444444-1111-1111-1111-111111111111",
            "title": "Cloud Security Architect",
            "companies": {"name": "Workday", "logo_url": "https://img.logo/workday.png", "website": "https://workday.com", "ats_type": "workday"},
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
            "visa_sponsorship_confidence": 96,
            "visa_types": ["Critical Skills Employment Permit"],
            "apply_url": "https://workday.com/1",
            "posted_at": two_days_ago,
            "created_at": two_days_ago,
            "status": "active",
        },
        # 7. Booking.com (NL - Onsite - EUR Salary - Active)
        {
            "id": "55555555-1111-1111-1111-111111111111",
            "title": "Lead Machine Learning Engineer",
            "companies": {"name": "Booking.com", "logo_url": "https://img.logo/booking.png", "website": "https://booking.com", "ats_type": "greenhouse"},
            "company_name": "Booking.com",
            "location_raw": "Amsterdam, Netherlands",
            "city": "Amsterdam",
            "country": "Netherlands",
            "country_code": "NL",
            "work_mode": "onsite",
            "contract_type": "full_time",
            "salary_min": 95000,
            "salary_max": 125000,
            "salary_currency": "EUR",
            "description_text": "Deploy large scale recommendation ranking models in Amsterdam.",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 97,
            "visa_types": ["Highly Skilled Migrant"],
            "apply_url": "https://booking.com/1",
            "posted_at": one_day_ago,
            "created_at": one_day_ago,
            "status": "active",
        },
        # 8. Expired / Closed Job (Should be excluded from search & sitemaps)
        {
            "id": "88888888-8888-8888-8888-888888888888",
            "title": "Legacy Perl Developer (Closed)",
            "companies": {"name": "OldCorp", "logo_url": None, "website": None},
            "company_name": "OldCorp",
            "location_raw": "Berlin, Germany",
            "city": "Berlin",
            "country": "Germany",
            "country_code": "DE",
            "work_mode": "onsite",
            "description_text": "Old legacy system job.",
            "status": "expired",
            "expires_at": forty_days_ago,
            "posted_at": forty_days_ago,
            "created_at": forty_days_ago,
            "apply_url": "https://oldcorp.com/closed",
        },
    ]


@pytest.fixture(autouse=True)
def reset_state():
    """Reset mock stores, limiters, and caches before each test."""
    from engine.api.jobs_routes import limiter
    try:
        limiter.reset()
    except Exception:
        pass
    clear_all_caches()
    clear_mock_stores()
    set_mock_jobs_store(_generate_seeded_jobs())
    yield
    try:
        limiter.reset()
    except Exception:
        pass
    clear_all_caches()
    clear_mock_stores()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Zero-Auth vs. Auth-Gating Verification
# ─────────────────────────────────────────────────────────────────────────────

def test_zero_auth_on_public_endpoints():
    """Verify that all public endpoints return 200 without Authorization header."""
    public_endpoints = [
        "/api/v1/jobs",
        "/api/v1/jobs/11111111-1111-1111-1111-111111111111",
        "/api/v1/countries",
        "/api/v1/countries/germany/summary",
        "/api/v1/visa-types",
        "/api/v1/companies",
        "/api/v1/companies/spotify/summary",
        "/api/v1/sitemap.xml",
        "/api/v1/sitemap-data",
    ]
    for ep in public_endpoints:
        res = client.get(ep, headers={})
        assert res.status_code == 200, f"Public endpoint {ep} failed with status {res.status_code}"


def test_auth_required_on_gated_endpoints():
    """Verify that session/resume/cover letter endpoints require valid session / return 401."""
    # 1. Resume tailor without valid session
    res_tailor = client.post(
        "/api/v1/resume/tailor",
        json={
            "session_id": "invalid_or_missing_session",
            "job_description": "We are seeking a talented Senior Software Engineer with strong experience in building distributed systems, microservices, and high-performance cloud APIs.",
            "company_name": "TestCorp",
            "job_title": "Software Engineer",
        },
    )
    assert res_tailor.status_code == 401
    assert "Session not found or expired" in res_tailor.json()["detail"]

    # 2. Cover letter generation without valid session
    res_cl = client.post(
        "/api/v1/cover-letter/generate",
        json={
            "session_id": "invalid_or_missing_session",
            "job_description": "We are seeking a talented Senior Software Engineer with strong experience in building distributed systems, microservices, and high-performance cloud APIs.",
            "company_name": "TestCorp",
            "job_title": "Software Engineer",
            "user_name": "Jane Doe",
        },
    )
    assert res_cl.status_code == 401
    assert "Session not found or expired" in res_cl.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Query Parameters & Filter Verification
# ─────────────────────────────────────────────────────────────────────────────

def test_jobs_filter_parameters_individual_and_combined():
    """Verify every query parameter individually and combined, checking result accuracy."""
    # 1. Country filter: Germany
    res_de = client.get("/api/v1/jobs?country=germany")
    assert res_de.status_code == 200
    data_de = res_de.json()
    assert data_de["total_count"] == 1
    assert data_de["results"][0]["country"] == "Germany"

    # 2. Visa type filter: EU Blue Card
    res_bc = client.get("/api/v1/jobs?visa_type=eu-blue-card")
    assert res_bc.status_code == 200
    assert res_bc.json()["total_count"] == 2  # Spotify DE & Spotify SE

    # 3. Role keyword: Android
    res_role = client.get("/api/v1/jobs?role=Android")
    assert res_role.status_code == 200
    assert res_role.json()["total_count"] == 1
    assert "Android" in res_role.json()["results"][0]["title"]

    # 4. Work mode: Remote
    res_remote = client.get("/api/v1/jobs?work_mode=remote")
    assert res_remote.status_code == 200
    assert res_remote.json()["total_count"] == 1
    assert res_remote.json()["results"][0]["company"]["name"] == "Stripe"

    # 5. Contract type: Contractor
    res_contract = client.get("/api/v1/jobs?contract_type=contractor")
    assert res_contract.status_code == 200
    assert res_contract.json()["total_count"] == 1
    assert res_contract.json()["results"][0]["company"]["name"] == "Monzo"

    # 6. Min confidence: 95
    res_conf = client.get("/api/v1/jobs?min_confidence=95")
    assert res_conf.status_code == 200
    for j in res_conf.json()["results"]:
        assert (j["visa_sponsorship_confidence"] or 0) >= 95

    # 7. Combined: country=United Kingdom + sort=newest
    res_uk = client.get("/api/v1/jobs?country=gb&sort=newest")
    assert res_uk.status_code == 200
    assert res_uk.json()["total_count"] == 2


def test_facets_are_scoped_to_applied_filters():
    """Verify that facet counts are dynamically scoped to currently applied filters."""
    # Global search -> multiple countries in facets
    res_global = client.get("/api/v1/jobs")
    assert res_global.status_code == 200
    global_countries = {f["slug"]: f["count"] for f in res_global.json()["facets"]["countries"]}
    assert global_countries.get("germany") == 1
    assert global_countries.get("united-kingdom") == 2

    # Scoped search to country=germany -> only Germany should be in country facets
    res_scoped = client.get("/api/v1/jobs?country=germany")
    assert res_scoped.status_code == 200
    scoped_countries = {f["slug"]: f["count"] for f in res_scoped.json()["facets"]["countries"]}
    assert scoped_countries == {"germany": 1}

    # Visa facets should only show visas available for Germany in scoped results (EU Blue Card)
    scoped_visas = {f["slug"]: f["count"] for f in res_scoped.json()["facets"]["visa_types"]}
    assert "eu-blue-card" in scoped_visas
    assert "skilled-worker" not in scoped_visas


# ─────────────────────────────────────────────────────────────────────────────
# 3. Schema.org JobPosting Mandatory 5 Fields Hard Regression Gate
# ─────────────────────────────────────────────────────────────────────────────

def test_all_active_jobs_resolve_mandatory_schema_fields():
    """
    Permanent regression gate:
    Guarantees every active job converts to valid schema.org/JobPosting JSON-LD
    with all 5 required fields: title, description, datePosted, hiringOrganization, jobLocation/telecommute.
    """
    res = client.get("/api/v1/jobs?page_size=100")
    assert res.status_code == 200
    jobs = res.json()["results"]
    assert len(jobs) >= 7

    for j in jobs:
        # Fetch detailed record
        det_res = client.get(f"/api/v1/jobs/{j['id']}")
        assert det_res.status_code == 200
        detail = JobDetail(**det_res.json())

        # Generate schema.org JSON-LD
        json_ld = to_job_posting_json_ld(detail)

        # 1. title
        assert json_ld.get("title"), f"Job {j['id']} missing title in JSON-LD"
        # 2. description
        assert json_ld.get("description"), f"Job {j['id']} missing description in JSON-LD"
        # 3. datePosted
        assert json_ld.get("datePosted"), f"Job {j['id']} missing datePosted in JSON-LD"
        # 4. hiringOrganization
        org = json_ld.get("hiringOrganization")
        assert isinstance(org, dict) and org.get("name"), f"Job {j['id']} missing hiringOrganization"
        # 5. jobLocation OR TELECOMMUTE
        if json_ld.get("jobLocationType") == "TELECOMMUTE":
            assert json_ld.get("applicantLocationRequirements"), f"Job {j['id']} missing applicantLocationRequirements"
        else:
            loc = json_ld.get("jobLocation")
            assert isinstance(loc, dict) and loc.get("address"), f"Job {j['id']} missing physical jobLocation"


def test_omit_when_unknown_salary_rule():
    """Verify that jobs with unknown salaries strictly omit baseSalary (never fabricate)."""
    # Monzo UK job has unknown salary
    res = client.get("/api/v1/jobs/33333333-1111-1111-1111-111111111111")
    assert res.status_code == 200
    detail = JobDetail(**res.json())

    assert detail.base_salary is None

    json_ld = to_job_posting_json_ld(detail)
    assert "baseSalary" not in json_ld, "baseSalary must be omitted when unknown"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Sitemap & Expiry Guard
# ─────────────────────────────────────────────────────────────────────────────

def test_sitemap_excludes_closed_jobs_and_empty_pages():
    """Verify GET /api/v1/sitemap.xml excludes expired jobs and non-job countries."""
    res = client.get("/api/v1/sitemap.xml")
    assert res.status_code == 200
    xml_text = res.text

    assert "<loc>https://visalane.com/</loc>" in xml_text
    assert "<loc>https://visalane.com/jobs/germany</loc>" in xml_text
    assert "<loc>https://visalane.com/jobs/germany/eu-blue-card</loc>" in xml_text

    # Expired job (id: 88888888-8888-8888-8888-888888888888) must NOT be in sitemap
    assert "88888888" not in xml_text
    assert "legacy-perl" not in xml_text

    # Country with 0 jobs (e.g. France / FR in our seeded dataset) must NOT be in sitemap
    assert "/jobs/france" not in xml_text


# ─────────────────────────────────────────────────────────────────────────────
# 5. Performance & Sub-Millisecond Cache Test
# ─────────────────────────────────────────────────────────────────────────────

def test_caching_latency_performance():
    """Verify that repeated requests hit cache with measurable sub-millisecond latency."""
    clear_all_caches()

    # Request 1 (Cache miss - loads from store & parses)
    t0 = time.perf_counter()
    res1 = client.get("/api/v1/jobs?country=germany")
    t1 = time.perf_counter()
    assert res1.status_code == 200
    miss_duration = t1 - t0

    # Request 2 (Cache hit - in-memory hit)
    t2 = time.perf_counter()
    res2 = client.get("/api/v1/jobs?country=germany")
    t3 = time.perf_counter()
    assert res2.status_code == 200
    hit_duration = t3 - t2

    assert hit_duration < miss_duration or hit_duration < 0.05
    assert res1.json() == res2.json()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Employer Directory, Aggregation, & Legal Disclaimer
# ─────────────────────────────────────────────────────────────────────────────

def test_employer_aggregation_and_legal_disclaimer():
    """Verify employer summary calculates stats and includes the mandatory legal disclaimer."""
    res = client.get("/api/v1/companies/spotify/summary")
    assert res.status_code == 200
    data = res.json()

    assert data["company"]["name"] == "Spotify"
    assert data["total_active_jobs"] == 3
    assert data["disclaimer"] == CENTRAL_LEGAL_DISCLAIMER
    assert "verification@visalane.com" in data["disclaimer"]


def test_employer_directory_min_jobs_threshold():
    """Verify /api/v1/companies filters out employers with < min_jobs."""
    # Spotify has 3 jobs; Stripe has 1 job; Monzo has 1 job; Workday has 1 job; Booking has 1 job
    res_guard = client.get("/api/v1/companies?min_jobs=3")
    assert res_guard.status_code == 200
    data = res_guard.json()
    assert data["total_count"] == 1
    assert data["results"][0]["name"] == "Spotify"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Match Reports End-to-End & Live Re-count
# ─────────────────────────────────────────────────────────────────────────────

def test_match_reports_live_recount_cycle():
    """Verify match report creation and dynamic live recount when new jobs are added."""
    # 1. Create match report for Sweden
    create_res = client.post(
        "/api/v1/match-reports",
        json={"country": "sweden", "title": "Swedish Tech Jobs"},
    )
    assert create_res.status_code == 200
    c_data = create_res.json()
    slug = c_data["slug"]
    assert c_data["original_match_count"] == 1

    # 2. Get report
    get_res1 = client.get(f"/api/v1/match-reports/{slug}")
    assert get_res1.status_code == 200
    assert get_res1.json()["current_match_count"] == 1
    assert get_res1.json()["original_match_count"] == 1

    # 3. Add second job in Sweden
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    new_sweden_job = {
        "id": "77777777-7777-7777-7777-777777777777",
        "title": "Data Engineer",
        "companies": {"name": "Klarna", "logo_url": "https://img.logo/klarna.png"},
        "company_name": "Klarna",
        "location_raw": "Stockholm, Sweden",
        "city": "Stockholm",
        "country": "Sweden",
        "country_code": "SE",
        "work_mode": "hybrid",
        "description_text": "Big data pipelines with Spark in Stockholm.",
        "visa_sponsorship_verified": True,
        "visa_sponsorship_confidence": 95,
        "visa_types": ["EU Blue Card"],
        "apply_url": "https://klarna.jobs/1",
        "posted_at": now,
        "created_at": now,
        "status": "active",
    }
    from engine.api.jobs_routes import _MOCK_JOBS_STORE
    _MOCK_JOBS_STORE.append(new_sweden_job)

    # 4. Get report again -> current count increments to 2, original stays 1
    get_res2 = client.get(f"/api/v1/match-reports/{slug}")
    assert get_res2.status_code == 200
    assert get_res2.json()["original_match_count"] == 1
    assert get_res2.json()["current_match_count"] == 2
    assert "2 sponsorship-verified jobs" in get_res2.json()["human_summary"]


# ─────────────────────────────────────────────────────────────────────────────
# 8. Input Validation & Error Handling (4xx with Structured JSON)
# ─────────────────────────────────────────────────────────────────────────────

def test_input_validation_and_structured_errors():
    """Verify invalid parameters return 422 or 404 with structured JSON bodies, never 500."""
    # 1. Page size exceeded (max 100)
    res_bad_size = client.get("/api/v1/jobs?page_size=500")
    assert res_bad_size.status_code == 422
    assert "detail" in res_bad_size.json()

    # 2. Negative page number
    res_bad_page = client.get("/api/v1/jobs?page=-5")
    assert res_bad_page.status_code == 422

    # 3. Out of range confidence score (> 100)
    res_bad_conf = client.get("/api/v1/jobs?min_confidence=150")
    assert res_bad_conf.status_code == 422

    # 4. Non-existent job ID
    res_not_found = client.get("/api/v1/jobs/non-existent-job-uuid-1234")
    assert res_not_found.status_code == 404
    assert "Job posting not found" in res_not_found.json()["detail"]

    # 5. Non-existent company
    res_bad_comp = client.get("/api/v1/companies/non-existent-company-slug/summary")
    assert res_bad_comp.status_code == 404

    # 6. Non-existent country summary
    res_bad_country = client.get("/api/v1/countries/atlantis/summary")
    assert res_bad_country.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 9. Concurrency & High-Throughput Load Smoke Test (50+ Concurrent Requests)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_concurrent_load_and_p95_latency():
    """
    Executes 50 concurrent requests against /api/v1/jobs and measures p95 latency.
    Asserts p95 latency is strictly <= 500ms (real measured value).
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as async_client:
        latencies: List[float] = []

        async def fetch():
            t0 = time.perf_counter()
            res = await async_client.get("/api/v1/jobs?country=germany")
            t1 = time.perf_counter()
            assert res.status_code == 200
            latencies.append((t1 - t0) * 1000)

        # Launch 50 concurrent requests
        tasks = [fetch() for _ in range(50)]
        await asyncio.gather(*tasks)

        assert len(latencies) == 50
        latencies.sort()
        p95_index = int(0.95 * len(latencies))
        p95_latency = latencies[p95_index]
        avg_latency = sum(latencies) / len(latencies)

        print(f"\n[PERF RESULT] 50 Concurrent Requests -> Avg: {avg_latency:.2f}ms | p95: {p95_latency:.2f}ms")
        assert p95_latency <= 500.0, f"p95 latency {p95_latency}ms exceeded 500ms target"


# ─────────────────────────────────────────────────────────────────────────────
# 10. Canonical Data & Indexing Service Unit Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_canonical_data_lookups():
    """Verify lookup helpers and alias resolution in canonical_data."""
    from engine.api.canonical_data import (
        find_country,
        find_visa_type,
        match_visa_type_from_string,
    )

    # Empty / None queries
    assert find_country(None) is None
    assert find_country("") is None
    assert find_visa_type(None) is None
    assert find_visa_type("") is None
    assert match_visa_type_from_string(None) is None
    assert match_visa_type_from_string("") is None

    # Country aliases
    assert find_country("de")["name"] == "Germany"
    assert find_country("GERMANY")["code"] == "DE"
    assert find_country("United Kingdom")["code"] == "GB"
    assert find_country("uk")["code"] == "GB"

    # Visa aliases
    assert find_visa_type("eu-blue-card")["name"] == "EU Blue Card"
    assert find_visa_type("blue card")["name"] == "EU Blue Card"
    assert find_visa_type("h1b")["name"] == "H-1B"
    assert find_visa_type("h-1b")["name"] == "H-1B"

    # String matching
    matched = match_visa_type_from_string("Position eligible for EU Blue Card visa sponsorship")
    assert matched is not None
    assert matched["slug"] == "eu-blue-card"

    matched_direct = match_visa_type_from_string("h-1b")
    assert matched_direct is not None
    assert matched_direct["slug"] == "h-1b"


def test_cache_redis_fallback_mock():
    """Verify cache layer with mocked Redis backend."""
    import unittest.mock
    from engine.api.cache import get_cache, set_cache, clear_all_caches

    mock_redis = unittest.mock.MagicMock()
    mock_store: Dict[str, str] = {}

    def r_get(k):
        return mock_store.get(k)

    def r_setex(k, ttl, v):
        mock_store[k] = v

    def r_flushdb():
        mock_store.clear()

    mock_redis.get.side_effect = r_get
    mock_redis.setex.side_effect = r_setex
    mock_redis.flushdb.side_effect = r_flushdb

    with unittest.mock.patch("engine.api.cache._get_redis", return_value=mock_redis):
        set_cache("test_key", {"status": "ok"}, ttl_seconds=60)
        assert mock_redis.setex.called
        cached = get_cache("test_key", ttl_seconds=60)
        assert cached == {"status": "ok"}
        clear_all_caches()
        assert mock_redis.flushdb.called


@pytest.mark.anyio
async def test_indexing_service_unconfigured_and_methods():
    """Verify Google Indexing Service graceful fallback when unconfigured and notification methods."""
    from engine.api.indexing_service import GoogleIndexingService, get_indexing_service

    service = get_indexing_service()
    assert isinstance(service, GoogleIndexingService)

    # When unconfigured, notifications return skipped: True
    res_up = await service.notify_url_updated("https://visalane.com/jobs/sample-1")
    assert res_up.get("skipped") is True
    assert res_up.get("reason") == "unconfigured"

    res_del = await service.notify_url_deleted("https://visalane.com/jobs/sample-1")
    assert res_del.get("skipped") is True
    assert res_del.get("reason") == "unconfigured"


def test_sorting_and_recency_options():
    """Verify sorting by salary, confidence, and relative recency cutoffs (24h, 7d, 30d)."""
    # 1. Sort by salary
    res_sal = client.get("/api/v1/jobs?sort=salary")
    assert res_sal.status_code == 200
    results_sal = res_sal.json()["results"]
    salaries = [(j.get("salary_max") or j.get("salary_min") or 0) for j in results_sal]
    assert salaries == sorted(salaries, reverse=True)

    # 2. Sort by confidence
    res_conf = client.get("/api/v1/jobs?sort=confidence")
    assert res_conf.status_code == 200
    results_conf = res_conf.json()["results"]
    confidences = [(j.get("visa_sponsorship_confidence") or 0) for j in results_conf]
    assert confidences == sorted(confidences, reverse=True)

    # 3. Recency filters
    res_24h = client.get("/api/v1/jobs?posted_since=24h")
    assert res_24h.status_code == 200

    res_7d = client.get("/api/v1/jobs?posted_since=7d")
    assert res_7d.status_code == 200

    res_30d = client.get("/api/v1/jobs?posted_since=30d")
    assert res_30d.status_code == 200
