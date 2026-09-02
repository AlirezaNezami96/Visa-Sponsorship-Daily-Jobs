"""
Core service engine for VisaLane Phase 8 (Backend):
B2B Self-Serve: Employer Job Posting, Quotas, and Analytics.
- Enforces strict Phase 2 schema completeness at submission time.
- Enforces active-listing quotas based on Phase 6 employer subscription tiers.
- Manages employer direct listings (CRUD, Close).
- Aggregates per-listing engagement analytics from the first-party events store.
"""
from __future__ import annotations

import datetime
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from engine.api.cache import clear_cache
from engine.api.canonical_data import find_country, find_visa_type
from engine.api.employer_models import (
    DailyAnalyticsPoint,
    EmployerJobCreateRequest,
    EmployerJobListResponse,
    EmployerJobResponse,
    EmployerJobUpdateRequest,
    JobAnalyticsResponse,
    QuotaExceededErrorDetail,
    SchemaValidationErrorDetail,
)
from engine.api.jobs_models import generate_company_slug, generate_job_slug

logger = logging.getLogger(__name__)

# Plan Quota Mapping: Free = 1, Featured = 3, Pro = Unlimited (-1)
EMPLOYER_PLAN_QUOTAS: Dict[str, int] = {
    "free": 1,
    "employer_featured": 3,
    "featured": 3,
    "employer_pro": -1,
    "pro": -1,
}

# In-memory employer direct listings store (keyed by job_id)
_MOCK_EMPLOYER_JOBS: Dict[str, Dict[str, Any]] = {}


def clear_mock_employer_stores() -> None:
    """Resets the in-memory employer jobs store for testing."""
    global _MOCK_EMPLOYER_JOBS
    _MOCK_EMPLOYER_JOBS = {}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Schema Completeness Validator (Phase 2 Parity)
# ─────────────────────────────────────────────────────────────────────────────

def validate_job_schema_completeness(
    data: Dict[str, Any],
) -> Tuple[bool, List[str], Dict[str, str]]:
    """
    Validates that a job submission meets the exact schema.org/JobPosting
    completeness bar required by Google JobPosting and VisaLane Phase 2 SEO rules.
    Required fields:
    1. title: >= 3 characters
    2. description: >= 30 characters
    3. company_name: non-empty string
    4. location OR is_remote: valid physical location OR is_remote=True
    5. apply_url: valid HTTP(S) URL
    """
    missing_fields: List[str] = []
    validation_errors: Dict[str, str] = {}

    # 1. Title
    title = str(data.get("title") or "").strip()
    if not title or len(title) < 3:
        missing_fields.append("title")
        validation_errors["title"] = "Job title is required and must contain at least 3 characters."

    # 2. Description
    desc = str(data.get("description") or "").strip()
    if not desc or len(desc) < 30:
        missing_fields.append("description")
        validation_errors["description"] = "Job description is required and must contain at least 30 characters."

    # 3. Company Name / Hiring Organization
    company = str(data.get("company_name") or "").strip()
    if not company:
        missing_fields.append("company_name")
        validation_errors["company_name"] = "Hiring organization (company_name) is required."

    # 4. Location vs. Remote Eligibility
    is_remote = bool(data.get("is_remote", False))
    loc = str(data.get("location") or "").strip()
    city = str(data.get("city") or "").strip()
    country = str(data.get("country") or "").strip()

    if not is_remote and not (loc or city or country):
        missing_fields.append("location")
        validation_errors["location"] = (
            "A valid physical location (location, city, or country) is required when is_remote is False."
        )

    # 5. Apply URL
    apply_url = str(data.get("apply_url") or "").strip()
    if not apply_url or not re.match(r"^https?://[^\s/$.?#].[^\s]*$", apply_url, re.IGNORECASE):
        missing_fields.append("apply_url")
        validation_errors["apply_url"] = "A valid application URL starting with http:// or https:// is required."

    # 6. Date Posted (Valid ISO if supplied)
    dp = data.get("date_posted")
    if dp:
        try:
            datetime.datetime.fromisoformat(str(dp).replace("Z", "+00:00"))
        except Exception:
            missing_fields.append("date_posted")
            validation_errors["date_posted"] = "date_posted must be a valid ISO 8601 timestamp string."

    is_valid = len(missing_fields) == 0
    return is_valid, missing_fields, validation_errors


