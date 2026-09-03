"""
Partner and Affiliate Infrastructure Service Layer for VisaLane (Phase 12).
Handles cloaked affiliate redirects with rapid-click debounce,
inbound partner referral code capture surviving multi-step signup,
first-touch partner attribution lock on user profiles,
and audit-grade admin performance & commission reporting.
"""
from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from engine.api.partner_models import (
    AffiliateClick,
    AffiliatePartner,
    MultiStepSignupResponse,
    PartnerReferralCode,
    PartnerReportResponse,
    ReferralValidationResponse,
)

logger = logging.getLogger("visalane.partner")

# ═════════════════════════════════════════════════════════════════════════════
# In-Memory Storage & Registries
# ═════════════════════════════════════════════════════════════════════════════

_MOCK_AFFILIATE_PARTNERS: Dict[str, AffiliatePartner] = {}
_MOCK_AFFILIATE_SLUGS: Dict[str, str] = {}  # slug -> partner_id
_MOCK_AFFILIATE_CLICKS: List[AffiliateClick] = []
_MOCK_PARTNER_CODES: Dict[str, PartnerReferralCode] = {}  # UPPERCASE_CODE -> PartnerReferralCode
_MOCK_SESSION_REFERRALS: Dict[str, str] = {}  # session_id -> UPPERCASE_CODE
_MOCK_MULTI_STEP_SIGNUPS: Dict[str, Dict[str, Any]] = {}  # session_id -> step data
_MOCK_USER_PARTNER_ATTRIBUTIONS: Dict[str, str] = {}  # user_id -> locked partner_code


def _seed_default_partners():
    """Seed confirmed real partners in accordance with Section 0 prerequisites."""
    # 1. Affiliate Partner: Expat International Banking
    revolut = AffiliatePartner(
        id="aff_revolut_expat",
        slug="revolut-expat",
        name="Revolut International Banking",
        category="banking",
        destination_url_template="https://revolut.com/promo/global-talent?visalane_session={session_id}&utm_source=visalane&utm_medium=affiliate",
        commission_structure={"type": "flat", "amount_usd": 35.00, "event": "account_opened"},
        status="active",
        created_at="2026-08-01T00:00:00Z",
    )
    _MOCK_AFFILIATE_PARTNERS[revolut.id] = revolut
    _MOCK_AFFILIATE_SLUGS[revolut.slug] = revolut.id

    # 2. Affiliate Partner: Global Health Insurance
    cigna = AffiliatePartner(
        id="aff_cigna_global",
        slug="cigna-global",
        name="Cigna Global Health",
        category="insurance",
        destination_url_template="https://cignaglobal.com/expat-plans?aff_sub={session_id}&ref=visalane",
        commission_structure={"type": "percentage", "rate_pct": 15.0, "estimated_avg_order_usd": 800.0, "event": "first_year_premium"},
        status="active",
        created_at="2026-08-01T00:00:00Z",
    )
    _MOCK_AFFILIATE_PARTNERS[cigna.id] = cigna
    _MOCK_AFFILIATE_SLUGS[cigna.slug] = cigna.id

    # 3. Referral Partner: Immigration Law Firm
    fragomen = AffiliatePartner(
        id="part_fragomen_law",
        slug="fragomen-law",
        name="Fragomen Immigration Law",
        category="legal",
        destination_url_template="https://www.fragomen.com/services/visalane-talent?partner_ref={session_id}",
        commission_structure={"type": "flat", "amount_usd": 100.00, "event": "consultation_booked"},
        status="active",
        created_at="2026-08-01T00:00:00Z",
    )
    _MOCK_AFFILIATE_PARTNERS[fragomen.id] = fragomen
    _MOCK_AFFILIATE_SLUGS[fragomen.slug] = fragomen.id
    code_fragomen = PartnerReferralCode(
        id="code_fragomen_01",
        partner_id=fragomen.id,
        code="FRAGOMEN2026",
        created_at="2026-08-01T00:00:00Z",
    )
    _MOCK_PARTNER_CODES[code_fragomen.code.upper()] = code_fragomen

    # 4. Referral Partner: Tech Career Bootcamp
    springboard = AffiliatePartner(
        id="part_springboard_tech",
        slug="springboard-tech",
        name="Springboard Global Careers",
        category="education",
        destination_url_template="https://springboard.com/workshops/visas?code=SPRINGBOARD_VISA&session={session_id}",
        commission_structure={"type": "flat", "amount_usd": 50.00, "event": "activated_user"},
        status="active",
        created_at="2026-08-01T00:00:00Z",
    )
    _MOCK_AFFILIATE_PARTNERS[springboard.id] = springboard
    _MOCK_AFFILIATE_SLUGS[springboard.slug] = springboard.id
    code_springboard = PartnerReferralCode(
        id="code_springboard_01",
        partner_id=springboard.id,
        code="SPRINGBOARD_VISA",
        created_at="2026-08-01T00:00:00Z",
    )
    _MOCK_PARTNER_CODES[code_springboard.code.upper()] = code_springboard


