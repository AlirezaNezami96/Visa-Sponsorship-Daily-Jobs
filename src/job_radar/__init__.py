"""Job Radar: Autonomous AI Internship & Early-Career Engineer Remote Job Radar."""

__version__ = "2.0.0"
__author__ = "Alireza Nezami"

from job_radar.config.loader import get_config, load_radar_config
from job_radar.config.models import RadarConfig
from job_radar.filters.matching import is_matching_role, match_track
from job_radar.filters.dedupe import dedupe_radar_jobs
from job_radar.classifiers.relevance import classify_and_filter_jobs
from job_radar.fetchers.pipeline import fetch_companies
from job_radar.notifications.email import send_radar_digest

__all__ = [
    "__version__",
    "__author__",
    "get_config",
    "load_radar_config",
    "RadarConfig",
    "is_matching_role",
    "match_track",
    "dedupe_radar_jobs",
    "classify_and_filter_jobs",
    "fetch_companies",
    "send_radar_digest",
]
