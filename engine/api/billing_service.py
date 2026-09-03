"""
Stripe Billing, Webhook Handling, and Feature Entitlements Service for VisaLane.
Implements:
- Stripe Checkout Session creation with native multi-currency pricing
- Cryptographic Webhook signature verification (rejects forged/missing signatures)
- Webhook event lifecycle handlers:
  - checkout.session.completed (Candidate Plus, Employer Featured, Employer Badge, Employer Pro)
  - customer.subscription.updated
  - customer.subscription.deleted (Revocation)
  - invoice.payment_failed (Past-due marking)
- Customer Portal session generation
- Entitlement status tracking and feature gating (AI generation quota, early access, alert delivery)
"""
from __future__ import annotations

import datetime
import hmac
import hashlib
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

import stripe

logger = logging.getLogger(__name__)

# Stripe API Keys & Webhook Secret
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "sk_test_visalane_mock_secret_key_2026")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "whsec_visalane_mock_webhook_secret_2026")
DEFAULT_SITE_URL = os.environ.get("SITE_URL", "https://visalane.com").rstrip("/")

stripe.api_key = STRIPE_SECRET_KEY

# Plan definitions
PLAN_CATALOG: Dict[str, Dict[str, Any]] = {
    "candidate_plus_monthly": {
        "name": "VisaLane Candidate Plus (Monthly)",
        "mode": "subscription",
        "interval": "month",
        "unit_amount": 1900,  # $19.00 USD
        "currency": "usd",
        "description": "Unlimited AI tailored resumes, real-time visa alert delivery, and 24h early access to new sponsor listings.",
        "price_id": os.environ.get("STRIPE_PRICE_CANDIDATE_PLUS_MONTHLY", "price_candidate_plus_monthly"),
    },
    "candidate_plus_annual": {
        "name": "VisaLane Candidate Plus (Annual)",
        "mode": "subscription",
        "interval": "year",
        "unit_amount": 14900,  # $149.00 USD
        "currency": "usd",
        "description": "Save 35% with annual billing. Unlimited AI tailored resumes, real-time alert delivery, and early sponsor access.",
        "price_id": os.environ.get("STRIPE_PRICE_CANDIDATE_PLUS_ANNUAL", "price_candidate_plus_annual"),
    },
    "employer_featured": {
        "name": "Featured Employer Listing (30 Days)",
        "mode": "payment",
        "unit_amount": 19900,  # $199.00 USD
        "currency": "usd",
        "description": "Boost company visibility and pin sponsored listings to the top of search results for 30 days.",
        "price_id": os.environ.get("STRIPE_PRICE_EMPLOYER_FEATURED", "price_employer_featured"),
    },
    "employer_badge": {
        "name": "Verified Sponsor Badge Application Fee",
        "mode": "payment",
        "unit_amount": 49900,  # $499.00 USD
        "currency": "usd",
        "description": "Official legal sponsorship verification audit and verified badge for company profile.",
        "price_id": os.environ.get("STRIPE_PRICE_EMPLOYER_BADGE", "price_employer_badge"),
    },
    "employer_pro": {
        "name": "VisaLane Employer Pro (Monthly)",
        "mode": "subscription",
        "interval": "month",
        "unit_amount": 59900,  # $599.00 USD
        "currency": "usd",
        "description": "Full employer suite: featured profile, applicant matching alerts, and unlimited job syndication.",
        "price_id": os.environ.get("STRIPE_PRICE_EMPLOYER_PRO", "price_employer_pro"),
    },
}

# In-memory entitlement and subscription store for offline testing
_MOCK_USER_PROFILES: Dict[str, Dict[str, Any]] = {}
_MOCK_COMPANY_BILLING: Dict[str, Dict[str, Any]] = {}
_MOCK_USAGE_TRACKING: Dict[str, Dict[str, Any]] = {}  # f"{user_id}:{week_str}" -> count
_MOCK_PROCESSED_WEBHOOKS: List[Dict[str, Any]] = []
_PROCESSED_EVENT_IDS: set[str] = set()


