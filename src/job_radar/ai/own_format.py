"""User's own format resume generator.

Preserves the user's original resume structural layout, section order, and style,
while tailoring bullet points, summary, and skills for the target job.
"""

from __future__ import annotations

import json
from typing import Any


def build_own_format_tailoring_prompt(
    profile_data: dict[str, Any],
    job_data: dict[str, Any],
    original_raw_text: str = "",
) -> str:
    """Build the AI prompt for user's own format resume tailoring."""
    return f"""You are an elite resume editor.
Your mission is to tailor the candidate's resume for the target job while PRESERVING the candidate's exact structural layout, tone, and section hierarchy.

TARGET JOB DETAILS:
- Title: {job_data.get("title", "Unknown")}
- Company: {job_data.get("company", "Unknown")}
- Required Skills: {json.dumps(job_data.get("skills", []))}
- Job Description:
{job_data.get("description", "")[:4000]}

CANDIDATE ORIGINAL RESUME / PROFILE:
{json.dumps(profile_data, indent=2)}

ORIGINAL RESUME CONTEXT (FOR SECTION ORDER & STYLE REFERENCE):
{original_raw_text[:3000] if original_raw_text else "Preserve standard order from profile data"}

STRICT RULES:
1. PRESERVE STRUCTURE: Keep the candidate's exact section ordering and personal style.
2. TAILOR CONTENT ONLY:
   - Enhance the summary for this job.
   - Align skill ordering with the target job requirements.
   - Refine experience achievements to highlight relevant impact and technologies.
3. NO HALLUCINATIONS: Do not invent any companies, degrees, or unearned certifications.
4. Return ONLY valid JSON (no markdown code blocks).

OUTPUT JSON SCHEMA:
{{
  "full_name": string,
  "email": string,
  "phone": string|null,
  "location": string|null,
  "linkedin_url": string|null,
  "github_url": string|null,
  "website_url": string|null,
  "summary": string,
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
  "projects": [
    {{
      "name": string,
      "description": string|null,
      "technologies": [string]
    }}
  ],
  "certifications": [
    {{
      "name": string,
      "issuer": string|null,
      "year": string|null
    }}
  ],
  "languages": [
    {{
      "language": string,
      "proficiency": string|null
    }}
  ],
  "format_type": "own"
}}"""
