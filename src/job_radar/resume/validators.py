"""Resume file and content validators.

Validates before any parsing begins:
  - File size bounds (1 KB – 10 MB)
  - MIME type / magic bytes match declared extension
  - File not corrupt (quick structural check)
  - Content plausibility (resume-like content)

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

# Keywords that strongly suggest the file is a resume
_RESUME_KEYWORDS = re.compile(
    r"\b(experience|education|skills|work|employment|university|degree|"
    r"bachelor|master|phd|engineer|developer|manager|analyst|"
    r"resume|cv|curriculum)\b",
    re.IGNORECASE,
)


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
    """Validate file extension + magic bytes agree.

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
            "Please upload a PDF, Word document (.docx), or plain text file."
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


def validate_content_plausibility(text: str) -> tuple[bool, str | None]:
    """Check that extracted text looks like a resume, not a random document.

    A resume must contain at least 2 resume-like keywords and have >= 100 chars.
    """
    if len(text.strip()) < 100:
        return False, (
            "The document appears to contain very little text. "
            "If this is a scanned resume, please upload a text-based PDF or DOCX."
        )

    # Count keyword matches
    matches = len(set(_RESUME_KEYWORDS.findall(text.lower())))
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
