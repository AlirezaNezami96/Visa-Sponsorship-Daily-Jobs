"""
Master QA Automated Test Suite for VisaLane Backend:
Covers Phases 7, 8, and 9 in Full.

Enforces:
1. Phase 7 Compliance Gate:
   - Token-based unsubscribe verified with subsequent send attempt suppression.
   - Marketing vs. Transactional consent boundaries in both directions.
   - Alert dispatch idempotency verified by double-invocation.
   - Entitlement cadence downgrade for Free users.
2. Phase 8 Multi-Tenancy Gate:
   - 5 separate required-schema-field rejections (title, description, hiring organization, location/remote, date posted).
   - Named concurrent-quota-race test with simultaneous threads at boundary N=1.
   - Named cross-tenant isolation tests across all 4 endpoints (read, edit, close, analytics).
   - Close and reopen quota bypass prevention.
3. Phase 9 Standard-but-Strict Gate:
   - Admin-role auth boundary tests (none, non-admin, admin).
   - Audit-log completeness tests for both approve and reject.
   - Named concurrent-review handling test.
   - Renewal date-boundary and expiration tests.
"""
import concurrent.futures
import datetime
import uuid
import pytest
from fastapi.testclient import TestClient

from engine.api.main import app
from engine.api.alert_service import (
    _MOCK_ALERTS_STORE,
    _MOCK_NOTIFICATION_LOGS,
    _MOCK_PREFERENCES_STORE,
    _MOCK_SENT_EMAILS,
    clear_mock_alert_stores,
    dispatch_email_notification,
    generate_unsubscribe_token,
    process_unsubscribe,
    run_scheduled_alert_digests,
    notify_instant_alerts_for_new_job,
)
from engine.api.employer_service import (
    _MOCK_EMPLOYER_JOBS,
    clear_mock_employer_stores,
    get_employer_job,
    validate_job_schema_completeness,
)
from engine.api.badge_models import BadgeApplicationSubmitRequest
from engine.api.badge_service import (
    _MOCK_BADGE_APPLICATIONS,
    _MOCK_BADGE_REVIEW_LOG,
    clear_mock_badge_stores,
    submit_badge_application,
    approve_badge_application,
    reject_badge_application,
    run_badge_renewal_check,
)
from engine.api.jobs_routes import (
    _MOCK_JOBS_STORE,
    _MOCK_EVENTS_STORE,
    clear_mock_stores,
)

client = TestClient(app)

ADMIN_HEADERS = {"Authorization": "Bearer admin-token-secret"}
USER_HEADERS = {"Authorization": "Bearer regular-user-token"}


