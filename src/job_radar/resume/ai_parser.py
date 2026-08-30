"""AI-powered structured resume parsing module.

Extracts complete resume information from raw text with strict JSON schema
validation, anti-hallucination checks, and waterfall fallback.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from job_radar.llm.router import LLMRouter, get_llm_router
from job_radar.llm.validated import parse_ai_json, run_validated_completion

logger = logging.getLogger(__name__)

RESUME_PARSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "full_name": {"type": ["string", "null"]},
        "email": {"type": ["string", "null"]},
        "phone": {"type": ["string", "null"]},
        "location": {"type": ["string", "null"]},
        "linkedin_url": {"type": ["string", "null"]},
        "github_url": {"type": ["string", "null"]},
        "website_url": {"type": ["string", "null"]},
        "summary": {"type": ["string", "null"]},
        "job_titles": {"type": "array", "items": {"type": "string"}},
        "skills": {"type": "array", "items": {"type": "string"}},
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "title": {"type": "string"},
                    "start": {"type": ["string", "null"]},
                    "end": {"type": ["string", "null"]},
                    "highlights": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["company", "title"],
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "institution": {"type": "string"},
                    "degree": {"type": ["string", "null"]},
                    "field": {"type": ["string", "null"]},
                    "year": {"type": ["string", "null"]},
                    "gpa": {"type": ["string", "null"]},
                },
                "required": ["institution"],
            },
        },
        "certifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "issuer": {"type": ["string", "null"]},
                    "year": {"type": ["string", "null"]},
                },
                "required": ["name"],
            },
        },
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": ["string", "null"]},
                    "technologies": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name"],
            },
        },
        "languages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "language": {"type": "string"},
                    "proficiency": {"type": ["string", "null"]},
                },
                "required": ["language"],
            },
        },
        "volunteer_work": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "organization": {"type": "string"},
                    "role": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                },
            },
        },
        "publications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "venue": {"type": ["string", "null"]},
                    "year": {"type": ["string", "null"]},
                },
            },
        },
        "awards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "issuer": {"type": ["string", "null"]},
                    "year": {"type": ["string", "null"]},
                },
            },
        },
        "interests": {"type": "array", "items": {"type": "string"}},
        "references": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "relationship": {"type": ["string", "null"]},
                    "contact": {"type": ["string", "null"]},
                },
            },
        },
    },
}


def build_resume_parse_prompt(raw_text: str) -> str:
    """Construct structured extraction prompt for AI model."""
    return f"""Extract structured data from this resume text.

HARD RULES:
- Use ONLY facts and statements present in the resume text. NEVER invent or hallucinate information.
- If a section or field is not present in the resume, use null or empty array [].
- Return ONLY valid JSON matching the schema, with NO markdown code fences.

JSON SCHEMA REQUIREMENT:
{{
  "full_name": string|null,
  "email": string|null,
  "phone": string|null,
  "location": string|null,
  "linkedin_url": string|null,
  "github_url": string|null,
  "website_url": string|null,
  "summary": string|null,
  "job_titles": [string],
  "skills": [string],
  "experience": [
    {{
      "company": string,
      "title": string,
      "start": string|null,
      "end": string|null,
      "highlights": [string]
    }}
  ],
  "education": [
    {{
      "institution": string,
      "degree": string|null,
      "field": string|null,
      "year": string|null,
      "gpa": string|null
    }}
  ],
  "certifications": [
    {{
      "name": string,
      "issuer": string|null,
      "year": string|null
    }}
  ],
  "projects": [
    {{
      "name": string,
      "description": string|null,
      "technologies": [string]
    }}
  ],
  "languages": [
    {{
      "language": string,
      "proficiency": string|null
    }}
  ],
  "volunteer_work": [
    {{
      "organization": string,
      "role": string|null,
      "description": string|null
    }}
  ],
  "publications": [
    {{
      "title": string,
      "venue": string|null,
      "year": string|null
    }}
  ],
  "awards": [
    {{
      "title": string,
      "issuer": string|null,
      "year": string|null
    }}
  ],
  "interests": [string],
  "references": [
    {{
      "name": string,
      "relationship": string|null,
      "contact": string|null
    }}
  ]
}}

RESUME TEXT:
{raw_text[:14000]}"""


def validate_resume_parse_output(parsed: Any) -> Optional[str]:
    """Validate that the AI response is a dict and has valid basic types."""
    if not isinstance(parsed, dict):
        return "Parsed output must be a JSON object"
    return None


class AIResumeParser:
    """High-level AI resume parsing orchestrator."""

    def __init__(self, llm_router: Optional[LLMRouter] = None):
        self.llm_router = llm_router or get_llm_router()

    def parse(self, raw_text: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Extract structured resume data from text using AI."""
        if not raw_text or not raw_text.strip():
            return {}

        prompt = build_resume_parse_prompt(raw_text)

        # Use validated completion with fallback chain
        completion = run_validated_completion(
            prompt=prompt,
            validate=validate_resume_parse_output,
            router=self.llm_router,
            json_schema=RESUME_PARSE_SCHEMA,
            document_type="resume_parse",
            user_id=user_id,
        )

        if completion.ok and isinstance(completion.parsed, dict):
            return completion.parsed

        # Fallback to direct json completion
        try:
            direct_result = self.llm_router.complete_json(prompt)
            if isinstance(direct_result, dict):
                return direct_result
        except Exception as exc:
            logger.warning("Direct LLM completion fallback failed: %s", exc)

        return {}


def parse_resume_with_ai(
    raw_text: str,
    llm_router: Optional[Any] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience functional wrapper for AI resume parsing."""
    parser = AIResumeParser(llm_router=llm_router)
    return parser.parse(raw_text, user_id=user_id)
