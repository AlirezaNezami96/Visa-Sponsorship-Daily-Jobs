"""
VisaLane Phase 8 Backend Test Suite.
Verifies B2B Self-Serve: Employer Job Posting, Quotas, and Analytics:
- Strict Phase 2 schema completeness validation (granular missing field error reporting)
- Plan-based active listing quota boundary enforcement (Free=1, Featured=3, Pro=Unlimited)
- Reclaiming quota upon closing listings
- Per-listing engagement analytics aggregation (views, unique sessions, apply clicks, CTR)
- SEO pipeline cross-checks (sitemap data, XML sitemap, country summary inclusion and exclusion upon closing)
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient

from engine.api.main import app
from engine.api.billing_service import clear_mock_billing_stores, set_mock_company_billing, set_mock_user_profile
from engine.api.employer_models import EmployerJobCreateRequest, EmployerJobUpdateRequest
from engine.api.employer_service import (
    clear_mock_employer_stores,
    close_employer_job,
    create_employer_job,
    get_employer_job,
    get_job_analytics,
    list_employer_jobs,
    update_employer_job,
    validate_job_schema_completeness,
)
from engine.api.jobs_routes import clear_mock_stores, limiter

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_test_state():
    """Reset all in-memory mock stores before each test."""
    clear_mock_employer_stores()
    clear_mock_billing_stores()
    clear_mock_stores()
    try:
        limiter.reset()
    except Exception:
        pass


def _valid_job_payload(**overrides) -> Dict[str, Any]:
    """Factory helper generating a complete, schema-compliant job submission."""
    base = {
        "title": "Senior Distributed Systems Engineer",
        "description": "Join our cloud infrastructure team to design, scale, and operate mission-critical payment networks across Europe.",
        "company_name": "Stripe Payments Europe",
        "company_website": "https://stripe.com",
        "location": "Dublin, Ireland",
        "city": "Dublin",
        "country": "Ireland",
        "country_code": "IE",
        "is_remote": False,
        "apply_url": "https://stripe.com/jobs/senior-distributed-systems",
        "visa_types": ["Critical Skills Employment Permit"],
        "salary_min": 105000,
        "salary_max": 135000,
        "salary_currency": "EUR",
        "employer_id": "emp_stripe_dublin",
        "company_slug": "stripe-payments-europe",
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# 1. Schema Completeness & Granular Error Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_schema_completeness_missing_title():
    """Missing title must independently trigger rejection naming 'title'."""
    payload = _valid_job_payload(title="")
    res = client.post("/api/v1/employer/jobs", json=payload)
    assert res.status_code == 422
    data = res.json()["detail"]
    assert data["error"] == "SCHEMA_VALIDATION_FAILED"
    assert "title" in data["missing_fields"]
    assert "Job title is required" in data["validation_errors"]["title"]


def test_schema_completeness_short_description():
    """Description shorter than 30 characters must be rejected naming 'description'."""
    payload = _valid_job_payload(description="Short job desc")
    res = client.post("/api/v1/employer/jobs", json=payload)
    assert res.status_code == 422
    data = res.json()["detail"]
    assert data["error"] == "SCHEMA_VALIDATION_FAILED"
    assert "description" in data["missing_fields"]
    assert "at least 30 characters" in data["validation_errors"]["description"]


def test_schema_completeness_missing_company_name():
    """Missing company_name must be rejected naming 'company_name'."""
    payload = _valid_job_payload(company_name="")
    res = client.post("/api/v1/employer/jobs", json=payload)
    assert res.status_code == 422
    data = res.json()["detail"]
    assert data["error"] == "SCHEMA_VALIDATION_FAILED"
    assert "company_name" in data["missing_fields"]


def test_schema_completeness_missing_location_when_not_remote():
    """Non-remote job missing location, city, and country must be rejected naming 'location'."""
    payload = _valid_job_payload(location="", city="", country="", is_remote=False)
    res = client.post("/api/v1/employer/jobs", json=payload)
    assert res.status_code == 422
    data = res.json()["detail"]
    assert data["error"] == "SCHEMA_VALIDATION_FAILED"
    assert "location" in data["missing_fields"]


def test_schema_completeness_remote_without_physical_location_is_valid():
    """Remote job without physical location must succeed."""
    payload = _valid_job_payload(location="", city="", country="", is_remote=True)
    res = client.post("/api/v1/employer/jobs", json=payload)
    assert res.status_code == 201
    assert res.json()["is_remote"] is True
    assert res.json()["work_mode"] == "remote"


def test_schema_completeness_missing_or_invalid_apply_url():
    """Missing or invalid apply_url must be rejected naming 'apply_url'."""
    # Invalid URL format
    payload_invalid = _valid_job_payload(apply_url="not-a-valid-url")
    res_inv = client.post("/api/v1/employer/jobs", json=payload_invalid)
    assert res_inv.status_code == 422
    assert "apply_url" in res_inv.json()["detail"]["missing_fields"]

    # Empty URL
    payload_empty = _valid_job_payload(apply_url="")
    res_empty = client.post("/api/v1/employer/jobs", json=payload_empty)
    assert res_empty.status_code == 422
    assert "apply_url" in res_empty.json()["detail"]["missing_fields"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Plan Quota Boundary Tests (Free, Featured, Pro)
# ─────────────────────────────────────────────────────────────────────────────

def test_quota_boundary_free_tier():
    """
    Free tier quota is exactly 1 active listing.
    - 1st listing: 201 Created (at limit: 1/1)
    - 2nd listing: 403 Forbidden with ACTIVE_LISTING_QUOTA_EXCEEDED upgrade prompt
    """
    emp_id = "emp_free_quota_tester"
    payload1 = _valid_job_payload(employer_id=emp_id, title="Listing 1")
    res1 = client.post("/api/v1/employer/jobs", json=payload1)
    assert res1.status_code == 201
    assert res1.json()["source"] == "employer_direct"

    # Attempt 2nd listing (N+1)
    payload2 = _valid_job_payload(employer_id=emp_id, title="Listing 2")
    res2 = client.post("/api/v1/employer/jobs", json=payload2)
    assert res2.status_code == 403
    err = res2.json()["detail"]
    assert err["error"] == "ACTIVE_LISTING_QUOTA_EXCEEDED"
    assert err["plan_name"] == "free"
    assert err["current_limit"] == 1
    assert err["current_active_count"] == 1
    assert "upgrade_url" in err


def test_quota_boundary_featured_tier():
    """
    Featured tier quota is exactly 3 active listings.
    - Listings 1, 2, 3: 201 Created (at limit: 3/3)
    - Listing 4: 403 Forbidden with upgrade prompt
    """
    c_slug = "featured-corp"
    emp_id = "emp_featured_user"
    set_mock_company_billing(c_slug, {"employer_plan": "featured"})

    for i in range(1, 4):
        p = _valid_job_payload(employer_id=emp_id, company_slug=c_slug, title=f"Featured Listing {i}")
        res = client.post("/api/v1/employer/jobs", json=p)
        assert res.status_code == 201

    # Attempt 4th listing (N+1)
    p4 = _valid_job_payload(employer_id=emp_id, company_slug=c_slug, title="Featured Listing 4")
    res4 = client.post("/api/v1/employer/jobs", json=p4)
    assert res4.status_code == 403
    err = res4.json()["detail"]
    assert err["error"] == "ACTIVE_LISTING_QUOTA_EXCEEDED"
    assert err["current_limit"] == 3
    assert err["current_active_count"] == 3


def test_quota_pro_tier_unlimited():
    """Pro tier has unlimited listings."""
    emp_id = "emp_pro_user"
    c_slug = "pro-tech-ltd"
    set_mock_company_billing(c_slug, {"employer_plan": "pro"})

    for i in range(1, 6):
        p = _valid_job_payload(employer_id=emp_id, company_slug=c_slug, title=f"Pro Role {i}")
        res = client.post("/api/v1/employer/jobs", json=p)
        assert res.status_code == 201


# ─────────────────────────────────────────────────────────────────────────────
# 3. Quota Reclamation on Closing Listings
# ─────────────────────────────────────────────────────────────────────────────

def test_closing_listing_reclaims_quota():
    """Closing an active listing reduces active count and allows posting a new listing."""
    emp_id = "emp_reclaim_tester"
    payload1 = _valid_job_payload(employer_id=emp_id, title="First Job")
    res1 = client.post("/api/v1/employer/jobs", json=payload1)
    assert res1.status_code == 201
    job_id = res1.json()["id"]

    # Blocked for 2nd job
    res_blocked = client.post("/api/v1/employer/jobs", json=_valid_job_payload(employer_id=emp_id, title="Second Job"))
    assert res_blocked.status_code == 403

    # Close the first listing
    res_close = client.post(f"/api/v1/employer/jobs/{job_id}/close?employer_id={emp_id}")
    assert res_close.status_code == 200
    assert res_close.json()["job_status"] == "Closed"
    assert res_close.json()["is_active"] is False

    # Now posting the second job succeeds!
    res_retry = client.post("/api/v1/employer/jobs", json=_valid_job_payload(employer_id=emp_id, title="Second Job"))
    assert res_retry.status_code == 201
    assert res_retry.json()["title"] == "Second Job"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Employer Job Update & Retrieval Endpoints
# ─────────────────────────────────────────────────────────────────────────────

def test_employer_job_crud_and_ownership():
    """Verify single job retrieval, updates, and ownership validation."""
    emp_id = "emp_crud_owner"
    payload = _valid_job_payload(employer_id=emp_id, title="Staff Engineer")
    created = client.post("/api/v1/employer/jobs", json=payload).json()
    job_id = created["id"]

    # Get Single Job
    res_get = client.get(f"/api/v1/employer/jobs/{job_id}")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == job_id

    # Update Single Job
    update_data = {"title": "Principal Staff Engineer", "salary_min": 140000}
    res_put = client.put(f"/api/v1/employer/jobs/{job_id}?employer_id={emp_id}", json=update_data)
    assert res_put.status_code == 200
    assert res_put.json()["title"] == "Principal Staff Engineer"
    assert res_put.json()["salary_min"] == 140000

    # Unauthorized edit from another employer fails (403)
    res_unauth = client.put(f"/api/v1/employer/jobs/{job_id}?employer_id=attacker", json=update_data)
    assert res_unauth.status_code == 403

    # List Employer Jobs
    res_list = client.get(f"/api/v1/employer/jobs?employer_id={emp_id}")
    assert res_list.status_code == 200
    list_data = res_list.json()
    assert list_data["total_count"] == 1
    assert list_data["active_count"] == 1
    assert list_data["jobs"][0]["id"] == job_id


# ─────────────────────────────────────────────────────────────────────────────
# 5. Per-Listing Engagement Analytics Endpoint
# ─────────────────────────────────────────────────────────────────────────────

def test_job_analytics_aggregation():
    """
    Verify GET /api/v1/employer/jobs/{id}/analytics computes:
    - total_views, unique_viewers, apply_clicks, and CTR.
    """
    emp_id = "emp_analytics_user"
    created = client.post("/api/v1/employer/jobs", json=_valid_job_payload(employer_id=emp_id)).json()
    job_id = created["id"]

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Simulate First-Party Events in _MOCK_EVENTS_STORE
    from engine.api.jobs_routes import _MOCK_EVENTS_STORE
    _MOCK_EVENTS_STORE.extend([
        {"event_type": "job_viewed", "session_id": "sess_1", "metadata": {"job_id": job_id}, "created_at": now},
        {"event_type": "job_viewed", "session_id": "sess_1", "metadata": {"job_id": job_id}, "created_at": now},
        {"event_type": "job_viewed", "session_id": "sess_2", "metadata": {"job_id": job_id}, "created_at": now},
        {"event_type": "job_viewed", "session_id": "sess_3", "metadata": {"job_id": job_id}, "created_at": now},
        {"event_type": "apply_click", "session_id": "sess_2", "metadata": {"job_id": job_id}, "created_at": now},
    ])

    res_an = client.get(f"/api/v1/employer/jobs/{job_id}/analytics")
    assert res_an.status_code == 200
    an_data = res_an.json()
    assert an_data["job_id"] == job_id
    assert an_data["total_views"] == 4
    assert an_data["unique_viewers"] == 3
    assert an_data["apply_clicks"] == 1
    assert an_data["click_through_rate"] == 0.25  # 1 / 4
    assert len(an_data["daily_breakdown"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. SEO Pipeline Cross-Checks (Phase 2 Parity)
# ─────────────────────────────────────────────────────────────────────────────

def test_self_serve_job_flows_identically_into_seo_pipeline():
    """
    Cross-phase verification:
    1. Direct employer job appears in GET /api/v1/jobs with source: employer_direct
    2. Appears in GET /api/v1/sitemap-data
    3. Increments country summary count for Ireland
    4. Upon closing, disappears immediately from active search and sitemap
    """
    payload = _valid_job_payload(country="Ireland", country_code="IE")
    created = client.post("/api/v1/employer/jobs", json=payload).json()
    job_id = created["id"]
    slug = created["slug"]

    # 1. Public Search Endpoint
    res_search = client.get("/api/v1/jobs?country=ireland")
    assert res_search.status_code == 200
    results = res_search.json()["results"]
    assert any(r["id"] == job_id and r["source"] == "employer_direct" for r in results)

    # 2. Public Job Detail with JobPosting schema.org
    res_det = client.get(f"/api/v1/jobs/{slug}")
    assert res_det.status_code == 200
    assert res_det.json()["source"] == "employer_direct"

    # 3. Phase 2 Sitemap-Data Endpoint
    res_sitemap = client.get("/api/v1/sitemap-data")
    assert res_sitemap.status_code == 200
    sitemap_data = res_sitemap.json()
    assert any(j["id"] == job_id for j in sitemap_data["job_slugs"])
    assert "ireland" in sitemap_data["countries"]

    # 4. Phase 2 Country Summary Endpoint
    res_country = client.get("/api/v1/countries/ireland/summary")
    assert res_country.status_code == 200
    assert res_country.json()["job_count"] >= 1

    # 5. Close the Listing
    res_close = client.post(f"/api/v1/employer/jobs/{job_id}/close?employer_id={payload['employer_id']}")
    assert res_close.status_code == 200

    # 6. Public Search immediately excludes closed job
    res_search_after = client.get("/api/v1/jobs?country=ireland")
    results_after = res_search_after.json()["results"]
    assert not any(r["id"] == job_id for r in results_after)

    # 7. Sitemap immediately excludes closed job
    res_sitemap_after = client.get("/api/v1/sitemap-data")
    assert not any(j["id"] == job_id for j in res_sitemap_after.json()["job_slugs"])


# ─────────────────────────────────────────────────────────────────────────────
# 7. Additional Edge Case & Coverage Booster Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_schema_completeness_invalid_date_posted():
    """Submitting an unparseable date_posted string must fail validation."""
    payload = _valid_job_payload(date_posted="invalid-non-iso-date")
    res = client.post("/api/v1/employer/jobs", json=payload)
    assert res.status_code == 422
    assert "date_posted" in res.json()["detail"]["missing_fields"]


def test_employer_crud_fallback_and_not_found():
    """Test 404 on missing jobs and 422 on schema invalidation during update."""
    # 404 on get
    res_404_get = client.get("/api/v1/employer/jobs/job_missing_123")
    assert res_404_get.status_code == 404

    # 404 on put
    res_404_put = client.put("/api/v1/employer/jobs/job_missing_123", json={"title": "New Title"})
    assert res_404_put.status_code == 404

    # 404 on close
    res_404_close = client.post("/api/v1/employer/jobs/job_missing_123/close")
    assert res_404_close.status_code == 404

    # 422 on update causing invalid schema (e.g. erasing title)
    created = client.post("/api/v1/employer/jobs", json=_valid_job_payload(employer_id="emp_val")).json()
    job_id = created["id"]

    res_inv_update = client.put(f"/api/v1/employer/jobs/{job_id}?employer_id=emp_val", json={"title": ""})
    assert res_inv_update.status_code == 422
    assert "title" in res_inv_update.json()["detail"]["missing_fields"]


def test_employer_list_filters_and_user_entitlements():
    """Test list filtering by status ('active', 'closed'), company slug, and user plan quota."""
    emp_id = "emp_filter_user"
    c_slug = "filter-corp"
    set_mock_user_profile(emp_id, {"subscription_plan": "employer_pro"})

    # Post 2 jobs
    j1 = client.post("/api/v1/employer/jobs", json=_valid_job_payload(employer_id=emp_id, company_slug=c_slug, title="Job 1")).json()
    j2 = client.post("/api/v1/employer/jobs", json=_valid_job_payload(employer_id=emp_id, company_slug=c_slug, title="Job 2")).json()

    # Close Job 1
    client.post(f"/api/v1/employer/jobs/{j1['id']}/close?employer_id={emp_id}")

    # List active only
    res_act = client.get(f"/api/v1/employer/jobs?employer_id={emp_id}&status=active")
    assert res_act.status_code == 200
    assert len(res_act.json()["jobs"]) == 1
    assert res_act.json()["jobs"][0]["id"] == j2["id"]

    # List closed only
    res_cls = client.get(f"/api/v1/employer/jobs?employer_id={emp_id}&status=closed")
    assert res_cls.status_code == 200
    assert len(res_cls.json()["jobs"]) == 1
    assert res_cls.json()["jobs"][0]["id"] == j1["id"]

    # List with company_slug filter
    res_comp = client.get(f"/api/v1/employer/jobs?company_slug={c_slug}")
    assert res_comp.status_code == 200
    assert len(res_comp.json()["jobs"]) == 2


def test_job_analytics_custom_date_range_and_event_filtering():
    """Verify analytics behavior with custom start/end dates and malformed event logs."""
    emp_id = "emp_an_deep"
    created = client.post("/api/v1/employer/jobs", json=_valid_job_payload(employer_id=emp_id)).json()
    job_id = created["id"]

    now = datetime.datetime.now(datetime.timezone.utc)
    start_str = (now - datetime.timedelta(days=7)).date().isoformat()
    end_str = now.date().isoformat()

    old_date = (now - datetime.timedelta(days=20)).isoformat()
    valid_date = (now - datetime.timedelta(days=2)).isoformat()

    from engine.api.jobs_routes import _MOCK_EVENTS_STORE
    _MOCK_EVENTS_STORE.extend([
        # Within date range
        {"event_type": "job_viewed", "session_id": "s1", "metadata": {"job_id": job_id}, "created_at": valid_date},
        {"event_type": "apply_click", "session_id": "s1", "metadata": {"job_id": job_id}, "created_at": valid_date},
        # Outside date range (too old)
        {"event_type": "job_viewed", "session_id": "s_old", "metadata": {"job_id": job_id}, "created_at": old_date},
        # Malformed event without timestamp
        {"event_type": "job_viewed", "session_id": "s_bad", "metadata": {"job_id": job_id}, "created_at": None},
        # Malformed invalid timestamp string
        {"event_type": "job_viewed", "session_id": "s_bad2", "metadata": {"job_id": job_id}, "created_at": "not-a-date"},
        # Event for a different job
        {"event_type": "job_viewed", "session_id": "s_other", "metadata": {"job_id": "other_job_999"}, "created_at": valid_date},
    ])

    res = client.get(f"/api/v1/employer/jobs/{job_id}/analytics?start_date={start_str}&end_date={end_str}")
    assert res.status_code == 200
    data = res.json()
    assert data["total_views"] == 1
    assert data["apply_clicks"] == 1
    assert data["click_through_rate"] == 1.0
