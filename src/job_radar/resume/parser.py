"""Main resume parser orchestrator.

Coordinates:
  1. Validation (file size, type, magic bytes)
  2. Text extraction (format-specific extractor)
  3. AI-powered structured parsing (via LLM router)
  4. Data normalization
  5. Content plausibility check
  6. Confidence scoring
  7. Result packaging (ResumeParseResult)

Fallback chain:
  - If AI parsing fails → return partial result from text extraction alone
  - If text extraction yields < 50 chars → mark as scanned, return warning
  - Never raise an exception that reaches the caller — always return a result

Fresher detection:
  - If user opts in via `is_fresher=True` param: skip parsing, create minimal profile
  - If parsed resume has no experience AND no education: flag as probable fresher
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .extractors import PdfExtractor, DocxExtractor, TextExtractor
from .normalizers import normalize_parsed_data
from .validators import validate_upload, validate_content_plausibility

logger = logging.getLogger(__name__)

# Confidence factors
_AI_PARSE_CONFIDENCE = 0.90
_NO_AI_CONFIDENCE = 0.40
_SCANNED_CONFIDENCE = 0.10


@dataclass
class ResumeParseResult:
    """Result of a resume parse operation."""
    # Core
    raw_text: str
    parsed_data: dict[str, Any]

    # Status
    status: str  # 'completed' | 'partial' | 'failed'
    confidence: float  # 0.0–1.0
    is_scanned: bool
    is_fresher: bool

    # Metadata
    page_count: int
    sections_detected: list[str]
    warnings: list[str]
    errors: list[str]
    parse_duration_ms: int
    file_type: str


@dataclass
class FresherProfile:
    """Minimal profile for a user who declares no resume."""
    is_fresher: bool = True
    profile_complete: bool = False
    resume_onboarding_complete: bool = False
    parsed_data: dict[str, Any] = field(default_factory=lambda: {
        "skills": [],
        "experience": [],
        "education": [],
        "job_titles": [],
    })


def parse_resume(
    data: bytes,
    filename: str,
    mime_type: str | None = None,
    ai_parse: bool = True,
    llm_router: Any = None,
) -> ResumeParseResult:
    """Parse a resume file end-to-end.

    Args:
        data: Raw file bytes.
        filename: Original filename (used to detect format).
        mime_type: Optional MIME type from upload headers.
        ai_parse: Whether to use AI for structured extraction.
        llm_router: Optional LLM router instance (for DI in tests).

    Returns:
        ResumeParseResult with all extracted data and metadata.
    """
    started = time.monotonic()
    warnings: list[str] = []
    errors: list[str] = []

    # ── 1. Validation ─────────────────────────────────────────────────────────
    validation_errors = validate_upload(data, filename, mime_type)
    if validation_errors:
        return ResumeParseResult(
            raw_text="",
            parsed_data={},
            status="failed",
            confidence=0.0,
            is_scanned=False,
            is_fresher=False,
            page_count=0,
            sections_detected=[],
            warnings=[],
            errors=validation_errors,
            parse_duration_ms=_elapsed_ms(started),
            file_type=_detect_file_type(filename),
        )

    file_type = _detect_file_type(filename)

    # ── 2. Text extraction ────────────────────────────────────────────────────
    raw_text = ""
    page_count = 0
    is_scanned = False

    try:
        extraction = _extract_text(data, filename)
        raw_text = extraction.text
        page_count = extraction.page_count
        is_scanned = extraction.is_scanned
        warnings.extend(extraction.warnings)
    except Exception as exc:
        error_msg = _user_error(exc)
        errors.append(error_msg)
        logger.warning("Text extraction failed for %r: %s", filename, exc)
        return ResumeParseResult(
            raw_text="",
            parsed_data={},
            status="failed",
            confidence=0.0,
            is_scanned=False,
            is_fresher=False,
            page_count=0,
            sections_detected=[],
            warnings=warnings,
            errors=errors,
            parse_duration_ms=_elapsed_ms(started),
            file_type=file_type,
        )

    # ── 3. AI parsing ─────────────────────────────────────────────────────────
    parsed_data: dict[str, Any] = {}
    ai_used = False

    if ai_parse and raw_text.strip():
        try:
            parsed_data = _ai_parse_resume(raw_text, llm_router)
            ai_used = True
        except Exception as exc:
            logger.warning("AI parse failed for %r: %s", filename, exc)
            warnings.append(
                "AI-powered parsing was unavailable. Basic information was extracted. "
                "Please review your profile and fill in any missing details."
            )

    # ── 4. Normalization ──────────────────────────────────────────────────────
    if parsed_data:
        try:
            parsed_data = normalize_parsed_data(parsed_data)
        except Exception as exc:
            logger.debug("Normalization warning: %s", exc)
            warnings.append(f"Data normalization warning: {exc!s:.80}")

    # ── 5. Content plausibility ───────────────────────────────────────────────
    if raw_text:
        ok, plausibility_err = validate_content_plausibility(raw_text)
        if not ok:
            warnings.append(plausibility_err or "Content plausibility check failed")

    # ── 6. Confidence scoring ─────────────────────────────────────────────────
    if is_scanned:
        confidence = _SCANNED_CONFIDENCE
    elif ai_used:
        confidence = _AI_PARSE_CONFIDENCE
        # Penalize for missing key sections
        if not parsed_data.get("experience") and not parsed_data.get("education"):
            confidence -= 0.2
        if not parsed_data.get("skills"):
            confidence -= 0.1
    else:
        confidence = _NO_AI_CONFIDENCE

    confidence = max(0.0, min(1.0, confidence))

    # ── 7. Fresher detection ──────────────────────────────────────────────────
    is_fresher = _detect_fresher(parsed_data)

    # ── 8. Section detection ──────────────────────────────────────────────────
    sections = _detect_sections(parsed_data)

    status = "failed" if errors else ("partial" if not ai_used or is_scanned else "completed")

    return ResumeParseResult(
        raw_text=raw_text,
        parsed_data=parsed_data,
        status=status,
        confidence=confidence,
        is_scanned=is_scanned,
        is_fresher=is_fresher,
        page_count=page_count,
        sections_detected=sections,
        warnings=warnings,
        errors=errors,
        parse_duration_ms=_elapsed_ms(started),
        file_type=file_type,
    )


def create_fresher_profile() -> FresherProfile:
    """Create a minimal profile for a user who declares no resume."""
    return FresherProfile()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_text(data: bytes, filename: str):
    """Dispatch to the correct extractor based on file extension."""
    ext = ("." + filename.rsplit(".", 1)[-1]).lower() if "." in filename else ""
    if ext == ".pdf":
        return PdfExtractor().extract(data)
    if ext in (".docx", ".doc"):
        return DocxExtractor().extract(data, filename)
    return TextExtractor().extract(data, filename)


def _ai_parse_resume(raw_text: str, llm_router: Any = None) -> dict[str, Any]:
    """Call the LLM router to extract structured resume data."""
    if llm_router is None:
        from job_radar.llm.router import LLMRouter
        llm_router = LLMRouter()

    prompt = _build_parse_prompt(raw_text)
    result = llm_router.complete_json(prompt)
    if not isinstance(result, dict):
        raise ValueError(f"AI returned non-dict: {type(result)}")
    return result


def _build_parse_prompt(raw_text: str) -> str:
    return f"""Extract structured data from this resume.

