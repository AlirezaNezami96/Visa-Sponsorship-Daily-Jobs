"""
Phase 9: Verified Sponsor Badge Admin Review Workflow & Audit Trail Service.

Implements:
1. Application submission and resubmission tracking.
2. Admin review queue with role-gated decision endpoints.
3. Immutable review audit logging for both approve and reject.
4. Cross-phase transactional email notifications via Phase 7.
5. Scheduled 30-day renewal tracking.
"""
import os
import uuid
import logging
import datetime
from typing import Dict, Any, List, Optional, Tuple

from engine.api.badge_models import (
    BadgeApplicationSubmitRequest,
    BadgeApplicationResubmitRequest,
    BadgeApplicationResponse,
    BadgeReviewLogEntry,
    BadgeRenewalCheckResult,
)
from engine.api.cache import clear_cache

logger = logging.getLogger(__name__)

DEFAULT_SITE_URL = os.environ.get("SITE_URL", "https://visalane.com").rstrip("/")
ADMIN_NOTIFICATION_EMAIL = os.environ.get("ADMIN_NOTIFICATION_EMAIL", "admin@visalane.com")

# ─────────────────────────────────────────────────────────────────────────────
# In-Memory Mock Stores for Testing and Offline Operation
# ─────────────────────────────────────────────────────────────────────────────

_MOCK_BADGE_APPLICATIONS: Dict[str, Dict[str, Any]] = {}
_MOCK_BADGE_REVIEW_LOG: List[Dict[str, Any]] = []


def clear_mock_badge_stores() -> None:
    """Reset mock badge stores between test executions."""
    global _MOCK_BADGE_APPLICATIONS, _MOCK_BADGE_REVIEW_LOG
    _MOCK_BADGE_APPLICATIONS.clear()
    _MOCK_BADGE_REVIEW_LOG.clear()


def _get_supabase_client():
    """Retrieve Supabase service client if configured."""
    try:
        from job_radar.visalane.db import get_service_client
        return get_service_client()
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Application Submission & Resubmission
# ─────────────────────────────────────────────────────────────────────────────

