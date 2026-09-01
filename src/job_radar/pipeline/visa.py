"""Visa sponsorship evaluation and registry matching pipeline stage."""
from __future__ import annotations

import logging
from typing import List, Tuple

from job_radar.models.config import JobSearchConfig
from job_radar.models.enums import AuthFit, VisaConfidence
from job_radar.models.job import Job
from job_radar.sources.overseas.geo import visa_type_for_destination
from job_radar.visa.evaluator import evaluate_job_visa, score_job_visa

logger = logging.getLogger(__name__)

# Ranking map for min_visa_confidence threshold.
# Rank values are internal to this module only (renumbering is safe).
# Note: with employer_sponsored_region at rank 2, a user selecting
# min_visa_confidence="on_sponsor_list" (rank 3) will EXCLUDE
# employer_sponsored_region jobs — that is intentional: registry matches
# rank above the regional work-permit model.
CONFIDENCE_RANK = {
    "unknown": 0,
    "historical_filings": 1,
    "employer_sponsored_region": 2,
    "on_sponsor_list": 3,
    "known_sponsor": 4,
    "stated_in_jd": 5,
}

# Confidence values that count as positive sponsorship evidence for the
# visa_sponsorship_only filter and the enriched counter.
_POSITIVE_SIGNALS = ("known_sponsor", "stated_in_jd", "on_sponsor_list", "historical_filings", "employer_sponsored_region")


def evaluate_visa_for_job(job: Job) -> Job:
    """Evaluate visa sponsorship signals and registry match for a single job."""
    if job.visa_confidence and job.visa_confidence != VisaConfidence.UNKNOWN:
        return job

    job_dict = job.to_legacy_dict()
    try:
        conf, auth, meta = evaluate_job_visa(job_dict)
        job.visa_confidence = VisaConfidence(conf.value) if hasattr(conf, "value") else conf  # type: ignore[assignment]
        job.auth_fit = auth.value if hasattr(auth, "value") else str(auth)
        job.visa_sponsor_meta = meta

        if conf in (VisaConfidence.STATED_IN_JD, VisaConfidence.KNOWN_SPONSOR):
            job.visa_sponsorship = True
            if conf == VisaConfidence.KNOWN_SPONSOR and not job.visa_type:
                job.visa_type = "International Visa Sponsorship"
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

        # Map to 5-tier explainable model
        if conf in (VisaConfidence.ON_SPONSOR_LIST, VisaConfidence.KNOWN_SPONSOR):
            job.visa_tier = "VERIFIED"
        elif conf == VisaConfidence.STATED_IN_JD:
            job.visa_tier = "HIGH"
        elif conf in (VisaConfidence.HISTORICAL_FILINGS, VisaConfidence.EMPLOYER_SPONSORED_REGION):
            job.visa_tier = "MEDIUM"
        elif conf == VisaConfidence.EXPLICIT_NO:
            job.visa_tier = "NEGATIVE"
        elif score >= 0.75:
            job.visa_tier = "HIGH"
        elif score >= 0.50:
            job.visa_tier = "MEDIUM"
        elif score >= 0.20:
            job.visa_tier = "LOW"
        else:
            job.visa_tier = "UNKNOWN"
    except Exception as e:
        logger.debug("Visa evaluation failed for %s (%s): %s", job.company, job.title, e)
        if not job.visa_confidence:
            job.visa_confidence = VisaConfidence.UNKNOWN

    # Employer-sponsored-region model (overseas expansion pack). Applied only
    # when the registry/JD result is still UNKNOWN and the job came from the
    # overseas adapter. STATED_IN_JD / ON_SPONSOR_LIST / HISTORICAL_FILINGS /
    # EXPLICIT_NO from the evaluator above are always stronger and are kept.
    conf_val_now = job.visa_confidence if isinstance(job.visa_confidence, str) else getattr(job.visa_confidence, "value", "")
    if conf_val_now == VisaConfidence.UNKNOWN.value and job.metadata.get("overseas"):
        from job_radar.sources.overseas.geo import normalize_destination

        dest = normalize_destination(job.country or job.location)
        job.visa_confidence = VisaConfidence.EMPLOYER_SPONSORED_REGION
        job.visa_sponsorship = True
        job.visa_type = visa_type_for_destination(dest)
        job.visa_sponsor_meta = {
            "model": "employer_sponsored_region",
            "destination_country": job.country,
            "disclaimer": "Employer-sponsored work-permit destination; not a verified registry match",
        }

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
        conf_val = job.visa_confidence if isinstance(job.visa_confidence, str) else job.visa_confidence.value
        if conf_val in _POSITIVE_SIGNALS:
            enriched_count += 1

        # 1. Exclude explicit NO if configured
        if config.exclude_explicit_no_sponsorship and conf_val == "explicit_no":
            continue

        # 2. Min confidence threshold
        job_rank = CONFIDENCE_RANK.get(conf_val, 0)
        if job_rank < min_rank:
            continue

        # 3. Visa sponsorship only filter
        if config.visa_sponsorship_only:
            # Positive signals: known_sponsor, stated_in_jd, on_sponsor_list, historical_filings, employer_sponsored_region
            if conf_val in _POSITIVE_SIGNALS:
                passed_jobs.append(job)
            elif conf_val == "unknown":
                if config.include_unknown_visa:
                    passed_jobs.append(job)
                else:
                    # Check permissive heuristics: known sponsor or JD sponsorship terms
                    from job_radar.visa.evaluator import check_known_sponsor
                    if check_known_sponsor(job.company):
                        passed_jobs.append(job)
                    else:
                        desc_lower = (job.description or job.snippet or "").lower()
                        if any(term in desc_lower for term in [
                            "relocation", "visa", "sponsorship", "work permit",
                            "work authorization", "immigration", "right to work",
                            "international candidates", "relocate"
                        ]):
                            passed_jobs.append(job)
            else:
                # Excluded when include_unknown_visa is False
                continue
        else:
            # visa_sponsorship_only is False: include all non-excluded jobs
            passed_jobs.append(job)

    return passed_jobs, enriched_count