HARD RULES:
- Use ONLY facts present in the resume text. NEVER invent information.
- Return ONLY valid JSON, no markdown fences.

Respond with JSON matching this exact shape:
{{
  "full_name": string|null,
  "email": string|null,
  "phone": string|null,
  "location": string|null,
  "linkedin_url": string|null,
  "github_url": string|null,
  "website_url": string|null,
  "summary": string|null,
  "job_titles": [string],
  "skills": [string],
  "experience": [{{
    "company": string,
    "title": string,
    "start": string|null,
    "end": string|null,
    "highlights": [string]
  }}],
  "education": [{{
    "institution": string,
    "degree": string|null,
    "field": string|null,
    "year": string|null,
    "gpa": string|null
  }}],
  "certifications": [{{
    "name": string,
    "issuer": string|null,
    "year": string|null
  }}],
  "projects": [{{
    "name": string,
    "description": string|null,
    "technologies": [string]
  }}],
  "languages": [{{
    "language": string,
    "proficiency": string|null
  }}]
}}

RESUME TEXT:
{raw_text[:12000]}"""


def _detect_fresher(parsed_data: dict[str, Any]) -> bool:
    """Detect if the resume belongs to a fresher (no professional experience)."""
    experience = parsed_data.get("experience") or []
    education = parsed_data.get("education") or []
    return len(experience) == 0 and len(education) >= 1


def _detect_sections(parsed_data: dict[str, Any]) -> list[str]:
    """Return list of detected section names."""
    sections = []
    for key in ["summary", "experience", "education", "skills", "certifications",
                "projects", "languages"]:
        value = parsed_data.get(key)
        if value and (isinstance(value, list) and value or isinstance(value, str) and value.strip()):
            sections.append(key)
    return sections


def _detect_file_type(filename: str) -> str:
    """Return the file type string from filename."""
    if "." not in filename:
        return "unknown"
    return filename.rsplit(".", 1)[-1].lower()


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _user_error(exc: Exception) -> str:
    """Convert an exception to a user-friendly message."""
    # Import error classes
    try:
        from .extractors.pdf_extractor import PdfExtractionError
        if isinstance(exc, PdfExtractionError) and exc.user_message:
            return exc.user_message
    except ImportError:
        pass
    return str(exc)