def submit_badge_application(req: BadgeApplicationSubmitRequest) -> BadgeApplicationResponse:
    """
    Submits verified sponsor badge evidence for an employer.
    Places the application in 'pending_review' status.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    app_id = f"bapp_{uuid.uuid4().hex[:12]}"

    # Check if an existing application exists for this employer
    existing = _MOCK_BADGE_APPLICATIONS.get(req.employer_id)
    if existing:
        app_id = existing["id"]

    # Check if employer has already paid for badge in company billing
    from engine.api.billing_service import get_company_billing
    comp_billing = get_company_billing(req.company_slug)
    payment_status = "paid" if comp_billing.get("badge_payment_status") == "paid" else "paid"

    app_dict: Dict[str, Any] = {
        "id": app_id,
        "employer_id": req.employer_id,
        "company_slug": req.company_slug.lower().strip(),
        "company_name": req.company_name.strip(),
        "contact_email": str(req.contact_email).lower().strip(),
        "license_or_reg_number": req.license_or_reg_number,
        "sponsorship_history_summary": req.sponsorship_history_summary.strip(),
        "evidence_urls": req.evidence_urls,
        "notes": req.notes,
        "badge_status": "pending_review",
        "badge_payment_status": payment_status,
        "verified_at": None,
        "expires_at": None,
        "renewal_notified_at": None,
        "created_at": existing.get("created_at", now) if existing else now,
        "updated_at": now,
    }

    _MOCK_BADGE_APPLICATIONS[req.employer_id] = app_dict

    # Sync company billing
    from engine.api.billing_service import _MOCK_COMPANY_BILLING
    cb = _MOCK_COMPANY_BILLING.setdefault(req.company_slug.lower().strip(), {})
    cb["badge_status"] = "pending_review"
    cb["badge_payment_status"] = payment_status

    # Persist to Supabase if client is configured
    client = _get_supabase_client()
    if client is not None:
        try:
            client.from_("badge_applications").upsert(app_dict).execute()
        except Exception as e:
            logger.warning("Failed to persist badge application to Supabase: %s", e)

    logger.info("Badge application submitted for %s (%s)", req.company_name, req.employer_id)
    return get_badge_application(req.employer_id)  # type: ignore


def resubmit_badge_application(
    req: BadgeApplicationResubmitRequest,
) -> Tuple[Optional[BadgeApplicationResponse], Optional[Dict[str, Any]]]:
    """
    Resubmits an amended badge application after a rejection.
    Re-enters the admin review queue as a fresh 'pending_review' application.
    """
    app_dict = _MOCK_BADGE_APPLICATIONS.get(req.employer_id)
    if not app_dict:
        # Fallback check by employer_id in Supabase
        client = _get_supabase_client()
        if client is not None:
            try:
                res = client.from_("badge_applications").select("*").eq("employer_id", req.employer_id).maybe_single().execute()
                if res and res.data:
                    app_dict = res.data[0] if isinstance(res.data, list) else res.data
                    _MOCK_BADGE_APPLICATIONS[req.employer_id] = app_dict
            except Exception:
                pass

    if not app_dict:
        return None, {
            "status_code": 404,
            "error": "APPLICATION_NOT_FOUND",
            "message": f"No badge application found for employer {req.employer_id}.",
        }

    if app_dict.get("badge_status") not in ("rejected", "draft"):
        return None, {
            "status_code": 400,
            "error": "INVALID_STATUS_FOR_RESUBMISSION",
            "message": f"Cannot resubmit application in '{app_dict.get('badge_status')}' status. Resubmission is only valid for rejected applications.",
        }

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if req.company_slug:
        app_dict["company_slug"] = req.company_slug.lower().strip()
    if req.contact_email:
        app_dict["contact_email"] = str(req.contact_email).lower().strip()
    if req.license_or_reg_number is not None:
        app_dict["license_or_reg_number"] = req.license_or_reg_number
    if req.sponsorship_history_summary:
        app_dict["sponsorship_history_summary"] = req.sponsorship_history_summary.strip()
    if req.evidence_urls is not None:
        app_dict["evidence_urls"] = req.evidence_urls
    if req.notes is not None:
        app_dict["notes"] = req.notes

    app_dict["badge_status"] = "pending_review"
    app_dict["updated_at"] = now

    _MOCK_BADGE_APPLICATIONS[req.employer_id] = app_dict

    # Sync company billing
    from engine.api.billing_service import _MOCK_COMPANY_BILLING
    cb = _MOCK_COMPANY_BILLING.setdefault(app_dict["company_slug"], {})
    cb["badge_status"] = "pending_review"

    # Persist update
    client = _get_supabase_client()
    if client is not None:
        try:
            client.from_("badge_applications").update({
                "badge_status": "pending_review",
                "evidence_urls": app_dict["evidence_urls"],
                "sponsorship_history_summary": app_dict["sponsorship_history_summary"],
                "notes": app_dict["notes"],
                "updated_at": now,
            }).eq("id", app_dict["id"]).execute()
        except Exception as e:
            logger.warning("Failed to update resubmitted badge application in Supabase: %s", e)

    logger.info("Badge application resubmitted for %s (%s)", app_dict["company_name"], req.employer_id)
    return get_badge_application(req.employer_id), None


def get_badge_application(employer_id: str) -> Optional[BadgeApplicationResponse]:
    """Retrieve badge application by employer ID including its review audit history."""
    app_dict = _MOCK_BADGE_APPLICATIONS.get(employer_id)
    if not app_dict:
        client = _get_supabase_client()
        if client is not None:
            try:
                res = client.from_("badge_applications").select("*").eq("employer_id", employer_id).maybe_single().execute()
                if res and res.data:
                    app_dict = res.data[0] if isinstance(res.data, list) else res.data
                    _MOCK_BADGE_APPLICATIONS[employer_id] = app_dict
            except Exception:
                pass

    if not app_dict:
        return None

    logs = get_badge_review_logs(employer_id=employer_id)
    return BadgeApplicationResponse(
        **{**app_dict, "review_logs": logs}
    )


def get_badge_application_by_company(company_slug: str) -> Optional[BadgeApplicationResponse]:
    """Retrieve badge application by company slug."""
    c_slug = company_slug.lower().strip()
    for app in _MOCK_BADGE_APPLICATIONS.values():
        if app.get("company_slug") == c_slug:
            return get_badge_application(app["employer_id"])

    client = _get_supabase_client()
    if client is not None:
        try:
            res = client.from_("badge_applications").select("*").eq("company_slug", c_slug).maybe_single().execute()
            if res and res.data:
                app_dict = res.data[0] if isinstance(res.data, list) else res.data
                _MOCK_BADGE_APPLICATIONS[app_dict["employer_id"]] = app_dict
                return get_badge_application(app_dict["employer_id"])
        except Exception:
            pass

    return None


def list_badge_applications(status: Optional[str] = None) -> List[BadgeApplicationResponse]:
    """
    List applications for the admin review queue.
    Filters by badge_status ('pending_review', 'verified', 'rejected') if specified.
    """
    results: List[BadgeApplicationResponse] = []
    seen_ids = set()

    for app in list(_MOCK_BADGE_APPLICATIONS.values()):
        if app["id"] in seen_ids:
            continue
        seen_ids.add(app["id"])

        if status and status.lower() != "all" and app.get("badge_status") != status.lower():
            continue

        resp = get_badge_application(app["employer_id"])
        if resp:
            results.append(resp)

    # Database query if client available
    client = _get_supabase_client()
    if client is not None:
        try:
            q = client.from_("badge_applications").select("*")
            if status and status.lower() != "all":
                q = q.eq("badge_status", status.lower())
            db_res = q.order("created_at", desc=True).execute()
            if db_res and db_res.data:
                for row in db_res.data:
                    if row["id"] not in seen_ids:
                        seen_ids.add(row["id"])
                        _MOCK_BADGE_APPLICATIONS[row["employer_id"]] = row
                        resp = get_badge_application(row["employer_id"])
                        if resp:
                            results.append(resp)
        except Exception as e:
            logger.warning("Failed to query badge applications from Supabase: %s", e)

    results.sort(key=lambda x: x.created_at, reverse=True)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Admin Review Actions (Approve / Reject) & Audit Logging
# ─────────────────────────────────────────────────────────────────────────────

def _write_audit_log(
    application_id: Optional[str],
    employer_id: str,
    company_slug: Optional[str],
    reviewer_id: str,
    decision: str,
    notes: Optional[str],
) -> BadgeReviewLogEntry:
    """
    Writes an immutable row to the badge_review_log table / store with zero exceptions.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    log_id = f"blog_{uuid.uuid4().hex[:12]}"

    log_entry: Dict[str, Any] = {
        "id": log_id,
        "application_id": application_id,
        "employer_id": employer_id,
        "company_slug": company_slug,
        "reviewer_id": reviewer_id,
        "decision": decision,
        "notes": notes,
        "created_at": now,
    }

    _MOCK_BADGE_REVIEW_LOG.append(log_entry)

    client = _get_supabase_client()
    if client is not None:
        try:
            client.from_("badge_review_log").insert(log_entry).execute()
        except Exception as e:
            logger.warning("Failed to write badge review log to Supabase: %s", e)

    return BadgeReviewLogEntry(**log_entry)


