"""Job Pipeline Acquisition (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.fetchers.pipeline import (
    API_ATS,
    DEFAULT_API_WORKERS,
    CompanyFetch,
    _env_positive_int,
    _fetch_api_company,
    fetch_companies,
)

__all__ = [
    "DEFAULT_API_WORKERS",
    "API_ATS",
    "CompanyFetch",
    "_env_positive_int",
    "_fetch_api_company",
    "fetch_companies",
]
