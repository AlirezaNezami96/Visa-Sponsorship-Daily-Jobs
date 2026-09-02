"""
VisaLane Alert & Lifecycle Notification Engine.
Provides alert CRUD, entitlement-aware cadence gating, job matching with zero-match suppression,
multi-channel dispatch (Email + Telegram), token-based one-click unsubscribe,
and 5 lifecycle email sequences with GDPR/CAN-SPAM consent classification.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import html
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests as http_requests

from engine.api.alert_models import (
    AlertCreateRequest,
    AlertFilterCriteria,
    AlertResponse,
    AlertUpdateRequest,
    NotificationLog,
    ScheduledDigestRunResponse,
    TelegramLinkTokenResponse,
    UserPreferencesResponse,
)
from engine.api.billing_service import get_user_entitlement
from engine.api.canonical_data import find_country, find_visa_type

logger = logging.getLogger(__name__)

DEFAULT_SITE_URL = os.environ.get("NEXT_PUBLIC_SITE_URL", "https://visalane.com")
UNSUBSCRIBE_SECRET = os.environ.get("UNSUBSCRIBE_SECRET_KEY", "visalane_unsub_secret_key_2026")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "mock_telegram_bot_token")
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "VisaLaneBot")

# In-Memory Stores for local dev and testing
_MOCK_ALERTS_STORE: Dict[str, Dict[str, Any]] = {}
_MOCK_PREFERENCES_STORE: Dict[str, Dict[str, Any]] = {}
_MOCK_NOTIFICATION_LOGS: List[Dict[str, Any]] = []
_MOCK_TELEGRAM_LINK_TOKENS: Dict[str, Dict[str, Any]] = {}
_MOCK_TELEGRAM_MESSAGES: List[Dict[str, Any]] = []
_MOCK_SENT_EMAILS: List[Dict[str, Any]] = []


def clear_mock_alert_stores() -> None:
    """Clears all in-memory mock stores for test isolation."""
    _MOCK_ALERTS_STORE.clear()
    _MOCK_PREFERENCES_STORE.clear()
    _MOCK_NOTIFICATION_LOGS.clear()
    _MOCK_TELEGRAM_LINK_TOKENS.clear()
    _MOCK_TELEGRAM_MESSAGES.clear()
    _MOCK_SENT_EMAILS.clear()


def get_mock_sent_emails() -> List[Dict[str, Any]]:
    return _MOCK_SENT_EMAILS


def get_mock_telegram_messages() -> List[Dict[str, Any]]:
    return _MOCK_TELEGRAM_MESSAGES


def get_mock_notification_logs() -> List[Dict[str, Any]]:
    return _MOCK_NOTIFICATION_LOGS


# ─────────────────────────────────────────────────────────────────────────────
# 1. Cryptographic Token Generation (Unsubscribe & Telegram Link)
# ─────────────────────────────────────────────────────────────────────────────

def generate_unsubscribe_token(email: str, alert_id: Optional[str] = None) -> str:
    """
    Generates a secure, unguessable HMAC token for one-click no-login unsubscription.
    Format: base_token:signature
    """
    normalized_email = email.strip().lower()
    raw = f"{normalized_email}:{alert_id or 'all'}"
    sig = hmac.new(UNSUBSCRIBE_SECRET.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{sig}:{raw}"


def verify_unsubscribe_token(token: str) -> Optional[Tuple[str, Optional[str]]]:
    """
    Verifies an unsubscribe token.
    Returns (email, alert_id) if valid, None otherwise.
    """
    try:
        parts = token.split(":", 2)
        if len(parts) != 3:
            return None
        sig, email, raw_alert_id = parts[0], parts[1], parts[2]
        expected_raw = f"{email}:{raw_alert_id}"
        expected_sig = hmac.new(UNSUBSCRIBE_SECRET.encode("utf-8"), expected_raw.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected_sig):
            return None
        alert_id = None if raw_alert_id == "all" else raw_alert_id
        return email, alert_id
    except Exception as e:
        logger.warning("Failed to verify unsubscribe token: %s", e)
        return None


def create_telegram_link_token(user_id: Optional[str], email: str) -> TelegramLinkTokenResponse:
    """
    Generates a 15-minute temporary link token for candidate Telegram account binding.
    """
    token_str = uuid.uuid4().hex[:12]
    expires_at = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15)).isoformat()
    _MOCK_TELEGRAM_LINK_TOKENS[token_str] = {
        "user_id": user_id,
        "email": email.strip().lower(),
        "expires_at": expires_at,
    }
    return TelegramLinkTokenResponse(
        token=token_str,
        bot_username=TELEGRAM_BOT_USERNAME,
        link_command=f"/link {token_str}",
        link_url=f"https://t.me/{TELEGRAM_BOT_USERNAME}?start={token_str}",
        expires_at=expires_at,
    )


def consume_telegram_link_token(token: str, chat_id: str) -> Optional[Dict[str, Any]]:
    """
    Consumes a link token when a candidate sends /link {token} or /start {token} in Telegram.
    Associates telegram_chat_id with the user's preferences and active alerts.
    """
    data = _MOCK_TELEGRAM_LINK_TOKENS.get(token)
    if not data:
        return None

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if data["expires_at"] < now_iso:
        _MOCK_TELEGRAM_LINK_TOKENS.pop(token, None)
        return None

    email = data["email"]
    user_id = data["user_id"]

    # 1. Update user preferences
    pref = _MOCK_PREFERENCES_STORE.get(email) or {
        "email": email,
        "user_id": user_id,
        "marketing_opt_out": False,
    }
    pref["telegram_chat_id"] = str(chat_id)
    _MOCK_PREFERENCES_STORE[email] = pref

    # 2. Update all active alerts for this email to include telegram channel and chat_id
    linked_alerts_count = 0
    for a in _MOCK_ALERTS_STORE.values():
        if a.get("email") == email:
            a["telegram_chat_id"] = str(chat_id)
            if "telegram" not in a.get("channels", []):
                a["channels"].append("telegram")
            linked_alerts_count += 1

    _MOCK_TELEGRAM_LINK_TOKENS.pop(token, None)
    logger.info("Linked Telegram chat %s to VisaLane user %s (%s alerts updated)", chat_id, email, linked_alerts_count)
    return {
        "email": email,
        "user_id": user_id,
        "telegram_chat_id": str(chat_id),
        "linked_alerts_count": linked_alerts_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Entitlement Enforcement on Cadence
# ─────────────────────────────────────────────────────────────────────────────

def validate_cadence_entitlement(
    user_id: Optional[str],
    requested_cadence: str,
    downgrade_to_daily: bool = False,
) -> Tuple[bool, str, Optional[str]]:
    """
    Enforces subscription entitlement on alert notification frequency:
    - Free tier: supports 'daily' and 'weekly' digests only.
    - Plus tier (or Admin): unlocks 'instant' real-time job matching.
    Returns: (is_allowed, final_cadence, reason)
    """
    req_cad = requested_cadence.lower()
    if req_cad not in ("instant", "daily", "weekly"):
        return False, "daily", f"Invalid cadence '{requested_cadence}'. Must be instant, daily, or weekly."

    if req_cad != "instant":
        return True, req_cad, None

    # Evaluate subscription tier
    ent = get_user_entitlement(user_id)
    is_plus = ent.get("is_plus", False) or ent.get("plan") in ("plus", "admin")

    if is_plus:
        return True, "instant", None

    # Free tier requesting instant cadence
    if downgrade_to_daily:
        return (
            True,
            "daily",
            "Instant notifications are an exclusive VisaLane Plus feature. Your alert cadence was automatically set to 'daily'.",
        )

    return (
        False,
        "daily",
        "Instant alerts require an active VisaLane Plus membership. Free accounts support 'daily' or 'weekly' digests.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Matching Engine & Zero-Match Suppression
# ─────────────────────────────────────────────────────────────────────────────

def match_job_against_criteria(job: Dict[str, Any], criteria: AlertFilterCriteria) -> bool:
    """
    Evaluates whether a job posting matches the specified alert filter criteria.
    Mirrors canonical /api/v1/jobs search filtering rules.
    """
    # 1. Active status check
    status = str(job.get("status", "active")).lower()
    if status not in ("active", "published"):
        return False

    # 2. Country Filter
    if criteria.country:
        req_c = criteria.country.strip().lower()
        j_c_code = str(job.get("country_code", "")).strip().lower()
        j_c_name = str(job.get("country", "")).strip().lower()
        canon = find_country(req_c)
        j_canon = find_country(j_c_code) or find_country(j_c_name)
        if canon:
            canon_slug = canon["slug"].lower()
            canon_code = canon["code"].lower()
            canon_name = canon["name"].lower()
            if j_canon:
                if j_canon["slug"].lower() != canon_slug:
                    return False
            else:
                if j_c_code != canon_code and canon_slug not in j_c_name and canon_name not in j_c_name:
                    return False
        else:
            if req_c != j_c_code and req_c not in j_c_name:
                return False

    # 3. Visa Type Filter
    if criteria.visa_type:
        req_v = criteria.visa_type.strip().lower()
        j_v = str(job.get("visa_sponsorship_type", job.get("visa_type", ""))).lower()
        canon_v = find_visa_type(req_v)
        if canon_v:
            canon_slug = canon_v["slug"].lower()
            canon_name = canon_v["name"].lower()
            aliases = [a.lower() for a in canon_v.get("aliases", [])]
            if canon_slug not in j_v and canon_name not in j_v and not any(a in j_v for a in aliases):
                return False
        else:
            if req_v not in j_v:
                return False

    # 4. Keyword Filter (Title or Description)
    if criteria.keyword:
        kw = criteria.keyword.strip().lower()
        title = str(job.get("title", "")).lower()
        desc = str(job.get("description", "")).lower()
        if kw not in title and kw not in desc:
            return False

    # 5. Remote Eligibility Filter
    if criteria.is_remote is True:
        is_remote_job = job.get("is_remote") is True or "remote" in str(job.get("workplace_type", "")).lower()
        if not is_remote_job:
            return False

    # 6. Minimum Salary Filter
    if criteria.min_salary is not None and criteria.min_salary > 0:
        sal_max = job.get("salary_max") or 0
        sal_min = job.get("salary_min") or 0
        if max(sal_max, sal_min) < criteria.min_salary:
            return False

    # 7. Specific Company Filter
    if criteria.company_name:
        req_comp = criteria.company_name.strip().lower()
        j_comp = str(job.get("company_name", "")).strip().lower()
        if req_comp not in j_comp:
            return False

    # 8. Minimum Sponsorship Confidence Threshold
    if criteria.min_confidence is not None and criteria.min_confidence > 0:
        conf = job.get("visa_sponsorship_confidence", 100)
        if conf < criteria.min_confidence:
            return False

    # 9. Role Category Filter
    if criteria.role_category:
        req_cat = criteria.role_category.strip().lower()
        j_cat = str(job.get("category", job.get("role_category", ""))).lower()
        j_title = str(job.get("title", "")).lower()
        if req_cat not in j_cat and req_cat not in j_title:
            return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
# 4. Alert CRUD Handlers
# ─────────────────────────────────────────────────────────────────────────────

def create_alert(req: AlertCreateRequest) -> Tuple[Optional[AlertResponse], Optional[Dict[str, Any]]]:
    """
    Creates a new user alert with entitlement verification.
    Returns (AlertResponse, None) on success.
    Returns (None, error_payload) on entitlement rejection.
    """
    allowed, final_cadence, reason = validate_cadence_entitlement(
        user_id=req.user_id,
        requested_cadence=req.cadence,
        downgrade_to_daily=req.downgrade_to_daily,
    )

    if not allowed:
        return None, {
            "error": "INSTANT_CADENCE_RESTRICTED",
            "detail": reason,
            "upgrade_url": f"{DEFAULT_SITE_URL}/pricing?plan=candidate_plus_monthly",
        }

    alert_id = f"alt_{uuid.uuid4().hex[:12]}"
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    downgraded = (final_cadence != req.cadence)

    alert_record = {
        "id": alert_id,
        "user_id": req.user_id,
        "email": req.email.strip().lower(),
        "filter_criteria": req.filter_criteria.model_dump(),
        "cadence": final_cadence,
        "channels": list(set(req.channels)),
        "telegram_chat_id": req.telegram_chat_id,
        "is_active": True,
        "created_at": now_iso,
        "last_notified_at": None,
        "downgraded": downgraded,
        "downgrade_reason": reason if downgraded else None,
    }

    _MOCK_ALERTS_STORE[alert_id] = alert_record
    logger.info("Created alert %s for %s with cadence %s", alert_id, req.email, final_cadence)

    return (
        AlertResponse(
            id=alert_id,
            user_id=req.user_id,
            email=req.email.strip().lower(),
            filter_criteria=req.filter_criteria,
            cadence=final_cadence,
            channels=alert_record["channels"],
            telegram_chat_id=req.telegram_chat_id,
            is_active=True,
            created_at=now_iso,
            last_notified_at=None,
            downgraded=downgraded,
            downgrade_reason=reason if downgraded else None,
        ),
        None,
    )


def get_alert(alert_id: str) -> Optional[AlertResponse]:
    data = _MOCK_ALERTS_STORE.get(alert_id)
    if not data:
        return None
    return AlertResponse(**data)


def list_alerts(user_id: Optional[str] = None, email: Optional[str] = None) -> List[AlertResponse]:
    """Returns alerts filtered by user_id or email."""
    results = []
    for a in _MOCK_ALERTS_STORE.values():
        if user_id and a.get("user_id") == user_id:
            results.append(AlertResponse(**a))
        elif email and a.get("email") == email.strip().lower():
            results.append(AlertResponse(**a))
        elif not user_id and not email:
            results.append(AlertResponse(**a))
    return results


def update_alert(
    alert_id: str,
    req: AlertUpdateRequest,
    user_id: Optional[str] = None,
) -> Tuple[Optional[AlertResponse], Optional[Dict[str, Any]]]:
    """Updates an existing alert with entitlement re-validation if cadence changes."""
    alert = _MOCK_ALERTS_STORE.get(alert_id)
    if not alert:
        return None, {"error": "ALERT_NOT_FOUND", "detail": f"Alert with ID {alert_id} not found."}

    if user_id and alert.get("user_id") and alert.get("user_id") != user_id:
        return None, {"error": "FORBIDDEN", "detail": "You do not have permission to modify this alert."}

    downgraded = False
    downgrade_reason = None

    if req.cadence:
        allowed, final_cad, reason = validate_cadence_entitlement(
            user_id=user_id or alert.get("user_id"),
            requested_cadence=req.cadence,
            downgrade_to_daily=req.downgrade_to_daily,
        )
        if not allowed:
            return None, {
                "error": "INSTANT_CADENCE_RESTRICTED",
                "detail": reason,
                "upgrade_url": f"{DEFAULT_SITE_URL}/pricing?plan=candidate_plus_monthly",
            }
        alert["cadence"] = final_cad
        if final_cad != req.cadence:
            downgraded = True
            downgrade_reason = reason

    if req.filter_criteria is not None:
        alert["filter_criteria"] = req.filter_criteria.model_dump()
    if req.channels is not None:
        alert["channels"] = list(set(req.channels))
    if req.telegram_chat_id is not None:
        alert["telegram_chat_id"] = req.telegram_chat_id
    if req.is_active is not None:
        alert["is_active"] = req.is_active

    alert["downgraded"] = downgraded
    alert["downgrade_reason"] = downgrade_reason
    _MOCK_ALERTS_STORE[alert_id] = alert

    return AlertResponse(**alert), None


def delete_alert(alert_id: str, user_id: Optional[str] = None) -> bool:
    """Deletes or deactivates an alert."""
    alert = _MOCK_ALERTS_STORE.get(alert_id)
    if not alert:
        return False
    if user_id and alert.get("user_id") and alert.get("user_id") != user_id:
        return False
    _MOCK_ALERTS_STORE.pop(alert_id, None)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 5. Email Templates & Multi-Channel Dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def _render_alert_digest_email(alert: Dict[str, Any], jobs: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Renders HTML and subject line for Job Alert Digest."""
    match_count = len(jobs)
    country_name = alert.get("filter_criteria", {}).get("country") or "Global"
    country_label = country_name.replace("-", " ").title()

    subject = f"🧠 {match_count} new verified visa sponsorship {'role' if match_count == 1 else 'roles'} in {country_label}"
    unsub_token = generate_unsubscribe_token(alert["email"], alert["id"])
    unsub_url = f"{DEFAULT_SITE_URL}/api/v1/alerts/unsubscribe?token={unsub_token}"
    pref_url = f"{DEFAULT_SITE_URL}/account/alerts/preferences?token={unsub_token}"

    job_cards_html = ""
    for j in jobs[:10]:
        title = html.escape(str(j.get("title", "Untitled Role")))
        company = html.escape(str(j.get("company_name", "Confidential Employer")))
        country = html.escape(str(j.get("country", country_label)))
        visa_type = html.escape(str(j.get("visa_sponsorship_type", "Work Visa Sponsor")))
        conf = int(j.get("visa_sponsorship_confidence", 95))
        job_url = f"{DEFAULT_SITE_URL}/jobs/{j.get('id')}"

        job_cards_html += f"""
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:10px; padding:18px; margin-bottom:14px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h3 style="margin:0 0 6px 0; font-size:17px; font-weight:700; color:#0f172a;">
                    <a href="{job_url}" style="color:#0284c7; text-decoration:none;">{title}</a>
                </h3>
                <span style="background:#ecfdf5; color:#059669; font-size:12px; font-weight:600; padding:3px 8px; border-radius:6px;">{conf}% Verified</span>
            </div>
            <p style="margin:0 0 8px 0; color:#475569; font-size:14px;">🏢 {company} &nbsp;•&nbsp; 📍 {country} &nbsp;•&nbsp; 🛂 {visa_type}</p>
            <a href="{job_url}" style="display:inline-block; background:#0284c7; color:#ffffff; font-size:13px; font-weight:600; padding:7px 14px; border-radius:6px; text-decoration:none; margin-top:6px;">View & Apply →</a>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background:#f8fafc; margin:0; padding:24px;">
        <div style="max-width:620px; margin:0 auto; background:#ffffff; border-radius:12px; border:1px solid #e2e8f0; overflow:hidden;">
            <div style="background:#0f172a; padding:24px; text-align:center;">
                <h1 style="color:#ffffff; margin:0; font-size:22px; letter-spacing:-0.5px;">VisaLane Job Alert</h1>
                <p style="color:#94a3b8; margin:6px 0 0 0; font-size:14px;">Real-time international relocation & verified sponsorship openings</p>
            </div>
            <div style="padding:24px;">
                <p style="font-size:15px; color:#334155; margin-top:0;">We found <b>{match_count} new visa sponsorship opportunities</b> matching your search criteria:</p>
                {job_cards_html}
            </div>
            <div style="background:#f1f5f9; padding:18px 24px; text-align:center; font-size:12px; color:#64748b; border-top:1px solid #e2e8f0;">
                <p style="margin:0 0 6px 0;">You received this email because you subscribed to alert #{alert['id']}.</p>
                <p style="margin:0;">
                    <a href="{unsub_url}" style="color:#64748b; text-decoration:underline;">Unsubscribe from this alert</a> &nbsp;|&nbsp;
                    <a href="{pref_url}" style="color:#64748b; text-decoration:underline;">Manage Preferences</a>
                </p>
            </div>
        </div>
    </body>
    </html>
    """
    return subject, html_content


