"""
Phase 12 Automated Test Suite:
Partnership & Affiliate Infrastructure.

Requirements & Gates:
1. Redirect service tests: correct destination & appended params for 2 real partner configs.
2. Rapid repeated clicks de-duplication test (confirm attribution doesn't double-count or corrupt).
3. Partner referral code survival through full multi-step signup flow (not single-step).
4. Unrelated affiliate click immunity (first-touch referral code never overwritten).
5. Admin report accuracy test against a hand-constructed known test set.
6. Admin RBAC boundary tests (401, 403, 200).
7. Test coverage >= 90%.
"""
from __future__ import annotations

import datetime
import pytest
from fastapi.testclient import TestClient

from engine.api.main import app
from engine.api.partner_service import (
    clear_mock_partner_stores,
    get_affiliate_partner_by_slug,
    record_affiliate_click,
    validate_referral_code,
    capture_landing_referral_code,
    get_session_referral_code,
    lock_user_partner_referral,
    signup_step1,
    signup_step2,
    signup_complete,
    generate_partner_report,
    _MOCK_AFFILIATE_CLICKS,
    _MOCK_USER_PARTNER_ATTRIBUTIONS,
)
from engine.api.jobs_routes import _MOCK_EVENTS_STORE, clear_mock_stores
from engine.api.alert_service import _MOCK_ALERTS_STORE, clear_mock_alert_stores
from engine.api.billing_service import _MOCK_USER_PROFILES, clear_mock_billing_stores

client = TestClient(app, follow_redirects=False)
ADMIN_HEADERS = {"Authorization": "Bearer admin-token-secret"}
USER_HEADERS = {"Authorization": "Bearer regular-user-token"}


@pytest.fixture(autouse=True)
def reset_all_stores():
    """Reset all application stores before each test for clean isolation."""
    clear_mock_partner_stores()
    clear_mock_stores()
    clear_mock_alert_stores()
    clear_mock_billing_stores()
    yield


# ═════════════════════════════════════════════════════════════════════════════
# 1. Affiliate Redirect Service: Destination & Tracking Parameters
# ═════════════════════════════════════════════════════════════════════════════

def test_affiliate_redirect_destination_and_params_for_two_real_partners():
    """
    Test affiliate redirect service for 2 real partner configurations:
    1. Revolut International Banking (slug: 'revolut-expat')
    2. Cigna Global Health (slug: 'cigna-global')
    Verifies 307 Temporary Redirect, correct destination URL, and injected tracking params.
    """
    session_alpha = "sess_globetrotter_01"

    # Partner 1: Revolut Banking
    res_revolut = client.get(f"/go/revolut-expat?session_id={session_alpha}")
    assert res_revolut.status_code == 307
    loc_revolut = res_revolut.headers["location"]
    assert "https://revolut.com/promo/global-talent" in loc_revolut
    assert f"visalane_session={session_alpha}" in loc_revolut
    assert "utm_source=visalane" in loc_revolut
    assert "utm_medium=affiliate" in loc_revolut

    # Partner 2: Cigna Health Insurance
    res_cigna = client.get(f"/go/cigna-global?session_id={session_alpha}")
    assert res_cigna.status_code == 307
    loc_cigna = res_cigna.headers["location"]
    assert "https://cignaglobal.com/expat-plans" in loc_cigna
    assert f"aff_sub={session_alpha}" in loc_cigna
    assert "ref=visalane" in loc_cigna


def test_affiliate_redirect_via_api_v1_prefix_and_404_for_unknown():
    """Verify redirect also works on /api/v1/go/{slug} and returns 404 for unknown partner."""
    res_api = client.get("/api/v1/go/revolut-expat?session_id=sess_test_99")
    assert res_api.status_code == 307

    res_404 = client.get("/go/non-existent-partner")
    assert res_404.status_code == 404


# ═════════════════════════════════════════════════════════════════════════════
# 2. Rapid Repeated Clicks De-duplication Test
# ═════════════════════════════════════════════════════════════════════════════

