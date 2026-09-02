"""
Pydantic response and request models for VisaLane Phase 1 & Phase 2 API endpoints.
Includes schema.org JobPosting compliance models and programmatic SEO summaries.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


def generate_job_slug(title: str, company_name: str, job_id: str) -> str:
    """Generate a clean, SEO-friendly job URL slug."""
    clean_title = re.sub(r"[^\w\s-]", "", title.lower()).strip()
    clean_title = re.sub(r"[-\s]+", "-", clean_title)
    clean_comp = re.sub(r"[^\w\s-]", "", company_name.lower()).strip()
    clean_comp = re.sub(r"[-\s]+", "-", clean_comp)
    short_id = str(job_id).replace("-", "")[:8]
    parts = [p for p in [clean_title, clean_comp, short_id] if p]
    return "-".join(parts) or f"job-{short_id}"


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
# Reference & Summary Models (Phase 2)
# ─────────────────────────────────────────────────────────────────────────────

class CountryItem(BaseModel):
    slug: str
    code: str
    name: str
    count: int


class VisaTypeItem(BaseModel):
    slug: str
    name: str
    country_code: str
    country_slug: str
    count: int


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
    visa_type: Dict[str, str]  # { "slug": "eu-blue-card", "name": "EU Blue Card", "country_code": "DE" }
    job_count: int
    top_roles: List[TopRoleItem] = Field(default_factory=list)
    sample_employers: List[EmployerSummaryItem] = Field(default_factory=list)
    last_updated: Optional[str] = None
    meta_description_suggestion: str


class EventLogRequest(BaseModel):
    event_type: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventLogResponse(BaseModel):
    success: bool = True
    message: str = "Event logged successfully."