def _render_welcome_email(email: str, step: int) -> Tuple[str, str]:
    """Renders 3-part Welcome lifecycle email series (marketing)."""
    unsub_token = generate_unsubscribe_token(email, "marketing")
    unsub_url = f"{DEFAULT_SITE_URL}/api/v1/alerts/unsubscribe?token={unsub_token}&scope=all_marketing"

    if step == 1:
        subject = "Welcome to VisaLane: Your Visa Sponsorship Journey Starts Here"
        body = """
        <h2>Welcome to VisaLane! 🌍</h2>
        <p>We built VisaLane to cut through the noise of misleading visa policies and fake sponsor postings.</p>
        <p><b>Next Step:</b> Set your target country and visa alert to receive instant or daily alerts the moment a genuine verified sponsor publishes an eligible role.</p>
        """
    elif step == 2:
        subject = "How to Spot Real Visa Sponsors (and Avoid Self-Sponsor Scams)"
        body = """
        <h2>Spotting Real Sponsors vs Illusions 🛂</h2>
        <p>Did you know over 40% of postings tagged 'visa sponsorship available' actually require existing domestic work authorization?</p>
        <p>VisaLane cross-references every posting against official government sponsor registries (UK Home Office, German Chancenkarte registries, Dutch IND databases) before tagging a job as verified.</p>
        """
    else:
        subject = "2026 Salary Thresholds & Relocation Guide for Global Engineers"
        body = """
        <h2>Key 2026 Visa Threshold Updates 📊</h2>
        <p>Germany increased the Chancenkarte points baseline, and the UK Skilled Worker threshold has updated.</p>
        <p>Check our interactive guides and salary tools to verify your target offer meets official legal requirements.</p>
        """

    html_content = f"""
    <!DOCTYPE html><html><body style="font-family:sans-serif; background:#f8fafc; padding:24px;">
        <div style="max-width:600px; margin:0 auto; background:#ffffff; border-radius:10px; padding:24px; border:1px solid #e2e8f0;">
            {body}
            <div style="margin-top:24px; padding-top:16px; border-top:1px solid #e2e8f0; font-size:12px; color:#64748b;">
                <p>VisaLane Marketing Communications • <a href="{unsub_url}">Unsubscribe from marketing emails</a></p>
            </div>
        </div>
    </body></html>
    """
    return subject, html_content