# Initialize default partners
_seed_default_partners()


def clear_mock_partner_stores():
    """Reset all partner and affiliate stores to initial default state."""
    _MOCK_AFFILIATE_PARTNERS.clear()
    _MOCK_AFFILIATE_SLUGS.clear()
    _MOCK_AFFILIATE_CLICKS.clear()
    _MOCK_PARTNER_CODES.clear()
    _MOCK_SESSION_REFERRALS.clear()
    _MOCK_MULTI_STEP_SIGNUPS.clear()
    _MOCK_USER_PARTNER_ATTRIBUTIONS.clear()
    _seed_default_partners()


# ═════════════════════════════════════════════════════════════════════════════
# 1. Affiliate Lookup & Redirect Service
# ═════════════════════════════════════════════════════════════════════════════

def get_affiliate_partner_by_slug(slug: str) -> Optional[AffiliatePartner]:
    """Retrieve an active affiliate partner by its URL slug."""
    slug_norm = slug.strip().lower()
    partner_id = _MOCK_AFFILIATE_SLUGS.get(slug_norm)
    if not partner_id:
        return None
    partner = _MOCK_AFFILIATE_PARTNERS.get(partner_id)
    if partner and partner.status == "active":
        return partner
    return None


def get_affiliate_partner_by_id(partner_id: str) -> Optional[AffiliatePartner]:
    """Retrieve an affiliate partner by its unique partner ID."""
    return _MOCK_AFFILIATE_PARTNERS.get(partner_id)


def build_destination_url(partner: AffiliatePartner, session_id: str, user_id: Optional[str] = None) -> str:
    """Interpolate tracking parameters into the partner destination template."""
    dest = partner.destination_url_template
    dest = dest.replace("{session_id}", session_id or "anonymous")
    dest = dest.replace("{user_id}", user_id or "")
    return dest


def record_affiliate_click(
    partner_id: str,
    session_id: str,
    user_id: Optional[str] = None,
    debounce_window_sec: float = 5.0,
    timestamp: Optional[datetime.datetime] = None,
) -> Tuple[AffiliateClick, str]:
    """
    Records an outbound click to an affiliate partner.
    Anti-Shortcut Rule: Debounces rapid repeated clicks from the same session
    within `debounce_window_sec` to prevent double-counting and volume distortion.
    """
    partner = _MOCK_AFFILIATE_PARTNERS.get(partner_id)
    if not partner:
        raise ValueError(f"Unknown partner ID: {partner_id}")

    now = timestamp or datetime.datetime.now(datetime.timezone.utc)
    is_duplicate = False

    # Check for rapid repeated click from same session on this partner
    for prior_click in reversed(_MOCK_AFFILIATE_CLICKS):
        if prior_click.partner_id == partner_id and prior_click.session_id == session_id:
            try:
                prior_dt = datetime.datetime.fromisoformat(prior_click.created_at)
                if abs((now - prior_dt).total_seconds()) <= debounce_window_sec:
                    is_duplicate = True
                    break
            except Exception:
                pass

    click = AffiliateClick(
        id=f"clk_{uuid.uuid4().hex[:12]}",
        partner_id=partner_id,
        session_id=session_id,
        user_id=user_id,
        is_duplicate=is_duplicate,
        created_at=now.isoformat(),
    )
    _MOCK_AFFILIATE_CLICKS.append(click)

    dest_url = build_destination_url(partner, session_id=session_id, user_id=user_id)
    logger.info(
        "Recorded affiliate click [id=%s, partner=%s, session=%s, duplicate=%s] -> %s",
        click.id,
        partner_id,
        session_id,
        is_duplicate,
        dest_url,
    )
    return click, dest_url