# ─────────────────────────────────────────────────────────────────────────────
# 2. Plan Quota Evaluator (Phase 6 Integration)
# ─────────────────────────────────────────────────────────────────────────────

def get_employer_active_quota(
    employer_id: Optional[str] = None,
    company_slug: Optional[str] = None,
) -> Tuple[str, int]:
    """
    Determines the employer's plan name and maximum allowed active listings.
    Checks Phase 6 billing state.
    """
    from engine.api.billing_service import get_company_billing, get_user_entitlement

    plan_name = "free"

    if company_slug:
        comp_billing = get_company_billing(company_slug)
        raw_p = comp_billing.get("employer_plan", "free").lower()
        if raw_p in ("pro", "employer_pro"):
            plan_name = "employer_pro"
        elif raw_p in ("featured", "employer_featured"):
            plan_name = "employer_featured"
        elif comp_billing.get("featured_until"):
            # Active 30-day featured listing purchased
            plan_name = "employer_featured"

    if plan_name == "free" and employer_id:
        from engine.api.billing_service import get_mock_user_profile
        prof = get_mock_user_profile(employer_id) or {}
        raw_u_plan = str(prof.get("subscription_plan") or prof.get("employer_plan") or "").lower()
        if raw_u_plan in ("employer_pro", "pro"):
            plan_name = "employer_pro"
        elif raw_u_plan in ("employer_featured", "featured"):
            plan_name = "employer_featured"
        else:
            user_ent = get_user_entitlement(employer_id)
            u_plan = str(user_ent.get("plan") or user_ent.get("subscription_plan") or "free").lower()
            if u_plan in ("employer_pro", "pro"):
                plan_name = "employer_pro"
            elif u_plan in ("employer_featured", "featured"):
                plan_name = "employer_featured"

    quota = EMPLOYER_PLAN_QUOTAS.get(plan_name, 1)
    return plan_name, quota


def count_active_employer_listings(
    employer_id: Optional[str] = None,
    company_slug: Optional[str] = None,
) -> int:
    """Counts currently active direct listings owned by this employer."""
    from engine.api.jobs_routes import _MOCK_JOBS_STORE

    count = 0
    seen_ids = set()

    # 1. Count from _MOCK_EMPLOYER_JOBS
    for j in _MOCK_EMPLOYER_JOBS.values():
        if not j.get("is_active", True) or j.get("job_status") == "Closed":
            continue
        if employer_id and j.get("employer_id") == employer_id:
            count += 1
            seen_ids.add(j["id"])
        elif company_slug and j.get("company_slug") == company_slug:
            if j["id"] not in seen_ids:
                count += 1
                seen_ids.add(j["id"])

    # 2. Check _MOCK_JOBS_STORE for any synced jobs not yet counted
    for j in _MOCK_JOBS_STORE:
        j_id = str(j.get("id", ""))
        if j_id in seen_ids:
            continue
        if j.get("source") != "employer_direct":
            continue
        if str(j.get("job_status", "Open")) == "Closed" or str(j.get("status", "active")) != "active":
            continue
        if employer_id and j.get("employer_id") == employer_id:
            count += 1
            seen_ids.add(j_id)
        elif company_slug and j.get("company_slug") == company_slug:
            count += 1
            seen_ids.add(j_id)

    return count


def evaluate_employer_listing_quota(
    employer_id: Optional[str] = None,
    company_slug: Optional[str] = None,
) -> Tuple[bool, Optional[QuotaExceededErrorDetail]]:
    """
    Evaluates whether the employer can publish an additional active listing.
    Blocks the (N+1)th active listing with an upgrade prompt response.
    """
    plan_name, quota_limit = get_employer_active_quota(employer_id, company_slug)
    active_count = count_active_employer_listings(employer_id, company_slug)

    # -1 represents unlimited
    if quota_limit != -1 and active_count >= quota_limit:
        upgrade_url = "https://visalane.com/pricing?role=employer&plan=employer_pro"
        detail = QuotaExceededErrorDetail(
            error="ACTIVE_LISTING_QUOTA_EXCEEDED",
            message=(
                f"You have reached the limit of {quota_limit} active listing(s) "
                f"allowed on your '{plan_name}' plan. Upgrade to Employer Pro for unlimited listings."
            ),
            plan_name=plan_name,
            current_limit=quota_limit,
            current_active_count=active_count,
            upgrade_url=upgrade_url,
        )
        return False, detail

    return True, None


