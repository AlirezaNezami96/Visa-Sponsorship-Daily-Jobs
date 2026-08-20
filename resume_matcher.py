"""Resume Matcher (Root Compatibility Facade)."""
from job_radar.resume.matcher import (
    RESUME_MATCH_SYSTEM_PROMPT,
    match_resume_batch,
    match_resume_to_job,
)

__all__ = [
    "RESUME_MATCH_SYSTEM_PROMPT",
    "match_resume_to_job",
    "match_resume_batch",
]
