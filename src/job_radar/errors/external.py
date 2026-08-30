"""External integration and third-party API error classes."""
from __future__ import annotations

from .base import EmailDeliveryError, ExternalServiceError, GenerationError, HallucinationError


class LLMQuotaExhaustedError(GenerationError):
    """External LLM provider quota or rate limit exhausted."""
    code = "llm_quota_exhausted"
    default_user_message = "AI service capacity is currently limited. Please try again shortly."


class ScraperBlockedError(ExternalServiceError):
    """Target website blocked scraper or returned bot challenge."""
    code = "scraper_blocked"
    default_user_message = "Company website could not be reached. Manual search links provided below."
