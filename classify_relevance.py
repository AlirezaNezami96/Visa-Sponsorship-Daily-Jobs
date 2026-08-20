"""LLM Relevance Classifier (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.classifiers.cache import (
    ClassificationCache,
    ClassifierCache,
    get_classifier_cache,
    make_cache_key,
)
from job_radar.classifiers.relevance import (
    LLM_CLASSIFIER_PROMPT,
    SYSTEM_PROMPT,
    JobClassification,
    _cache_key,
    _call_anthropic,
    _call_gemini,
    _call_openai,
    classify_and_filter_jobs,
    classify_job_llm,
    classify_single_job,
    heuristic_classify_job,
    parse_llm_json_response,
)

__all__ = [
    "SYSTEM_PROMPT",
    "LLM_CLASSIFIER_PROMPT",
    "ClassificationCache",
    "ClassifierCache",
    "JobClassification",
    "classify_and_filter_jobs",
    "classify_job_llm",
    "classify_single_job",
    "heuristic_classify_job",
    "parse_llm_json_response",
    "get_classifier_cache",
    "make_cache_key",
    "_cache_key",
    "_call_gemini",
    "_call_anthropic",
    "_call_openai",
]