# ═════════════════════════════════════════════════════════════════════════════
# 2. Inbound Partner Referral Code Capture & Multi-Step Lifecycle
# ═════════════════════════════════════════════════════════════════════════════

def validate_referral_code(code: str) -> ReferralValidationResponse:
    """Validate whether an inbound referral code exists and is active."""
    code_norm = code.strip().upper()
    ref_record = _MOCK_PARTNER_CODES.get(code_norm)
    if not ref_record:
        return ReferralValidationResponse(valid=False, code=code_norm)

    partner = _MOCK_AFFILIATE_PARTNERS.get(ref_record.partner_id)
    if not partner or partner.status != "active":
        return ReferralValidationResponse(valid=False, code=code_norm)

    return ReferralValidationResponse(
        valid=True,
        code=code_norm,
        partner_id=partner.id,
        partner_name=partner.name,
        category=partner.category,
    )


def capture_landing_referral_code(session_id: str, code: str) -> Optional[str]:
    """
    Captures referral code on initial landing and binds it to the visitor session.
    Returns the validated code if valid, or None.
    """
    validation = validate_referral_code(code)
    if validation.valid:
        _MOCK_SESSION_REFERRALS[session_id] = validation.code
        logger.info("Captured partner referral code '%s' for session '%s'", validation.code, session_id)
        return validation.code
    return None


def get_session_referral_code(session_id: str) -> Optional[str]:
    """Retrieve any partner referral code captured for this session."""
    return _MOCK_SESSION_REFERRALS.get(session_id)


