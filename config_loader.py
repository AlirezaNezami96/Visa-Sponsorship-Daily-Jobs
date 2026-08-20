"""Configuration loader (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.config.loader import get_config, load_radar_config
from job_radar.config.models import (
    ClassifierConfig,
    EmailConfig,
    RadarConfig,
    SeniorityRules,
    SourcesConfig,
    TrackConfig,
)

__all__ = [
    "TrackConfig",
    "SeniorityRules",
    "SourcesConfig",
    "ClassifierConfig",
    "EmailConfig",
    "RadarConfig",
    "load_radar_config",
    "get_config",
]
