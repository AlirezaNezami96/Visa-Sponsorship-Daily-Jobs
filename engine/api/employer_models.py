"""
Pydantic data models for VisaLane Phase 8 (Backend):
B2B Self-Serve Employer Job Posting, Quotas, and Analytics.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EmployerJobCreateRequest(BaseModel):
    """Payload for employer direct job posting."""
    title: str = Field(..., description="Job title (minimum 3 characters)")
    description: str = Field(..., description="Full job description (minimum 30 characters)")
    description_html: Optional[str] = Field(None, description="Optional HTML formatted description")
    company_name: str = Field(..., description="Hiring organization name")
    company_website: Optional[str] = Field(None, description="Company website URL")
    company_logo_url: Optional[str] = Field(None, description="Company logo URL")
    location: Optional[str] = Field(None, description="Raw location string (e.g., 'Berlin, Germany')")
    city: Optional[str] = Field(None, description="City name")
    country: Optional[str] = Field(None, description="Country name")
    country_code: Optional[str] = Field(None, description="2-letter ISO country code")
    is_remote: bool = Field(False, description="Flag indicating if the job is fully remote")
    date_posted: Optional[str] = Field(None, description="ISO 8601 posting date (defaulted to UTC now)")
    employment_type: Optional[str] = Field("FULL_TIME", description="Employment type (FULL_TIME, CONTRACTOR, etc.)")
    apply_url: str = Field(..., description="Direct candidate application URL")
    visa_types: List[str] = Field(default_factory=list, description="Target visa sponsorship types")
    salary_min: Optional[int] = Field(None, description="Minimum annual salary in integer currency units")
    salary_max: Optional[int] = Field(None, description="Maximum annual salary in integer currency units")
    salary_currency: Optional[str] = Field("USD", description="3-letter currency code (e.g. USD, EUR, GBP)")
    employer_id: Optional[str] = Field(None, description="Employer / User ID posting this listing")
    company_slug: Optional[str] = Field(None, description="Company directory slug")


class EmployerJobUpdateRequest(BaseModel):
    """Payload for updating an existing employer direct listing."""
    title: Optional[str] = None
    description: Optional[str] = None
    description_html: Optional[str] = None
    location: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    is_remote: Optional[bool] = None
    employment_type: Optional[str] = None
    apply_url: Optional[str] = None
    visa_types: Optional[List[str]] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: Optional[str] = None


class EmployerJobResponse(BaseModel):
    """Public and private representation of an employer direct job listing."""
    id: str
    slug: str
    title: str
    description: str
    description_html: Optional[str] = None
    company_name: str
    company_slug: str
    company_website: Optional[str] = None
    company_logo_url: Optional[str] = None
    location: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    is_remote: bool = False
    work_mode: str = "on_site"
    date_posted: str
    employment_type: str = "FULL_TIME"
    apply_url: str
    visa_types: List[str] = Field(default_factory=list)
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: Optional[str] = "USD"
    job_status: str = "Open"  # "Open" | "Closed"
    status: str = "active"    # "active" | "closed"
    is_active: bool = True
    source: str = "employer_direct"
    employer_id: Optional[str] = None
    created_at: str
    updated_at: str


class EmployerJobListResponse(BaseModel):
    """List response for all jobs posted by an employer."""
    jobs: List[EmployerJobResponse]
    total_count: int
    active_count: int
    closed_count: int
    quota_limit: int  # -1 represents unlimited
    plan_name: str


class SchemaValidationErrorDetail(BaseModel):
    """Granular error breakdown for schema-completeness rejection."""
    error: str = "SCHEMA_VALIDATION_FAILED"
    message: str
    missing_fields: List[str]
    validation_errors: Dict[str, str]


class QuotaExceededErrorDetail(BaseModel):
    """Structured error breakdown for plan-based active listing quota exhaustion."""
    error: str = "ACTIVE_LISTING_QUOTA_EXCEEDED"
    message: str
    plan_name: str
    current_limit: int
    current_active_count: int
    upgrade_url: str


class DailyAnalyticsPoint(BaseModel):
    """Per-day breakdown of job listing engagement."""
    date: str
    views: int
    unique_viewers: int
    apply_clicks: int
    click_through_rate: float


class JobAnalyticsResponse(BaseModel):
    """Aggregate engagement analytics for an employer direct job listing."""
    job_id: str
    date_range: Dict[str, str]
    total_views: int
    unique_viewers: int
    apply_clicks: int
    click_through_rate: float
    daily_breakdown: List[DailyAnalyticsPoint]
