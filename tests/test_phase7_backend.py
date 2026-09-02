"""
VisaLane Phase 7 Backend Test Suite.
Verifies the Alert & Lifecycle Notification Engine:
- Alert CRUD with entitlement-aware cadence enforcement (Free tier vs Plus tier)
- Job matching engine and zero-match suppression (never sending empty digests)
- Multi-channel dispatch (Email + Telegram bot)
- Token-based one-click unsubscriptions and preference center
- Lifecycle email sequences with GDPR/CAN-SPAM consent classification (transactional vs marketing)
- Permanent regression test: Unsubscribing suppresses all subsequent scheduled digest runs
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient

from engine.api.main import app
from engine.api.alert_models import AlertFilterCriteria
from engine.api.alert_service import (
    clear_mock_alert_stores,
    create_telegram_link_token,
    dispatch_email_notification,
    dispatch_telegram_alert,
    generate_unsubscribe_token,
    get_mock_notification_logs,
    get_mock_sent_emails,
    get_mock_telegram_messages,
    match_job_against_criteria,
    notify_instant_alerts_for_new_job,
    process_unsubscribe,
    run_scheduled_alert_digests,
    validate_cadence_entitlement,
    verify_unsubscribe_token,
)
from engine.api.billing_service import clear_mock_billing_stores, set_mock_user_profile
from engine.api.jobs_routes import ADMIN_SECRET_KEY, clear_mock_stores, limiter

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_alert_test_state():
    """Reset all in-memory mock stores before each test."""
    clear_mock_alert_stores()
    clear_mock_billing_stores()
    clear_mock_stores()
    try:
        limiter.reset()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 1. Matching Logic & Filter Engine Unit Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_matching_logic_country_and_visa_type():
    """Verify job matching on country and visa type."""
    criteria = AlertFilterCriteria(country="germany", visa_type="eu-blue-card")

    # Match: Germany + EU Blue Card
    job_match = {
        "id": "j-match-1",
        "title": "Senior Go Engineer",
        "country": "Germany",
        "country_code": "DE",
        "visa_sponsorship_type": "EU Blue Card",
        "status": "active",
    }
    assert match_job_against_criteria(job_match, criteria) is True

    # Non-match: UK
    job_uk = {
        "id": "j-uk-2",
        "title": "Senior Go Engineer",
        "country": "United Kingdom",
        "country_code": "GB",
        "visa_sponsorship_type": "EU Blue Card",
        "status": "active",
    }
    assert match_job_against_criteria(job_uk, criteria) is False

    # Non-match: Germany with Skilled Worker (non-Blue Card)
    job_other_visa = {
        "id": "j-visa-3",
        "title": "Senior Go Engineer",
        "country": "Germany",
        "country_code": "DE",
        "visa_sponsorship_type": "Working Holiday",
        "status": "active",
    }
    assert match_job_against_criteria(job_other_visa, criteria) is False


def test_matching_logic_keyword_remote_and_salary():
    """Verify keyword search, remote eligibility, and minimum salary filtering."""
    criteria = AlertFilterCriteria(
        keyword="Kubernetes",
        is_remote=True,
        min_salary=80000,
        min_confidence=90,
    )

    # Match: title contains Kubernetes, remote, 95k salary, 95% confidence
    valid_job = {
        "id": "j-k8s-1",
        "title": "Staff Platform Engineer (Kubernetes)",
        "description": "Scale multi-cluster deployments.",
        "is_remote": True,
        "salary_min": 85000,
        "salary_max": 110000,
        "visa_sponsorship_confidence": 95,
        "status": "active",
    }
    assert match_job_against_criteria(valid_job, criteria) is True

    # Fail: In-office only
    office_job = dict(valid_job, is_remote=False, workplace_type="on_site")
    assert match_job_against_criteria(office_job, criteria) is False

    # Fail: Low salary
    low_sal_job = dict(valid_job, salary_min=60000, salary_max=75000)
    assert match_job_against_criteria(low_sal_job, criteria) is False

    # Fail: Low confidence
    low_conf_job = dict(valid_job, visa_sponsorship_confidence=80)
    assert match_job_against_criteria(low_conf_job, criteria) is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. Entitlement Enforcement on Alert Cadence
# ─────────────────────────────────────────────────────────────────────────────

def test_cadence_entitlement_free_vs_plus():
    """
    Verify cadence entitlement:
    - Free user requesting 'instant' is rejected (403) or downgraded with explanation
    - Free user requesting 'daily' or 'weekly' is accepted
    - Plus user requesting 'instant' is accepted
    """
    free_user = "usr_free_cadence_tester"
    plus_user = "usr_plus_cadence_tester"
    set_mock_user_profile(plus_user, {"subscription_plan": "plus", "subscription_status": "active"})

    # 1. Free user requesting instant without downgrade option -> Rejected
    ok_free, cad_free, reason_free = validate_cadence_entitlement(free_user, "instant", downgrade_to_daily=False)
    assert ok_free is False
    assert "Instant alerts require an active VisaLane Plus membership" in reason_free

    # 2. Free user requesting instant with downgrade_to_daily=True -> Downgraded
    ok_down, cad_down, reason_down = validate_cadence_entitlement(free_user, "instant", downgrade_to_daily=True)
    assert ok_down is True
    assert cad_down == "daily"
    assert "automatically set to 'daily'" in reason_down

    # 3. Plus user requesting instant -> Allowed
    ok_plus, cad_plus, reason_plus = validate_cadence_entitlement(plus_user, "instant", downgrade_to_daily=False)
    assert ok_plus is True
    assert cad_plus == "instant"
    assert reason_plus is None

    # 4. Free user requesting daily or weekly -> Allowed
    ok_daily, cad_d, _ = validate_cadence_entitlement(free_user, "daily")
    ok_weekly, cad_w, _ = validate_cadence_entitlement(free_user, "weekly")
    assert ok_daily is True and cad_d == "daily"
    assert ok_weekly is True and cad_w == "weekly"


def test_api_alert_create_entitlement_rejection_and_downgrade():
    """Test HTTP POST /api/v1/alerts boundary behaviors on cadence entitlement."""
    free_user = "usr_api_free_candidate"

    # Case A: Free user requesting instant -> 403 INSTANT_CADENCE_RESTRICTED
    payload_instant = {
        "email": "free_user@example.com",
        "user_id": free_user,
        "cadence": "instant",
        "filter_criteria": {"country": "germany"},
    }
    res_reject = client.post("/api/v1/alerts", json=payload_instant)
    assert res_reject.status_code == 403
    err_data = res_reject.json()["detail"]
    assert err_data["error"] == "INSTANT_CADENCE_RESTRICTED"
    assert "upgrade_url" in err_data

    # Case B: Free user requesting instant with downgrade_to_daily=True -> 201 Created with downgraded=True
    payload_downgrade = dict(payload_instant, downgrade_to_daily=True)
    res_down = client.post("/api/v1/alerts", json=payload_downgrade)
    assert res_down.status_code == 201
    down_data = res_down.json()
    assert down_data["cadence"] == "daily"
    assert down_data["downgraded"] is True
    assert "automatically set to 'daily'" in down_data["downgrade_reason"]

    # Case C: Plus user requesting instant -> 201 Created with cadence=instant
    plus_user = "usr_api_plus_candidate"
    set_mock_user_profile(plus_user, {"subscription_plan": "plus", "subscription_status": "active"})
    payload_plus = dict(payload_instant, user_id=plus_user)
    res_plus = client.post("/api/v1/alerts", json=payload_plus)
    assert res_plus.status_code == 201
    assert res_plus.json()["cadence"] == "instant"
    assert res_plus.json()["downgraded"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 3. Alert CRUD Endpoints
# ─────────────────────────────────────────────────────────────────────────────

def test_alert_crud_lifecycle():
    """Verify full CRUD lifecycle: Create, List, Patch, and Delete alert."""
    email = "candidate_crud@example.com"
    user_id = "usr_crud_123"

    # 1. Create
    create_body = {
        "email": email,
        "user_id": user_id,
        "filter_criteria": {"country": "united-kingdom", "keyword": "Python"},
        "cadence": "daily",
        "channels": ["email"],
    }
    res_c = client.post("/api/v1/alerts", json=create_body)
    assert res_c.status_code == 201
    created = res_c.json()
    alert_id = created["id"]
    assert created["email"] == email
    assert created["is_active"] is True

    # 2. List
    res_l = client.get(f"/api/v1/alerts?user_id={user_id}")
    assert res_l.status_code == 200
    list_data = res_l.json()
    assert list_data["total_count"] == 1
    assert list_data["alerts"][0]["id"] == alert_id

    # 3. Patch criteria and cadence
    patch_body = {
        "cadence": "weekly",
        "filter_criteria": {"country": "germany", "keyword": "Rust"},
    }
    res_p = client.patch(f"/api/v1/alerts/{alert_id}?user_id={user_id}", json=patch_body)
    assert res_p.status_code == 200
    updated = res_p.json()
    assert updated["cadence"] == "weekly"
    assert updated["filter_criteria"]["country"] == "germany"
    assert updated["filter_criteria"]["keyword"] == "Rust"

    # 4. Delete (Deactivate)
    res_d = client.delete(f"/api/v1/alerts/{alert_id}?user_id={user_id}")
    assert res_d.status_code == 200
    assert res_d.json()["success"] is True

    # Confirm list is now empty
    res_after = client.get(f"/api/v1/alerts?user_id={user_id}")
    assert res_after.json()["total_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Zero-Match Suppression Rule & Scheduled Digest Runner
# ─────────────────────────────────────────────────────────────────────────────

def test_zero_match_suppression_rule():
    """
    Verify CRITICAL RULE: An alert with 0 new matching jobs sends NOTHING.
    Never sends an empty digest.
    """
    # Create an alert for Ireland Python jobs
    alert_payload = {
        "email": "zero_match_tester@example.com",
        "cadence": "daily",
        "filter_criteria": {"country": "ireland", "keyword": "Python"},
    }
    client.post("/api/v1/alerts", json=alert_payload)

    # Job dataset has Germany Go jobs (0 matches for Ireland Python)
    jobs_store = [
        {
            "id": "j-ger-1",
            "title": "Senior Go Engineer",
            "country": "Germany",
            "country_code": "DE",
            "status": "active",
        }
    ]

    res = run_scheduled_alert_digests(cadence="daily", all_jobs=jobs_store)
    assert res.alerts_evaluated == 1
    assert res.digests_sent == 0
    assert res.alerts_suppressed_zero_matches == 1
    assert len(get_mock_sent_emails()) == 0

    # Confirm audit log records suppressed status
    logs = get_mock_notification_logs()
    assert len(logs) == 1
    assert logs[0]["status"] == "suppressed"
    assert logs[0]["reason"] == "zero_matches"


def test_scheduled_digest_successful_dispatch():
    """Verify scheduled digest sends email when new matching jobs exist."""
    alert_payload = {
        "email": "digest_recipient@example.com",
        "cadence": "daily",
        "filter_criteria": {"country": "germany"},
    }
    client.post("/api/v1/alerts", json=alert_payload)

    jobs_store = [
        {
            "id": "j-de-1",
            "title": "Lead Visa Developer",
            "company_name": "Berlin Tech Labs",
            "country": "Germany",
            "country_code": "DE",
            "visa_sponsorship_type": "EU Blue Card",
            "status": "active",
        }
    ]

    res = run_scheduled_alert_digests(cadence="daily", all_jobs=jobs_store)
    assert res.alerts_evaluated == 1
    assert res.digests_sent == 1
    assert res.alerts_suppressed_zero_matches == 0

    emails = get_mock_sent_emails()
    assert len(emails) == 1
    sent = emails[0]
    assert sent["to"] == "digest_recipient@example.com"
    assert "1 new verified visa sponsorship role in Germany" in sent["subject"]
    assert "Berlin Tech Labs" in sent["html"]
    assert "List-Unsubscribe" in sent["headers"]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Telegram Integration & /link Flow
# ─────────────────────────────────────────────────────────────────────────────

def test_telegram_link_and_alert_dispatch():
    """Verify Telegram link token creation, webhook binding, and alert card dispatch."""
    email = "telegram_candidate@example.com"
    user_id = "usr_tg_123"

    # 1. Create alert with telegram channel
    client.post(
        "/api/v1/alerts",
        json={
            "email": email,
            "user_id": user_id,
            "cadence": "daily",
            "channels": ["email", "telegram"],
            "filter_criteria": {"country": "germany"},
        },
    )

    # 2. Request Link Token
    res_tok = client.post(f"/api/v1/alerts/telegram/link-token?email={email}&user_id={user_id}")
    assert res_tok.status_code == 200
    token_info = res_tok.json()
    token = token_info["token"]
    assert token_info["bot_username"] == "VisaLaneBot"
    assert f"/link {token}" in token_info["link_command"]

    # 3. Simulate Candidate sending /link {token} in Telegram
    tg_update = {
        "update_id": 10001,
        "message": {
            "message_id": 1,
            "chat": {"id": 987654321, "type": "private"},
            "from": {"id": 987654321, "first_name": "Alex"},
            "text": f"/link {token}",
        },
    }
    res_hook = client.post("/api/v1/alerts/telegram/webhook", json=tg_update)
    assert res_hook.status_code == 200
    assert res_hook.json()["action"] == "linked"

    # 4. Dispatch Telegram opportunity card
    test_jobs = [
        {
            "id": "j-tg-01",
            "title": "Senior AI Architect",
            "company_name": "Turing Visa AI",
            "country": "Germany",
            "visa_sponsorship_confidence": 98,
        }
    ]
    tg_ok = dispatch_telegram_alert(chat_id="987654321", jobs=test_jobs)
    assert tg_ok is True

    messages = get_mock_telegram_messages()
    assert len(messages) == 1
    assert messages[0]["chat_id"] == "987654321"
    assert "Senior AI Architect" in messages[0]["text"]
    assert "Turing Visa AI" in messages[0]["text"]


# ─────────────────────────────────────────────────────────────────────────────
# 6. Unsubscribe & Preference Center Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_token_based_unsubscribe_and_preferences():
    """Verify one-click token generation, verification, and preference center endpoints."""
    email = "unsub_tester@example.com"
    token = generate_unsubscribe_token(email, "alert_999")

    # 1. Verify token
    verified = verify_unsubscribe_token(token)
    assert verified is not None
    assert verified[0] == email
    assert verified[1] == "alert_999"

    # 2. Tampered token fails
    assert verify_unsubscribe_token("invalid_tampered_token:foo:bar") is None

    # 3. Browser GET /api/v1/alerts/unsubscribe -> HTML page returned
    res_page = client.get(f"/api/v1/alerts/unsubscribe?token={token}")
    assert res_page.status_code == 200
    assert "text/html" in res_page.headers["content-type"]
    assert "Unsubscribe Successful" in res_page.text

    # 4. Programmatic POST /api/v1/alerts/unsubscribe for marketing
    res_unsub_mkt = client.post(
        "/api/v1/alerts/unsubscribe",
        json={"token": token, "scope": "all_marketing"},
    )
    assert res_unsub_mkt.status_code == 200
    assert res_unsub_mkt.json()["scope"] == "all_marketing"

    # 5. Preference Center GET
    res_pref = client.get(f"/api/v1/alerts/preferences?email={email}")
    assert res_pref.status_code == 200
    assert res_pref.json()["marketing_opt_out"] is True


def test_consent_classification_marketing_suppression():
    """
    Verify GDPR/CAN-SPAM consent classification:
    When a recipient has marketing_opt_out=True:
    - Marketing sequences (Welcome, Re-engagement, Winback) are SUPPRESSED.
    - Transactional notifications (Job alerts, Policy updates) SUCCEED.
    """
    email = "optout_candidate@example.com"

    # Set marketing opt-out
    client.put(
        "/api/v1/alerts/preferences",
        json={"email": email, "marketing_opt_out": True},
    )

    # 1. Dispatch marketing email -> Suppressed
    mkt_dispatched = dispatch_email_notification(
        to_email=email,
        subject="Welcome to VisaLane",
        html_content="<p>Welcome</p>",
        consent_classification="marketing",
    )
    assert mkt_dispatched is False

    # 2. Dispatch transactional alert -> Succeeded
    tx_dispatched = dispatch_email_notification(
        to_email=email,
        subject="Your VisaLane Daily Digest",
        html_content="<p>Jobs</p>",
        consent_classification="transactional",
    )
    assert tx_dispatched is True


# ─────────────────────────────────────────────────────────────────────────────
# 7. PERMANENT REGRESSION TEST: Unsubscribe Suppresses Scheduled Runs
# ─────────────────────────────────────────────────────────────────────────────

def test_permanent_regression_unsubscribe_suppresses_subsequent_runs():
    """
    PERMANENT REGRESSION TEST:
    1. Create an active alert.
    2. Click the token-based unsubscribe link.
    3. Verify alert flag is_active flips to False.
    4. Trigger subsequent scheduled digest run.
    5. Confirm ZERO emails are dispatched to that alert/recipient.
    """
    email = "regression_target@example.com"
    create_res = client.post(
        "/api/v1/alerts",
        json={
            "email": email,
            "cadence": "daily",
            "filter_criteria": {"country": "germany"},
        },
    )
    alert_id = create_res.json()["id"]

    # Initial Run -> Email sent
    jobs_store = [
        {"id": "j-reg-1", "title": "Software Engineer", "country": "Germany", "status": "active"}
    ]
    res1 = run_scheduled_alert_digests(cadence="daily", all_jobs=jobs_store)
    assert res1.digests_sent == 1
    assert len(get_mock_sent_emails()) == 1

    # Execute Unsubscribe via Token
    unsub_token = generate_unsubscribe_token(email, alert_id)
    unsub_res = client.post(
        "/api/v1/alerts/unsubscribe",
        json={"token": unsub_token, "alert_id": alert_id, "scope": "alert_only"},
    )
    assert unsub_res.status_code == 200

    # Verify is_active flag in database flipped to False
    res_list = client.get(f"/api/v1/alerts?email={email}")
    alerts = res_list.json()["alerts"]
    target_alert = next(a for a in alerts if a["id"] == alert_id)
    assert target_alert["is_active"] is False

    # Trigger Second Scheduled Run -> MUST BE COMPLETELY SUPPRESSED
    clear_mock_alert_stores()
    # Re-insert the deactivated alert to test scheduler evaluation
    from engine.api.alert_service import _MOCK_ALERTS_STORE
    _MOCK_ALERTS_STORE[alert_id] = target_alert

    res2 = run_scheduled_alert_digests(cadence="daily", all_jobs=jobs_store)
    assert res2.alerts_evaluated == 0  # Ignored inactive alert
    assert res2.digests_sent == 0
    assert len(get_mock_sent_emails()) == 0  # ZERO new emails sent!


# ─────────────────────────────────────────────────────────────────────────────
# 8. Lifecycle Sequences & Edge Case Coverage Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_lifecycle_email_sequences_rendering():
    """Verify rendering of all 5 lifecycle email sequences."""
    from engine.api.alert_service import (
        _render_welcome_email,
        _render_reengagement_email,
        _render_winback_email,
        _render_policy_alert_email,
    )
    email = "lifecycle_test@example.com"

    # 1. Welcome Series (Steps 1, 2, 3)
    s1, h1 = _render_welcome_email(email, step=1)
    s2, h2 = _render_welcome_email(email, step=2)
    s3, h3 = _render_welcome_email(email, step=3)
    assert "Welcome to VisaLane" in s1 and "Journey Starts Here" in s1
    assert "Spot Real Visa Sponsors" in s2 and "Self-Sponsor Scams" in s2
    assert "2026 Salary Thresholds" in s3 and "Relocation Guide" in s3
    assert "Unsubscribe from marketing" in h1 and "Unsubscribe from marketing" in h2

    # 2. Re-engagement Email
    s_re, h_re = _render_reengagement_email(email, {"id": "alt_123"})
    assert "New sponsorship activity on your saved VisaLane search" in s_re
    assert "Fresh verified roles" in h_re

    # 3. Winback Emails (30, 60, 90 days)
    s_wb30, h_wb30 = _render_winback_email(email, days_inactive=30)
    s_wb60, h_wb60 = _render_winback_email(email, days_inactive=60)
    assert "30 days of new sponsorship jobs" in s_wb30
    assert "60 days of new sponsorship jobs" in s_wb60

    # 4. Policy Alert Email
    s_pol, h_pol = _render_policy_alert_email(email, "Siemens AG", "Added to German Fast-Track Skilled Immigration Registry")
    assert "Sponsorship Policy Update: Siemens AG" in s_pol
    assert "Siemens AG" in h_pol
    assert "Fast-Track" in h_pol


def test_instant_alert_hook_for_new_job():
    """Verify notify_instant_alerts_for_new_job hook with active instant Plus alert."""
    plus_user = "usr_instant_hook_user"
    set_mock_user_profile(plus_user, {"subscription_plan": "plus", "subscription_status": "active"})

    # Create active instant alert
    res_c = client.post(
        "/api/v1/alerts",
        json={
            "email": "instant_applicant@example.com",
            "user_id": plus_user,
            "cadence": "instant",
            "channels": ["email", "telegram"],
            "telegram_chat_id": "tg_chat_instant_99",
            "filter_criteria": {"country": "germany", "keyword": "Go"},
        },
    )
    assert res_c.status_code == 201

    # New job matching criteria
    matching_new_job = {
        "id": "j-instant-001",
        "title": "Senior Go Backend Architect",
        "company_name": "Stripe Payments Europe",
        "country": "Germany",
        "country_code": "DE",
        "visa_sponsorship_type": "EU Blue Card",
        "status": "active",
    }

    count = notify_instant_alerts_for_new_job(matching_new_job)
    assert count == 1

    # Verify email and telegram messages dispatched immediately
    emails = get_mock_sent_emails()
    assert len(emails) == 1
    assert "Instant Match: Senior Go Backend Architect" in emails[0]["subject"]

    tg_msgs = get_mock_telegram_messages()
    assert len(tg_msgs) == 1
    assert "Senior Go Backend Architect" in tg_msgs[0]["text"]


def test_scheduled_digest_weekly_and_timestamp_filtering():
    """Verify weekly cadence and skipping jobs created before last_notified_at."""
    email = "weekly_user@example.com"
    client.post(
        "/api/v1/alerts",
        json={
            "email": email,
            "cadence": "weekly",
            "filter_criteria": {"country": "germany"},
        },
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    old_time = (now - datetime.timedelta(days=10)).isoformat()
    new_time = (now - datetime.timedelta(hours=2)).isoformat()

    jobs = [
        {"id": "j-old", "title": "Old Job", "country": "Germany", "created_at": old_time, "status": "active"},
        {"id": "j-new", "title": "New Job", "country": "Germany", "created_at": new_time, "status": "active"},
    ]

    # Set last_notified_at to 5 days ago
    from engine.api.alert_service import _MOCK_ALERTS_STORE
    for a in _MOCK_ALERTS_STORE.values():
        a["last_notified_at"] = (now - datetime.timedelta(days=5)).isoformat()

    res = run_scheduled_alert_digests(cadence="weekly", all_jobs=jobs)
    assert res.digests_sent == 1
    emails = get_mock_sent_emails()
    assert len(emails) == 1
    assert "1 new verified visa sponsorship role in Germany" in emails[0]["subject"]
    assert "New Job" in emails[0]["html"]
    assert "Old Job" not in emails[0]["html"]


def test_unsubscribe_all_notifications_and_preferences_edge_cases():
    """Verify process_unsubscribe scope=all_notifications and fallback handling."""
    email = "full_unsub@example.com"
    client.post("/api/v1/alerts", json={"email": email, "cadence": "daily", "filter_criteria": {}})
    client.post("/api/v1/alerts", json={"email": email, "cadence": "weekly", "filter_criteria": {}})

    token = generate_unsubscribe_token(email)
    ok, msg, u_email = process_unsubscribe(token, scope="all_notifications")
    assert ok is True
    assert "all 2 alert(s)" in msg

    # Re-check alerts in list -> all deactivated
    alerts = client.get(f"/api/v1/alerts?email={email}").json()["alerts"]
    assert all(a["is_active"] is False for a in alerts)


def test_telegram_webhook_start_and_error_cases():
    """Verify Telegram webhook handling for deep links and invalid tokens."""
    # 1. /start with invalid token
    res_bad = client.post(
        "/api/v1/alerts/telegram/webhook",
        json={"update_id": 1, "message": {"text": "/start invalid_tok", "chat": {"id": 123}}},
    )
    assert res_bad.status_code == 200
    assert res_bad.json()["action"] == "invalid_token"

    # 2. Unknown message ignored
    res_ign = client.post(
        "/api/v1/alerts/telegram/webhook",
        json={"update_id": 2, "message": {"text": "hello bot", "chat": {"id": 123}}},
    )
    assert res_ign.status_code == 200
    assert res_ign.json()["action"] == "ignored"


def test_admin_run_digest_endpoint():
    """Verify POST /api/v1/admin/alerts/run-digest security and invocation."""
    # 1. No auth -> 401
    res_no = client.post("/api/v1/admin/alerts/run-digest")
    assert res_no.status_code == 401

    # 2. Non-admin auth -> 403
    res_user = client.post(
        "/api/v1/admin/alerts/run-digest",
        headers={"Authorization": "Bearer regular-user-token"},
    )
    assert res_user.status_code == 403

    # 3. Admin auth -> 200
    res_admin = client.post(
        "/api/v1/admin/alerts/run-digest?cadence=daily&dry_run=true",
        headers={"X-Admin-Key": ADMIN_SECRET_KEY},
    )
    assert res_admin.status_code == 200
    data = res_admin.json()
    assert data["cadence"] == "daily"


def test_alert_service_coverage_boost():
    """Targeted coverage tests for edge cases and branch completeness."""
    from unittest.mock import patch, MagicMock
    from engine.api.alert_service import (
        _MOCK_ALERTS_STORE,
        _MOCK_TELEGRAM_LINK_TOKENS,
        consume_telegram_link_token,
        create_alert,
        delete_alert,
        dispatch_email_notification,
        dispatch_telegram_alert,
        get_alert,
        get_user_preferences,
        notify_instant_alerts_for_new_job,
        process_unsubscribe,
        run_scheduled_alert_digests,
        update_alert,
        verify_unsubscribe_token,
    )
    from engine.api.alert_models import AlertCreateRequest, AlertUpdateRequest

    # 1. verify_unsubscribe_token bad format
    assert verify_unsubscribe_token("not:enough:parts:here:foo") is None
    assert verify_unsubscribe_token("") is None

    # 2. consume_telegram_link_token expired
    _MOCK_TELEGRAM_LINK_TOKENS["exp_tok"] = {
        "email": "exp@test.com",
        "user_id": "u_exp",
        "expires_at": "2020-01-01T00:00:00+00:00",
    }
    assert consume_telegram_link_token("exp_tok", "123") is None

    # 3. get_alert not found & delete_alert not found / forbidden
    assert get_alert("non_existent_id") is None
    assert delete_alert("non_existent_id") is False

    # Create an alert with user_id
    alert_res, _ = create_alert(
        AlertCreateRequest(
            email="owner@test.com",
            user_id="user_owner",
            cadence="daily",
        )
    )
    a_id = alert_res.id

    # Forbidden delete
    assert delete_alert(a_id, user_id="user_attacker") is False

    # Forbidden update
    up_res, up_err = update_alert(a_id, AlertUpdateRequest(cadence="weekly"), user_id="user_attacker")
    assert up_res is None
    assert up_err["error"] == "FORBIDDEN"

    # Update not found
    up_res404, up_err404 = update_alert("missing_alert", AlertUpdateRequest(cadence="weekly"))
    assert up_err404["error"] == "ALERT_NOT_FOUND"

    # Update cadence to instant as free user -> rejected
    up_res_inst, up_err_inst = update_alert(a_id, AlertUpdateRequest(cadence="instant", downgrade_to_daily=False), user_id="user_owner")
    assert up_res_inst is None
    assert up_err_inst["error"] == "INSTANT_CADENCE_RESTRICTED"

    # Update cadence to instant with downgrade
    up_res_down, _ = update_alert(a_id, AlertUpdateRequest(cadence="instant", downgrade_to_daily=True), user_id="user_owner")
    assert up_res_down.cadence == "daily"
    assert up_res_down.downgraded is True

    # 4. dispatch_telegram_alert empty chat or empty jobs
    assert dispatch_telegram_alert("", [{"id": 1}]) is False
    assert dispatch_telegram_alert("123", []) is False

    # 5. notify_instant_alerts_for_new_job inactive or draft job
    assert notify_instant_alerts_for_new_job({"status": "draft"}) == 0

    # 6. process_unsubscribe fallback with no active alerts
    assert process_unsubscribe(generate_unsubscribe_token("unknown_email@test.com"))[0] is True

    # 7. Category and non-canonical filter matching
    crit_cat = AlertFilterCriteria(role_category="Engineering", country="zz-unknown", visa_type="unknown-visa")
    assert match_job_against_criteria({"title": "Engineering Manager", "category": "Engineering", "status": "active"}, crit_cat) is False

    # 8. Live email dispatch with mocked Resend API
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        with patch.dict("os.environ", {"RESEND_API_KEY": "re_live_test_key", "EMAIL_FROM": "alerts@visalane.com"}):
            ok = dispatch_email_notification("live@example.com", "Test Subject", "<p>Hi</p>", "transactional")
            assert ok is True

    # 9. Live telegram dispatch with mocked requests
    with patch("requests.post") as mock_tg_post:
        mock_tg_resp = MagicMock()
        mock_tg_resp.status_code = 200
        mock_tg_post.return_value = mock_tg_resp

        with patch("engine.api.alert_service.TELEGRAM_BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"):
            ok_tg = dispatch_telegram_alert("987654", [{"title": "Job", "id": 1}])
            assert ok_tg is True
