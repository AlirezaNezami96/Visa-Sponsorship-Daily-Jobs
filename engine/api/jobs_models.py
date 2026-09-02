"""
Pydantic response and request models for VisaLane Phase 1, Phase 2, Phase 3, and Phase 4 API endpoints.
Includes schema.org JobPosting compliance models, programmatic SEO summaries,
employer aggregation directories, shareable match reports, and localized content/posts engine.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

CENTRAL_LEGAL_DISCLAIMER = (
    "VisaLane aggregates and analyzes publicly available job postings, employer filings, "
    "and immigration registries as of the date indicated. Past sponsorship patterns and "
    "hiring statistics do not guarantee future visa support or individual eligibility. "
    "For official sponsorship verification or correction requests, contact verification@visalane.com."
)


def generate_job_slug(title: str, company_name: str, job_id: str) -> str:
    """Generate a clean, SEO-friendly job URL slug."""
    clean_title = re.sub(r"[^\w\s-]", "", title.lower()).strip()
    clean_title = re.sub(r"[-\s]+", "-", clean_title)
    clean_comp = re.sub(r"[^\w\s-]", "", company_name.lower()).strip()
    clean_comp = re.sub(r"[-\s]+", "-", clean_comp)
    short_id = str(job_id).replace("-", "")[:8]
    parts = [p for p in [clean_title, clean_comp, short_id] if p]
    return "-".join(parts) or f"job-{short_id}"


def generate_company_slug(name: Optional[str]) -> str:
    """Generate a clean URL slug for a company."""
    if not name or not isinstance(name, str):
        return "company"
    clean = re.sub(r"[^\w\s-]", "", name.lower()).strip()
    return re.sub(r"[-\s]+", "-", clean) or "company"


def generate_post_slug(title: str) -> str:
    """Generate a clean URL slug for a blog/content post."""
    clean = re.sub(r"[^\w\s-]", "", title.lower()).strip()
    return re.sub(r"[-\s]+", "-", clean) or "post"


class FacetItem(BaseModel):
    slug: str
    label: str
    count: int


class JobFacets(BaseModel):
    countries: List[FacetItem] = Field(default_factory=list)
    visa_types: List[FacetItem] = Field(default_factory=list)


class CompanySummary(BaseModel):
    name: str
    logo_url: Optional[str] = None
    website: Optional[str] = None
    ats_type: Optional[str] = None
    slug: Optional[str] = None


class JobSummary(BaseModel):
    id: str
    slug: str
    title: str
    company: CompanySummary
    location: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    work_mode: Optional[str] = None
    contract_type: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: Optional[str] = None
    salary_raw: Optional[str] = None
    visa_sponsorship_verified: bool = False
    visa_sponsorship_confidence: Optional[int] = None
    visa_types: List[str] = Field(default_factory=list)
    posted_at: Optional[str] = None
    apply_url: str
    job_status: str = "Open"  # "Open" | "Closed"
    created_at: Optional[str] = None


class JobSearchResponse(BaseModel):
    results: List[JobSummary]
    total_count: int
    page: int
    page_size: int
    facets: JobFacets


class ConfidenceFactor(BaseModel):
    label: str
    detail: str


class SalaryValue(BaseModel):
    min: Optional[int] = None
    max: Optional[int] = None
    unit_text: str = "YEAR"


class BaseSalary(BaseModel):
    currency: str
    value: SalaryValue


class StructuredJobLocation(BaseModel):
    country: Optional[str] = None
    country_code: Optional[str] = None
    city: Optional[str] = None
    street_address: Optional[str] = None
    postal_code: Optional[str] = None


class JobDetail(BaseModel):
    id: str
    slug: str
    title: str
    description: str
    description_html: Optional[str] = None
    date_posted: Optional[str] = None
    valid_through: Optional[str] = None
    employment_type: Optional[str] = None
    hiring_organization: CompanySummary
    job_location: Optional[StructuredJobLocation] = None
    remote: bool = False
    applicant_location_requirements: Optional[str] = None
    # Strictly omitted or null when salary is unknown — never fabricated
    base_salary: Optional[BaseSalary] = None
    visa_types_supported: List[str] = Field(default_factory=list)
    confidence_score: int = 0
    confidence_factors: List[ConfidenceFactor] = Field(default_factory=list)
    job_status: str = "Open"  # "Open" | "Closed"
    event_status: str = "https://schema.org/EventScheduled"  # For schema.org
    apply_url: str
    source_url: Optional[str] = None
    created_at: Optional[str] = None


def to_job_posting_json_ld(detail: JobDetail, base_url: str = "https://visalane.com") -> Dict[str, Any]:
    """
    Generate valid schema.org/JobPosting JSON-LD object.
    Guarantees the 5 required Google JobPosting fields:
    - title
    - description
    - datePosted
    - hiringOrganization
    - jobLocation (or jobLocationType: TELECOMMUTE + applicantLocationRequirements)
    """
    job_url = f"{base_url.rstrip('/')}/jobs/{detail.slug}"
    
    json_ld: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": detail.title,
        "description": detail.description_html or detail.description,
        "identifier": {
            "@type": "PropertyValue",
            "name": detail.hiring_organization.name,
            "value": detail.id,
        },
        "datePosted": detail.date_posted or detail.created_at,
        "hiringOrganization": {
            "@type": "Organization",
            "name": detail.hiring_organization.name,
            "sameAs": detail.hiring_organization.website,
            "logo": detail.hiring_organization.logo_url,
        },
        "url": job_url,
        "directApply": True,
    }

    # Job status / Expiration
    if detail.job_status == "Closed":
        json_ld["validThrough"] = detail.valid_through or detail.date_posted
    elif detail.valid_through:
        json_ld["validThrough"] = detail.valid_through

    # Employment Type
    if detail.employment_type:
        json_ld["employmentType"] = detail.employment_type

    # Remote vs Physical Location
    if detail.remote:
        json_ld["jobLocationType"] = "TELECOMMUTE"
        json_ld["applicantLocationRequirements"] = {
            "@type": "Country",
            "name": detail.applicant_location_requirements or "Worldwide",
        }
        if detail.job_location and detail.job_location.country:
            json_ld["jobLocation"] = {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": detail.job_location.city,
                    "addressCountry": detail.job_location.country_code or detail.job_location.country,
                }
            }
    elif detail.job_location:
        json_ld["jobLocation"] = {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": detail.job_location.city,
                "addressCountry": detail.job_location.country_code or detail.job_location.country,
                "streetAddress": detail.job_location.street_address,
                "postalCode": detail.job_location.postal_code,
            }
        }

    # Base Salary: Strictly omit if unknown — never fabricate
    if detail.base_salary and detail.base_salary.value:
        salary_obj: Dict[str, Any] = {
            "@type": "MonetaryAmount",
            "currency": detail.base_salary.currency,
            "value": {
                "@type": "QuantitativeValue",
                "unitText": detail.base_salary.value.unit_text,
            }
        }
        if detail.base_salary.value.min is not None:
            salary_obj["value"]["minValue"] = detail.base_salary.value.min
        if detail.base_salary.value.max is not None:
            salary_obj["value"]["maxValue"] = detail.base_salary.value.max
        if detail.base_salary.value.min == detail.base_salary.value.max:
            salary_obj["value"]["value"] = detail.base_salary.value.min
        json_ld["baseSalary"] = salary_obj

    return json_ld


# ─────────────────────────────────────────────────────────────────────────────
# Reference & Summary Models (Phase 2 & Phase 3)
# ─────────────────────────────────────────────────────────────────────────────

class CountryItem(BaseModel):
    slug: str
    code: str
    name: str
    label: Optional[str] = None
    count: int
    is_fallback: bool = False


class VisaTypeItem(BaseModel):
    slug: str
    name: str
    label: Optional[str] = None
    country_code: str
    country_slug: str
    count: int
    is_fallback: bool = False


class CountryVisaPair(BaseModel):
    country: str
    visa_type: str
    count: int


class JobSitemapItem(BaseModel):
    id: str
    slug: str
    updated_at: Optional[str] = None


class SitemapDataResponse(BaseModel):
    countries: List[str]
    visa_types: List[str]
    country_visa_pairs: List[CountryVisaPair]
    job_slugs: List[JobSitemapItem]


class TopRoleItem(BaseModel):
    title: str
    count: int


class EmployerSummaryItem(BaseModel):
    name: str
    logo_url: Optional[str] = None
    job_count: int


class VisaAvailabilityItem(BaseModel):
    slug: str
    name: str
    count: int


class CountrySummaryResponse(BaseModel):
    country: Dict[str, str]  # { "slug": "germany", "code": "DE", "name": "Germany" }
    job_count: int
    top_roles: List[TopRoleItem] = Field(default_factory=list)
    sample_employers: List[EmployerSummaryItem] = Field(default_factory=list)
    visa_types_available: List[VisaAvailabilityItem] = Field(default_factory=list)
    last_updated: Optional[str] = None
    meta_description_suggestion: str


class CountryVisaSummaryResponse(BaseModel):
    country: Dict[str, str]
    visa_type: Dict[str, str]
    job_count: int
    top_roles: List[TopRoleItem] = Field(default_factory=list)
    sample_employers: List[EmployerSummaryItem] = Field(default_factory=list)
    last_updated: Optional[str] = None
    meta_description_suggestion: str


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3: Employer Aggregation & Match Report Models
# ─────────────────────────────────────────────────────────────────────────────

class CompanyCountryCount(BaseModel):
    slug: str
    code: str
    name: str
    count: int


class CompanyDirectoryItem(BaseModel):
    name: str
    slug: str
    logo_url: Optional[str] = None
    website: Optional[str] = None
    ats_type: Optional[str] = None
    active_job_count: int = 0
    total_job_count: int = 0
    confidence_score: int = 0
    verified_sponsorship_rate: float = 0.0
    countries: List[str] = Field(default_factory=list)


class CompanyDirectoryResponse(BaseModel):
    results: List[CompanyDirectoryItem]
    total_count: int
    page: int
    page_size: int


class CompanyDetailSummary(BaseModel):
    company: CompanySummary
    total_active_jobs: int
    total_historical_jobs: int
    sponsorship_confidence_score: int
    verified_sponsorship_rate: float
    supported_visa_types: List[str] = Field(default_factory=list)
    hiring_countries: List[CompanyCountryCount] = Field(default_factory=list)
    top_roles: List[TopRoleItem] = Field(default_factory=list)
    recent_jobs: List[JobSummary] = Field(default_factory=list)
    last_verified: Optional[str] = None
    disclaimer: str = CENTRAL_LEGAL_DISCLAIMER


class MatchReportCreateRequest(BaseModel):
    country: Optional[str] = None
    visa_type: Optional[str] = None
    role: Optional[str] = None
    work_mode: Optional[str] = None
    contract_type: Optional[str] = None
    min_confidence: Optional[int] = None
    posted_since: Optional[str] = None
    title: Optional[str] = None
    session_id: Optional[str] = None


class MatchReportCreateResponse(BaseModel):
    slug: str
    share_url: str
    original_match_count: int


class MatchReportDetailResponse(BaseModel):
    slug: str
    title: Optional[str] = None
    filters: Dict[str, Any]
    original_match_count: int
    current_match_count: int
    human_summary: str
    og_title: str
    og_description: str
    share_url: str
    created_at: str
    results_sample: List[JobSummary] = Field(default_factory=list)


class EventLogRequest(BaseModel):
    event_type: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventLogResponse(BaseModel):
    success: bool = True
    message: str = "Event logged successfully."


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4: Content/Blog Engine & i18n Models
# ─────────────────────────────────────────────────────────────────────────────

class LocaleItem(BaseModel):
    code: str
    label: str
    native_label: str
    is_rtl: bool
    default: bool


class PostTranslationItem(BaseModel):
    locale: str
    title: str
    body_markdown: str
    meta_description: Optional[str] = None


class PostSummary(BaseModel):
    id: str
    slug: str
    category: str
    author: str
    published_at: str
    locale: str
    is_fallback: bool = False
    title: str
    meta_description: Optional[str] = None
    featured_image_url: Optional[str] = None


class PostDetail(BaseModel):
    id: str
    slug: str
    category: str
    author: str
    published_at: str
    updated_at: str
    canonical_locale: str
    locale: str
    is_fallback: bool = False
    title: str
    body_markdown: str
    meta_description: Optional[str] = None
    featured_image_url: Optional[str] = None
    available_locales: List[str] = Field(default_factory=list)


class PostListResponse(BaseModel):
    results: List[PostSummary]
    total_count: int
    page: int
    page_size: int
    locale: str


class AdminPostCreateRequest(BaseModel):
    slug: Optional[str] = None
    category: str = Field(..., description="'policy-radar', 'guide', or 'data-report'")
    author: Optional[str] = "VisaLane Policy Team"
    canonical_locale: str = "en"
    status: str = "published"
    featured_image_url: Optional[str] = None
    translations: List[PostTranslationItem] = Field(..., min_length=1)


class AdminPostUpdateRequest(BaseModel):
    category: Optional[str] = None
    author: Optional[str] = None
    canonical_locale: Optional[str] = None
    status: Optional[str] = None
    featured_image_url: Optional[str] = None
    translations: Optional[List[PostTranslationItem]] = None


# ─────────────────────────────────────────────────────────────────────────────
# Phase 5: Chrome Extension Lookup Models
# ─────────────────────────────────────────────────────────────────────────────

class ExtensionCompanySummary(BaseModel):
    name: str
    slug: str
    logo_url: Optional[str] = None
    website: Optional[str] = None
    ats_type: Optional[str] = None
    active_job_count: int
    total_job_count: int
    sponsorship_confidence_score: int
    verified_sponsorship_rate: float
    supported_visa_types: List[str] = Field(default_factory=list)
    hiring_countries: List[str] = Field(default_factory=list)
    top_roles: List[str] = Field(default_factory=list)
    profile_url: str
    last_verified: Optional[str] = None
    disclaimer: str = CENTRAL_LEGAL_DISCLAIMER


class ExtensionLookupResponse(BaseModel):
    match: bool
    query: str
    normalized_query: str
    similarity_score: Optional[float] = None
    company: Optional[ExtensionCompanySummary] = None
    message: Optional[str] = None
