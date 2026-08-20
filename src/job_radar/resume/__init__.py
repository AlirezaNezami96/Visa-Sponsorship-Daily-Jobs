"""Resume subpackage — fetch and ATS matching."""
from job_radar.resume.fetch import fetch_resume_text
from job_radar.resume.matcher import RESUME_MATCH_SYSTEM_PROMPT, match_resume_to_job

__all__ = [
    "fetch_resume_text",
    "match_resume_to_job",
    "RESUME_MATCH_SYSTEM_PROMPT",
]
