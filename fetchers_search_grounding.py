"""Search Grounding Fetcher (Root Compatibility Facade)."""
from job_radar.fetchers.search_grounding import (
    CATEGORY_PROFILES,
    build_search_grounding_prompt,
    fetch_search_grounded_jobs,
)

__all__ = [
    "CATEGORY_PROFILES",
    "build_search_grounding_prompt",
    "fetch_search_grounded_jobs",
]