def _render_reengagement_email(email: str, alert: Dict[str, Any]) -> Tuple[str, str]:
    """Renders 14-day re-engagement email (marketing)."""
    unsub_token = generate_unsubscribe_token(email, "marketing")
    unsub_url = f"{DEFAULT_SITE_URL}/api/v1/alerts/unsubscribe?token={unsub_token}&scope=all_marketing"
    subject = "New sponsorship activity on your saved VisaLane search"
    html_content = f"""
    <!DOCTYPE html><html><body style="font-family:sans-serif; background:#f8fafc; padding:24px;">
        <div style="max-width:600px; margin:0 auto; background:#ffffff; border-radius:10px; padding:24px; border:1px solid #e2e8f0;">
            <h2>Fresh verified roles waiting for you</h2>
            <p>It has been two weeks since you last visited VisaLane. New government-certified sponsors in your field have posted openings.</p>
            <p><a href="{DEFAULT_SITE_URL}/jobs" style="display:inline-block; background:#0284c7; color:#fff; padding:10px 18px; border-radius:6px; text-decoration:none;">Explore New Openings →</a></p>
            <div style="margin-top:24px; padding-top:16px; border-top:1px solid #e2e8f0; font-size:12px; color:#64748b;">
                <p><a href="{unsub_url}">Unsubscribe from re-engagement updates</a></p>
            </div>
        </div>
    </body></html>
    """
    return subject, html_content


