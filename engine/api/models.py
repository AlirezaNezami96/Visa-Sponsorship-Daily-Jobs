"""
Pydantic schemas for all API request and response bodies.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl


# ── Requests ─────────────────────────────────────────────────────────────────


class SessionInitRequest(BaseModel):
    """Initialize a session by providing a Google Doc ID for the master resume."""
    google_doc_id: str = Field(
        ...,
        description="Google Doc ID of the master resume (doc must be publicly viewable).",
        min_length=10,
        examples=["1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"],
    )


class ResumeOptions(BaseModel):
    ats_mode: bool = Field(True, description="Optimize output for ATS parsers.")
    max_bullet_additions: int = Field(3, ge=0, le=5)
    preserve_dates: bool = True


class ResumeTailorRequest(BaseModel):
    """Tailor the master resume to a specific job description."""
    session_id: str = Field(..., description="Session ID returned from /session/init.")
    job_description: str = Field(
        ..., min_length=100, max_length=16000,
        description="Full text of the job description.",
    )
    job_url: Optional[str] = None
    company_name: str = Field(..., min_length=1, max_length=200)
    job_title: str = Field(..., min_length=1, max_length=200)
    options: ResumeOptions = Field(default_factory=ResumeOptions)


class CoverLetterRequest(BaseModel):
    """Generate a human-toned cover letter for a specific job."""
    session_id: str = Field(..., description="Session ID returned from /session/init.")
    job_description: str = Field(..., min_length=100, max_length=16000)
    job_url: Optional[str] = None
    company_name: str = Field(..., min_length=1, max_length=200)
    job_title: str = Field(..., min_length=1, max_length=200)
    user_name: str = Field(..., min_length=1, max_length=200)
    tone: str = Field("professional", pattern="^(professional|casual|startup)$")


# ── Responses ─────────────────────────────────────────────────────────────────


class SessionInitResponse(BaseModel):
    success: bool
    session_id: str
    resume_char_count: int
    message: str


class ATSReport(BaseModel):
    required_keywords: List[str] = []
    preferred_keywords: List[str] = []
    matched_keywords: List[str] = []
    missing_entirely: List[str] = []
    ats_score_estimate: int = Field(0, ge=0, le=100)


class DocumentResponse(BaseModel):
    success: bool
    doc_id: str
    download_url: str
    google_doc_url: Optional[str] = None
    preview_html: Optional[str] = None
    ats_report: Optional[ATSReport] = None
    processing_time_ms: int
    message: str = ""


class ErrorResponse(BaseModel):
    success: bool = False
    error_code: str
    message: str
    retry: bool = False


# ── Internal (Gemini output schemas) ──────────────────────────────────────────


class ContactInfo(BaseModel):
    email: str = ""
    linkedin: str = ""
    github: str = ""
    phone: str = ""
    location: str = ""


class ExperienceEntry(BaseModel):
    company: str
    title: str
    dates: str
    location: str = ""
    bullets: List[str]


class SkillsSection(BaseModel):
    primary: List[str] = []
    secondary: List[str] = []
    languages: List[str] = []


class ProjectEntry(BaseModel):
    name: str
    description: str
    tech: List[str] = []
    url: str = ""


class RewrittenResume(BaseModel):
    name: str
    contact: ContactInfo
    summary: str = ""
    experience: List[ExperienceEntry]
    education: List[Dict[str, Any]] = []
    skills: SkillsSection
    projects: List[ProjectEntry] = []


class GeminiResumeOutput(BaseModel):
    ats_keywords: Dict[str, List[str]]
    matched_keywords: List[str]
    missing_entirely: List[str]
    rewritten_resume: RewrittenResume
