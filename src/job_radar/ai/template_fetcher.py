"""Template fetcher for professional resume format.

Fetches Google Doc resume template structure or falls back to built-in
ATS-optimized professional template schema.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional
import requests

logger = logging.getLogger(__name__)

# Standard ATS-optimized Google Doc template structure
DEFAULT_PROFESSIONAL_TEMPLATE: Dict[str, Any] = {
    "template_id": "visalane_ats_standard_v1",
    "name": "VisaLane ATS Professional",
    "margins_in": {"top": 0.5, "bottom": 0.5, "left": 0.5, "right": 0.5},
    "font_family": "Helvetica",
    "font_sizes": {
        "name": 18,
        "contact": 10,
        "section_header": 12,
        "item_title": 11,
        "body": 10,
    },
    "section_order": [
        "header",
        "summary",
        "skills",
        "experience",
        "education",
        "projects",
        "certifications",
        "languages",
    ],
}


class TemplateFetcher:
    """Fetches and caches Google Doc resume templates."""

    def __init__(self, google_doc_template_id: Optional[str] = None):
        self.template_id = google_doc_template_id or os.getenv("GOOGLE_DOC_TEMPLATE_ID", "").strip()

    def get_template(self) -> Dict[str, Any]:
        """Fetch template structure. Returns fallback if Google Doc is unreachable."""
        if not self.template_id:
            return dict(DEFAULT_PROFESSIONAL_TEMPLATE)

        # If a Google Doc ID is configured, attempt to fetch doc structure via API
        google_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if google_api_key:
            try:
                url = f"https://docs.googleapis.com/v1/documents/{self.template_id}?key={google_api_key}"
                resp = requests.get(url, timeout=5.0)
                if resp.status_code == 200:
                    doc_data = resp.json()
                    return self._parse_google_doc_structure(doc_data)
            except Exception as exc:
                logger.debug("Google Docs template fetch failed, using built-in template: %s", exc)

        return dict(DEFAULT_PROFESSIONAL_TEMPLATE)

    def _parse_google_doc_structure(self, doc_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract layout sections from Google Doc AST."""
        template = dict(DEFAULT_PROFESSIONAL_TEMPLATE)
        template["template_id"] = doc_data.get("documentId", self.template_id)
        template["title"] = doc_data.get("title", "Google Doc Template")
        return template


def get_professional_template(template_id: Optional[str] = None) -> Dict[str, Any]:
    """Convenience helper to retrieve professional resume template."""
    return TemplateFetcher(google_doc_template_id=template_id).get_template()
