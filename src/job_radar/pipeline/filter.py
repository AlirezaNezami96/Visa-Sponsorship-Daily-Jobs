"""Filtering logic for the shared job pipeline."""
from __future__ import annotations

import datetime
import logging
import re
from typing import Any, List, Optional

from job_radar.models.config import JobSearchConfig
from job_radar.models.enums import VisaConfidence
from job_radar.models.job import Job

logger = logging.getLogger(__name__)


KEYWORD_SYNONYMS = {
    "software engineer": ["software developer", "swe", "software dev", "dev", "programmer"],
    "machine learning": ["ml", "ml engineer", "ai engineer", "data scientist"],
    "android": ["mobile", "kotlin", "android developer", "android engineer", "android dev"],
    "frontend": ["front-end", "front end", "ui", "react", "web developer"],
    "backend": ["back-end", "back end", "server", "api"],
    "fullstack": ["full-stack", "full stack"],
    "data engineer": ["data platform", "etl", "data pipeline"],
    "devops": ["sre", "site reliability", "platform engineer", "infrastructure"],
    "product manager": ["pm", "product owner"],
    "designer": ["ux", "ui designer", "product designer"],
}


def expand_keywords(keywords: List[str]) -> List[str]:
    """Expand keywords with synonyms for broader matching."""
    expanded = set(keywords)
    for kw in keywords:
        kw_lower = kw.lower().strip()
        if kw_lower in KEYWORD_SYNONYMS:
            expanded.update(KEYWORD_SYNONYMS[kw_lower])
        for syn_key, syn_list in KEYWORD_SYNONYMS.items():
            if syn_key in kw_lower or kw_lower in syn_key:
                expanded.update(syn_list)
    return list(expanded)


def matches_keywords(job_title: str, job_description: str, keywords: List[str]) -> bool:
    """
    Permissive keyword matching.
    - OR logic: match ANY keyword, not ALL
    - Case-insensitive
    - Word-boundary aware but allows partial matches for compound terms
    - Also checks common abbreviations and synonyms
    """
    if not keywords:
        return True

    title_lower = (job_title or "").lower()
    desc_lower = (job_description or "").lower()[:500]

    all_keywords = expand_keywords(keywords)

    for keyword in all_keywords:
        kw = keyword.lower().strip()
        if not kw:
            continue

        if kw in title_lower or re.search(r"\b" + re.escape(kw) + r"\b", title_lower):
            return True

        variations = [
            kw,
            kw.replace(" ", "-"),
            kw.replace(" ", ""),
            kw.replace("engineer", "dev"),
            kw.replace("engineer", "developer"),
            kw.replace("developer", "engineer"),
            kw.replace("software", "swe"),
        ]

        for var in variations:
            if var in title_lower or re.search(r"\b" + re.escape(var) + r"\b", title_lower):
                return True

        if kw in desc_lower or re.search(r"\b" + re.escape(kw) + r"\b", desc_lower):
            return True

    return False


def is_job_fresh(job: Job, max_age_days: int) -> bool:
    """Check if job posting date is within max_age_days. Fails open if date is unknown."""
    if not max_age_days or max_age_days <= 0:
        return True

    posted_dt = job.posted_at
    if not posted_dt and job.date_posted:
        try:
            posted_dt = datetime.datetime.fromisoformat(job.date_posted.replace("Z", "+00:00"))
        except Exception:
            pass

    if not posted_dt:
        return True

    if posted_dt.tzinfo is None:
        posted_dt = posted_dt.replace(tzinfo=datetime.timezone.utc)

    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - posted_dt).days <= max_age_days


def filter_job(job: Job, config: JobSearchConfig) -> bool:
    """Evaluate whether a job matches all configured criteria."""
    title_lower = (job.title or "").lower()
    desc_lower = (job.description or job.snippet or "").lower()
    comp_lower = (job.company or "").lower()
    loc_lower = (job.location or "").lower()
    combined_text = f"{title_lower} {desc_lower} {comp_lower}"

    # 1. Freshness filter
    if not is_job_fresh(job, config.posted_within_days):
        return False

    # 2. Exclude keywords
    if config.exclude_keywords:
        for exc in config.exclude_keywords:
            exc_clean = exc.lower().strip()
            if exc_clean and (
                re.search(r"\b" + re.escape(exc_clean) + r"\b", title_lower)
                or exc_clean in title_lower
            ):
                return False

    # 3. Include keywords (if provided, permissive matching)
    if config.keywords:
        desc_raw = job.description or job.snippet or ""
        if not matches_keywords(job.title or "", desc_raw, config.keywords):
            techs_lower = [t.lower() for t in job.technologies]
            all_kw = expand_keywords(config.keywords)
            if not any(any(kw.lower() in t for t in techs_lower) for kw in all_kw):
                return False

    # 4. Remote filter
    if config.remote_only:
        is_remote = bool(job.remote or job.is_remote)
        has_remote_loc = any(w in loc_lower for w in ("remote", "anywhere", "worldwide", "virtual", "home"))
        if not is_remote and not has_remote_loc:
            return False

    # 5. Remote regions filter
    if config.remote_regions and (job.remote or job.is_remote):
        regions_lower = [r.lower() for r in config.remote_regions]
        allowed = [r.lower() for r in job.allowed_regions]
        if not any(r in regions_lower or r in loc_lower for r in allowed) and "worldwide" not in allowed and "remote (worldwide)" not in loc_lower:
            return False

    # 6. Country filter
    if config.countries:
        countries_lower = [c.lower() for c in config.countries]
        loc_and_country = f"{loc_lower} {(job.country or '').lower()}"
        if not any(c in loc_and_country for c in countries_lower):
            # Check allowed regions
            if not any(any(c in r.lower() for c in countries_lower) for r in job.allowed_regions):
                return False

    # 7. City filter
    if config.cities:
        cities_lower = [c.lower() for c in config.cities]
        if not any(city in loc_lower for city in cities_lower):
            return False

    # 8. Seniority filter
    if config.seniority_levels:
        sen_lower = [s.lower() for s in config.seniority_levels]
        job_sen = (job.seniority or "").lower()
        if job_sen and job_sen not in sen_lower:
            # Check if title explicitly indicates target seniority
            if not any(s in title_lower for s in sen_lower):
                return False

    # 9. Employment type filter
    if config.employment_types:
        types_lower = [t.lower() for t in config.employment_types]
        job_emp = (job.employment_type or "").lower()
        if job_emp and job_emp not in types_lower:
            return False

    # 10. Required technologies filter
    if config.technologies:
        techs_lower = [t.lower() for t in config.technologies]
        job_techs = [t.lower() for t in job.technologies]
        if not any(t in combined_text or t in job_techs for t in techs_lower):
            return False

    # 11. Salary floor filter (only if salary is stated)
    if config.min_salary and config.min_salary > 0:
        if job.salary_max and job.salary_max < config.min_salary:
            return False
        elif job.salary_min and not job.salary_max and job.salary_min < config.min_salary:
            return False

    # 12. Explicit no-sponsorship exclusion
    if config.exclude_explicit_no_sponsorship:
        if job.visa_confidence == VisaConfidence.EXPLICIT_NO or job.visa_status == "no":
            return False

    return True


def filter_jobs(jobs: List[Job], config: JobSearchConfig) -> List[Job]:
    """Filter a list of jobs against the configured criteria."""
    return [job for job in jobs if filter_job(job, config)]