def _render_winback_email(email: str, days_inactive: int) -> Tuple[str, str]:
    """Renders 30/60/90-day winback email (marketing)."""
    unsub_token = generate_unsubscribe_token(email, "marketing")
    unsub_url = f"{DEFAULT_SITE_URL}/api/v1/alerts/unsubscribe?token={unsub_token}&scope=all_marketing"
    subject = f"We miss you on VisaLane ({days_inactive} days of new sponsorship jobs)"
    html_content = f"""
    <!DOCTYPE html><html><body style="font-family:sans-serif; background:#f8fafc; padding:24px;">
        <div style="max-width:600px; margin:0 auto; background:#ffffff; border-radius:10px; padding:24px; border:1px solid #e2e8f0;">
            <h2>Global visa sponsorship has accelerated</h2>
            <p>Over {days_inactive} days, hundreds of companies have joined official sponsor registries.</p>
            <p><a href="{DEFAULT_SITE_URL}/jobs" style="display:inline-block; background:#0284c7; color:#fff; padding:10px 18px; border-radius:6px; text-decoration:none;">Check Latest Jobs →</a></p>
            <div style="margin-top:24px; padding-top:16px; border-top:1px solid #e2e8f0; font-size:12px; color:#64748b;">
                <p><a href="{unsub_url}">Opt out of winback emails</a></p>
            </div>
        </div>
    </body></html>
    """
    return subject, html_content


