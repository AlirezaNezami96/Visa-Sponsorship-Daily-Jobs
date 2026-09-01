"""Dataclass configuration for Job Search & Apify Actor execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class JobSearchConfig:
    """Canonical search configuration consumed by the shared pipeline."""

    # Search Criteria
    keywords: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    countries: List[str] = field(default_factory=list)
    cities: List[str] = field(default_factory=list)
    remote_only: bool = False
    remote_regions: List[str] = field(default_factory=list)

    # Visa Sponsorship Filters
    visa_sponsorship_only: bool = True
    include_unknown_visa: bool = False
    visa_registry_countries: List[str] = field(default_factory=lambda: ["UK", "US"])
    min_visa_confidence: str = "unknown"  # unknown | historical_filings | on_sponsor_list | stated_in_jd
    exclude_explicit_no_sponsorship: bool = True

    # Data Sources
    sources: List[str] = field(default_factory=list)
    company_urls: List[str] = field(default_factory=list)
    company_names: List[str] = field(default_factory=list)

    # Job Filters
    seniority_levels: List[str] = field(default_factory=list)
    employment_types: List[str] = field(default_factory=list)
    posted_within_days: int = 30
    min_salary: Optional[float] = None
    salary_currency: str = "USD"
    technologies: List[str] = field(default_factory=list)

    # AI Classification (Optional)
    enable_ai_classification: bool = False
    llm_provider: str = "gemini"  # gemini | groq
    llm_api_key: Optional[str] = None
    minimum_relevance_score: float = 0.5
    max_ai_calls: int = 200
    max_total_ai_charge_usd: Optional[float] = None
    classification_prompt: Optional[str] = None
    classifier_version: str = "v1"

    # Output Options
    max_results: int = 200
    sort_by: str = "composite_score"  # composite_score | relevance_score | posted_at | visa_confidence | salary_max
    sort_order: str = "desc"  # desc | asc
    include_description: bool = True
    include_raw_metadata: bool = False
    deduplicate_within_run: bool = True
    deduplication_across_runs: bool = True
    deduplication_ttl_days: int = 30
    reset_dedup_state: bool = False

    # Advanced Options
    max_per_source: int = 500
    max_companies_per_ats: int = 50
    concurrency: int = 5
    timeout_per_source_secs: int = 30
    max_runtime_secs: int = 300
    use_browser_fallback: bool = False
    proxy_configuration: Optional[Dict[str, Any]] = None
    proxy_url: Optional[str] = None
    refresh_registries: bool = False

    # Overseas Expansion (v1) — flag-gated; defaults preserve current behavior
    enable_overseas_sources: bool = False
    overseas_categories: List[str] = field(default_factory=lambda: ["government", "manpower_agency", "aggregator", "remote_board", "visa_specialist", "unknown_board"])
    overseas_destination_countries: List[str] = field(default_factory=list)   # adapter-level filter; empty = all
    overseas_max_sources_per_run: int = 150
    overseas_concurrency: int = 20
    overseas_budget_secs: int = 600
    overseas_fetch_details: bool = False
    overseas_max_detail_fetches: int = 300
    overseas_simhash_dedup: bool = True
    overseas_simhash_threshold: int = 6
    overseas_min_results: int = 20
    respect_robots_txt: bool = True
