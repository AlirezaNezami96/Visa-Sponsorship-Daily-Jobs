"""
src/job_radar/taxonomy/__init__.py

Global Occupation Taxonomy and Normalization Module based on ISCO-08, ANZSCO, NOC, and ONET-SOC.
"""
from __future__ import annotations

from job_radar.taxonomy.isco import (
    ISCO_MAJOR_GROUPS,
    ISCO_SUB_MAJOR_GROUPS,
    ISCO_UNIT_GROUPS,
    ISCOUnitGroup,
    get_country_specific_occupation_code,
    lookup_isco_by_code,
    search_isco_by_keywords,
)
from job_radar.taxonomy.normalizer import (
    NormalizedJobFields,
    detect_sponsorship_language,
    extract_employment_type,
    extract_remote_scope,
    extract_seniority,
    normalize_job_posting,
    normalize_location,
    normalize_title_string,
)
from job_radar.taxonomy.skills import extract_skills_from_text

__all__ = [
    "ISCO_MAJOR_GROUPS",
    "ISCO_SUB_MAJOR_GROUPS",
    "ISCO_UNIT_GROUPS",
    "ISCOUnitGroup",
    "lookup_isco_by_code",
    "search_isco_by_keywords",
    "get_country_specific_occupation_code",
    "NormalizedJobFields",
    "normalize_title_string",
    "extract_seniority",
    "extract_remote_scope",
    "extract_employment_type",
    "normalize_location",
    "detect_sponsorship_language",
    "normalize_job_posting",
    "extract_skills_from_text",
]
