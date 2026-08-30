"""Main resume parser orchestrator.

Coordinates:
  1. Validation (file size, type, magic bytes, declared MIME)
  2. Text extraction (format-specific extractor)
  3. AI-powered structured parsing (via LLM router)
  4. Data normalization
  5. Content plausibility check (language-aware) + missing-contact warnings
  6. Confidence scoring
  7. Result packaging (ResumeParseResult)

Fallback chain:
  - If AI parsing fails → return partial result from text extraction alone
  - If text extraction yields < 50 chars → OCR attempt, else scanned warning
  - Never raise an exception that reaches the caller — always return a result

Budgets and limits:
  - Whole-parse budget: 30s (PARSER_TIMEOUT_S). On breach the pipeline
    stops and returns a partial result with a retry-suggesting warning.
  - Per-user rate limit: min 5s between parse attempts (parse_rate_limited),
    protecting the AI waterfall and extraction workers from rapid retries.

Fresher detection and conversion:
  - If parsed resume has no experience AND >= 1 education: flag is_fresher.
  - create_fresher_profile(): minimal profile for "I'm a fresher" opt-in.
  - fresher_conversion_update(): field updates that flip a fresher profile
    to a full profile once a real resume was parsed (used by the Edge
    Function / sync layer when persisting).

Persistence contract (resumes + profiles tables):
  - resumes_row()/profile_updates() produce the exact column payloads for
    the new Phase-4 metadata columns (parse_status, parse_confidence,
    parse_warnings, sections_detected, parse_duration_ms, resume_parse_warnings).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .extractors import PdfExtractor, DocxExtractor, TextExtractor
from .normalizers import normalize_parsed_data
from .validators import detect_language, validate_upload, validate_content_plausibility
from .ai_parser import parse_resume_with_ai, build_resume_parse_prompt
from .section_detector import detect_all_sections, detect_sections_from_text, detect_sections_from_parsed_data

logger = logging.getLogger(__name__)

# Confidence factors
_AI_PARSE_CONFIDENCE = 0.90
_NO_AI_CONFIDENCE = 0.40
_SCANNED_CONFIDENCE = 0.10

# Budgets / limits
PARSER_TIMEOUT_S = 30.0           # spec: parse timeout 30s, fail gracefully
PARSE_COOLDOWN_S = 5.0            # min seconds between two parses per user

# Last time each user attempted a parse (monotonic clock). Module-level on
# purpose: single-process in-memory rate limiter for the Python runtime;
# the Edge Function enforces its own per-user quota via usage_limits.
_parse_attempts: dict[str, float] = {}


def parse_rate_limited(user_key: str, now: float | None = None) -> bool:
    """True if `user_key` parsed a resume within the cooldown window."""
    now = time.monotonic() if now is None else now
    last = _parse_attempts.get(user_key)
    return last is not None and (now - last) < PARSE_COOLDOWN_S


def _record_parse_attempt(user_key: str, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    _parse_attempts[user_key] = now


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

    # Language flag (spec: non-English resumes parsed and flagged)
    language: str = "en"
    # True when the 30s budget was breached
    timed_out: bool = False


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
    user_key: str = "",
) -> ResumeParseResult:
    """Parse a resume file end-to-end.

    Args:
        data: Raw file bytes.
        filename: Original filename (used to detect format).
        mime_type: Optional MIME type from upload headers.
        ai_parse: Whether to use AI for structured extraction.
        llm_router: Optional LLM router instance (for DI in tests).
        user_key: Optional per-user key for the parse cooldown (rate limit).

    Returns:
        ResumeParseResult with all extracted data and metadata.
    """
    started = time.monotonic()
    warnings: list[str] = []
    errors: list[str] = []
    timed_out = False

    def _deadline_hit() -> bool:
        return (time.monotonic() - started) > PARSER_TIMEOUT_S

    # ── 0. Rate limit (per user, rapid retries) ───────────────────────────────
    if user_key and parse_rate_limited(user_key):
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
            errors=[
                "You're parsing resumes too quickly. Please wait a few seconds and try again."
            ],
            parse_duration_ms=_elapsed_ms(started),
            file_type=_detect_file_type(filename),
        )
    if user_key:
        _record_parse_attempt(user_key)

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

    if _deadline_hit():
        timed_out = True
        warnings.append(
            "Resume parsing took too long and was stopped. "
            "Your file was saved; please retry to complete parsing."
        )
        return _partial_result(
            raw_text=raw_text,
            parsed_data={},
            started=started,
            file_type=file_type,
            page_count=page_count,
            warnings=warnings,
            timed_out=timed_out,
            is_scanned=is_scanned,
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

    if _deadline_hit() and not ai_used:
        timed_out = True
        warnings.append(
            "Resume parsing took too long and was stopped. "
            "Your file was saved; please retry to complete parsing."
        )

    # ── 4. Normalization ──────────────────────────────────────────────────────
    if parsed_data:
        try:
            parsed_data = normalize_parsed_data(parsed_data)
        except Exception as exc:
            logger.debug("Normalization warning: %s", exc)
            warnings.append(f"Data normalization warning: {exc!s:.80}")

    # ── 5. Content plausibility + language flag + contact warnings ────────────
    language = "en"
    if raw_text:
        language = detect_language(raw_text)
        if language not in ("en", "unknown"):
            warnings.append(
                f"Resume appears to be written in another language ({language}). "
                "Check the extracted details for accuracy."
            )
        ok, plausibility_err = validate_content_plausibility(raw_text)
        if not ok:
            warnings.append(plausibility_err or "Content plausibility check failed")

    if parsed_data:
        contact_warnings = _missing_contact_warnings(parsed_data)
        warnings.extend(contact_warnings)

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

    status = "failed" if errors else ("partial" if not ai_used or is_scanned or timed_out else "completed")

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
        language=language,
        timed_out=timed_out,
    )


def create_fresher_profile() -> FresherProfile:
    """Create a minimal profile for a user who declares no resume."""
    return FresherProfile()


def fresher_conversion_update(result: ResumeParseResult) -> dict[str, Any]:
    """Column updates converting a fresher profile to a full profile.

    Called by the sync layer when a previously-fresher user uploads a
    resume that parses successfully: clears the fresher flags and fills
    the parsed resume snapshot. AI features are re-enabled automatically
    by the DB trigger once parsed_resume is set and is_fresher clears.
    """
    return {
        "is_fresher": False,
        "resume_onboarding_complete": True,
        "parsed_resume": result.parsed_data if result.parsed_data else None,
        "last_resume_parse": _now_iso(),
        "resume_parse_warnings": result.warnings if result.warnings else None,
    }


def resumes_row(result: ResumeParseResult, resume_id: str | None = None) -> dict[str, Any]:
    """Column payload for the resumes table Phase-4 metadata columns."""
    row: dict[str, Any] = {
        "parse_status": result.status,
        "parse_confidence": result.confidence,
        "parse_warnings": result.warnings if result.warnings else None,
        "sections_detected": result.sections_detected if result.sections_detected else None,
        "parse_duration_ms": result.parse_duration_ms,
        "file_type": result.file_type,
    }
    if result.errors:
        row["parse_error"] = "; ".join(result.errors)[:2000]
    if resume_id:
        row["id"] = resume_id
    return row


def profile_updates(result: ResumeParseResult) -> dict[str, Any]:
    """Column payload for profiles.parsed_resume + Phase-4 parse columns."""
    updates: dict[str, Any] = {
        "is_fresher": result.is_fresher,
        "parsed_resume": result.parsed_data if result.parsed_data else None,
        "last_resume_parse": _now_iso(),
        "resume_parse_warnings": result.warnings if result.warnings else None,
    }
    if result.status == "completed" and result.confidence >= 0.8:
        updates["profile_complete"] = True
        updates["resume_onboarding_complete"] = True
    return updates


# ── Internal helpers ──────────────────────────────────────────────────────────

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _partial_result(
    raw_text: str,
    parsed_data: dict[str, Any],
    started: float,
    file_type: str,
    page_count: int,
    warnings: list[str],
    timed_out: bool,
    is_scanned: bool,
) -> ResumeParseResult:
    """Build a partial result (deadline breach / AI unavailable)."""
    return ResumeParseResult(
        raw_text=raw_text,
        parsed_data=parsed_data,
        status="partial",
        confidence=_NO_AI_CONFIDENCE,
        is_scanned=is_scanned,
        is_fresher=False,
        page_count=page_count,
        sections_detected=_detect_sections(parsed_data),
        warnings=warnings,
        errors=[],
        parse_duration_ms=_elapsed_ms(started),
        file_type=file_type,
        timed_out=timed_out,
    )


_MISSING_CONTACT_FIELDS = {
    "email": "No email address was found on your resume.",
    "phone": "No phone number was found on your resume.",
    "full_name": "No name was found at the top of your resume.",
}


def _missing_contact_warnings(parsed_data: dict[str, Any]) -> list[str]:
    """Warn when core contact info is missing from the parsed resume."""
    out = []
    for key, message in _MISSING_CONTACT_FIELDS.items():
        value = parsed_data.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            out.append(message)
    return out


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
  }}],
  "volunteer_work": [{{
    "organization": string,
    "role": string|null,
    "description": string|null
  }}],
  "publications": [{{
    "title": string,
    "venue": string|null,
    "year": string|null
  }}],
  "awards": [{{
    "title": string,
    "issuer": string|null,
    "year": string|null
  }}],
  "interests": [string],
  "references": [{{
    "name": string,
    "relationship": string|null,
    "contact": string|null
  }}]
}}

RESUME TEXT:
{raw_text[:12000]}"""


def _detect_fresher(parsed_data: dict[str, Any]) -> bool:
    """Detect if the resume belongs to a fresher (no professional experience)."""
    experience = parsed_data.get("experience") or []
    education = parsed_data.get("education") or []
    return len(experience) == 0 and len(education) >= 1


_SECTION_KEYS = [
    "summary", "experience", "education", "skills", "certifications",
    "projects", "languages", "volunteer_work", "publications", "awards",
    "interests", "references",
]


def _detect_sections(parsed_data: dict[str, Any]) -> list[str]:
    """Return list of detected section names."""
    sections = []
    for key in _SECTION_KEYS:
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