def test_rapid_repeated_clicks_debounce_and_unique_tally():
    """
    Anti-Shortcut Rule:
    Simulate rapid 5 repeated clicks in a row from the exact same session on the same link.
    Confirm attribution doesn't corrupt or inflate unique click volume.
    """
    session_id = "sess_rapid_clicker_101"
    partner_slug = "revolut-expat"

    # 5 Rapid clicks within debounce threshold
    for i in range(5):
        res = client.get(f"/go/{partner_slug}?session_id={session_id}")
        assert res.status_code == 307

    # Inspect recorded click events
    revolut_clicks = [c for c in _MOCK_AFFILIATE_CLICKS if c.partner_id == "aff_revolut_expat"]
    assert len(revolut_clicks) == 5

    # Exactly 1 unique click, remaining 4 tagged as duplicate
    unique_clicks = [c for c in revolut_clicks if not c.is_duplicate]
    duplicate_clicks = [c for c in revolut_clicks if c.is_duplicate]

    assert len(unique_clicks) == 1
    assert len(duplicate_clicks) == 4

    # Admin report shows unique_clicks = 1, total_clicks = 5
    report = generate_partner_report("aff_revolut_expat")
    assert report.total_clicks == 5
    assert report.unique_clicks == 1


# ═════════════════════════════════════════════════════════════════════════════
# 3. Multi-Step Signup Flow & Referral Code Survival
# ═════════════════════════════════════════════════════════════════════════════

def test_referral_code_survives_full_multistep_signup_flow():
    """
    Anti-Shortcut Rule:
    Capture partner referral code on landing, carry it through Step 1, Step 2,
    and Step 3 (completion). Confirm referred_by_partner_code is locked onto the created user.
    """
    session_id = "sess_multistep_candidate_007"
    ref_code = "FRAGOMEN2026"

    # 1. Step 1: Initial landing with referral code and credentials
    res_step1 = client.post("/api/v1/auth/signup/step1", json={
        "session_id": session_id,
        "email": "candidate.maria@gmail.com",
        "password": "SecurePassword2026!",
        "referral_code": ref_code,
    })
    assert res_step1.status_code == 200
    s1 = res_step1.json()
    assert s1["current_step"] == 1
    assert s1["referred_by_partner_code"] == ref_code

    # 2. Step 2: Visa status and career preferences
    res_step2 = client.post("/api/v1/auth/signup/step2", json={
        "session_id": session_id,
        "visa_status": "F-1 OPT",
        "target_role": "Machine Learning Engineer",
    })
    assert res_step2.status_code == 200
    s2 = res_step2.json()
    assert s2["current_step"] == 2
    assert s2["referred_by_partner_code"] == ref_code  # Carried through!

    # 3. Step 3: Account creation finalization
    res_complete = client.post("/api/v1/auth/signup/complete", json={
        "session_id": session_id,
        "full_name": "Maria Hernandez",
    })
    assert res_complete.status_code == 200
    comp = res_complete.json()
    assert comp["current_step"] == 3
    assert comp["status"] == "account_created"
    assert comp["referred_by_partner_code"] == ref_code

    created_uid = comp["user_id"]
    assert created_uid is not None

    # Verify user profile in billing/account store has locked partner code
    user_prof = _MOCK_USER_PROFILES[created_uid]
    assert user_prof["referred_by_partner_code"] == ref_code

    # Verify event store contains user_signed_up with referral code metadata
    signup_events = [e for e in _MOCK_EVENTS_STORE if e["event_name"] == "user_signed_up" and e["user_id"] == created_uid]
    assert len(signup_events) == 1
    assert signup_events[0]["metadata"]["referred_by_partner_code"] == ref_code


def test_invalid_referral_code_and_step_validation_errors():
    """Verify invalid referral code handling and out-of-order step execution."""
    val = validate_referral_code("INVALID_CODE_123")
    assert val.valid is False

    # Calling step 2 without step 1 fails with 400
    res = client.post("/api/v1/auth/signup/step2", json={
        "session_id": "sess_unstarted",
        "visa_status": "H-1B",
        "target_role": "DevOps",
    })
    assert res.status_code == 400

    # Calling complete without step 2 fails with 400
    res_c = client.post("/api/v1/auth/signup/complete", json={
        "session_id": "sess_unstarted",
        "full_name": "Ghost User",
    })
    assert res_c.status_code == 400


# ═════════════════════════════════════════════════════════════════════════════
# 4. Cross-Partner Collision & First-Touch Attribution Immunity
# ═════════════════════════════════════════════════════════════════════════════

