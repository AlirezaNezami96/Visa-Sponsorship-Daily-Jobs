"""Resume subpackage — fetch, ATS matching, universal parser, AI parser, and section detection."""
from job_radar.resume.ai_parser import AIResumeParser, parse_resume_with_ai
from job_radar.resume.fetch import fetch_resume_text
from job_radar.resume.matcher import RESUME_MATCH_SYSTEM_PROMPT, match_resume_to_job
from job_radar.resume.normalizers import normalize_parsed_data
from job_radar.resume.parser import FresherProfile, ResumeParseResult, create_fresher_profile, parse_resume
from job_radar.resume.section_detector import (
    detect_all_sections,
    detect_sections_from_parsed_data,
    detect_sections_from_text,
)
from job_radar.resume.validators import validate_upload

__all__ = [
    # Existing
    "fetch_resume_text",
    "match_resume_to_job",
    "RESUME_MATCH_SYSTEM_PROMPT",
    # Phase 4
    "ResumeParseResult",
    "FresherProfile",
    "parse_resume",
    "create_fresher_profile",
    "validate_upload",
    "normalize_parsed_data",
    "AIResumeParser",
    "parse_resume_with_ai",
    "detect_all_sections",
    "detect_sections_from_text",
    "detect_sections_from_parsed_data",
]
