"""LLM-based relevance classification, remote scope validation, and visa signal extraction for job listings.

Implements the single-pass combined LLM auditor (relevance, track, seniority,
remote scope, visa sponsorship mention, and resume matching in one call).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from job_radar.classifiers.cache import ClassificationCache, make_cache_key
from job_radar.config import RadarConfig, get_config
from job_radar.models import CombinedLLMResponse, Job, VisaStatus
from job_radar.visa.evaluator import score_job_visa

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert AI/ML recruitment auditor and technical screener.
Evaluate the job posting below for an early-career AI/ML candidate.

Respond with strict JSON adhering to this schema:
{
  "relevance": 85,
  "why": "Clear 1-sentence explanation of what the role is and why it fits/fails.",
  "is_ai_ml_day_to_day": true,
  "track_guess": "internship",
  "seniority_guess": "junior",
  "remote_scope": "worldwide",
  "allowed_regions": ["US", "Canada"],
  "visa_mention": "sponsors",
  "visa_quote": null,
  "salary_min": null,
  "salary_max": null,
  "salary_currency": null,
  "salary_interval": null,
  "resume_match_score": null,
  "resume_match_why": null
}

Field definitions & rules:
1. "relevance": 0 to 100 based on alignment with AI/ML internship / early-career engineers (0 if not an AI/ML role).
2. "is_ai_ml_day_to_day": true ONLY if primary work is training, tuning, building, researching, or deploying AI/ML/CV/NLP/LLM models or AI agents.
3. "track_guess":
   - "internship": student, intern, co-op, fellowship, trainee roles.
   - "engineer": junior, entry-level, associate, or early-career IC (0-2 years exp).
   - "borderline": prompt engineering, data science, solutions engineering.
   - "other": senior (3+ yrs required), staff, principal, lead, manager, director, or non-AI.
4. "seniority_guess": "intern" | "junior" | "mid" | "senior"
5. "remote_scope":
   - "worldwide": anywhere in the world, global remote.
   - "region_restricted": remote, but restricted to specific country/timezones.
   - "onsite_only": requires in-office presence.
   - "unknown": not specified.
6. "visa_mention":
   - "sponsors": explicit offer to sponsor visas (H-1B, Skilled Worker, etc.) or relocation assistance.
   - "opt_friendly": mentions OPT / STEM-OPT or student work authorization.
   - "no": explicit refusal (e.g. 'no visa sponsorship', 'must already have right to work without sponsorship', 'citizens only').
   - "unspecified": no mention in description.
7. "visa_quote": direct quote from the job description regarding sponsorship/relocation if present, else null.
8. "resume_match_score": 0 to 100 integer if candidate resume is provided, else null.
9. Return ONLY valid JSON, no markdown fences, no extra text.
"""

LLM_CLASSIFIER_PROMPT = SYSTEM_PROMPT


class JobClassification(dict):
    """Classification result container."""
    pass



def _cache_key(company: str, title: str, location: str, url: str) -> str:
    return make_cache_key(company, title, location=location, url=url)


