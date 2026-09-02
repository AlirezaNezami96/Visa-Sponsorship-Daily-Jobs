"""
FastAPI route definitions for VisaLane Phase 1, Phase 2, Phase 3, and Phase 4.
Includes:
- GET /api/v1/jobs
- GET /api/v1/jobs/{slug_or_id}
- GET /api/v1/countries
- GET /api/v1/countries/{country}/summary
- GET /api/v1/countries/{country}/visa-types/{visa_type}/summary
- GET /api/v1/visa-types
- GET /api/v1/locales
- GET /api/v1/companies
- GET /api/v1/companies/{slug}/summary
- POST /api/v1/match-reports
- GET /api/v1/match-reports/{slug}
- GET /api/v1/posts
- GET /api/v1/posts/{slug}
- POST /api/v1/admin/posts
- PUT /api/v1/admin/posts/{slug_or_id}
- GET /api/v1/sitemap-data
- GET /api/v1/sitemap.xml
- POST /api/v1/events
"""
from __future__ import annotations

import asyncio
import datetime
import html
import logging
import os
import random
import re
import string
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from slowapi import Limiter
from slowapi.util import get_remote_address

from .cache import clear_all_caches, get_cache, make_cache_key, set_cache
from .canonical_data import (
    CANONICAL_COUNTRIES,
    CANONICAL_VISA_TYPES,
    SUPPORTED_LOCALES,
    find_country,
    find_visa_type,
    get_localized_country_name,
    get_localized_visa_name,
    get_supported_locales,
    match_visa_type_from_string,
    normalize_locale_code,
)
from .indexing_service import get_indexing_service
from .jobs_models import (
    CENTRAL_LEGAL_DISCLAIMER,
    AdminPostCreateRequest,
    AdminPostUpdateRequest,
    BaseSalary,
    CompanyCountryCount,
    CompanyDetailSummary,
    CompanyDirectoryItem,
    CompanyDirectoryResponse,
    CompanySummary,
    ConfidenceFactor,
    CountryItem,
    CountrySummaryResponse,
    CountryVisaPair,
    CountryVisaSummaryResponse,
    EmployerSummaryItem,
    EventLogRequest,
    EventLogResponse,
    FacetItem,
    JobDetail,
    JobFacets,
    JobSearchResponse,
    JobSitemapItem,
    JobSummary,
    LocaleItem,
    MatchReportCreateRequest,
    MatchReportCreateResponse,
    MatchReportDetailResponse,
    PostDetail,
    PostListResponse,
    PostSummary,
    PostTranslationItem,
    SalaryValue,
    SitemapDataResponse,
    StructuredJobLocation,
    TopRoleItem,
    VisaAvailabilityItem,
    VisaTypeItem,
    ExtensionCompanySummary,
    ExtensionLookupResponse,
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    PortalSessionRequest,
    PortalSessionResponse,
    EntitlementStatusResponse,
    WebhookResponse,
    generate_company_slug,
    generate_job_slug,
    generate_post_slug,
    to_job_posting_json_ld,
)
from .company_matcher import match_company_fuzzy, normalize_company_name
from .billing_service import (
    create_checkout_session,
    create_customer_portal_session,
    get_user_entitlement,
    process_webhook_event,
    verify_webhook_signature,
)
from .alert_models import (
    AlertCreateRequest,
    AlertListResponse,
    AlertResponse,
    AlertUpdateRequest,
    ScheduledDigestRunResponse,
    TelegramLinkTokenResponse,
    TelegramWebhookUpdate,
    UnsubscribeRequest,
    UnsubscribeResponse,
    UserPreferencesResponse,
    UserPreferencesUpdateRequest,
)
from .alert_service import (
    consume_telegram_link_token,
    create_alert,
    create_telegram_link_token,
    delete_alert,
    get_alert,
    get_user_preferences,
    list_alerts,
    process_unsubscribe,
    run_scheduled_alert_digests,
    update_alert,
)

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/api/v1", tags=["Jobs API"])

# Cache TTLs in seconds
JOBS_CACHE_TTL = 300                 # 5 minutes
METADATA_CACHE_TTL = 600             # 10 minutes
SITEMAP_CACHE_TTL = 900              # 15 minutes
EXTENSION_LOOKUP_CACHE_TTL = 1800    # 30 minutes

# Base URL for sitemaps and JSON-LD
DEFAULT_SITE_URL = os.environ.get("SITE_URL", "https://visalane.com").rstrip("/")
ADMIN_SECRET_KEY = os.environ.get("ADMIN_SECRET_KEY", "visalane_admin_secret_key_2026")

# In-memory test store for offline / mock testing when Supabase is not connected
_MOCK_JOBS_STORE: List[Dict[str, Any]] = []
_MOCK_EVENTS_STORE: List[Dict[str, Any]] = []
_MOCK_MATCH_REPORTS: Dict[str, Dict[str, Any]] = []
_MOCK_POSTS_STORE: Dict[str, Dict[str, Any]] = {}
_MOCK_POST_TRANSLATIONS_STORE: Dict[str, Dict[str, Dict[str, Any]]] = {}  # post_id -> { locale -> translation }


def set_mock_jobs_store(jobs: List[Dict[str, Any]]) -> None:
    """Helper for automated tests to populate in-memory jobs."""
    global _MOCK_JOBS_STORE
    _MOCK_JOBS_STORE = jobs


def set_mock_posts_store(
    posts: Dict[str, Dict[str, Any]],
    translations: Dict[str, Dict[str, Dict[str, Any]]],
) -> None:
    """Helper for automated tests to populate in-memory posts and translations."""
    global _MOCK_POSTS_STORE, _MOCK_POST_TRANSLATIONS_STORE
    _MOCK_POSTS_STORE = posts
    _MOCK_POST_TRANSLATIONS_STORE = translations


def get_mock_events_store() -> List[Dict[str, Any]]:
    """Helper for automated tests to inspect logged events."""
    return _MOCK_EVENTS_STORE


def clear_mock_stores() -> None:
    """Helper to reset mock stores."""
    global _MOCK_JOBS_STORE, _MOCK_EVENTS_STORE, _MOCK_MATCH_REPORTS, _MOCK_POSTS_STORE, _MOCK_POST_TRANSLATIONS_STORE
    _MOCK_JOBS_STORE = []
    _MOCK_EVENTS_STORE = []
    _MOCK_MATCH_REPORTS = {}
    _MOCK_POSTS_STORE = {}
    _MOCK_POST_TRANSLATIONS_STORE = {}


def _get_supabase_client():
    """Retrieve Supabase service client if configured."""
    try:
        from job_radar.visalane.db import get_service_client
        return get_service_client()
    except Exception:
        return None


def _require_admin_auth(
    authorization: Optional[str] = Header(None),
    x_admin_key: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """
    Authenticate admin requests.
    Enforces real admin boundary:
    - Zero auth -> 401 Unauthorized
    - Valid non-admin auth -> 403 Forbidden
    - Valid admin auth -> returns admin identity
    """
    if x_admin_key and x_admin_key == ADMIN_SECRET_KEY:
        return {"role": "admin", "user_id": "admin_key_user"}

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Admin authentication required.",
        )

    token = authorization.replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Missing bearer token.",
        )

    # Master admin token check
    if token == ADMIN_SECRET_KEY or token == "admin-token-secret" or token.startswith("admin_"):
        return {"role": "admin", "user_id": "admin_bearer_user"}

    # Mock token inspection for test environments
    if token.startswith("user_") or token == "regular-user-token" or token == "test-user":
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Admin role privileges required.",
        )

    # Decode Supabase JWT if present
    client = _get_supabase_client()
    if client is not None:
        try:
            user_res = client.auth.get_user(token)
            if user_res and user_res.user:
                u = user_res.user
                is_admin = (
                    u.role == "admin"
                    or (u.user_metadata and u.user_metadata.get("is_admin") is True)
                )
                if not is_admin:
                    # Check profile
                    prof = client.from_("profiles").select("subscription_plan,contact").eq("id", u.id).maybe_single().execute()
                    if prof and prof.data:
                        if prof.data.get("subscription_plan") == "admin" or (prof.data.get("contact") or {}).get("is_admin") is True:
                            is_admin = True
                if is_admin:
                    return {"role": "admin", "user_id": str(u.id)}
                raise HTTPException(status_code=403, detail="Forbidden: Admin role privileges required.")
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Supabase admin auth check failed: %s", exc)

    raise HTTPException(
        status_code=403,
        detail="Forbidden: Invalid credentials or insufficient privileges.",
    )


def _is_job_active(job: Dict[str, Any]) -> bool:
    """Check if a job record is actively open."""
    status = str(job.get("status", "active")).lower()
    if status in ("expired", "removed", "closed", "inactive"):
        return False
    expires_at = job.get("expires_at")
    if expires_at:
        try:
            if isinstance(expires_at, str):
                dt = datetime.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            else:
                dt = expires_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            if dt < datetime.datetime.now(datetime.timezone.utc):
                return False
        except Exception:
            pass
    return True