# ─────────────────────────────────────────────────────────────────────────────
# 3. Employer Direct Job CRUD
# ─────────────────────────────────────────────────────────────────────────────

def create_employer_job(
    req: EmployerJobCreateRequest,
) -> Tuple[Optional[EmployerJobResponse], Optional[Dict[str, Any]]]:
    """
    Validates schema completeness, enforces plan quota, and stores direct job listing.
    Tags source as 'employer_direct'.
    """
    # 1. Validate Schema Completeness
    is_valid, missing_fields, validation_errors = validate_job_schema_completeness(req.model_dump())
    if not is_valid:
        return None, {
            "status_code": 422,
            "error": "SCHEMA_VALIDATION_FAILED",
            "message": "Job submission failed schema completeness requirements.",
            "missing_fields": missing_fields,
            "validation_errors": validation_errors,
        }

    # 2. Evaluate Quota
    company_slug = req.company_slug or generate_company_slug(req.company_name)
    can_post, quota_err = evaluate_employer_listing_quota(
        employer_id=req.employer_id,
        company_slug=company_slug,
    )
    if not can_post and quota_err is not None:
        return None, {
            "status_code": 403,
            **quota_err.model_dump(),
        }

    # 3. Construct Record
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    job_id = f"job_direct_{uuid.uuid4().hex[:12]}"
    slug = generate_job_slug(req.title, req.company_name, job_id)
    date_posted = req.date_posted or now

    work_mode = "remote" if req.is_remote else "on_site"

    job_dict: Dict[str, Any] = {
        "id": job_id,
        "slug": slug,
        "title": req.title.strip(),
        "description": req.description.strip(),
        "description_html": req.description_html or f"<p>{req.description.strip()}</p>",
        "company_name": req.company_name.strip(),
        "company_slug": company_slug,
        "company_website": req.company_website,
        "company_logo_url": req.company_logo_url,
        "companies": {
            "name": req.company_name.strip(),
            "slug": company_slug,
            "logo_url": req.company_logo_url,
            "website": req.company_website,
        },
        "location": req.location,
        "location_raw": req.location,
        "city": req.city,
        "country": req.country,
        "country_code": req.country_code.upper() if req.country_code else None,
        "is_remote": req.is_remote,
        "work_mode": work_mode,
        "employment_type": req.employment_type or "FULL_TIME",
        "date_posted": date_posted,
        "posted_at": date_posted,
        "apply_url": req.apply_url.strip(),
        "visa_types": req.visa_types,
        "visa_sponsorship_type": req.visa_types[0] if req.visa_types else "Verified Employer",
        "visa_sponsorship_confidence": 100,  # Direct employer listings carry 100% verified confidence
        "visa_sponsorship_verified": True,
        "salary_min": req.salary_min,
        "salary_max": req.salary_max,
        "salary_currency": req.salary_currency or "USD",
        "job_status": "Open",
        "status": "active",
        "is_active": True,
        "source": "employer_direct",
        "employer_id": req.employer_id or "emp_direct_owner",
        "created_at": now,
        "updated_at": now,
    }

    # 4. Save to in-memory employer store and global jobs store
    _MOCK_EMPLOYER_JOBS[job_id] = job_dict

    from engine.api.jobs_routes import _MOCK_JOBS_STORE
    _MOCK_JOBS_STORE.insert(0, job_dict)

    # 5. Clear caches so job is instantly indexable and searchable
    clear_cache()

    # 6. Trigger instant candidate alert notification hook
    try:
        from engine.api.alert_service import notify_instant_alerts_for_new_job
        notify_instant_alerts_for_new_job(job_dict)
    except Exception as e:
        logger.warning("Failed to trigger instant candidate alerts for direct job %s: %s", job_id, e)

    logger.info("Employer direct job %s published successfully by employer %s", job_id, req.employer_id)
    return EmployerJobResponse(**job_dict), None


