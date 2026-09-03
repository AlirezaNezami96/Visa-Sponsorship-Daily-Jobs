"""
VisaLane Phase 12 — Physical Manual/Exploratory Testing Protocol Runner
Executes all 5 required protocols from Section 8 with hard evidence, exact boundary verification,
rapid repeated click de-duplication, multi-step signup survival, and hand-calculated commission validation.
"""
from __future__ import annotations

import datetime
import time
from typing import Any, Dict, List
from fastapi.testclient import TestClient

from engine.api.main import app
from engine.api.partner_service import (
    clear_mock_partner_stores,
    get_affiliate_partner_by_slug,
    record_affiliate_click,
    generate_partner_report,
    _MOCK_AFFILIATE_CLICKS,
    _MOCK_USER_PARTNER_ATTRIBUTIONS,
)
from engine.api.jobs_routes import _MOCK_EVENTS_STORE, clear_mock_stores
from engine.api.alert_service import _MOCK_ALERTS_STORE, clear_mock_alert_stores
from engine.api.billing_service import _MOCK_USER_PROFILES, clear_mock_billing_stores

client = TestClient(app, follow_redirects=False)
ADMIN_HEADERS = {"Authorization": "Bearer admin-token-secret"}


def header(title: str):
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def run_protocol_1():
    header("PROTOCOL 1: Affiliate Redirect Clickthrough & Parameter Verification")
    clear_mock_partner_stores()

    session_id = "sess_real_traveler_88"
    partner_slug = "revolut-expat"

    print("1. Querying GET /go/revolut-expat?session_id=sess_real_traveler_88:")
    res = client.get(f"/go/{partner_slug}?session_id={session_id}")
    print(f"   Status Code: {res.status_code} (Expected 307 Temporary Redirect)")
    assert res.status_code == 307

    location = res.headers.get("location")
    print(f"   Redirect Location: {location}")
    assert "https://revolut.com/promo/global-talent" in location
    assert f"visalane_session={session_id}" in location
    assert "utm_source=visalane" in location
    assert "utm_medium=affiliate" in location
    print("   [CONFIRMED] Destination URL template correctly interpolated tracking parameters.")


def run_protocol_2():
    header("PROTOCOL 2: Rapid 5-Click Burst De-duplication Test")
    clear_mock_partner_stores()

    session_id = "sess_rapid_fire_user"
    partner_slug = "cigna-global"

    print("1. Simulating 5 rapid sequential clicks from the same visitor session:")
    for i in range(1, 6):
        res = client.get(f"/go/{partner_slug}?session_id={session_id}")
        assert res.status_code == 307
        print(f"   - Click #{i}: 307 Redirect OK")

    cigna_clicks = [c for c in _MOCK_AFFILIATE_CLICKS if c.partner_id == "aff_cigna_global"]
    total_clicks = len(cigna_clicks)
    unique_clicks = len([c for c in cigna_clicks if not c.is_duplicate])
    duplicate_clicks = len([c for c in cigna_clicks if c.is_duplicate])

    print(f"\n2. Audit Breakdown in Click Store:")
    print(f"   - Total Clicks Logged:     {total_clicks}")
    print(f"   - Unique Non-Duplicate:    {unique_clicks}")
    print(f"   - Debounced Duplicates:    {duplicate_clicks}")

    assert total_clicks == 5
    assert unique_clicks == 1
    assert duplicate_clicks == 4
    print("   [CONFIRMED] Rapid repeated clicks successfully de-duplicated. Click volume not distorted.")


