"""Internal document-render endpoint for the Supabase Edge Functions.

After the Edge Function's AI waterfall produces validated structured JSON, it
calls this endpoint to assemble deterministic documents:
- DOCX (python-docx — primary ATS format for resumes)
- PDF (fpdf2 — secondary preview format)
Uploads them to Supabase Storage (`users/{uid}/jobs/{job_id}/{type}/{document_id}.[docx|pdf]`),
records `generated_documents.file_path`, and returns storage paths.

Auth: shared secret header `x-internal-key` (env INTERNAL_API_KEY).
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from .config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["Internal"])

USERS_BUCKET = "users"


class DocumentRenderRequest(BaseModel):
    user_id: str
    job_id: Optional[str] = None
    document_id: Optional[str] = None
    document_type: str  # resume | cover_letter
    format_type: str = "professional"
    output_json: dict[str, Any] = {}
    profile: dict[str, Any] = {}
    job: dict[str, Any] = {}


def _load_builders():
    """Load docx_builder and pdf_builder safely."""
    try:
        from job_radar.ai import docx_builder, pdf_builder
        return docx_builder, pdf_builder
    except ImportError:
        import importlib.util

        repo_root = Path(__file__).resolve().parents[2]
        pdf_path = repo_root / "src" / "job_radar" / "ai" / "pdf_builder.py"
        docx_path = repo_root / "src" / "job_radar" / "ai" / "docx_builder.py"

        spec_pdf = importlib.util.spec_from_file_location("visalane_pdf_builder", pdf_path)
        if spec_pdf is None or spec_pdf.loader is None:
            raise HTTPException(status_code=500, detail=f"pdf_builder not found at {pdf_path}")
        mod_pdf = importlib.util.module_from_spec(spec_pdf)
        spec_pdf.loader.exec_module(mod_pdf)

        spec_docx = importlib.util.spec_from_file_location("visalane_docx_builder", docx_path)
        if spec_docx is None or spec_docx.loader is None:
            raise HTTPException(status_code=500, detail=f"docx_builder not found at {docx_path}")
        mod_docx = importlib.util.module_from_spec(spec_docx)
        spec_docx.loader.exec_module(mod_docx)

        return mod_docx, mod_pdf


def _supabase_headers(settings) -> dict[str, str]:
    return {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }


def _upload_to_storage(settings, path: str, data: bytes, content_type: str) -> bool:
    url = f"{settings.supabase_url}/storage/v1/object/{USERS_BUCKET}/{path}"
    headers = {
        **_supabase_headers(settings),
        "Content-Type": content_type,
        "x-upsert": "true",
    }
    resp = httpx.post(url, content=data, headers=headers, timeout=60)
    if resp.status_code in (200, 201):
        return True
    logger.error("document upload failed (%d) for %s: %s", resp.status_code, path, resp.text[:300])
    return False


def _update_document_row(settings, document_id: str, file_path: str, size: int) -> None:
    url = f"{settings.supabase_url}/rest/v1/generated_documents"
    headers = {
        **_supabase_headers(settings),
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    resp = httpx.patch(
        url,
        params={"id": f"eq.{document_id}"},
        json={"file_path": file_path, "file_size": size},
        headers=headers,
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        logger.warning("generated_documents update failed (%d): %s", resp.status_code, resp.text[:300])


@router.post("/documents/render")
async def render_document(req: DocumentRenderRequest, x_internal_key: str = Header(default="")):
    settings = get_settings()
    if not settings.internal_api_key or x_internal_key != settings.internal_api_key:
        raise HTTPException(status_code=401, detail="invalid x-internal-key")
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="supabase storage not configured")

    docx_builder, pdf_builder = _load_builders()
    document_id = req.document_id or str(uuid.uuid4())
    job_part = req.job_id or "no-job"

    pdf_bytes: Optional[bytes] = None
    docx_bytes: Optional[bytes] = None
    docx_path: Optional[str] = None

    if req.document_type == "resume":
        format_type = req.format_type or "professional"
        docx_bytes = docx_builder.build_resume_docx(req.profile, req.output_json, format_type=format_type)
        pdf_bytes = pdf_builder.build_resume_pdf(req.profile, req.output_json, format_type=format_type)
    elif req.document_type == "cover_letter":
        pdf_bytes = pdf_builder.build_cover_letter_pdf(req.profile, req.output_json, req.job)
    else:
        raise HTTPException(status_code=400, detail=f"unsupported document_type: {req.document_type}")

    pdf_path = f"{req.user_id}/jobs/{job_part}/{req.document_type}/{document_id}.pdf"
    if pdf_bytes and not _upload_to_storage(settings, pdf_path, pdf_bytes, "application/pdf"):
        raise HTTPException(status_code=502, detail="pdf storage upload failed")

    if docx_bytes:
        docx_path = f"{req.user_id}/jobs/{job_part}/{req.document_type}/{document_id}.docx"
        _upload_to_storage(
            settings,
            docx_path,
            docx_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    if pdf_bytes:
        _update_document_row(settings, document_id, pdf_path, len(pdf_bytes))

    return {
        "document_id": document_id,
        "storage_path": pdf_path,
        "docx_path": docx_path,
        "bucket": USERS_BUCKET,
        "file_size": len(pdf_bytes) if pdf_bytes else len(docx_bytes or b""),
    }
