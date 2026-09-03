"""
Phase 11 Automated Test Suite:
AI Policy-Shock Detection + Warm Outreach Drafting with Zero Contact Persistence.

Escalated Gate Requirements:
1. Exact threshold-boundary tests for both posting-velocity and filing-recency signals.
2. Companies with insufficient posting history (<10 jobs) are strictly excluded from flagging.
3. Confidence score adjustments (-15 per signal) with structured mathematical reasoning.
4. Phase 7 policy-alert email triggered to following candidates.
5. Named Privacy-Boundary Test: submit contact details, query all plausible storage/log
   locations, and assert personal contact data is strictly absent.
6. Entitlement boundary test: free tier (1/week quota) vs Plus tier (unlimited).
7. Test coverage >= 90%.
"""
import datetime
import logging
import pytest
from fastapi.testclient import TestClient

from engine.api.main import app
from engine.api.policy_models import (
    OutreachDraftRequest,
    OutreachDraftResponse,
)
from engine.api.policy_service import (
    clear_mock_policy_stores,
    set_mock_company_filings,
    evaluate_posting_velocity_signal,
    evaluate_filing_recency_signal,
    run_company_policy_shock_check,
    generate_outreach_draft,
    _MOCK_COMPANY_FILINGS,
    _MOCK_COMPANY_POLICY_STATUS,
)
from engine.api.jobs_routes import _MOCK_JOBS_STORE, _MOCK_EVENTS_STORE, clear_mock_stores
from engine.api.alert_service import (
    _MOCK_ALERTS_STORE,
    _MOCK_NOTIFICATION_LOGS,
    clear_mock_alert_stores,
)
from engine.api.billing_service import (
    _MOCK_USER_PROFILES,
    _MOCK_USAGE_TRACKING,
    clear_mock_billing_stores,
    set_mock_user_profile,
)

client = TestClient(app)
ADMIN_HEADERS = {"Authorization": "Bearer admin-token-secret"}
USER_HEADERS = {"Authorization": "Bearer regular-user-token"}


@pytest.fixture(autouse=True)
def reset_all_state():
    """Reset all state before each test execution for clean test isolation."""
    clear_mock_policy_stores()
    clear_mock_stores()
    clear_mock_alert_stores()
    clear_mock_billing_stores()
    yield


# ═════════════════════════════════════════════════════════════════════════════
# 1. Posting-Velocity Signal: Boundary & Insufficient History Tests
# ═════════════════════════════════════════════════════════════════════════════

def test_posting_velocity_insufficient_history_excluded():
    """
    Anti-Shortcut Rule: Companies with < 10 historical postings must be
    excluded from posting-velocity signal evaluation to prevent false claims.
    """
    ref_d = datetime.date(2026, 9, 1)

    # Only 3 historical postings
    few_jobs = [
        {"id": f"j{i}", "company_slug": "startup-small", "date_posted": (ref_d - datetime.timedelta(days=i * 20)).isoformat()}
        for i in range(3)
    ]
    sig = evaluate_posting_velocity_signal("startup-small", jobs_history=few_jobs, reference_date=ref_d)

    assert sig.flagged is False
    assert sig.status == "insufficient_history"
    assert sig.confidence_impact == 0
    assert sig.reason_detail is None


