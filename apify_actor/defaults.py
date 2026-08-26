"""Single source of truth for Apify Actor default configurations and source providers."""
from __future__ import annotations

from typing import List

# Default high-yield ATS and remote/global job sources enabled by default
DEFAULT_SOURCES: List[str] = [
    "greenhouse",
    "lever",
    "ashby",
    "remoteok",
    "remotive",
    "arbeitnow",
    "himalayas",
    "jobicy",
]

# Supported LLM providers for AI classification
SUPPORTED_LLM_PROVIDERS: List[str] = [
    "gemini",
    "groq",
]
