"""
Automated Test Suite for VisaLane Phase 6 Backend:
Stripe Billing, Webhooks, Lifecycle Events, and Feature Entitlements.

Covers:
1. Checkout session creation for all 5 plans (Candidate Plus Monthly/Annual, Employer Featured, Badge, Pro)
2. Invalid plan rejection (HTTP 400)
3. Cryptographic webhook signature verification (valid vs missing vs forged)
4. Full webhook lifecycle processing (checkout.session.completed, subscription.updated, subscription.deleted, invoice.payment_failed)
5. Employer badge pending_review status verification on paid badge application
6. Entitlement boundary tests (free tier 0 vs 1 vs 2 requests, Plus tier unlimited)
7. Customer portal session generation
8. API endpoints integration tests for /api/v1/billing/*
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import time
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from engine.api.main import app
from engine.api.billing_service import (
    PLAN_CATALOG,
    STRIPE_WEBHOOK_SECRET,
    clear_mock_billing_stores,
    create_checkout_session,
    create_customer_portal_session,
    get_mock_company_billing,
    get_mock_processed_webhooks,
    get_mock_user_profile,
    get_user_entitlement,
    process_webhook_event,
    record_ai_generation_usage,
    set_mock_company_billing,
    set_mock_user_profile,
    verify_webhook_signature,
    check_ai_generation_entitlement,
)
from engine.api.jobs_routes import limiter

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_test_state():
    """Reset mock stores and rate limits before each test."""
    clear_mock_billing_stores()
    try:
        limiter.reset()
    except Exception:
        pass


def _generate_valid_stripe_signature(payload_bytes: bytes, secret: str = STRIPE_WEBHOOK_SECRET) -> str:
    """Helper to generate a cryptographically valid Stripe-Signature header."""
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
    signature = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


# ─────────────────────────────────────────────────────────────────────────────
# 1. Checkout Session Creation Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_create_checkout_session_all_valid_plans():
    """Verify checkout session creation across all supported plans."""
    for plan in [
        "candidate_plus_monthly",
        "candidate_plus_annual",
        "employer_featured",
        "employer_badge",
        "employer_pro",
    ]:
        session_id, checkout_url = create_checkout_session(
            plan=plan,
            user_id="user_123",
            customer_email="candidate@example.com",
            company_slug="stripe" if "employer" in plan else None,
        )
        assert session_id.startswith("cs_test_")
        assert "checkout.stripe.com" in checkout_url or "cs_test_" in checkout_url


def test_create_checkout_session_invalid_plan():
    """Verify ValueError is raised on invalid plan string."""
    with pytest.raises(ValueError) as exc:
        create_checkout_session(plan="invalid_unsupported_plan")
    assert "Invalid plan identifier" in str(exc.value)


def test_api_checkout_session_endpoint():
    """Test POST /api/v1/billing/checkout-session integration."""
    payload = {
        "plan": "candidate_plus_monthly",
        "user_id": "usr_test_999",
        "customer_email": "engineer@visalane.com",
        "success_url": "https://visalane.com/billing/success",
        "cancel_url": "https://visalane.com/pricing",
    }
    response = client.post("/api/v1/billing/checkout-session", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["plan"] == "candidate_plus_monthly"
    assert "session_id" in data
    assert "checkout_url" in data


def test_api_checkout_session_endpoint_bad_request():
    """Test POST /api/v1/billing/checkout-session with invalid plan returns 400."""
    payload = {"plan": "super_vip_tier"}
    response = client.post("/api/v1/billing/checkout-session", json=payload)
    assert response.status_code == 400
    assert "Invalid plan identifier" in response.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Webhook Signature Verification Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_webhook_signature_verification_valid():
    """Verify valid HMAC-SHA256 signature is accepted."""
    event_payload = {
        "id": "evt_test_1",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_1", "customer": "cus_1"}},
    }
    payload_bytes = json.dumps(event_payload).encode("utf-8")
    sig_header = _generate_valid_stripe_signature(payload_bytes)

    event = verify_webhook_signature(payload_bytes, sig_header)
    assert event["id"] == "evt_test_1"
    assert event["type"] == "checkout.session.completed"


def test_webhook_signature_verification_missing_header():
    """Verify missing signature header raises ValueError."""
    payload_bytes = b'{"id":"evt_1"}'
    with pytest.raises(ValueError) as exc:
        verify_webhook_signature(payload_bytes, None)
    assert "Missing Stripe-Signature header" in str(exc.value)


def test_webhook_signature_verification_forged_signature():
    """Verify forged signature is rejected with error."""
    payload_bytes = b'{"id":"evt_1"}'
    forged_sig = "t=1700000000,v1=deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    with pytest.raises(ValueError) as exc:
        verify_webhook_signature(payload_bytes, forged_sig)
    assert "Forged or invalid Stripe webhook signature" in str(exc.value)


def test_api_webhook_forged_signature_returns_400():
    """Test POST /api/v1/billing/webhook returns HTTP 400 on forged signature."""
    payload = json.dumps({"type": "checkout.session.completed"}).encode("utf-8")
    headers = {
        "stripe-signature": "t=1700000000,v1=bad_signature",
        "content-type": "application/json",
    }
    response = client.post("/api/v1/billing/webhook", content=payload, headers=headers)
    assert response.status_code == 400
    assert "Invalid webhook signature" in response.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Webhook Event Lifecycle Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_webhook_checkout_completed_candidate_plus():
    """Test candidate plus checkout grants active Plus entitlement."""
    user_id = "user_cand_101"
    event_data = {
        "id": "evt_checkout_plus",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_plus",
                "customer": "cus_stripe_101",
                "subscription": "sub_stripe_101",
                "metadata": {
                    "plan": "candidate_plus_monthly",
                    "user_id": user_id,
                },
            }
        },
    }
    payload_bytes = json.dumps(event_data).encode("utf-8")
    sig_header = _generate_valid_stripe_signature(payload_bytes)

    res = client.post("/api/v1/billing/webhook", content=payload_bytes, headers={"stripe-signature": sig_header})
    assert res.status_code == 200

    profile = get_mock_user_profile(user_id)
    assert profile is not None
    assert profile["subscription_plan"] == "plus"
    assert profile["subscription_status"] == "active"
    assert profile["stripe_customer_id"] == "cus_stripe_101"
    assert profile["stripe_subscription_id"] == "sub_stripe_101"

    # Verify entitlement
    ent = get_user_entitlement(user_id)
    assert ent["is_plus"] is True
    assert ent["alert_delivery_mode"] == "realtime"
    assert ent["early_access_unlocked"] is True
    assert ent["can_use_ai_generation"] is True


def test_webhook_checkout_completed_employer_badge():
    """Test employer badge payment sets badge_status to 'pending_review'."""
    company_slug = "spotify"
    event_data = {
        "id": "evt_checkout_badge",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_badge",
                "customer": "cus_spotify_emp",
                "metadata": {
                    "plan": "employer_badge",
                    "company_slug": company_slug,
                },
            }
        },
    }
    payload_bytes = json.dumps(event_data).encode("utf-8")
    sig_header = _generate_valid_stripe_signature(payload_bytes)

    res = client.post("/api/v1/billing/webhook", content=payload_bytes, headers={"stripe-signature": sig_header})
    assert res.status_code == 200

    comp_billing = get_mock_company_billing(company_slug)
    assert comp_billing is not None
    assert comp_billing["badge_status"] == "pending_review"
    assert comp_billing["badge_payment_status"] == "paid"


def test_webhook_checkout_completed_employer_featured():
    """Test employer featured payment sets featured_until."""
    company_slug = "zalando"
    event_data = {
        "id": "evt_checkout_feat",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_feat",
                "customer": "cus_zalando_emp",
                "metadata": {
                    "plan": "employer_featured",
                    "company_slug": company_slug,
                },
            }
        },
    }
    payload_bytes = json.dumps(event_data).encode("utf-8")
    sig_header = _generate_valid_stripe_signature(payload_bytes)

    res = client.post("/api/v1/billing/webhook", content=payload_bytes, headers={"stripe-signature": sig_header})
    assert res.status_code == 200

    comp_billing = get_mock_company_billing(company_slug)
    assert comp_billing is not None
    assert "featured_until" in comp_billing


def test_webhook_subscription_updated():
    """Test customer.subscription.updated syncs status."""
    user_id = "user_cand_202"
    set_mock_user_profile(user_id, {
        "subscription_plan": "plus",
        "subscription_status": "active",
        "stripe_subscription_id": "sub_sync_202",
        "stripe_customer_id": "cus_sync_202",
    })

    event_data = {
        "id": "evt_sub_upd",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_sync_202",
                "customer": "cus_sync_202",
                "status": "past_due",
            }
        },
    }
    payload_bytes = json.dumps(event_data).encode("utf-8")
    sig_header = _generate_valid_stripe_signature(payload_bytes)

    res = client.post("/api/v1/billing/webhook", content=payload_bytes, headers={"stripe-signature": sig_header})
    assert res.status_code == 200

    profile = get_mock_user_profile(user_id)
    assert profile["subscription_status"] == "past_due"


def test_webhook_subscription_deleted_revokes_plus():
    """Test customer.subscription.deleted revokes Plus plan back to free."""
    user_id = "user_cand_303"
    set_mock_user_profile(user_id, {
        "subscription_plan": "plus",
        "subscription_status": "active",
        "stripe_subscription_id": "sub_del_303",
        "stripe_customer_id": "cus_del_303",
    })

    event_data = {
        "id": "evt_sub_del",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_del_303",
                "customer": "cus_del_303",
            }
        },
    }
    payload_bytes = json.dumps(event_data).encode("utf-8")
    sig_header = _generate_valid_stripe_signature(payload_bytes)

    res = client.post("/api/v1/billing/webhook", content=payload_bytes, headers={"stripe-signature": sig_header})
    assert res.status_code == 200

    profile = get_mock_user_profile(user_id)
    assert profile["subscription_plan"] == "free"
    assert profile["subscription_status"] == "canceled"

    # Verify user entitlement is downgraded to free
    ent = get_user_entitlement(user_id)
    assert ent["is_plus"] is False
    assert ent["plan"] == "free"
    assert ent["ai_generation_quota_limit"] == 1


def test_webhook_invoice_payment_failed():
    """Test invoice.payment_failed marks user subscription as past_due."""
    user_id = "user_cand_404"
    set_mock_user_profile(user_id, {
        "subscription_plan": "plus",
        "subscription_status": "active",
        "stripe_subscription_id": "sub_inv_404",
        "stripe_customer_id": "cus_inv_404",
    })

    event_data = {
        "id": "evt_inv_fail",
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "subscription": "sub_inv_404",
                "customer": "cus_inv_404",
            }
        },
    }
    payload_bytes = json.dumps(event_data).encode("utf-8")
    sig_header = _generate_valid_stripe_signature(payload_bytes)

    res = client.post("/api/v1/billing/webhook", content=payload_bytes, headers={"stripe-signature": sig_header})
    assert res.status_code == 200

    profile = get_mock_user_profile(user_id)
    assert profile["subscription_status"] == "past_due"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Entitlement Quota & Boundary Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_entitlement_boundary_free_tier_exhaustion():
    """
    Test exact entitlement boundary for free tier users (1 generation/week):
    - Initial state: 0 usage -> quota_remaining: 1, allowed = True
    - 1st generation: usage = 1 -> quota_remaining: 0, allowed = False (boundary reached)
    - 2nd generation attempt: blocked with QUOTA_EXHAUSTED structured upgrade prompt
    """
    user_id = "free_user_boundary_test"

    # Step 1: Initial state
    ent0 = get_user_entitlement(user_id)
    assert ent0["ai_generation_usage_this_week"] == 0
    assert ent0["ai_generation_quota_remaining"] == 1
    assert ent0["can_use_ai_generation"] is True
    assert ent0["alert_delivery_mode"] == "daily"

    can_gen0, prompt0 = check_ai_generation_entitlement(user_id)
    assert can_gen0 is True
    assert prompt0 is None

    # Step 2: Use exact free quota (1 generation)
    new_count = record_ai_generation_usage(user_id)
    assert new_count == 1

    # Step 3: Check at-boundary state
    ent1 = get_user_entitlement(user_id)
    assert ent1["ai_generation_usage_this_week"] == 1
    assert ent1["ai_generation_quota_remaining"] == 0
    assert ent1["can_use_ai_generation"] is False

    # Step 4: Check next generation is blocked
    can_gen1, prompt1 = check_ai_generation_entitlement(user_id)
    assert can_gen1 is False
    assert prompt1 is not None
    assert prompt1["error"] == "QUOTA_EXHAUSTED"
    assert "candidate_plus_monthly" in prompt1["upgrade_url"]
    assert prompt1["usage_this_week"] == 1


def test_entitlement_plus_tier_unlimited_burst():
    """Test Plus subscribers can make continuous generation requests without quota blocking."""
    user_id = "plus_subscriber_burst"
    set_mock_user_profile(user_id, {
        "subscription_plan": "plus",
        "subscription_status": "active",
    })

    # Simulate 10 generations in a row
    for i in range(10):
        can_gen, prompt = check_ai_generation_entitlement(user_id)
        assert can_gen is True
        assert prompt is None
        record_ai_generation_usage(user_id)

    ent = get_user_entitlement(user_id)
    assert ent["is_plus"] is True
    assert ent["ai_generation_usage_this_week"] == 10
    assert ent["can_use_ai_generation"] is True
    assert ent["early_access_unlocked"] is True
    assert ent["alert_delivery_mode"] == "realtime"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Customer Portal & Entitlements API Integration Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_api_billing_portal_session():
    """Test GET /api/v1/billing/portal-session returns portal URL."""
    user_id = "portal_user_505"
    set_mock_user_profile(user_id, {
        "stripe_customer_id": "cus_portal_505",
    })

    res = client.get(f"/api/v1/billing/portal-session?user_id={user_id}")
    assert res.status_code == 200
    data = res.json()
    assert "portal_url" in data
    assert "billing.stripe.com" in data["portal_url"]


def test_api_billing_entitlements_endpoint():
    """Test GET /api/v1/billing/entitlements."""
    user_id = "ent_user_606"
    set_mock_user_profile(user_id, {
        "subscription_plan": "plus",
        "subscription_status": "active",
    })

    res = client.get(f"/api/v1/billing/entitlements?user_id={user_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["is_plus"] is True
    assert data["plan"] == "plus"
    assert data["status"] == "active"
    assert data["alert_delivery_mode"] == "realtime"
    assert data["early_access_unlocked"] is True