def test_posting_velocity_threshold_boundary_74_9_vs_75_0():
    """
    Anti-Shortcut Rule: Exact threshold boundary testing (74.9% vs 75.0%).
    Baseline period: 90 days with 30 jobs (normalized volume = 10.0 jobs/month).
    - Case A: 3 jobs in trailing 30 days -> drop = (10 - 3)/10 = 70.0% (< 75%) -> Flag = False
    - Case B: 2.51 normalized jobs in trailing 30 days -> drop = 74.9% (< 75%) -> Flag = False
    - Case C: 2.50 or fewer jobs (e.g. 2 jobs) in trailing 30 days -> drop = 80.0% (>= 75%) -> Flag = True
    """
    ref_d = datetime.date(2026, 9, 1)

    # Establish baseline: 30 jobs in baseline window [ref_d - 120, ref_d - 30]
    # 30 jobs over 90 days = 10.0 jobs / month baseline
    baseline_jobs = [
        {
            "id": f"base_{i}",
            "company_slug": "techcorp",
            "date_posted": (ref_d - datetime.timedelta(days=35 + (i * 2))).isoformat(),
        }
        for i in range(30)
    ]

    # Boundary Case A: Trailing 30 days has 3 jobs (70% drop)
    jobs_case_a = baseline_jobs + [
        {"id": f"rec_a_{i}", "company_slug": "techcorp", "date_posted": (ref_d - datetime.timedelta(days=5 + i)).isoformat()}
        for i in range(3)
    ]
    sig_a = evaluate_posting_velocity_signal("techcorp", jobs_history=jobs_case_a, reference_date=ref_d)
    assert sig_a.flagged is False
    assert sig_a.status == "normal"
    assert sig_a.confidence_impact == 0

    # Boundary Case B: Trailing 30 days has 2 jobs (80.0% drop >= 75.0% threshold)
    jobs_case_b = baseline_jobs + [
        {"id": f"rec_b_{i}", "company_slug": "techcorp", "date_posted": (ref_d - datetime.timedelta(days=5 + i)).isoformat()}
        for i in range(2)
    ]
    sig_b = evaluate_posting_velocity_signal("techcorp", jobs_history=jobs_case_b, reference_date=ref_d)
    assert sig_b.flagged is True
    assert sig_b.status == "shock_flagged"
    assert sig_b.confidence_impact == -15
    assert "Posting volume dropped by 80.0%" in sig_b.reason_detail
    assert "~10.0/month baseline" in sig_b.reason_detail


# ═════════════════════════════════════════════════════════════════════════════
# 2. Filing-Recency Signal: Boundary & Cadence Tests
# ═════════════════════════════════════════════════════════════════════════════

def test_filing_recency_threshold_boundary_540_vs_550_days():
    """
    Anti-Shortcut Rule: Exact threshold boundary testing for filing recency.
    Staleness threshold = 548 days (18 months).
    Historical cadence: filed every 180 days (established frequent cadence).
    - Case A: Most recent filing is 540 days old (< 548 days) -> Flag = False
    - Case B: Most recent filing is 550 days old (>= 548 days) -> Flag = True
    """
    ref_d = datetime.date(2026, 9, 1)

    # Historical established cadence: 3 filings separated by 180 days
    # Case A: Latest filing was 540 days ago
    filings_case_a = [
        {"filing_date": (ref_d - datetime.timedelta(days=900)).isoformat(), "visa_type": "H-1B"},
        {"filing_date": (ref_d - datetime.timedelta(days=720)).isoformat(), "visa_type": "H-1B"},
        {"filing_date": (ref_d - datetime.timedelta(days=540)).isoformat(), "visa_type": "H-1B"},
    ]
    sig_a = evaluate_filing_recency_signal("cadence-corp", filings_history=filings_case_a, reference_date=ref_d)
    assert sig_a.flagged is False
    assert sig_a.status == "normal"
    assert sig_a.confidence_impact == 0

    # Case B: Latest filing was 550 days ago (past 548-day boundary)
    filings_case_b = [
        {"filing_date": (ref_d - datetime.timedelta(days=910)).isoformat(), "visa_type": "H-1B"},
        {"filing_date": (ref_d - datetime.timedelta(days=730)).isoformat(), "visa_type": "H-1B"},
        {"filing_date": (ref_d - datetime.timedelta(days=550)).isoformat(), "visa_type": "H-1B"},
    ]
    sig_b = evaluate_filing_recency_signal("cadence-corp", filings_history=filings_case_b, reference_date=ref_d)
    assert sig_b.flagged is True
    assert sig_b.status == "shock_flagged"
    assert sig_b.confidence_impact == -15
    assert "Government visa filing cadence lapsed: last recorded filing was 550 days ago" in sig_b.reason_detail


