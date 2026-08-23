"""Maps raw Apify Actor input JSON to canonical JobSearchConfig."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from job_radar.models.config import JobSearchConfig

logger = logging.getLogger(__name__)


def input_to_config(actor_input: Optional[Dict[str, Any]]) -> JobSearchConfig:
    """
    Transforms Apify input JSON (supporting both nested sections from the UI
    and flat JSON keys from API calls) into a canonical JobSearchConfig.
    """
    raw = actor_input or {}

    # Extract section dictionaries (if present)
    search_crit = raw.get("searchCriteria", {}) if isinstance(raw.get("searchCriteria"), dict) else {}
    visa_filt = raw.get("visaFilters", {}) if isinstance(raw.get("visaFilters"), dict) else {}
    sources_sec = raw.get("sources", {}) if isinstance(raw.get("sources"), dict) else {}
    job_filt = raw.get("jobFilters", {}) if isinstance(raw.get("jobFilters"), dict) else {}
    ai_sec = raw.get("aiClassification", {}) if isinstance(raw.get("aiClassification"), dict) else {}
    output_sec = raw.get("outputOptions", {}) if isinstance(raw.get("outputOptions"), dict) else {}
    adv_sec = raw.get("advancedOptions", {}) if isinstance(raw.get("advancedOptions"), dict) else {}

    def _get_val(key: str, section_dict: Dict[str, Any], default: Any) -> Any:
        """Helper to get value from either section dict or flat top-level dict."""
        if key in section_dict and section_dict[key] is not None:
            return section_dict[key]
        if key in raw and raw[key] is not None:
            return raw[key]
        return default

    # 1. Search Criteria
    keywords = _get_val("keywords", search_crit, [])
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    exclude_keywords = _get_val("excludeKeywords", search_crit, [])
    if isinstance(exclude_keywords, str):
        exclude_keywords = [k.strip() for k in exclude_keywords.split(",") if k.strip()]
    countries = _get_val("countries", search_crit, [])
    if isinstance(countries, str):
        countries = [c.strip() for c in countries.split(",") if c.strip()]
    cities = _get_val("cities", search_crit, [])
    if isinstance(cities, str):
        cities = [c.strip() for c in cities.split(",") if c.strip()]
    remote_only = bool(_get_val("remoteOnly", search_crit, False))
    remote_regions = _get_val("remoteRegions", search_crit, [])
    if isinstance(remote_regions, str):
        remote_regions = [r.strip() for r in remote_regions.split(",") if r.strip()]

    # 2. Visa Filters
    visa_sponsorship_only = bool(_get_val("visaSponsorshipOnly", visa_filt, True))
    visa_registry_countries = _get_val("visaRegistryCountries", visa_filt, ["UK", "US"])
    min_visa_confidence = str(_get_val("minVisaConfidence", visa_filt, "unknown")).lower()
    exclude_explicit_no_sponsorship = bool(_get_val("excludeExplicitNoSponsorship", visa_filt, True))

    # 3. Data Sources
    sources = _get_val("sources", sources_sec, [])
    if isinstance(sources, str):
        sources = [s.strip() for s in sources.split(",") if s.strip()]
    company_urls = _get_val("companyUrls", sources_sec, [])
    if isinstance(company_urls, str):
        company_urls = [u.strip() for u in company_urls.split(",") if u.strip()]
    company_names = _get_val("companyNames", sources_sec, [])
    if isinstance(company_names, str):
        company_names = [n.strip() for n in company_names.split(",") if n.strip()]

    # 4. Job Filters
    seniority_levels = _get_val("seniorityLevels", job_filt, [])
    employment_types = _get_val("employmentTypes", job_filt, [])
    posted_within_days = int(_get_val("postedWithinDays", job_filt, 30))
    min_salary_raw = _get_val("minSalary", job_filt, None)
    min_salary = float(min_salary_raw) if min_salary_raw is not None else None
    salary_currency = str(_get_val("salaryCurrency", job_filt, "USD")).upper()
    technologies = _get_val("technologies", job_filt, [])
    if isinstance(technologies, str):
        technologies = [t.strip() for t in technologies.split(",") if t.strip()]

    # 5. AI Classification
    enable_ai_classification = bool(_get_val("enableAIClassification", ai_sec, False))
    minimum_relevance_score = float(_get_val("minimumRelevanceScore", ai_sec, 0.5))
    max_ai_calls = int(_get_val("maxAICalls", ai_sec, 200))
    classification_prompt = _get_val("classificationPrompt", ai_sec, None)

    # 6. Output Options
    max_results = int(_get_val("maxResults", output_sec, 200))
    sort_by = str(_get_val("sortBy", output_sec, "composite_score"))
    sort_order = str(_get_val("sortOrder", output_sec, "desc"))
    include_description = bool(_get_val("includeDescription", output_sec, True))
    include_raw_metadata = bool(_get_val("includeRawMetadata", output_sec, False))
    deduplicate_within_run = bool(_get_val("deduplicateWithinRun", output_sec, True))

    # 7. Advanced Options
    max_per_source = int(_get_val("maxPerSource", adv_sec, 500))
    concurrency = int(_get_val("concurrency", adv_sec, 5))
    timeout_per_source_secs = int(_get_val("timeoutPerSourceSecs", adv_sec, 30))
    max_runtime_secs = int(_get_val("maxRuntimeSecs", adv_sec, 300))
    use_browser_fallback = bool(_get_val("useBrowserFallback", adv_sec, False))
    proxy_configuration = _get_val("proxyConfiguration", adv_sec, None)

    return JobSearchConfig(
        keywords=keywords,
        exclude_keywords=exclude_keywords,
        countries=countries,
        cities=cities,
        remote_only=remote_only,
        remote_regions=remote_regions,
        visa_sponsorship_only=visa_sponsorship_only,
        visa_registry_countries=visa_registry_countries,
        min_visa_confidence=min_visa_confidence,
        exclude_explicit_no_sponsorship=exclude_explicit_no_sponsorship,
        sources=sources,
        company_urls=company_urls,
        company_names=company_names,
        seniority_levels=seniority_levels,
        employment_types=employment_types,
        posted_within_days=posted_within_days,
        min_salary=min_salary,
        salary_currency=salary_currency,
        technologies=technologies,
        enable_ai_classification=enable_ai_classification,
        minimum_relevance_score=minimum_relevance_score,
        max_ai_calls=max_ai_calls,
        classification_prompt=classification_prompt,
        max_results=max_results,
        sort_by=sort_by,
        sort_order=sort_order,
        include_description=include_description,
        include_raw_metadata=include_raw_metadata,
        deduplicate_within_run=deduplicate_within_run,
        max_per_source=max_per_source,
        concurrency=concurrency,
        timeout_per_source_secs=timeout_per_source_secs,
        max_runtime_secs=max_runtime_secs,
        use_browser_fallback=use_browser_fallback,
        proxy_configuration=proxy_configuration,
    )
