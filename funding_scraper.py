"""Funding Scraper (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.fetchers.funding import (
    ALLOWED_REGIONS,
    EXCLUDED_LOCATIONS,
    FUNDING_SIGNAL,
    HEADERS,
    SOURCES,
    _get,
    _http_session,
    extract_company_name,
    extract_funding_amount,
    extract_round,
    fetch_all_funding_deals,
    is_excluded_location,
    is_fresh,
    is_funding_announcement,
    match_keywords,
    scrape_html_fallback,
    scrape_rss_feed,
)

__all__ = [
    "HEADERS",
    "FUNDING_SIGNAL",
    "EXCLUDED_LOCATIONS",
    "ALLOWED_REGIONS",
    "SOURCES",
    "_http_session",
    "_get",
    "is_excluded_location",
    "is_funding_announcement",
    "extract_funding_amount",
    "extract_round",
    "extract_company_name",
    "match_keywords",
    "is_fresh",
    "scrape_rss_feed",
    "scrape_html_fallback",
    "fetch_all_funding_deals",
]
