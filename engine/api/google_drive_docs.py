"""
Google Drive & Google Docs API Service.

Provides:
  1. Reading master resume structure directly from Google Docs API
  2. In-place cloning of the Master Resume into a target Google Drive folder
  3. Batch text replacement on the cloned doc while preserving 100% of formatting/styles
  4. Direct PDF export from Google's rendering engine (zero local OS dependencies)
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google.oauth2 import service_account
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from .config import get_settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


def _get_credentials_path() -> Optional[Path]:
    """Find the service account credentials file."""
    settings = get_settings()
    custom_path = Path(settings.google_credentials_path)
    if custom_path.is_absolute() and custom_path.exists():
        return custom_path

    # Check relative to engine/ directory
    engine_dir = Path(__file__).resolve().parent.parent
    for candidate in [
        engine_dir / custom_path,
        engine_dir / "credentials.json",
        Path("credentials.json"),
        Path("engine/credentials.json"),
    ]:
        if candidate.exists():
            return candidate.resolve()
    return None


def is_google_drive_configured() -> bool:
    """Return True if credentials.json is present and readable."""
    return _get_credentials_path() is not None


def _get_services() -> Tuple[Resource, Resource]:
    """Initialize and return (drive_service, docs_service)."""
    creds_path = _get_credentials_path()
    if not creds_path:
        raise FileNotFoundError(
            "credentials.json not found. Please place your service account key in engine/credentials.json."
        )

    creds = service_account.Credentials.from_service_account_file(
        str(creds_path), scopes=SCOPES
    )
    drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    docs_service = build("docs", "v1", credentials=creds, cache_discovery=False)
    return drive_service, docs_service


# ── Document Reading ──────────────────────────────────────────────────────────

def fetch_doc_text_api(doc_id: str) -> str:
    """Extract plain text from a Google Doc using the Docs API."""
    _drive, docs = _get_services()
    try:
        doc = docs.documents().get(documentId=doc_id).execute()
        return _extract_text_from_doc(doc)
    except HttpError as exc:
        logger.error("Failed to read Google Doc via API: %s", exc)
        raise ValueError(f"Could not access Google Doc ({doc_id}): {exc}") from exc


def _extract_text_from_doc(doc: Dict[str, Any]) -> str:
    """Recursively extract plain text from Google Docs structural elements."""
    body = doc.get("body", {})
    content = body.get("content", [])
    text_parts: List[str] = []

    for element in content:
        if "paragraph" in element:
            para = element["paragraph"]
            for el in para.get("elements", []):
                text_run = el.get("textRun", {})
                if "content" in text_run:
                    text_parts.append(text_run["content"])
        elif "table" in element:
            table = element["table"]
            for row in table.get("tableRows", []):
                for cell in row.get("tableCells", []):
                    for cell_elem in cell.get("content", []):
                        if "paragraph" in cell_elem:
                            for el in cell_elem["paragraph"].get("elements", []):
                                text_run = el.get("textRun", {})
                                if "content" in text_run:
                                    text_parts.append(text_run["content"])

    return "".join(text_parts).strip()


# ── Clone & Tailor Document ───────────────────────────────────────────────────

def clone_and_tailor_doc(
    master_doc_id: str,
    company_name: str,
    job_title: str,
    replacements: List[Tuple[str, str]],
    folder_id: Optional[str] = None,
) -> Tuple[str, str, bytes]:
    """
    Clone the master resume Google Doc and apply text replacements.

    Args:
        master_doc_id: The ID of the source Google Doc.
        company_name: Target company (e.g. OpenAI).
        job_title: Target role (e.g. Senior AI Engineer).
        replacements: List of (original_text, replacement_text) tuples.
        folder_id: Optional target Google Drive folder ID.

    Returns:
        (new_doc_id, edit_url, pdf_bytes)
    """
    drive, docs = _get_services()
    settings = get_settings()
    target_folder = folder_id or settings.google_drive_folder_id

    # 1. Copy the master document
    title = f"{company_name} — {job_title} Resume"
    copy_body: Dict[str, Any] = {"name": title}
    if target_folder:
        copy_body["parents"] = [target_folder]

    try:
        copied_file = (
            drive.files()
            .copy(
                fileId=master_doc_id,
                body=copy_body,
                supportsAllDrives=True,
                fields="id, name, webViewLink",
            )
            .execute()
        )
    except HttpError as exc:
        error_str = str(exc)
        logger.error("Failed to copy Google Doc: %s", exc)
        if "storageQuotaExceeded" in error_str or "storage quota" in error_str.lower():
            raise ValueError(
                "Service account Drive storage quota exceeded. "
                "Service accounts have 0 bytes of personal storage. "
                "To fix: convert the 'Tailored Resumes' folder to a Shared Drive "
                "and add the service account as a Member — copies will then count against "
                "the Shared Drive quota, not the SA's personal storage. "
                "See: https://support.google.com/a/answer/7212025"
            ) from exc
        raise ValueError(
            f"Google Drive failed to copy document: {exc}. "
            "Make sure your Master Resume and Tailored Resumes folder are shared with your Service Account email."
        ) from exc

    new_doc_id = copied_file["id"]
    edit_url = f"https://docs.google.com/document/d/{new_doc_id}/edit"
    logger.info("Created tailored Google Doc copy: %s (%s)", title, new_doc_id)

    # 2. Apply batch text replacements to preserve exact formatting
    if replacements:
        requests = []
        for old_text, new_text in replacements:
            old_clean = old_text.strip()
            new_clean = new_text.strip()
            if old_clean and new_clean and old_clean != new_clean:
                requests.append({
                    "replaceAllText": {
                        "containsText": {
                            "text": old_clean,
                            "matchCase": False,
                        },
                        "replaceText": new_clean,
                    }
                })

        if requests:
            try:
                docs.documents().batchUpdate(
                    documentId=new_doc_id,
                    body={"requests": requests},
                ).execute()
                logger.info("Applied %d text replacements to Google Doc %s", len(requests), new_doc_id)
            except HttpError as exc:
                logger.warning("Docs batchUpdate warning: %s — document still created.", exc)

    # 3. Export directly as PDF from Google Docs render engine
    try:
        pdf_bytes = (
            drive.files()
            .export(fileId=new_doc_id, mimeType="application/pdf")
            .execute()
        )
        logger.info("Exported PDF from Google Docs for %s (%d bytes)", new_doc_id, len(pdf_bytes))
    except Exception as exc:
        logger.warning("Google Drive export to PDF failed (%s), returning empty bytes", exc)
        pdf_bytes = b""

    return new_doc_id, edit_url, pdf_bytes