def _render_policy_alert_email(email: str, company_name: str, update_detail: str) -> Tuple[str, str]:
    """Renders Company Sponsorship Policy Alert (transactional)."""
    unsub_token = generate_unsubscribe_token(email, "policy")
    unsub_url = f"{DEFAULT_SITE_URL}/api/v1/alerts/unsubscribe?token={unsub_token}"
    subject = f"⚠️ Visa Sponsorship Policy Update: {company_name}"
    html_content = f"""
    <!DOCTYPE html><html><body style="font-family:sans-serif; background:#f8fafc; padding:24px;">
        <div style="max-width:600px; margin:0 auto; background:#ffffff; border-radius:10px; padding:24px; border:1px solid #e2e8f0;">
            <h2>Sponsorship Policy Update for {html.escape(company_name)}</h2>
            <p>We detected an important change in {html.escape(company_name)}'s visa sponsorship standing:</p>
            <div style="background:#f1f5f9; padding:14px; border-radius:8px; margin:16px 0; border-left:4px solid #0284c7;">
                {html.escape(update_detail)}
            </div>
            <div style="margin-top:24px; padding-top:16px; border-top:1px solid #e2e8f0; font-size:12px; color:#64748b;">
                <p>Transactional alert • <a href="{unsub_url}">Unsubscribe from company updates</a></p>
            </div>
        </div>
    </body></html>
    """
    return subject, html_content


