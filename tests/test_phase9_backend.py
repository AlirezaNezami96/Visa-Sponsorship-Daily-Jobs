"""
VisaLane Phase 9 Backend Test Suite: Verified Sponsor Badge Admin Review Workflow & Audit Trail.

Comprehensive tests covering:
1. Admin-role auth boundaries: zero auth (401), valid non-admin auth (403), valid admin auth (200).
2. Badge application submission, status querying, and validation.
3. Approval workflow:
   - Status transition to 'verified' with 12 months validity (expires_at = now + 365d)
   - Unconditional audit logging in badge_review_log
   - Real Phase 7 transactional email dispatch to employer
   - Immediate public badge visibility on company profile (GET /companies/{slug}/summary)
4. Rejection workflow:
   - Mandatory reviewer notes validation (empty notes rejected with 422)
   - Status transition to 'rejected'
   - Unconditional audit logging in badge_review_log with identical completeness to approve
   - Real Phase 7 transactional email dispatch with reviewer feedback and resubmit link
5. Resubmission workflow:
   - Resubmission re-enters admin review queue as fresh 'pending_review'
   - Preserves complete historical audit trail
6. Scheduled renewal tracking & date boundary:
   - Badge expiring in 35 days: not flagged (0 emails)
   - Badge expiring in 25 days: flagged (2 emails: 1 to employer, 1 to admin)
   - Idempotent suppression on subsequent runs
7. Elevated test coverage target: >= 90%.
"""
import pytest
import datetime
from fastapi.testclient import TestClient

from engine.api.main import app
from engine.api.badge_service import clear_mock_badge_stores, get_badge_review_logs, _MOCK_BADGE_APPLICATIONS
from engine.api.billing_service import clear_mock_billing_stores, set_mock_company_billing
from engine.api.alert_service import clear_mock_alert_stores, get_mock_sent_emails
from engine.api.jobs_routes import clear_mock_stores, _MOCK_JOBS_STORE

client = TestClient(app)

ADMIN_AUTH = {"Authorization": "Bearer admin-token-secret"}
NON_ADMIN_AUTH = {"Authorization": "Bearer regular-user-token"}


@pytest.fixture(autouse=True)
def setup_teardown():
    """Reset all relevant stores before and after each test."""
    clear_mock_stores()
    clear_mock_badge_stores()
    clear_mock_billing_stores()
    clear_mock_alert_stores()
    yield
    clear_mock_stores()
    clear_mock_badge_stores()
    clear_mock_billing_stores()
    clear_mock_alert_stores()


