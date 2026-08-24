"""Canonical Job domain model for the Visa-Sponsorship-Daily-Jobs radar & Apify platform."""
from __future__ import annotations

import datetime
import hashlib
import re
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator

from job_radar.models.enums import (
    AuthFit,
    RemoteScope,
    Seniority,
    TrackType,
    VisaConfidence,
    VisaStatus,
    WorkplaceType,
)

VISA_CONFIDENCE_FLOAT_MAP: Dict[str, float] = {
    "stated_in_jd": 1.0,
    "on_sponsor_list": 0.85,
    "employer_sponsored_region": 0.70,
    "historical_filings": 0.65,
    "unknown": 0.25,
    "explicit_no": 0.0,
}


def _to_camel_case(snake_str: str) -> str:
    """Convert snake_case string to camelCase."""
    components = snake_str.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


def _normalize_name(name: str) -> str:
    """Lowercase and strip common corporate suffixes."""
    if not name:
        return ""
    n = name.lower().strip()
    suffixes = [
        r"\binc\.?\b", r"\bltd\.?\b", r"\bllc\.?\b", r"\bgmbh\b",
        r"\bplc\b", r"\bcorp\.?\b", r"\bco\.?\b", r"\blimited\b",
        r"\bnv\b", r"\bbv\b", r"\boy\b", r"\bab\b", r"\bs\.a\.\b",
        r"\bag\b", r"\bpty\b", r"\bkk\b",
    ]
    for s in suffixes:
        n = re.sub(s, "", n, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", n).strip(",. ")


class Job(BaseModel):
    """Canonical, fully validated job posting schema."""

    # Identity
    id: str = Field(description="Unique fingerprint or source-prefixed ID")
    source: str = Field(default="custom", description="greenhouse | lever | ashby | workable | smartrecruiters | personio | remoteok | ...")
    source_id: Optional[str] = None
    ats: Optional[str] = None

    # Core job data
    title: str = Field(default="Untitled")
    company: str = Field(default="Unknown")
    company_normalized: str = Field(default="")
    company_domain: Optional[str] = None
    description: str = Field(default="")
    description_html: Optional[str] = None
    description_text: Optional[str] = None
    snippet: Optional[str] = None
    department: Optional[str] = None
    team: Optional[str] = None

    # Location / Workplace
    location: str = Field(default="")
    location_raw: str = Field(default="")
    locations: List[str] = Field(default_factory=list)
    remote: bool = False
    is_remote: Optional[bool] = None
    is_hybrid: Optional[bool] = None
    workplace_type: Optional[str] = None  # remote | hybrid | onsite | unspecified
    remote_type: RemoteScope = Field(default=RemoteScope.UNKNOWN)
    allowed_regions: List[str] = Field(default_factory=list)
    location_requirements: Optional[List[str]] = None
    country: Optional[str] = None

    # Employment & Compensation
    employment_type: Optional[str] = None  # full_time | part_time | contract | internship
    job_type: Optional[str] = None
    seniority: Optional[str] = None  # intern | new_grad | junior | mid | senior | lead | executive
    job_level: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    salary_period: Optional[str] = None  # hourly | daily | monthly | yearly
    salary_interval: Optional[str] = None
    salary_raw: Optional[str] = None

    # Timing
    posted_at: Optional[datetime.datetime] = None
    date_posted: Optional[str] = None
    first_seen_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    fetched_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    updated_at: Optional[datetime.datetime] = None

    # URLs
    apply_url: Optional[str] = None
    job_url: Optional[str] = None
    url: Optional[str] = None

    # Technologies
    technologies: List[str] = Field(default_factory=list)

    # Visa Intelligence (The Moat)
    visa_sponsorship: Optional[bool] = None
    visa_confidence: VisaConfidence = Field(default=VisaConfidence.UNKNOWN)
    visa_type: Optional[str] = None
    visa_sponsor_meta: Optional[Dict[str, Any]] = None
    auth_fit: Optional[str] = None  # ineligible | remote_ok | sponsor_required_and_plausible | sponsor_unknown | already_authorized
    visa_status: Optional[str] = None  # sponsors | likely | opt_friendly | unknown | no
    visa_score: Optional[float] = None
    visa_evidence: List[str] = Field(default_factory=list)

    # AI Classification (Optional)
    relevance_score: Optional[float] = None
    classification_track: Optional[str] = None  # internship | engineer | borderline | other
    track: Optional[str] = None
    classification_reason: Optional[str] = None
    relevance_why: Optional[str] = None
    why_matched: Optional[str] = None
    is_ai_role: Optional[bool] = None
    remote_scope_ai: Optional[str] = None
    remote_scope: Optional[str] = None
    resume_match_score: Optional[int] = None
    resume_match_why: Optional[str] = None

    # B2B Lead Gen & Enrichment (Hiring Contacts & Company Intel)
    hiring_contacts: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    company_intel: Optional[Dict[str, Any]] = None

    # Composite Scoring & Ranking
    composite_score: Optional[float] = None

    # Metadata & Change Detection
    raw_source_metadata: Optional[Dict[str, Any]] = None
    raw_source_payload: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    jd_hash: str = Field(default="")

    model_config = ConfigDict(use_enum_values=True, populate_by_name=True)

    @field_validator("id", mode="before")
    @classmethod
    def ensure_id(cls, v: Any) -> str:
        if not v:
            return f"job-{datetime.datetime.now(datetime.timezone.utc).timestamp()}"
        return str(v)

    def model_post_init(self, __context: Any) -> None:
        """Ensure derived fields are populated."""
        if not self.company_normalized and self.company:
            self.company_normalized = _normalize_name(self.company)
        if not self.location and self.location_raw:
            self.location = self.location_raw
        elif not self.location_raw and self.location:
            self.location_raw = self.location
        if not self.description:
            self.description = self.description_text or self.description_html or self.snippet or ""
        if not self.description_text and self.description:
            self.description_text = self.description
        if not self.url and self.apply_url:
            self.url = self.apply_url
        elif not self.apply_url and self.url:
            self.apply_url = self.url
        if not self.job_url:
            self.job_url = self.url or self.apply_url or ""
        if self.is_remote is None and self.remote:
            self.is_remote = self.remote
        elif self.remote is False and self.is_remote is True:
            self.remote = True
        if not self.jd_hash and self.description:
            self.jd_hash = hashlib.sha256(self.description.encode("utf-8")).hexdigest()
        if not self.track and self.classification_track:
            self.track = self.classification_track
        elif not self.classification_track and self.track:
            self.classification_track = self.track
        if not self.relevance_why and self.classification_reason:
            self.relevance_why = self.classification_reason
        elif not self.classification_reason and self.relevance_why:
            self.classification_reason = self.relevance_why
        if not self.why_matched and self.relevance_why:
            self.why_matched = self.relevance_why

    @property
    def fingerprint(self) -> str:
        """Compute robust fingerprint: SHA256(company_normalized|title_normalized|location_normalized)."""
        norm_title = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", self.title.lower())).strip()
        norm_loc = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (self.location or "remote").lower())).strip()
        norm_comp = self.company_normalized or _normalize_name(self.company)
        key = f"{norm_comp}|{norm_title}|{norm_loc}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def to_apify_dict(self, include_description: bool = True, include_raw_metadata: bool = False) -> Dict[str, Any]:
        """Convert canonical Job model to camelCase dictionary for Apify Dataset."""
        posted_iso = None
        if self.posted_at:
            posted_iso = self.posted_at.isoformat()
        elif self.date_posted:
            posted_iso = self.date_posted

        conf_str = self.visa_confidence if isinstance(self.visa_confidence, str) else self.visa_confidence.value

        out: Dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "companyNormalized": self.company_normalized or _normalize_name(self.company),
            "location": self.location or (", ".join(self.locations) if self.locations else "Remote"),
            "locations": self.locations,
            "remote": bool(self.remote or self.is_remote),
            "remoteType": self.remote_type if isinstance(self.remote_type, str) else (self.remote_type.value if self.remote_type else "unknown"),
            "allowedRegions": self.allowed_regions,
            "country": self.country,
            "employmentType": self.employment_type or self.job_type,
            "seniority": self.seniority or self.job_level,
            "salaryMin": self.salary_min,
            "salaryMax": self.salary_max,
            "salaryCurrency": self.salary_currency,
            "salaryPeriod": self.salary_period or self.salary_interval,
            "postedAt": posted_iso,
            "applyUrl": self.apply_url or self.url or "",
            "jobUrl": self.job_url or self.url or self.apply_url or "",
            "source": self.source,
            "ats": self.ats or self.source,
            "sourceCategory": self.metadata.get("source_category"),
            "destinationCountry": self.country if self.metadata.get("overseas") else None,
            "technologies": self.technologies,
            "visaSignal": conf_str,
            "visaConfidence": round(float(VISA_CONFIDENCE_FLOAT_MAP.get(conf_str, 0.25)), 2),
            "visaType": self.visa_type,
            "visaSponsorMeta": self.visa_sponsor_meta,
            "authFit": self.auth_fit,
            "relevanceScore": self.relevance_score,
            "compositeScore": self.composite_score,
            "classificationReason": self.classification_reason or self.relevance_why,
            "isAiRole": self.is_ai_role,
            "hiringContacts": self.hiring_contacts if self.hiring_contacts is not None else [],
            "companyIntel": self.company_intel,
        }

        if include_description:
            out["description"] = self.description
            out["snippet"] = self.snippet

        if include_raw_metadata:
            out["rawSourceMetadata"] = self.raw_source_metadata or self.raw_source_payload or {}

        # Remove keys with None values for clean Apify output
        return {k: v for k, v in out.items() if v is not None}

    @property
    def visaSponsorship_bool(self) -> Optional[bool]:
        if self.visa_sponsorship is not None:
            return self.visa_sponsorship
        if self.visa_confidence in (VisaConfidence.STATED_IN_JD.value, VisaConfidence.ON_SPONSOR_LIST.value, VisaConfidence.HISTORICAL_FILINGS.value):
            return True
        if self.visa_confidence == VisaConfidence.EXPLICIT_NO.value:
            return False
        if self.visa_status in (VisaStatus.SPONSORS.value, VisaStatus.LIKELY.value):
            return True
        if self.visa_status == VisaStatus.NO.value:
            return False
        return None

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Convert canonical Job model to legacy dictionary format for backwards compatibility."""
        d = self.model_dump()
        d["location"] = self.location or self.location_raw or (", ".join(self.locations) if self.locations else "Remote")
        d["description"] = self.description or self.description_text or self.description_html or self.snippet or ""
        d["why_matched"] = self.relevance_why or self.classification_reason or ""
        d["visa_sponsorship"] = self.visaSponsorship_bool is True
        d["classified_track"] = self.track or self.classification_track
        d["_fingerprint"] = self.metadata.get("fingerprint") or self.fingerprint
        if self.salary_min or self.salary_max or self.salary_raw:
            d["salary"] = self.salary_raw or (
                f"{self.salary_currency or '$'}{self.salary_min:,.0f} - {self.salary_max:,.0f}"
                if (self.salary_min and self.salary_max) else self.salary_raw
            )
        return d

    @classmethod
    def from_legacy_dict(cls, data: Dict[str, Any]) -> Job:
        """Construct canonical Job model from legacy dictionary."""
        source = str(data.get("source", "custom")).lower()
        company = data.get("company", "Unknown")
        title = data.get("title", "Untitled")
        url = data.get("url") or data.get("apply_url") or ""
        job_id = str(data.get("id") or f"{source}-{abs(hash(url or title + company))}")

        # Parse date
        date_raw = data.get("date_posted") or data.get("posted_at")
        posted_dt: Optional[datetime.datetime] = None
        if isinstance(date_raw, datetime.datetime):
            posted_dt = date_raw
        elif isinstance(date_raw, str):
            try:
                posted_dt = datetime.datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
            except Exception:
                pass

        # Determine visa confidence
        v_conf = data.get("visa_confidence")
        if not v_conf:
            v_status = data.get("visa_status")
            if v_status == "sponsors":
                v_conf = VisaConfidence.STATED_IN_JD
            elif v_status == "likely":
                v_conf = VisaConfidence.ON_SPONSOR_LIST
            elif v_status == "no":
                v_conf = VisaConfidence.EXPLICIT_NO
            else:
                v_conf = VisaConfidence.UNKNOWN
        elif isinstance(v_conf, str):
            try:
                v_conf = VisaConfidence(v_conf.lower())
            except Exception:
                v_conf = VisaConfidence.UNKNOWN

        desc = data.get("description") or data.get("description_text") or data.get("description_html") or data.get("snippet") or ""

        return cls(
            id=job_id,
            source=source,
            source_id=data.get("source_id"),
            ats=data.get("ats") or source,
            company=company,
            company_normalized=data.get("company_normalized") or _normalize_name(company),
            company_domain=data.get("company_domain"),
            title=title,
            url=url,
            apply_url=data.get("apply_url") or url,
            job_url=data.get("job_url") or url,
            location=data.get("location") or "",
            location_raw=data.get("location_raw") or data.get("location") or "",
            locations=data.get("locations") or ([data["location"]] if data.get("location") else []),
            remote=bool(data.get("remote") or data.get("is_remote")),
            is_remote=data.get("is_remote"),
            is_hybrid=data.get("is_hybrid"),
            workplace_type=data.get("workplace_type"),
            country=data.get("country"),
            description=desc,
            description_html=data.get("description_html"),
            description_text=data.get("description_text") or desc,
            snippet=data.get("snippet"),
            department=data.get("department"),
            team=data.get("team"),
            employment_type=data.get("employment_type") or data.get("job_type"),
            job_type=data.get("job_type"),
            seniority=data.get("seniority") or data.get("job_level"),
            job_level=data.get("job_level"),
            posted_at=posted_dt,
            date_posted=str(date_raw) if date_raw else None,
            fetched_at=data.get("fetched_at") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
            salary_min=data.get("salary_min"),
            salary_max=data.get("salary_max"),
            salary_currency=data.get("salary_currency"),
            salary_period=data.get("salary_period") or data.get("salary_interval"),
            salary_interval=data.get("salary_interval"),
            salary_raw=data.get("salary") or data.get("salary_raw"),
            technologies=data.get("technologies") or [],
            visa_sponsorship=data.get("visa_sponsorship"),
            visa_confidence=v_conf,
            visa_type=data.get("visa_type"),
            visa_sponsor_meta=data.get("visa_sponsor_meta") or data.get("sponsor_meta"),
            auth_fit=data.get("auth_fit"),
            visa_status=data.get("visa_status"),
            visa_score=data.get("visa_score"),
            visa_evidence=data.get("visa_evidence") or [],
            classification_track=data.get("classified_track") or data.get("track"),
            track=data.get("classified_track") or data.get("track"),
            relevance_score=data.get("relevance_score"),
            classification_reason=data.get("why_matched") or data.get("relevance_why") or data.get("classification_reason"),
            relevance_why=data.get("why_matched") or data.get("relevance_why"),
            why_matched=data.get("why_matched"),
            is_ai_role=data.get("is_ai_role") or data.get("is_ai_ml_day_to_day"),
            remote_scope=data.get("remote_scope"),
            remote_scope_ai=data.get("remote_scope_ai") or data.get("remote_scope"),
            allowed_regions=data.get("allowed_regions") or [],
            composite_score=data.get("composite_score"),
            resume_match_score=data.get("resume_match_score"),
            resume_match_why=data.get("resume_match_why"),
            metadata=data.get("metadata") or {},
            raw_source_payload=data.get("raw_source_payload"),
            raw_source_metadata=data.get("raw_source_metadata"),
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
