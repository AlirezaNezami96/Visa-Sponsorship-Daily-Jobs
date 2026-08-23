"""Visa sponsorship evaluation and registry matching pipeline stage."""
from __future__ import annotations

import logging
from typing import List, Tuple

from job_radar.models.config import JobSearchConfig
from job_radar.models.enums import AuthFit, VisaConfidence
from job_radar.models.job import Job
from job_radar.visa.evaluator import evaluate_job_visa, score_job_visa

logger = logging.getLogger(__name__)

# Ranking map for min_visa_confidence threshold
CONFIDENCE_RANK = {
    "unknown": 0,
    "historical_filings": 1,
    "on_sponsor_list": 2,
    "stated_in_jd": 3,
}


def evaluate_visa_for_job(job: Job) -> Job:
    """Evaluate visa sponsorship signals and registry match for a single job."""
    job_dict = job.to_legacy_dict()
    try:
        conf, auth, meta = evaluate_job_visa(job_dict)
        job.visa_confidence = conf
        job.auth_fit = auth.value if hasattr(auth, "value") else str(auth)
        job.visa_sponsor_meta = meta

        if conf == VisaConfidence.STATED_IN_JD:
            job.visa_sponsorship = True
        elif conf in (VisaConfidence.ON_SPONSOR_LIST, VisaConfidence.HISTORICAL_FILINGS):
            job.visa_sponsorship = True
            if meta and meta.get("matched_sponsor"):
                job.visa_type = "UK Skilled Worker" if meta.get("country") == "GB" or meta.get("rating") else "US H-1B"
        elif conf == VisaConfidence.EXPLICIT_NO:
            job.visa_sponsorship = False

        # Compute status and score
        status, score, evidence = score_job_visa(job_dict)
        job.visa_status = status
        job.visa_score = score
        job.visa_evidence = evidence
    except Exception as e:
        logger.debug("Visa evaluation failed for %s (%s): %s", job.company, job.title, e)
        if not job.visa_confidence:
            job.visa_confidence = VisaConfidence.UNKNOWN

    return job


def evaluate_and_filter_visa(jobs: List[Job], config: JobSearchConfig) -> Tuple[List[Job], int]:
    """
    Evaluates visa intelligence for all jobs and applies visa filters.
    Returns (filtered_jobs, enriched_count).
    """
    enriched_count = 0
    passed_jobs: List[Job] = []

    min_rank = CONFIDENCE_RANK.get(config.min_visa_confidence.lower(), 0)

    for job in jobs:
        evaluate_visa_for_job(job)
        if job.visa_confidence in (VisaConfidence.ON_SPONSOR_LIST, VisaConfidence.HISTORICAL_FILINGS, VisaConfidence.STATED_IN_JD):
            enriched_count += 1

        # 1. Exclude explicit NO if configured
        if config.exclude_explicit_no_sponsorship and job.visa_confidence == VisaConfidence.EXPLICIT_NO:
            continue

        # 2. Min confidence threshold
        conf_val = job.visa_confidence if isinstance(job.visa_confidence, str) else job.visa_confidence.value
        job_rank = CONFIDENCE_RANK.get(conf_val, 0)
        if job_rank < min_rank:
            continue

        # 3. Visa sponsorship only filter
        if config.visa_sponsorship_only:
            # Keep if explicitly offered in JD, company on sponsor list, historical filings, or unknown if permissive
            if job.visa_confidence == VisaConfidence.EXPLICIT_NO:
                continue
            if min_rank > 0 and job_rank < min_rank:
                continue
            # If min_visa_confidence is unknown but visa_sponsorship_only is true, exclude known NOs
            if job.visa_status == "no":
                continue

        passed_jobs.append(job)

    return passed_jobs, enriched_count
