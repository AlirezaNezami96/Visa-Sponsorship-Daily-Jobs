"""Dataclass models for Radar configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class TrackConfig:
    internship_include: List[str] = field(default_factory=list)
    engineer_include: List[str] = field(default_factory=list)
    seniority_exclude: List[str] = field(default_factory=list)
    borderline_review: List[str] = field(default_factory=list)


SeniorityRules = TrackConfig


@dataclass
class GeographyConfig:
    allowed_remote_scopes: List[str] = field(default_factory=lambda: ["worldwide", "region_restricted"])
    allowed_regions: List[str] = field(default_factory=lambda: ["Worldwide", "US", "Canada", "Europe", "UK", "Germany", "APAC"])
    rejected_scopes: List[str] = field(default_factory=lambda: ["hybrid", "onsite"])


@dataclass
class ClassifierConfig:
    enabled: bool = True
    provider: str = "gemini"
    model: str = "gemini-3.6-flash"
    min_relevance_score: int = 60
    cache_file: str = "state/classifier_cache.json"


@dataclass
class EmailConfig:
    send_empty_digests: bool = False
    show_visa_tag: bool = True
    subject_template: str = "🧠 {total_count} new AI roles today ({intern_count} internships, {eng_count} engineer)"


@dataclass
class SourcesConfig:
    company_files: List[str] = field(default_factory=lambda: ["ai_companies.json", "companies.json", "remote_companies.json"])
    enable_public_apis: bool = True
    public_apis: Dict[str, bool] = field(default_factory=lambda: {
        "remoteok": True,
        "remotive": True,
        "arbeitnow": True,
        "himalayas": True,
        "hn_hiring": True,
    })


@dataclass
class RadarConfig:
    tracks: TrackConfig = field(default_factory=TrackConfig)
    geography: GeographyConfig = field(default_factory=GeographyConfig)
    classifier: ClassifierConfig = field(default_factory=ClassifierConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)
