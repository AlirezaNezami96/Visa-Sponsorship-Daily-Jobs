"""Alert filter matching for the VisaLane alert dispatch stage.

Alert `filters` JSONB (all keys optional; missing key = no constraint):

  keywords:          [str]  ANY keyword appears in title/description (case-insensitive)
  countries:         [str]  2-letter country codes or country names (substring, case-insensitive)
  work_modes:        [str]  remote | hybrid | onsite
  exclude_companies: [str]  normalized company names to exclude
  min_confidence:    int    visa_sponsorship_confidence >= value
  verified_only:     bool   require visa_sponsorship_verified
  min_match:         int    resume_match_score >= value (jobs without a score fail)

Matching is deterministic and side-effect free — used identically by the
Python dispatch stage and mirrored by the process-new-jobs Edge Function.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)


def _norm(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum() or ch.isspace())


def _job_work_modes(job: dict[str, Any]) -> set:
    modes = set()
    mode = job.get("work_mode") or job.get("workplace_type")
    if mode:
        modes.add(str(mode).lower())
    if job.get("remote") or job.get("is_remote"):
        modes.add("remote")
    if job.get("is_hybrid"):
        modes.add("hybrid")
    if not modes:
        modes.add("unspecified")
    return modes


def job_matches_alert(job: dict[str, Any], filters: dict[str, Any]) -> bool:
    """Return True when a job satisfies every constraint in `filters`."""
    if not filters:
        return True

    title = str(job.get("title") or "")
    desc = str(job.get("description") or job.get("description_text") or job.get("snippet") or "")
    haystack = f"{title}\n{desc}".lower()

    keywords = filters.get("keywords") or []
    if keywords and not any(str(kw).lower() in haystack for kw in keywords):
        return False

    countries = filters.get("countries") or []
    if countries:
        job_cc = (job.get("country_code") or "").upper()
        job_country = (job.get("country") or "").lower()
        job_loc = (job.get("location_raw") or job.get("location") or "").lower()
        matched = False
        for c in countries:
            c_clean = str(c).strip()
            if len(c_clean) == 2:
                if c_clean.upper() == job_cc:
                    matched = True
                    break
            elif c_clean.lower() in job_country or c_clean.lower() in job_loc:
                matched = True
                break
        if not matched:
            return False

    work_modes = [str(m).lower() for m in (filters.get("work_modes") or [])]
    if work_modes and not (_job_work_modes(job) & set(work_modes)):
        return False

    excluded = [_norm(str(x)) for x in (filters.get("exclude_companies") or [])]
    if excluded and _norm(str(job.get("company") or "")) in excluded:
        return False

    min_confidence = filters.get("min_confidence")
    if min_confidence is not None:
        conf = job.get("visa_sponsorship_confidence")
        if conf is None or int(conf) < int(min_confidence):
            return False

    if filters.get("verified_only") and not job.get("visa_sponsorship_verified"):
        return False

    min_match = filters.get("min_match")
    if min_match is not None:
        score = job.get("resume_match_score")
        if score is None:
            match = job.get("resume_match") or {}
            score = match.get("ats_score") if isinstance(match, dict) else None
        if score is None or int(score) < int(min_match):
            return False

    return True


def match_jobs_to_alerts(
    jobs: Iterable[dict[str, Any]],
    alerts: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group matching jobs per alert.

    `alerts` rows need at least: id, filters (dict). Returns
    {alert_id: [job, ...]} containing only alerts with >=1 match.
    """
    result: dict[str, list[dict[str, Any]]] = {}
    alerts_list = list(alerts)
    jobs_list = list(jobs)
    for alert in alerts_list:
        alert_id = str(alert.get("id"))
        filters = alert.get("filters") or {}
        matches = [j for j in jobs_list if job_matches_alert(j, filters)]
        if matches:
            result[alert_id] = matches
    logger.info(
        "Alert matching: %d jobs against %d alerts -> %d alerts matched",
        len(jobs_list),
        len(alerts_list),
        len(result),
    )
    return result
