"""
FastAPI application entry point.

Defines routes, middleware, startup/shutdown hooks, and rate limiting.
"""
from __future__ import annotations

import hmac

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import get_settings
from .gemini_client import generate_cover_letter, tailor_resume
from .google_docs import fetch_resume_from_google_doc
from .google_drive_docs import clone_and_tailor_doc, is_google_drive_configured
from .models import (
    ATSReport,
    CoverLetterRequest,
    DocumentResponse,
    ErrorResponse,
    GeminiResumeOutput,
    ResumeTailorRequest,
    SessionInitRequest,
    SessionInitResponse,
)
from .pdf_service import (
    cleanup_old_pdfs,
    generate_cover_letter_pdf,
    generate_resume_pdf,
    generate_signed_token,
    get_pdf_path,
    save_raw_pdf_bytes,
)
from .session_store import get_session_store

# ── Logging ───────────────────────────────────────────────────────────────────
settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Rate Limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run startup/shutdown tasks."""
    settings = get_settings()
    logger.info("Starting Job Acquisition Engine API...")
    logger.info(
        "Models: Pro=%s  Flash=%s",
        settings.gemini_pro_model,
        settings.gemini_flash_model,
    )
    # Background cleanup task — removes PDFs older than TTL every hour
    async def _cleanup_loop() -> None:
        while True:
            await asyncio.sleep(3600)
            cleanup_old_pdfs()

    cleanup_task = asyncio.create_task(_cleanup_loop())
    yield
    cleanup_task.cancel()
    logger.info("Engine API shutting down.")


# ── App Factory ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Job Acquisition Engine API",
    description=(
        "AI-powered resume tailoring and cover letter generation. "
        "Powered by Gemini 3.7 Flash with hybrid reasoning."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Session-ID"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _require_session(session_id: str):
    """Validate a session_id and return the session, or raise 401."""
    store = get_session_store()
    session = store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=401,
            detail="Session not found or expired. Please call /session/init again.",
        )
    return session


def _compute_ats_report(output: GeminiResumeOutput) -> ATSReport:
    """Calculate match metrics and estimated ATS score."""
    req = output.ats_keywords.get("required", [])
    pref = output.ats_keywords.get("preferred", [])
    matched = output.matched_keywords
    missing = output.missing_entirely

    total_key = len(req) + len(pref)
    if total_key == 0:
        score = 85
    else:
        req_matched = len([k for k in req if k in matched])
        pref_matched = len([k for k in pref if k in matched])
        req_weight = (req_matched / max(len(req), 1)) * 70
        pref_weight = (pref_matched / max(len(pref), 1)) * 30
        score = int(min(100, max(0, req_weight + pref_weight)))

    return ATSReport(
        required_keywords=req,
        preferred_keywords=pref,
        matched_keywords=matched,
        missing_entirely=missing,
        ats_score_estimate=score,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health_check():
    """Liveness probe. Returns active session count and status."""
    store = get_session_store()
    return {
        "status": "ok",
        "active_sessions": store.count(),
        "version": "1.0.0",
    }


@app.post(
    "/api/v1/session/init",
    response_model=SessionInitResponse,
    tags=["Session"],
)
@limiter.limit("20/hour")
async def session_init(request: Request, body: SessionInitRequest):
    """
    Initialize a session by fetching the master resume from a public Google Doc.
    Returns a session_id to be included in subsequent API calls.
    """
    try:
        resume_text = await fetch_resume_from_google_doc(body.google_doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to fetch Google Doc %s", body.google_doc_id)
        raise HTTPException(status_code=502, detail=f"Could not fetch Google Doc: {exc}")

    store = get_session_store()
    session_id = store.create(resume_text, google_doc_id=body.google_doc_id)

    return SessionInitResponse(
        success=True,
        session_id=session_id,
        resume_char_count=len(resume_text),
        message="Session created. Resume cached for 2 hours.",
    )


@app.post(
    "/api/v1/resume/tailor",
    response_model=DocumentResponse,
    tags=["Resume"],
)
@limiter.limit(f"{settings.rate_limit_per_hour}/hour")
async def tailor_resume_endpoint(request: Request, body: ResumeTailorRequest):
    """
    Tailor the master resume to a specific job description using Gemini.
    Clones into Google Drive with in-place text replacement if configured,
    and returns a direct Google Doc URL + downloadable PDF.
    """
    session = _require_session(body.session_id)
    t0 = time.perf_counter()

    try:
        resume_output = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: tailor_resume(
                resume_text=session.resume_text,
                job_description=body.job_description,
                company_name=body.company_name,
                job_title=body.job_title,
                max_bullet_additions=body.options.max_bullet_additions,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Resume tailoring failed for session %s", body.session_id)
        raise HTTPException(status_code=502, detail=f"AI processing failed: {exc}")

    google_doc_url = None
    preview_html = None
    doc_id = None

    # Strategy 1: Google Docs & Drive API (clones into Drive & exports exact PDF)
    if is_google_drive_configured() and session.google_doc_id:
        try:
            logger.info("Attempting Google Drive cloning for %s...", body.company_name)
            new_doc_id, gdoc_url, pdf_bytes = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: clone_and_tailor_doc(
                    master_doc_id=session.google_doc_id,
                    company_name=body.company_name,
                    job_title=body.job_title,
                    replacements=[],
                ),
            )
            google_doc_url = gdoc_url
            if pdf_bytes:
                doc_id, _pdf_path = save_raw_pdf_bytes(pdf_bytes, session_id=body.session_id)
        except Exception as exc:
            logger.warning("Google Drive clone/export failed (%s), falling back to template engine...", exc)

    # Strategy 2: Built-in PDF generation engine (xhtml2pdf / WeasyPrint)
    if not doc_id:
        try:
            doc_id, _pdf_path, preview_html = generate_resume_pdf(
                resume_output=resume_output,
                session_id=body.session_id,
                company_name=body.company_name,
                job_title=body.job_title,
            )
        except Exception as exc:
            logger.exception("PDF generation failed for session %s", body.session_id)
            raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}")

    store = get_session_store()
    store.add_doc(body.session_id, doc_id)

    token = generate_signed_token(doc_id)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    ats_report = _compute_ats_report(resume_output)

    return DocumentResponse(
        success=True,
        doc_id=doc_id,
        download_url=f"/api/v1/document/{body.session_id}/{doc_id}?token={token}",
        google_doc_url=google_doc_url,
        preview_html=preview_html,
        ats_report=ats_report,
        processing_time_ms=elapsed_ms,
        message=f"Resume tailored with ATS score estimate: {ats_report.ats_score_estimate}%",
    )


@app.post(
    "/api/v1/cover-letter/generate",
    response_model=DocumentResponse,
    tags=["Cover Letter"],
)
@limiter.limit(f"{settings.rate_limit_per_hour}/hour")
async def generate_cover_letter_endpoint(request: Request, body: CoverLetterRequest):
    """
    Generate a human-toned, pain-point-driven cover letter using Gemini 3.7 Flash.
    Returns a download URL for the generated PDF.
    """
    session = _require_session(body.session_id)
    t0 = time.perf_counter()

    try:
        letter_body = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: generate_cover_letter(
                resume_text=session.resume_text,
                job_description=body.job_description,
                company_name=body.company_name,
                job_title=body.job_title,
                user_name=body.user_name,
                tone=body.tone,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Cover letter generation failed for session %s", body.session_id)
        raise HTTPException(status_code=502, detail=f"AI processing failed: {exc}")

    try:
        doc_id, _pdf_path, preview_html = generate_cover_letter_pdf(
            letter_body=letter_body,
            user_name=body.user_name,
            company_name=body.company_name,
            job_title=body.job_title,
            session_id=body.session_id,
        )
    except Exception as exc:
        logger.exception("Cover letter PDF generation failed for session %s", body.session_id)
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}")

    store = get_session_store()
    store.add_doc(body.session_id, doc_id)

    token = generate_signed_token(doc_id)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    return DocumentResponse(
        success=True,
        doc_id=doc_id,
        download_url=f"/api/v1/document/{body.session_id}/{doc_id}?token={token}",
        preview_html=preview_html,
        processing_time_ms=elapsed_ms,
        message="Cover letter generated successfully.",
    )


@app.get("/api/v1/document/{session_id}/{doc_id}", tags=["Documents"])
async def download_document(session_id: str, doc_id: str, token: str):
    """
    Serve a generated PDF for download.
    Requires a valid HMAC token to prevent unauthorized access.
    """
    # Validate HMAC token
    expected_token = generate_signed_token(doc_id)
    if not hmac.compare_digest(token, expected_token):
        raise HTTPException(status_code=403, detail="Invalid or expired download token.")

    # Verify session owns this doc
    store = get_session_store()
    session = store.get(session_id)
    if session is None or doc_id not in session.doc_ids:
        raise HTTPException(status_code=404, detail="Document not found or session expired.")

    pdf_path = get_pdf_path(session_id, doc_id)
    if pdf_path is None:
        raise HTTPException(status_code=404, detail="Document file not found. It may have expired.")

    media_type = "application/pdf" if str(pdf_path).endswith(".pdf") else "text/html"
    filename = f"resume_{doc_id[:8]}.pdf" if "resume" in str(pdf_path) else f"cover_letter_{doc_id[:8]}.pdf"

    return FileResponse(
        path=str(pdf_path),
        media_type=media_type,
        filename=filename,
    )



