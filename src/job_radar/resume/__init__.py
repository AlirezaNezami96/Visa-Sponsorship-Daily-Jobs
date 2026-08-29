"""Resume subpackage — fetch, ATS matching, and Phase 4 parser."""
from job_radar.resume.fetch import fetch_resume_text
from job_radar.resume.matcher import RESUME_MATCH_SYSTEM_PROMPT, match_resume_to_job
from job_radar.resume.parser import ResumeParseResult, FresherProfile, parse_resume, create_fresher_profile
from job_radar.resume.validators import validate_upload
from job_radar.resume.normalizers import normalize_parsed_data

__all__ = [
    # existing
    "fetch_resume_text",
    "match_resume_to_job",
    "RESUME_MATCH_SYSTEM_PROMPT",
    # phase 4
    "ResumeParseResult",
    "FresherProfile",
    "parse_resume",
    "create_fresher_profile",
    "validate_upload",
    "normalize_parsed_data",
]
