"""Fetchers subpackage for job_radar."""
from job_radar.fetchers.ats import (
    ATS_FETCHERS,
    fetch_ashby,
    fetch_ats_jobs,
    fetch_greenhouse,
    fetch_lever,
    fetch_personio,
    fetch_smartrecruiters,
    fetch_workable,
)
from job_radar.fetchers.classify import ATS_PATTERNS, classify
from job_radar.fetchers.custom import (
    extract_jobs_from_html,
    fetch_custom_many_sync,
    fetch_custom_sync,
    fetch_with_playwright,
)
from job_radar.fetchers.discover import KNOWN_SLUGS, try_discover_ats
from job_radar.fetchers.funding import fetch_all_funding_deals
from job_radar.fetchers.jobboards import (
    JobListing,
    fetch_all_jobboard_jobs,
    fetch_indeed_jobs,
    load_config as load_jobboard_config,
)
from job_radar.fetchers.pipeline import CompanyFetch, fetch_companies
from job_radar.fetchers.public_apis import (
    fetch_all_public_apis,
    fetch_arbeitnow,
    fetch_himalayas,
    fetch_hn_who_is_hiring,
    fetch_remoteok,
    fetch_remotive,
)

__all__ = [
    "ATS_FETCHERS",
    "fetch_greenhouse",
    "fetch_lever",
    "fetch_ashby",
    "fetch_smartrecruiters",
    "fetch_personio",
    "fetch_workable",
    "fetch_ats_jobs",
    "ATS_PATTERNS",
    "classify",
    "extract_jobs_from_html",
    "fetch_custom_many_sync",
    "fetch_custom_sync",
    "fetch_with_playwright",
    "KNOWN_SLUGS",
    "try_discover_ats",
    "fetch_all_funding_deals",
    "JobListing",
    "fetch_all_jobboard_jobs",
    "fetch_indeed_jobs",
    "load_jobboard_config",
    "CompanyFetch",
    "fetch_companies",
    "fetch_all_public_apis",
    "fetch_remoteok",
    "fetch_remotive",
    "fetch_arbeitnow",
    "fetch_himalayas",
    "fetch_hn_who_is_hiring",
]