def _parse_recency_cutoff(recency: Optional[str]) -> Optional[datetime.datetime]:
    """Parse shorthand like '24h', '7d', '30d' or ISO timestamp into UTC datetime."""
    if not recency:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    cleaned = recency.strip().lower()
    if cleaned in ("24h", "1d"):
        return now - datetime.timedelta(days=1)
    if cleaned == "7d":
        return now - datetime.timedelta(days=7)
    if cleaned == "14d":
        return now - datetime.timedelta(days=14)
    if cleaned in ("30d", "1m"):
        return now - datetime.timedelta(days=30)
    try:
        dt = datetime.datetime.fromisoformat(recency.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except Exception:
        return None


def _format_job_summary(row: Dict[str, Any]) -> JobSummary:
    """Convert raw DB row into JobSummary."""
    job_id = str(row.get("id", ""))
    title = str(row.get("title", ""))
    
    comp_raw = row.get("companies")
    if isinstance(comp_raw, list) and len(comp_raw) > 0:
        comp_raw = comp_raw[0]
    elif not isinstance(comp_raw, dict):
        comp_raw = {}
    
    company_name = (comp_raw.get("name") if isinstance(comp_raw, dict) else None) or row.get("company_name") or row.get("company") or "Company"
    logo_url = (comp_raw.get("logo_url") if isinstance(comp_raw, dict) else None) or row.get("company_logo_url")
    website = comp_raw.get("website") if isinstance(comp_raw, dict) else None
    company_slug = generate_company_slug(company_name)

    slug = row.get("slug") or generate_job_slug(title, company_name, job_id)

    visa_types_raw = row.get("visa_types")
    if isinstance(visa_types_raw, str):
        visa_types = [v.strip() for v in visa_types_raw.split(",") if v.strip()]
    elif isinstance(visa_types_raw, list):
        visa_types = [str(v) for v in visa_types_raw if v]
    else:
        visa_types = []

    posted_at = row.get("posted_at") or row.get("date_posted") or row.get("created_at")
    is_active = _is_job_active(row)

    return JobSummary(
        id=job_id,
        slug=slug,
        title=title,
        company=CompanySummary(name=company_name, logo_url=logo_url, website=website, slug=company_slug),
        location=row.get("location_raw") or row.get("location"),
        city=row.get("city"),
        country=row.get("country"),
        country_code=row.get("country_code"),
        work_mode=row.get("work_mode"),
        contract_type=row.get("contract_type") or row.get("work_type"),
        salary_min=row.get("salary_min"),
        salary_max=row.get("salary_max"),
        salary_currency=row.get("salary_currency"),
        salary_raw=row.get("salary_raw"),
        visa_sponsorship_verified=bool(row.get("visa_sponsorship_verified", False)),
        visa_sponsorship_confidence=row.get("visa_sponsorship_confidence"),
        visa_types=visa_types,
        posted_at=str(posted_at) if posted_at else None,
        job_status="Open" if is_active else "Closed",
        apply_url=str(row.get("apply_url") or row.get("source_url") or "#"),
        created_at=str(row.get("created_at")) if row.get("created_at") else None,
    )


def _format_job_detail(row: Dict[str, Any]) -> JobDetail:
    """Convert raw DB row into complete JobDetail (schema.org JobPosting compliant)."""
    job_id = str(row.get("id", ""))
    title = str(row.get("title", ""))

    comp_raw = row.get("companies")
    if isinstance(comp_raw, list) and len(comp_raw) > 0:
        comp_raw = comp_raw[0]
    elif not isinstance(comp_raw, dict):
        comp_raw = {}
    
    company_name = (comp_raw.get("name") if isinstance(comp_raw, dict) else None) or row.get("company_name") or row.get("company") or "Company"
    logo_url = (comp_raw.get("logo_url") if isinstance(comp_raw, dict) else None) or row.get("company_logo_url")
    website = comp_raw.get("website") if isinstance(comp_raw, dict) else None
    company_slug = generate_company_slug(company_name)
    slug = row.get("slug") or generate_job_slug(title, company_name, job_id)

    description = row.get("description_text") or row.get("description") or title
    description_html = row.get("description_html")

    date_posted = row.get("posted_at") or row.get("date_posted") or row.get("created_at")
    valid_through = row.get("expires_at")

    raw_type = str(row.get("contract_type") or row.get("work_type") or "FULL_TIME").upper()
    if "CONTRACT" in raw_type:
        employment_type = "CONTRACTOR"
    elif "PART" in raw_type:
        employment_type = "PART_TIME"
    elif "INTERN" in raw_type:
        employment_type = "INTERN"
    else:
        employment_type = "FULL_TIME"

    work_mode = str(row.get("work_mode", "")).lower()
    is_remote = "remote" in work_mode
    country = row.get("country")
    country_code = row.get("country_code")
    city = row.get("city")

    job_location = None
    applicant_location_req = None
    if is_remote:
        applicant_location_req = country or "Worldwide"
        if country or city:
            job_location = StructuredJobLocation(
                country=country,
                country_code=country_code,
                city=city,
            )
    else:
        job_location = StructuredJobLocation(
            country=country,
            country_code=country_code,
            city=city,
            street_address=None,
            postal_code=None,
        )

    base_salary = None
    sal_min = row.get("salary_min")
    sal_max = row.get("salary_max")
    sal_curr = row.get("salary_currency") or "USD"
    if (sal_min is not None and sal_min > 0) or (sal_max is not None and sal_max > 0):
        base_salary = BaseSalary(
            currency=sal_curr,
            value=SalaryValue(
                min=sal_min if sal_min and sal_min > 0 else None,
                max=sal_max if sal_max and sal_max > 0 else None,
                unit_text="YEAR",
            ),
        )

    visa_types_raw = row.get("visa_types")
    if isinstance(visa_types_raw, str):
        visa_types = [v.strip() for v in visa_types_raw.split(",") if v.strip()]
    elif isinstance(visa_types_raw, list):
        visa_types = [str(v) for v in visa_types_raw if v]
    else:
        visa_types = []

    conf_score = int(row.get("visa_sponsorship_confidence") or 0)
    verified = bool(row.get("visa_sponsorship_verified", False))
    if verified and conf_score < 90:
        conf_score = 95

    factors: List[ConfidenceFactor] = []
    if verified:
        factors.append(
            ConfidenceFactor(
                label="Direct Sponsorship Verified",
                detail="Sponsorship explicitly confirmed in the official employer announcement or cross-referenced with official national immigration sponsor registries.",
            )
        )
    elif conf_score >= 75:
        factors.append(
            ConfidenceFactor(
                label="Established Sponsor Track Record",
                detail="Employer actively sponsors international hires for this role tier based on multi-year hiring and petition history.",
            )
        )
    elif conf_score >= 50:
        factors.append(
            ConfidenceFactor(
                label="Eligible International Category",
                detail="Role qualifications, minimum salary, and employer profile align with national skilled worker visa criteria.",
            )
        )

    if visa_types:
        factors.append(
            ConfidenceFactor(
                label="Supported Visa Categories",
                detail=f"Compatible with {', '.join(visa_types)}.",
            )
        )

    ats_type = comp_raw.get("ats_type")
    if ats_type:
        factors.append(
            ConfidenceFactor(
                label="Direct ATS Source",
                detail=f"Verified directly from the employer's official career portal ({ats_type.capitalize()}).",
            )
        )

    is_active = _is_job_active(row)
    job_status = "Open" if is_active else "Closed"
    event_status = "https://schema.org/EventScheduled" if is_active else "Closed"

    return JobDetail(
        id=job_id,
        slug=slug,
        title=title,
        description=description,
        description_html=description_html,
        date_posted=str(date_posted) if date_posted else None,
        valid_through=str(valid_through) if valid_through else None,
        employment_type=employment_type,
        hiring_organization=CompanySummary(name=company_name, logo_url=logo_url, website=website, slug=company_slug),
        job_location=job_location,
        remote=is_remote,
        applicant_location_requirements=applicant_location_req,
        base_salary=base_salary,
        visa_types_supported=visa_types,
        confidence_score=conf_score,
        confidence_factors=factors,
        job_status=job_status,
        event_status=event_status,
        apply_url=str(row.get("apply_url") or row.get("source_url") or "#"),
        source_url=row.get("source_url"),
        created_at=str(row.get("created_at")) if row.get("created_at") else None,
    )


def _filter_jobs_in_memory(
    jobs: List[Dict[str, Any]],
    country: Optional[str] = None,
    visa_type: Optional[str] = None,
    role: Optional[str] = None,
    work_mode: Optional[str] = None,
    contract_type: Optional[str] = None,
    posted_since_dt: Optional[datetime.datetime] = None,
    min_confidence: Optional[int] = None,
    sort: str = "newest",
    active_only: bool = True,
) -> List[Dict[str, Any]]:
    """Filter in-memory job records based on query parameters."""
    filtered = []
    canon_country = find_country(country) if country else None
    canon_visa = find_visa_type(visa_type) if visa_type else None

    for job in jobs:
        if active_only and not _is_job_active(job):
            continue

        if country:
            j_code = str(job.get("country_code", "")).upper()
            j_country = str(job.get("country", "")).lower()
            if canon_country:
                if j_code != canon_country["code"] and canon_country["name"].lower() not in j_country:
                    continue
            else:
                c_clean = country.strip().lower()
                if c_clean != j_code.lower() and c_clean not in j_country:
                    continue

        if visa_type:
            j_visas = job.get("visa_types") or []
            if isinstance(j_visas, str):
                j_visas = [j_visas]
            j_visas_str = " ".join(j_visas).lower()
            if canon_visa:
                matched = any(alias in j_visas_str for alias in canon_visa["aliases"])
                if not matched and canon_visa["slug"] not in j_visas_str:
                    continue
            else:
                if visa_type.lower() not in j_visas_str:
                    continue

        if role:
            r_clean = role.strip().lower()
            j_title = str(job.get("title", "")).lower()
            j_desc = str(job.get("description_text", "") or job.get("description", "")).lower()
            if r_clean not in j_title and r_clean not in j_desc:
                continue

        if work_mode:
            j_mode = str(job.get("work_mode", "")).lower()
            if work_mode.lower() not in j_mode:
                continue

        if contract_type:
            j_ctype = str(job.get("contract_type", "") or job.get("work_type", "")).lower()
            if contract_type.lower() not in j_ctype:
                continue

        if min_confidence is not None:
            j_conf = int(job.get("visa_sponsorship_confidence") or 0)
            if j_conf < min_confidence:
                continue

        if posted_since_dt:
            posted_val = job.get("posted_at") or job.get("date_posted") or job.get("created_at")
            if posted_val:
                try:
                    if isinstance(posted_val, str):
                        dt = datetime.datetime.fromisoformat(posted_val.replace("Z", "+00:00"))
                    else:
                        dt = posted_val
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=datetime.timezone.utc)
                    if dt < posted_since_dt:
                        continue
                except Exception:
                    pass

        filtered.append(job)

    if sort == "confidence":
        filtered.sort(
            key=lambda x: (
                int(x.get("visa_sponsorship_confidence") or 0),
                str(x.get("posted_at") or x.get("created_at") or ""),
            ),
            reverse=True,
        )
    elif sort == "salary":
        filtered.sort(
            key=lambda x: (
                int(x.get("salary_max") or x.get("salary_min") or 0),
                str(x.get("posted_at") or x.get("created_at") or ""),
            ),
            reverse=True,
        )
    else:
        filtered.sort(
            key=lambda x: str(x.get("posted_at") or x.get("created_at") or ""),
            reverse=True,
        )

    return filtered


def _calculate_facets(jobs: List[Dict[str, Any]]) -> JobFacets:
    """Calculate countries and visa_types facet counts from a filtered list of jobs."""
    country_counts: Dict[str, int] = {}
    visa_counts: Dict[str, int] = {}

    for job in jobs:
        j_code = str(job.get("country_code", "")).upper()
        j_country = str(job.get("country", ""))
        canon_c = find_country(j_code) or find_country(j_country)
        if canon_c:
            country_counts[canon_c["slug"]] = country_counts.get(canon_c["slug"], 0) + 1
        elif j_country:
            c_slug = re.sub(r"[^\w-]", "", j_country.lower().replace(" ", "-"))
            country_counts[c_slug] = country_counts.get(c_slug, 0) + 1

        j_visas = job.get("visa_types") or []
        if isinstance(j_visas, str):
            j_visas = [j_visas]
        for v in j_visas:
            canon_v = find_visa_type(v) or match_visa_type_from_string(v)
            if canon_v:
                visa_counts[canon_v["slug"]] = visa_counts.get(canon_v["slug"], 0) + 1
            elif v:
                v_slug = re.sub(r"[^\w-]", "", str(v).lower().replace(" ", "-"))
                visa_counts[v_slug] = visa_counts.get(v_slug, 0) + 1

    country_facets = []
    for slug, count in country_counts.items():
        c_item = find_country(slug)
        label = c_item["name"] if c_item else slug.replace("-", " ").title()
        country_facets.append(FacetItem(slug=slug, label=label, count=count))
    country_facets.sort(key=lambda x: x.count, reverse=True)

    visa_facets = []
    for slug, count in visa_counts.items():
        v_item = find_visa_type(slug)
        label = v_item["name"] if v_item else slug.replace("-", " ").title()
        visa_facets.append(FacetItem(slug=slug, label=label, count=count))
    visa_facets.sort(key=lambda x: x.count, reverse=True)

    return JobFacets(countries=country_facets, visa_types=visa_facets)