def dispatch_email_notification(
    to_email: str,
    subject: str,
    html_content: str,
    consent_classification: str,
    headers: Optional[Dict[str, str]] = None,
    dry_run: bool = False,
) -> bool:
    """
    Dispatches transactional or marketing email with GDPR/CAN-SPAM consent enforcement.
    Adds RFC 2369 / RFC 8058 List-Unsubscribe headers.
    """
    email_norm = to_email.strip().lower()

    # 1. Marketing Consent Check
    if consent_classification == "marketing":
        pref = _MOCK_PREFERENCES_STORE.get(email_norm)
        if pref and pref.get("marketing_opt_out") is True:
            logger.info("Marketing email suppressed for %s due to marketing_opt_out preference.", email_norm)
            return False

    # 2. Add Standard Deliverability & Unsubscribe Headers
    unsub_token = generate_unsubscribe_token(email_norm)
    unsub_url = f"{DEFAULT_SITE_URL}/api/v1/alerts/unsubscribe?token={unsub_token}"
    dispatch_headers = {
        "List-Unsubscribe": f"<{unsub_url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        **(headers or {}),
    }

    send_record = {
        "to": email_norm,
        "subject": subject,
        "html": html_content,
        "consent_classification": consent_classification,
        "headers": dispatch_headers,
        "sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _MOCK_SENT_EMAILS.append(send_record)

    if dry_run:
        return True

    # Check for live Resend / SendGrid credentials
    resend_key = os.environ.get("RESEND_API_KEY")
    if resend_key and not resend_key.startswith("mock_"):
        try:
            r = http_requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
                json={
                    "from": os.environ.get("EMAIL_FROM", "alerts@visalane.com"),
                    "to": [email_norm],
                    "subject": subject,
                    "html": html_content,
                    "headers": dispatch_headers,
                },
                timeout=15,
            )
            return r.status_code in (200, 201)
        except Exception as e:
            logger.warning("Live email dispatch failed: %s", e)

    return True


