"""Jobs subpackage — skill extractor, matcher, scorer, and cache."""
from job_radar.jobs.cache import MatchScoreCache, get_match_score_cache
from job_radar.jobs.matcher import (
    GOOD_MATCH_THRESHOLD,
    MATCH_CACHE_TTL,
    MATCH_LABEL_THRESHOLD,
    purge_stale_scores,
    read_cached_scores,
    score_jobs_for_profile,
    write_match_scores,
)
from job_radar.jobs.scorer import (
    compute_match_score,
    score_experience_level,
    score_location_preference,
    score_skills_overlap,
    score_title_relevance,
    score_visa_sponsorship,
)
from job_radar.jobs.skill_extractor import (
    extract_skills_from_job,
    extract_skills_rule_based,
    extraction_confidence,
)

__all__ = [
    "extract_skills_from_job",
    "extract_skills_rule_based",
    "extraction_confidence",
    "score_jobs_for_profile",
    "write_match_scores",
    "read_cached_scores",
    "purge_stale_scores",
    "MATCH_LABEL_THRESHOLD",
    "GOOD_MATCH_THRESHOLD",
    "MATCH_CACHE_TTL",
    "compute_match_score",
    "score_title_relevance",
    "score_skills_overlap",
    "score_experience_level",
    "score_visa_sponsorship",
    "score_location_preference",
    "MatchScoreCache",
    "get_match_score_cache",
]
