"""LLM-based relevance classification and remote scope validation for job listings."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from job_radar.classifiers.cache import ClassificationCache
from job_radar.config import RadarConfig, get_config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert AI/ML recruitment auditor and technical screener.
Evaluate the job posting below to verify if it is genuinely an AI, Machine Learning, or Data Science role for internships or early-career engineers, and determine its remote eligibility.

Respond with strict JSON adhering to this schema:
{
  "is_ai_ml_role": true,
  "track": "internship", // "internship" | "new_grad_engineer" | "too_senior" | "not_ai_ml"
  "remote_scope": "worldwide", // "worldwide" | "region_restricted" | "hybrid" | "onsite" | "unclear"
  "allowed_regions": ["US", "Canada"], // list of eligible countries/regions or ["Worldwide"]
  "relevance_score": 85, // integer 0 to 100
  "why": "Clear 1-sentence explanation of what the role is and why it fits/fails."
}

Rules:
1. "is_ai_ml_role": true ONLY if the primary day-to-day work is training, tuning, building, researching, or deploying AI/ML/CV/NLP/LLM models or AI agents. If it is a generic backend/frontend/DevOps role merely using AI tools or at an AI company, return false.
2. "track":
   - "internship": student, intern, co-op, fellowship, trainee roles.
   - "new_grad_engineer": junior, entry-level, associate, or early-career IC (0-2 years exp).
   - "too_senior": senior, staff, principal, lead, manager, director, or 3+ years required exp.
   - "not_ai_ml": not an AI/ML engineering or research role.
3. "remote_scope":
   - "worldwide": anywhere in the world, global remote.
   - "region_restricted": remote, but restricted to specific country/timezones (e.g. US only, EMEA only).
   - "hybrid" or "onsite": requires in-office presence.
   - "unclear": not specified.
4. "relevance_score": 0 to 100 based on alignment with early-career AI/ML seekers.
5. Return ONLY valid JSON, no markdown fences, no explanatory text outside the JSON.
"""

LLM_CLASSIFIER_PROMPT = SYSTEM_PROMPT


class JobClassification(dict):
    """Classification result container."""
    pass


def _cache_key(company: str, title: str, location: str, url: str) -> str:
    """Generate deterministic hash key for classification cache."""
    raw = f"{company.strip().lower()}|{title.strip().lower()}|{location.strip().lower()}|{url.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _call_gemini(user_prompt: str, model_name: str) -> str:
    """Call Google GenAI with gemini-3.6-flash using client.interactions.create."""
    import sys
    if "classify_relevance" in sys.modules:
        cr = sys.modules["classify_relevance"]
        if hasattr(cr, "_call_gemini") and cr._call_gemini is not _call_gemini:
            return cr._call_gemini(user_prompt, model_name)

    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    full_input = f"{SYSTEM_PROMPT}\n\n---\n\n{user_prompt}"
    interaction = client.interactions.create(
        model=model_name,
        input=full_input,
        response_mime_type="application/json",
    )
    return (interaction.output_text or "").strip()


def _call_anthropic(user_prompt: str, model_name: str) -> str:
    """Call Anthropic API."""
    import requests

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set")

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model_name,
        "max_tokens": 1000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    blocks = data.get("content", [])
    if blocks and "text" in blocks[0]:
        return blocks[0]["text"].strip()
    return ""


def _call_openai(user_prompt: str, model_name: str) -> str:
    """Call OpenAI API."""
    import requests

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "").strip()
    return ""