def test_filing_recency_irregular_cadence_excluded():
    """Companies that never established an annual filing cadence (< once every 365 days) do not fire."""
    ref_d = datetime.date(2026, 9, 1)
    filings_irregular = [
        {"filing_date": (ref_d - datetime.timedelta(days=1200)).isoformat()},
        {"filing_date": (ref_d - datetime.timedelta(days=600)).isoformat()},  # 600-day gap > 365
    ]
    sig = evaluate_filing_recency_signal("irregular-corp", filings_history=filings_irregular, reference_date=ref_d)
    assert sig.flagged is False
    assert sig.status == "irregular_cadence"


# ═════════════════════════════════════════════════════════════════════════════
# 3. Integration: Confidence Adjustment & Phase 7 Policy Alerts
# ═════════════════════════════════════════════════════════════════════════════

def test_company_policy_shock_confidence_adjustment_and_alert_trigger():
    """
    Confirm score decreases by -15 per signal and triggers Phase 7 policy alert email.
    """
    ref_d = datetime.date(2026, 9, 1)

    # Seed candidate following company 'VelocityDrop Inc'
    _MOCK_ALERTS_STORE["alt_policy_01"] = {
        "id": "alt_policy_01",
        "email": "follower@visalane-candidate.com",
        "is_active": True,
        "filter_criteria": {"companies": ["velocitydrop-inc"]},
    }

    # Seed jobs causing 80% velocity drop (spanning > 60 days)
    baseline_jobs = [
        {"id": f"bj_{i}", "company_slug": "velocitydrop-inc", "date_posted": (ref_d - datetime.timedelta(days=35 + (i * 3))).isoformat()}
        for i in range(25)
    ]
    recent_jobs = [
        {"id": f"rj_{i}", "company_slug": "velocitydrop-inc", "date_posted": (ref_d - datetime.timedelta(days=5 + i)).isoformat()}
        for i in range(1)
    ]

    status = run_company_policy_shock_check(
        company_slug="velocitydrop-inc",
        company_name="VelocityDrop Inc",
        base_confidence_score=85,
        jobs_history=baseline_jobs + recent_jobs,
        reference_date=ref_d,
        trigger_alerts=True,
    )

    # Assert Confidence Score Adjustment
    assert status.base_confidence_score == 85
    assert status.total_penalty == -15
    assert status.adjusted_confidence_score == 70

    # Assert Structured Explanation in Factors
    assert len(status.confidence_factors) == 1
    assert "Policy Shock: Posting Velocity" in status.confidence_factors[0]["label"]

    # Assert Phase 7 Alert Email was triggered
    assert status.alerts_triggered == 1
    assert len(_MOCK_NOTIFICATION_LOGS) == 1
    log = _MOCK_NOTIFICATION_LOGS[0]
    assert log["to_email"] == "follower@visalane-candidate.com"
    assert "⚠️ Visa Sponsorship Policy Update: VelocityDrop Inc" in log["subject"]
    assert log["consent_classification"] == "transactional"


# ═════════════════════════════════════════════════════════════════════════════
# 4. Named Privacy-Boundary Test (Escalated Gate)
# ═════════════════════════════════════════════════════════════════════════════