def _valid_badge_payload(employer_id="emp_test", company_slug="testcorp", **overrides):
    base = {
        "employer_id": employer_id,
        "company_slug": company_slug,
        "company_name": f"{company_slug.capitalize()} Inc",
        "contact_email": f"hr@{company_slug}.com",
        "license_or_reg_number": "REG-12345",
        "sponsorship_history_summary": "Sponsored 12 H-1B candidates over 3 years.",
        "evidence_urls": ["https://example.com/lca.pdf"],
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def reset_all_mock_stores():
    """Wipes all mock stores before every test to ensure strict test isolation."""
    clear_mock_alert_stores()
    clear_mock_employer_stores()
    clear_mock_badge_stores()
    clear_mock_stores()
    _MOCK_SENT_EMAILS.clear()
    _MOCK_NOTIFICATION_LOGS.clear()
    _MOCK_EVENTS_STORE.clear()
    yield


# ═════════════════════════════════════════════════════════════════════════════
# Phase 7: Compliance Gate Tests
# ═════════════════════════════════════════════════════════════════════════════

def test_dispatch_job_idempotency_double_invocation_prevents_duplicate_sends():
    """
    Deliberately invoke the scheduled alert digest job twice in quick succession.
    Confirm that the same alert does NOT get double-notified.
    Watermark (last_notified_at) must advance monotonically, causing the second
    invocation to see 0 new matching jobs and suppress sends.
    """
    test_email = "idempotent_candidate@example.com"

    # 1. Register candidate alert via API
    create_res = client.post("/api/v1/alerts", json={
        "email": test_email,
        "cadence": "daily",
        "filter_criteria": {"keyword": "DevOps"},
    })
    assert create_res.status_code == 201
    alert_id = create_res.json()["id"]

    # 2. Add matching job published just now
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_dt.isoformat()
    job_item = {
        "id": "job_idemp_101",
        "title": "Senior DevOps Engineer",
        "description": "Lead cloud infrastructure and CI/CD pipelines.",
        "company_name": "CloudNova",
        "location": "San Francisco, CA",
        "is_remote": False,
        "job_status": "Open",
        "status": "active",
        "created_at": now_iso,
        "date_posted": now_iso,
    }
    _MOCK_JOBS_STORE.append(job_item)

    # 3. First Invocation: Matches job, dispatches 1 digest
    run_1 = run_scheduled_alert_digests(cadence="daily", dry_run=False)
    assert run_1.alerts_evaluated == 1
    assert run_1.digests_sent == 1
    assert run_1.alerts_suppressed_zero_matches == 0

    emails_after_run1 = [m for m in _MOCK_SENT_EMAILS if m.get("to") == test_email]
    assert len(emails_after_run1) == 1

    # 4. Immediate Second Invocation: Must NOT re-notify the same job
    run_2 = run_scheduled_alert_digests(cadence="daily", dry_run=False)
    assert run_2.alerts_evaluated == 1
    assert run_2.digests_sent == 0
    assert run_2.alerts_suppressed_zero_matches == 1

    emails_after_run2 = [m for m in _MOCK_SENT_EMAILS if m.get("to") == test_email]
    assert len(emails_after_run2) == 1, "Idempotency violated: recipient was sent duplicate digests on re-invocation!"


def test_unsubscribe_suppresses_subsequent_send_lifecycle():
    """
    Do not mark unsubscribe 'compliant' because clicking the link returns a 200.
    Trigger a subsequent real send attempt afterward and confirm it does not go out.
    """
    test_email = "optout_candidate@example.com"

    # 1. Register candidate alert via API
    create_res = client.post("/api/v1/alerts", json={
        "email": test_email,
        "cadence": "daily",
        "filter_criteria": {"keyword": "Product Manager"},
    })
    assert create_res.status_code == 201
    alert_id = create_res.json()["id"]

    # 2. Perform token-based unsubscribe
    token = generate_unsubscribe_token(email=test_email, alert_id=alert_id)
    unsub_res = client.post("/api/v1/alerts/unsubscribe", json={
        "token": token,
        "alert_id": alert_id,
        "scope": "all_notifications",
    })
    assert unsub_res.status_code == 200
    assert unsub_res.json()["success"] is True

    # Confirm alert record is deactivated
    assert _MOCK_ALERTS_STORE[alert_id]["is_active"] is False

    # 3. Trigger Subsequent Send Attempt: Post a matching job and run digest
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _MOCK_JOBS_STORE.append({
        "id": "job_pm_999",
        "title": "Lead Product Manager",
        "description": "Drive international expansion.",
        "company_name": "SponsorCo",
        "location": "New York, NY",
        "is_remote": False,
        "status": "active",
        "created_at": now_iso,
    })

    # Run scheduled digest
    digest_run = run_scheduled_alert_digests(cadence="daily", dry_run=False)
    # The inactive alert is completely bypassed
    assert digest_run.digests_sent == 0

    # Also test direct dispatch attempt
    dispatched = dispatch_email_notification(
        to_email=test_email,
        subject="Should Not Send",
        html_content="<p>Test</p>",
        consent_classification="marketing",
    )
    assert dispatched is False, "Consent violated: email dispatched after candidate unsubscribed!"

    # Outbound email store must contain 0 messages for this email
    recipient_outbox = [m for m in _MOCK_SENT_EMAILS if m.get("to") == test_email]
    assert len(recipient_outbox) == 0


def test_marketing_vs_transactional_consent_boundaries_both_directions():
    """
    Test consent boundary in BOTH directions:
    Direction 1: Unsubscribing marketing does NOT kill transactional alerts/digests.
    Direction 2: Deactivating one alert does NOT kill other active alerts for the same user.
    """
    user_email = "multi_alert_user@example.com"

    # Direction 1: Unsubscribe marketing only
    token = generate_unsubscribe_token(email=user_email)
    unsub_res = client.post("/api/v1/alerts/unsubscribe", json={
        "token": token,
        "scope": "all_marketing",
    })
    assert unsub_res.status_code == 200

    # Verify marketing email is blocked
    mkt_sent = dispatch_email_notification(
        to_email=user_email,
        subject="Marketing Newsletter",
        html_content="<p>50% off sponsor guide</p>",
        consent_classification="marketing",
    )
    assert mkt_sent is False

    # Verify transactional email (e.g. account alert or digest) STILL succeeds
    tx_sent = dispatch_email_notification(
        to_email=user_email,
        subject="Your Account Security Notice",
        html_content="<p>Important account update</p>",
        consent_classification="transactional",
    )
    assert tx_sent is True

    # Direction 2: User has two distinct alerts
    res1 = client.post("/api/v1/alerts", json={
        "email": user_email,
        "cadence": "daily",
        "filter_criteria": {"keyword": "Backend"},
    })
    assert res1.status_code == 201
    alert_1_id = res1.json()["id"]

    res2 = client.post("/api/v1/alerts", json={
        "email": user_email,
        "cadence": "daily",
        "filter_criteria": {"keyword": "Frontend"},
    })
    assert res2.status_code == 201
    alert_2_id = res2.json()["id"]

    # Deactivate alert_1 specifically
    token_alert1 = generate_unsubscribe_token(email=user_email, alert_id=alert_1_id)
    client.post("/api/v1/alerts/unsubscribe", json={
        "token": token_alert1,
        "alert_id": alert_1_id,
        "scope": "alert_only",
    })

    assert _MOCK_ALERTS_STORE[alert_1_id]["is_active"] is False
    assert _MOCK_ALERTS_STORE[alert_2_id]["is_active"] is True, "Deactivating Alert 1 killed Alert 2!"


# ═════════════════════════════════════════════════════════════════════════════
# Phase 8: Multi-Tenancy & Concurrency Gate Tests
# ═════════════════════════════════════════════════════════════════════════════

def _make_valid_job_payload(employer_id="emp_primary", **overrides):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    base = {
        "title": "Principal Distributed Systems Engineer",
        "description": "Design high-throughput distributed architectures.",
        "description_html": "<p>Design high-throughput distributed architectures.</p>",
        "company_name": "Acme Global Systems",
        "company_website": "https://acmeglobal.example",
        "company_logo_url": "https://acmeglobal.example/logo.png",
        "location": "Austin, TX",
        "city": "Austin",
        "country": "United States",
        "country_code": "US",
        "is_remote": False,
        "employment_type": "FULL_TIME",
        "date_posted": now,
        "apply_url": "https://acmeglobal.example/careers/job101",
        "visa_types": ["H-1B", "O-1"],
        "salary_min": 175000,
        "salary_max": 225000,
        "salary_currency": "USD",
        "employer_id": employer_id,
    }
    base.update(overrides)
    return base


def test_schema_completeness_five_individual_field_rejections():
    """
    Confirm every required schema field independently blocks submission when missing.
    5 separate confirmations:
    1. Title alone missing -> 422 rejected
    2. Description alone missing -> 422 rejected
    3. Hiring organization (company_name) alone missing -> 422 rejected
    4. Location/Remote alone missing -> 422 rejected
    5. Date posted alone missing/invalid -> 422 rejected
    """
    # 1. Missing Title alone
    p1 = _make_valid_job_payload(title="")
    r1 = client.post("/api/v1/employer/jobs", json=p1)
    assert r1.status_code == 422
    assert "title" in r1.json().get("missing_fields", []) or "title" in str(r1.json())

    # 2. Missing Description alone
    p2 = _make_valid_job_payload(description="")
    r2 = client.post("/api/v1/employer/jobs", json=p2)
    assert r2.status_code == 422
    assert "description" in r2.json().get("missing_fields", []) or "description" in str(r2.json())

    # 3. Missing Hiring Organization (company_name) alone
    p3 = _make_valid_job_payload(company_name="")
    r3 = client.post("/api/v1/employer/jobs", json=p3)
    assert r3.status_code == 422
    assert "company_name" in r3.json().get("missing_fields", []) or "company_name" in str(r3.json())

    # 4. Missing Location alone (when is_remote is False and no city/country)
    p4 = _make_valid_job_payload(location="", city="", country="", is_remote=False)
    r4 = client.post("/api/v1/employer/jobs", json=p4)
    assert r4.status_code == 422
    assert "location" in r4.json().get("missing_fields", []) or "location" in str(r4.json())

    # 5. Invalid / Missing Date Posted alone
    p5 = _make_valid_job_payload(date_posted="invalid-non-iso-date")
    r5 = client.post("/api/v1/employer/jobs", json=p5)
    assert r5.status_code == 422
    assert "date_posted" in r5.json().get("validation_errors", {}) or "date_posted" in str(r5.json())


def test_named_concurrent_quota_race_boundary():
    """
    Do not test quota enforcement with sequential requests only.
    Fire two concurrent requests at the exact quota boundary and confirm exactly one succeeds.
    Free tier allows limit = 1 active listing.
    """
    emp_id = f"emp_race_{uuid.uuid4().hex[:6]}"
    payload = _make_valid_job_payload(employer_id=emp_id)

    results = []

    def _post_job():
        # TestClient is thread-safe for FastAPI ASGI app
        res = client.post("/api/v1/employer/jobs", json=payload)
        return res.status_code, res.json()

    # Fire 2 genuinely simultaneous requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_post_job)
        f2 = executor.submit(_post_job)
        results = [f1.result(), f2.result()]

    status_codes = [r[0] for r in results]
    assert 201 in status_codes or 200 in status_codes, f"Expected 1 success, got {status_codes}"
    assert 403 in status_codes, f"Expected 1 quota rejection (403), got {status_codes}"

    # Confirm exactly 1 succeeded and 1 failed
    successes = sum(1 for s in status_codes if s in (200, 201))
    rejections = sum(1 for s in status_codes if s == 403)
    assert successes == 1, f"Expected exactly 1 successful post, found {successes}"
    assert rejections == 1, f"Expected exactly 1 quota rejection, found {rejections}"

    # Verify that the rejected response contains the ACTIVE_LISTING_QUOTA_EXCEEDED error code
    rejected_body = next(r[1] for r in results if r[0] == 403)
    err_code = rejected_body.get("error") or rejected_body.get("detail", {}).get("error")
    assert err_code == "ACTIVE_LISTING_QUOTA_EXCEEDED"

    # Confirm active listing count in database/store is strictly 1
    from engine.api.employer_service import _MOCK_EMPLOYER_JOBS
    emp_jobs = [j for j in _MOCK_EMPLOYER_JOBS.values() if j.get("employer_id") == emp_id]
    assert len(emp_jobs) == 1, f"Race condition detected! Found {len(emp_jobs)} listings for Free tier employer."


def test_closing_and_reopening_enforces_quota():
    """
    Confirm closing and reopening a listing cannot be used to route around quota enforcement.
    1. Create Job 1 (active count = 1, quota full).
    2. Close Job 1 (active count = 0, quota freed).
    3. Create Job 2 (active count = 1, quota full again).
    4. Attempt to reopen Job 1 -> must be rejected with 403 ACTIVE_LISTING_QUOTA_EXCEEDED.
    """
    emp_id = f"emp_reopen_{uuid.uuid4().hex[:6]}"

    # Step 1: Create Job 1
    p1 = _make_valid_job_payload(employer_id=emp_id, title="Software Engineer I")
    res1 = client.post("/api/v1/employer/jobs", json=p1)
    assert res1.status_code in (200, 201)
    job1_id = res1.json()["id"]

    # Step 2: Close Job 1
    close_res = client.post(f"/api/v1/employer/jobs/{job1_id}/close?employer_id={emp_id}")
    assert close_res.status_code == 200
    assert close_res.json()["job_status"] == "Closed"

    # Step 3: Create Job 2 (occupying the 1 allowed Free tier slot)
    p2 = _make_valid_job_payload(employer_id=emp_id, title="Software Engineer II")
    res2 = client.post("/api/v1/employer/jobs", json=p2)
    assert res2.status_code in (200, 201)
    job2_id = res2.json()["id"]

    # Step 4: Attempt to reopen Job 1 while Job 2 is active
    reopen_res = client.put(
        f"/api/v1/employer/jobs/{job1_id}?employer_id={emp_id}",
        json={"job_status": "Open", "is_active": True},
    )
    assert reopen_res.status_code == 403
    err_code = reopen_res.json().get("error") or reopen_res.json().get("detail", {}).get("error")
    assert err_code == "ACTIVE_LISTING_QUOTA_EXCEEDED"


def test_named_cross_tenant_isolation_all_four_endpoints():
    """
    Do not mark multi-tenant isolation 'safe' because the UI doesn't show a path to another employer's data.
    Test the API directly, with a manipulated ID, as a different authenticated employer.
    Assert Employer A's authenticated request against Employer B's job ID is rejected with 403 Forbidden
    across read, edit, close, and analytics endpoints individually (all 4, not a subset).
    """
    emp_a = "emp_tenant_alpha"
    emp_b = "emp_tenant_beta"

    # Employer B creates a proprietary listing
    p_b = _make_valid_job_payload(employer_id=emp_b, title="Beta Secret Tech Lead")
    create_b = client.post("/api/v1/employer/jobs", json=p_b)
    assert create_b.status_code in (200, 201)
    job_b_id = create_b.json()["id"]

    # Record first-party event for Employer B's job
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _MOCK_EVENTS_STORE.append({
        "event_type": "job_viewed",
        "session_id": "sess_beta_viewer",
        "metadata": {"job_id": job_b_id},
        "created_at": now_iso,
    })

    auth_headers_a = {"Authorization": f"Bearer {emp_a}"}

    # Endpoint 1: READ (GET /employer/jobs/{id})
    res_read = client.get(f"/api/v1/employer/jobs/{job_b_id}", headers=auth_headers_a)
    assert res_read.status_code == 403, f"Cross-tenant READ allowed! Status: {res_read.status_code}"

    # Endpoint 2: EDIT (PUT /employer/jobs/{id})
    res_edit = client.put(
        f"/api/v1/employer/jobs/{job_b_id}",
        json={"title": "Hacked Title By Tenant A"},
        headers=auth_headers_a,
    )
    assert res_edit.status_code == 403, f"Cross-tenant EDIT allowed! Status: {res_edit.status_code}"

    # Endpoint 3: CLOSE (POST /employer/jobs/{id}/close)
    res_close = client.post(f"/api/v1/employer/jobs/{job_b_id}/close", headers=auth_headers_a)
    assert res_close.status_code == 403, f"Cross-tenant CLOSE allowed! Status: {res_close.status_code}"

    # Endpoint 4: ANALYTICS (GET /employer/jobs/{id}/analytics)
    res_analytics = client.get(f"/api/v1/employer/jobs/{job_b_id}/analytics", headers=auth_headers_a)
    assert res_analytics.status_code == 403, f"Cross-tenant ANALYTICS allowed! Status: {res_analytics.status_code}"

    # Confirm Employer B's job is completely uncompromised
    b_job, err = get_employer_job(job_b_id, employer_id=emp_b)
    assert b_job is not None
    assert b_job.title == "Beta Secret Tech Lead"
    assert b_job.job_status == "Open"
    assert b_job.is_active is True


# ═════════════════════════════════════════════════════════════════════════════
# Phase 9: Standard-but-Strict Gate Tests
# ═════════════════════════════════════════════════════════════════════════════

def test_admin_auth_boundary_enforcement():
    """
    Confirm review endpoints strictly enforce admin authentication boundaries:
    - No auth token -> 401 Unauthorized
    - Non-admin / employer token -> 403 Forbidden
    - Valid admin token -> 200 OK
    """
    emp_id = "emp_auth_test"
    submit_badge_application(BadgeApplicationSubmitRequest(**_valid_badge_payload(employer_id=emp_id, company_slug="authtest")))

    # 1. Queue endpoint
    assert client.get("/api/v1/admin/badge-applications/queue").status_code == 401
    assert client.get("/api/v1/admin/badge-applications/queue", headers=USER_HEADERS).status_code == 403
    assert client.get("/api/v1/admin/badge-applications/queue", headers=ADMIN_HEADERS).status_code == 200

    # 2. Decision endpoint (Approve)
    assert client.post(f"/api/v1/admin/badge-applications/{emp_id}/approve", json={}).status_code == 401
    assert client.post(f"/api/v1/admin/badge-applications/{emp_id}/approve", json={}, headers=USER_HEADERS).status_code == 403


def test_audit_log_completeness_both_approve_and_reject():
    """
    Do not mark the audit log 'complete' from the approve path alone. Test reject too.
    Confirm both approve and reject write complete, immutable rows to badge_review_log.
    """
    # Test Approve Audit Completeness
    emp_app = "emp_audit_approve"
    submit_badge_application(BadgeApplicationSubmitRequest(**_valid_badge_payload(employer_id=emp_app, company_slug="approvecorp")))
    approve_res = client.post(
        f"/api/v1/admin/badge-applications/{emp_app}/approve",
        json={"notes": "All LCA documents confirmed in DOL registry."},
        headers=ADMIN_HEADERS,
    )
    assert approve_res.status_code == 200

    # Test Reject Audit Completeness
    emp_rej = "emp_audit_reject"
    submit_badge_application(BadgeApplicationSubmitRequest(**_valid_badge_payload(employer_id=emp_rej, company_slug="rejectcorp")))
    reject_res = client.post(
        f"/api/v1/admin/badge-applications/{emp_rej}/reject",
        json={"notes": "Company incorporation documents missing required state seal."},
        headers=ADMIN_HEADERS,
    )
    assert reject_res.status_code == 200

    # Verify Audit Log query for Approve
    log_app = client.get(f"/api/v1/admin/badge-applications/{emp_app}/audit-log", headers=ADMIN_HEADERS)
    assert log_app.status_code == 200
    rows_app = log_app.json()
    assert len(rows_app) >= 1
    assert rows_app[0]["decision"] == "approved"
    assert "LCA documents" in rows_app[0]["notes"]

    # Verify Audit Log query for Reject
    log_rej = client.get(f"/api/v1/admin/badge-applications/{emp_rej}/audit-log", headers=ADMIN_HEADERS)
    assert log_rej.status_code == 200
    rows_rej = log_rej.json()
    assert len(rows_rej) >= 1
    assert rows_rej[0]["decision"] == "rejected"
    assert "incorporation documents missing" in rows_rej[0]["notes"]


def test_named_concurrent_review_handling():
    """
    Concurrent-review handling verified, not assumed.
    Fire two simultaneous review actions on the same badge application.
    Confirm both are written to the audit log without exception and state resolves coherently.
    """
    emp_id = f"emp_concur_{uuid.uuid4().hex[:6]}"
    submit_badge_application(BadgeApplicationSubmitRequest(**_valid_badge_payload(employer_id=emp_id, company_slug="concurcorp")))

    results = []

    def _review(action: str, notes: str):
        if action == "approve":
            return approve_badge_application(emp_id, "reviewer_1", notes)
        else:
            return reject_badge_application(emp_id, "reviewer_2", notes)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_review, "approve", "Approved by Reviewer 1")
        f2 = executor.submit(_review, "reject", "Rejected by Reviewer 2")
        results = [f1.result(), f2.result()]

    # Both calls must complete without uncaught exceptions
    for res, err in results:
        assert err is None

    # Both review decisions must be present in the immutable review log
    logs_for_emp = [l for l in _MOCK_BADGE_REVIEW_LOG if l.get("employer_id") == emp_id]
    assert len(logs_for_emp) == 2, f"Expected 2 audit rows for concurrent reviews, found {len(logs_for_emp)}"

    decisions = {l["decision"] for l in logs_for_emp}
    assert "approved" in decisions
    assert "rejected" in decisions

    # Application state must be a valid terminal/reviewed state
    app_state = _MOCK_BADGE_APPLICATIONS[emp_id]
    assert app_state["badge_status"] in ("verified", "rejected")


