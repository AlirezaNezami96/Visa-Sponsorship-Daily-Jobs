"""
Google Docs integration — fetches plain text content from a publicly shared doc.

No OAuth required for MVP: the doc must be shared as "Anyone with the link can view."
The export URL pattern:
  https://docs.google.com/document/d/{DOC_ID}/export?format=txt
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

GDOCS_EXPORT_URL = "https://docs.google.com/document/d/{doc_id}/export?format=txt"

# Validate Google Docs IDs — they are 44-character base64url strings
import re
_GDOC_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{10,60}$")


def _validate_doc_id(doc_id: str) -> bool:
    return bool(_GDOC_ID_RE.match(doc_id))


async def fetch_resume_from_google_doc(doc_id: str) -> str:
    """
    Fetch the plain text content of a publicly shared Google Doc.

    Args:
        doc_id: The Google Docs document ID (from the URL).

    Returns:
        The raw text content of the document.

    Raises:
        ValueError: If the doc_id is invalid or the document isn't publicly accessible.
        httpx.HTTPStatusError: For HTTP errors (403 = not public, 404 = not found).
    """
    if not _validate_doc_id(doc_id):
        raise ValueError(f"Invalid Google Doc ID format: '{doc_id}'")

    url = GDOCS_EXPORT_URL.format(doc_id=doc_id)
    logger.info("Fetching Google Doc: %s", url)

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; JobEngine/1.0)",
        "Accept": "text/plain",
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
        response = await client.get(url, headers=headers)

    if response.status_code == 403:
        raise ValueError(
            "Google Doc is not publicly accessible. "
            "Please set sharing to 'Anyone with the link can view'."
        )
    if response.status_code == 404:
        raise ValueError(f"Google Doc not found: {doc_id}")

    response.raise_for_status()

    text = response.text.strip()
    if len(text) < 50:
        raise ValueError(
            "Google Doc appears to be empty or too short to be a valid resume."
        )

    logger.info("Fetched %d characters from Google Doc %s", len(text), doc_id)
    return text
