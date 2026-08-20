"""Resume document fetcher.

Fetches the candidate's resume text from a Google Doc once per pipeline run.
The content is kept in-memory only — never written to disk or logged.

Supported access methods:
  - "link_shared": uses the public export URL (doc must be shared "Anyone with link → Viewer").
  - "service_account": uses the Google Docs API with GOOGLE_SERVICE_ACCOUNT_JSON env var.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GOOGLE_DOCS_EXPORT_URL = "https://docs.google.com/document/d/{doc_id}/export?format=txt"
GOOGLE_DOCS_API_URL = "https://docs.googleapis.com/v1/documents/{doc_id}"
DEFAULT_TIMEOUT = 20


def fetch_resume_text(
    doc_id: Optional[str] = None,
    access_method: str = "link_shared",
) -> str:
    """Fetch the resume document text.

    Args:
        doc_id: Google Doc ID (the long hash in the URL). Falls back to config or
                the RESUME_DOC_ID environment variable.
        access_method: "link_shared" (export URL, default) or "service_account".

    Returns:
        Resume text as a plain string.

    Raises:
        RuntimeError: if the document cannot be fetched (pipeline should catch and log).
    """
    # Resolve doc_id from args → env → config (lazy import to avoid circular)
    if not doc_id:
        doc_id = os.environ.get("RESUME_DOC_ID")
    if not doc_id:
        try:
            from job_radar.config.loader import get_config
            cfg = get_config()
            doc_id = cfg.resume.doc_id
            access_method = access_method or cfg.resume.access_method
        except Exception:
            pass

    if not doc_id:
        raise RuntimeError(
            "Resume doc_id is not configured. "
            "Set RESUME_DOC_ID env var or configure resume.doc_id in config.yaml."
        )

    if access_method == "service_account":
        return _fetch_via_service_account(doc_id)
    else:
        return _fetch_via_export_url(doc_id)


def _fetch_via_export_url(doc_id: str) -> str:
    """Fetch plain-text export from a link-shared Google Doc."""
    url = GOOGLE_DOCS_EXPORT_URL.format(doc_id=doc_id)
    logger.debug("Fetching resume from export URL (doc_id: %s...)", doc_id[:8])

    try:
        resp = requests.get(url, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        raise RuntimeError(f"Network error fetching resume doc: {exc}") from exc

    if resp.status_code == 401 or "Sign in" in resp.text[:500]:
        raise RuntimeError(
            "Google Doc returned a sign-in page. "
            "Ensure the doc is shared 'Anyone with the link → Viewer', "
            "or switch to access_method: service_account."
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Unexpected HTTP {resp.status_code} fetching resume doc. "
            f"Check the doc_id and sharing settings."
        )

    text = resp.text.strip()
    if not text:
        raise RuntimeError("Resume doc returned empty content.")

    # Intentionally NOT logging the content — privacy guard
    logger.info("✅ Resume fetched successfully (%d chars)", len(text))
    return text


def _fetch_via_service_account(doc_id: str) -> str:
    """Fetch using a Google service account — requires GOOGLE_SERVICE_ACCOUNT_JSON env var."""
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "google-api-python-client and google-auth are required for service_account access. "
            "Install them: pip install google-api-python-client google-auth"
        ) from exc

    sa_json_raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json_raw:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON env var is not set. "
            "Either set it or switch to access_method: link_shared."
        )

    try:
        # Support both raw JSON and base64-encoded JSON
        try:
            sa_info = json.loads(sa_json_raw)
        except json.JSONDecodeError:
            sa_info = json.loads(base64.b64decode(sa_json_raw).decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to parse GOOGLE_SERVICE_ACCOUNT_JSON: {exc}") from exc

    scopes = ["https://www.googleapis.com/auth/documents.readonly"]
    credentials = Credentials.from_service_account_info(sa_info, scopes=scopes)
    service = build("docs", "v1", credentials=credentials)

    try:
        doc = service.documents().get(documentId=doc_id).execute()
    except Exception as exc:
        raise RuntimeError(f"Google Docs API error: {exc}") from exc

    # Extract plain text from the document body
    text_parts = []
    for element in doc.get("body", {}).get("content", []):
        paragraph = element.get("paragraph", {})
        for pe in paragraph.get("elements", []):
            text_run = pe.get("textRun", {})
            text_parts.append(text_run.get("content", ""))

    text = "".join(text_parts).strip()
    if not text:
        raise RuntimeError("Resume doc returned empty content via service account.")

    logger.info("✅ Resume fetched via service account (%d chars)", len(text))
    return text