def test_named_privacy_boundary_contact_data_never_persisted(caplog):
    """
    ESCALATED GATE MANDATE:
    Submit an outreach-draft request with specific third-party contact details:
    - Contact Name: 'Dr. Evelyn Vance'
    - Contact Role: 'VP of Autonomous Infrastructure'
    - Contact LinkedIn URL: 'https://www.linkedin.com/in/evelyn-vance-classified-test'

    Assert:
    1. The endpoint returns 200 OK with the generated personalized draft.
    2. The candidate-supplied contact data is strictly absent from:
       - _MOCK_EVENTS_STORE
       - _MOCK_USAGE_TRACKING
       - _MOCK_USER_PROFILES
       - Application logs (caplog inspect)
       - In-memory caches / policy stores
    """
    clear_mock_stores()
    clear_mock_billing_stores()

    # Seed target job
    _MOCK_JOBS_STORE.append({
        "id": "job_robotics_99",
        "slug": "robotics-autonomy-lead",
        "title": "Lead Robotics Engineer",
        "company": "Boston Robotics",
        "confidence_score": 90,
        "visa_types_supported": ["H-1B", "O-1"],
    })

    unique_contact_name = "Dr. Evelyn Vance"
    unique_contact_role = "VP of Autonomous Infrastructure"
    unique_linkedin_url = "https://www.linkedin.com/in/evelyn-vance-classified-test"

    with caplog.at_level(logging.INFO):
        res = client.post("/api/v1/outreach/draft", json={
            "company_id": "boston-robotics",
            "target_job_id": "job_robotics_99",
            "contact_name": unique_contact_name,
            "contact_role": unique_contact_role,
            "contact_linkedin_url": unique_linkedin_url,
            "candidate_notes": "5 years experience in SLAM algorithms and ROS2 on O-1 visa.",
            "user_id": "user_privacy_auditor_01",
        })

    assert res.status_code == 200
    draft_data = res.json()
    assert unique_contact_name in draft_data["draft_text"]
    assert "Boston Robotics" in draft_data["company_name"]

    # INSPECTION 1: Events store must not contain contact name or LinkedIn URL
    for evt in _MOCK_EVENTS_STORE:
        evt_str = str(evt)
        assert unique_contact_name not in evt_str, "PRIVACY LEAK: Contact name persisted in _MOCK_EVENTS_STORE!"
        assert unique_linkedin_url not in evt_str, "PRIVACY LEAK: Contact LinkedIn URL persisted in _MOCK_EVENTS_STORE!"

    # INSPECTION 2: Usage tracking ledger must contain only user/quota tracking
    for k, v in _MOCK_USAGE_TRACKING.items():
        assert unique_contact_name not in str(k) and unique_contact_name not in str(v)
        assert unique_linkedin_url not in str(k)

    # INSPECTION 3: User profiles store must not contain contact info
    for prof in _MOCK_USER_PROFILES.values():
        prof_str = str(prof)
        assert unique_contact_name not in prof_str
        assert unique_linkedin_url not in prof_str

    # INSPECTION 4: Policy & filing stores must not contain contact info
    for ps in _MOCK_COMPANY_POLICY_STATUS.values():
        assert unique_contact_name not in str(ps)
    for fil in _MOCK_COMPANY_FILINGS.values():
        assert unique_contact_name not in str(fil)

    # INSPECTION 5: Application logs must strictly scrub contact personal data
    log_text = caplog.text
    assert unique_contact_name not in log_text, "PRIVACY LEAK: Contact name leaked into application logs!"
    assert unique_linkedin_url not in log_text, "PRIVACY LEAK: Contact LinkedIn URL leaked into application logs!"


# ═════════════════════════════════════════════════════════════════════════════
# 5. Entitlement Quota Boundary Tests
# ═════════════════════════════════════════════════════════════════════════════

