"""Centralized configuration loader with YAML and environment variable overrides."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


@dataclass
class TrackConfig:
    internship_include: List[str] = field(default_factory=list)
    engineer_include: List[str] = field(default_factory=list)
    seniority_exclude: List[str] = field(default_factory=list)
    borderline_review: List[str] = field(default_factory=list)


@dataclass
class GeographyConfig:
    allowed_remote_scopes: List[str] = field(
        default_factory=lambda: ["worldwide", "region_restricted"]
    )
    preferred_regions: List[str] = field(
        default_factory=lambda: ["worldwide", "any", "remote", "us", "uk", "ca", "eu"]
    )


@dataclass
class ClassifierConfig:
    enabled: bool = True
    provider: str = "gemini"  # "gemini", "anthropic", "openai"
    model: str = "gemini-3.6-flash"
    min_relevance_score: int = 60
    cache_file: str = "state/classifier_cache.json"


@dataclass
class EmailConfig:
    send_empty_digests: bool = False
    show_visa_tag: bool = True


@dataclass
class SourcesConfig:
    company_files: List[str] = field(
        default_factory=lambda: ["ai_companies.json", "companies.json", "remote_companies.json"]
    )
    enable_public_apis: bool = True
    public_apis: Dict[str, bool] = field(
        default_factory=lambda: {
            "remoteok": True,
            "remotive": True,
            "arbeitnow": True,
            "himalayas": True,
            "hn_hiring": True,
        }
    )


@dataclass
class RadarConfig:
    tracks: TrackConfig = field(default_factory=TrackConfig)
    geography: GeographyConfig = field(default_factory=GeographyConfig)
    classifier: ClassifierConfig = field(default_factory=ClassifierConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)


_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"
_CACHED_CONFIG: Optional[RadarConfig] = None


def _to_bool(val: Any, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def load_radar_config(config_path: str | Path = _DEFAULT_CONFIG_PATH) -> RadarConfig:
    """Load configuration from config.yaml with env var overrides."""
    path = Path(config_path)
    data: Dict[str, Any] = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to parse %s: %s. Using defaults.", path, exc)

    tracks_data = data.get("tracks", {})
    track_cfg = TrackConfig(
        internship_include=tracks_data.get("internship", {}).get("include", []),
        engineer_include=tracks_data.get("engineer", {}).get("include", []),
        seniority_exclude=tracks_data.get("seniority_exclude", []),
        borderline_review=tracks_data.get("borderline_review", []),
    )

    geo_data = data.get("geography", {})
    geo_cfg = GeographyConfig(
        allowed_remote_scopes=geo_data.get("allowed_remote_scopes", ["worldwide", "region_restricted"]),
        preferred_regions=[r.lower() for r in geo_data.get("preferred_regions", ["worldwide", "any"])],
    )

    clf_data = data.get("classifier", {})
    clf_enabled = _to_bool(os.environ.get("CLASSIFIER_ENABLED", clf_data.get("enabled", True)), default=True)
    clf_provider = os.environ.get("CLASSIFIER_PROVIDER", clf_data.get("provider", "gemini")).lower()
    clf_model = os.environ.get("CLASSIFIER_MODEL", clf_data.get("model", "gemini-3.6-flash"))
    clf_min_score = int(os.environ.get("MIN_RELEVANCE_SCORE", clf_data.get("min_relevance_score", 60)))
    clf_cache_file = os.environ.get("CLASSIFIER_CACHE_FILE", clf_data.get("cache_file", "state/classifier_cache.json"))

    clf_cfg = ClassifierConfig(
        enabled=clf_enabled,
        provider=clf_provider,
        model=clf_model,
        min_relevance_score=clf_min_score,
        cache_file=clf_cache_file,
    )

    email_data = data.get("email", {})
    send_empty = _to_bool(os.environ.get("SEND_EMPTY_DIGESTS", email_data.get("send_empty_digests", False)), default=False)
    show_visa = _to_bool(os.environ.get("SHOW_VISA_TAG", email_data.get("show_visa_tag", True)), default=True)

    email_cfg = EmailConfig(
        send_empty_digests=send_empty,
        show_visa_tag=show_visa,
    )

    sources_data = data.get("sources", {})
    enable_public_apis = _to_bool(os.environ.get("ENABLE_PUBLIC_APIS", sources_data.get("enable_public_apis", True)), default=True)
    sources_cfg = SourcesConfig(
        company_files=sources_data.get("company_files", ["ai_companies.json", "companies.json", "remote_companies.json"]),
        enable_public_apis=enable_public_apis,
        public_apis=sources_data.get("public_apis", {
            "remoteok": True,
            "remotive": True,
            "arbeitnow": True,
            "himalayas": True,
            "hn_hiring": True,
        }),
    )

    return RadarConfig(
        tracks=track_cfg,
        geography=geo_cfg,
        classifier=clf_cfg,
        email=email_cfg,
        sources=sources_cfg,
    )


def get_config(reload: bool = False) -> RadarConfig:
    """Singleton getter for RadarConfig."""
    global _CACHED_CONFIG
    if _CACHED_CONFIG is None or reload:
        _CACHED_CONFIG = load_radar_config()
    return _CACHED_CONFIG