def lock_user_partner_referral(
    user_id: str,
    referral_code: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    """
    Strict First-Touch Rule:
    Locks the partner referral code onto the user profile at account creation.
    - If user is already locked to a code, it is NEVER overwritten.
    - If referral_code is provided explicitly, it is validated.
    - Otherwise, falls back to code stored on the visitor session.
    """
    # 1. Check if already locked
    if user_id in _MOCK_USER_PARTNER_ATTRIBUTIONS:
        existing = _MOCK_USER_PARTNER_ATTRIBUTIONS[user_id]
        logger.info("User %s already locked to partner referral code %s (cannot overwrite)", user_id, existing)
        return existing

    candidate_code = referral_code
    if not candidate_code and session_id:
        candidate_code = _MOCK_SESSION_REFERRALS.get(session_id)

    if not candidate_code:
        return None

    val = validate_referral_code(candidate_code)
    if not val.valid:
        return None

    # Permanently lock attribution
    _MOCK_USER_PARTNER_ATTRIBUTIONS[user_id] = val.code

    # Synchronize with user profile in billing/account store if present
    from engine.api.billing_service import _MOCK_USER_PROFILES
    if user_id in _MOCK_USER_PROFILES:
        _MOCK_USER_PROFILES[user_id]["referred_by_partner_code"] = val.code

    logger.info("Permanently locked user %s to partner referral code %s", user_id, val.code)
    return val.code


# ═════════════════════════════════════════════════════════════════════════════
# 3. Multi-Step Signup Progression (Survival Verification)
# ═════════════════════════════════════════════════════════════════════════════

def signup_step1(session_id: str, email: str, password: str, referral_code: Optional[str] = None) -> MultiStepSignupResponse:
    """Step 1: Save credentials and persist initial landing referral code into session state."""
    # Capture or preserve referral code
    active_code = None
    if referral_code:
        active_code = capture_landing_referral_code(session_id, referral_code)
    if not active_code:
        active_code = get_session_referral_code(session_id)

    _MOCK_MULTI_STEP_SIGNUPS[session_id] = {
        "step": 1,
        "email": email.strip().lower(),
        "password": password,
        "referral_code": active_code,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    return MultiStepSignupResponse(
        session_id=session_id,
        email=email,
        current_step=1,
        referred_by_partner_code=active_code,
        status="step1_complete",
    )


def signup_step2(session_id: str, visa_status: str, target_role: str) -> MultiStepSignupResponse:
    """Step 2: Collect immigration and career preferences while carrying referral code."""
    data = _MOCK_MULTI_STEP_SIGNUPS.get(session_id)
    if not data or data.get("step") < 1:
        raise ValueError("Invalid session state: step 1 must be completed before step 2.")

    data["step"] = 2
    data["visa_status"] = visa_status
    data["target_role"] = target_role

    return MultiStepSignupResponse(
        session_id=session_id,
        email=data["email"],
        current_step=2,
        referred_by_partner_code=data.get("referral_code"),
        status="step2_complete",
    )


def signup_complete(session_id: str, full_name: str) -> MultiStepSignupResponse:
    """
    Step 3: Finalize registration.
    Locks the partner referral code permanently onto the created user profile.
    """
    data = _MOCK_MULTI_STEP_SIGNUPS.get(session_id)
    if not data or data.get("step") < 2:
        raise ValueError("Invalid session state: steps 1 and 2 must be completed before completion.")

    user_id = f"usr_{uuid.uuid4().hex[:12]}"
    email = data["email"]
    code = data.get("referral_code")

    # Seed user profile in billing store
    from engine.api.billing_service import _MOCK_USER_PROFILES
    _MOCK_USER_PROFILES[user_id] = {
        "id": user_id,
        "email": email,
        "full_name": full_name,
        "visa_status": data.get("visa_status"),
        "target_role": data.get("target_role"),
        "subscription_plan": "free",
        "subscription_status": "none",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    # Lock partner referral code permanently
    locked_code = lock_user_partner_referral(user_id=user_id, referral_code=code, session_id=session_id)

    # Ingest user_signed_up event into analytics/event store
    from engine.api.jobs_routes import _MOCK_EVENTS_STORE
    _MOCK_EVENTS_STORE.append({
        "event_name": "user_signed_up",
        "user_id": user_id,
        "session_id": session_id,
        "metadata": {"referred_by_partner_code": locked_code, "full_name": full_name},
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })

    data["step"] = 3
    data["user_id"] = user_id
    data["completed"] = True

    return MultiStepSignupResponse(
        session_id=session_id,
        user_id=user_id,
        email=email,
        current_step=3,
        referred_by_partner_code=locked_code,
        status="account_created",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 4. Admin Partner Reporting & Commission Engine
# ═════════════════════════════════════════════════════════════════════════════

def generate_partner_report(
    partner_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> PartnerReportResponse:
    """
    Generates an audit-grade partner report detailing:
    - Click volume (total vs distinct de-duplicated)
    - Referred signups (users locked to partner's code)
    - Activated users (by Phase 10's formal locked definition)
    - Calculated commission matching exact commission contract rules
    """
    partner = _MOCK_AFFILIATE_PARTNERS.get(partner_id)
    if not partner:
        raise ValueError(f"Partner '{partner_id}' not found.")

    # Find referral code associated with this partner (if any)
    partner_code: Optional[str] = None
    for pcode in _MOCK_PARTNER_CODES.values():
        if pcode.partner_id == partner_id:
            partner_code = pcode.code
            break

    # Parse date boundaries
    start_dt = None
    end_dt = None
    if start_date:
        try:
            start_dt = datetime.datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        except Exception:
            start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)

    if end_date:
        try:
            end_dt = datetime.datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except Exception:
            end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(hour=23, minute=59, second=59, tzinfo=datetime.timezone.utc)

    # 1. Click Analysis
    partner_clicks = [c for c in _MOCK_AFFILIATE_CLICKS if c.partner_id == partner_id]
    if start_dt or end_dt:
        filtered_clicks = []
        for c in partner_clicks:
            cdt = datetime.datetime.fromisoformat(c.created_at.replace("Z", "+00:00"))
            if cdt.tzinfo is None:
                cdt = cdt.replace(tzinfo=datetime.timezone.utc)
            if start_dt and cdt < start_dt:
                continue
            if end_dt and cdt > end_dt:
                continue
            filtered_clicks.append(c)
        partner_clicks = filtered_clicks

    total_clicks = len(partner_clicks)
    unique_clicks = len([c for c in partner_clicks if not c.is_duplicate])

    # 2. Referred Signups Analysis
    # A user is referred by this partner if _MOCK_USER_PARTNER_ATTRIBUTIONS[uid] == partner_code
    from engine.api.billing_service import _MOCK_USER_PROFILES
    from engine.api.analytics_service import is_user_or_session_activated

    referred_user_ids: List[str] = []
    if partner_code:
        for uid, code in _MOCK_USER_PARTNER_ATTRIBUTIONS.items():
            if code == partner_code:
                # Filter by creation date if present
                uprof = _MOCK_USER_PROFILES.get(uid, {})
                u_created = uprof.get("created_at")
                if u_created and (start_dt or end_dt):
                    udt = datetime.datetime.fromisoformat(u_created.replace("Z", "+00:00"))
                    if udt.tzinfo is None:
                        udt = udt.replace(tzinfo=datetime.timezone.utc)
                    if start_dt and udt < start_dt:
                        continue
                    if end_dt and udt > end_dt:
                        continue
                referred_user_ids.append(uid)

    referred_signups = len(referred_user_ids)

    # 3. Activation Analysis (Phase 10 locked definition: alert or >=3 distinct job views)
    activated_users_count = 0
    for uid in referred_user_ids:
        if is_user_or_session_activated(user_id=uid):
            activated_users_count += 1

    activation_rate = 0.0
    if referred_signups > 0:
        activation_rate = round((activated_users_count / referred_signups) * 100.0, 2)

    # 4. Commission Calculation
    comm_rule = partner.commission_structure or {}
    comm_type = comm_rule.get("type", "flat")
    comm_amount = float(comm_rule.get("amount_usd", 0.0))
    comm_rate = float(comm_rule.get("rate_pct", 0.0))
    comm_event = comm_rule.get("event", "user_signup")

    estimated_commission = 0.0
    breakdown: Dict[str, Any] = {"rule": comm_rule}

    if comm_type == "flat":
        if comm_event in ("activated_user", "activated_users"):
            estimated_commission = round(activated_users_count * comm_amount, 2)
            breakdown["basis"] = f"{activated_users_count} activated users @ ${comm_amount:.2f}"
        elif comm_event in ("click", "unique_click"):
            estimated_commission = round(unique_clicks * comm_amount, 2)
            breakdown["basis"] = f"{unique_clicks} unique clicks @ ${comm_amount:.2f}"
        else:
            # Default flat per signup/account
            estimated_commission = round(referred_signups * comm_amount, 2)
            breakdown["basis"] = f"{referred_signups} referred signups @ ${comm_amount:.2f}"
    elif comm_type == "percentage":
        avg_val = float(comm_rule.get("estimated_avg_order_usd", 100.0))
        estimated_commission = round(referred_signups * avg_val * (comm_rate / 100.0), 2)
        breakdown["basis"] = f"{referred_signups} orders @ avg ${avg_val:.2f} * {comm_rate}%"

    return PartnerReportResponse(
        partner_id=partner.id,
        partner_name=partner.name,
        category=partner.category,
        referral_code=partner_code,
        total_clicks=total_clicks,
        unique_clicks=unique_clicks,
        referred_signups=referred_signups,
        activated_users=activated_users_count,
        activation_rate_pct=activation_rate,
        estimated_commission_usd=estimated_commission,
        commission_breakdown=breakdown,
        period_start=start_date or "all_time",
        period_end=end_date or "current",
    )