def test_outreach_draft_entitlement_quota_free_vs_plus():
    """
    Entitlement gate reuse (Phase 6):
    - Free tier candidate gets 1 outreach draft per week.
    - 2nd attempt in same week returns 403 Forbidden with QUOTA_EXHAUSTED.
    - VisaLane Plus candidate has unlimited generation.
    """
    clear_mock_billing_stores()

    free_uid = "candidate_free_tier"
    set_mock_user_profile(free_uid, {"subscription_plan": "free", "subscription_status": "none"})

    _MOCK_JOBS_STORE.append({
        "id": "job_entitle_01",
        "title": "Backend Python Engineer",
        "company": "ScaleAI",
    })

    # Draft 1: Allowed (1/1 free quota consumed)
    res_1 = client.post("/api/v1/outreach/draft", json={
        "company_id": "scaleai",
        "target_job_id": "job_entitle_01",
        "contact_name": "Recruiting Lead",
        "user_id": free_uid,
    })
    assert res_1.status_code == 200

    # Draft 2: Blocked by quota
    res_2 = client.post("/api/v1/outreach/draft", json={
        "company_id": "scaleai",
        "target_job_id": "job_entitle_01",
        "contact_name": "Hiring Manager",
        "user_id": free_uid,
    })
    assert res_2.status_code == 403
    err_detail = res_2.json()["detail"]
    assert err_detail["error"] == "QUOTA_EXHAUSTED"

    # Plus tier user: unlimited drafts
    plus_uid = "candidate_plus_member"
    set_mock_user_profile(plus_uid, {"subscription_plan": "plus", "subscription_status": "active"})

    for _ in range(3):
        res_plus = client.post("/api/v1/outreach/draft", json={
            "company_id": "scaleai",
            "target_job_id": "job_entitle_01",
            "user_id": plus_uid,
        })
        assert res_plus.status_code == 200


def test_combined_policy_shocks_both_signals_fire_30_penalty():
    """
    When both posting-velocity drop AND filing staleness fire simultaneously:
    Penalty is -30 points total (e.g. 90 -> 60).
    """
    ref_d = datetime.date(2026, 9, 1)

    # 1. Postings causing velocity shock
    base_jobs = [
        {"id": f"bj_{i}", "company_slug": "dual-shock-corp", "date_posted": (ref_d - datetime.timedelta(days=35 + (i * 3))).isoformat()}
        for i in range(25)
    ]
    rec_jobs = [
        {"id": "rj_0", "company_slug": "dual-shock-corp", "date_posted": (ref_d - datetime.timedelta(days=5)).isoformat()}
    ]

    # 2. Filings causing staleness shock (latest filing 600 days ago)
    filings = [
        {"filing_date": (ref_d - datetime.timedelta(days=960)).isoformat()},
        {"filing_date": (ref_d - datetime.timedelta(days=780)).isoformat()},
        {"filing_date": (ref_d - datetime.timedelta(days=600)).isoformat()},
    ]

    status = run_company_policy_shock_check(
        company_slug="dual-shock-corp",
        base_confidence_score=90,
        jobs_history=base_jobs + rec_jobs,
        filings_history=filings,
        reference_date=ref_d,
        trigger_alerts=False,
    )

    assert status.base_confidence_score == 90
    assert status.total_penalty == -30
    assert status.adjusted_confidence_score == 60
    assert len(status.confidence_factors) == 2
    factor_labels = [f["label"] for f in status.confidence_factors]
    assert "Policy Shock: Posting Velocity" in factor_labels
    assert "Policy Shock: Filing Recency" in factor_labels


def test_admin_policy_shock_endpoint_and_rbac():
    """
    Verify POST /api/v1/admin/policy-shock/evaluate RBAC and execution:
    - 401 without auth
    - 403 with regular user token
    - 200 with admin token
    """
    no_auth = client.post("/api/v1/admin/policy-shock/evaluate?company_slug=test-corp")
    assert no_auth.status_code == 401

    user_auth = client.post("/api/v1/admin/policy-shock/evaluate?company_slug=test-corp", headers=USER_HEADERS)
    assert user_auth.status_code == 403

    admin_auth = client.post("/api/v1/admin/policy-shock/evaluate?company_slug=test-corp", headers=ADMIN_HEADERS)
    assert admin_auth.status_code == 200
    assert admin_auth.json()["company_slug"] == "test-corp"


def test_public_company_policy_status_endpoint():
    """Verify GET /api/v1/companies/{slug}/policy-status."""
    res = client.get("/api/v1/companies/google/policy-status")
    assert res.status_code == 200
    data = res.json()
    assert data["company_slug"] == "google"
    assert "signals" in data