def classify_single_job(
    job: dict,
    config: Optional[RadarConfig] = None,
    cache: Optional[ClassificationCache] = None,
) -> dict:
    """Classify a single job posting via LLM or rule-based fallback."""
    cfg = config or get_config()
    company = job.get("company", "Unknown")
    title = job.get("title", "")
    location = job.get("location", "")
    department = job.get("department", "")
    snippet = job.get("snippet", "") or job.get("description_snippet", "")
    url = job.get("url", "")

    key = _cache_key(company, title, location, url)
    if cache:
        cached = cache.get(key)
        if cached:
            return cached

    # Construct prompt
    user_prompt = f"""Evaluate this job posting:
- Company: {company}
- Title: {title}
- Location: {location or 'Not specified'}
- Department / Team: {department or 'Not specified'}
- Summary / Excerpt: {snippet or 'N/A'}
- URL: {url}
"""

    provider = cfg.classifier.provider.lower()
    model = cfg.classifier.model
    raw_text = ""
    parsed: Optional[dict] = None

    if cfg.classifier.enabled:
        try:
            if provider == "gemini" or os.environ.get("GEMINI_API_KEY"):
                raw_text = _call_gemini(user_prompt, model or "gemini-3.6-flash")
            elif provider == "anthropic" or os.environ.get("ANTHROPIC_API_KEY"):
                raw_text = _call_anthropic(user_prompt, model or "claude-3-5-haiku-20241022")
            elif provider == "openai" or os.environ.get("OPENAI_API_KEY"):
                raw_text = _call_openai(user_prompt, model or "gpt-4o-mini")
        except Exception as exc:
            logger.warning("LLM classification failed for '%s — %s' (%s): %s", company, title, provider, exc)

    if raw_text:
        try:
            cleaned = raw_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned.split("```json", 1)[1].rsplit("```", 1)[0].strip()
            elif cleaned.startswith("```"):
                cleaned = cleaned.split("```", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(cleaned)
        except Exception as parse_exc:
            logger.warning("Failed to parse LLM JSON response: %s", parse_exc)

    # Fallback to rule-based classification if LLM is disabled or failed
    if not parsed:
        from job_radar.filters import match_track
        detected_track = match_track(title, config=cfg)
        senior_list = cfg.tracks.seniority_exclude if hasattr(cfg, "tracks") else ["senior", "staff", "principal", "lead", "architect"]
        is_senior = any(re.search(r"\b" + re.escape(exc) + r"\b", title.lower()) for exc in senior_list)
        is_remote = any(w in (location or "").lower() for w in ("remote", "anywhere", "worldwide", "virtual")) or bool(job.get("remote"))

        if is_senior:
            track = "too_senior"
            is_ai = True
        elif detected_track == "internship":
            track = "internship"
            is_ai = True
        elif detected_track in ("engineer", "borderline"):
            track = "new_grad_engineer"
            is_ai = True
        else:
            track = "not_ai_ml"
            is_ai = False

        parsed = {
            "is_ai_ml_role": is_ai,
            "track": track,
            "remote_scope": "worldwide" if is_remote else "onsite",
            "allowed_regions": ["Worldwide" if is_remote else location],
            "relevance_score": 75 if is_remote and is_ai and track != "too_senior" else 40,
            "why": f"{'Internship' if track == 'internship' else 'Engineering'} role matching AI/ML patterns (rule-based evaluation).",
            "_fallback": True,
        }

    if cache:
        cache.set(key, parsed)

    return parsed


def classify_and_filter_jobs(
    jobs: List[dict],
    config: Optional[RadarConfig] = None,
) -> Tuple[List[dict], Dict[str, Any]]:
    """Filter candidate jobs through the LLM classification pass."""
    cfg = config or get_config()
    cache = ClassificationCache(cfg.classifier.cache_file)
    min_score = cfg.classifier.min_relevance_score
    allowed_scopes = set(cfg.geography.allowed_remote_scopes)

    qualified_jobs = []
    stats = {
        "total_evaluated": len(jobs),
        "passed": 0,
        "rejected_not_ai": 0,
        "rejected_seniority": 0,
        "rejected_not_remote": 0,
        "rejected_low_score": 0,
    }

    for job in jobs:
        clf = classify_single_job(job, config=cfg, cache=cache)
        is_ai = clf.get("is_ai_ml_role", False)
        track = clf.get("track", "not_ai_ml")
        remote_scope = clf.get("remote_scope", "unclear")
        score = clf.get("relevance_score", 0)

        # 1. Must be an AI/ML role
        if not is_ai:
            stats["rejected_not_ai"] += 1
            continue

        # 2. Track must be internship or early-career engineer
        if track in ("too_senior", "not_ai_ml"):
            stats["rejected_seniority"] += 1
            continue

        # 3. Check remote scope (worldwide or region_restricted)
        is_explicit_remote = bool(job.get("remote")) or any(
            w in (job.get("location") or "").lower() for w in ("remote", "worldwide", "anywhere")
        )
        if remote_scope not in allowed_scopes and not is_explicit_remote:
            stats["rejected_not_remote"] += 1
            continue

        # 4. Relevance score threshold
        if score < min_score:
            stats["rejected_low_score"] += 1
            continue

        enriched_job = dict(job)
        enriched_job["classified_track"] = "internship" if track == "internship" else "engineer"
        enriched_job["remote_scope"] = remote_scope
        enriched_job["allowed_regions"] = clf.get("allowed_regions", [])
        enriched_job["relevance_score"] = score
        enriched_job["why_matched"] = clf.get("why", "")
        qualified_jobs.append(enriched_job)
        stats["passed"] += 1

    cache.save()
    logger.info(
        "Classification complete: %d/%d passed (rejected: %d not-AI, %d senior, %d non-remote, %d low-score)",
        stats["passed"],
        stats["total_evaluated"],
        stats["rejected_not_ai"],
        stats["rejected_seniority"],
        stats["rejected_not_remote"],
        stats["rejected_low_score"],
    )
    return qualified_jobs, stats


classify_job_llm = classify_single_job


def heuristic_classify_job(job: dict, config: Optional[RadarConfig] = None) -> dict:
    cfg = config or get_config()
    return classify_single_job(job, config=cfg)


def parse_llm_json_response(raw_text: str) -> Optional[dict]:
    if not raw_text:
        return None
    try:
        cleaned = raw_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.split("```json", 1)[1].rsplit("```", 1)[0].strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned.split("```", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(cleaned)
    except Exception:
        return None