def dispatch_telegram_alert(
    chat_id: str,
    jobs: List[Dict[str, Any]],
    dry_run: bool = False,
) -> bool:
    """
    Sends interactive job opportunity cards to candidate's linked Telegram chat.
    Reuses the bot infrastructure.
    """
    if not chat_id or not jobs:
        return False

    message_lines = [
        f"🌟 <b>VisaLane Alert: {len(jobs)} New Verified Sponsor {'Role' if len(jobs) == 1 else 'Roles'}</b>\n"
    ]
    for j in jobs[:5]:
        title = html.escape(str(j.get("title", "Role")))
        company = html.escape(str(j.get("company_name", "Company")))
        country = html.escape(str(j.get("country", "Global")))
        conf = int(j.get("visa_sponsorship_confidence", 95))
        url = f"{DEFAULT_SITE_URL}/jobs/{j.get('id')}"
        message_lines.append(
            f"💼 <b><a href=\"{url}\">{title}</a></b>\n"
            f"🏢 {company} | 📍 {country}\n"
            f"🛂 Verified Sponsorship ({conf}%)\n"
        )

    full_text = "\n".join(message_lines)
    _MOCK_TELEGRAM_MESSAGES.append({
        "chat_id": chat_id,
        "text": full_text,
        "sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })

    if dry_run or not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "mock_telegram_bot_token":
        return True

    try:
        r = http_requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": full_text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        logger.warning("Failed to dispatch live Telegram alert: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 6. Scheduled Digest Execution & Zero-Match Rule
# ─────────────────────────────────────────────────────────────────────────────

def run_scheduled_alert_digests(
    cadence: str = "daily",
    all_jobs: Optional[List[Dict[str, Any]]] = None,
    dry_run: bool = False,
) -> ScheduledDigestRunResponse:
    """
    Executes scheduled alert digest cycle for 'daily' or 'weekly' alerts.
    CRITICAL RULE: An alert with 0 new matching jobs sends NOTHING (zero-match suppression).
    """
    start_time = datetime.datetime.now(datetime.timezone.utc)
    target_cad = cadence.lower()

    if all_jobs is None:
        from engine.api.jobs_routes import _MOCK_JOBS_STORE
        all_jobs = list(_MOCK_JOBS_STORE)

    active_jobs = [j for j in all_jobs if str(j.get("status", "active")).lower() in ("active", "published")]

    alerts_evaluated = 0
    digests_sent = 0
    zero_suppressed = 0
    marketing_suppressed = 0
    errors = 0

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff_hours = 24 if target_cad == "daily" else 168

    for alert_id, alert in list(_MOCK_ALERTS_STORE.items()):
        if not alert.get("is_active"):
            continue
        if alert.get("cadence") != target_cad:
            continue

        alerts_evaluated += 1
        last_notified = alert.get("last_notified_at")
        criteria = AlertFilterCriteria(**(alert.get("filter_criteria") or {}))

        # Filter jobs created since last notification
        matching_new_jobs = []
        for j in active_jobs:
            if match_job_against_criteria(j, criteria):
                # Filter by creation time if available
                created_str = j.get("created_at") or j.get("date_posted")
                if created_str and last_notified:
                    try:
                        dt_created = datetime.datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                        dt_last = datetime.datetime.fromisoformat(last_notified.replace("Z", "+00:00"))
                        if dt_created <= dt_last:
                            continue
                    except Exception:
                        pass
                matching_new_jobs.append(j)

        # Zero-Match Rule: An alert with 0 new matches sends NOTHING
        if not matching_new_jobs:
            zero_suppressed += 1
            _MOCK_NOTIFICATION_LOGS.append({
                "id": f"log_{uuid.uuid4().hex[:12]}",
                "alert_id": alert_id,
                "recipient_email": alert["email"],
                "status": "suppressed",
                "job_count": 0,
                "sent_at": now.isoformat(),
                "reason": "zero_matches",
            })
            continue

        # Render and dispatch
        channels = alert.get("channels", ["email"])
        sent_any = False

        if "email" in channels:
            sub, body = _render_alert_digest_email(alert, matching_new_jobs)
            email_ok = dispatch_email_notification(
                to_email=alert["email"],
                subject=sub,
                html_content=body,
                consent_classification="transactional",
                dry_run=dry_run,
            )
            if email_ok:
                sent_any = True

        if "telegram" in channels and alert.get("telegram_chat_id"):
            tg_ok = dispatch_telegram_alert(
                chat_id=alert["telegram_chat_id"],
                jobs=matching_new_jobs,
                dry_run=dry_run,
            )
            if tg_ok:
                sent_any = True

        if sent_any:
            digests_sent += 1
            alert["last_notified_at"] = now.isoformat()
            _MOCK_NOTIFICATION_LOGS.append({
                "id": f"log_{uuid.uuid4().hex[:12]}",
                "alert_id": alert_id,
                "recipient_email": alert["email"],
                "status": "sent",
                "job_count": len(matching_new_jobs),
                "job_ids": [str(j.get("id")) for j in matching_new_jobs[:10]],
                "sent_at": now.isoformat(),
            })

    elapsed_ms = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds() * 1000
    return ScheduledDigestRunResponse(
        cadence=target_cad,
        alerts_evaluated=alerts_evaluated,
        digests_sent=digests_sent,
        alerts_suppressed_zero_matches=zero_suppressed,
        marketing_suppressed=marketing_suppressed,
        errors=errors,
        execution_time_ms=round(elapsed_ms, 2),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 7. Instant Match Hook
# ─────────────────────────────────────────────────────────────────────────────

def notify_instant_alerts_for_new_job(job: Dict[str, Any], dry_run: bool = False) -> int:
    """
    Hook triggered when a new job posting is created or indexed.
    Checks all active 'instant' cadence alerts and enqueues immediate notifications.
    """
    if str(job.get("status", "active")).lower() not in ("active", "published"):
        return 0

    dispatched_count = 0
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for alert_id, alert in _MOCK_ALERTS_STORE.items():
        if not alert.get("is_active"):
            continue
        if alert.get("cadence") != "instant":
            continue

        criteria = AlertFilterCriteria(**(alert.get("filter_criteria") or {}))
        if match_job_against_criteria(job, criteria):
            channels = alert.get("channels", ["email"])
            sent_any = False

            if "email" in channels:
                sub, body = _render_alert_digest_email(alert, [job])
                ok = dispatch_email_notification(
                    to_email=alert["email"],
                    subject=f"⚡ Instant Match: {job.get('title')} at {job.get('company_name')}",
                    html_content=body,
                    consent_classification="transactional",
                    dry_run=dry_run,
                )
                if ok:
                    sent_any = True

            if "telegram" in channels and alert.get("telegram_chat_id"):
                tg_ok = dispatch_telegram_alert(
                    chat_id=alert["telegram_chat_id"],
                    jobs=[job],
                    dry_run=dry_run,
                )
                if tg_ok:
                    sent_any = True

            if sent_any:
                dispatched_count += 1
                alert["last_notified_at"] = now_iso
                _MOCK_NOTIFICATION_LOGS.append({
                    "id": f"log_{uuid.uuid4().hex[:12]}",
                    "alert_id": alert_id,
                    "recipient_email": alert["email"],
                    "status": "sent",
                    "job_count": 1,
                    "job_ids": [str(job.get("id"))],
                    "sent_at": now_iso,
                    "type": "instant",
                })

    return dispatched_count


# ─────────────────────────────────────────────────────────────────────────────
# 8. Unsubscribe & Preference Center
# ─────────────────────────────────────────────────────────────────────────────

def process_unsubscribe(
    token: str,
    alert_id: Optional[str] = None,
    scope: str = "alert_only",
) -> Tuple[bool, str, Optional[str]]:
    """
    Executes one-click token-based unsubscribe without requiring login.
    Scopes:
    - 'alert_only': Deactivates the specified alert_id.
    - 'all_marketing': Sets marketing_opt_out=True on user preferences.
    - 'all_notifications': Deactivates all alerts for that email and sets marketing_opt_out=True.
    """
    verified = verify_unsubscribe_token(token)
    if not verified:
        return False, "Invalid or expired unsubscribe token.", None

    email, token_alert_id = verified
    target_alert_id = alert_id or token_alert_id

    pref = _MOCK_PREFERENCES_STORE.get(email) or {
        "email": email,
        "marketing_opt_out": False,
    }

    if scope == "all_marketing":
        pref["marketing_opt_out"] = True
        _MOCK_PREFERENCES_STORE[email] = pref
        return True, f"Successfully opted out of all VisaLane marketing emails for {email}.", email

    if scope == "all_notifications":
        pref["marketing_opt_out"] = True
        _MOCK_PREFERENCES_STORE[email] = pref
        count = 0
        for a in _MOCK_ALERTS_STORE.values():
            if a.get("email") == email:
                a["is_active"] = False
                count += 1
        return True, f"Successfully unsubscribed from all {count} alert(s) and marketing emails for {email}.", email

    # Default 'alert_only'
    if target_alert_id:
        target_a = _MOCK_ALERTS_STORE.get(target_alert_id)
        if target_a and target_a.get("email") == email:
            target_a["is_active"] = False
            return True, f"Successfully unsubscribed alert #{target_alert_id}.", email

    # Fallback to muting any active alert for this email if no specific ID matched
    found = False
    for a in _MOCK_ALERTS_STORE.values():
        if a.get("email") == email and a.get("is_active"):
            a["is_active"] = False
            found = True
            break

    if found:
        return True, f"Successfully deactivated alert for {email}.", email

    return True, f"Email {email} has no active alerts.", email


def get_user_preferences(email_or_token: str) -> Optional[UserPreferencesResponse]:
    """Retrieves preference center state for a verified token or authenticated email."""
    email = email_or_token.strip().lower()
    if ":" in email_or_token:
        verified = verify_unsubscribe_token(email_or_token)
        if verified:
            email = verified[0]

    pref = _MOCK_PREFERENCES_STORE.get(email) or {"email": email, "marketing_opt_out": False}
    user_alerts = [a for a in _MOCK_ALERTS_STORE.values() if a.get("email") == email and a.get("is_active")]

    channels = set()
    for a in user_alerts:
        for c in a.get("channels", []):
            channels.add(c)

    return UserPreferencesResponse(
        email=email,
        marketing_opt_out=pref.get("marketing_opt_out", False),
        telegram_linked=bool(pref.get("telegram_chat_id")),
        telegram_chat_id=pref.get("telegram_chat_id"),
        active_alerts_count=len(user_alerts),
        configured_channels=sorted(list(channels)),
    )
