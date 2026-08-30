"""Custom outreach message generator tailored by contact persona.

Generates:
  1. LinkedIn Connection Request (<= 300 chars)
  2. LinkedIn InMail (100-150 words)
  3. Cold Email (subject <= 60 chars, body <= 200 words)
  4. Follow-up Email (sent 5 days later, value-add)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from job_radar.errors.base import HallucinationError, ValidationError
from job_radar.llm.router import LLMRouter, get_llm_router
from job_radar.llm.validated import run_validated_completion
from .outreach_templates import PERSONA_GUIDELINES
from .validators import validate_outreach_message

logger = logging.getLogger(__name__)


def build_outreach_prompt(
    profile_data: Dict[str, Any],
    job_data: Dict[str, Any],
    contact: Dict[str, Any],
    persona_type: str = "recruiter",
) -> str:
    """Construct prompt for generating personalized outreach messages across 4 formats."""
    guidelines = PERSONA_GUIDELINES.get(persona_type, PERSONA_GUIDELINES["recruiter"])
    contact_name = contact.get("name") or "Hiring Team"
    contact_title = contact.get("title") or "Recruiter"
    company_name = job_data.get("company", "the company")
    job_title = job_data.get("title", "the role")

    return f"""You are an elite networking coach.
Write 4 high-converting, personalized outreach messages from the candidate to {contact_name} ({contact_title} at {company_name}) regarding the {job_title} role.

TARGET AUDIENCE PERSONA: {persona_type.upper()}
- Tone Focus: {guidelines['focus']}
- Persona Style: {guidelines['tone']}

TARGET JOB:
- Title: {job_title}
- Company: {company_name}
- Required Skills: {json.dumps(job_data.get('skills', []))}

CANDIDATE FACTS:
{json.dumps(profile_data, indent=2)}

OUTPUT FORMATS REQUIRED:
1. linkedin_connection: Strictly under 300 characters total. Warm, personalized note to accompany connection invite.
2. linkedin_inmail: 100-150 words structured note detailing fit and asking for brief chat.
3. cold_email:
   - subject: Under 60 characters, engaging, non-spammy.
   - body: Under 200 words (3 short paragraphs) with low-commitment CTA (15 min call).
4. followup_email:
   - subject: Re: [original subject]
   - body: Under 120 words. Friendly follow-up 5 days later adding value (mentioning a shared technology or recent company news).

OUTPUT JSON SCHEMA:
{{
  "persona_type": "{persona_type}",
  "contact_name": "{contact_name}",
  "linkedin_connection": string,
  "linkedin_inmail": string,
  "cold_email": {{
    "subject": string,
    "body": string
  }},
  "followup_email": {{
    "subject": string,
    "body": string
  }}
}}"""


class OutreachGenerator:
    """Generates personalized multi-channel outreach messages."""

    def __init__(self, llm_router: Optional[LLMRouter] = None):
        self.llm_router = llm_router or get_llm_router()

    def generate_messages(
        self,
        profile_data: Dict[str, Any],
        job_data: Dict[str, Any],
        contact: Dict[str, Any],
        persona_type: str = "recruiter",
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate all 4 outreach message variations for a target contact."""
        prompt = build_outreach_prompt(
            profile_data=profile_data,
            job_data=job_data,
            contact=contact,
            persona_type=persona_type,
        )

        def _validator(candidate: Dict[str, Any]) -> Optional[str]:
            if not isinstance(candidate, dict):
                return "Output must be a JSON object"
            conn = candidate.get("linkedin_connection", "")
            email_info = candidate.get("cold_email", {})
            email_body = email_info.get("body", "") if isinstance(email_info, dict) else ""
            return validate_outreach_message(conn, email_body)

        completion = run_validated_completion(
            prompt=prompt,
            validate=_validator,
            router=self.llm_router,
            document_type="outreach_message",
            user_id=user_id,
        )

        if not completion.ok or not completion.parsed:
            raise HallucinationError(
                f"Outreach message generation failed validation: {completion.violation}",
                violations=[completion.violation],
            )

        parsed = completion.parsed
        return {
            "success": True,
            "contact": contact,
            "persona_type": persona_type,
            "messages": parsed,
            "provider_used": completion.provider,
            "model_used": completion.model,
        }


def generate_outreach(
    profile_data: Dict[str, Any],
    job_data: Dict[str, Any],
    contact: Dict[str, Any],
    persona_type: str = "recruiter",
    llm_router: Optional[LLMRouter] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience functional helper for outreach generation."""
    generator = OutreachGenerator(llm_router=llm_router)
    return generator.generate_messages(
        profile_data=profile_data,
        job_data=job_data,
        contact=contact,
        persona_type=persona_type,
        user_id=user_id,
    )