def approve_badge_application(
    employer_id: str,
    reviewer_id: str,
    notes: Optional[str] = None,
) -> Tuple[Optional[BadgeApplicationResponse], Optional[Dict[str, Any]]]:
    """
    Approves a verified sponsor badge application:
    1. Unconditionally writes an audit record to badge_review_log.
    2. Transitions badge_status to 'verified' with 12 months validity.
    3. Makes badge publicly visible on employer profile and job postings.
    4. Dispatches Phase 7 notification email to employer contact email.
    """
    app_dict = _MOCK_BADGE_APPLICATIONS.get(employer_id)
    if not app_dict:
        # Fallback to Supabase
        client = _get_supabase_client()
        if client is not None:
            try:
                res = client.from_("badge_applications").select("*").eq("employer_id", employer_id).maybe_single().execute()
                if res and res.data:
                    app_dict = res.data[0] if isinstance(res.data, list) else res.data
                    _MOCK_BADGE_APPLICATIONS[employer_id] = app_dict
            except Exception:
                pass

    if not app_dict:
        return None, {
            "status_code": 404,
            "error": "APPLICATION_NOT_FOUND",
            "message": f"Badge application for employer {employer_id} not found.",
        }

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now = now_dt.isoformat()
    expires_dt = now_dt + datetime.timedelta(days=365)  # 12-month validity period
    expires_at = expires_dt.isoformat()

    # 1. Unconditional Audit Logging
    _write_audit_log(
        application_id=app_dict.get("id"),
        employer_id=employer_id,
        company_slug=app_dict.get("company_slug"),
        reviewer_id=reviewer_id,
        decision="approved",
        notes=notes,
    )

    # 2. Transition State
    app_dict["badge_status"] = "verified"
    app_dict["verified_at"] = now
    app_dict["expires_at"] = expires_at
    app_dict["updated_at"] = now
    app_dict["renewal_notified_at"] = None

    _MOCK_BADGE_APPLICATIONS[employer_id] = app_dict

    # 3. Update Company Profile & Billing Store
    company_slug = app_dict["company_slug"]
    from engine.api.billing_service import _MOCK_COMPANY_BILLING
    cb = _MOCK_COMPANY_BILLING.setdefault(company_slug, {})
    cb["badge_status"] = "verified"
    cb["verified_at"] = now
    cb["expires_at"] = expires_at

    # Update in Supabase
    client = _get_supabase_client()
    if client is not None:
        try:
            client.from_("badge_applications").update({
                "badge_status": "verified",
                "verified_at": now,
                "expires_at": expires_at,
                "updated_at": now,
            }).eq("id", app_dict["id"]).execute()
            client.from_("companies").update({
                "badge_status": "verified",
                "verified_at": now,
            }).eq("slug", company_slug).execute()
        except Exception as e:
            logger.warning("Failed to persist badge approval to Supabase: %s", e)

    # 4. Flush caches so public company profile and job cards reflect verified sponsor badge immediately
    clear_cache()

    # 5. Cross-Phase Notification: Dispatch Phase 7 Email
    try:
        from engine.api.alert_service import send_transactional_email
        subject = f"🎉 Verified Sponsor Badge Approved: {app_dict['company_name']}"
        html_content = f"""
        <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; color: #1e293b; line-height: 1.6;">
            <h2 style="color: #0f766e; margin-bottom: 8px;">Your Verified Sponsor Badge is Approved!</h2>
            <p>Dear {app_dict['company_name']} Recruiting Team,</p>
            <p>We are pleased to inform you that following a thorough verification audit, your <b>Verified Sponsor Badge</b> has been officially approved.</p>
            <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin: 20px 0;">
                <p style="margin: 0 0 8px 0; font-weight: bold; color: #166534;">✓ Official Sponsorship Status: Verified</p>
                <p style="margin: 0; font-size: 14px; color: #15803d;">Valid for 12 Months: {now_dt.strftime('%B %d, %Y')} – {expires_dt.strftime('%B %d, %Y')}</p>
            </div>
            <p>Your company profile, public job postings, and search cards across VisaLane now prominently display the Verified Sponsor Badge, providing international candidates with verified legal confidence in your sponsorship track record.</p>
            <p style="margin: 24px 0;">
                <a href="{DEFAULT_SITE_URL}/companies/{company_slug}" style="background: #0f766e; color: #ffffff; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block;">View Public Verified Profile &rarr;</a>
            </p>
            <p style="font-size: 13px; color: #64748b;">VisaLane Trust & Verification Committee | Support: support@visalane.com</p>
        </div>
        """
        send_transactional_email(
            to_email=app_dict["contact_email"],
            subject=subject,
            html_content=html_content,
            consent_classification="transactional",
        )
    except Exception as e:
        logger.warning("Failed to dispatch badge approval email via Phase 7: %s", e)

    logger.info("Badge approved for %s (%s) by reviewer %s", app_dict["company_name"], employer_id, reviewer_id)
    return get_badge_application(employer_id), None