def test_unrelated_affiliate_click_does_not_overwrite_partner_referral():
    """
    Protocol 5 Verification:
    Candidate lands with Partner A's referral code ('SPRINGBOARD_VISA').
    Before completing registration, candidate clicks through Partner B's affiliate link ('revolut-expat').
    Candidate completes signup.
    Confirm referral attribution remains strictly locked to Partner A ('SPRINGBOARD_VISA').
    """
    session_id = "sess_cross_partner_candidate"

    # Step 1: Start signup with Partner A code
    client.post("/api/v1/auth/signup/step1", json={
        "session_id": session_id,
        "email": "alex.dev@visalane.com",
        "password": "Password123!",
        "referral_code": "SPRINGBOARD_VISA",
    })

    # Middle action: Click unrelated affiliate link (Revolut)
    res_click = client.get(f"/go/revolut-expat?session_id={session_id}")
    assert res_click.status_code == 307

    # Step 2 & Complete
    client.post("/api/v1/auth/signup/step2", json={
        "session_id": session_id,
        "visa_status": "O-1A",
        "target_role": "Staff Software Engineer",
    })
    res_comp = client.post("/api/v1/auth/signup/complete", json={
        "session_id": session_id,
        "full_name": "Alex Mercer",
    })
    assert res_comp.status_code == 200
    user_id = res_comp.json()["user_id"]

    # Confirm user attribution is still locked to SPRINGBOARD_VISA, NOT overwritten by Revolut
    assert _MOCK_USER_PARTNER_ATTRIBUTIONS[user_id] == "SPRINGBOARD_VISA"

    # Attempt to re-lock attribution with a different code (must be rejected/ignored)
    re_locked = lock_user_partner_referral(user_id, referral_code="FRAGOMEN2026")
    assert re_locked == "SPRINGBOARD_VISA"  # Remains original first-touch code!


# ═════════════════════════════════════════════════════════════════════════════
# 5. Admin Report Accuracy & Hand-Calculated Spot Check
# ═════════════════════════════════════════════════════════════════════════════

def test_admin_partner_report_accuracy_against_hand_calculation():
    """
    Anti-Shortcut Rule:
    Construct a known test set for partner 'part_springboard_tech' (code 'SPRINGBOARD_VISA'):
    - Commission structure: $50.00 flat per activated user.
    - Clicks: 4 clicks from same session -> 1 unique click, 3 duplicates.
    - Signups: 3 referred candidates (Alex, Brian, Chloe).
    - Activations (Phase 10 locked definition):
      - Alex: has active alert -> Activated.
      - Brian: viewed 3 distinct jobs -> Activated.
      - Chloe: viewed only 1 job -> NOT activated.
    
    Hand-Calculations:
    - total_clicks = 4
    - unique_clicks = 1
    - referred_signups = 3
    - activated_users = 2
    - activation_rate_pct = 2 / 3 = 66.67%
    - estimated_commission_usd = 2 * $50.00 = $100.00
    """
    partner_id = "part_springboard_tech"
    partner_code = "SPRINGBOARD_VISA"

    # 1. Ingest 4 clicks (1 unique, 3 duplicates)
    for _ in range(4):
        record_affiliate_click(partner_id, session_id="sess_springboard_test")

    # 2. Ingest 3 referred users
    u_alex = "usr_alex_01"
    u_brian = "usr_brian_02"
    u_chloe = "usr_chloe_03"

    for uid, name in [(u_alex, "Alex"), (u_brian, "Brian"), (u_chloe, "Chloe")]:
        _MOCK_USER_PROFILES[uid] = {
            "id": uid,
            "full_name": name,
            "referred_by_partner_code": partner_code,
            "created_at": "2026-08-15T12:00:00Z",
        }
        _MOCK_USER_PARTNER_ATTRIBUTIONS[uid] = partner_code

    # 3. Simulate Activations
    # Alex: Active alert
    _MOCK_ALERTS_STORE["alt_alex"] = {
        "id": "alt_alex",
        "user_id": u_alex,
        "is_active": True,
    }

    # Brian: 3 distinct job views
    for job_num in [101, 102, 103]:
        _MOCK_EVENTS_STORE.append({
            "event_name": "job_viewed",
            "user_id": u_brian,
            "metadata": {"job_id": f"job_{job_num}"},
            "created_at": "2026-08-16T12:00:00Z",
        })

    # Chloe: Only 1 job view (repeats 3 times on same job -> 1 distinct job view)
    for _ in range(3):
        _MOCK_EVENTS_STORE.append({
            "event_name": "job_viewed",
            "user_id": u_chloe,
            "metadata": {"job_id": "job_999"},
            "created_at": "2026-08-16T12:00:00Z",
        })

    # Query Admin Report via API
    res = client.get(f"/api/v1/admin/partners/{partner_id}/report", headers=ADMIN_HEADERS)
    assert res.status_code == 200
    report = res.json()

    # Exact Hand-Calculation Assertions
    assert report["partner_id"] == partner_id
    assert report["total_clicks"] == 4
    assert report["unique_clicks"] == 1
    assert report["referred_signups"] == 3
    assert report["activated_users"] == 2
    assert report["activation_rate_pct"] == 66.67
    assert report["estimated_commission_usd"] == 100.00
    assert "2 activated users @ $50.00" in report["commission_breakdown"]["basis"]