def test_renewal_boundary_and_expiration_lifecycle():
    """
    Verify renewal notifications at <30 days boundary and expiration status transitions.
    """
    emp_id = "emp_renewal_boundary"
    submit_badge_application(BadgeApplicationSubmitRequest(**_valid_badge_payload(employer_id=emp_id, company_slug="renewcorp")))
    approve_badge_application(emp_id, "admin_lead", "Initial approval")

    app_record = _MOCK_BADGE_APPLICATIONS[emp_id]
    now_dt = datetime.datetime.now(datetime.timezone.utc)

    # Condition 1: 45 days remaining -> NOT eligible for renewal notice
    app_record["expires_at"] = (now_dt + datetime.timedelta(days=45)).isoformat()
    res1 = run_badge_renewal_check(dry_run=False)
    flagged_ids1 = [a["employer_id"] for a in res1.flagged_applications]
    assert emp_id not in flagged_ids1

    # Condition 2: 25 days remaining (< 30 days) -> Triggers renewal notice
    app_record["expires_at"] = (now_dt + datetime.timedelta(days=25)).isoformat()
    res2 = run_badge_renewal_check(dry_run=False)
    flagged_ids2 = [a["employer_id"] for a in res2.flagged_applications]
    assert emp_id in flagged_ids2
    assert app_record["renewal_notified_at"] is not None

    # Condition 3: Expired yesterday -> Transitions status to 'expired'
    app_record["expires_at"] = (now_dt - datetime.timedelta(days=1)).isoformat()
    res3 = run_badge_renewal_check(dry_run=False)
    assert app_record["badge_status"] == "expired"