def update_employer_job(
    job_id: str,
    req: EmployerJobUpdateRequest,
    employer_id: Optional[str] = None,
) -> Tuple[Optional[EmployerJobResponse], Optional[Dict[str, Any]]]:
    """Updates an existing employer direct listing."""
    job_dict = _MOCK_EMPLOYER_JOBS.get(job_id)
    if not job_dict:
        # Search global store fallback
        from engine.api.jobs_routes import _MOCK_JOBS_STORE
        for j in _MOCK_JOBS_STORE:
            if j.get("id") == job_id and j.get("source") == "employer_direct":
                job_dict = j
                _MOCK_EMPLOYER_JOBS[job_id] = j
                break

    if not job_dict:
        return None, {"status_code": 404, "error": "JOB_NOT_FOUND", "message": f"Job {job_id} not found."}

    if employer_id and job_dict.get("employer_id") and job_dict["employer_id"] != employer_id:
        return None, {"status_code": 403, "error": "FORBIDDEN", "message": "You do not have permission to edit this listing."}

    # Build merged payload to check schema validity
    merged = dict(job_dict)
    update_data = req.model_dump(exclude_unset=True)
    merged.update(update_data)

    is_valid, missing_fields, validation_errors = validate_job_schema_completeness(merged)
    if not is_valid:
        return None, {
            "status_code": 422,
            "error": "SCHEMA_VALIDATION_FAILED",
            "message": "Updated fields cause the listing to fail schema completeness requirements.",
            "missing_fields": missing_fields,
            "validation_errors": validation_errors,
        }

    # Apply updates
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    merged["updated_at"] = now
    if "is_remote" in update_data:
        merged["work_mode"] = "remote" if update_data["is_remote"] else "on_site"

    _MOCK_EMPLOYER_JOBS[job_id] = merged

    # Update in global store
    from engine.api.jobs_routes import _MOCK_JOBS_STORE
    for idx, j in enumerate(_MOCK_JOBS_STORE):
        if j.get("id") == job_id:
            _MOCK_JOBS_STORE[idx] = merged
            break

    clear_cache()
    return EmployerJobResponse(**merged), None


def close_employer_job(
    job_id: str,
    employer_id: Optional[str] = None,
) -> Tuple[Optional[EmployerJobResponse], Optional[Dict[str, Any]]]:
    """
    Closes an employer direct listing, flipping status to Closed and freeing up quota.
    Immediately excludes from active public search and sitemap.
    """
    job_dict = _MOCK_EMPLOYER_JOBS.get(job_id)
    if not job_dict:
        from engine.api.jobs_routes import _MOCK_JOBS_STORE
        for j in _MOCK_JOBS_STORE:
            if j.get("id") == job_id and j.get("source") == "employer_direct":
                job_dict = j
                _MOCK_EMPLOYER_JOBS[job_id] = j
                break

    if not job_dict:
        return None, {"status_code": 404, "error": "JOB_NOT_FOUND", "message": f"Job {job_id} not found."}

    if employer_id and job_dict.get("employer_id") and job_dict["employer_id"] != employer_id:
        return None, {"status_code": 403, "error": "FORBIDDEN", "message": "You do not have permission to close this listing."}

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    job_dict["job_status"] = "Closed"
    job_dict["status"] = "closed"
    job_dict["is_active"] = False
    job_dict["valid_through"] = now
    job_dict["updated_at"] = now

    _MOCK_EMPLOYER_JOBS[job_id] = job_dict

    # Sync with global store
    from engine.api.jobs_routes import _MOCK_JOBS_STORE
    for idx, j in enumerate(_MOCK_JOBS_STORE):
        if j.get("id") == job_id:
            _MOCK_JOBS_STORE[idx] = job_dict
            break

    # Flush caches so closed listing is removed from public SEO sitemaps immediately
    clear_cache()
    logger.info("Employer direct job %s closed successfully", job_id)
    return EmployerJobResponse(**job_dict), None


def get_employer_job(job_id: str) -> Optional[EmployerJobResponse]:
    """Retrieves a direct employer job."""
    job_dict = _MOCK_EMPLOYER_JOBS.get(job_id)
    if not job_dict:
        from engine.api.jobs_routes import _MOCK_JOBS_STORE
        for j in _MOCK_JOBS_STORE:
            if j.get("id") == job_id:
                job_dict = j
                break
    if job_dict:
        return EmployerJobResponse(**job_dict)
    return None