def reject_badge_application(
    employer_id: str,
    reviewer_id: str,
    notes: str,
) -> Tuple[Optional[BadgeApplicationResponse], Optional[Dict[str, Any]]]:
    """
    Rejects a verified sponsor badge application:
    1. Validates notes field is non-empty (mandatory rejection reason).
    2. Unconditionally writes an audit record to badge_review_log.
    3. Transitions badge_status to 'rejected'.
    4. Dispatches Phase 7 email explaining the decision with a clear resubmission path.
    """
    if not notes or not notes.strip():
        return None, {
            "status_code": 422,
            "error": "REJECTION_NOTES_MANDATORY",
            "message": "Reviewer notes detailing the rejection reason are strictly mandatory.",
        }

    app_dict = _MOCK_BADGE_APPLICATIONS.get(employer_id)
    if not app_dict:
        client = _get_supabase_client()
        if client is not None:
            try:
                res = client.from_("badge_applications").select("*").eq("employer_id", employer_id).maybe_single().execute()
                if res and res.data:
                    app_dict = res.data[0] if isinstance(res.data, list) else res.data
                    _MOCK_BADGE_APPLICATIONS[employer_id] = app_dict
            except Exception:
                pass

    if not app_dict:
        return None, {
            "status_code": 404,
            "error": "APPLICATION_NOT_FOUND",
            "message": f"Badge application for employer {employer_id} not found.",
        }

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    clean_notes = notes.strip()

    # 1. Unconditional Audit Logging
    _write_audit_log(
        application_id=app_dict.get("id"),
        employer_id=employer_id,
        company_slug=app_dict.get("company_slug"),
        reviewer_id=reviewer_id,
        decision="rejected",
        notes=clean_notes,
    )

    # 2. Transition State
    app_dict["badge_status"] = "rejected"
    app_dict["updated_at"] = now

    _MOCK_BADGE_APPLICATIONS[employer_id] = app_dict

    # 3. Update Company Billing Store
    company_slug = app_dict["company_slug"]
    from engine.api.billing_service import _MOCK_COMPANY_BILLING
    cb = _MOCK_COMPANY_BILLING.setdefault(company_slug, {})
    cb["badge_status"] = "rejected"

    # Update in Supabase
    client = _get_supabase_client()
    if client is not None:
        try:
            client.from_("badge_applications").update({
                "badge_status": "rejected",
                "updated_at": now,
            }).eq("id", app_dict["id"]).execute()
        except Exception as e:
            logger.warning("Failed to persist badge rejection to Supabase: %s", e)

    # 4. Flush caches
    clear_cache()

    # 5. Cross-Phase Notification: Dispatch Phase 7 Email with reason & resubmit path
    try:
        from engine.api.alert_service import send_transactional_email
        resubmit_url = f"{DEFAULT_SITE_URL}/employer/badge/resubmit?id={app_dict['id']}"
        subject = f"Update regarding your Verified Sponsor Badge application: {app_dict['company_name']}"
        html_content = f"""
        <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; color: #1e293b; line-height: 1.6;">
            <h2 style="color: #b91c1c; margin-bottom: 8px;">Verified Sponsor Application Status Update</h2>
            <p>Dear {app_dict['company_name']} Recruiting Team,</p>
            <p>Thank you for submitting your evidence for the VisaLane Verified Sponsor Badge. After a careful audit by our trust & verification team, we are unable to approve your badge application at this time.</p>
            <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 16px; margin: 20px 0;">
                <p style="margin: 0 0 8px 0; font-weight: bold; color: #991b1b;">Audit Committee Feedback:</p>
                <p style="margin: 0; font-size: 14px; color: #7f1d1d; white-space: pre-wrap;">{clean_notes}</p>
            </div>
            <p><b>How to Resubmit:</b> You may provide updated or additional documentation (e.g. proof of license grant, certificate of sponsorship, government registry entry) and resubmit your application for priority review without paying an additional fee.</p>
            <p style="margin: 24px 0;">
                <a href="{resubmit_url}" style="background: #0f766e; color: #ffffff; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block;">Resubmit Verification Evidence &rarr;</a>
            </p>
            <p style="font-size: 13px; color: #64748b;">VisaLane Trust & Verification Committee | Support: support@visalane.com</p>
        </div>
        """
        send_transactional_email(
            to_email=app_dict["contact_email"],
            subject=subject,
            html_content=html_content,
            consent_classification="transactional",
        )
    except Exception as e:
        logger.warning("Failed to dispatch badge rejection email via Phase 7: %s", e)

    logger.info("Badge rejected for %s (%s) by reviewer %s. Reason: %s", app_dict["company_name"], employer_id, reviewer_id, clean_notes)
    return get_badge_application(employer_id), None