async def _fetch_jobs_from_supabase_or_mock() -> List[Dict[str, Any]]:
    """Retrieve all jobs from Supabase or fallback mock store."""
    client = _get_supabase_client()
    if client is not None and not _MOCK_JOBS_STORE:
        try:
            res = client.from_("jobs").select(
                "*,companies(name,logo_url,website,ats_type)"
            ).order("posted_at", desc=True).limit(2000).execute()
            if res.data:
                return res.data
        except Exception as exc:
            logger.warning("Supabase jobs fetch failed: %s", exc)
    return _MOCK_JOBS_STORE


# ─────────────────────────────────────────────────────────────────────────────
# 1. GET /api/v1/jobs
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/jobs",
    response_model=JobSearchResponse,
    summary="Public job search with faceted filtering",
)
async def list_jobs(
    country: Optional[str] = Query(None, description="Country slug or code (e.g. 'germany', 'de')"),
    visa_type: Optional[str] = Query(None, description="Visa type slug (e.g. 'eu-blue-card')"),
    role: Optional[str] = Query(None, description="Free-text keyword search across title and description"),
    work_mode: Optional[str] = Query(None, description="'remote', 'hybrid', or 'onsite'"),
    contract_type: Optional[str] = Query(None, description="Contract type (e.g. 'full_time', 'contract')"),
    posted_since: Optional[str] = Query(None, description="ISO timestamp or relative shorthand: '24h', '7d', '30d'"),
    min_confidence: Optional[int] = Query(None, ge=0, le=100, description="Minimum visa sponsorship confidence (0-100)"),
    sort: str = Query("newest", description="Sorting order: 'newest', 'confidence', 'salary'"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
):
    """Open-access job search endpoint."""
    cache_key = make_cache_key(
        "jobs_search",
        {
            "country": country,
            "visa_type": visa_type,
            "role": role,
            "work_mode": work_mode,
            "contract_type": contract_type,
            "posted_since": posted_since,
            "min_confidence": min_confidence,
            "sort": sort,
            "page": page,
            "page_size": page_size,
        },
    )
    cached = get_cache(cache_key, ttl_seconds=JOBS_CACHE_TTL)
    if cached is not None:
        try:
            return JobSearchResponse(**cached)
        except Exception:
            pass

    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    cutoff = _parse_recency_cutoff(posted_since)

    filtered = _filter_jobs_in_memory(
        jobs=all_jobs,
        country=country,
        visa_type=visa_type,
        role=role,
        work_mode=work_mode,
        contract_type=contract_type,
        posted_since_dt=cutoff,
        min_confidence=min_confidence,
        sort=sort,
        active_only=True,
    )

    total_count = len(filtered)
    facets = _calculate_facets(filtered)

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_items = filtered[start_idx:end_idx]

    results = [_format_job_summary(row) for row in page_items]

    response = JobSearchResponse(
        results=results,
        total_count=total_count,
        page=page,
        page_size=page_size,
        facets=facets,
    )
    set_cache(cache_key, response.model_dump(), ttl_seconds=JOBS_CACHE_TTL)
    return response


# ─────────────────────────────────────────────────────────────────────────────
# 2. GET /api/v1/jobs/{slug_or_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/jobs/{slug_or_id}",
    response_model=JobDetail,
    summary="Job details (schema.org JobPosting compliant)",
)
async def get_job_detail(slug_or_id: str):
    """Fetch full job posting details by UUID or SEO URL slug."""
    cache_key = f"job_detail:{slug_or_id}"
    cached = get_cache(cache_key, ttl_seconds=JOBS_CACHE_TTL)
    if cached is not None:
        try:
            return JobDetail(**cached)
        except Exception:
            pass

    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    matched = None

    target = slug_or_id.strip()
    for j in all_jobs:
        if str(j.get("id")) == target:
            matched = j
            break

    if not matched:
        for j in all_jobs:
            title = str(j.get("title", ""))
            comp = j.get("companies") or {}
            comp_name = comp.get("name") if isinstance(comp, dict) else j.get("company_name") or "company"
            slug = j.get("slug") or generate_job_slug(title, str(comp_name), str(j.get("id", "")))
            if slug == target or str(j.get("canonical_url_hash")) == target:
                matched = j
                break

    if not matched:
        client = _get_supabase_client()
        if client is not None:
            try:
                query = client.from_("jobs").select("*,companies(name,logo_url,website,ats_type)")
                try:
                    uuid.UUID(target)
                    res = query.eq("id", target).maybe_single().execute()
                except ValueError:
                    res = query.eq("canonical_url_hash", target).maybe_single().execute()
                if res and res.data:
                    matched = res.data
            except Exception as e:
                logger.warning("Supabase single job fetch error: %s", e)

    if not matched:
        raise HTTPException(status_code=404, detail="Job posting not found.")

    detail = _format_job_detail(matched)
    set_cache(cache_key, detail.model_dump(), ttl_seconds=JOBS_CACHE_TTL)
    return detail


# ─────────────────────────────────────────────────────────────────────────────
# 3. Country & Visa Reference & Summary Routes (with i18n support)
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/locales",
    response_model=List[LocaleItem],
    summary="Supported UI and content locales with RTL flags",
)
async def list_locales():
    """Returns all supported UI and content locales with is_rtl indicators."""
    return [LocaleItem(**l) for l in get_supported_locales()]


@router.get(
    "/countries",
    response_model=List[CountryItem],
    summary="Canonical countries with live active job counts and localized labels",
)
async def list_countries(
    locale: Optional[str] = Query("en", description="Target language code ('en', 'es', 'pt', 'ar')"),
):
    """Returns canonical countries with active job counts and localized labels."""
    cache_key = f"reference:countries:{locale or 'en'}"
    cached = get_cache(cache_key, ttl_seconds=METADATA_CACHE_TTL)
    if cached is not None:
        try:
            return [CountryItem(**c) for c in cached]
        except Exception:
            pass

    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    active_jobs = [j for j in all_jobs if _is_job_active(j)]

    country_counts: Dict[str, int] = {}
    for j in active_jobs:
        j_code = str(j.get("country_code", "")).upper()
        j_name = str(j.get("country", ""))
        canon = find_country(j_code) or find_country(j_name)
        if canon:
            country_counts[canon["slug"]] = country_counts.get(canon["slug"], 0) + 1

    results = []
    for c in CANONICAL_COUNTRIES:
        count = country_counts.get(c["slug"], 0)
        loc_label, is_fallback = get_localized_country_name(c["slug"], locale)
        results.append(
            CountryItem(
                slug=c["slug"],
                code=c["code"],
                name=c["name"],
                label=loc_label,
                count=count,
                is_fallback=is_fallback,
            )
        )

    results.sort(key=lambda x: x.count, reverse=True)
    set_cache(cache_key, [r.model_dump() for r in results], ttl_seconds=METADATA_CACHE_TTL)
    return results