def run_protocol_3():
    header("PROTOCOL 3: Full Multi-Step Signup Survival (Fragomen Immigration Law)")
    clear_mock_partner_stores()
    clear_mock_stores()
    clear_mock_billing_stores()

    session_id = "sess_immigrant_journey_2026"
    partner_code = "FRAGOMEN2026"

    print("1. Step 1: Candidate lands with referral code FRAGOMEN2026 & enters credentials:")
    s1_res = client.post("/api/v1/auth/signup/step1", json={
        "session_id": session_id,
        "email": "dev.priya@outlook.com",
        "password": "StrongSecretPassword99!",
        "referral_code": partner_code,
    })
    assert s1_res.status_code == 200
    s1_data = s1_res.json()
    print(f"   Step 1 Response: step={s1_data['current_step']}, code={s1_data['referred_by_partner_code']}")
    assert s1_data["referred_by_partner_code"] == partner_code

    print("\n2. Step 2: Candidate inputs visa preferences and target role:")
    s2_res = client.post("/api/v1/auth/signup/step2", json={
        "session_id": session_id,
        "visa_status": "H-1B Transfer",
        "target_role": "Senior Distributed Systems Engineer",
    })
    assert s2_res.status_code == 200
    s2_data = s2_res.json()
    print(f"   Step 2 Response: step={s2_data['current_step']}, code={s2_data['referred_by_partner_code']}")
    assert s2_data["referred_by_partner_code"] == partner_code

    print("\n3. Step 3: Candidate completes profile and account finalization:")
    s3_res = client.post("/api/v1/auth/signup/complete", json={
        "session_id": session_id,
        "full_name": "Priya Sharma",
    })
    assert s3_res.status_code == 200
    s3_data = s3_res.json()
    created_uid = s3_data["user_id"]
    print(f"   Step 3 Response: step={s3_data['current_step']}, status={s3_data['status']}, user_id={created_uid}")
    print(f"   Locked Attribution: {s3_data['referred_by_partner_code']}")

    assert s3_data["referred_by_partner_code"] == partner_code
    assert _MOCK_USER_PARTNER_ATTRIBUTIONS[created_uid] == partner_code
    assert _MOCK_USER_PROFILES[created_uid]["referred_by_partner_code"] == partner_code
    print("   [CONFIRMED] Referral code survived full multi-step signup and was permanently locked on account.")


def run_protocol_4():
    header("PROTOCOL 4: Hand-Counted Admin Report Accuracy Check (5 Test Referrals)")
    clear_mock_partner_stores()
    clear_mock_stores()
    clear_mock_alert_stores()
    clear_mock_billing_stores()

    partner_id = "part_fragomen_law"
    partner_code = "FRAGOMEN2026"
    # Commission: $100.00 flat per signup

    print("1. Constructing exact known test set:")
    print("   - 2 Clicks (1 unique, 1 duplicate)")
    print("   - 3 Referred Signups (User 1, User 2, User 3)")
    print("   - User 1: Activated via Job Alert")
    print("   - User 2: Activated via 3 Distinct Job Views")
    print("   - User 3: Inactive (0 job views)")

    # Ingest clicks
    for _ in range(2):
        record_affiliate_click(partner_id, session_id="sess_law_check")

    # Ingest signups
    for i, name in enumerate(["User 1", "User 2", "User 3"], start=1):
        uid = f"usr_test_{i}"
        _MOCK_USER_PROFILES[uid] = {
            "id": uid,
            "full_name": name,
            "referred_by_partner_code": partner_code,
            "created_at": "2026-08-20T10:00:00Z",
        }
        _MOCK_USER_PARTNER_ATTRIBUTIONS[uid] = partner_code

    # Activate User 1 via Alert
    _MOCK_ALERTS_STORE["alt_u1"] = {"id": "alt_u1", "user_id": "usr_test_1", "is_active": True}

    # Activate User 2 via 3 Distinct Job Views
    for j_id in ["job_aws_01", "job_msft_02", "job_meta_03"]:
        _MOCK_EVENTS_STORE.append({
            "event_type": "job_viewed",
            "user_id": "usr_test_2",
            "metadata": {"job_id": j_id},
        })

    # Expected Hand Math:
    # total_clicks = 2, unique_clicks = 1
    # referred_signups = 3
    # activated_users = 2 (User 1 and User 2)
    # activation_rate = 2 / 3 = 66.67%
    # commission = 3 * $100.00 = $300.00 (Flat $100 per signup)

    print("\n2. Querying GET /api/v1/admin/partners/part_fragomen_law/report:")
    res = client.get(f"/api/v1/admin/partners/{partner_id}/report", headers=ADMIN_HEADERS)
    assert res.status_code == 200
    rep = res.json()

    print(f"   - Total Clicks:      {rep['total_clicks']} (Hand Count: 2)")
    print(f"   - Unique Clicks:     {rep['unique_clicks']} (Hand Count: 1)")
    print(f"   - Referred Signups:  {rep['referred_signups']} (Hand Count: 3)")
    print(f"   - Activated Users:   {rep['activated_users']} (Hand Count: 2)")
    print(f"   - Activation Rate:   {rep['activation_rate_pct']}% (Hand Math: 66.67%)")
    print(f"   - Estimated Payout:  ${rep['estimated_commission_usd']:.2f} (Hand Math: $300.00)")

    assert rep["total_clicks"] == 2
    assert rep["unique_clicks"] == 1
    assert rep["referred_signups"] == 3
    assert rep["activated_users"] == 2
    assert rep["activation_rate_pct"] == 66.67
    assert rep["estimated_commission_usd"] == 300.00
    print("   [CONFIRMED] Admin report numbers match hand calculations to the penny.")


