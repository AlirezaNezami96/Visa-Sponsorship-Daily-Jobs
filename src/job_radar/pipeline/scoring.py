"""Composite scoring and ranking stage for job opportunities."""
from __future__ import annotations

import datetime
import logging
from typing import List, Optional

from job_radar.models.config import JobSearchConfig
from job_radar.models.enums import VisaConfidence
from job_radar.models.job import Job

logger = logging.getLogger(__name__)

VISA_SCORE_MAP = {
    VisaConfidence.STATED_IN_JD.value: 100.0,
    VisaConfidence.ON_SPONSOR_LIST.value: 85.0,
    VisaConfidence.HISTORICAL_FILINGS.value: 65.0,
    VisaConfidence.UNKNOWN.value: 25.0,
    VisaConfidence.EXPLICIT_NO.value: 0.0,
}

SOURCE_QUALITY_MAP = {
    "greenhouse": 100.0,
    "lever": 100.0,
    "ashby": 100.0,
    "workable": 90.0,
    "smartrecruiters": 90.0,
    "personio": 90.0,
    "remoteok": 75.0,
    "remotive": 75.0,
    "himalayas": 75.0,
    "jobicy": 70.0,
    "arbeitnow": 70.0,
    "hn_whoshiring": 65.0,
}


def calculate_recency_score(job: Job) -> float:
    """Score recency: <24h = 100, <72h = 70, <5d = 40, else = 10."""
    posted = job.posted_at
    if not posted and job.date_posted:
        try:
            posted = datetime.datetime.fromisoformat(job.date_posted.replace("Z", "+00:00"))
        except Exception:
            pass

    if not posted:
        return 50.0

    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=datetime.timezone.utc)

    now = datetime.datetime.now(datetime.timezone.utc)
    age_hours = (now - posted).total_seconds() / 3600.0

    if age_hours < 24:
        return 100.0
    elif age_hours < 72:
        return 70.0
    elif age_hours < 120:
        return 40.0
    return 10.0


def calculate_seniority_fit(job: Job, target_seniorities: Optional[List[str]] = None) -> float:
    """Score seniority fit: 100 if matching or unstated, 0 if excluded."""
    title_lower = (job.title or "").lower()
    excluded = ["staff", "principal", "director", "vp", "head of"]
    for exc in excluded:
        if exc in title_lower:
            return 0.0

    if target_seniorities:
        targets = [s.lower() for s in target_seniorities]
        job_sen = (job.seniority or "").lower()
        if job_sen and job_sen in targets:
            return 100.0
        if any(t in title_lower for t in targets):
            return 100.0

    return 80.0


def calculate_pay_fit(job: Job, min_salary: Optional[float] = None) -> float:
    """Score compensation: 100 if >= min_salary or unstated, 0 if below floor."""
    if not min_salary or min_salary <= 0:
        return 100.0 if (job.salary_min or job.salary_max) else 75.0

    if job.salary_max:
        return 100.0 if job.salary_max >= min_salary else 0.0
    if job.salary_min:
        return 100.0 if job.salary_min >= min_salary else 20.0
    return 75.0  # Unstated


def compute_job_score(job: Job, config: JobSearchConfig) -> float:
    """Compute weighted composite score (0.0 to 1.0) according to the formula."""
    # 1. Visa score (0.30)
    conf_key = job.visa_confidence if isinstance(job.visa_confidence, str) else job.visa_confidence.value
    visa_score = VISA_SCORE_MAP.get(conf_key, 25.0)

    # 2. Relevance score (0.25)
    rel_score = (job.relevance_score * 100.0) if job.relevance_score is not None else 50.0

    # 3. Recency score (0.15)
    recency_score = calculate_recency_score(job)

    # 4. Seniority fit (0.15)
    seniority_score = calculate_seniority_fit(job, config.seniority_levels)

    # 5. Pay fit (0.10)
    pay_score = calculate_pay_fit(job, config.min_salary)

    # 6. Source quality (0.05)
    source_quality = SOURCE_QUALITY_MAP.get(job.source.lower(), 60.0)

    raw_composite = (
        0.30 * visa_score
        + 0.25 * rel_score
        + 0.15 * recency_score
        + 0.15 * seniority_score
        + 0.10 * pay_score
        + 0.05 * source_quality
    )

    # Normalized score in 0.00 - 1.00 range
    return round(raw_composite / 100.0, 2)


def score_and_rank_jobs(jobs: List[Job], config: JobSearchConfig) -> List[Job]:
    """Calculate composite score for each job and sort according to config."""
    for job in jobs:
        job.composite_score = compute_job_score(job, config)

    reverse_sort = config.sort_order.lower() == "desc"
    sort_key = config.sort_by.lower()

    if sort_key == "relevance_score":
        jobs.sort(key=lambda j: (j.relevance_score or 0.0), reverse=reverse_sort)
    elif sort_key == "posted_at":
        epoch = datetime.datetime.fromtimestamp(0, tz=datetime.timezone.utc)
        jobs.sort(key=lambda j: (j.posted_at or epoch), reverse=reverse_sort)
    elif sort_key == "visa_confidence":
        jobs.sort(
            key=lambda j: VISA_SCORE_MAP.get(
                j.visa_confidence if isinstance(j.visa_confidence, str) else j.visa_confidence.value, 0
            ),
            reverse=reverse_sort,
        )
    elif sort_key == "salary_max":
        jobs.sort(key=lambda j: (j.salary_max or j.salary_min or 0.0), reverse=reverse_sort)
    else:  # Default to composite_score
        jobs.sort(key=lambda j: (j.composite_score or 0.0), reverse=reverse_sort)

    return jobs
