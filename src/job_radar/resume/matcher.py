"""Gemini-powered resume ↔ job-description ATS matcher.

Follows the exact same calling pattern as classify_relevance.py:
- Same _call_gemini() shape
- Same JSON-mode response
- Same try/except-and-log-don't-crash resilience
- Same disk-backed ClassificationCache

One shared prompt used identically across all three tracks (visa, remote, ai_intern).
The JD content differentiates each call, not the track.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Optional

from job_radar.classifiers.cache import ClassificationCache

logger = logging.getLogger(__name__)

RESUME_MATCH_SYSTEM_PROMPT = """You are a resume optimization specialist and ATS analyst
working for one candidate across every job you evaluate. You will be given (1) a specific
job description and (2) the candidate's current resume text. Tell the candidate exactly how
well they currently match and exactly what to change — without ever inventing anything about
their background.

How resume screening actually works in 2026, which your scoring must reflect:
- Most mid-size and large employers screen in two layers: a literal parsing/keyword layer
  (still rewards exact phrases and the exact job title used in the posting) sitting under a
  semantic/embedding layer (credits close synonyms and adjacent skills, weights recent and
  directly-relevant experience higher).
- Keyword match density matters, but unnatural repetition is actively penalized — the goal is
  accurate, natural inclusion of the terms this specific JD uses, not maximum density.
- Exact phrasing beats paraphrase when it's honestly available: if the JD says "Kotlin
  Coroutines" and the resume already has that experience, surface that exact phrase rather
  than a looser description.
- A bullet that pairs a skill/tool with a measurable outcome outperforms a bare mention of the
  same skill.
- Clean, single-column, standard-heading formatting parses reliably. Never suggest a change
  that would require tables, columns, or graphics to implement.

Respond with ONLY valid JSON in this exact shape, no markdown fences:
{
  "ats_score": 0,
  "score_rationale": "1-2 sentences on what is driving the score",
  "keywords_to_add": ["...", "..."],
  "keywords_to_deemphasize": ["...", "..."],
  "section_suggestions": [
    {"section": "Experience — <Company/Role from the resume>", "suggestion": "concrete rewrite guidance referencing the candidate's real, existing bullet"}
  ],
  "resume_editing_prompt": "a self-contained, ready-to-paste instruction block — see rules below"
}