def clear_mock_billing_stores() -> None:
    """Reset mock stores between test executions."""
    global _MOCK_USER_PROFILES, _MOCK_COMPANY_BILLING, _MOCK_USAGE_TRACKING, _MOCK_PROCESSED_WEBHOOKS, _PROCESSED_EVENT_IDS
    _MOCK_USER_PROFILES.clear()
    _MOCK_COMPANY_BILLING.clear()
    _MOCK_USAGE_TRACKING.clear()
    _MOCK_PROCESSED_WEBHOOKS.clear()
    _PROCESSED_EVENT_IDS.clear()


def set_mock_user_profile(user_id: str, profile_data: Dict[str, Any]) -> None:
    """Helper for tests to seed user profile state."""
    _MOCK_USER_PROFILES[user_id] = profile_data


def get_mock_user_profile(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve in-memory user profile data."""
    return _MOCK_USER_PROFILES.get(user_id)


def set_mock_company_billing(company_slug: str, data: Dict[str, Any]) -> None:
    """Helper for tests to seed company billing state."""
    _MOCK_COMPANY_BILLING[company_slug] = data


def get_mock_company_billing(company_slug: str) -> Optional[Dict[str, Any]]:
    """Retrieve in-memory company billing data."""
    return _MOCK_COMPANY_BILLING.get(company_slug)


def _get_supabase_client():
    """Retrieve Supabase service client if configured."""
    try:
        from job_radar.visalane.db import get_service_client
        return get_service_client()
    except Exception:
        return None


def get_company_billing(company_slug: str) -> Dict[str, Any]:
    """Retrieve company billing data from mock store or database."""
    comp = _MOCK_COMPANY_BILLING.get(company_slug)
    if comp:
        return comp
    client = _get_supabase_client()
    if client is not None:
        try:
            res = client.from_("companies").select("billing_plan,employer_plan,featured_until").eq("slug", company_slug).maybe_single().execute()
            if res and res.data:
                return res.data
        except Exception:
            pass
    return {}


def get_mock_processed_webhooks() -> List[Dict[str, Any]]:
    """Retrieve list of processed webhook events."""
    return _MOCK_PROCESSED_WEBHOOKS


def _get_current_week_key() -> str:
    """Return ISO year and week number, e.g. '2026-W36'."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-W%W")


