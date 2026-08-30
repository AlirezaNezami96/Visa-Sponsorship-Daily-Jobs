"""Professional resume format generator.

Generates tailored resumes matching the Google Doc professional template structure,
optimizing for ATS readability and keyword relevance (target ATS score 95+).
"""

from __future__ import annotations

import json
from typing import Any

from .template_fetcher import get_professional_template


def build_professional_tailoring_prompt(
    profile_data: dict[str, Any],
    job_data: dict[str, Any],
    template_config: dict[str, Any] | None = None,
) -> str:
    """Build the AI prompt for professional template resume tailoring."""
    template = template_config or get_professional_template()

    return f"""You are an expert executive resume writer and ATS optimization specialist.
Tailor the candidate's resume for the specific job opening below, formatting for the Professional ATS Template.

TARGET JOB DETAILS:
- Title: {job_data.get("title", "Unknown")}
- Company: {job_data.get("company", "Unknown")}
- Required Skills: {json.dumps(job_data.get("skills", []))}
- Job Description:
{job_data.get("description", "")[:4000]}

CANDIDATE PROFILE (SOURCE OF TRUTH):
{json.dumps(profile_data, indent=2)}

STRICT GENERATION RULES:
1. FACTUAL FIDELITY: Use ONLY companies, job titles, dates, institutions, degrees, and core projects present in the candidate profile. NEVER invent employment or credentials.
2. ATS OPTIMIZATION (TARGET 95+):
   - Rewrite the summary to strongly pitch candidate for this exact role.
   - Reorder skills so job-matching skills appear first.
   - Tailor work experience bullet points to emphasize relevant achievements, metrics, and technologies.
3. Preserve all non-empty sections from the profile (projects, certifications, languages, etc.).
4. Return ONLY a valid JSON object matching the schema below (NO markdown fences).

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
  "format_type": "professional",
  "template_id": "{template.get("template_id", "visalane_ats_standard_v1")}"
}}"""