Rules for "resume_editing_prompt":
- Write it as a direct instruction to an AI assistant that already has the candidate's resume
  document open and can edit it (e.g. Gemini's assistant panel inside Google Docs).
- Reference specific existing sections/bullets from the resume text you were given
  ("In the <Company> bullet about X, change ... to ..."), never generic advice.
- Every suggested addition must be a truthful reframing or emphasis of experience already
  present in the source resume. Never invent employers, titles, dates, tools, or metrics that
  are not in the source resume text.
- Keep it short enough to paste into a chat box in one go — a tight numbered list of concrete
  edits beats a paragraph of prose.
- End with one line reminding the assistant not to change dates, employer names, or job titles.

If a JD wants a keyword the resume has no honest basis for, list it in "keywords_to_add" only —
never fabricate it into "resume_editing_prompt"."""


def _cache_key(company: str, title: str, url: str) -> str:
    """Stable cache key for a job's resume match result."""
    raw = f"{company.strip().lower()}|{title.strip().lower()}|{url.strip()}"
    return "rm|" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def _call_gemini_resume(user_prompt: str, model_name: str, fallback_model: str) -> str:
    """Call Gemini with the resume match prompt. Falls back to fallback_model on model-not-found."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    full_input = f"{RESUME_MATCH_SYSTEM_PROMPT}\n\n---\n\n{user_prompt}"

    try:
        interaction = client.interactions.create(
            model=model_name,
            input=full_input,
            response_mime_type="application/json",
        )
        return (interaction.output_text or "").strip()
    except Exception as primary_exc:
        err_str = str(primary_exc).lower()
        if "not found" in err_str or "model" in err_str or "404" in err_str:
            logger.warning(
                "Model %s not available (%s), retrying with fallback %s",
                model_name, primary_exc, fallback_model,
            )
            try:
                interaction = client.interactions.create(
                    model=fallback_model,
                    input=full_input,
                    response_mime_type="application/json",
                )
                return (interaction.output_text or "").strip()
            except Exception as fallback_exc:
                raise RuntimeError(f"Both {model_name} and {fallback_model} failed: {fallback_exc}") from fallback_exc
        raise


def _parse_match_response(raw_text: str) -> Optional[dict]:
    """Parse and validate the JSON response from Gemini."""
    if not raw_text:
        return None
    try:
        cleaned = raw_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.split("```json", 1)[1].rsplit("```", 1)[0].strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned.split("```", 1)[1].rsplit("```", 1)[0].strip()
        parsed = json.loads(cleaned)
        # Minimal validation
        if not isinstance(parsed.get("ats_score"), int):
            return None
        return parsed
    except Exception as exc:
        logger.debug("Failed to parse resume match JSON: %s", exc)
        return None


def match_resume_to_job(
    job: dict,
    resume_text: str,
    config: Any = None,
    cache: Optional[ClassificationCache] = None,
) -> Optional[dict]:
    """Match a resume against a job description using Gemini.

    Returns a dict with ats_score, keywords_to_add, resume_editing_prompt, etc.
    Returns None on failure — never raises, never blocks the pipeline.
    A failed match call must not change result order or terminate a digest.
    """
    if not resume_text:
        logger.debug("Skipping resume match — no resume text available")
        return None

    # Resolve config
    if config is None:
        try:
            from job_radar.config.loader import get_config
            config = get_config()
        except Exception:
            config = None

    enabled = True
    model = "gemini-3.7-flash"
    fallback_model = "gemini-3.6-flash"
    cache_file = "state/resume_match_cache.json"

    if config is not None and hasattr(config, "resume_matcher"):
        enabled = config.resume_matcher.enabled
        model = config.resume_matcher.model
        fallback_model = config.resume_matcher.fallback_model
        cache_file = config.resume_matcher.cache_file

    if not enabled:
        return None

    company = job.get("company", "Unknown")
    title = job.get("title", "")
    url = job.get("url", "")

    # Cache lookup
    cache_key = _cache_key(company, title, url)
    if cache is None:
        cache = ClassificationCache(cache_file)

    cached = cache.get(cache_key)
    if cached:
        logger.debug("Resume match cache hit for '%s — %s'", company, title)
        return cached

    # Build the user prompt
    location = job.get("location", "Not specified")
    description = job.get("description", "") or job.get("snippet", "") or job.get("description_snippet", "")
    department = job.get("department", "")

    user_prompt = f"""=== JOB DESCRIPTION ===
Company: {company}
Title: {title}
Location: {location}
{"Department: " + department if department else ""}
{"---" if description else ""}
{description or "(No job description available — match based on title and company only)"}

=== CANDIDATE RESUME ===
{resume_text}
"""

    try:
        raw_text = _call_gemini_resume(user_prompt, model, fallback_model)
        parsed = _parse_match_response(raw_text)
        if parsed:
            cache.set(cache_key, parsed)
            cache.save()
            logger.debug(
                "Resume match for '%s — %s': ATS score %d",
                company, title, parsed.get("ats_score", 0)
            )
            return parsed
        else:
            logger.warning("Resume match returned unparseable response for '%s — %s'", company, title)
            return None
    except Exception as exc:
        logger.warning("Resume match failed for '%s — %s': %s", company, title, exc)
        return None


def match_resume_batch(
    jobs: list,
    resume_text: str,
    config: Any = None,
) -> list:
    """Run resume matching for a batch of jobs.

    Injects 'resume_match' key into each job dict in-place.
    Jobs where matching fails get resume_match=None — the job is still included.
    """
    if not resume_text or not jobs:
        for j in jobs:
            j["resume_match"] = None
        return jobs

    if config is None:
        try:
            from job_radar.config.loader import get_config
            config = get_config()
        except Exception:
            pass

    cache_file = "state/resume_match_cache.json"
    if config is not None and hasattr(config, "resume_matcher"):
        cache_file = config.resume_matcher.cache_file
    cache = ClassificationCache(cache_file)

    for job in jobs:
        match = match_resume_to_job(job, resume_text, config=config, cache=cache)
        job["resume_match"] = match

    return jobs
