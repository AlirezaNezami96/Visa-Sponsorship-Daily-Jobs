"""
PDF generation service using WeasyPrint + Jinja2.

Converts structured resume/cover letter data into polished, ATS-safe PDFs.
Files are stored in the configured output directory with a UUID-based name.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from engine.api.config import get_settings
from engine.api.models import GeminiResumeOutput

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _get_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,
    )


def _ensure_output_dir() -> Path:
    out = Path(get_settings().pdf_output_dir)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _render_html(template_name: str, context: dict) -> str:
    env = _get_jinja_env()
    template = env.get_template(template_name)
    return template.render(**context)


def _html_to_pdf(html: str, output_path: str) -> None:
    """Convert HTML string to PDF using WeasyPrint."""
    try:
        from weasyprint import HTML  # type: ignore
        HTML(string=html).write_pdf(output_path)
        logger.debug("PDF written to %s", output_path)
    except ImportError:
        # Fallback: write HTML as-is (for dev environments without WeasyPrint system deps)
        logger.warning("WeasyPrint not available — saving as .html fallback")
        html_path = output_path.replace(".pdf", ".html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        raise RuntimeError(
            "WeasyPrint is not installed. Run: pip install weasyprint"
        ) from None


def generate_signed_token(doc_id: str) -> str:
    """
    Generate a short HMAC token for authenticated PDF download URLs.
    Prevents enumeration of other users' documents.
    """
    secret = get_settings().session_secret.encode()
    sig = hmac.new(secret, doc_id.encode(), hashlib.sha256).hexdigest()[:16]
    return sig


def generate_resume_pdf(
    resume_output: GeminiResumeOutput,
    session_id: str,
    company_name: str,
    job_title: str,
) -> tuple[str, str, str]:
    """
    Generate a polished resume PDF from the Gemini output.

    Returns:
        (doc_id, pdf_path, rendered_html_preview)
    """
    doc_id = str(uuid.uuid4())
    out_dir = _ensure_output_dir() / session_id
    out_dir.mkdir(parents=True, exist_ok=True)

    context = {
        "resume": resume_output.rewritten_resume.model_dump(),
        "company_name": company_name,
        "job_title": job_title,
        "generated_at": time.strftime("%B %d, %Y"),
    }

    html = _render_html("resume.html", context)
    pdf_path = str(out_dir / f"{doc_id}.pdf")

    _html_to_pdf(html, pdf_path)
    logger.info("Resume PDF generated: %s (%s at %s)", doc_id, job_title, company_name)

    return doc_id, pdf_path, html


def generate_cover_letter_pdf(
    letter_body: str,
    user_name: str,
    company_name: str,
    job_title: str,
    session_id: str,
) -> tuple[str, str, str]:
    """
    Generate a polished cover letter PDF.

    Returns:
        (doc_id, pdf_path, rendered_html_preview)
    """
    doc_id = str(uuid.uuid4())
    out_dir = _ensure_output_dir() / session_id
    out_dir.mkdir(parents=True, exist_ok=True)

    context = {
        "letter_body": letter_body,
        "user_name": user_name,
        "company_name": company_name,
        "job_title": job_title,
        "generated_at": time.strftime("%B %d, %Y"),
    }

    html = _render_html("cover_letter.html", context)
    pdf_path = str(out_dir / f"{doc_id}.pdf")

    _html_to_pdf(html, pdf_path)
    logger.info("Cover letter PDF generated: %s (%s at %s)", doc_id, job_title, company_name)

    return doc_id, pdf_path, html


def get_pdf_path(session_id: str, doc_id: str) -> Optional[Path]:
    """Return the full path to a generated PDF, or None if it doesn't exist."""
    out_dir = _ensure_output_dir() / session_id
    pdf_path = out_dir / f"{doc_id}.pdf"
    if pdf_path.exists():
        return pdf_path
    # Fallback: check for HTML (dev mode)
    html_path = out_dir / f"{doc_id}.html"
    if html_path.exists():
        return html_path
    return None


def cleanup_old_pdfs() -> int:
    """Delete PDFs older than the configured TTL. Returns count of deleted files."""
    ttl = get_settings().pdf_ttl_seconds
    out_dir = _ensure_output_dir()
    now = time.time()
    deleted = 0
    for session_dir in out_dir.iterdir():
        if session_dir.is_dir():
            for f in session_dir.glob("*"):
                if (now - f.stat().st_mtime) > ttl:
                    f.unlink(missing_ok=True)
                    deleted += 1
            # Remove empty session dirs
            try:
                session_dir.rmdir()
            except OSError:
                pass
    logger.info("PDF cleanup: removed %d old files.", deleted)
    return deleted
