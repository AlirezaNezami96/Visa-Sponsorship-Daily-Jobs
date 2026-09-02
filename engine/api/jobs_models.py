"""
Pydantic response and request models for VisaLane Phase 1 API endpoints.
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
    apply_url: str
    source_url: Optional[str] = None
    created_at: Optional[str] = None


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


class EventLogRequest(BaseModel):
    event_type: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventLogResponse(BaseModel):
    success: bool = True
    message: str = "Event logged successfully."