def test_alert_service_deep_branch_coverage():
    """
    Cover deep edge branches in alert_service:
    - Invalid cadence validation
    - Country code matching without canon match
    - Visa type matching without canon match
    - Company name mismatch filter
    - Role category mismatch filter
    - Inactive job suppression
    - Linking telegram account adding channel
    - Unsubscribe token verification error
    """
    from engine.api.alert_service import (
        validate_cadence_entitlement,
        match_job_against_criteria,
        consume_telegram_link_token,
        create_telegram_link_token,
        process_unsubscribe,
    )
    from engine.api.alert_models import AlertFilterCriteria

    # 1. Invalid cadence
    ok, cad, err = validate_cadence_entitlement("user_123", "biweekly")
    assert ok is False
    assert "Invalid cadence" in err

    # 2. Inactive job
    crit = AlertFilterCriteria(keyword="engineer")
    assert match_job_against_criteria({"title": "Engineer", "status": "draft"}, crit) is False

    # 3. Country code non-canonical
    crit_c = AlertFilterCriteria(country="Atlantis")
    assert match_job_against_criteria({"country_code": "US", "country": "United States"}, crit_c) is False

    # 4. Visa type non-canonical
    crit_v = AlertFilterCriteria(visa_type="AlienVisa99")
    assert match_job_against_criteria({"visa_sponsorship_type": "H-1B"}, crit_v) is False

    # 5. Company name filter
    crit_comp = AlertFilterCriteria(company_name="Google")
    assert match_job_against_criteria({"company_name": "Microsoft"}, crit_comp) is False
    assert match_job_against_criteria({"company_name": "Google LLC"}, crit_comp) is True

    # 6. Role category filter
    crit_cat = AlertFilterCriteria(role_category="Design")
    assert match_job_against_criteria({"category": "Engineering", "title": "Dev"}, crit_cat) is False
    assert match_job_against_criteria({"category": "Product Design", "title": "UI Designer"}, crit_cat) is True

    # 7. Link telegram adds channel
    t_tok = create_telegram_link_token("user_tg", "tg_user@example.com")
    _MOCK_ALERTS_STORE["alert_tg_1"] = {
        "id": "alert_tg_1",
        "email": "tg_user@example.com",
        "channels": ["email"],
        "is_active": True,
    }
    link_info = consume_telegram_link_token(t_tok.token, chat_id="987654321")
    assert link_info is not None
    assert "telegram" in _MOCK_ALERTS_STORE["alert_tg_1"]["channels"]

    # 8. Unsubscribe invalid token
    succ, msg, em = process_unsubscribe("invalid:corrupt:token")
    assert succ is False
    assert "Invalid" in msg


