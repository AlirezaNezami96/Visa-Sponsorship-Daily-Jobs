"""Resume file and content validators.

Validates before any parsing begins:
  - File size bounds (1 KB – 10 MB)
  - MIME type / magic bytes match declared extension
  - File not corrupt (quick structural check)
  - Content plausibility (resume-like content, language-aware)

All validators return (is_valid: bool, error_message: str | None).
"""
from __future__ import annotations

import re

# File size limits
MIN_FILE_BYTES = 1 * 1024          # 1 KB
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB

# Supported MIME types
SUPPORTED_TYPES = {
    "application/pdf": [".pdf"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
    "application/msword": [".doc"],
    "text/plain": [".txt", ".md"],
    "text/rtf": [".rtf"],
    "application/rtf": [".rtf"],
    "application/vnd.oasis.opendocument.text": [".odt"],
}

# Magic bytes per format
MAGIC: dict[str, bytes] = {
    ".pdf": b"%PDF",
    ".docx": b"PK\x03\x04",
    ".doc": b"\xd0\xcf\x11\xe0",
    ".odt": b"PK\x03\x04",
    ".rtf": b"{\\rtf",
}

# Keywords that strongly suggest the file is a resume.
# Includes the most common non-English equivalents so non-English resumes
# are not falsely rejected (spec: "Resume in non-English language — parse
# and flag language", not reject).
_RESUME_KEYWORDS = re.compile(
    r"\b(experience|education|skills|work|employment|university|degree|"
    r"bachelor|master|phd|engineer|developer|manager|analyst|"
    r"resume|cv|curriculum|"
    # German
    r"erfahrung|ausbildung|kenntnisse|studium|universität|abschluss|ingenieur|entwickler|"
    r"lebenslauf|"
    # French
    r"expérience|formation|compétences|diplôme|ingénieur|développeur|"
    # Spanish
    r"experiencia|educación|formación|universidad|título|ingeniero|desarrollador|"
    # Portuguese
    r"experiência|formação|habilidades|engenheiro|"
    # Italian
    r"esperienza|istruzione|formazione|laurea|ingegnere|"
    # Dutch
    r"ervaring|opleiding|vaardigheden|universiteit|"
    # Turkish
    r"deneyim|eğitim|üniversite|mühendis|geliştirici|"
    r"\u00f6zge\u00e7mi\u015f)"
    ,
    re.IGNORECASE | re.UNICODE,
)

# Scripts/languages we can reliably detect cheaply.
_LATIN_RE = re.compile(r"[a-zA-Z]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_CJK_RE = re.compile(r"[\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]")
_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def validate_file_size(data: bytes) -> tuple[bool, str | None]:
    """Check file is within allowed size range."""
    size = len(data)
    if size < MIN_FILE_BYTES:
        return False, (
            f"File is too small ({size} bytes). "
            "Please upload a complete resume file (at least 1 KB)."
        )
    if size > MAX_FILE_BYTES:
        return False, (
            f"File is too large ({size // (1024 * 1024):.1f} MB). "
            "Please upload a resume smaller than 10 MB."
        )
    return True, None


def validate_file_type(data: bytes, filename: str, declared_mime: str | None = None) -> tuple[bool, str | None]:
    """Validate file extension + magic bytes agree, and declared MIME is consistent.

    Args:
        data: File bytes.
        filename: Original filename.
        declared_mime: Content-Type from upload, if available.

    Returns:
        (is_valid, error_message)
    """
    ext = _get_extension(filename)

    # Check supported extension
    all_exts = {ext for exts in SUPPORTED_TYPES.values() for ext in exts}
    if ext not in all_exts:
        return False, (
            f"Unsupported file type '{ext}'. "
            "Please upload a PDF, Word document (.docx/.doc), plain text, RTF, or ODT file."
        )

    # Declared MIME (when provided) must match a MIME mapped to this extension.
    # Unknown MIME strings pass through — browsers send varied types for .txt/.md.
    if declared_mime:
        normalized_mime = declared_mime.split(";")[0].strip().lower()
        expected_exts = SUPPORTED_TYPES.get(normalized_mime)
        if expected_exts is not None and ext not in expected_exts:
            return False, (
                f"The uploaded content type '{normalized_mime}' does not match "
                f"the file extension '{ext}'. Please upload the original file."
            )

    # Magic bytes check
    if ext in MAGIC:
        magic = MAGIC[ext]
        if not data[:len(magic)] == magic:
            return False, (
                f"File extension is '{ext}' but the file content doesn't match. "
                "The file may be corrupted or renamed. Please try again."
            )

    return True, None


def validate_not_empty(data: bytes) -> tuple[bool, str | None]:
    """Reject completely empty files."""
    if not data:
        return False, "File is empty. Please upload a resume file."
    return True, None


def detect_language(text: str) -> str:
    """Detect the dominant language family of extracted text.

    Returns a stable code: 'en' (default for Latin text), 'de', 'fr', 'es',
    'pt', 'it', 'tr', or script-level codes ('cyrillic', 'cjk', 'arabic',
    'devanagari') for non-Latin scripts. Cheap heuristic — sufficient for
    flagging, not for translation.
    """
    if not text or not text.strip():
        return "en"

    sample = text[:4000]
    if _CYRILLIC_RE.search(sample):
        return "cyrillic"
    if _CJK_RE.search(sample):
        return "cjk"
    if _ARABIC_RE.search(sample):
        return "arabic"
    if _DEVANAGARI_RE.search(sample):
        return "devanagari"
    if not _LATIN_RE.search(sample):
        return "unknown"

    lowered = sample.lower()
    # Language-specific stop/markers (cheap and low-false-positive)
    markers = {
        "de": (" der ", " die ", " und ", " mit ", "erfahrung", "kenntnisse", "studium"),
        "fr": (" les ", " des ", " une ", " avec ", "expérience", "compétences"),
        "es": (" los ", " las ", " con ", " para ", "experiencia", "formación"),
        "pt": (" dos ", " das ", " com ", " para ", "experiência", "formação"),
        "it": (" della ", " con ", " per ", "esperienza", "formazione"),
        "tr": (" ve ", " ile ", " deneyim", "eğitim", "üniversite"),
    }
    best_lang, best_count = "en", 0
    for lang, tokens in markers.items():
        count = sum(1 for t in tokens if t in lowered)
        if count > best_count:
            best_lang, best_count = lang, count
    return best_lang


def validate_content_plausibility(text: str) -> tuple[bool, str | None]:
    """Check that extracted text looks like a resume, not a random document.

    A resume must contain at least 2 resume-like keywords (multi-language)
    and have >= 100 chars.
    """
    if len(text.strip()) < 100:
        return False, (
            "The document appears to contain very little text. "
            "If this is a scanned resume, please upload a text-based PDF or DOCX."
        )

    # Count keyword matches
    matches = len(set(w.lower() for w in _RESUME_KEYWORDS.findall(text)))
    if matches < 2:
        return False, (
            "The uploaded file does not appear to be a resume. "
            "Please upload your resume/CV document."
        )

    return True, None


def validate_upload(
    data: bytes,
    filename: str,
    mime_type: str | None = None,
) -> list[str]:
    """Run all pre-parse validations. Returns a list of error messages (empty = OK)."""
    errors: list[str] = []

    ok, err = validate_not_empty(data)
    if not ok:
        errors.append(err or "File is empty")
        return errors  # no point continuing

    ok, err = validate_file_size(data)
    if not ok:
        errors.append(err or "File size error")
        return errors

    ok, err = validate_file_type(data, filename, mime_type)
    if not ok:
        errors.append(err or "File type error")

    return errors


def _get_extension(filename: str) -> str:
    """Return lowercased extension including dot, e.g. '.pdf'."""
    if "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()
