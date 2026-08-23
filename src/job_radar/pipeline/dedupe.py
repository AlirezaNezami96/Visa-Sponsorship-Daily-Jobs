"""Within-run deduplication logic based on fingerprinting."""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from job_radar.models.job import Job

logger = logging.getLogger(__name__)


def deduplicate_jobs(jobs: List[Job]) -> Tuple[List[Job], int]:
    """
    Deduplicates a list of jobs within a single run.
    When duplicates are encountered, retains the version with the richest content.
    Returns (deduped_jobs, duplicate_count).
    """
    seen: Dict[str, Job] = {}
    duplicates_count = 0

    for job in jobs:
        fp = job.fingerprint
        if fp not in seen:
            seen[fp] = job
        else:
            duplicates_count += 1
            existing = seen[fp]
            # Replace if current job has richer description or is direct ATS source
            curr_desc_len = len(job.description or "")
            exist_desc_len = len(existing.description or "")

            is_curr_ats = job.source in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "personio")
            is_exist_ats = existing.source in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "personio")

            if (is_curr_ats and not is_exist_ats) or (curr_desc_len > exist_desc_len and is_curr_ats == is_exist_ats):
                # Preserve any existing annotations
                if existing.relevance_score is not None and job.relevance_score is None:
                    job.relevance_score = existing.relevance_score
                    job.classification_reason = existing.classification_reason
                if existing.visa_sponsor_meta and not job.visa_sponsor_meta:
                    job.visa_sponsor_meta = existing.visa_sponsor_meta
                seen[fp] = job

    deduped = list(seen.values())
    logger.info("Deduplication complete: %d unique jobs, %d duplicates removed", len(deduped), duplicates_count)
    return deduped, duplicates_count
