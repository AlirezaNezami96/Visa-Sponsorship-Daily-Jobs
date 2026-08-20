"""Job Board Fetchers (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.fetchers.jobboards import (
    DEFAULT_CACHE_PATH,
    DEFAULT_CONFIG_PATH,
    JOBBOARD_FETCHERS,
    USER_AGENT,
    JobListing,
    build_indeed_url,
    canonicalize_indeed_url,
    extract_jobs_from_indeed_html,
    fetch_all_jobboard_jobs,
    fetch_indeed_jobs,
    fetch_indeed_jobs_async,
    get_indeed_domain,
    load_cache,
    load_config,
    save_cache,
)

__all__ = [
    "USER_AGENT",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_CACHE_PATH",
    "JobListing",
    "load_config",
    "load_cache",
    "save_cache",
    "get_indeed_domain",
    "build_indeed_url",
    "canonicalize_indeed_url",
    "extract_jobs_from_indeed_html",
    "fetch_indeed_jobs_async",
    "fetch_indeed_jobs",
    "JOBBOARD_FETCHERS",
    "fetch_all_jobboard_jobs",
]