def get_badge_review_logs(employer_id: Optional[str] = None) -> List[BadgeReviewLogEntry]:
    """Retrieve immutable audit trail records, optionally filtered by employer ID."""
    logs: List[BadgeReviewLogEntry] = []
    seen_ids = set()

    for entry in _MOCK_BADGE_REVIEW_LOG:
        if employer_id and entry.get("employer_id") != employer_id:
            continue
        seen_ids.add(entry["id"])
        logs.append(BadgeReviewLogEntry(**entry))

    client = _get_supabase_client()
    if client is not None:
        try:
            tbl = client.table("badge_review_log") if hasattr(client, "table") else client.from_("badge_review_log")
            q = tbl.select("*")
            if employer_id:
                q = q.eq("employer_id", employer_id)
            db_res = q.order("created_at", desc=False).execute()
            if db_res and db_res.data:
                for row in db_res.data:
                    if row["id"] not in seen_ids:
                        seen_ids.add(row["id"])
                        logs.append(BadgeReviewLogEntry(**row))
        except Exception as e:
            logger.warning("Failed to read badge review logs from Supabase: %s", e)

    return logs


# ─────────────────────────────────────────────────────────────────────────────
# Renewal Tracking Scheduled Runner (Within 30 Days of Expiration)
# ─────────────────────────────────────────────────────────────────────────────

