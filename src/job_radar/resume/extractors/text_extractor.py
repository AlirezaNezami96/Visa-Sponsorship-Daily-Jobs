"""Plain text, RTF, and ODT extractor for resume parsing.

Handles:
  - .txt: direct UTF-8/latin-1 decode with BOM stripping
  - .rtf: strip RTF control words to expose plain text
  - .odt: ODT is zip-based; extract content.xml and strip XML tags
"""
from __future__ import annotations

import logging
import re
import zipfile

from .pdf_extractor import ExtractionResult, MAX_FILE_BYTES, PdfExtractionError

logger = logging.getLogger(__name__)

# RTF control word pattern
_RTF_CONTROL_RE = re.compile(r"\\[a-z]+\d*\s?|[{}]|\\\n|\\\\|\\'[0-9a-fA-F]{2}")
# RTF header
_RTF_SIGNATURE = b"{\\rtf"


class TextExtractionError(PdfExtractionError):
    """Raised when text/RTF/ODT extraction fails."""


def extract_text_from_txt(data: bytes) -> ExtractionResult:
    """Extract text from a plain-text file."""
    if len(data) > MAX_FILE_BYTES:
        raise TextExtractionError(
            f"File size {len(data)} exceeds limit",
            "Your resume file is too large. Please upload a file smaller than 10 MB.",
        )
    # Try UTF-8 first, then latin-1 (never fails)
    try:
        text = data.decode("utf-8-sig")  # strips BOM if present
    except UnicodeDecodeError:
        text = data.decode("latin-1", errors="replace")

    warnings: list[str] = []
    if len(text.strip()) < 50:
        warnings.append("Very little text found in the plain-text file.")

    return ExtractionResult(text=text, page_count=1, is_scanned=False, warnings=warnings)


def extract_text_from_rtf(data: bytes) -> ExtractionResult:
    """Extract plain text from an RTF file."""
    if len(data) > MAX_FILE_BYTES:
        raise TextExtractionError(
            f"File size {len(data)} exceeds limit",
            "Your resume file is too large. Please upload a file smaller than 10 MB.",
        )
    if not data[:5].startswith(_RTF_SIGNATURE):
        raise TextExtractionError(
            "File does not have RTF signature",
            "The uploaded file does not appear to be a valid RTF document.",
        )

    warnings: list[str] = []
    try:
        raw = data.decode("latin-1", errors="replace")
    except Exception as exc:
        raise TextExtractionError(f"RTF decode error: {exc}") from exc

    # Try striprtf library first (better quality)
    try:
        from striprtf.striprtf import rtf_to_text  # type: ignore[import]
        text = rtf_to_text(raw)
    except ImportError:
        # Fallback: naive RTF stripping
        text = _strip_rtf_naive(raw)
        warnings.append("Using basic RTF parser. Install 'striprtf' for better accuracy.")
    except Exception as exc:
        logger.debug("striprtf error: %s", exc)
        text = _strip_rtf_naive(raw)
        warnings.append(f"RTF parse warning: {exc!s:.80}")

    return ExtractionResult(text=text, page_count=1, is_scanned=False, warnings=warnings)


def _strip_rtf_naive(rtf: str) -> str:
    """Naive RTF-to-text: strip control words and braces."""
    text = _RTF_CONTROL_RE.sub("", rtf)
    # Convert \\par and \\line to newlines
    text = re.sub(r"\\par\b", "\n", text)
    text = re.sub(r"\\line\b", "\n", text)
    # Collapse whitespace
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def extract_text_from_odt(data: bytes) -> ExtractionResult:
    """Extract plain text from an ODT (OpenDocument Text) file."""
    if len(data) > MAX_FILE_BYTES:
        raise TextExtractionError(
            f"File size {len(data)} exceeds limit",
            "Your resume file is too large. Please upload a file smaller than 10 MB.",
        )

    warnings: list[str] = []

    try:
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if "content.xml" not in zf.namelist():
                raise TextExtractionError(
                    "ODT missing content.xml",
                    "The ODT file appears to be corrupted. Please try a different format.",
                )
            content_xml = zf.read("content.xml").decode("utf-8", errors="replace")
    except zipfile.BadZipFile:
        raise TextExtractionError(
            "ODT is not a valid zip archive",
            "The ODT file appears to be corrupted. Please try converting to PDF or DOCX.",
        )

    # Strip XML tags
    text = re.sub(r"<[^>]+>", " ", content_xml)
    # Decode XML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&apos;", "'").replace("&quot;", '"')
    # Normalize whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    if len(text) < 50:
        warnings.append("Very little text extracted from the ODT file.")

    return ExtractionResult(text=text, page_count=1, is_scanned=False, warnings=warnings)


class TextExtractor:
    """High-level plain-text / RTF / ODT extractor interface."""

    def extract(self, data: bytes, filename: str = "resume.txt") -> ExtractionResult:
        lower = filename.lower()
        if lower.endswith(".rtf"):
            return extract_text_from_rtf(data)
        if lower.endswith(".odt"):
            return extract_text_from_odt(data)
        return extract_text_from_txt(data)
