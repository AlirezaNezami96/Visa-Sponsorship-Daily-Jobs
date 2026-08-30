"""Fast, personalized cover letter generator.

Uses fast models (Groq Llama 3.3 70B, OpenRouter free models, with Gemini fallback)
to generate high-impact, grounded cover letters (250-400 words) without cliché openers.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from job_radar.errors.base import HallucinationError, ValidationError
from job_radar.llm.router import LLMRouter, get_llm_router
from job_radar.llm.validated import run_validated_completion
from .validators import validate_cover_letter_content

logger = logging.getLogger(__name__)


def build_cover_letter_prompt(
    profile_data: Dict[str, Any],
    job_data: Dict[str, Any],
    company_intel: str = "",
) -> str:
    """Construct cover letter generation prompt."""
    company_name = job_data.get("company") or "the company"
    job_title = job_data.get("title") or "the open position"

    return f"""You are a world-class executive career coach and cover letter author.
Write a compelling, tailored, and concise cover letter for the candidate applying to {company_name} for the role of {job_title}.

TARGET JOB DETAILS:
- Title: {job_title}
- Company: {company_name}
- Required Skills: {json.dumps(job_data.get('skills', []))}
- Job Description:
{job_data.get('description', '')[:3000]}
{f"- Company Context / Mission: {company_intel}" if company_intel else ""}

CANDIDATE FACTS (GROUNDING SOURCE OF TRUTH):
{json.dumps(profile_data, indent=2)}

STRICT RULES:
1. WORD COUNT: 250 to 400 words total.
2. NO CLICHÉ PHRASES:
   - NEVER start with "I am writing to apply..." or "I am thrilled to apply..."
   - NEVER use "To whom it may concern" or "delve into"
3. FACTUAL GROUNDING: Reference ONLY companies, metrics, and achievements from the candidate's profile.
4. SPECIFICITY: Mention {company_name} by name and why their mission/products excite the candidate.
5. Return ONLY a valid JSON object matching the schema below (NO markdown code blocks).

OUTPUT JSON SCHEMA:
{{
  "salutation": "Dear Hiring Team at {company_name},",
  "opening_hook": string,
  "body_paragraphs": [string],
  "closing_call_to_action": string,
  "sign_off": "Sincerely,\\n{profile_data.get('full_name', 'Candidate')}",
  "full_text": string,
  "word_count": integer
}}"""


class CoverLetterGenerator:
    """Generates and validates cover letters."""

    def __init__(self, llm_router: Optional[LLMRouter] = None):
        self.llm_router = llm_router or get_llm_router()

    def generate(
        self,
        profile_data: Dict[str, Any],
        job_data: Dict[str, Any],
        company_intel: str = "",
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate tailored cover letter."""
        company_name = job_data.get("company", "")
        prompt = build_cover_letter_prompt(
            profile_data=profile_data,
            job_data=job_data,
            company_intel=company_intel,
        )

        def _validator(candidate: Dict[str, Any]) -> Optional[str]:
            if not isinstance(candidate, dict):
                return "AI output must be a JSON object"
            full_text = candidate.get("full_text") or "\n\n".join(candidate.get("body_paragraphs", []))
            return validate_cover_letter_content(full_text, company_name=company_name)

        completion = run_validated_completion(
            prompt=prompt,
            validate=_validator,
            router=self.llm_router,
            document_type="cover_letter",
            user_id=user_id,
        )

        if not completion.ok or not completion.parsed:
            raise HallucinationError(
                f"Cover letter generation failed validation: {completion.violation}",
                violations=[completion.violation],
            )

        parsed = completion.parsed
        full_text = parsed.get("full_text")
        if not full_text:
            parts = [
                parsed.get("salutation", f"Dear Hiring Team at {company_name},"),
                parsed.get("opening_hook", ""),
                *parsed.get("body_paragraphs", []),
                parsed.get("closing_call_to_action", ""),
                parsed.get("sign_off", f"Sincerely,\n{profile_data.get('full_name', 'Candidate')}"),
            ]
            full_text = "\n\n".join(p for p in parts if p)
            parsed["full_text"] = full_text

        parsed["word_count"] = len(full_text.split())
        parsed["provider_used"] = completion.provider
        parsed["model_used"] = completion.model

        return {
            "success": True,
            "cover_letter": parsed,
            "word_count": parsed["word_count"],
            "company": company_name,
            "provider_used": completion.provider,
            "model_used": completion.model,
        }


def generate_cover_letter(
    profile_data: Dict[str, Any],
    job_data: Dict[str, Any],
    company_intel: str = "",
    llm_router: Optional[LLMRouter] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience functional helper for cover letter generation."""
    generator = CoverLetterGenerator(llm_router=llm_router)
    return generator.generate(
        profile_data=profile_data,
        job_data=job_data,
        company_intel=company_intel,
        user_id=user_id,
    )