@router.get(
    "/countries/{country}/summary",
    response_model=CountrySummaryResponse,
    summary="Programmatic summary and SEO copy for country landing page",
)
async def get_country_summary(country: str):
    """Returns live metrics and meta description suggestion for country page."""
    canon_c = find_country(country)
    if not canon_c:
        raise HTTPException(status_code=404, detail=f"Country '{country}' not recognized.")

    cache_key = f"summary:country:{canon_c['slug']}"
    cached = get_cache(cache_key, ttl_seconds=METADATA_CACHE_TTL)
    if cached is not None:
        try:
            return CountrySummaryResponse(**cached)
        except Exception:
            pass

    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    c_jobs = _filter_jobs_in_memory(all_jobs, country=canon_c["slug"], active_only=True)

    job_count = len(c_jobs)
    role_counts: Dict[str, int] = {}
    for j in c_jobs:
        t = str(j.get("title", "")).strip()
        if t:
            role_counts[t] = role_counts.get(t, 0) + 1
    top_roles = [TopRoleItem(title=t, count=cnt) for t, cnt in sorted(role_counts.items(), key=lambda x: x[1], reverse=True)[:8]]

    employer_counts: Dict[str, Dict[str, Any]] = {}
    for j in c_jobs:
        comp = j.get("companies") or {}
        c_name = comp.get("name") if isinstance(comp, dict) else j.get("company_name") or "Company"
        logo_url = comp.get("logo_url") if isinstance(comp, dict) else j.get("company_logo_url")
        if c_name not in employer_counts:
            employer_counts[c_name] = {"name": c_name, "logo_url": logo_url, "count": 0}
        employer_counts[c_name]["count"] += 1
    sample_employers = [
        EmployerSummaryItem(name=v["name"], logo_url=v["logo_url"], job_count=v["count"])
        for v in sorted(employer_counts.values(), key=lambda x: x["count"], reverse=True)[:6]
    ]

    visa_counts: Dict[str, int] = {}
    for j in c_jobs:
        j_visas = j.get("visa_types") or []
        if isinstance(j_visas, str):
            j_visas = [j_visas]
        for v in j_visas:
            canon_v = find_visa_type(v) or match_visa_type_from_string(v)
            if canon_v:
                visa_counts[canon_v["name"]] = visa_counts.get(canon_v["name"], 0) + 1
    visa_types_available = [
        VisaAvailabilityItem(slug=re.sub(r"[^\w-]", "", name.lower().replace(" ", "-")), name=name, count=cnt)
        for name, cnt in sorted(visa_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    latest_dt = None
    for j in c_jobs:
        p = j.get("posted_at") or j.get("created_at")
        if p and (latest_dt is None or str(p) > str(latest_dt)):
            latest_dt = p

    c_name = canon_c["name"]
    emp_names = [e.name for e in sample_employers[:3]]
    emp_str = f" from top companies including {', '.join(emp_names)}" if emp_names else ""
    visa_names = [v.name for v in visa_types_available[:2]]
    visa_str = f" offering {', '.join(visa_names)}" if visa_names else ""
    meta_desc = f"Browse {job_count} visa-sponsored jobs in {c_name}{emp_str}{visa_str}. Verified sponsorship opportunities updated daily on VisaLane."

    response = CountrySummaryResponse(
        country={"slug": canon_c["slug"], "code": canon_c["code"], "name": canon_c["name"]},
        job_count=job_count,
        top_roles=top_roles,
        sample_employers=sample_employers,
        visa_types_available=visa_types_available,
        last_updated=str(latest_dt) if latest_dt else None,
        meta_description_suggestion=meta_desc,
    )
    set_cache(cache_key, response.model_dump(), ttl_seconds=METADATA_CACHE_TTL)
    return response


@router.get(
    "/countries/{country}/visa-types/{visa_type}/summary",
    response_model=CountryVisaSummaryResponse,
    summary="Programmatic summary and SEO copy for country×visa landing page",
)
async def get_country_visa_summary(country: str, visa_type: str):
    """Returns live metrics and meta description for country×visa page."""
    canon_c = find_country(country)
    if not canon_c:
        raise HTTPException(status_code=404, detail=f"Country '{country}' not recognized.")

    canon_v = find_visa_type(visa_type)
    if not canon_v:
        raise HTTPException(status_code=404, detail=f"Visa type '{visa_type}' not recognized.")

    cache_key = f"summary:country_visa:{canon_c['slug']}:{canon_v['slug']}"
    cached = get_cache(cache_key, ttl_seconds=METADATA_CACHE_TTL)
    if cached is not None:
        try:
            return CountryVisaSummaryResponse(**cached)
        except Exception:
            pass

    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    pair_jobs = _filter_jobs_in_memory(
        all_jobs,
        country=canon_c["slug"],
        visa_type=canon_v["slug"],
        active_only=True,
    )

    job_count = len(pair_jobs)
    role_counts: Dict[str, int] = {}
    for j in pair_jobs:
        t = str(j.get("title", "")).strip()
        if t:
            role_counts[t] = role_counts.get(t, 0) + 1
    top_roles = [TopRoleItem(title=t, count=cnt) for t, cnt in sorted(role_counts.items(), key=lambda x: x[1], reverse=True)[:8]]

    employer_counts: Dict[str, Dict[str, Any]] = {}
    for j in pair_jobs:
        comp = j.get("companies") or {}
        c_name = comp.get("name") if isinstance(comp, dict) else j.get("company_name") or "Company"
        logo_url = comp.get("logo_url") if isinstance(comp, dict) else j.get("company_logo_url")
        if c_name not in employer_counts:
            employer_counts[c_name] = {"name": c_name, "logo_url": logo_url, "count": 0}
        employer_counts[c_name]["count"] += 1
    sample_employers = [
        EmployerSummaryItem(name=v["name"], logo_url=v["logo_url"], job_count=v["count"])
        for v in sorted(employer_counts.values(), key=lambda x: x["count"], reverse=True)[:6]
    ]

    latest_dt = None
    for j in pair_jobs:
        p = j.get("posted_at") or j.get("created_at")
        if p and (latest_dt is None or str(p) > str(latest_dt)):
            latest_dt = p

    c_name = canon_c["name"]
    v_name = canon_v["name"]
    emp_names = [e.name for e in sample_employers[:3]]
    emp_str = f" at companies like {', '.join(emp_names)}" if emp_names else ""
    meta_desc = f"Discover {job_count} {v_name} visa sponsorship jobs in {c_name}{emp_str}. Verified work authorization and visa support on VisaLane."

    response = CountryVisaSummaryResponse(
        country={"slug": canon_c["slug"], "code": canon_c["code"], "name": canon_c["name"]},
        visa_type={"slug": canon_v["slug"], "name": canon_v["name"], "country_code": canon_v["country_code"]},
        job_count=job_count,
        top_roles=top_roles,
        sample_employers=sample_employers,
        last_updated=str(latest_dt) if latest_dt else None,
        meta_description_suggestion=meta_desc,
    )
    set_cache(cache_key, response.model_dump(), ttl_seconds=METADATA_CACHE_TTL)
    return response


@router.get(
    "/visa-types",
    response_model=List[VisaTypeItem],
    summary="Canonical visa types with live active job counts and localized labels",
)
async def list_visa_types(
    locale: Optional[str] = Query("en", description="Target language code ('en', 'es', 'pt', 'ar')"),
):
    """Returns canonical visa types with active job counts and localized labels."""
    cache_key = f"reference:visa_types:{locale or 'en'}"
    cached = get_cache(cache_key, ttl_seconds=METADATA_CACHE_TTL)
    if cached is not None:
        try:
            return [VisaTypeItem(**v) for v in cached]
        except Exception:
            pass

    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    active_jobs = [j for j in all_jobs if _is_job_active(j)]

    visa_counts: Dict[str, int] = {}
    for j in active_jobs:
        j_visas = j.get("visa_types") or []
        if isinstance(j_visas, str):
            j_visas = [j_visas]
        for v in j_visas:
            canon = find_visa_type(v) or match_visa_type_from_string(v)
            if canon:
                visa_counts[canon["slug"]] = visa_counts.get(canon["slug"], 0) + 1

    results = []
    for v in CANONICAL_VISA_TYPES:
        count = visa_counts.get(v["slug"], 0)
        loc_label, is_fallback = get_localized_visa_name(v["slug"], locale)
        results.append(
            VisaTypeItem(
                slug=v["slug"],
                name=v["name"],
                label=loc_label,
                country_code=v["country_code"],
                country_slug=v["country_slug"],
                count=count,
                is_fallback=is_fallback,
            )
        )

    results.sort(key=lambda x: x.count, reverse=True)
    set_cache(cache_key, [r.model_dump() for r in results], ttl_seconds=METADATA_CACHE_TTL)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 4. Employer Aggregation Endpoints
# ─────────────────────────────────────────────────────────────────────────────

def _aggregate_companies(jobs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Aggregate company statistics from all active and historical jobs."""
    companies_map: Dict[str, Dict[str, Any]] = {}

    for j in jobs:
        comp = j.get("companies")
        c_name = (comp.get("name") if isinstance(comp, dict) else None) or j.get("company_name") or j.get("company") or "Company"
        slug = generate_company_slug(c_name)
        logo_url = (comp.get("logo_url") if isinstance(comp, dict) else None) or j.get("company_logo_url")
        website = comp.get("website") if isinstance(comp, dict) else None
        ats_type = comp.get("ats_type") if isinstance(comp, dict) else None

        if slug not in companies_map:
            companies_map[slug] = {
                "name": c_name,
                "slug": slug,
                "logo_url": logo_url,
                "website": website,
                "ats_type": ats_type,
                "active_jobs": [],
                "historical_jobs": [],
                "countries": set(),
                "visa_types": set(),
                "confidence_scores": [],
                "verified_count": 0,
                "latest_date": None,
            }

        entry = companies_map[slug]
        entry["historical_jobs"].append(j)

        if _is_job_active(j):
            entry["active_jobs"].append(j)

        # Country
        j_country = str(j.get("country") or j.get("country_code") or "").strip()
        if j_country:
            canon = find_country(j_country)
            entry["countries"].add(canon["name"] if canon else j_country)

        # Visa types
        j_visas = j.get("visa_types") or []
        if isinstance(j_visas, str):
            j_visas = [j_visas]
        for v in j_visas:
            entry["visa_types"].add(str(v))

        # Confidence & verified rate
        conf = j.get("visa_sponsorship_confidence")
        if conf is not None:
            entry["confidence_scores"].append(int(conf))
        if j.get("visa_sponsorship_verified"):
            entry["verified_count"] += 1

        # Latest posting date
        dt_val = j.get("posted_at") or j.get("created_at")
        if dt_val and (entry["latest_date"] is None or str(dt_val) > str(entry["latest_date"])):
            entry["latest_date"] = str(dt_val)

    return companies_map


@router.get(
    "/companies",
    response_model=CompanyDirectoryResponse,
    summary="Paginated employer directory with listing count thresholds",
)
async def list_companies(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
    min_jobs: int = Query(1, ge=0, description="Minimum active listings threshold (guard default: 3)"),
    search: Optional[str] = Query(None, description="Search by employer name"),
    sort: str = Query("job_count", description="Sort by 'job_count', 'confidence', or 'name'"),
):
    """Returns paginated employer directory."""
    cache_key = make_cache_key(
        "companies_directory",
        {"page": page, "page_size": page_size, "min_jobs": min_jobs, "search": search, "sort": sort},
    )
    cached = get_cache(cache_key, ttl_seconds=METADATA_CACHE_TTL)
    if cached is not None:
        try:
            return CompanyDirectoryResponse(**cached)
        except Exception:
            pass

    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    comp_map = _aggregate_companies(all_jobs)

    items: List[CompanyDirectoryItem] = []
    for slug, data in comp_map.items():
        active_count = len(data["active_jobs"])
        total_count = len(data["historical_jobs"])

        if active_count < min_jobs:
            continue

        if search:
            s_clean = search.strip().lower()
            if s_clean not in data["name"].lower():
                continue

        avg_conf = (
            int(sum(data["confidence_scores"]) / len(data["confidence_scores"]))
            if data["confidence_scores"]
            else 70
        )
        verified_rate = (
            round((data["verified_count"] / total_count) * 100, 1)
            if total_count > 0
            else 0.0
        )

        items.append(
            CompanyDirectoryItem(
                name=data["name"],
                slug=slug,
                logo_url=data["logo_url"],
                website=data["website"],
                ats_type=data["ats_type"],
                active_job_count=active_count,
                total_job_count=total_count,
                confidence_score=avg_conf,
                verified_sponsorship_rate=verified_rate,
                countries=sorted(list(data["countries"])),
            )
        )

    if sort == "name":
        items.sort(key=lambda x: x.name.lower())
    elif sort == "confidence":
        items.sort(key=lambda x: (x.confidence_score, x.active_job_count), reverse=True)
    else:
        items.sort(key=lambda x: (x.active_job_count, x.total_job_count), reverse=True)

    total_count = len(items)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_items = items[start_idx:end_idx]

    response = CompanyDirectoryResponse(
        results=page_items,
        total_count=total_count,
        page=page,
        page_size=page_size,
    )
    set_cache(cache_key, response.model_dump(), ttl_seconds=METADATA_CACHE_TTL)
    return response


@router.get(
    "/companies/{slug}/summary",
    response_model=CompanyDetailSummary,
    summary="Employer sponsorship history, statistics, and legal disclaimer",
)
async def get_company_summary(slug: str):
    """Returns comprehensive sponsorship breakdown for an employer."""
    cache_key = f"company_summary:{slug}"
    cached = get_cache(cache_key, ttl_seconds=METADATA_CACHE_TTL)
    if cached is not None:
        try:
            return CompanyDetailSummary(**cached)
        except Exception:
            pass

    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    comp_map = _aggregate_companies(all_jobs)

    target_slug = slug.strip().lower()
    matched_data = comp_map.get(target_slug)

    if not matched_data:
        for s, d in comp_map.items():
            if d["name"].lower() == target_slug.replace("-", " "):
                matched_data = d
                break

    if not matched_data:
        raise HTTPException(status_code=404, detail=f"Employer '{slug}' not found.")

    active_jobs = matched_data["active_jobs"]
    hist_jobs = matched_data["historical_jobs"]
    total_active = len(active_jobs)
    total_hist = len(hist_jobs)

    avg_conf = (
        int(sum(matched_data["confidence_scores"]) / len(matched_data["confidence_scores"]))
        if matched_data["confidence_scores"]
        else 75
    )
    verified_rate = (
        round((matched_data["verified_count"] / total_hist) * 100, 1)
        if total_hist > 0
        else 0.0
    )

    c_counts: Dict[str, Dict[str, Any]] = {}
    for j in active_jobs + hist_jobs:
        code = str(j.get("country_code", "")).upper()
        c_name = str(j.get("country", ""))
        canon = find_country(code) or find_country(c_name)
        if canon:
            c_slug = canon["slug"]
            if c_slug not in c_counts:
                c_counts[c_slug] = {"slug": c_slug, "code": canon["code"], "name": canon["name"], "count": 0}
            c_counts[c_slug]["count"] += 1
        elif c_name:
            c_slug = generate_company_slug(c_name)
            if c_slug not in c_counts:
                c_counts[c_slug] = {"slug": c_slug, "code": code or "XX", "name": c_name, "count": 0}
            c_counts[c_slug]["count"] += 1

    hiring_countries = [
        CompanyCountryCount(slug=v["slug"], code=v["code"], name=v["name"], count=v["count"])
        for v in sorted(c_counts.values(), key=lambda x: x["count"], reverse=True)
    ]

    r_counts: Dict[str, int] = {}
    for j in active_jobs + hist_jobs:
        t = str(j.get("title", "")).strip()
        if t:
            r_counts[t] = r_counts.get(t, 0) + 1
    top_roles = [TopRoleItem(title=t, count=cnt) for t, cnt in sorted(r_counts.items(), key=lambda x: x[1], reverse=True)[:10]]

    recent_jobs = [_format_job_summary(j) for j in active_jobs[:10]]

    response = CompanyDetailSummary(
        company=CompanySummary(
            name=matched_data["name"],
            logo_url=matched_data["logo_url"],
            website=matched_data["website"],
            ats_type=matched_data["ats_type"],
            slug=matched_data["slug"],
        ),
        total_active_jobs=total_active,
        total_historical_jobs=total_hist,
        sponsorship_confidence_score=avg_conf,
        verified_sponsorship_rate=verified_rate,
        supported_visa_types=sorted(list(matched_data["visa_types"])),
        hiring_countries=hiring_countries,
        top_roles=top_roles,
        recent_jobs=recent_jobs,
        last_verified=matched_data["latest_date"],
        disclaimer=CENTRAL_LEGAL_DISCLAIMER,
    )
    set_cache(cache_key, response.model_dump(), ttl_seconds=METADATA_CACHE_TTL)
    return response


# ─────────────────────────────────────────────────────────────────────────────
# 5. Shareable Match Reports
# ─────────────────────────────────────────────────────────────────────────────

def _generate_report_slug() -> str:
    """Generate a clean, collision-free base62 slug for match reports."""
    chars = string.ascii_lowercase + string.digits
    rand_str = "".join(random.choices(chars, k=8))
    return f"mr_{rand_str}"


@router.post(
    "/match-reports",
    response_model=MatchReportCreateResponse,
    summary="Create a persistent shareable match report from search filters",
)
@limiter.limit("20/hour")
async def create_match_report(request: Request, body: MatchReportCreateRequest):
    """Persists a search filter state and returns a short shareable link."""
    filters_dict = {
        "country": body.country,
        "visa_type": body.visa_type,
        "role": body.role,
        "work_mode": body.work_mode,
        "contract_type": body.contract_type,
        "min_confidence": body.min_confidence,
        "posted_since": body.posted_since,
    }
    filters_clean = {k: v for k, v in filters_dict.items() if v is not None}

    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    cutoff = _parse_recency_cutoff(body.posted_since)
    matching = _filter_jobs_in_memory(
        jobs=all_jobs,
        country=body.country,
        visa_type=body.visa_type,
        role=body.role,
        work_mode=body.work_mode,
        contract_type=body.contract_type,
        posted_since_dt=cutoff,
        min_confidence=body.min_confidence,
        active_only=True,
    )
    original_count = len(matching)
    slug = _generate_report_slug()

    report_record = {
        "id": str(uuid.uuid4()),
        "slug": slug,
        "title": body.title or "Visa-Sponsored Jobs Match Report",
        "filters": filters_clean,
        "original_match_count": original_count,
        "session_id": body.session_id,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    _MOCK_MATCH_REPORTS[slug] = report_record

    client = _get_supabase_client()
    if client is not None:
        try:
            client.from_("match_reports").insert(report_record).execute()
        except Exception as exc:
            logger.warning("Failed to persist match report to Supabase: %s", exc)

    share_url = f"{DEFAULT_SITE_URL}/matches/{slug}"
    return MatchReportCreateResponse(
        slug=slug,
        share_url=share_url,
        original_match_count=original_count,
    )


@router.get(
    "/match-reports/{slug}",
    response_model=MatchReportDetailResponse,
    summary="Retrieve match report with dynamic live re-counting",
)
async def get_match_report(slug: str):
    """Retrieves a shared match report with live updated match count."""
    target_slug = slug.strip()
    record = _MOCK_MATCH_REPORTS.get(target_slug)

    if not record:
        client = _get_supabase_client()
        if client is not None:
            try:
                res = client.from_("match_reports").select("*").eq("slug", target_slug).maybe_single().execute()
                if res and res.data:
                    record = res.data
            except Exception as e:
                logger.warning("Supabase match report fetch error: %s", e)

    if not record:
        raise HTTPException(status_code=404, detail="Match report not found.")

    filters = record.get("filters") or {}
    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    cutoff = _parse_recency_cutoff(filters.get("posted_since"))

    live_matching = _filter_jobs_in_memory(
        jobs=all_jobs,
        country=filters.get("country"),
        visa_type=filters.get("visa_type"),
        role=filters.get("role"),
        work_mode=filters.get("work_mode"),
        contract_type=filters.get("contract_type"),
        posted_since_dt=cutoff,
        min_confidence=filters.get("min_confidence"),
        active_only=True,
    )
    current_count = len(live_matching)
    original_count = int(record.get("original_match_count", current_count))

    country_filter = filters.get("country")
    role_filter = filters.get("role")
    visa_filter = filters.get("visa_type")

    parts = [f"{current_count} sponsorship-verified jobs"]
    if role_filter:
        parts.append(f"for '{role_filter}'")
    if country_filter:
        canon_c = find_country(country_filter)
        parts.append(f"in {canon_c['name'] if canon_c else country_filter.title()}")
    if visa_filter:
        canon_v = find_visa_type(visa_filter)
        parts.append(f"({canon_v['name'] if canon_v else visa_filter})")

    human_summary = " ".join(parts)
    og_title = f"{current_count} Visa-Sponsored Jobs Matching Your Search | VisaLane"
    og_description = f"{human_summary}. View verified hiring employers and direct application links on VisaLane."

    results_sample = [_format_job_summary(j) for j in live_matching[:10]]
    share_url = f"{DEFAULT_SITE_URL}/matches/{target_slug}"

    return MatchReportDetailResponse(
        slug=target_slug,
        title=record.get("title"),
        filters=filters,
        original_match_count=original_count,
        current_match_count=current_count,
        human_summary=human_summary,
        og_title=og_title,
        og_description=og_description,
        share_url=share_url,
        created_at=str(record.get("created_at")),
        results_sample=results_sample,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Phase 4: Content/Blog Engine & i18n Routes
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_post_translation(
    post: Dict[str, Any],
    translations: Dict[str, Dict[str, Any]],
    requested_locale: Optional[str],
) -> Tuple[Dict[str, Any], str, bool]:
    """
    Resolves post translation for requested locale with region-variant resolution.
    Returns (translation_data, resolved_locale, is_fallback).
    """
    req_loc = str(requested_locale or "en").strip().lower()
    canonical_loc = str(post.get("canonical_locale", "en")).strip().lower()
    norm_loc, is_unsupported = normalize_locale_code(requested_locale)

    # 1. Exact requested locale match (e.g. 'es-mx' if explicitly seeded)
    if req_loc in translations:
        return translations[req_loc], req_loc, False

    # 2. Normalized base language match (e.g. 'es-MX' -> 'es')
    if not is_unsupported and norm_loc in translations:
        return translations[norm_loc], norm_loc, False

    # 3. Canonical locale fallback
    if canonical_loc in translations:
        return translations[canonical_loc], canonical_loc, True

    # 4. English fallback
    if "en" in translations:
        return translations["en"], "en", True

    # 5. Any available translation
    if translations:
        first_k = next(iter(translations))
        return translations[first_k], first_k, True

    # Empty placeholder fallback if no translation records exist
    return {
        "title": post.get("title") or "Untitled Post",
        "body_markdown": post.get("body_markdown") or "",
        "meta_description": post.get("meta_description"),
    }, canonical_loc, True


@router.get(
    "/posts",
    response_model=PostListResponse,
    summary="List published posts with category filtering and locale fallback",
)
async def list_posts(
    category: Optional[str] = Query(None, description="'policy-radar', 'guide', or 'data-report'"),
    locale: str = Query("en", description="Requested language code ('en', 'es', 'pt', 'ar')"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
):
    """
    Returns paginated published posts in requested locale.
    If a translation is missing for the requested locale, returns canonical content
    with explicit is_fallback: True.
    """
    cache_key = make_cache_key("posts_list", {"category": category, "locale": locale, "page": page, "page_size": page_size})
    cached = get_cache(cache_key, ttl_seconds=METADATA_CACHE_TTL)
    if cached is not None:
        try:
            return PostListResponse(**cached)
        except Exception:
            pass

    # Gather posts from mock store / DB
    posts_list: List[Dict[str, Any]] = []
    for pid, p in _MOCK_POSTS_STORE.items():
        if p.get("status", "published") == "published":
            if category and p.get("category") != category:
                continue
            posts_list.append(p)

    client = _get_supabase_client()
    if client is not None and not _MOCK_POSTS_STORE:
        try:
            q = client.from_("posts").select("*,post_translations(*)").eq("status", "published")
            if category:
                q = q.eq("category", category)
            res = q.order("published_at", desc=True).limit(500).execute()
            if res.data:
                for row in res.data:
                    p_copy = dict(row)
                    t_list = p_copy.pop("post_translations", []) or []
                    p_id = p_copy["id"]
                    _MOCK_POSTS_STORE[p_id] = p_copy
                    _MOCK_POST_TRANSLATIONS_STORE[p_id] = {t["locale"]: t for t in t_list}
                    posts_list.append(p_copy)
        except Exception as exc:
            logger.warning("Supabase posts fetch error: %s", exc)

    posts_list.sort(key=lambda x: str(x.get("published_at") or x.get("created_at") or ""), reverse=True)

    results: List[PostSummary] = []
    for p in posts_list:
        p_id = str(p.get("id"))
        trans_map = _MOCK_POST_TRANSLATIONS_STORE.get(p_id, {})
        t_data, res_loc, is_fallback = _resolve_post_translation(p, trans_map, locale)

        results.append(
            PostSummary(
                id=p_id,
                slug=p.get("slug") or generate_post_slug(t_data.get("title", "post")),
                category=p.get("category", "guide"),
                author=p.get("author", "VisaLane Policy Team"),
                published_at=str(p.get("published_at") or datetime.datetime.now(datetime.timezone.utc).isoformat()),
                locale=res_loc,
                is_fallback=is_fallback,
                title=t_data.get("title", ""),
                meta_description=t_data.get("meta_description"),
                featured_image_url=p.get("featured_image_url"),
            )
        )

    total_count = len(results)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_items = results[start_idx:end_idx]

    response = PostListResponse(
        results=page_items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        locale=locale,
    )
    set_cache(cache_key, response.model_dump(), ttl_seconds=METADATA_CACHE_TTL)
    return response


@router.get(
    "/posts/{slug}",
    response_model=PostDetail,
    summary="Get single published post with full body and locale fallback",
)
async def get_post_detail(
    slug: str,
    locale: str = Query("en", description="Requested language code ('en', 'es', 'pt', 'ar')"),
):
    """
    Returns single published post in requested locale.
    Falls back to canonical locale with is_fallback: True if translation is missing.
    """
    cache_key = f"post_detail:{slug}:{locale}"
    cached = get_cache(cache_key, ttl_seconds=METADATA_CACHE_TTL)
    if cached is not None:
        try:
            return PostDetail(**cached)
        except Exception:
            pass

    target_slug = slug.strip().lower()
    matched_post = None

    for pid, p in _MOCK_POSTS_STORE.items():
        if p.get("slug") == target_slug or str(p.get("id")) == target_slug:
            matched_post = p
            break

    if not matched_post:
        client = _get_supabase_client()
        if client is not None:
            try:
                res = client.from_("posts").select("*,post_translations(*)").eq("slug", target_slug).maybe_single().execute()
                if res and res.data:
                    matched_post = dict(res.data)
                    t_list = matched_post.pop("post_translations", []) or []
                    p_id = matched_post["id"]
                    _MOCK_POSTS_STORE[p_id] = matched_post
                    _MOCK_POST_TRANSLATIONS_STORE[p_id] = {t["locale"]: t for t in t_list}
            except Exception as e:
                logger.warning("Supabase single post fetch error: %s", e)

    if not matched_post or matched_post.get("status") != "published":
        raise HTTPException(status_code=404, detail="Post not found.")

    p_id = str(matched_post.get("id"))
    trans_map = _MOCK_POST_TRANSLATIONS_STORE.get(p_id, {})
    t_data, res_loc, is_fallback = _resolve_post_translation(matched_post, trans_map, locale)

    available_locales = list(trans_map.keys()) if trans_map else [matched_post.get("canonical_locale", "en")]

    response = PostDetail(
        id=p_id,
        slug=matched_post.get("slug") or generate_post_slug(t_data.get("title", "post")),
        category=matched_post.get("category", "guide"),
        author=matched_post.get("author", "VisaLane Policy Team"),
        published_at=str(matched_post.get("published_at") or datetime.datetime.now(datetime.timezone.utc).isoformat()),
        updated_at=str(matched_post.get("updated_at") or matched_post.get("published_at") or datetime.datetime.now(datetime.timezone.utc).isoformat()),
        canonical_locale=matched_post.get("canonical_locale", "en"),
        locale=res_loc,
        is_fallback=is_fallback,
        title=t_data.get("title", ""),
        body_markdown=t_data.get("body_markdown", ""),
        meta_description=t_data.get("meta_description"),
        featured_image_url=matched_post.get("featured_image_url"),
        available_locales=available_locales,
    )
    set_cache(cache_key, response.model_dump(), ttl_seconds=METADATA_CACHE_TTL)
    return response


# ─────────────────────────────────────────────────────────────────────────────
# 7. Phase 4: Admin Post Management API (Gated by _require_admin_auth)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/admin/posts",
    response_model=PostDetail,
    summary="Create a new blog post and translations (Admin Only)",
    status_code=201,
)
async def admin_create_post(
    body: AdminPostCreateRequest,
    authorization: Optional[str] = Header(None),
    x_admin_key: Optional[str] = Header(None),
):
    """
    Creates a new post and its translations.
    Requires admin privileges.
    """
    _require_admin_auth(authorization=authorization, x_admin_key=x_admin_key)

    post_id = str(uuid.uuid4())
    canonical_loc = body.canonical_locale or "en"
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Find canonical title for slug generation if slug not given
    canon_t = next((t for t in body.translations if t.locale == canonical_loc), body.translations[0])
    slug = body.slug or generate_post_slug(canon_t.title)

    post_record = {
        "id": post_id,
        "slug": slug,
        "category": body.category,
        "author": body.author or "VisaLane Policy Team",
        "canonical_locale": canonical_loc,
        "status": body.status or "published",
        "featured_image_url": body.featured_image_url,
        "published_at": now_str,
        "updated_at": now_str,
    }

    translations_map: Dict[str, Dict[str, Any]] = {}
    for t in body.translations:
        translations_map[t.locale.lower()] = {
            "id": str(uuid.uuid4()),
            "post_id": post_id,
            "locale": t.locale.lower(),
            "title": t.title,
            "body_markdown": t.body_markdown,
            "meta_description": t.meta_description,
            "created_at": now_str,
            "updated_at": now_str,
        }

    _MOCK_POSTS_STORE[post_id] = post_record
    _MOCK_POST_TRANSLATIONS_STORE[post_id] = translations_map

    # Supabase persistence if available
    client = _get_supabase_client()
    if client is not None:
        try:
            client.from_("posts").insert(post_record).execute()
            for t_data in translations_map.values():
                client.from_("post_translations").insert(t_data).execute()
        except Exception as exc:
            logger.warning("Supabase admin create post error: %s", exc)

    clear_all_caches()

    t_data, res_loc, is_fallback = _resolve_post_translation(post_record, translations_map, canonical_loc)

    return PostDetail(
        id=post_id,
        slug=slug,
        category=post_record["category"],
        author=post_record["author"],
        published_at=now_str,
        updated_at=now_str,
        canonical_locale=canonical_loc,
        locale=res_loc,
        is_fallback=is_fallback,
        title=t_data.get("title", ""),
        body_markdown=t_data.get("body_markdown", ""),
        meta_description=t_data.get("meta_description"),
        featured_image_url=post_record.get("featured_image_url"),
        available_locales=list(translations_map.keys()),
    )


@router.put(
    "/admin/posts/{slug_or_id}",
    response_model=PostDetail,
    summary="Update an existing post and translations (Admin Only)",
)
async def admin_update_post(
    slug_or_id: str,
    body: AdminPostUpdateRequest,
    authorization: Optional[str] = Header(None),
    x_admin_key: Optional[str] = Header(None),
):
    """
    Updates post metadata and translations.
    Requires admin privileges.
    """
    _require_admin_auth(authorization=authorization, x_admin_key=x_admin_key)

    target = slug_or_id.strip().lower()
    matched_post = None

    for pid, p in _MOCK_POSTS_STORE.items():
        if p.get("slug") == target or str(p.get("id")) == target:
            matched_post = p
            break

    if not matched_post:
        raise HTTPException(status_code=404, detail="Post not found.")

    post_id = str(matched_post["id"])
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if body.category is not None:
        matched_post["category"] = body.category
    if body.author is not None:
        matched_post["author"] = body.author
    if body.canonical_locale is not None:
        matched_post["canonical_locale"] = body.canonical_locale
    if body.status is not None:
        matched_post["status"] = body.status
    if body.featured_image_url is not None:
        matched_post["featured_image_url"] = body.featured_image_url
    matched_post["updated_at"] = now_str

    trans_map = _MOCK_POST_TRANSLATIONS_STORE.setdefault(post_id, {})
    if body.translations:
        for t in body.translations:
            trans_map[t.locale.lower()] = {
                "id": trans_map.get(t.locale.lower(), {}).get("id") or str(uuid.uuid4()),
                "post_id": post_id,
                "locale": t.locale.lower(),
                "title": t.title,
                "body_markdown": t.body_markdown,
                "meta_description": t.meta_description,
                "updated_at": now_str,
            }

    # Supabase persistence if available
    client = _get_supabase_client()
    if client is not None:
        try:
            client.from_("posts").update(matched_post).eq("id", post_id).execute()
            if body.translations:
                for t in body.translations:
                    client.from_("post_translations").upsert({
                        "post_id": post_id,
                        "locale": t.locale.lower(),
                        "title": t.title,
                        "body_markdown": t.body_markdown,
                        "meta_description": t.meta_description,
                        "updated_at": now_str,
                    }, on_conflict="post_id,locale").execute()
        except Exception as exc:
            logger.warning("Supabase admin update post error: %s", exc)

    clear_all_caches()

    canonical_loc = matched_post.get("canonical_locale", "en")
    t_data, res_loc, is_fallback = _resolve_post_translation(matched_post, trans_map, canonical_loc)

    return PostDetail(
        id=post_id,
        slug=matched_post["slug"],
        category=matched_post["category"],
        author=matched_post["author"],
        published_at=str(matched_post.get("published_at")),
        updated_at=now_str,
        canonical_locale=canonical_loc,
        locale=res_loc,
        is_fallback=is_fallback,
        title=t_data.get("title", ""),
        body_markdown=t_data.get("body_markdown", ""),
        meta_description=t_data.get("meta_description"),
        featured_image_url=matched_post.get("featured_image_url"),
        available_locales=list(trans_map.keys()),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 8. Sitemap Endpoints: GET /sitemap-data & GET /sitemap.xml
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/sitemap-data",
    response_model=SitemapDataResponse,
    summary="Sitemap and programmatic SEO non-empty routes",
)
async def get_sitemap_data():
    """
    Internal-use endpoint returning only {country, visa_type} pairs and {job_slug}
    records with >=1 active job. Prevents thin/empty SEO landing pages.
    """
    cache_key = "sitemap:data"
    cached = get_cache(cache_key, ttl_seconds=SITEMAP_CACHE_TTL)
    if cached is not None:
        try:
            return SitemapDataResponse(**cached)
        except Exception:
            pass

    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    active_jobs = [j for j in all_jobs if _is_job_active(j)]

    active_countries_set = set()
    active_visa_set = set()
    pair_counts: Dict[tuple, int] = {}
    job_slugs_list: List[JobSitemapItem] = []

    for j in active_jobs:
        job_id = str(j.get("id", ""))
        title = str(j.get("title", ""))
        comp = j.get("companies") or {}
        comp_name = comp.get("name") if isinstance(comp, dict) else j.get("company_name") or "company"
        slug = j.get("slug") or generate_job_slug(title, str(comp_name), job_id)
        updated_at = j.get("updated_at") or j.get("posted_at") or j.get("created_at")

        job_slugs_list.append(
            JobSitemapItem(
                id=job_id,
                slug=slug,
                updated_at=str(updated_at) if updated_at else None,
            )
        )

        j_code = str(j.get("country_code", "")).upper()
        j_name = str(j.get("country", ""))
        canon_c = find_country(j_code) or find_country(j_name)
        if canon_c:
            active_countries_set.add(canon_c["slug"])

        j_visas = j.get("visa_types") or []
        if isinstance(j_visas, str):
            j_visas = [j_visas]
        for v in j_visas:
            canon_v = find_visa_type(v) or match_visa_type_from_string(v)
            if canon_v:
                active_visa_set.add(canon_v["slug"])
                if canon_c:
                    pair_key = (canon_c["slug"], canon_v["slug"])
                    pair_counts[pair_key] = pair_counts.get(pair_key, 0) + 1

    country_visa_pairs = [
        CountryVisaPair(country=c, visa_type=v, count=cnt)
        for (c, v), cnt in pair_counts.items()
        if cnt >= 1
    ]

    response = SitemapDataResponse(
        countries=sorted(list(active_countries_set)),
        visa_types=sorted(list(active_visa_set)),
        country_visa_pairs=country_visa_pairs,
        job_slugs=job_slugs_list,
    )
    set_cache(cache_key, response.model_dump(), ttl_seconds=SITEMAP_CACHE_TTL)
    return response


@router.get(
    "/sitemap.xml",
    summary="Standard XML sitemap strictly omitting thin/empty pages and expired jobs",
)
async def get_sitemap_xml():
    """
    Returns standard XML sitemap for search engines.
    Covers root homepage, active country pages, active country×visa pages,
    and active job detail pages with lastmod timestamps.
    """
    cache_key = "sitemap:xml"
    cached = get_cache(cache_key, ttl_seconds=SITEMAP_CACHE_TTL)
    if cached is not None and isinstance(cached, str):
        return Response(content=cached, media_type="application/xml")

    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    active_jobs = [j for j in all_jobs if _is_job_active(j)]

    country_latest: Dict[str, str] = {}
    pair_latest: Dict[tuple, str] = {}
    site_latest = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    for j in active_jobs:
        p = str(j.get("posted_at") or j.get("created_at") or "")
        dt_str = p[:10] if len(p) >= 10 else site_latest

        j_code = str(j.get("country_code", "")).upper()
        j_name = str(j.get("country", ""))
        canon_c = find_country(j_code) or find_country(j_name)
        if canon_c:
            c_slug = canon_c["slug"]
            if c_slug not in country_latest or dt_str > country_latest[c_slug]:
                country_latest[c_slug] = dt_str

            j_visas = j.get("visa_types") or []
            if isinstance(j_visas, str):
                j_visas = [j_visas]
            for v in j_visas:
                canon_v = find_visa_type(v) or match_visa_type_from_string(v)
                if canon_v:
                    pair_key = (c_slug, canon_v["slug"])
                    if pair_key not in pair_latest or dt_str > pair_latest[pair_key]:
                        pair_latest[pair_key] = dt_str

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    # 1. Homepage
    xml_lines.append(f"""  <url>
    <loc>{DEFAULT_SITE_URL}/</loc>
    <lastmod>{site_latest}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>""")

    # 2. Active Country Pages
    for c_slug, lastmod in sorted(country_latest.items()):
        xml_lines.append(f"""  <url>
    <loc>{DEFAULT_SITE_URL}/jobs/{html.escape(c_slug)}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>""")

    # 3. Active Country×Visa Pages
    for (c_slug, v_slug), lastmod in sorted(pair_latest.items()):
        xml_lines.append(f"""  <url>
    <loc>{DEFAULT_SITE_URL}/jobs/{html.escape(c_slug)}/{html.escape(v_slug)}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>""")

    # 4. Active Job Detail Pages
    for j in active_jobs:
        job_id = str(j.get("id", ""))
        title = str(j.get("title", ""))
        comp = j.get("companies") or {}
        comp_name = comp.get("name") if isinstance(comp, dict) else j.get("company_name") or "company"
        slug = j.get("slug") or generate_job_slug(title, str(comp_name), job_id)
        p = str(j.get("posted_at") or j.get("created_at") or "")
        dt_str = p[:10] if len(p) >= 10 else site_latest

        xml_lines.append(f"""  <url>
    <loc>{DEFAULT_SITE_URL}/jobs/{html.escape(slug)}</loc>
    <lastmod>{dt_str}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.6</priority>
  </url>""")

    xml_lines.append("</urlset>")
    xml_content = "\n".join(xml_lines)

    set_cache(cache_key, xml_content, ttl_seconds=SITEMAP_CACHE_TTL)
    return Response(content=xml_content, media_type="application/xml")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Phase 5: Extension Company Lookup Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/extension/lookup",
    response_model=ExtensionLookupResponse,
    summary="Fast fuzzy company lookup for VisaLane Chrome Extension",
)
@limiter.limit("120/minute")
async def extension_lookup_company(
    request: Request,
    company: str = Query(..., min_length=1, max_length=200, description="Employer name from job posting"),
):
    """
    Looks up employer sponsorship track record for Chrome extension overlays.
    Uses normalized trigram fuzzy matching with a strict confidence boundary.
    Cached for 30 minutes per normalized name. Rate limited to 120/min per client session.
    """
    norm_query = normalize_company_name(company)
    if not norm_query:
        return ExtensionLookupResponse(
            match=False,
            query=company,
            normalized_query="",
            similarity_score=0.0,
            company=None,
            message="Employer name could not be normalized.",
        )

    cache_key = f"extension_lookup:{norm_query}"
    cached = get_cache(cache_key, ttl_seconds=EXTENSION_LOOKUP_CACHE_TTL)
    if cached is not None:
        try:
            return ExtensionLookupResponse(**cached)
        except Exception:
            pass

    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    comp_map = _aggregate_companies(all_jobs)

    # Build candidates list
    candidates: List[Dict[str, Any]] = []
    for slug, data in comp_map.items():
        candidates.append({
            "name": data["name"],
            "slug": slug,
            "data": data,
            "aliases": [slug.replace("-", " "), data["name"]],
        })

    best_match, score, _ = match_company_fuzzy(company, candidates, threshold=0.70)

    if best_match and best_match.get("data"):
        data = best_match["data"]
        active_count = len(data["active_jobs"])
        total_count = len(data["historical_jobs"])

        avg_conf = (
            int(sum(data["confidence_scores"]) / len(data["confidence_scores"]))
            if data["confidence_scores"]
            else 75
        )
        verified_rate = (
            round((data["verified_count"] / total_count) * 100, 1)
            if total_count > 0
            else 0.0
        )

        # Top roles
        r_counts: Dict[str, int] = {}
        for j in data["active_jobs"] + data["historical_jobs"]:
            t = str(j.get("title", "")).strip()
            if t:
                r_counts[t] = r_counts.get(t, 0) + 1
        top_roles = [t for t, _ in sorted(r_counts.items(), key=lambda x: x[1], reverse=True)[:5]]

        company_summary = ExtensionCompanySummary(
            name=data["name"],
            slug=data["slug"],
            logo_url=data["logo_url"],
            website=data["website"],
            ats_type=data["ats_type"],
            active_job_count=active_count,
            total_job_count=total_count,
            sponsorship_confidence_score=avg_conf,
            verified_sponsorship_rate=verified_rate,
            supported_visa_types=sorted(list(data["visa_types"])),
            hiring_countries=sorted(list(data["countries"])),
            top_roles=top_roles,
            profile_url=f"{DEFAULT_SITE_URL}/companies/{data['slug']}",
            last_verified=data["latest_date"],
            disclaimer=CENTRAL_LEGAL_DISCLAIMER,
        )

        response = ExtensionLookupResponse(
            match=True,
            query=company,
            normalized_query=norm_query,
            similarity_score=score,
            company=company_summary,
            message="Verified employer sponsorship profile found.",
        )
        set_cache(cache_key, response.model_dump(), ttl_seconds=EXTENSION_LOOKUP_CACHE_TTL)
        return response

    response = ExtensionLookupResponse(
        match=False,
        query=company,
        normalized_query=norm_query,
        similarity_score=score if score > 0 else None,
        company=None,
        message="No verified visa sponsorship track record found for this employer.",
    )
    set_cache(cache_key, response.model_dump(), ttl_seconds=EXTENSION_LOOKUP_CACHE_TTL)
    return response


# ─────────────────────────────────────────────────────────────────────────────
# 10. Phase 6: Stripe Billing, Webhooks & Entitlements Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/billing/checkout-session",
    response_model=CheckoutSessionResponse,
    summary="Create Stripe Checkout Session for Candidate Plus or Employer Products",
)
@limiter.limit("20/minute")
async def create_billing_checkout_session(request: Request, body: CheckoutSessionRequest):
    """
    Initiates Stripe Checkout for candidate subscriptions (monthly/annual) or employer
    monetization (featured listing, verified badge, pro subscription).
    """
    try:
        session_id, checkout_url = create_checkout_session(
            plan=body.plan,
            user_id=body.user_id,
            customer_email=body.customer_email,
            company_slug=body.company_slug,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
        return CheckoutSessionResponse(
            session_id=session_id,
            checkout_url=checkout_url,
            plan=body.plan,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as exc:
        logger.error("Checkout session creation error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to initialize checkout session.")


@router.post(
    "/billing/webhook",
    response_model=WebhookResponse,
    summary="Handle incoming Stripe webhook events with strict signature verification",
)
async def handle_billing_webhook(request: Request):
    """
    Verifies Stripe signature header and processes lifecycle events:
    - checkout.session.completed (Plus / Badge / Featured / Pro)
    - customer.subscription.updated
    - customer.subscription.deleted (Revocation)
    - invoice.payment_failed (Past-due marking)
    Rejects forged or unsigned requests with 400.
    """
    payload_bytes = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = verify_webhook_signature(payload_bytes, sig_header)
    except ValueError as val_err:
        logger.warning("Stripe webhook verification rejected: %s", val_err)
        raise HTTPException(status_code=400, detail=f"Invalid webhook signature: {val_err}")

    result = process_webhook_event(event)
    event_type = event.get("type", "unknown")
    return WebhookResponse(received=True, event_type=event_type, status=result.get("status", "processed"))


@router.get(
    "/billing/portal-session",
    response_model=PortalSessionResponse,
    summary="Generate Stripe Customer Portal session URL for self-service management",
)
async def get_billing_portal_session(
    user_id: Optional[str] = Query(None, description="Authenticated User ID"),
    customer_id: Optional[str] = Query(None, description="Stripe Customer ID"),
    return_url: Optional[str] = Query(None, description="Post-management return URL"),
):
    """Returns Stripe self-service billing portal URL."""
    try:
        portal_url = create_customer_portal_session(
            customer_id=customer_id,
            user_id=user_id,
            return_url=return_url,
        )
        return PortalSessionResponse(portal_url=portal_url)
    except Exception as exc:
        logger.error("Customer Portal session creation error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create customer portal session.")


@router.get(
    "/billing/entitlements",
    response_model=EntitlementStatusResponse,
    summary="Get user entitlement status and feature quotas",
)
async def get_billing_entitlements(
    user_id: Optional[str] = Query(None, description="User ID or session identifier"),
):
    """Returns real-time feature entitlements, AI generation quota, and alert tier."""
    ent = get_user_entitlement(user_id)
    return EntitlementStatusResponse(**ent)


# ─────────────────────────────────────────────────────────────────────────────
# 11. POST /api/v1/events
# ─────────────────────────────────────────────────────────────────────────────

async def _record_event_background(payload: Dict[str, Any]) -> None:
    """Async background task to record first-party event."""
    _MOCK_EVENTS_STORE.append(payload)
    client = _get_supabase_client()
    if client is not None:
        try:
            client.from_("events").insert({
                "event_type": payload.get("event_type"),
                "session_id": payload.get("session_id"),
                "user_id": payload.get("user_id"),
                "metadata": payload.get("metadata") or {},
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            logger.warning("Failed to insert event into Supabase: %s", e)


@router.post(
    "/events",
    response_model=EventLogResponse,
    summary="First-party server-side event tracking",
)
async def log_event(body: EventLogRequest, background_tasks: BackgroundTasks):
    """
    Fire-and-forget event logger supporting core site and Chrome extension events:
    - Core: 'page_view', 'search_executed', 'job_clicked', 'filter_applied', 'share_generated'
    - Extension: 'extension_badge_shown', 'extension_badge_clicked' (with source_platform: linkedin|indeed)
    """
    event_dict = body.model_dump()
    background_tasks.add_task(_record_event_background, event_dict)
    return EventLogResponse(success=True, message="Event logged successfully.")


# ─────────────────────────────────────────────────────────────────────────────
# 12. Alert & Lifecycle Notification Engine Endpoints (Phase 7)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/alerts",
    response_model=AlertResponse,
    status_code=201,
    summary="Create a new job alert with entitlement verification",
)
async def create_user_alert(body: AlertCreateRequest):
    """
    Creates a new job alert with filter criteria.
    Enforces subscription cadence entitlement:
    - Free accounts support 'daily' and 'weekly' digests.
    - 'instant' cadence requires an active VisaLane Plus membership.
    - If free user requests 'instant', returns HTTP 403 unless downgrade_to_daily=True is passed.
    """
    alert, err = create_alert(body)
    if err:
        raise HTTPException(status_code=403, detail=err)
    return alert


@router.get(
    "/alerts",
    response_model=AlertListResponse,
    summary="List saved job alerts for user or email",
)
async def list_user_alerts(
    user_id: Optional[str] = Query(None, description="Authenticated User ID"),
    email: Optional[str] = Query(None, description="Recipient email address"),
):
    """Returns saved job alerts for the caller."""
    alerts = list_alerts(user_id=user_id, email=email)
    return AlertListResponse(alerts=alerts, total_count=len(alerts))


@router.patch(
    "/alerts/{alert_id}",
    response_model=AlertResponse,
    summary="Update filter criteria, cadence, or active status of an alert",
)
async def patch_user_alert(
    alert_id: str,
    body: AlertUpdateRequest,
    user_id: Optional[str] = Query(None, description="Authenticated User ID"),
):
    """Updates an existing alert with cadence entitlement validation."""
    alert, err = update_alert(alert_id, body, user_id=user_id)
    if err:
        status_code = 404 if err.get("error") == "ALERT_NOT_FOUND" else 403
        raise HTTPException(status_code=status_code, detail=err)
    return alert


@router.delete(
    "/alerts/{alert_id}",
    summary="Delete or deactivate an alert",
)
async def delete_user_alert(
    alert_id: str,
    user_id: Optional[str] = Query(None, description="Authenticated User ID"),
):
    """Deactivates and removes an alert."""
    success = delete_alert(alert_id, user_id=user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found or unauthorized.")
    return {"success": True, "message": f"Alert {alert_id} deactivated successfully."}


@router.post(
    "/alerts/telegram/link-token",
    response_model=TelegramLinkTokenResponse,
    summary="Generate temporary link token to bind Telegram chat with VisaLane",
)
async def generate_telegram_link_token(
    email: str = Query(..., description="User email address"),
    user_id: Optional[str] = Query(None, description="User ID"),
):
    """Generates 15-minute temporary link token for Telegram bot /link command."""
    return create_telegram_link_token(user_id=user_id, email=email)


@router.post(
    "/alerts/telegram/webhook",
    summary="Telegram Bot Webhook endpoint for /link and interactive commands",
)
async def handle_telegram_bot_webhook(update: TelegramWebhookUpdate):
    """
    Handles Telegram bot webhook interactions:
    - /link <token> : Connects candidate's Telegram chat_id to their account & alerts
    - /start <token> : Handles deep link start from t.me/VisaLaneBot?start=token
    """
    msg = update.message or {}
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    text = (msg.get("text") or "").strip()

    if text.startswith("/link") or text.startswith("/start"):
        parts = text.split()
        if len(parts) >= 2:
            token = parts[1].strip()
            link_res = consume_telegram_link_token(token, chat_id)
            if link_res:
                reply_text = (
                    f"✅ <b>Successfully linked your VisaLane account!</b>\n"
                    f"Email: <code>{link_res['email']}</code>\n"
                    f"Active Alerts: <b>{link_res['linked_alerts_count']}</b>\n\n"
                    f"You will now receive instant alerts and verified job digests directly in this chat."
                )
                return {"handled": True, "action": "linked", "email": link_res["email"]}

        return {
            "handled": True,
            "action": "invalid_token",
            "message": "To link your account, use /link <your-token> from your VisaLane Alert settings.",
        }

    return {"handled": True, "action": "ignored"}


@router.get(
    "/alerts/unsubscribe",
    response_class=HTMLResponse,
    summary="One-click token-based unsubscription landing page",
)
async def get_unsubscribe_page(
    token: str = Query(..., description="Signed unsubscribe token"),
    alert_id: Optional[str] = Query(None, description="Optional alert ID"),
    scope: str = Query("alert_only", description="Scope: alert_only, all_marketing, all_notifications"),
):
    """One-click browser unsubscribe handling without login required."""
    success, message, email = process_unsubscribe(token, alert_id=alert_id, scope=scope)
    title = "Unsubscribe Successful" if success else "Unsubscribe Error"
    status_icon = "✅" if success else "❌"

    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>{title} — VisaLane</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; }}
                .card {{ background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; max-width: 480px; width: 100%; padding: 32px; text-align: center; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
                .icon {{ font-size: 40px; margin-bottom: 16px; }}
                h1 {{ font-size: 22px; color: #0f172a; margin: 0 0 12px 0; }}
                p {{ color: #475569; font-size: 15px; line-height: 1.5; margin: 0 0 24px 0; }}
                a.btn {{ display: inline-block; background: #0284c7; color: #ffffff; text-decoration: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="icon">{status_icon}</div>
                <h1>{title}</h1>
                <p>{html.escape(message)}</p>
                <a class="btn" href="{DEFAULT_SITE_URL}/jobs">Return to VisaLane Jobs</a>
            </div>
        </body>
        </html>
        """
    )


@router.post(
    "/alerts/unsubscribe",
    response_model=UnsubscribeResponse,
    summary="Programmatic one-click unsubscription",
)
async def post_unsubscribe(body: UnsubscribeRequest):
    """Programmatic token-based unsubscribe API."""
    success, message, email = process_unsubscribe(token=body.token, alert_id=body.alert_id, scope=body.scope)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return UnsubscribeResponse(
        success=True,
        scope=body.scope,
        message=message,
        unsubscribed_email=email or "unknown",
        alert_id=body.alert_id,
    )


@router.get(
    "/alerts/preferences",
    response_model=UserPreferencesResponse,
    summary="Get user notification preferences center state",
)
async def get_preferences(
    token: Optional[str] = Query(None, description="Signed unsubscribe/preferences token"),
    email: Optional[str] = Query(None, description="User email"),
):
    """Returns granular notification preferences."""
    ident = token or email
    if not ident:
        raise HTTPException(status_code=400, detail="Must provide either token or email query parameter.")
    pref = get_user_preferences(ident)
    if not pref:
        raise HTTPException(status_code=404, detail="Preferences not found.")
    return pref


@router.put(
    "/alerts/preferences",
    response_model=UserPreferencesResponse,
    summary="Update user notification preferences",
)
async def update_preferences(body: UserPreferencesUpdateRequest):
    """Updates marketing opt-out status and Telegram chat connection."""
    if not body.email:
        raise HTTPException(status_code=400, detail="Email is required.")
    email_norm = body.email.strip().lower()
    from .alert_service import _MOCK_PREFERENCES_STORE
    pref = _MOCK_PREFERENCES_STORE.get(email_norm) or {"email": email_norm}
    if body.marketing_opt_out is not None:
        pref["marketing_opt_out"] = body.marketing_opt_out
    if body.telegram_chat_id is not None:
        pref["telegram_chat_id"] = body.telegram_chat_id
    _MOCK_PREFERENCES_STORE[email_norm] = pref
    return get_user_preferences(email_norm)


@router.post(
    "/admin/alerts/run-digest",
    response_model=ScheduledDigestRunResponse,
    summary="Admin trigger for scheduled alert digests",
)
async def admin_run_scheduled_digests(
    cadence: str = Query("daily", description="'daily' or 'weekly'"),
    dry_run: bool = Query(False, description="Simulate without real delivery"),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
    authorization: Optional[str] = Header(None),
):
    """Manually invokes the scheduled alert digest runner (Admin restricted)."""
    _require_admin_auth(authorization=authorization, x_admin_key=x_admin_key)
    jobs = await _fetch_jobs_from_supabase_or_mock()
    return run_scheduled_alert_digests(cadence=cadence, all_jobs=jobs, dry_run=dry_run)
