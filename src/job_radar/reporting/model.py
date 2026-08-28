"""Run report model: a single structured object the renderers consume.

``build_run_report`` folds the shared pipeline's ``PipelineResult`` plus the
search configuration into one self-contained, JSON-serializable structure.
No I/O, no Apify imports, no recomputation of pipeline work.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job, VISA_CONFIDENCE_FLOAT_MAP
from job_radar.reporting.aggregations import (
    aggregate_companies,
    aggregate_countries,
    aggregate_sources,
    aggregate_visa,
    country_flag,
    detect_country,
    format_salary,
    is_visa_positive,
    is_visa_strong,
    opportunity_reasons,
    opportunity_score,
    rank_top_jobs,
    source_trust,
    time_ago,
    top_match_count,
    visa_info,
    workplace_label,
    _conf_str,
)

ACTOR_TITLE = "Visa Sponsorship Jobs Report"

DISCLAIMER = (
    "Visa sponsorship signals are based on job-description evidence, employer information, "
    "public sponsorship/registration data, and other available sources. Presence of sponsorship "
    "evidence does not guarantee that an employer will sponsor a specific applicant for a specific "
    "position. Always confirm sponsorship directly with the employer."
)


@dataclass
class TopJobView:
    rank: int
    opportunityScore: int
    title: str
    company: str
    location: str
    country: str
    countryFlag: str
    remote: bool
    workplace: str
    employmentType: str
    seniority: str
    salary: str
    visaSignal: str
    visaLabel: str
    visaTone: str
    visaEmoji: str
    visaConfidence: float
    visaEvidence: str
    source: str
    sourceTrust: str
    postedAgo: str
    postedAt: str
    technologies: List[str]
    reasons: List[str]
    applyUrl: str
    snippet: str


@dataclass
class RunReport:
    generatedAt: str
    actorTitle: str
    status: str  # "completed" | "completed_empty" | "timeout" | "failed"
    empty: bool
    summary: Dict[str, Any] = field(default_factory=dict)
    searchCriteria: Dict[str, Any] = field(default_factory=dict)
    topJobs: List[TopJobView] = field(default_factory=list)
    countryStats: List[Dict[str, Any]] = field(default_factory=list)
    companyStats: List[Dict[str, Any]] = field(default_factory=list)
    sourceStats: List[Dict[str, Any]] = field(default_factory=list)
    visaStats: List[Dict[str, Any]] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER
    metadata: Dict[str, Any] = field(default_factory=dict)


def _iso(dt: Optional[datetime.datetime]) -> str:
    if not dt:
        return ""
    try:
        return dt.isoformat()
    except Exception:
        return ""


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _snippet(job: Job, max_chars: int = 220) -> str:
    text = getattr(job, "snippet", None) or getattr(job, "description_text", None) or ""
    text = " ".join(str(text).split())
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _build_search_criteria(config: JobSearchConfig) -> Dict[str, Any]:
    """Echo back the candidate/search configuration used for this run."""
    return {
        "keywords": list(getattr(config, "keywords", []) or []),
        "excludeKeywords": list(getattr(config, "exclude_keywords", []) or []),
        "countries": list(getattr(config, "countries", []) or []),
        "cities": list(getattr(config, "cities", []) or []),
        "remoteOnly": bool(getattr(config, "remote_only", False)),
        "remoteRegions": list(getattr(config, "remote_regions", []) or []),
        "seniorityLevels": list(getattr(config, "seniority_levels", []) or []),
        "employmentTypes": list(getattr(config, "employment_types", []) or []),
        "technologies": list(getattr(config, "technologies", []) or []),
        "postedWithinDays": int(getattr(config, "posted_within_days", 30) or 30),
        "visaSponsorshipOnly": bool(getattr(config, "visa_sponsorship_only", True)),
        "minVisaConfidence": str(getattr(config, "min_visa_confidence", "unknown")),
        "sources": list(getattr(config, "sources", []) or []),
        "enableOverseasSources": bool(getattr(config, "enable_overseas_sources", False)),
        "enableAIClassification": bool(getattr(config, "enable_ai_classification", False)),
        "maxResults": int(getattr(config, "max_results", 0) or 0),
    }


def _build_summary(
    jobs: List[Job],
    stats: Dict[str, Any],
    successful_sources: List[str],
    failed_sources: List[Dict[str, str]],
) -> Dict[str, Any]:
    total = len(jobs)
    remote_count = sum(
        1 for j in jobs if getattr(j, "remote", False) or getattr(j, "is_remote", False)
    )
    visa_relevant = sum(1 for j in jobs if is_visa_positive(_conf_str(j)))
    strong = sum(1 for j in jobs if is_visa_strong(_conf_str(j)))
    countries = {detect_country(j) for j in jobs}
    companies = {(getattr(j, "company_normalized", "") or (getattr(j, "company", "") or "").lower()) for j in jobs}
    salary_covered = sum(
        1 for j in jobs if getattr(j, "salary_min", None) or getattr(j, "salary_max", None)
    )

    def _stat(key: str, default: Any = 0) -> Any:
        return stats.get(key, default)

    return {
        "jobsEmitted": total,
        "jobsFetched": int(_stat("totalFetched")),
        "jobsAfterFiltering": int(_stat("totalFiltered")),
        "duplicatesRemoved": int(_stat("totalDeduplicated")),
        "simhashDuplicates": int(_stat("simhashDuplicates", 0) or 0),
        "visaRelevant": visa_relevant,
        "strongVisaEvidence": strong,
        "possibleVisaEvidence": max(0, visa_relevant - strong),
        "visaEnriched": int(_stat("visaEnrichedJobs", 0) or 0),
        "aiClassified": int(_stat("aiClassifiedJobs", 0) or 0),
        "remoteJobs": remote_count,
        "countries": len(countries),
        "companies": len(companies),
        "salaryCoverage": salary_covered,
        "successfulSourceCount": len(successful_sources),
        "failedSourceCount": len(failed_sources),
        "durationSeconds": float(_stat("durationSeconds", 0.0) or 0.0),
    }


def _build_top_jobs(jobs: List[Job], config: JobSearchConfig) -> List[TopJobView]:
    n = top_match_count(len(jobs))
    views: List[TopJobView] = []
    for idx, job in enumerate(rank_top_jobs(jobs, n), start=1):
        signal = _conf_str(job)
        info = visa_info(signal)
        country = detect_country(job)
        meta = getattr(job, "visa_sponsor_meta", None) or {}
        evidence = ""
        if isinstance(meta, dict):
            evidence = _safe_str(
                meta.get("notes") or meta.get("disclaimer") or meta.get("matched_sponsor") or meta.get("model")
            )
        try:
            conf_float = round(float(VISA_CONFIDENCE_FLOAT_MAP.get(signal, 0.25)), 2)
        except Exception:
            conf_float = 0.25
        views.append(TopJobView(
            rank=idx,
            opportunityScore=opportunity_score(job),
            title=_safe_str(getattr(job, "title", "")) or "Untitled",
            company=_safe_str(getattr(job, "company", "")) or "Unknown",
            location=_safe_str(getattr(job, "location", "")),
            country=country,
            countryFlag=country_flag(country),
            remote=bool(getattr(job, "remote", False) or getattr(job, "is_remote", False)),
            workplace=workplace_label(job),
            employmentType=_safe_str(getattr(job, "employment_type", None) or getattr(job, "job_type", None)),
            seniority=_safe_str(getattr(job, "seniority", None) or getattr(job, "job_level", None)),
            salary=format_salary(job),
            visaSignal=signal,
            visaLabel=info["label"],
            visaTone=info["tone"],
            visaEmoji=info["emoji"],
            visaConfidence=conf_float,
            visaEvidence=evidence,
            source=_safe_str(getattr(job, "source", "")),
            sourceTrust=source_trust(job),
            postedAgo=time_ago(getattr(job, "posted_at", None), getattr(job, "date_posted", None)),
            postedAt=_iso(getattr(job, "posted_at", None)),
            technologies=list(getattr(job, "technologies", []) or [])[:8],
            reasons=opportunity_reasons(job, config),
            applyUrl=_safe_str(getattr(job, "apply_url", None) or getattr(job, "job_url", None) or getattr(job, "url", None)),
            snippet=_snippet(job),
        ))
    return views


def _empty_suggestions(config: JobSearchConfig) -> List[str]:
    sug: List[str] = []
    if getattr(config, "visa_sponsorship_only", True):
        sug.append("Relax the visa filter (set visaSponsorshipOnly=false or includeUnknownVisa=true).")
    if (getattr(config, "min_visa_confidence", "unknown") or "unknown") not in ("unknown", ""):
        sug.append("Lower minVisaConfidence to accept weaker sponsorship signals.")
    if getattr(config, "countries", None) or getattr(config, "cities", None):
        sug.append("Broaden the target countries/cities.")
    if getattr(config, "keywords", None):
        sug.append("Remove or broaden the search keywords.")
    if getattr(config, "remote_only", False):
        sug.append("Turn off remoteOnly to include on-site and hybrid roles.")
    if getattr(config, "seniority_levels", None):
        sug.append("Remove the seniority restriction.")
    if int(getattr(config, "posted_within_days", 30) or 30) < 30:
        sug.append("Increase postedWithinDays to search a wider time window.")
    sug.append("Add or enable additional data sources.")
    return sug


def build_run_report(
    jobs: List[Job],
    config: JobSearchConfig,
    stats: Optional[Dict[str, Any]] = None,
    successful_sources: Optional[List[str]] = None,
    failed_sources: Optional[List[Dict[str, str]]] = None,
    status: str = "completed",
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> RunReport:
    """Build the complete, renderer-ready RunReport from pipeline outputs."""
    jobs = list(jobs or [])
    stats = dict(stats or {})
    successful_sources = list(successful_sources or [])
    failed_sources = list(failed_sources or [])

    empty = len(jobs) == 0
    report_status = status
    if empty and status == "completed":
        report_status = "completed_empty"

    report = RunReport(
        generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        actorTitle=ACTOR_TITLE,
        status=report_status,
        empty=empty,
        summary=_build_summary(jobs, stats, successful_sources, failed_sources),
        searchCriteria=_build_search_criteria(config),
        topJobs=_build_top_jobs(jobs, config),
        countryStats=aggregate_countries(jobs) if jobs else [],
        companyStats=aggregate_companies(jobs) if jobs else [],
        sourceStats=aggregate_sources(jobs, successful_sources, failed_sources),
        visaStats=aggregate_visa(jobs) if jobs else [],
        suggestions=_empty_suggestions(config) if empty else [],
        metadata=dict(extra_metadata or {}),
    )

    # Surface failed sources as non-fatal warnings (no stack traces).
    for fs in failed_sources:
        if isinstance(fs, dict):
            name = fs.get("name", "unknown")
            report.warnings.append(f"Source '{name}' did not return results for this run.")

    return report
