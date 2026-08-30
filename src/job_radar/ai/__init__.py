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
    "compute_ats_score",
    "build_resume_pdf",
    "build_cover_letter_pdf",
    "build_outreach_email_pdf",
    "ResumeGenerator",
    "generate_resume",
    "generate_idempotency_key",
    "build_professional_tailoring_prompt",
    "build_own_format_tailoring_prompt",
    "TemplateFetcher",
    "get_professional_template",
    "validate_resume_grounding",
    "validate_cover_letter_content",
    "validate_outreach_message",
    "CoverLetterGenerator",
    "generate_cover_letter",
    "HOOK_TEMPLATES",
    "OutreachGenerator",
    "generate_outreach",
    "PERSONA_GUIDELINES",
]