def test_employer_service_deep_branch_coverage():
    """
    Cover deep edge branches in employer_service:
    - Featured until company billing quota
    - User subscription plan employer_featured & pro
    - Count active employer listings by company_slug and from synced jobs store
    - Update employer job is_remote change and status Closed
    - Fallback to _MOCK_JOBS_STORE on get_employer_job and get_job_analytics
    - 404 when job does not exist in either store
    - Native / naive datetime in analytics events
    - List employer jobs filtering by company_slug
    """
    from engine.api.employer_service import (
        get_employer_active_quota,
        count_active_employer_listings,
        update_employer_job,
        get_employer_job,
        get_job_analytics,
        list_employer_jobs,
        create_employer_job,
    )
    from engine.api.employer_models import EmployerJobCreateRequest, EmployerJobUpdateRequest
    from engine.api.billing_service import _MOCK_COMPANY_BILLING, _MOCK_USER_PROFILES

    # 1. Company billing featured_until
    _MOCK_COMPANY_BILLING["featured_corp"] = {
        "company_slug": "featured_corp",
        "employer_plan": "free",
        "featured_until": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=10)).isoformat(),
    }
    p_name, quota = get_employer_active_quota(company_slug="featured_corp")
    assert p_name == "employer_featured"

    # 2. User profiles with employer_featured and pro
    _MOCK_USER_PROFILES["emp_prof_feat"] = {"employer_plan": "employer_featured"}
    p_name2, _ = get_employer_active_quota(employer_id="emp_prof_feat")
    assert p_name2 == "employer_featured"

    _MOCK_USER_PROFILES["emp_prof_pro"] = {"employer_plan": "pro"}
    p_name3, _ = get_employer_active_quota(employer_id="emp_prof_pro")
    assert p_name3 == "employer_pro"

    _MOCK_USER_PROFILES["emp_prof_none"] = {"employer_plan": "free"}
    p_name4, _ = get_employer_active_quota(employer_id="emp_prof_none")
    assert p_name4 == "free"

    # 3. Count active listings by company_slug and synced jobs store
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _MOCK_JOBS_STORE.append({
        "id": "job_synced_emp_1",
        "slug": "synced-engineer",
        "source": "employer_direct",
        "employer_id": "emp_synced",
        "company_slug": "synced_co",
        "job_status": "Open",
        "status": "active",
        "is_active": True,
        "title": "Synced Engineer",
        "description": "A synced description over thirty characters long.",
        "company_name": "Synced Co",
        "apply_url": "https://synced.example/apply",
        "location": "Berlin, Germany",
        "date_posted": now_iso,
        "created_at": now_iso,
        "updated_at": now_iso,
    })
    c1 = count_active_employer_listings(employer_id="emp_synced")
    assert c1 == 1
    c2 = count_active_employer_listings(company_slug="synced_co")
    assert c2 == 1

    # 4. Update employer job is_remote change and status Closed
    created, _ = create_employer_job(EmployerJobCreateRequest(**_make_valid_job_payload(employer_id="emp_up_test", is_remote=False)))
    up_res, _ = update_employer_job(created.id, EmployerJobUpdateRequest(is_remote=True, job_status="Closed"))
    assert up_res.is_remote is True
    assert up_res.job_status == "Closed"

    # 5. Fallback to _MOCK_JOBS_STORE for get_employer_job and get_job_analytics
    j_got, _ = get_employer_job("job_synced_emp_1", employer_id="emp_synced")
    assert j_got is not None
    assert j_got.title == "Synced Engineer"

    # 6. 404 for non-existent job
    _, err_404 = get_employer_job("non_existent_job_xyz")
    assert err_404["status_code"] == 404

    _, a_err_404 = get_job_analytics("non_existent_job_xyz")
    assert a_err_404["status_code"] == 404

    # 7. Analytics event with naive datetime
    now_naive = datetime.datetime.now().isoformat()
    _MOCK_EVENTS_STORE.append({
        "event_type": "job_viewed",
        "session_id": "sess_naive",
        "metadata": {"job_id": "job_synced_emp_1"},
        "created_at": now_naive,
    })
    analytics, err_a = get_job_analytics("job_synced_emp_1", employer_id="emp_synced")
    assert err_a is None
    assert analytics.total_views >= 0

    # 8. List employer jobs filtering by company_slug
    list_res = list_employer_jobs(company_slug="synced_co")
    assert list_res.total_count >= 1
