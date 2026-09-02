"""
Targeted coverage tests for engine.api.billing_service to achieve >= 95% line coverage.
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch
import pytest

import stripe
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


@pytest.fixture(autouse=True)
def clean_stores():
    clear_mock_billing_stores()


def test_billing_helpers_and_anonymous_entitlements():
    """Test get/set helpers and anonymous entitlement evaluation."""
    assert get_mock_company_billing("nonexistent") is None
    set_mock_company_billing("acme", {"badge_status": "pending_review"})
    assert get_mock_company_billing("acme")["badge_status"] == "pending_review"

    # Anonymous user entitlement
    ent_anon = get_user_entitlement(None)
    assert ent_anon["user_id"] is None
    assert ent_anon["plan"] == "free"
    assert ent_anon["is_plus"] is False
    assert ent_anon["can_use_ai_generation"] is True

    # Usage recording for anonymous session
    u_count = record_ai_generation_usage(None)
    assert u_count == 1

    # Admin profile entitlement
    set_mock_user_profile("admin_user_01", {"subscription_plan": "admin", "is_admin": True})
    ent_admin = get_user_entitlement("admin_user_01")
    assert ent_admin["plan"] == "admin"
    assert ent_admin["is_plus"] is True
    assert ent_admin["ai_generation_quota_limit"] == 999999


def test_customer_portal_session_variants():
    """Test create_customer_portal_session with and without customer_id / user_id."""
    # 1. No customer ID and no user ID -> uses fallback customer
    url1 = create_customer_portal_session(None, None, return_url="https://visalane.com/done")
    assert "mock_portal_cus_mock_customer_id" in url1

    # 2. User with customer ID in profile
    set_mock_user_profile("user_with_cust", {"stripe_customer_id": "cus_real_123"})
    url2 = create_customer_portal_session(None, "user_with_cust")
    assert "cus_real_123" in url2

    # 3. Direct customer ID provided
    url3 = create_customer_portal_session(customer_id="cus_direct_789")
    assert "cus_direct_789" in url3


def test_process_webhook_unhandled_and_edge_events():
    """Test process_webhook_event for ignored event types and unknown customers."""
    # 1. Ignored event type
    res_ign = process_webhook_event({"id": "evt_ping", "type": "ping", "data": {"object": {}}})
    assert res_ign["handled"] is True
    assert res_ign["action"] == "ignored"

    # 2. subscription.updated for unknown customer -> ignored
    res_sub_unk = process_webhook_event({
        "id": "evt_sub_unk",
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_unknown", "customer": "cus_unknown", "status": "active"}},
    })
    assert res_sub_unk["action"] == "subscription_updated"

    # 3. subscription.deleted for unknown customer -> ignored
    res_del_unk = process_webhook_event({
        "id": "evt_del_unk",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_unknown", "customer": "cus_unknown"}},
    })
    assert res_del_unk["action"] == "subscription_canceled"

    # 4. invoice.payment_failed for unknown customer -> ignored
    res_inv_unk = process_webhook_event({
        "id": "evt_inv_unk",
        "type": "invoice.payment_failed",
        "data": {"object": {"subscription": "sub_unknown", "customer": "cus_unknown"}},
    })
    assert res_inv_unk["action"] == "invoice_failure_recorded"

    # 5. charge.refunded for unknown target -> ignored
    res_ref_unk = process_webhook_event({
        "id": "evt_ref_unk",
        "type": "charge.refunded",
        "data": {"object": {"customer": "cus_unknown"}},
    })
    assert res_ref_unk["action"] == "refund_recorded"

    # 6. checkout.session.completed for candidate_plus_annual
    res_ann = process_webhook_event({
        "id": "evt_ann",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_annual",
                "customer": "cus_ann",
                "subscription": "sub_ann",
                "metadata": {"plan": "candidate_plus_annual", "user_id": "user_annual_01"},
            }
        },
    })
    assert res_ann["plan"] == "plus"
    prof_ann = get_mock_user_profile("user_annual_01")
    assert prof_ann["subscription_plan"] == "plus"

    # 7. checkout.session.completed for employer_pro
    res_pro = process_webhook_event({
        "id": "evt_pro",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_pro",
                "customer": "cus_pro",
                "subscription": "sub_pro",
                "metadata": {"plan": "employer_pro", "company_slug": "meta_emp"},
            }
        },
    })
    assert res_pro["plan"] == "employer_pro"
    comp_pro = get_mock_company_billing("meta_emp")
    assert comp_pro["employer_plan"] == "pro"


def test_verify_webhook_signature_live_sdk_and_exceptions():
    """Test Stripe SDK signature verification logic and exception branches."""
    # Signature parsing format errors
    with pytest.raises(ValueError) as exc1:
        verify_webhook_signature(b"{}", "invalid_header_no_commas")
    assert "Invalid Stripe-Signature format" in str(exc1.value)

    # Test official SDK construct_event branch
    with patch("stripe.Webhook.construct_event") as mock_construct:
        mock_construct.return_value = {"id": "evt_live_123", "type": "checkout.session.completed"}
        event = verify_webhook_signature(b'{"id":"evt_live_123"}', "t=170000,v1=valid", webhook_secret="whsec_live_key")
        assert event["id"] == "evt_live_123"

    # Test signature verification error from SDK
    with patch("stripe.Webhook.construct_event", side_effect=stripe.SignatureVerificationError("Sig bad", "sig_hdr")):
        with pytest.raises(ValueError) as exc2:
            verify_webhook_signature(b'{}', "t=170000,v1=bad", webhook_secret="whsec_live_key")
        assert "Stripe signature verification failed" in str(exc2.value)


def test_create_checkout_and_portal_live_sdk_branches():
    """Test live Stripe API branches for checkout and customer portal."""
    with patch("stripe.checkout.Session.create") as mock_sess_create:
        mock_sess = MagicMock()
        mock_sess.id = "cs_live_12345"
        mock_sess.url = "https://checkout.stripe.com/live/pay"
        mock_sess_create.return_value = mock_sess

        with patch("engine.api.billing_service.STRIPE_SECRET_KEY", "sk_test_live_secret_key"):
            s_id, s_url = create_checkout_session("candidate_plus_monthly", user_id="u_live", customer_email="live@test.com")
            assert s_id == "cs_live_12345"
            assert s_url == "https://checkout.stripe.com/live/pay"

    with patch("stripe.billing_portal.Session.create") as mock_portal_create:
        mock_portal = MagicMock()
        mock_portal.url = "https://billing.stripe.com/live/portal"
        mock_portal_create.return_value = mock_portal

        with patch("engine.api.billing_service.STRIPE_SECRET_KEY", "sk_test_live_secret_key"):
            portal_url = create_customer_portal_session(customer_id="cus_live_999")
            assert portal_url == "https://billing.stripe.com/live/portal"