# ═════════════════════════════════════════════════════════════════════════════
# 6. Admin Authentication & RBAC Boundaries
# ═════════════════════════════════════════════════════════════════════════════

def test_admin_partner_report_rbac():
    """Verify admin report endpoint enforces RBAC (401, 403, 200)."""
    p_id = "part_fragomen_law"

    # No auth -> 401
    res_no = client.get(f"/api/v1/admin/partners/{p_id}/report")
    assert res_no.status_code == 401

    # Regular user auth -> 403
    res_user = client.get(f"/api/v1/admin/partners/{p_id}/report", headers=USER_HEADERS)
    assert res_user.status_code == 403

    # Admin auth -> 200
    res_admin = client.get(f"/api/v1/admin/partners/{p_id}/report", headers=ADMIN_HEADERS)
    assert res_admin.status_code == 200
    assert res_admin.json()["partner_id"] == p_id


def test_admin_partner_report_with_date_range_and_percentage_commission():
    """
    Test partner report with:
    - Percentage commission (Cigna: 15% of $800 = $120/signup)
    - Date filtering with start_date and end_date
    """
    p_id = "aff_cigna_global"

    # Click in range (2026-08-10)
    dt_in_range = datetime.datetime(2026, 8, 10, 12, 0, tzinfo=datetime.timezone.utc)
    record_affiliate_click(p_id, session_id="s1", timestamp=dt_in_range)

    # Click out of range (2026-07-01)
    dt_out_range = datetime.datetime(2026, 7, 1, 12, 0, tzinfo=datetime.timezone.utc)
    record_affiliate_click(p_id, session_id="s2", timestamp=dt_out_range)

    res = client.get(
        f"/api/v1/admin/partners/{p_id}/report?start_date=2026-08-01&end_date=2026-08-31",
        headers=ADMIN_HEADERS,
    )
    assert res.status_code == 200
    rep = res.json()
    assert rep["partner_id"] == p_id
    assert rep["total_clicks"] == 1  # Only in-range click counted!
    assert rep["unique_clicks"] == 1


def test_partner_edge_cases_and_error_handling():
    """Test helper functions and edge cases to ensure robust coverage."""
    from engine.api.partner_service import (
        get_affiliate_partner_by_id,
        _MOCK_AFFILIATE_PARTNERS,
    )

    # 1. get_affiliate_partner_by_id
    p = get_affiliate_partner_by_id("aff_revolut_expat")
    assert p is not None
    assert p.slug == "revolut-expat"

    # 2. Inactive partner lookup
    _MOCK_AFFILIATE_PARTNERS["aff_revolut_expat"].status = "paused"
    p_paused = get_affiliate_partner_by_slug("revolut-expat")
    assert p_paused is None
    _MOCK_AFFILIATE_PARTNERS["aff_revolut_expat"].status = "active"

    # 3. record_affiliate_click with invalid partner raises ValueError
    with pytest.raises(ValueError, match="Unknown partner ID"):
        record_affiliate_click("non_existent_id", session_id="s_err")

    # 4. capture_landing_referral_code with invalid code returns None
    assert capture_landing_referral_code("sess_test", "NOT_A_REAL_CODE") is None

    # 5. lock_user_partner_referral with no candidate code returns None
    assert lock_user_partner_referral("usr_blank_99", referral_code=None, session_id="sess_empty") is None

    # 6. lock_user_partner_referral with invalid code returns None
    assert lock_user_partner_referral("usr_blank_99", referral_code="BAD_CODE_XYZ") is None

    # 7. generate_partner_report with non-existent partner raises 404 in API
    res_404 = client.get("/api/v1/admin/partners/phantom_partner/report", headers=ADMIN_HEADERS)
    assert res_404.status_code == 404

    # 8. Commission calculation for unique clicks
    from engine.api.partner_models import AffiliatePartner
    from engine.api.partner_service import _MOCK_AFFILIATE_SLUGS
    click_partner = AffiliatePartner(
        id="aff_click_model",
        slug="click-model",
        name="Click Based Partner",
        category="relocation",
        destination_url_template="https://example.com/reloc?sess={session_id}",
        commission_structure={"type": "flat", "amount_usd": 2.50, "event": "unique_click"},
        status="active",
    )
    _MOCK_AFFILIATE_PARTNERS[click_partner.id] = click_partner
    _MOCK_AFFILIATE_SLUGS[click_partner.slug] = click_partner.id

    record_affiliate_click(click_partner.id, session_id="sess_click_1")
    rep_click = generate_partner_report(click_partner.id)
    assert rep_click.estimated_commission_usd == 2.50