def _call_gemini(user_prompt: str, model_name: str) -> str:
    """Call LLM via router with waterfall fallback."""
    import sys
    if "classify_relevance" in sys.modules:
        cr = sys.modules["classify_relevance"]
        if hasattr(cr, "_call_gemini") and cr._call_gemini is not _call_gemini:
            return cr._call_gemini(user_prompt, model_name)

    from job_radar.llm.router import complete

    full_input = f"{SYSTEM_PROMPT}\n\n---\n\n{user_prompt}"
    res = complete(
        prompt=full_input,
        json_schema={"type": "object"},
        max_tokens=1000,
    )
    return (res.text or "").strip()


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
    resp = requests.post(url, headers=headers, json=payload, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"].strip()


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
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def classify_single_job(
    job: dict,
    config: Optional[RadarConfig] = None,
    cache: Optional[ClassificationCache] = None,
    resume_text: Optional[str] = None,
) -> dict:
    """
    Classify a single job using the combined single-pass LLM prompt with fail-open fallback.
    """
    cfg = config or get_config()
    company = job.get("company", "Unknown")
    title = job.get("title", "Untitled")
    location = job.get("location", "")
    url = job.get("url", "")
    desc = job.get("description") or job.get("description_text") or job.get("snippet") or ""

    # Hash full available text for cache key (not truncated)
    key = make_cache_key(
        company=company,
        title=title,
        description=desc,
        resume_text=resume_text or "",
        location=location,
        url=url,
    )

    if cache:
        cached = cache.get(key)
        if cached:
            return cached

    parsed: Optional[dict] = None
    raw_text: Optional[str] = None

    if cfg.classifier.enabled:
        provider = (cfg.classifier.provider or "gemini").lower()
        model = cfg.classifier.model

        # Build prompt payload (truncate description to 4000 chars for token limits)
        user_prompt = f"Company: {company}\nTitle: {title}\nLocation: {location}\nURL: {url}\n\nJob Description:\n{desc[:4000]}"
        if resume_text:
            user_prompt += f"\n\nCandidate Resume:\n{resume_text[:2500]}"

        try:
            if provider == "gemini" or os.environ.get("GEMINI_API_KEY"):
                raw_text = _call_gemini(user_prompt, model or "gemini-3.6-flash")
            elif provider == "anthropic" or os.environ.get("ANTHROPIC_API_KEY"):
                raw_text = _call_anthropic(user_prompt, model or "claude-3-5-haiku-20241022")
            elif provider == "openai" or os.environ.get("OPENAI_API_KEY"):
                raw_text = _call_openai(user_prompt, model or "gpt-4o-mini")
        except Exception as exc:
            logger.warning("LLM classification failed for '%s — %s' (%s): %s — failing open", company, title, provider, exc)

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

    # Fail-open fallback to deterministic evaluation if LLM was disabled or failed
    if not parsed:
        from job_radar.filters import match_track
        detected_track = match_track(title, config=cfg)
        senior_list = cfg.tracks.seniority_exclude if hasattr(cfg, "tracks") else ["senior", "staff", "principal", "lead", "architect"]
        is_senior = any(re.search(r"\b" + re.escape(exc) + r"\b", title.lower()) for exc in senior_list)
        is_remote = any(w in (location or "").lower() for w in ("remote", "anywhere", "worldwide", "virtual")) or bool(job.get("remote"))

        if is_senior:
            track = "other"
            is_ai = True
        elif detected_track == "internship":
            track = "internship"
            is_ai = True
        elif detected_track in ("engineer", "borderline"):
            track = "engineer"
            is_ai = True
        else:
            track = "other"
            is_ai = False

        parsed = {
            "relevance": 75 if is_remote and is_ai and not is_senior else 40,
            "why": f"{'Internship' if track == 'internship' else 'Engineering'} role matching AI/ML patterns (deterministic fallback).",
            "is_ai_ml_day_to_day": is_ai,
            "track_guess": track,
            "seniority_guess": "senior" if is_senior else ("intern" if track == "internship" else "junior"),
            "remote_scope": "worldwide" if is_remote else "onsite_only",
            "allowed_regions": ["Worldwide" if is_remote else location],
            "visa_mention": "unspecified",
            "visa_quote": None,
            "salary_min": job.get("salary_min"),
            "salary_max": job.get("salary_max"),
            "salary_currency": job.get("salary_currency"),
            "salary_interval": job.get("salary_interval"),
            "resume_match_score": None,
            "resume_match_why": None,
            "_fallback": True,
        }

    # Standardize legacy keys for downstream components without overriding explicit keys
    if "is_ai_ml_role" not in parsed:
        parsed["is_ai_ml_role"] = parsed.get("is_ai_ml_day_to_day", False)
    if "relevance_score" not in parsed:
        parsed["relevance_score"] = parsed.get("relevance", 0)
    if "track" not in parsed:
        parsed["track"] = parsed.get("track_guess", "other")
    elif parsed.get("track") == "new_grad_engineer" and "track_guess" in parsed:
        parsed["track"] = "engineer"

    if cache:
        cache.set(key, parsed)

    return parsed


def classify_and_filter_jobs(
    jobs: List[dict],
    config: Optional[RadarConfig] = None,
    resume_text: Optional[str] = None,
) -> Tuple[List[dict], Dict[str, Any]]:
    """
    Filter candidate jobs through the single-pass combined LLM + Visa classification pass.
    """
    cfg = config or get_config()
    cache = ClassificationCache(cfg.classifier.cache_file)
    min_score = cfg.classifier.min_relevance_score
    allowed_scopes = set(cfg.geography.allowed_remote_scopes)
    visa_weights = cfg.visa.weights.__dict__ if hasattr(cfg, "visa") and hasattr(cfg.visa, "weights") else None

    qualified_jobs = []
    stats = {
        "total_evaluated": len(jobs),
        "passed": 0,
        "rejected_not_ai": 0,
        "rejected_seniority": 0,
        "rejected_not_remote": 0,
        "rejected_low_score": 0,
        "visa_status_counts": {},
    }

    for job in jobs:
        clf = classify_single_job(job, config=cfg, cache=cache, resume_text=resume_text)
        is_ai = clf.get("is_ai_ml_day_to_day", clf.get("is_ai_ml_role", False))
        track = clf.get("track_guess", clf.get("track", "other"))
        seniority = clf.get("seniority_guess", "")
        remote_scope = clf.get("remote_scope", "unknown")
        score = clf.get("relevance", clf.get("relevance_score", 0))

        # 1. Must be an AI/ML role
        if not is_ai:
            stats["rejected_not_ai"] += 1
            continue

        # 2. Track & Seniority filter
        if track in ("too_senior", "other", "not_ai_ml") or seniority == "senior":
            # If deterministic prefilter confirmed internship or engineer, keep if relevance is high
            pre_track = job.get("prefilter_track")
            if pre_track not in ("internship", "engineer") or score < 60:
                stats["rejected_seniority"] += 1
                continue
            track = pre_track

        # 3. Check remote scope
        is_explicit_remote = bool(job.get("remote")) or any(
            w in (job.get("location") or "").lower() for w in ("remote", "worldwide", "anywhere")
        )
        if remote_scope in ("onsite_only", "hybrid", "onsite") and not is_explicit_remote:
            stats["rejected_not_remote"] += 1
            continue

        # 4. Relevance score threshold
        if score < min_score:
            stats["rejected_low_score"] += 1
            continue

        # 5. Visa Scoring Pass
        visa_mention = clf.get("visa_mention")
        visa_quote = clf.get("visa_quote")
        visa_status, visa_score, visa_evidence = score_job_visa(
            job=job,
            llm_visa_mention=visa_mention,
            llm_visa_quote=visa_quote,
            weights=visa_weights,
        )

        stats["visa_status_counts"][visa_status] = stats["visa_status_counts"].get(visa_status, 0) + 1

        enriched_job = dict(job)
        enriched_job["classified_track"] = "internship" if track == "internship" else "engineer"
        enriched_job["track"] = enriched_job["classified_track"]
        enriched_job["remote_scope"] = remote_scope
        enriched_job["allowed_regions"] = clf.get("allowed_regions", [])
        enriched_job["relevance_score"] = score
        enriched_job["why_matched"] = clf.get("why", "")

        # Compensation enrichment from LLM if structured fields were missing
        if clf.get("salary_min") and not enriched_job.get("salary_min"):
            enriched_job["salary_min"] = clf.get("salary_min")
        if clf.get("salary_max") and not enriched_job.get("salary_max"):
            enriched_job["salary_max"] = clf.get("salary_max")
        if clf.get("salary_currency") and not enriched_job.get("salary_currency"):
            enriched_job["salary_currency"] = clf.get("salary_currency")

        # Visa enrichment
        enriched_job["visa_status"] = visa_status
        enriched_job["visa_score"] = visa_score
        enriched_job["visa_evidence"] = visa_evidence
        enriched_job["visa_sponsorship"] = visa_status in (VisaStatus.SPONSORS.value, VisaStatus.LIKELY.value)

        # Resume match enrichment
        if clf.get("resume_match_score") is not None:
            enriched_job["resume_match_score"] = clf.get("resume_match_score")
            enriched_job["resume_match_why"] = clf.get("resume_match_why")
            enriched_job["resume_match"] = {
                "ats_score": clf.get("resume_match_score"),
                "score_rationale": clf.get("resume_match_why") or "",
                "keywords_to_add": [],
                "resume_editing_prompt": "",
            }

        qualified_jobs.append(enriched_job)
        stats["passed"] += 1

    cache.save()
    logger.info(
        "Combined classification complete: %d/%d passed (rejected: %d not-AI, %d senior, %d non-remote, %d low-score)",
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
