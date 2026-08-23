"""Canonical domain models for the Visa-Sponsorship-Daily-Jobs radar pipeline.

Implements strict Pydantic validation across all sources, ATS feeds,
filters, enrichment, and LLM classifiers.
"""
from __future__ import annotations

import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class TrackType(str, Enum):
    INTERNSHIP = "internship"
    ENGINEER = "engineer"
    BORDERLINE = "borderline"
    REJECT = "reject"
    OTHER = "other"


class WorkplaceType(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNSPECIFIED = "unspecified"


class RemoteScope(str, Enum):
    WORLDWIDE = "worldwide"
    REGION_RESTRICTED = "region_restricted"
    ONSITE_ONLY = "onsite_only"
    UNKNOWN = "unknown"


class VisaStatus(str, Enum):
    SPONSORS = "sponsors"
    LIKELY = "likely"
    OPT_FRIENDLY = "opt_friendly"
    UNKNOWN = "unknown"
    NO = "no"


class Job(BaseModel):
    """Canonical, fully validated job posting schema."""

    # Identity
    id: str = Field(description="Source-prefixed unique ID, e.g. 'gh-6860572' or 'lever-abc123'")
    source: str = Field(description="greenhouse | lever | ashby | smartrecruiters | personio | workable | remoteok | ...")
    company: str
    title: str
    url: str
    apply_url: Optional[str] = None

    # Location / Workplace
    location_raw: str = ""
    locations: List[str] = Field(default_factory=list)
    is_remote: Optional[bool] = None
    is_hybrid: Optional[bool] = None
    workplace_type: Optional[str] = None  # remote | hybrid | onsite | unspecified
    location_requirements: Optional[List[str]] = None  # Country/region eligibility
    country: Optional[str] = None

    # Content
    description_html: Optional[str] = None
    description_text: Optional[str] = None
    snippet: Optional[str] = None
    department: Optional[str] = None
    team: Optional[str] = None
    job_type: Optional[str] = None  # fulltime | parttime | internship | contract
    job_level: Optional[str] = None
    date_posted: Optional[str] = None  # Employer-claimed posting date
    fetched_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    # Compensation
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    salary_interval: Optional[str] = None  # yearly | monthly | hourly
    salary_raw: Optional[str] = None

    # Pipeline annotations
    track: Optional[str] = None  # internship | engineer | borderline | reject
    relevance_score: Optional[int] = None
    relevance_why: Optional[str] = None
    remote_scope: Optional[str] = None  # worldwide | region_restricted | onsite_only | unknown
    allowed_regions: List[str] = Field(default_factory=list)
    visa_status: Optional[str] = None  # sponsors | likely | opt_friendly | unknown | no
    visa_score: Optional[float] = None
    visa_evidence: List[str] = Field(default_factory=list)
    resume_match_score: Optional[int] = None
    resume_match_why: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Debug payload
    raw_source_payload: Optional[Dict[str, Any]] = None

    @field_validator("id", mode="before")
    @classmethod
    def ensure_id(cls, v: Any, info: Any) -> str:
        if not v:
            # Fallback to generated ID
            return f"job-{datetime.datetime.now(datetime.timezone.utc).timestamp()}"
        return str(v)

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Convert canonical Job model to legacy dictionary format for backwards compatibility."""
        d = self.model_dump()
        # Ensure legacy keys exist
        d["location"] = self.location_raw or (", ".join(self.locations) if self.locations else "Remote")
        d["description"] = self.description_text or self.description_html or self.snippet or ""
        d["why_matched"] = self.relevance_why or ""
        d["visa_sponsorship"] = self.visa_status in (VisaStatus.SPONSORS.value, VisaStatus.LIKELY.value)
        d["classified_track"] = self.track
        d["_fingerprint"] = self.metadata.get("fingerprint")
        if self.salary_min or self.salary_max or self.salary_raw:
            d["salary"] = self.salary_raw or f"{self.salary_currency or '$'}{self.salary_min:,.0f} - {self.salary_max:,.0f}" if (self.salary_min and self.salary_max) else self.salary_raw
        return d

    @classmethod
    def from_legacy_dict(cls, data: Dict[str, Any]) -> Job:
        """Construct canonical Job model from legacy dictionary."""
        source = str(data.get("source", "custom")).lower()
        company = data.get("company", "Unknown")
        title = data.get("title", "Untitled")
        url = data.get("url", "")
        job_id = str(data.get("id") or f"{source}-{hash(url)}")

        return cls(
            id=job_id,
            source=source,
            company=company,
            title=title,
            url=url,
            apply_url=data.get("apply_url"),
            location_raw=data.get("location", ""),
            locations=[data["location"]] if data.get("location") else [],
            is_remote=data.get("is_remote"),
            is_hybrid=data.get("is_hybrid"),
            workplace_type=data.get("workplace_type"),
            country=data.get("country"),
            description_html=data.get("description_html"),
            description_text=data.get("description") or data.get("description_text"),
            snippet=data.get("snippet"),
            department=data.get("department"),
            team=data.get("team"),
            job_type=data.get("job_type"),
            job_level=data.get("job_level"),
            date_posted=str(data.get("date_posted")) if data.get("date_posted") else None,
            fetched_at=data.get("fetched_at") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
            salary_min=data.get("salary_min"),
            salary_max=data.get("salary_max"),
            salary_currency=data.get("salary_currency"),
            salary_interval=data.get("salary_interval"),
            salary_raw=data.get("salary") or data.get("salary_raw"),
            track=data.get("classified_track") or data.get("track"),
            relevance_score=data.get("relevance_score"),
            relevance_why=data.get("why_matched") or data.get("relevance_why"),
            remote_scope=data.get("remote_scope"),
            allowed_regions=data.get("allowed_regions", []),
            visa_status=data.get("visa_status"),
            visa_score=data.get("visa_score"),
            visa_evidence=data.get("visa_evidence", []),
            resume_match_score=data.get("resume_match_score"),
            resume_match_why=data.get("resume_match_why"),
            metadata=data.get("metadata", {}),
            raw_source_payload=data.get("raw_source_payload"),
        )


class CombinedLLMResponse(BaseModel):
    """Structured response schema for the single-pass LLM classifier & resume matcher."""

    relevance: int = Field(ge=0, le=100, description="Relevance score 0-100 for AI/ML focus")
    why: str = Field(description="Concise 1-sentence explanation of relevance/fit")
    is_ai_ml_day_to_day: bool = Field(description="True if primary work involves AI/ML/CV/NLP/LLM/Agents")
    track_guess: str = Field(description="internship | engineer | borderline | other")
    seniority_guess: str = Field(description="intern | junior | mid | senior")
    remote_scope: str = Field(description="worldwide | region_restricted | onsite_only | unknown")
    allowed_regions: List[str] = Field(default_factory=list, description="List of eligible country codes/regions or ['Worldwide']")
    visa_mention: str = Field(description="sponsors | opt_friendly | no | unspecified")
    visa_quote: Optional[str] = Field(default=None, description="Direct quote from JD regarding sponsorship or null")
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    salary_interval: Optional[str] = None
    resume_match_score: Optional[int] = Field(default=None, ge=0, le=100)
    resume_match_why: Optional[str] = None


class RunHealthMetrics(BaseModel):
    """Run health diagnostics and operational counters."""

    sources_total: int = 0
    companies_ok: int = 0
    companies_fail: int = 0
    jobs_raw: int = 0
    jobs_after_freshness: int = 0
    jobs_after_prefilter: int = 0
    jobs_after_dedupe: int = 0
    jobs_after_llm: int = 0
    visa_status_counts: Dict[str, int] = Field(default_factory=dict)
    llm_failures: int = 0
    circuit_breaker_trips: Dict[str, int] = Field(default_factory=dict)
    duration_seconds: float = 0.0
