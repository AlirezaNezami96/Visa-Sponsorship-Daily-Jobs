"""
src/job_radar/scoring/composite.py

Calculates the multi-dimensional composite ranking score for job opportunities:
  composite = 0.30*ats_score + 0.25*visa_score + 0.15*seniority_fit + 0.10*recency + 0.10*pay_fit + 0.10*company_quality
"""
from __future__ import annotations

import datetime
import logging
import time
from typing import Any, Dict, Optional

from job_radar.visa.models import VisaConfidence

logger = logging.getLogger(__name__)


def calculate_visa_score(visa_confidence: str | VisaConfidence) -> float:
    """Map visa confidence to a 0-100 score."""
    val = str(visa_confidence).lower().replace("visaconfidence.", "")
    if val == "stated_in_jd":
        return 100.0
    elif val == "on_sponsor_list":
        return 80.0
    elif val == "historical_filings":
        return 60.0
    elif val == "unknown":
        return 25.0
    elif val == "explicit_no":
        return 0.0
    return 25.0


def calculate_seniority_fit(
    title: str,
    target_seniorities: Optional[list[str]] = None,
    excluded_seniorities: Optional[list[str]] = None,
) -> float:
    """Score title alignment with target career stage (0 or 100)."""
    t = title.lower()
    excluded = excluded_seniorities or ["staff", "principal", "director", "vp", "head of", "lead"]
    for exc in excluded:
        if exc in t:
            return 0.0

    targets = target_seniorities or ["intern", "new_grad", "junior", "mid", "entry"]
    # If general SWE or engineer without explicit high seniority, score high
    return 100.0


def calculate_recency_score(date_posted: Optional[str], first_seen_at: Optional[float] = None) -> float:
    """
    Score recency based on age:
      < 24h: 100
      < 72h: 70
      < 5d:  40
      else:  0
    """
    now = time.time()
    ts = first_seen_at or now

    if date_posted:
        try:
            # Try parsing ISO format
            dt = datetime.datetime.fromisoformat(date_posted.replace("Z", "+00:00"))
            ts = dt.timestamp()
        except Exception:
            pass

    age_hours = (now - ts) / 3600.0
    if age_hours < 24:
        return 100.0
    elif age_hours < 72:
        return 70.0
    elif age_hours < 120:
        return 40.0
    return 10.0


def calculate_pay_fit(
    salary_min: Optional[float],
    salary_max: Optional[float],
    salary_floor_usd: float = 70000.0,
    is_remote: bool = True,
) -> float:
    """Score compensation alignment with candidate floor."""
    if salary_max:
        return 100.0 if salary_max >= salary_floor_usd else 0.0
    if salary_min:
        return 100.0 if salary_min >= salary_floor_usd else 20.0
    # If salary unstated and remote, default favorable
    return 80.0 if is_remote else 50.0


def calculate_company_quality(job: Dict[str, Any], is_funded_watch: bool = False) -> float:
    """Score company pedigree, recent funding, or tier."""
    if is_funded_watch or job.get("is_funding_watch"):
        return 90.0
    sponsor_meta = job.get("sponsor_meta") or {}
    if sponsor_meta.get("rating") == "A":
        return 75.0
    return 50.0


def compute_composite_score(
    job: Dict[str, Any],
    ats_score: Optional[int] = None,
    candidate_profile: Optional[Dict[str, Any]] = None,
) -> float:
    """
    Computes weighted composite score (0.0 to 100.0).
    """
    profile = candidate_profile or {}
    targets = profile.get("targets", {})

    # 1. ATS Score (0.30)
    raw_ats = ats_score if ats_score is not None else job.get("ats_score", 50)
    ats_comp = float(raw_ats or 50)

    # 2. Visa Score (0.25)
    visa_conf = job.get("visa_confidence", VisaConfidence.UNKNOWN)
    visa_comp = calculate_visa_score(visa_conf)

    # 3. Seniority Fit (0.15)
    seniority_comp = calculate_seniority_fit(
        title=job.get("title", ""),
        target_seniorities=targets.get("seniority"),
        excluded_seniorities=targets.get("excluded_seniority"),
    )

    # 4. Recency (0.10)
    recency_comp = calculate_recency_score(
        date_posted=job.get("date_posted"),
        first_seen_at=job.get("first_seen_at"),
    )

    # 5. Pay Fit (0.10)
    pay_comp = calculate_pay_fit(
        salary_min=job.get("salary_min"),
        salary_max=job.get("salary_max"),
        salary_floor_usd=targets.get("salary_floor_usd", 70000.0),
        is_remote=job.get("remote_scope") in ("worldwide", "region_restricted"),
    )

    # 6. Company Quality (0.10)
    quality_comp = calculate_company_quality(job)

    composite = (
        0.30 * ats_comp
        + 0.25 * visa_comp
        + 0.15 * seniority_comp
        + 0.10 * recency_comp
        + 0.10 * pay_comp
        + 0.10 * quality_comp
    )

    return round(composite, 2)