def list_employer_jobs(
    employer_id: Optional[str] = None,
    company_slug: Optional[str] = None,
    status_filter: str = "all",
) -> EmployerJobListResponse:
    """Lists all employer listings with plan quota context."""
    from engine.api.jobs_routes import _MOCK_JOBS_STORE

    seen_ids = set()
    matched: List[EmployerJobResponse] = []

    all_candidates = list(_MOCK_EMPLOYER_JOBS.values()) + [
        j for j in _MOCK_JOBS_STORE if j.get("source") == "employer_direct"
    ]

    for j in all_candidates:
        j_id = str(j.get("id", ""))
        if j_id in seen_ids:
            continue
        seen_ids.add(j_id)

        if employer_id and j.get("employer_id") != employer_id:
            continue
        if company_slug and j.get("company_slug") != company_slug:
            continue

        is_act = j.get("is_active", True) and j.get("job_status") != "Closed"

        if status_filter == "active" and not is_act:
            continue
        elif status_filter == "closed" and is_act:
            continue

        try:
            matched.append(EmployerJobResponse(**j))
        except Exception:
            pass

    plan_name, quota_limit = get_employer_active_quota(employer_id, company_slug)
    active_count = sum(1 for m in matched if m.is_active and m.job_status != "Closed")
    closed_count = sum(1 for m in matched if not m.is_active or m.job_status == "Closed")

    return EmployerJobListResponse(
        jobs=matched,
        total_count=len(matched),
        active_count=active_count,
        closed_count=closed_count,
        quota_limit=quota_limit,
        plan_name=plan_name,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Per-Listing Analytics Aggregator
# ─────────────────────────────────────────────────────────────────────────────

def get_job_analytics(
    job_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> JobAnalyticsResponse:
    """
    Aggregates first-party engagement events ('job_viewed', 'apply_click')
    scoped to this specific job ID over the selected date range.
    """
    from engine.api.jobs_routes import _MOCK_EVENTS_STORE

    now = datetime.datetime.now(datetime.timezone.utc)
    if not end_date:
        end_dt = now
        end_date = end_dt.date().isoformat()
    else:
        end_dt = datetime.datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)
        end_dt = end_dt.replace(hour=23, minute=59, second=59)

    if not start_date:
        start_dt = end_dt - datetime.timedelta(days=30)
        start_date = start_dt.date().isoformat()
    else:
        start_dt = datetime.datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
        start_dt = start_dt.replace(hour=0, minute=0, second=0)

    total_views = 0
    unique_viewers_set = set()
    apply_clicks = 0
    daily_stats: Dict[str, Dict[str, Any]] = {}

    # Initialize daily points
    cur = start_dt.date()
    while cur <= end_dt.date():
        ds = cur.isoformat()
        daily_stats[ds] = {"views": 0, "uniques": set(), "clicks": 0}
        cur += datetime.timedelta(days=1)

    # Aggregate events from store
    for evt in _MOCK_EVENTS_STORE:
        meta = evt.get("metadata") or {}
        evt_job_id = str(meta.get("job_id") or meta.get("id") or "")
        if evt_job_id != job_id:
            continue

        raw_ts = evt.get("created_at")
        if not raw_ts:
            continue
        try:
            evt_dt = datetime.datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
            if evt_dt.tzinfo is None:
                evt_dt = evt_dt.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            continue

        if not (start_dt <= evt_dt <= end_dt):
            continue

        day_str = evt_dt.date().isoformat()
        sess_id = evt.get("session_id") or evt.get("user_id") or f"sess_{uuid.uuid4().hex[:6]}"
        evt_type = str(evt.get("event_type", "")).lower()

        if evt_type == "job_viewed":
            total_views += 1
            unique_viewers_set.add(sess_id)
            if day_str in daily_stats:
                daily_stats[day_str]["views"] += 1
                daily_stats[day_str]["uniques"].add(sess_id)
        elif evt_type == "apply_click":
            apply_clicks += 1
            if day_str in daily_stats:
                daily_stats[day_str]["clicks"] += 1

    ctr = round(apply_clicks / total_views, 4) if total_views > 0 else 0.0

    daily_breakdown = [
        DailyAnalyticsPoint(
            date=day_str,
            views=data["views"],
            unique_viewers=len(data["uniques"]),
            apply_clicks=data["clicks"],
            click_through_rate=round(data["clicks"] / data["views"], 4) if data["views"] > 0 else 0.0,
        )
        for day_str, data in sorted(daily_stats.items())
    ]

    return JobAnalyticsResponse(
        job_id=job_id,
        date_range={"start_date": start_date, "end_date": end_date},
        total_views=total_views,
        unique_viewers=len(unique_viewers_set),
        apply_clicks=apply_clicks,
        click_through_rate=ctr,
        daily_breakdown=daily_breakdown,
    )
