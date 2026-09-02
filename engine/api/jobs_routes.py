"""
FastAPI route definitions for VisaLane Phase 1 Open Access & SSR Foundation.
Includes:
- GET /api/v1/jobs
- GET /api/v1/jobs/{slug_or_id}
- GET /api/v1/countries
- GET /api/v1/visa-types
- GET /api/v1/sitemap-data
- POST /api/v1/events
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request
from pydantic import ValidationError

from .cache import get_cache, make_cache_key, set_cache
from .canonical_data import (
    CANONICAL_COUNTRIES,
    CANONICAL_VISA_TYPES,
    find_country,
    find_visa_type,
    match_visa_type_from_string,
)
from .jobs_models import (
    BaseSalary,
    CompanySummary,
    ConfidenceFactor,
    CountryItem,
    CountryVisaPair,
    EventLogRequest,
    EventLogResponse,
    FacetItem,
    JobDetail,
    JobFacets,
    JobSearchResponse,
    JobSitemapItem,
    JobSummary,
    SalaryValue,
    SitemapDataResponse,
    StructuredJobLocation,
    VisaTypeItem,
    generate_job_slug,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Jobs API"])

# Cache TTLs in seconds
JOBS_CACHE_TTL = 300       # 5 minutes
METADATA_CACHE_TTL = 600   # 10 minutes
SITEMAP_CACHE_TTL = 900    # 15 minutes

# In-memory test store for offline / mock testing when Supabase is not connected
_MOCK_JOBS_STORE: List[Dict[str, Any]] = []
_MOCK_EVENTS_STORE: List[Dict[str, Any]] = []


def set_mock_jobs_store(jobs: List[Dict[str, Any]]) -> None:
    """Helper for automated tests to populate in-memory jobs."""
    global _MOCK_JOBS_STORE
    _MOCK_JOBS_STORE = jobs


def get_mock_events_store() -> List[Dict[str, Any]]:
    """Helper for automated tests to inspect logged events."""
    return _MOCK_EVENTS_STORE


def clear_mock_stores() -> None:
    """Helper to reset mock stores."""
    global _MOCK_JOBS_STORE, _MOCK_EVENTS_STORE
    _MOCK_JOBS_STORE = []
    _MOCK_EVENTS_STORE = []


def _get_supabase_client():
    """Retrieve Supabase service client if configured."""
    try:
        from job_radar.visalane.db import get_service_client
        return get_service_client()
    except Exception:
        return None


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
    
    # Extract company info
    comp_raw = row.get("companies") or {}
    if isinstance(comp_raw, list) and len(comp_raw) > 0:
        comp_raw = comp_raw[0]
    elif not isinstance(comp_raw, dict):
        comp_raw = {}
    
    company_name = comp_raw.get("name") or row.get("company_name") or row.get("company") or "Company"
    logo_url = comp_raw.get("logo_url") or row.get("company_logo_url")
    website = comp_raw.get("website")

    slug = row.get("slug") or generate_job_slug(title, company_name, job_id)

    visa_types_raw = row.get("visa_types")
    if isinstance(visa_types_raw, str):
        visa_types = [v.strip() for v in visa_types_raw.split(",") if v.strip()]
    elif isinstance(visa_types_raw, list):
        visa_types = [str(v) for v in visa_types_raw if v]
    else:
        visa_types = []

    posted_at = row.get("posted_at") or row.get("date_posted") or row.get("created_at")

    return JobSummary(
        id=job_id,
        slug=slug,
        title=title,
        company=CompanySummary(name=company_name, logo_url=logo_url, website=website),
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
        apply_url=str(row.get("apply_url") or row.get("source_url") or "#"),
        created_at=str(row.get("created_at")) if row.get("created_at") else None,
    )


def _format_job_detail(row: Dict[str, Any]) -> JobDetail:
    """Convert raw DB row into complete JobDetail (schema.org JobPosting compliant)."""
    job_id = str(row.get("id", ""))
    title = str(row.get("title", ""))

    comp_raw = row.get("companies") or {}
    if isinstance(comp_raw, list) and len(comp_raw) > 0:
        comp_raw = comp_raw[0]
    elif not isinstance(comp_raw, dict):
        comp_raw = {}
    
    company_name = comp_raw.get("name") or row.get("company_name") or row.get("company") or "Company"
    logo_url = comp_raw.get("logo_url") or row.get("company_logo_url")
    website = comp_raw.get("website")
    slug = row.get("slug") or generate_job_slug(title, company_name, job_id)

    # Description (full text, never a teaser)
    description = row.get("description_text") or row.get("description") or title
    description_html = row.get("description_html")

    # Dates
    date_posted = row.get("posted_at") or row.get("date_posted") or row.get("created_at")
    valid_through = row.get("expires_at")

    # Employment Type
    raw_type = str(row.get("contract_type") or row.get("work_type") or "FULL_TIME").upper()
    if "CONTRACT" in raw_type:
        employment_type = "CONTRACTOR"
    elif "PART" in raw_type:
        employment_type = "PART_TIME"
    elif "INTERN" in raw_type:
        employment_type = "INTERN"
    else:
        employment_type = "FULL_TIME"

    # Location / Remote
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

    # Base Salary: STRICT RULE — omit entirely if unknown, never fabricate
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

    # Visa sponsorship & confidence factors
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

    # Confidence factors breakdown
    factors: List[ConfidenceFactor] = []
    if verified:
        factors.append(
            ConfidenceFactor(
                label="Direct Sponsorship Verified",
                detail="Sponsorship explicitly verified in job announcement or official immigration sponsor register.",
            )
        )
    elif conf_score >= 80:
        factors.append(
            ConfidenceFactor(
                label="High Confidence Profile",
                detail="Employer has high historical sponsorship activity and matches verified hiring patterns.",
            )
        )
    elif conf_score >= 50:
        factors.append(
            ConfidenceFactor(
                label="Likely Eligible",
                detail="Role and employer meet eligibility criteria for international applicant sponsorship.",
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
                detail=f"Parsed directly from official {ats_type.capitalize()} career portal.",
            )
        )

    return JobDetail(
        id=job_id,
        slug=slug,
        title=title,
        description=description,
        description_html=description_html,
        date_posted=str(date_posted) if date_posted else None,
        valid_through=str(valid_through) if valid_through else None,
        employment_type=employment_type,
        hiring_organization=CompanySummary(name=company_name, logo_url=logo_url, website=website),
        job_location=job_location,
        remote=is_remote,
        applicant_location_requirements=applicant_location_req,
        base_salary=base_salary,
        visa_types_supported=visa_types,
        confidence_score=conf_score,
        confidence_factors=factors,
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
) -> List[Dict[str, Any]]:
    """Filter in-memory job records based on query parameters."""
    filtered = []
    canon_country = find_country(country) if country else None
    canon_visa = find_visa_type(visa_type) if visa_type else None

    for job in jobs:
        # Status active check
        if job.get("status") and job.get("status") != "active":
            continue

        # Country filter
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

        # Visa type filter
        if visa_type:
            j_visas = job.get("visa_types") or []
            if isinstance(j_visas, str):
                j_visas = [j_visas]
            j_visas_str = " ".join(j_visas).lower()
            if canon_visa:
                # Match against canonical aliases or name
                matched = any(alias in j_visas_str for alias in canon_visa["aliases"])
                if not matched and canon_visa["slug"] not in j_visas_str:
                    continue
            else:
                if visa_type.lower() not in j_visas_str:
                    continue

        # Role / keyword filter (title or description)
        if role:
            r_clean = role.strip().lower()
            j_title = str(job.get("title", "")).lower()
            j_desc = str(job.get("description_text", "") or job.get("description", "")).lower()
            if r_clean not in j_title and r_clean not in j_desc:
                continue

        # Work mode filter
        if work_mode:
            j_mode = str(job.get("work_mode", "")).lower()
            if work_mode.lower() not in j_mode:
                continue

        # Contract type filter
        if contract_type:
            j_ctype = str(job.get("contract_type", "") or job.get("work_type", "")).lower()
            if contract_type.lower() not in j_ctype:
                continue

        # Min confidence filter
        if min_confidence is not None:
            j_conf = int(job.get("visa_sponsorship_confidence") or 0)
            if j_conf < min_confidence:
                continue

        # Recency cutoff filter
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

    # Sorting
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
        # Default: newest
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

        # Visa types
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
    """Retrieve all active jobs from Supabase or fallback mock store."""
    client = _get_supabase_client()
    if client is not None and not _MOCK_JOBS_STORE:
        try:
            # Query active jobs from Supabase with company relation
            res = client.from_("jobs").select(
                "*,companies(name,logo_url,website,ats_type)"
            ).eq("status", "active").order("posted_at", desc=True).limit(1000).execute()
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
    """
    Open-access job search endpoint. Does NOT require authentication.
    Returns paginated job summaries and faceted counts scoped to active filters.
    """
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
    """
    Fetch full job posting details by UUID or SEO URL slug.
    Strictly omits salary field if unknown. Open-access, no authentication required.
    """
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
    # 1. Try exact UUID match
    for j in all_jobs:
        if str(j.get("id")) == target:
            matched = j
            break

    # 2. Try slug match
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
        # Check direct Supabase query if not found in cache/mock
        client = _get_supabase_client()
        if client is not None:
            try:
                query = client.from_("jobs").select("*,companies(name,logo_url,website,ats_type)")
                # If target is a valid UUID, filter by id
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
# 3. Reference Endpoints: GET /api/v1/countries & GET /api/v1/visa-types
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/countries",
    response_model=List[CountryItem],
    summary="Canonical countries with live active job counts",
)
async def list_countries():
    """
    Returns canonical countries with active job counts.
    Used by frontend SSR to determine which country landing pages to generate.
    """
    cache_key = "reference:countries"
    cached = get_cache(cache_key, ttl_seconds=METADATA_CACHE_TTL)
    if cached is not None:
        try:
            return [CountryItem(**c) for c in cached]
        except Exception:
            pass

    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    active_jobs = [j for j in all_jobs if not j.get("status") or j.get("status") == "active"]

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
        results.append(
            CountryItem(
                slug=c["slug"],
                code=c["code"],
                name=c["name"],
                count=count,
            )
        )

    results.sort(key=lambda x: x.count, reverse=True)
    set_cache(cache_key, [r.model_dump() for r in results], ttl_seconds=METADATA_CACHE_TTL)
    return results


@router.get(
    "/visa-types",
    response_model=List[VisaTypeItem],
    summary="Canonical visa types with live active job counts",
)
async def list_visa_types():
    """
    Returns canonical visa types with active job counts.
    Used by frontend SSR to determine which visa landing pages to generate.
    """
    cache_key = "reference:visa_types"
    cached = get_cache(cache_key, ttl_seconds=METADATA_CACHE_TTL)
    if cached is not None:
        try:
            return [VisaTypeItem(**v) for v in cached]
        except Exception:
            pass

    all_jobs = await _fetch_jobs_from_supabase_or_mock()
    active_jobs = [j for j in all_jobs if not j.get("status") or j.get("status") == "active"]

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
        results.append(
            VisaTypeItem(
                slug=v["slug"],
                name=v["name"],
                country_code=v["country_code"],
                country_slug=v["country_slug"],
                count=count,
            )
        )

    results.sort(key=lambda x: x.count, reverse=True)
    set_cache(cache_key, [r.model_dump() for r in results], ttl_seconds=METADATA_CACHE_TTL)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 4. GET /api/v1/sitemap-data
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
    active_jobs = [j for j in all_jobs if not j.get("status") or j.get("status") == "active"]

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


# ─────────────────────────────────────────────────────────────────────────────
# 5. POST /api/v1/events
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
    Fire-and-forget event logger for page views, searches, job clicks, and alert creations.
    Returns 200 immediately without blocking user requests.
    """
    event_dict = body.model_dump()
    background_tasks.add_task(_record_event_background, event_dict)
    return EventLogResponse(success=True, message="Event logged successfully.")
