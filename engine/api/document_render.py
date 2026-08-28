"""Internal document-render endpoint for the Supabase Edge Functions.

After the Edge Function's AI waterfall produces validated structured JSON, it
calls this endpoint to assemble the deterministic PDF (fpdf2 — no AI in
layout), upload it to Supabase Storage
(`users/{uid}/jobs/{job_id}/{type}/{document_id}.pdf`, private bucket), and
record `generated_documents.file_path`. The Edge Function then mints the
signed preview URL for the frontend.

Auth: shared secret header `x-internal-key` (env INTERNAL_API_KEY). Never
exposed to the browser.
"""
from __future__ import annotations

import logging
import uuid
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


def _build_pdf(req: DocumentRenderRequest) -> bytes:
    builder = _load_pdf_builder()
    if req.document_type == "resume":
        return builder.build_resume_pdf(req.profile, req.output_json, format_type=req.format_type or "professional")
    if req.document_type == "cover_letter":
        return builder.build_cover_letter_pdf(req.profile, req.output_json, req.job)
    raise HTTPException(status_code=400, detail=f"unsupported document_type: {req.document_type}")


def _load_pdf_builder():
    """Load job_radar.ai.pdf_builder without importing the full job_radar chain.

    The engine container ships only the pdf_builder module + bundled fonts, so
    the heavy pipeline package (feedparser/apify/etc.) must not be imported.
    """
    try:
        from job_radar.ai import pdf_builder  # full local install

        return pdf_builder
    except ImportError:
        import importlib.util
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]
        mod_path = repo_root / "src" / "job_radar" / "ai" / "pdf_builder.py"
        spec = importlib.util.spec_from_file_location("visalane_pdf_builder", mod_path)
        if spec is None or spec.loader is None:
            raise HTTPException(status_code=500, detail=f"pdf_builder not found at {mod_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def _supabase_headers(settings) -> dict[str, str]:
    return {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }


def _upload_to_storage(settings, path: str, pdf: bytes) -> bool:
    url = f"{settings.supabase_url}/storage/v1/object/{USERS_BUCKET}/{path}"
    headers = {
        **_supabase_headers(settings),
        "Content-Type": "application/pdf",
        "x-upsert": "true",
    }
    resp = httpx.post(url, content=pdf, headers=headers, timeout=60)
    if resp.status_code in (200, 201):
        return True
    logger.error("document upload failed (%d): %s", resp.status_code, resp.text[:300])
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

    pdf = _build_pdf(req)
    document_id = req.document_id or str(uuid.uuid4())
    job_part = req.job_id or "no-job"
    path = f"{req.user_id}/jobs/{job_part}/{req.document_type}/{document_id}.pdf"

    if not _upload_to_storage(settings, path, pdf):
        raise HTTPException(status_code=502, detail="storage upload failed")

    _update_document_row(settings, document_id, path, len(pdf))
    return {
        "document_id": document_id,
        "storage_path": path,
        "bucket": USERS_BUCKET,
        "file_size": len(pdf),
    }