# ═════════════════════════════════════════════════════════════════════════════
# 6. Hardening Tests: Self-Referral, Redirect Allowlist & Click Burst Sanity
# ═════════════════════════════════════════════════════════════════════════════

def test_named_self_referral_fraud_pattern_flagged_and_excluded():
    """
    Hardening Rule:
    The system does not silently credit an obviously self-referential pattern
    as a legitimate referral.
    Self-referrals are detected, flagged in attribution metadata, and excluded
    from payable commission math in the admin report.
    """
    clear_mock_partner_stores()
    from engine.api.partner_service import _MOCK_USER_PARTNER_ATTRIBUTIONS_METADATA

    sess_fraud = "sess_self_referral_01"
    # Candidate signs up with an email matching the partner organization domain
    client.post("/api/v1/auth/signup/step1", json={
        "session_id": sess_fraud,
        "email": "attorney.smith@fragomen.com",
        "password": "Password123!",
        "referral_code": "FRAGOMEN2026",
    })
    client.post("/api/v1/auth/signup/step2", json={
        "session_id": sess_fraud,
        "visa_status": "Citizen",
        "target_role": "Partner",
    })
    res_comp = client.post("/api/v1/auth/signup/complete", json={
        "session_id": sess_fraud,
        "full_name": "Attorney Smith",
    })
    assert res_comp.status_code == 200
    uid = res_comp.json()["user_id"]

    # Assert attribution metadata flags this as self-referral
    meta = _MOCK_USER_PARTNER_ATTRIBUTIONS_METADATA.get(uid)
    assert meta is not None
    assert meta["is_self_referral"] is True

    # Generate admin report: Fragomen has $100 flat/signup contract
    res_rep = client.get("/api/v1/admin/partners/part_fragomen_law/report", headers=ADMIN_HEADERS)
    assert res_rep.status_code == 200
    rep = res_rep.json()

    assert rep["referred_signups"] == 1
    assert rep["self_referrals_flagged"] == 1
    # Payable signups is 0 -> Commission must be $0.00
    assert rep["estimated_commission_usd"] == 0.0
    assert rep["commission_breakdown"]["flagged_self_referrals"] == 1
    assert rep["commission_breakdown"]["payable_signups"] == 0


def test_named_redirect_allowlist_enforcement():
    """
    Hardening Rule:
    Confirm the redirect service cannot be used as an open redirect to launder
    arbitrary external URLs through VisaLane's domain.
    Only pre-registered destinations to real partners are allowed.
    """
    # 1. Non-existent slug returns 404
    res_404 = client.get("/go/unauthorized-external-slug")
    assert res_404.status_code == 404

    # 2. Attempt to override destination via query params is ignored
    res_inject = client.get("/go/revolut-expat?dest=https://phishing-site.com/steal-creds")
    assert res_inject.status_code == 307
    location = res_inject.headers["Location"]
    assert "revolut.com" in location
    assert "phishing-site.com" not in location

    # 3. Insecure non-HTTPS destination template is rejected
    from engine.api.partner_models import AffiliatePartner
    from engine.api.partner_service import build_destination_url
    bad_partner = AffiliatePartner(
        id="bad_partner",
        slug="bad-partner",
        name="Insecure Partner",
        category="banking",
        destination_url_template="http://insecure-site.com/tracker",
    )
    with pytest.raises(ValueError, match="Insecure partner destination URL"):
        build_destination_url(bad_partner, session_id="s1")


def test_named_click_volume_burst_sanity_50_clicks():
    """
    Hardening Rule:
    Fire 50 rapid clicks through /go/{slug} from one source in a short window.
    Confirm the resulting data makes this artificial burst clearly distinguishable
    from organic volume via duplicate tagging and burst detection.
    """
    clear_mock_partner_stores()
    burst_session = "sess_burst_attacker_50"

    for _ in range(50):
        res = client.get(f"/go/revolut-expat?session_id={burst_session}")
        assert res.status_code == 307

    # Verify admin report distinguishes the burst
    res_rep = client.get("/api/v1/admin/partners/aff_revolut_expat/report", headers=ADMIN_HEADERS)
    assert res_rep.status_code == 200
    rep = res_rep.json()

    # Out of 50 clicks: exactly 1 unique organic click, 49 duplicate clicks, and burst detected
    assert rep["total_clicks"] == 50
    assert rep["unique_clicks"] == 1
    assert rep["duplicate_clicks"] == 49
    assert rep["burst_clicks"] >= 45
    assert rep["commission_breakdown"]["burst_clicks"] >= 45
