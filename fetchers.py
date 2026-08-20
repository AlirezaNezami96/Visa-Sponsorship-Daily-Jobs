"""ATS API Fetchers (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.fetchers.ats import (
    ATS_FETCHERS,
    FETCHERS,
    fetch_ashby,
    fetch_ats_jobs,
    fetch_greenhouse,
    fetch_lever,
    fetch_personio,
    fetch_smartrecruiters,
    fetch_workable,
)

__all__ = [
    "FETCHERS",
    "ATS_FETCHERS",
    "fetch_greenhouse",
    "fetch_lever",
    "fetch_ashby",
    "fetch_smartrecruiters",
    "fetch_personio",
    "fetch_workable",
    "fetch_ats_jobs",
]
