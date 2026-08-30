"""PDF text extractor for resume parsing.

Extraction strategy (in order):
  1. pdfminer.six — handles text-based PDFs with best layout fidelity.
  2. pypdf fallback — lighter, handles more encryption variants.
  3. OCR fallback — if both text extractors yield < 50 chars and an OCR
     engine is installed (pytesseract + pdf2image + tesseract binary),
     rasterize and OCR the first pages. When OCR is unavailable the
     result is flagged is_scanned with a clear warning (never crashes).

Hard limits enforced here:
  - Max file size: 10 MB
  - Min text after extraction: 50 chars (else suspected scanned PDF)
  - Password-protected PDFs are detected and rejected immediately.
  - OCR is capped (first 10 pages, 60s budget) so a hostile file can't
    burn unbounded CPU.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
MIN_TEXT_CHARS = 50
MAX_OCR_PAGES = 10
MAX_OCR_SECONDS = 60.0


@dataclass
class ExtractionResult:
    text: str
    page_count: int
    is_scanned: bool
    warnings: list[str]


class PdfExtractionError(Exception):
    """Raised when PDF cannot be parsed."""
    def __init__(self, message: str, user_message: str | None = None):
        super().__init__(message)
        self.user_message = user_message or message


def extract_text_from_pdf(data: bytes) -> ExtractionResult:
    """Extract raw text from PDF bytes.

    Args:
        data: Raw PDF file bytes.

    Returns:
        ExtractionResult with text and metadata.

    Raises:
        PdfExtractionError: On unrecoverable parse failures.
    """
    if len(data) > MAX_FILE_BYTES:
        raise PdfExtractionError(
            f"File size {len(data)} bytes exceeds {MAX_FILE_BYTES} byte limit",
            "Your resume file is too large. Please upload a file smaller than 10 MB.",
        )
    if len(data) < 100:
        raise PdfExtractionError(
            "File too small to be a valid PDF",
            "The uploaded file appears to be empty or corrupted.",
        )

    # Quick header check
    if not data[:5].startswith(b"%PDF"):
        raise PdfExtractionError(
            "File does not have PDF header",
            "The file you uploaded is not a valid PDF. Please check the file and try again.",
        )

    warnings: list[str] = []
    text = ""
    page_count = 0

    # --- Strategy 1: pdfminer.six ---
    try:
        text, page_count = _extract_with_pdfminer(data, warnings)
    except PdfExtractionError:
        raise
    except Exception as exc:
        logger.debug("pdfminer failed (%s), trying pypdf fallback", exc)
        warnings.append(f"Primary extractor failed: {exc!s:.100}")

    # --- Strategy 2: pypdf fallback ---
    if not text.strip():
        try:
            text, page_count = _extract_with_pypdf(data, warnings)
        except PdfExtractionError:
            raise
        except Exception as exc:
            logger.debug("pypdf also failed: %s", exc)
            warnings.append(f"Fallback extractor failed: {exc!s:.100}")

    is_scanned = len(text.strip()) < MIN_TEXT_CHARS

    # --- Strategy 3: OCR fallback for scanned PDFs ---
    if is_scanned:
        ocr_text = _try_ocr(data, warnings)
        if ocr_text.strip():
            text = ocr_text
            is_scanned = False
            warnings.append(
                "This PDF appears to be scanned; text was recovered via OCR. "
                "For best results, upload a text-based PDF or DOCX."
            )

    if is_scanned:
        warnings.append(
            "PDF appears to be scanned (image-only) and no OCR engine is available. "
            "Please upload a text-based PDF or a DOCX version of your resume for best results."
        )

    return ExtractionResult(
        text=text,
        page_count=page_count,
        is_scanned=is_scanned,
        warnings=warnings,
    )


def _try_ocr(data: bytes, warnings: list[str]) -> str:
    """Attempt OCR on a scanned PDF. Returns extracted text ('' on any failure).

    Requires optional deps: pdf2image (poppler) + pytesseract (tesseract).
    Any missing dependency, missing binary, or timeout degrades gracefully
    to the clear-error path.
    """
    import time as _time

    started = _time.monotonic()
    try:
        from pdf2image import convert_from_bytes  # type: ignore[import]
        import pytesseract  # type: ignore[import]
    except ImportError as exc:
        logger.debug("OCR unavailable: %s", exc)
        return ""

    try:
        images = convert_from_bytes(data, first_page=1, last_page=MAX_OCR_PAGES, dpi=200)
    except Exception as exc:
        warnings.append(f"OCR rasterization failed: {exc!s:.80}")
        return ""

    parts: list[str] = []
    for i, img in enumerate(images):
        if _time.monotonic() - started > MAX_OCR_SECONDS:
            warnings.append(f"OCR stopped after {MAX_OCR_SECONDS:.0f}s (page {i + 1}).")
            break
        try:
            parts.append(pytesseract.image_to_string(img))
        except Exception as exc:
            warnings.append(f"OCR page {i + 1} failed: {exc!s:.80}")

    return "\n".join(parts)


def _extract_with_pdfminer(data: bytes, warnings: list[str]) -> tuple[str, int]:
    """Use pdfminer.six for text extraction."""
    try:
        from pdfminer.high_level import extract_text_to_fp  # type: ignore[import]
        from pdfminer.layout import LAParams  # type: ignore[import]
        from pdfminer.pdfpage import PDFPage  # type: ignore[import]
        from pdfminer.pdfparser import PDFSyntaxError  # type: ignore[import]
    except ImportError:
        raise PdfExtractionError("pdfminer.six is not installed")

    try:
        output = io.StringIO()
        with io.BytesIO(data) as fh:
            # Count pages first
            try:
                pages = list(PDFPage.get_pages(fh, check_extractable=True))
                page_count = len(pages)
            except Exception:
                page_count = 0

            fh.seek(0)
            params = LAParams(line_margin=0.5, word_margin=0.1, char_margin=2.0, all_texts=True)
            try:
                extract_text_to_fp(fh, output, laparams=params)
            except PDFSyntaxError as exc:
                if "password" in str(exc).lower() or "encrypted" in str(exc).lower():
                    raise PdfExtractionError(
                        f"PDF is password-protected: {exc}",
                        "This PDF is password-protected. Please remove the password and upload again.",
                    )
                raise

        text = output.getvalue()
        if page_count == 0:
            # Estimate from text
            page_count = max(1, text.count("\x0c") + 1)
        return text, page_count

    except PdfExtractionError:
        raise
    except Exception as exc:
        raise RuntimeError(f"pdfminer extraction failed: {exc}") from exc


def _extract_with_pypdf(data: bytes, warnings: list[str]) -> tuple[str, int]:
    """Use pypdf as fallback extractor."""
    try:
        from pypdf import PdfReader  # type: ignore[import]
        from pypdf.errors import PdfReadError  # type: ignore[import]
    except ImportError:
        raise PdfExtractionError("pypdf is not installed")

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise PdfExtractionError(
                "PDF is encrypted",
                "This PDF is password-protected. Please remove the password and upload again.",
            )
        parts: list[str] = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception as exc:
                warnings.append(f"Page extraction warning: {exc!s:.80}")
        return "\n".join(parts), len(reader.pages)
    except PdfExtractionError:
        raise
    except PdfReadError as exc:
        if "password" in str(exc).lower():
            raise PdfExtractionError(
                f"PDF requires password: {exc}",
                "This PDF is password-protected. Please remove the password and upload again.",
            )
        raise RuntimeError(f"pypdf read error: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"pypdf extraction failed: {exc}") from exc


class PdfExtractor:
    """High-level PDF extractor interface."""

    def extract(self, data: bytes) -> ExtractionResult:
        return extract_text_from_pdf(data)
