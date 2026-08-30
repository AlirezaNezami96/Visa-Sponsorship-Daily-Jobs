"""AI output validation + deterministic document assembly (Python runtime)."""

from .ats_scorer import compute_ats_score
from .cover_letter_generator import CoverLetterGenerator, generate_cover_letter
from .cover_letter_templates import HOOK_TEMPLATES
from .outreach_generator import OutreachGenerator, generate_outreach
from .outreach_templates import PERSONA_GUIDELINES
from .own_format import build_own_format_tailoring_prompt
from .pdf_builder import build_cover_letter_pdf, build_outreach_email_pdf, build_resume_pdf
from .professional_format import build_professional_tailoring_prompt
from .resume_generator import ResumeGenerator, generate_idempotency_key, generate_resume
from .template_fetcher import TemplateFetcher, get_professional_template
from .validators import (
    validate_cover_letter_content,
    validate_outreach_message,
    validate_resume_grounding,
)

__all__ = [
    "HOOK_TEMPLATES",
    "PERSONA_GUIDELINES",
    "CoverLetterGenerator",
    "OutreachGenerator",
    "ResumeGenerator",
    "TemplateFetcher",
    "build_cover_letter_pdf",
    "build_outreach_email_pdf",
    "build_own_format_tailoring_prompt",
    "build_professional_tailoring_prompt",
    "build_resume_pdf",
    "compute_ats_score",
    "generate_cover_letter",
    "generate_idempotency_key",
    "generate_outreach",
    "generate_resume",
    "get_professional_template",
    "validate_cover_letter_content",
    "validate_outreach_message",
    "validate_resume_grounding",
]