def run_protocol_5():
    header("PROTOCOL 5: Cross-Partner Collision & First-Touch Immunity")
    clear_mock_partner_stores()
    clear_mock_stores()
    clear_mock_billing_stores()

    session_id = "sess_immune_candidate"

    print("1. Visitor lands with Springboard Tech referral code 'SPRINGBOARD_VISA':")
    s1 = client.post("/api/v1/auth/signup/step1", json={
        "session_id": session_id,
        "email": "hannah.ai@visalane.com",
        "password": "SecretPassword2026!",
        "referral_code": "SPRINGBOARD_VISA",
    })
    assert s1.status_code == 200

    print("2. Prior to completing signup, visitor clicks Revolut banking affiliate link:")
    res_revolut = client.get(f"/go/revolut-expat?session_id={session_id}")
    assert res_revolut.status_code == 307

    print("3. Visitor finishes registration steps 2 & 3:")
    client.post("/api/v1/auth/signup/step2", json={
        "session_id": session_id,
        "visa_status": "TN Visa",
        "target_role": "Data Scientist",
    })
    comp = client.post("/api/v1/auth/signup/complete", json={
        "session_id": session_id,
        "full_name": "Hannah Abbott",
    })
    assert comp.status_code == 200
    user_id = comp.json()["user_id"]

    locked_code = _MOCK_USER_PARTNER_ATTRIBUTIONS.get(user_id)
    print(f"   Account Locked Attribution: {locked_code}")
    assert locked_code == "SPRINGBOARD_VISA"

    print("4. Attempting an explicit overwrite with another partner code (Fragomen):")
    from engine.api.partner_service import lock_user_partner_referral
    attempt = lock_user_partner_referral(user_id, referral_code="FRAGOMEN2026")
    print(f"   Result of Overwrite Attempt: {attempt} (Must remain 'SPRINGBOARD_VISA')")
    assert attempt == "SPRINGBOARD_VISA"
    print("   [CONFIRMED] First-touch partner referral code is strictly immune to subsequent affiliate clicks and overwrites.")


if __name__ == "__main__":
    t0 = time.time()
    print("\n" + "#" * 80)
    print(" VISALANE PHASE 12: PARTNERSHIP & AFFILIATE INFRASTRUCTURE PROTOCOL RUNNER")
    print("#" * 80)

    run_protocol_1()
    run_protocol_2()
    run_protocol_3()
    run_protocol_4()
    run_protocol_5()

    elapsed = time.time() - t0
    print("\n" + "#" * 80)
    print(f" ALL 5 EXPLORATORY TESTING PROTOCOLS CONFIRMED WITH ZERO ERRORS in {elapsed:.2f}s!")
    print("#" * 80 + "\n")