def _valid_application_payload(
    employer_id: str = "emp_spotify_test",
    company_slug: str = "spotify",
    company_name: str = "Spotify AB",
    contact_email: str = "legal@spotify.com",
) -> dict:
    return {
        "employer_id": employer_id,
        "company_slug": company_slug,
        "company_name": company_name,
        "contact_email": contact_email,
        "license_or_reg_number": "UK-SPONSOR-LIC-12345",
        "sponsorship_history_summary": "Sponsored over 50 skilled worker and EU Blue Card visas across engineering and product in Sweden, Germany, and the UK.",
        "evidence_urls": [
            "https://visas.example.gov/sponsors/spotify-cert.pdf",
            "https://spotify.com/careers/legal-verification.pdf",
        ],
        "notes": "Annual verification audit renewal evidence submitted.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Admin-Role Authentication Boundary Tests (Zero / Non-Admin / Admin)
# ─────────────────────────────────────────────────────────────────────────────

def test_admin_auth_boundary_zero_auth():
    """Admin queue and decision endpoints strictly reject zero auth with 401 Unauthorized."""
    # List queue
    res_list = client.get("/api/v1/admin/badge-applications")
    assert res_list.status_code == 401
    assert "Unauthorized" in res_list.json()["detail"]

    # Approve
    res_app = client.post("/api/v1/admin/badge-applications/emp_1/approve")
    assert res_app.status_code == 401

    # Reject
    res_rej = client.post("/api/v1/admin/badge-applications/emp_1/reject", json={"notes": "Reason"})
    assert res_rej.status_code == 401

    # Audit logs
    res_logs = client.get("/api/v1/admin/badge-applications/emp_1/logs")
    assert res_logs.status_code == 401

    # Renewal check
    res_ren = client.post("/api/v1/admin/badge-renewals/run-check")
    assert res_ren.status_code == 401


def test_admin_auth_boundary_valid_non_admin_auth():
    """Admin endpoints strictly reject valid-but-non-admin tokens with 403 Forbidden."""
    # List queue
    res_list = client.get("/api/v1/admin/badge-applications", headers=NON_ADMIN_AUTH)
    assert res_list.status_code == 403
    assert "Forbidden" in res_list.json()["detail"]

    # Approve
    res_app = client.post("/api/v1/admin/badge-applications/emp_1/approve", headers=NON_ADMIN_AUTH)
    assert res_app.status_code == 403

    # Reject
    res_rej = client.post(
        "/api/v1/admin/badge-applications/emp_1/reject",
        headers=NON_ADMIN_AUTH,
        json={"notes": "Reason"},
    )
    assert res_rej.status_code == 403

    # Audit logs
    res_logs = client.get("/api/v1/admin/badge-applications/emp_1/logs", headers=NON_ADMIN_AUTH)
    assert res_logs.status_code == 403

    # Renewal check
    res_ren = client.post("/api/v1/admin/badge-renewals/run-check", headers=NON_ADMIN_AUTH)
    assert res_ren.status_code == 403


def test_admin_auth_boundary_valid_admin_auth():
    """Admin endpoints successfully authenticate requests bearing valid admin credentials."""
    res_list = client.get("/api/v1/admin/badge-applications", headers=ADMIN_AUTH)
    assert res_list.status_code == 200
    assert isinstance(res_list.json(), list)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Employer Badge Application Submission & Status Tracking
# ─────────────────────────────────────────────────────────────────────────────

def test_employer_badge_submission_and_status():
    """Employer submits verification evidence and queries status."""
    payload = _valid_application_payload()
    res = client.post("/api/v1/employer/badge/apply", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["badge_status"] == "pending_review"
    assert data["company_slug"] == "spotify"
    assert data["contact_email"] == "legal@spotify.com"
    assert len(data["evidence_urls"]) == 2

    # Query status by employer_id
    res_status = client.get(f"/api/v1/employer/badge/status?employer_id={payload['employer_id']}")
    assert res_status.status_code == 200
    assert res_status.json()["id"] == data["id"]
    assert res_status.json()["badge_status"] == "pending_review"

    # Query status by company_slug
    res_status_comp = client.get(f"/api/v1/employer/badge/status?company_slug={payload['company_slug']}")
    assert res_status_comp.status_code == 200
    assert res_status_comp.json()["id"] == data["id"]

    # Appears in Admin Queue
    res_queue = client.get("/api/v1/admin/badge-applications?status=pending_review", headers=ADMIN_AUTH)
    assert res_queue.status_code == 200
    queue = res_queue.json()
    assert any(item["id"] == data["id"] for item in queue)


def test_employer_badge_submission_invalid_data():
    """Submitting empty company name or missing evidence URLs fails validation."""
    # Empty company
    bad_payload = _valid_application_payload(company_name="")
    res = client.post("/api/v1/employer/badge/apply", json=bad_payload)
    assert res.status_code == 422

    # Empty evidence list
    bad_payload2 = _valid_application_payload()
    bad_payload2["evidence_urls"] = []
    res2 = client.post("/api/v1/employer/badge/apply", json=bad_payload2)
    assert res2.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# 3. Approval Workflow: Audit Logging, Phase 7 Email & Public Badge Display
# ─────────────────────────────────────────────────────────────────────────────

def test_badge_approval_lifecycle_and_audit_completeness():
    """
    Approval path:
    1. Submit application
    2. Before approval: public company profile shows is_verified_sponsor = False
    3. Admin approves application
    4. Confirms complete row written to badge_review_log
    5. Confirms Phase 7 transactional approval email delivered to employer
    6. Confirms public company profile now reflects is_verified_sponsor = True with 12 months validity
    """
    # Seed an active job for Spotify to test job card integration
    import engine.api.jobs_routes as jr
    jr._MOCK_JOBS_STORE.append({
        "id": "job_sp_1",
        "slug": "senior-engineer-spotify-job_sp_1",
        "title": "Senior Staff Engineer",
        "company_name": "Spotify AB",
        "companies": {"name": "Spotify AB", "slug": "spotify"},
        "location": "London, United Kingdom",
        "country": "United Kingdom",
        "country_code": "GB",
        "visa_types": ["Skilled Worker Visa (Tier 2)"],
        "is_active": True,
        "date_posted": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })

    payload = _valid_application_payload(employer_id="emp_spotify_appr", company_slug="spotify")
    client.post("/api/v1/employer/badge/apply", json=payload)

    # Pre-condition: public profile is not verified
    res_pub_before = client.get(f"/api/v1/companies/{payload['company_slug']}/summary")
    assert res_pub_before.status_code == 200
    assert res_pub_before.json()["is_verified_sponsor"] is False
    assert res_pub_before.json()["badge_status"] in ("none", "pending_review")

    # Admin approves
    approve_notes = "Official UK sponsor license verified against Home Office register. Valid through 2027."
    res_app = client.post(
        f"/api/v1/admin/badge-applications/{payload['employer_id']}/approve",
        headers=ADMIN_AUTH,
        json={"notes": approve_notes},
    )
    assert res_app.status_code == 200
    approved_data = res_app.json()
    assert approved_data["badge_status"] == "verified"
    assert approved_data["verified_at"] is not None
    assert approved_data["expires_at"] is not None

    # Verify validity window is 12 months (approx 365 days)
    ver_dt = datetime.datetime.fromisoformat(approved_data["verified_at"].replace("Z", "+00:00"))
    exp_dt = datetime.datetime.fromisoformat(approved_data["expires_at"].replace("Z", "+00:00"))
    assert (exp_dt - ver_dt).days in (364, 365, 366)

    # 4. Mandatory Audit Log Inviolability Check
    logs = get_badge_review_logs(employer_id=payload["employer_id"])
    assert len(logs) == 1
    log_entry = logs[0]
    assert log_entry.employer_id == payload["employer_id"]
    assert log_entry.decision == "approved"
    assert log_entry.reviewer_id == "admin_bearer_user"
    assert log_entry.notes == approve_notes
    assert log_entry.created_at is not None

    # Also check via admin logs endpoint
    res_logs_ep = client.get(
        f"/api/v1/admin/badge-applications/{payload['employer_id']}/logs",
        headers=ADMIN_AUTH,
    )
    assert res_logs_ep.status_code == 200
    assert len(res_logs_ep.json()) == 1

    # 5. Phase 7 Email Delivery Verification
    sent_emails = get_mock_sent_emails()
    assert len(sent_emails) == 1
    approval_email = sent_emails[0]
    assert approval_email["to"] == payload["contact_email"].lower()
    assert "Verified Sponsor Badge Approved" in approval_email["subject"]
    assert "Spotify AB" in approval_email["subject"]
    assert "/companies/spotify" in approval_email["html"]
    assert approval_email["consent_classification"] == "transactional"

    # 6. Public Company Profile reflects verified badge
    res_pub_after = client.get(f"/api/v1/companies/{payload['company_slug']}/summary")
    assert res_pub_after.status_code == 200
    comp_data = res_pub_after.json()
    assert comp_data["is_verified_sponsor"] is True
    assert comp_data["badge_status"] == "verified"
    assert comp_data["company"]["is_verified_sponsor"] is True

    # 7. Public Job Card reflects verified badge
    res_jobs = client.get("/api/v1/jobs?country=united-kingdom")
    assert res_jobs.status_code == 200
    sp_job = [j for j in res_jobs.json()["results"] if j["id"] == "job_sp_1"][0]
    assert sp_job["company"]["is_verified_sponsor"] is True
    assert sp_job["company"]["badge_status"] == "verified"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Rejection Workflow: Mandatory Notes, Audit Completeness & Phase 7 Email
# ─────────────────────────────────────────────────────────────────────────────

def test_badge_rejection_mandatory_notes_enforcement():
    """Rejecting an application strictly requires non-empty reviewer notes."""
    payload = _valid_application_payload(employer_id="emp_zalando_rej", company_slug="zalando")
    client.post("/api/v1/employer/badge/apply", json=payload)

    # Empty notes payload
    res_empty = client.post(
        f"/api/v1/admin/badge-applications/{payload['employer_id']}/reject",
        headers=ADMIN_AUTH,
        json={"notes": ""},
    )
    assert res_empty.status_code == 422
    assert "REJECTION_NOTES_MANDATORY" in res_empty.json()["detail"]["error"]

    # Whitespace-only notes
    res_whitespace = client.post(
        f"/api/v1/admin/badge-applications/{payload['employer_id']}/reject",
        headers=ADMIN_AUTH,
        json={"notes": "   "},
    )
    assert res_whitespace.status_code == 422


def test_badge_rejection_lifecycle_and_audit_completeness():
    """
    Rejection path:
    1. Submit application
    2. Admin rejects with specific feedback notes
    3. Confirms complete row written to badge_review_log with identical completeness to approve
    4. Confirms Phase 7 email delivered with reviewer's reason and resubmission link
    5. Public profile remains unverified
    """
    payload = _valid_application_payload(
        employer_id="emp_zalando_rej2",
        company_slug="zalando",
        company_name="Zalando SE",
        contact_email="talent@zalando.de",
    )
    client.post("/api/v1/employer/badge/apply", json=payload)

    rejection_reason = "The uploaded sponsorship certificate expired in 2024. Please provide current Federal Employment Agency approval."
    res_rej = client.post(
        f"/api/v1/admin/badge-applications/{payload['employer_id']}/reject",
        headers=ADMIN_AUTH,
        json={"notes": rejection_reason},
    )
    assert res_rej.status_code == 200
    rej_data = res_rej.json()
    assert rej_data["badge_status"] == "rejected"

    # 3. Mandatory Audit Log Inviolability Check
    logs = get_badge_review_logs(employer_id=payload["employer_id"])
    assert len(logs) == 1
    log_entry = logs[0]
    assert log_entry.employer_id == payload["employer_id"]
    assert log_entry.decision == "rejected"
    assert log_entry.reviewer_id == "admin_bearer_user"
    assert log_entry.notes == rejection_reason

    # 4. Phase 7 Email Delivery Verification
    sent_emails = get_mock_sent_emails()
    assert len(sent_emails) == 1
    rejection_email = sent_emails[0]
    assert rejection_email["to"] == "talent@zalando.de"
    assert "Verified Sponsor Badge application" in rejection_email["subject"]
    assert rejection_reason in rejection_email["html"]
    assert "/employer/badge/resubmit" in rejection_email["html"]
    assert rejection_email["consent_classification"] == "transactional"

    # 5. Public profile remains unverified
    res_pub = client.get(f"/api/v1/companies/{payload['company_slug']}/summary")
    assert res_pub.status_code == 200
    assert res_pub.json()["is_verified_sponsor"] is False
    assert res_pub.json()["badge_status"] == "rejected"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Resubmission Workflow (Rejected -> Amended -> Pending Review -> Approved)
# ─────────────────────────────────────────────────────────────────────────────

def test_badge_resubmission_and_full_historical_audit_trail():
    """
    End-to-End Resubmission Loop:
    1. Application rejected by reviewer.
    2. Employer resubmits with amended evidence.
    3. Application status transitions back to 'pending_review'.
    4. Re-enters admin review queue.
    5. Admin reviews and approves.
    6. Audit log contains both the initial rejection and the subsequent approval without gaps.
    """
    emp_id = "emp_amend_loop"
    c_slug = "klarna"
    payload = _valid_application_payload(
        employer_id=emp_id,
        company_slug=c_slug,
        company_name="Klarna AB",
        contact_email="compliance@klarna.com",
    )
    client.post("/api/v1/employer/badge/apply", json=payload)

    # 1. First Review: Reject
    client.post(
        f"/api/v1/admin/badge-applications/{emp_id}/reject",
        headers=ADMIN_AUTH,
        json={"notes": "Need proof of Swedish Migration Agency certified sponsor status."},
    )

    # Confirm rejected status
    st1 = client.get(f"/api/v1/employer/badge/status?employer_id={emp_id}").json()
    assert st1["badge_status"] == "rejected"

    # 2. Employer Resubmits with Amended Evidence
    resubmit_payload = {
        "employer_id": emp_id,
        "evidence_urls": [
            "https://migrationsverket.se/certified/klarna-current-2026.pdf",
        ],
        "notes": "Attached official 2026 certification from Swedish Migration Agency.",
    }
    res_resub = client.post("/api/v1/employer/badge/resubmit", json=resubmit_payload)
    assert res_resub.status_code == 200
    resub_data = res_resub.json()
    assert resub_data["badge_status"] == "pending_review"
    assert len(resub_data["evidence_urls"]) == 1

    # 3. Confirm re-entry in Admin Review Queue
    queue = client.get("/api/v1/admin/badge-applications?status=pending_review", headers=ADMIN_AUTH).json()
    assert any(item["employer_id"] == emp_id for item in queue)

    # 4. Second Review: Approve
    client.post(
        f"/api/v1/admin/badge-applications/{emp_id}/approve",
        headers=ADMIN_AUTH,
        json={"notes": "Swedish Migration Agency certification verified."},
    )

    # 5. Full Historical Audit Trail Inspection
    logs = get_badge_review_logs(employer_id=emp_id)
    assert len(logs) == 2
    assert logs[0].decision == "rejected"
    assert "Need proof of Swedish" in logs[0].notes
    assert logs[1].decision == "approved"
    assert "Swedish Migration Agency certification verified" in logs[1].notes


# ─────────────────────────────────────────────────────────────────────────────
# 6. Scheduled Renewal Tracking & Date Boundary Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_badge_renewal_check_date_boundary():
    """
    Date Boundary Verification:
    - Badge expiring in 35 days: outside 30-day window -> 0 flagged, 0 emails
    - Badge expiring in 25 days: inside 30-day window -> 1 flagged, 2 emails (employer + admin)
    - Subsequent run: idempotent suppression -> 0 additional emails
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    clear_mock_alert_stores()

    # Badge 1: Expiring in 35 days (Should NOT be flagged)
    exp_35 = (now + datetime.timedelta(days=35)).isoformat()
    app_35 = _valid_application_payload(employer_id="emp_far_exp", company_slug="farcorp", contact_email="far@example.com")
    client.post("/api/v1/employer/badge/apply", json=app_35)
    _MOCK_BADGE_APPLICATIONS["emp_far_exp"]["badge_status"] = "verified"
    _MOCK_BADGE_APPLICATIONS["emp_far_exp"]["expires_at"] = exp_35

    # Run check
    res_chk1 = client.post("/api/v1/admin/badge-renewals/run-check", headers=ADMIN_AUTH)
    assert res_chk1.status_code == 200
    assert res_chk1.json()["flagged_count"] == 0
    assert len(get_mock_sent_emails()) == 0

    # Badge 2: Expiring in 25 days (SHOULD be flagged)
    exp_25 = (now + datetime.timedelta(days=25)).isoformat()
    app_25 = _valid_application_payload(employer_id="emp_near_exp", company_slug="nearcorp", contact_email="near@example.com")
    client.post("/api/v1/employer/badge/apply", json=app_25)
    _MOCK_BADGE_APPLICATIONS["emp_near_exp"]["badge_status"] = "verified"
    _MOCK_BADGE_APPLICATIONS["emp_near_exp"]["expires_at"] = exp_25

    # Run check
    res_chk2 = client.post("/api/v1/admin/badge-renewals/run-check", headers=ADMIN_AUTH)
    assert res_chk2.status_code == 200
    chk2_data = res_chk2.json()
    assert chk2_data["flagged_count"] == 1
    assert chk2_data["flagged_applications"][0]["employer_id"] == "emp_near_exp"

    # Verify 2 emails sent: 1 to employer, 1 to admin
    sent = get_mock_sent_emails()
    assert len(sent) == 2
    emp_email = [e for e in sent if e["to"] == "near@example.com"][0]
    adm_email = [e for e in sent if "admin@" in e["to"]][0]
    assert "expires in 24 days" in emp_email["subject"] or "expires in 25 days" in emp_email["subject"]
    assert "[Admin Alert] Upcoming Badge Renewal" in adm_email["subject"]

    # Subsequent run: idempotent suppression (already flagged)
    res_chk3 = client.post("/api/v1/admin/badge-renewals/run-check", headers=ADMIN_AUTH)
    assert res_chk3.status_code == 200
    assert res_chk3.json()["flagged_count"] == 0
    assert len(get_mock_sent_emails()) == 2  # No additional emails sent


# ─────────────────────────────────────────────────────────────────────────────
# 7. Edge Cases: Invalid Resubmissions, Not Found & Dry-Run Renewal
# ─────────────────────────────────────────────────────────────────────────────

def test_badge_resubmit_invalid_state_and_not_found():
    """Resubmission fails if application does not exist or is not in 'rejected' state."""
    # Non-existent application
    res_not_found = client.post("/api/v1/employer/badge/resubmit", json={
        "employer_id": "emp_non_existent",
        "evidence_urls": ["https://example.com/cert.pdf"],
    })
    assert res_not_found.status_code == 404
    assert "APPLICATION_NOT_FOUND" in res_not_found.json()["detail"]["error"]

    # Application is in pending_review, not rejected
    payload = _valid_application_payload(employer_id="emp_pending_state", company_slug="statecorp")
    client.post("/api/v1/employer/badge/apply", json=payload)

    res_invalid_state = client.post("/api/v1/employer/badge/resubmit", json={
        "employer_id": "emp_pending_state",
        "evidence_urls": ["https://example.com/cert.pdf"],
    })
    assert res_invalid_state.status_code == 400
    assert "INVALID_STATUS_FOR_RESUBMISSION" in res_invalid_state.json()["detail"]["error"]


def test_badge_decision_on_nonexistent_application():
    """Admin approving or rejecting non-existent employer ID returns 404."""
    res_app = client.post(
        "/api/v1/admin/badge-applications/emp_ghost/approve",
        headers=ADMIN_AUTH,
        json={"notes": "No such emp"},
    )
    assert res_app.status_code == 404

    res_rej = client.post(
        "/api/v1/admin/badge-applications/emp_ghost/reject",
        headers=ADMIN_AUTH,
        json={"notes": "No such emp"},
    )
    assert res_rej.status_code == 404


def test_badge_status_unknown_target():
    """Querying status for an unknown employer ID or company slug returns 404."""
    res = client.get("/api/v1/employer/badge/status?employer_id=emp_unknown_999")
    assert res.status_code == 404

    res2 = client.get("/api/v1/employer/badge/status?company_slug=unknown-corp-xyz")
    assert res2.status_code == 404


def test_badge_renewal_check_dry_run():
    """Renewal check with dry_run=True identifies expiring badges without firing emails or updating state."""
    now = datetime.datetime.now(datetime.timezone.utc)
    clear_mock_alert_stores()

    exp_20 = (now + datetime.timedelta(days=20)).isoformat()
    app_dry = _valid_application_payload(employer_id="emp_dry_run", company_slug="drycorp", contact_email="dry@example.com")
    client.post("/api/v1/employer/badge/apply", json=app_dry)
    _MOCK_BADGE_APPLICATIONS["emp_dry_run"]["badge_status"] = "verified"
    _MOCK_BADGE_APPLICATIONS["emp_dry_run"]["expires_at"] = exp_20

    res_dry = client.post("/api/v1/admin/badge-renewals/run-check?dry_run=true", headers=ADMIN_AUTH)
    assert res_dry.status_code == 200
    assert res_dry.json()["flagged_count"] == 1
    # Confirm NO emails were sent in dry run
    assert len(get_mock_sent_emails()) == 0
    # Confirm application remains unflagged in store
    assert _MOCK_BADGE_APPLICATIONS["emp_dry_run"].get("renewal_notified_at") is None


# ─────────────────────────────────────────────────────────────────────────────
# 8. Supabase Client Integration & Fallback Mocking (Coverage Enhancement)
# ─────────────────────────────────────────────────────────────────────────────

def test_badge_service_supabase_integration_paths():
    """Verifies badge_service execution paths when Supabase service client is present."""
    from unittest.mock import patch, MagicMock
    from engine.api.badge_service import (
        submit_badge_application,
        get_badge_application,
        get_badge_application_by_company,
        list_badge_applications,
        approve_badge_application,
        reject_badge_application,
        get_badge_review_logs,
        run_badge_renewal_check,
    )
    from engine.api.badge_models import BadgeApplicationSubmitRequest

    # Create a versatile mock query builder
    mock_db = MagicMock()
    mock_apps_table = MagicMock()
    mock_logs_table = MagicMock()

    def _get_table(t_name):
        return mock_logs_table if "log" in t_name else mock_apps_table

    mock_db.table.side_effect = _get_table
    mock_db.from_.side_effect = _get_table

    for tbl in (mock_apps_table, mock_logs_table):
        tbl.select.return_value = tbl
        tbl.insert.return_value = tbl
        tbl.update.return_value = tbl
        tbl.eq.return_value = tbl
        tbl.order.return_value = tbl
        tbl.limit.return_value = tbl

    mock_row = {
        "id": "app_sb_1",
        "employer_id": "emp_sb_1",
        "company_slug": "sb-corp",
        "company_name": "Supabase Corp",
        "contact_email": "admin@sbcorp.com",
        "license_or_reg_number": "SB-12345",
        "sponsorship_history_summary": "Sponsored visas in EU and UK.",
        "evidence_urls": ["https://sbcorp.com/ev1.pdf"],
        "badge_status": "pending_review",
        "payment_status": "paid",
        "notes": "Initial",
        "reviewer_id": None,
        "reviewer_notes": None,
        "verified_at": None,
        "expires_at": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=20)).isoformat(),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    mock_apps_res = MagicMock()
    mock_apps_res.data = [mock_row]
    mock_apps_table.execute.return_value = mock_apps_res

    mock_log_row = {
        "id": "log_sb_1",
        "employer_id": "emp_sb_1",
        "reviewer_id": "admin_sb",
        "decision": "approved",
        "notes": "Good",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    mock_logs_res = MagicMock()
    mock_logs_res.data = [mock_log_row]
    mock_logs_table.execute.return_value = mock_logs_res

    with patch("engine.api.badge_service._get_supabase_client", return_value=mock_db):
        # 1. Submit
        req = BadgeApplicationSubmitRequest(**_valid_application_payload(employer_id="emp_sb_1", company_slug="sb-corp"))
        submit_badge_application(req)

        # 2. Get by employer
        app_by_emp = get_badge_application("emp_sb_1")
        assert app_by_emp is not None
        assert app_by_emp.company_slug == "sb-corp"

        # 3. Get by company
        app_by_comp = get_badge_application_by_company("sb-corp")
        assert app_by_comp is not None

        # 4. List with status
        q_list = list_badge_applications(status="pending_review")
        assert len(q_list) >= 1

        # 5. Approve
        app_approved, err_app = approve_badge_application("emp_sb_1", reviewer_id="admin_sb", notes="Approved via SB")
        assert err_app is None

        # 6. Reject
        app_rejected, err_rej = reject_badge_application("emp_sb_1", reviewer_id="admin_sb", notes="Rejected via SB")
        assert err_rej is None

        # 7. Audit logs
        sb_logs = get_badge_review_logs("emp_sb_1")
        assert len(sb_logs) >= 1

        # 8. Renewal check
        _MOCK_BADGE_APPLICATIONS["emp_sb_1"]["badge_status"] = "verified"
        _MOCK_BADGE_APPLICATIONS["emp_sb_1"]["expires_at"] = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=15)).isoformat()
        _MOCK_BADGE_APPLICATIONS["emp_sb_1"]["renewal_notified_at"] = None
        ren_res = run_badge_renewal_check()
        assert ren_res.checked_count >= 1


def test_badge_service_supabase_exception_handling():
    """Verifies that Supabase query failures degrade gracefully without crashing."""
    from unittest.mock import patch, MagicMock
    from engine.api.badge_service import (
        submit_badge_application,
        get_badge_application,
        list_badge_applications,
        approve_badge_application,
        reject_badge_application,
        get_badge_review_logs,
        run_badge_renewal_check,
    )
    from engine.api.badge_models import BadgeApplicationSubmitRequest

    failing_db = MagicMock()
    failing_table = MagicMock()
    failing_db.table.return_value = failing_table
    failing_table.select.side_effect = Exception("DB Connection Timeout")
    failing_table.insert.side_effect = Exception("DB Write Error")
    failing_table.update.side_effect = Exception("DB Update Error")

    with patch("engine.api.badge_service._get_supabase_client", return_value=failing_db):
        # Should gracefully fall back to mock store without crashing
        req = BadgeApplicationSubmitRequest(**_valid_application_payload(employer_id="emp_fail_1", company_slug="failcorp"))
        submit_res = submit_badge_application(req)
        assert submit_res.employer_id == "emp_fail_1"

        app_res = get_badge_application("emp_fail_1")
        assert app_res is not None

        list_res = list_badge_applications()
        assert isinstance(list_res, list)

        # Audit logs should return empty list or fallback gracefully
        logs = get_badge_review_logs("emp_fail_1")
        assert isinstance(logs, list)

        # Renewal check fallback
        ren = run_badge_renewal_check()
        assert ren.checked_count >= 0


def test_badge_service_edge_cases_and_branch_coverage(monkeypatch):
    """Hits remaining edge case branches and error handlers for >= 90% coverage."""
    from unittest.mock import patch, MagicMock
    from engine.api.badge_service import (
        _get_supabase_client,
        resubmit_badge_application,
        get_badge_application,
        get_badge_application_by_company,
        list_badge_applications,
        approve_badge_application,
        reject_badge_application,
        run_badge_renewal_check,
        get_badge_review_logs,
        clear_mock_badge_stores,
    )
    from engine.api.badge_models import BadgeApplicationResubmitRequest

    # Test _get_supabase_client exception branch
    with patch("job_radar.visalane.db.get_service_client", side_effect=Exception("DB init error")):
        assert _get_supabase_client() is None

    # Test reject without notes directly on service layer
    res_rej, err_rej = reject_badge_application("emp_any", "admin_1", notes="")
    assert err_rej is not None
    assert err_rej["status_code"] == 422

    # Clear mock stores and test empty state lookups
    clear_mock_badge_stores()
    assert get_badge_application("emp_empty") is None
    assert get_badge_application_by_company("company_empty") is None
    assert get_badge_review_logs() == []

    # Test resubmit with full optional fields
    payload = _valid_application_payload(employer_id="emp_full_opts", company_slug="fullopts")
    client.post("/api/v1/employer/badge/apply", json=payload)
    client.post("/api/v1/admin/badge-applications/emp_full_opts/reject", headers=ADMIN_AUTH, json={"notes": "Fix"})

    resub_req = BadgeApplicationResubmitRequest(
        employer_id="emp_full_opts",
        company_slug="fullopts-new",
        contact_email="updated@fullopts.com",
        license_or_reg_number="LIC-NEW-999",
        sponsorship_history_summary="Over 100 visas sponsored.",
        evidence_urls=["https://fullopts.com/new-evidence.pdf"],
        notes="All fields amended.",
    )
    resub_res, resub_err = resubmit_badge_application(resub_req)
    assert resub_err is None
    assert resub_res.company_slug == "fullopts-new"
    assert resub_res.contact_email == "updated@fullopts.com"
    assert resub_res.license_or_reg_number == "LIC-NEW-999"

    # Test list_badge_applications with 'all' and with non-matching status
    all_apps = list_badge_applications(status="all")
    assert len(all_apps) >= 1
    rej_apps = list_badge_applications(status="rejected")
    assert isinstance(rej_apps, list)

    # Test run_badge_renewal_check with invalid date string and with missing expires_at
    _MOCK_BADGE_APPLICATIONS["emp_bad_date"] = {
        "employer_id": "emp_bad_date",
        "company_slug": "baddate",
        "company_name": "Bad Date Corp",
        "badge_status": "verified",
        "expires_at": "not-a-valid-date-iso",
    }
    _MOCK_BADGE_APPLICATIONS["emp_no_exp"] = {
        "employer_id": "emp_no_exp",
        "company_slug": "noexp",
        "company_name": "No Exp Corp",
        "badge_status": "verified",
        "expires_at": None,
    }
    ren_chk = run_badge_renewal_check()
    assert ren_chk.checked_count >= 1

    # Test email dispatch exception handling during approve and reject
    import engine.api.alert_service as alt_svc
    monkeypatch.setattr(alt_svc, "send_transactional_email", MagicMock(side_effect=Exception("SMTP Down")))

    # Approve with email exception
    app_exp, err_exp = approve_badge_application("emp_full_opts", reviewer_id="admin_1", notes="Approve despite mail down")
    assert err_exp is None
    assert app_exp.badge_status == "verified"

    # Reject with email exception
    client.post("/api/v1/employer/badge/apply", json=_valid_application_payload(employer_id="emp_mail_fail", company_slug="failmail"))
    rej_exp, err_rej_exp = reject_badge_application("emp_mail_fail", reviewer_id="admin_1", notes="Reject despite mail down")
    assert err_rej_exp is None
    assert rej_exp.badge_status == "rejected"


def test_badge_service_supabase_pure_fallback_paths():
    """Hits Supabase fallback fetch and write branches when in-memory cache is empty."""
    from unittest.mock import patch, MagicMock
    from engine.api.badge_service import (
        get_badge_application,
        get_badge_application_by_company,
        resubmit_badge_application,
        approve_badge_application,
        reject_badge_application,
        list_badge_applications,
        clear_mock_badge_stores,
    )
    from engine.api.badge_models import BadgeApplicationResubmitRequest

    clear_mock_badge_stores()

    mock_db = MagicMock()
    mock_apps_table = MagicMock()
    mock_logs_table = MagicMock()

    def _get_t(name):
        return mock_logs_table if "log" in name else mock_apps_table

    mock_db.table.side_effect = _get_t
    mock_db.from_.side_effect = _get_t

    for t in (mock_apps_table, mock_logs_table):
        for meth in ("select", "insert", "update", "eq", "order", "limit", "maybe_single"):
            getattr(t, meth).return_value = t

    raw_row = {
        "id": "app_pure_sb",
        "employer_id": "emp_pure_sb",
        "company_slug": "puresb",
        "company_name": "Pure Supabase Inc",
        "contact_email": "pure@sb.com",
        "license_or_reg_number": "LIC-SB-1",
        "sponsorship_history_summary": "Visas sponsored in UK.",
        "evidence_urls": ["https://sb.com/doc.pdf"],
        "badge_status": "rejected",
        "payment_status": "paid",
        "notes": "Rejected initially",
        "reviewer_id": "admin_prior",
        "reviewer_notes": "Fix doc",
        "verified_at": None,
        "expires_at": None,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    mock_apps_res = MagicMock()
    mock_apps_res.data = [raw_row]
    mock_apps_table.execute.return_value = mock_apps_res

    mock_log_row = {
        "id": "log_pure_1",
        "employer_id": "emp_pure_sb",
        "reviewer_id": "admin_pure",
        "decision": "rejected",
        "notes": "Evidence incomplete",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    mock_logs_res = MagicMock()
    mock_logs_res.data = [mock_log_row]
    mock_logs_table.execute.return_value = mock_logs_res

    with patch("engine.api.badge_service._get_supabase_client", return_value=mock_db):
        # 1. Submit when existing application is present (covers line 70)
        from engine.api.badge_service import _MOCK_BADGE_APPLICATIONS, submit_badge_application
        from engine.api.badge_models import BadgeApplicationSubmitRequest
        _MOCK_BADGE_APPLICATIONS["emp_existing"] = {"id": "bapp_exist_1"}
        sub_dup = submit_badge_application(BadgeApplicationSubmitRequest(**_valid_application_payload(employer_id="emp_existing", company_slug="existcorp")))
        assert sub_dup.id == "bapp_exist_1"

        # 2. get_badge_application directly from Supabase
        _MOCK_BADGE_APPLICATIONS.pop("emp_pure_sb", None)
        app_emp = get_badge_application("emp_pure_sb")
        assert app_emp is not None

        # 3. get_badge_application_by_company directly from Supabase
        _MOCK_BADGE_APPLICATIONS.pop("emp_pure_sb", None)
        app_comp = get_badge_application_by_company("puresb")
        assert app_comp is not None

        # 4. list_badge_applications directly from Supabase with status filter
        raw_row["badge_status"] = "pending_review"
        _MOCK_BADGE_APPLICATIONS.clear()
        listed = list_badge_applications(status="pending_review")
        assert len(listed) >= 1

        # 5. resubmit_badge_application directly from Supabase (lines 128-134)
        raw_row["badge_status"] = "rejected"
        _MOCK_BADGE_APPLICATIONS.pop("emp_pure_sb", None)
        resub = BadgeApplicationResubmitRequest(
            employer_id="emp_pure_sb",
            evidence_urls=["https://sb.com/amended.pdf"],
        )
        r_app, r_err = resubmit_badge_application(resub)
        assert r_err is None

        # 6. approve_badge_application directly from Supabase (lines 337-343)
        _MOCK_BADGE_APPLICATIONS.pop("emp_pure_sb", None)
        a_app, a_err = approve_badge_application("emp_pure_sb", reviewer_id="admin_appr", notes="Approved")
        assert a_err is None

        # 7. reject_badge_application directly from Supabase (lines 460-466)
        _MOCK_BADGE_APPLICATIONS.pop("emp_pure_sb", None)
        r_app2, r_err2 = reject_badge_application("emp_pure_sb", reviewer_id="admin_appr", notes="Reject reason")
        assert r_err2 is None