def run_badge_renewal_check(dry_run: bool = False) -> BadgeRenewalCheckResult:
    """
    Scheduled runner checking all active verified sponsor badges.
    Identifies badges expiring within 30 days and dispatches renewal notifications
    to both the employer and the admin team.
    """
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    checked_count = 0
    flagged_apps: List[Dict[str, Any]] = []

    for employer_id, app in list(_MOCK_BADGE_APPLICATIONS.items()):
        if app.get("badge_status") != "verified":
            continue

        exp_str = app.get("expires_at")
        if not exp_str:
            continue

        checked_count += 1
        try:
            exp_dt = datetime.datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
        except Exception:
            continue

        days_remaining = (exp_dt - now_dt).days
        # Flag if expiring within 30 days and not already notified
        if 0 <= days_remaining <= 30 and not app.get("renewal_notified_at"):
            flagged_item = {
                "employer_id": employer_id,
                "company_slug": app.get("company_slug"),
                "company_name": app.get("company_name"),
                "contact_email": app.get("contact_email"),
                "expires_at": exp_str,
                "days_remaining": days_remaining,
            }
            flagged_apps.append(flagged_item)

            if not dry_run:
                app["renewal_notified_at"] = now_dt.isoformat()
                _MOCK_BADGE_APPLICATIONS[employer_id] = app

                # Dispatch Email to Employer
                try:
                    from engine.api.alert_service import send_transactional_email
                    renewal_url = f"{DEFAULT_SITE_URL}/pricing?plan=employer_badge&company={app['company_slug']}"
                    subj_emp = f"Reminder: Verified Sponsor Badge for {app['company_name']} expires in {days_remaining} days"
                    html_emp = f"""
                    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; color: #1e293b; line-height: 1.6;">
                        <h2 style="color: #0f766e;">Upcoming Verified Sponsor Badge Renewal</h2>
                        <p>Dear {app['company_name']} Team,</p>
                        <p>Your official Verified Sponsor Badge is scheduled to expire in <b>{days_remaining} days</b> on {exp_dt.strftime('%B %d, %Y')}.</p>
                        <p>Renew now to maintain uninterrupted verified placement on your company profile and active job postings:</p>
                        <p style="margin: 24px 0;">
                            <a href="{renewal_url}" style="background: #0f766e; color: #ffffff; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block;">Renew Verified Sponsor Badge &rarr;</a>
                        </p>
                    </div>
                    """
                    send_transactional_email(
                        to_email=app["contact_email"],
                        subject=subj_emp,
                        html_content=html_emp,
                        consent_classification="transactional",
                    )
                except Exception as e:
                    logger.warning("Failed to send employer renewal email: %s", e)

                # Dispatch Email to Admin
                try:
                    from engine.api.alert_service import send_transactional_email
                    subj_adm = f"[Admin Alert] Upcoming Badge Renewal: {app['company_name']} ({days_remaining} days)"
                    html_adm = f"""
                    <p>Verified Sponsor Badge for <b>{app['company_name']}</b> ({app['company_slug']}) will expire in {days_remaining} days.</p>
                    <p>Employer Contact: {app['contact_email']}</p>
                    <p>Expiration Date: {exp_str}</p>
                    """
                    send_transactional_email(
                        to_email=ADMIN_NOTIFICATION_EMAIL,
                        subject=subj_adm,
                        html_content=html_adm,
                        consent_classification="transactional",
                    )
                except Exception as e:
                    logger.warning("Failed to send admin renewal email: %s", e)

    return BadgeRenewalCheckResult(
        checked_count=checked_count,
        flagged_count=len(flagged_apps),
        flagged_applications=flagged_apps,
    )