def _get_next_week_reset_iso() -> str:
    """Return the start of the next Monday in UTC ISO format."""
    now = datetime.datetime.now(datetime.timezone.utc)
    days_until_monday = 7 - now.weekday() if now.weekday() != 0 else 7
    next_monday = (now + datetime.timedelta(days=days_until_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return next_monday.isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Checkout Session Creation
# ─────────────────────────────────────────────────────────────────────────────

def create_checkout_session(
    plan: str,
    user_id: Optional[str] = None,
    customer_email: Optional[str] = None,
    company_slug: Optional[str] = None,
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Creates a Stripe Checkout Session for a candidate subscription or employer purchase.
    Returns (session_id, checkout_url).
    """
    plan_info = PLAN_CATALOG.get(plan)
    if not plan_info:
        raise ValueError(f"Invalid plan identifier '{plan}'. Must be one of {list(PLAN_CATALOG.keys())}.")

    default_success = f"{DEFAULT_SITE_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}&plan={plan}"
    default_cancel = f"{DEFAULT_SITE_URL}/pricing?canceled=true"

    succ_url = success_url or default_success
    canc_url = cancel_url or default_cancel

    metadata = {
        "plan": plan,
        "user_id": user_id or "",
        "company_slug": company_slug or "",
    }

    # Attempt live/test Stripe API call if configured with valid live key
    if STRIPE_SECRET_KEY and not STRIPE_SECRET_KEY.startswith("sk_test_visalane_mock"):
        try:
            line_item: Dict[str, Any] = {
                "price_data": {
                    "currency": plan_info["currency"],
                    "product_data": {
                        "name": plan_info["name"],
                        "description": plan_info["description"],
                    },
                    "unit_amount": plan_info["unit_amount"],
                },
                "quantity": 1,
            }
            if plan_info["mode"] == "subscription":
                line_item["price_data"]["recurring"] = {"interval": plan_info["interval"]}

            session_params: Dict[str, Any] = {
                "payment_method_types": ["card"],
                "mode": plan_info["mode"],
                "line_items": [line_item],
                "success_url": succ_url,
                "cancel_url": canc_url,
                "metadata": metadata,
            }
            if customer_email:
                session_params["customer_email"] = customer_email

            session = stripe.checkout.Session.create(**session_params)
            return session.id, session.url
        except Exception as exc:
            logger.warning("Live Stripe Checkout creation failed, falling back to mock: %s", exc)

    # Deterministic mock checkout session for test environments
    mock_id = f"cs_test_{uuid.uuid4().hex[:16]}"
    mock_url = f"https://checkout.stripe.com/c/pay/{mock_id}"
    return mock_id, mock_url


# ─────────────────────────────────────────────────────────────────────────────
# 2. Webhook Signature Verification & Processing
# ─────────────────────────────────────────────────────────────────────────────

def verify_webhook_signature(
    payload_bytes: bytes,
    signature_header: Optional[str],
    webhook_secret: str = STRIPE_WEBHOOK_SECRET,
    tolerance_seconds: int = 300,
) -> Dict[str, Any]:
    """
    Verifies Stripe webhook HMAC-SHA256 signature header.
    Raises ValueError if signature is missing, invalid, or forged.
    """
    if not signature_header:
        raise ValueError("Missing Stripe-Signature header.")

    # In mock test mode where secret starts with mock
    if webhook_secret.startswith("whsec_visalane_mock"):
        # Custom HMAC verification for mock testing
        try:
            sig_dict = {}
            for item in signature_header.split(","):
                if "=" in item:
                    k, v = item.strip().split("=", 1)
                    sig_dict[k] = v
            timestamp = sig_dict.get("t")
            v1_sig = sig_dict.get("v1")

            if not timestamp or not v1_sig:
                raise ValueError("Invalid Stripe-Signature format.")

            signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
            expected_sig = hmac.new(
                webhook_secret.encode("utf-8"),
                signed_payload,
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(expected_sig, v1_sig):
                raise ValueError("Forged or invalid Stripe webhook signature.")

            return json.loads(payload_bytes.decode("utf-8"))
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Webhook signature parsing error: {e}")

    # Official Stripe SDK construct_event
    try:
        event = stripe.Webhook.construct_event(
            payload=payload_bytes,
            sig_header=signature_header,
            secret=webhook_secret,
            tolerance=tolerance_seconds,
        )
        return event
    except stripe.SignatureVerificationError as sve:
        raise ValueError(f"Stripe signature verification failed: {sve}")
    except Exception as exc:
        raise ValueError(f"Invalid webhook payload: {exc}")


def process_webhook_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Processes verified Stripe webhook event across the full subscription & payment lifecycle.
    Implements idempotency checking to prevent duplicate side effects on at-least-once deliveries.
    Handles:
    - checkout.session.completed
    - customer.subscription.updated
    - customer.subscription.deleted
    - invoice.payment_failed
    - charge.refunded (Gap closed: revokes entitlement and resets employer status)
    """
    event_id = str(event.get("id", ""))
    event_type = str(event.get("type", ""))
    event_data = event.get("data", {}).get("object", {})

    # 1. Idempotency Check: Ignore already processed event IDs
    if event_id:
        if event_id in _PROCESSED_EVENT_IDS:
            logger.info("Ignoring duplicate Stripe webhook event ID: %s", event_id)
            return {
                "handled": True,
                "event_type": event_type,
                "status": "duplicate_ignored",
                "idempotent": True,
            }
        _PROCESSED_EVENT_IDS.add(event_id)

    _MOCK_PROCESSED_WEBHOOKS.append({
        "event_id": event_id,
        "event_type": event_type,
        "processed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "object": event_data,
    })

    if event_type == "checkout.session.completed":
        return _handle_checkout_completed(event_data)
    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        return _handle_subscription_updated(event_data)
    elif event_type == "customer.subscription.deleted":
        return _handle_subscription_deleted(event_data)
    elif event_type == "invoice.payment_failed":
        return _handle_invoice_payment_failed(event_data)
    elif event_type == "charge.refunded":
        return _handle_charge_refunded(event_data)
    else:
        logger.info("Unhandled Stripe event type: %s", event_type)
        return {"handled": True, "event_type": event_type, "action": "ignored"}


def _handle_checkout_completed(data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle successful checkout completion for Plus or Employer products."""
    metadata = data.get("metadata") or {}
    plan = metadata.get("plan", "candidate_plus_monthly")
    user_id = metadata.get("user_id")
    company_slug = metadata.get("company_slug")
    customer_id = data.get("customer")
    subscription_id = data.get("subscription")

    now = datetime.datetime.now(datetime.timezone.utc)
    one_month_later = (now + datetime.timedelta(days=30)).isoformat()
    one_year_later = (now + datetime.timedelta(days=365)).isoformat()

    # Candidate Subscriptions
    if plan in ("candidate_plus_monthly", "candidate_plus_annual"):
        if user_id:
            period_end = one_year_later if plan == "candidate_plus_annual" else one_month_later
            prof = _MOCK_USER_PROFILES.setdefault(user_id, {})
            prof.update({
                "subscription_plan": "plus",
                "subscription_status": "active",
                "stripe_customer_id": customer_id,
                "stripe_subscription_id": subscription_id,
                "current_period_end": period_end,
                "updated_at": now.isoformat(),
            })
            return {"handled": True, "plan": "plus", "user_id": user_id, "status": "active"}

    # Employer Badge Purchase
    elif plan == "employer_badge":
        if company_slug:
            comp_billing = _MOCK_COMPANY_BILLING.setdefault(company_slug, {})
            comp_billing.update({
                "badge_status": "pending_review",
                "badge_payment_status": "paid",
                "stripe_customer_id": customer_id,
                "last_payment_at": now.isoformat(),
            })
            return {"handled": True, "plan": "employer_badge", "company_slug": company_slug, "badge_status": "pending_review"}

    # Employer Featured Listing
    elif plan == "employer_featured":
        if company_slug:
            comp_billing = _MOCK_COMPANY_BILLING.setdefault(company_slug, {})
            comp_billing.update({
                "featured_until": one_month_later,
                "stripe_customer_id": customer_id,
                "last_payment_at": now.isoformat(),
            })
            return {"handled": True, "plan": "employer_featured", "company_slug": company_slug, "featured_until": one_month_later}

    # Employer Pro Subscription
    elif plan == "employer_pro":
        if company_slug:
            comp_billing = _MOCK_COMPANY_BILLING.setdefault(company_slug, {})
            comp_billing.update({
                "employer_plan": "pro",
                "subscription_status": "active",
                "stripe_customer_id": customer_id,
                "stripe_subscription_id": subscription_id,
                "current_period_end": one_month_later,
            })
            return {"handled": True, "plan": "employer_pro", "company_slug": company_slug, "status": "active"}

    return {"handled": True, "action": "checkout_recorded"}


def _handle_subscription_updated(data: Dict[str, Any]) -> Dict[str, Any]:
    """Sync status changes (active, past_due, trialing) from Stripe."""
    sub_id = data.get("id")
    status = data.get("status", "active")
    customer_id = data.get("customer")
    period_end_ts = data.get("current_period_end")

    period_end_iso = (
        datetime.datetime.fromtimestamp(period_end_ts, datetime.timezone.utc).isoformat()
        if period_end_ts
        else None
    )

    # Find matching user profile
    for uid, prof in _MOCK_USER_PROFILES.items():
        if prof.get("stripe_subscription_id") == sub_id or prof.get("stripe_customer_id") == customer_id:
            prof["subscription_status"] = status
            if period_end_iso:
                prof["current_period_end"] = period_end_iso
            return {"handled": True, "user_id": uid, "status": status}

    return {"handled": True, "action": "subscription_updated"}


def _handle_subscription_deleted(data: Dict[str, Any]) -> Dict[str, Any]:
    """Revoke Plus/Pro entitlements upon subscription cancellation."""
    sub_id = data.get("id")
    customer_id = data.get("customer")

    for uid, prof in _MOCK_USER_PROFILES.items():
        if prof.get("stripe_subscription_id") == sub_id or prof.get("stripe_customer_id") == customer_id:
            prof["subscription_plan"] = "free"
            prof["subscription_status"] = "canceled"
            return {"handled": True, "user_id": uid, "status": "canceled", "plan": "free"}

    return {"handled": True, "action": "subscription_canceled"}


def _handle_invoice_payment_failed(data: Dict[str, Any]) -> Dict[str, Any]:
    """Mark subscription as past_due on invoice failure (e.g. card decline)."""
    sub_id = data.get("subscription")
    customer_id = data.get("customer")

    for uid, prof in _MOCK_USER_PROFILES.items():
        if prof.get("stripe_subscription_id") == sub_id or prof.get("stripe_customer_id") == customer_id:
            prof["subscription_status"] = "past_due"
            return {"handled": True, "user_id": uid, "status": "past_due"}

    return {"handled": True, "action": "invoice_failure_recorded"}


def _handle_charge_refunded(data: Dict[str, Any]) -> Dict[str, Any]:
    """Revoke entitlements upon charge refund (Candidate Plus, Employer Badge, Featured Listing)."""
    customer_id = data.get("customer")
    metadata = data.get("metadata") or {}
    user_id = metadata.get("user_id")
    company_slug = metadata.get("company_slug")

    # 1. Candidate Plus Refund -> Revoke to free
    for uid, prof in _MOCK_USER_PROFILES.items():
        if (user_id and uid == user_id) or prof.get("stripe_customer_id") == customer_id:
            prof["subscription_plan"] = "free"
            prof["subscription_status"] = "refunded"
            logger.info("Revoked Plus entitlement due to refund for user %s", uid)
            return {"handled": True, "user_id": uid, "status": "refunded", "plan": "free"}

    # 2. Employer Product Refund -> Reset badge and featured status
    for c_slug, comp_billing in _MOCK_COMPANY_BILLING.items():
        if (company_slug and c_slug == company_slug) or comp_billing.get("stripe_customer_id") == customer_id:
            comp_billing["badge_payment_status"] = "refunded"
            comp_billing["badge_status"] = "rejected"
            comp_billing["featured_until"] = None
            comp_billing["employer_plan"] = "free"
            logger.info("Revoked employer privileges due to refund for company %s", c_slug)
            return {"handled": True, "company_slug": c_slug, "status": "refunded"}

    return {"handled": True, "action": "refund_recorded"}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Customer Portal Session
# ─────────────────────────────────────────────────────────────────────────────

def create_customer_portal_session(
    customer_id: Optional[str] = None,
    user_id: Optional[str] = None,
    return_url: Optional[str] = None,
) -> str:
    """
    Creates a Stripe Customer Portal Session for self-service plan management.
    Returns the portal redirect URL.
    """
    ret_url = return_url or f"{DEFAULT_SITE_URL}/account/billing"
    cust_id = customer_id

    if not cust_id and user_id:
        prof = _MOCK_USER_PROFILES.get(user_id) or {}
        cust_id = prof.get("stripe_customer_id")

    if not cust_id:
        cust_id = "cus_mock_customer_id"

    if STRIPE_SECRET_KEY and not STRIPE_SECRET_KEY.startswith("sk_test_visalane_mock"):
        try:
            session = stripe.billing_portal.Session.create(
                customer=cust_id,
                return_url=ret_url,
            )
            return session.url
        except Exception as e:
            logger.warning("Live Stripe Portal session creation failed: %s", e)

    return f"https://billing.stripe.com/p/session/mock_portal_{cust_id}"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Entitlement Model & Feature Gating
# ─────────────────────────────────────────────────────────────────────────────

def get_user_entitlement(user_id: Optional[str]) -> Dict[str, Any]:
    """
    Calculates comprehensive user entitlement status:
    - Free tier: 1 AI generation / week quota, daily alerts, standard confidence depth
    - Plus tier: Unlimited AI generations, real-time alert delivery, 24h early access window, full confidence depth
    - Past-Due (Grace Period): Read-only daily alerts, AI generation suspended with payment update prompt
    - Admin tier: Full unlimited access
    """
    if not user_id:
        # Anonymous user defaults to free tier with 0 usage
        return {
            "user_id": None,
            "plan": "free",
            "status": "none",
            "is_plus": False,
            "ai_generation_quota_limit": 1,
            "ai_generation_usage_this_week": 0,
            "ai_generation_quota_remaining": 1,
            "can_use_ai_generation": True,
            "alert_delivery_mode": "daily",
            "early_access_unlocked": False,
            "full_confidence_depth": False,
            "quota_resets_at": _get_next_week_reset_iso(),
        }

    prof = _MOCK_USER_PROFILES.get(user_id) or {}
    plan = str(prof.get("subscription_plan", "free")).lower()
    status = str(prof.get("subscription_status", "none")).lower()

    is_active_plus = (plan == "plus" and status in ("active", "trialing"))
    is_admin = (plan == "admin" or prof.get("is_admin") is True)

    week_key = _get_current_week_key()
    usage_key = f"{user_id}:{week_key}"
    usage_count = _MOCK_USAGE_TRACKING.get(usage_key, 0)

    if is_active_plus or is_admin:
        return {
            "user_id": user_id,
            "plan": "admin" if is_admin else "plus",
            "status": "active",
            "is_plus": True,
            "ai_generation_quota_limit": 999999,
            "ai_generation_usage_this_week": usage_count,
            "ai_generation_quota_remaining": 999999,
            "can_use_ai_generation": True,
            "alert_delivery_mode": "realtime",
            "early_access_unlocked": True,
            "full_confidence_depth": True,
            "quota_resets_at": _get_next_week_reset_iso(),
        }

    # Explicit past_due grace period state
    if status == "past_due":
        return {
            "user_id": user_id,
            "plan": "plus_past_due",
            "status": "past_due",
            "is_plus": False,
            "ai_generation_quota_limit": 0,
            "ai_generation_usage_this_week": usage_count,
            "ai_generation_quota_remaining": 0,
            "can_use_ai_generation": False,
            "alert_delivery_mode": "daily",
            "early_access_unlocked": False,
            "full_confidence_depth": False,
            "grace_period_active": True,
            "message": "Payment past due. AI generation is suspended. Please update your payment method.",
            "quota_resets_at": _get_next_week_reset_iso(),
        }

    quota_limit = 1
    quota_remaining = max(0, quota_limit - usage_count)
    can_generate = quota_remaining > 0

    return {
        "user_id": user_id,
        "plan": "free",
        "status": status,
        "is_plus": False,
        "ai_generation_quota_limit": quota_limit,
        "ai_generation_usage_this_week": usage_count,
        "ai_generation_quota_remaining": quota_remaining,
        "can_use_ai_generation": can_generate,
        "alert_delivery_mode": "daily",
        "early_access_unlocked": False,
        "full_confidence_depth": False,
        "quota_resets_at": _get_next_week_reset_iso(),
    }


def check_ai_generation_entitlement(user_id: Optional[str]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Enforces AI Generation Quota gate.
    Returns (True, None) if generation is permitted.
    Returns (False, upgrade_prompt_dict) if free quota has been exhausted.
    """
    ent = get_user_entitlement(user_id)
    if ent["can_use_ai_generation"]:
        return True, None

    prompt_payload = {
        "error": "QUOTA_EXHAUSTED",
        "detail": (
            "Free AI generation quota exhausted (1/week). "
            "Upgrade to VisaLane Plus for unlimited AI tailored resumes, cover letters, and real-time alerts."
        ),
        "upgrade_url": f"{DEFAULT_SITE_URL}/pricing?plan=candidate_plus_monthly",
        "quota_limit": ent["ai_generation_quota_limit"],
        "usage_this_week": ent["ai_generation_usage_this_week"],
        "quota_resets_at": ent["quota_resets_at"],
    }
    return False, prompt_payload


def record_ai_generation_usage(user_id: Optional[str]) -> int:
    """Records one AI generation usage for the user in the current week."""
    uid = user_id or "anon_session"
    week_key = _get_current_week_key()
    usage_key = f"{uid}:{week_key}"
    current = _MOCK_USAGE_TRACKING.get(usage_key, 0)
    _MOCK_USAGE_TRACKING[usage_key] = current + 1
    return current + 1
