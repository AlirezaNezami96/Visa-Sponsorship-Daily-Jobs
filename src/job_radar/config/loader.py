"""Configuration loader for AI Job Radar.

Loads and validates config.yaml with environment variable overrides.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional
import yaml

from job_radar.config.models import (
    ClassifierConfig,
    EmailConfig,
    FreshnessConfig,
    GeographyConfig,
    RadarConfig,
    ResumeConfig,
    ResumeMatcherConfig,
    SearchGroundingConfig,
    SourcesConfig,
    SupabaseConfig,
    TrackConfig,
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config.yaml"


def _find_config_file(path: Optional[str] = None) -> str:
    """Find configuration file searching standard locations."""
    candidates = [
        path,
        os.environ.get("RADAR_CONFIG"),
        DEFAULT_CONFIG_PATH,
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "config.yaml"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    return DEFAULT_CONFIG_PATH


def load_radar_config(config_path: Optional[str] = None) -> RadarConfig:
    """Load configuration from YAML file and apply environment variable overrides."""
    resolved_path = _find_config_file(config_path)
    data: Dict[str, Any] = {}

    if os.path.exists(resolved_path):
        try:
            with open(resolved_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            logger.debug("Loaded config from %s", resolved_path)
        except Exception as exc:
            logger.warning("Failed to parse config YAML at %s: %s. Using defaults.", resolved_path, exc)
    else:
        logger.debug("Config file %s not found. Using defaults.", resolved_path)

    # 1. Tracks
    tracks_raw = data.get("tracks", {})
    tracks = TrackConfig(
        internship_include=tracks_raw.get("internship_include", []),
        engineer_include=tracks_raw.get("engineer_include", []),
        seniority_exclude=tracks_raw.get("seniority_exclude", []),
        borderline_review=tracks_raw.get("borderline_review", []),
    )

    # 2. Geography
    geo_raw = data.get("geography", {})
    geography = GeographyConfig(
        allowed_remote_scopes=geo_raw.get("allowed_remote_scopes", ["worldwide", "region_restricted"]),
        allowed_regions=geo_raw.get("allowed_regions", ["Worldwide", "US", "Canada", "Europe", "UK", "Germany", "APAC"]),
        rejected_scopes=geo_raw.get("rejected_scopes", ["hybrid", "onsite"]),
    )

    # 3. Classifier
    clf_raw = data.get("classifier", {})
    classifier = ClassifierConfig(
        enabled=clf_raw.get("enabled", True),
        provider=os.environ.get("CLASSIFIER_PROVIDER", clf_raw.get("provider", "gemini")),
        model=os.environ.get("CLASSIFIER_MODEL", clf_raw.get("model", "gemini-3.6-flash")),
        min_relevance_score=int(os.environ.get("MIN_RELEVANCE_SCORE", clf_raw.get("min_relevance_score", 60))),
        cache_file=clf_raw.get("cache_file", "state/classifier_cache.json"),
    )

    # 4. Email
    email_raw = data.get("email", {})
    email = EmailConfig(
        send_empty_digests=bool(email_raw.get("send_empty_digests", False)),
        show_visa_tag=bool(email_raw.get("show_visa_tag", True)),
        subject_template=email_raw.get(
            "subject_template",
            "🧠 {total_count} new AI roles today ({intern_count} internships, {eng_count} engineer)",
        ),
    )

    # 5. Sources
    sources_raw = data.get("sources", {})
    sources = SourcesConfig(
        company_files=sources_raw.get("company_files", ["ai_companies.json", "companies.json", "remote_companies.json"]),
        enable_public_apis=bool(sources_raw.get("enable_public_apis", True)),
        public_apis=sources_raw.get("public_apis", {
            "remoteok": True,
            "remotive": True,
            "arbeitnow": True,
            "himalayas": True,
            "hn_hiring": True,
        }),
    )

    # 6. Resume fetch config
    resume_raw = data.get("resume", {})
    resume = ResumeConfig(
        doc_id=os.environ.get("RESUME_DOC_ID", resume_raw.get("doc_id", "")),
        access_method=resume_raw.get("access_method", "link_shared"),
    )

    # 7. Freshness filter config
    freshness_raw = data.get("freshness", {})
    freshness = FreshnessConfig(
        max_age_days=int(freshness_raw.get("max_age_days", 5)),
    )

    # 8. Supabase dedup config
    supabase_raw = data.get("supabase", {})
    supabase = SupabaseConfig(
        table_name=supabase_raw.get("table_name", "sent_jobs"),
        enabled=bool(supabase_raw.get("enabled", True)),
    )

    # 9. Resume matcher config
    rm_raw = data.get("resume_matcher", {})
    resume_matcher = ResumeMatcherConfig(
        enabled=bool(rm_raw.get("enabled", True)),
        model=os.environ.get("RESUME_MATCHER_MODEL", rm_raw.get("model", "gemini-3.7-flash")),
        fallback_model=rm_raw.get("fallback_model", "gemini-3.6-flash"),
        cache_file=rm_raw.get("cache_file", "state/resume_match_cache.json"),
    )

    # 10. Search grounding config
    sg_raw = data.get("search_grounding", {})
    search_grounding = SearchGroundingConfig(
        enabled=bool(sg_raw.get("enabled", True)),
        model=os.environ.get("SEARCH_GROUNDING_MODEL", sg_raw.get("model", "gemini-3.7-flash")),
        fallback_model=sg_raw.get("fallback_model", "gemini-3.6-flash"),
        thinking_level=sg_raw.get("thinking_level", "HIGH"),
        run_hours_utc=sg_raw.get("run_hours_utc", [3, 15]),
        force_run=bool(sg_raw.get("force_run", False)),
    )

    # 11. Visa config
    visa_raw = data.get("visa", {})
    weights_raw = visa_raw.get("weights", {})
    from job_radar.config.models import DedupConfig, VisaConfig, VisaWeightsConfig
    visa = VisaConfig(
        enabled=bool(visa_raw.get("enabled", True)),
        min_score_to_tag=float(visa_raw.get("min_score_to_tag", 0.55)),
        drop_if_status=visa_raw.get("drop_if_status", []),
        show_unknown=bool(visa_raw.get("show_unknown", True)),
        weights=VisaWeightsConfig(
            registry=float(weights_raw.get("registry", 0.50)),
            llm=float(weights_raw.get("llm", 0.35)),
            keyword=float(weights_raw.get("keyword", 0.15)),
        ),
    )

    # 12. Dedup config
    dedup_raw = data.get("dedup", {})
    dedup = DedupConfig(
        title_synonyms=dedup_raw.get("title_synonyms", {
            "internship": "intern",
            "machine learning": "ml",
            "artificial intelligence": "ai",
            "deep learning": "dl",
        }),
        company_suffixes=dedup_raw.get("company_suffixes", [
            "inc", "incorporated", "corp", "corporation", "llc", "ltd", "limited", "gmbh", "co", "technologies", "technology", "labs", "pbc"
        ]),
        remote_terms=dedup_raw.get("remote_terms", [
            "remote", "anywhere", "worldwide", "work from home", "virtual"
        ]),
    )

    return RadarConfig(
        tracks=tracks,
        geography=geography,
        classifier=classifier,
        email=email,
        sources=sources,
        resume=resume,
        freshness=freshness,
        supabase=supabase,
        resume_matcher=resume_matcher,
        search_grounding=search_grounding,
        visa=visa,
        dedup=dedup,
    )


_GLOBAL_CONFIG: Optional[RadarConfig] = None


def get_config(reload: bool = False) -> RadarConfig:
    """Singleton getter for RadarConfig."""
    global _GLOBAL_CONFIG
    if _GLOBAL_CONFIG is None or reload:
        _GLOBAL_CONFIG = load_radar_config()
    return _GLOBAL_CONFIG
