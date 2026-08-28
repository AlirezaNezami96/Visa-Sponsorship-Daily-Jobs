"""AI classification pipeline stage with async execution, bounded concurrency, and budget protection."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from job_radar.llm.router import complete
from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job

logger = logging.getLogger(__name__)

DEFAULT_CLASSIFICATION_PROMPT = """You are an expert technical recruiter and job analyst.
Evaluate the following job posting based on relevance, tech stack, and role fit.

Respond in strict JSON format matching this schema:
{
  "relevance_score": 0.85,
  "classification_track": "ai_ml",
  "is_ai_role": true,
  "classification_reason": "Clear 1-sentence explanation of fit/mismatch",
  "technologies": ["Python", "PyTorch", "Transformers"],
  "seniority": "junior",
  "remote_scope": "worldwide"
}

Rules:
1. relevance_score: Float between 0.0 and 1.0 representing overall match quality.
2. is_ai_role: Boolean, true if role focuses on AI/ML/Data/LLM engineering.
3. classification_track: "ai_ml" | "general_swe" | "data_engineering" | "frontend" | "mobile" | "other"
4. Output valid JSON ONLY.
"""


def build_prompt(job: Job, custom_prompt: Optional[str] = None) -> str:
    system_instruction = custom_prompt or DEFAULT_CLASSIFICATION_PROMPT
    desc_snippet = (job.description or job.snippet or "")[:3500]
    user_content = f"""Company: {job.company}
Title: {job.title}
Location: {job.location}
Apply URL: {job.apply_url or job.url}

Job Description:
{desc_snippet}
"""
    return f"{system_instruction}\n\n---\n\n{user_content}"


def _sync_classify(prompt: str, cache_key: str) -> Optional[Dict[str, Any]]:
    """Synchronous LLM router completion call to be run in worker thread."""
    try:
        res = complete(
            prompt=prompt,
            json_schema={"type": "object"},
            max_tokens=600,
            cache_key=cache_key,
            temperature=0.1,
        )
        if not res or not res.text:
            return None

        cleaned = res.text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.split("```json", 1)[1].rsplit("```", 1)[0].strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned.split("```", 1)[1].rsplit("```", 1)[0].strip()

        return json.loads(cleaned)
    except Exception as e:
        logger.debug("AI LLM router completion failed: %s", e)
        return None


async def classify_job(
    job: Job,
    config: JobSearchConfig,
    semaphore: asyncio.Semaphore,
) -> Optional[Dict[str, Any]]:
    """Perform non-blocking AI classification on a single job using asyncio.to_thread."""
    prompt = build_prompt(job, config.classification_prompt)
    cache_key = f"{job.fingerprint}:{config.classifier_version}"

    async with semaphore:
        try:
            return await asyncio.to_thread(_sync_classify, prompt, cache_key)
        except Exception as e:
            logger.debug("AI classification error for %s: %s", job.title, e)
            return None


async def classify_jobs_stage(
    jobs: List[Job],
    config: JobSearchConfig,
) -> Tuple[List[Job], int]:
    """
    Executes non-blocking AI classification across candidate jobs with bounded concurrency (3).
    Zero-liability: skips classification if no API key is provided, emitting 0 AI events.
    Skips AI classification if the user's spending limit or ACTOR_MAX_TOTAL_CHARGE_USD budget is >= 80% exhausted.
    Returns (qualified_jobs, classified_count).
    """
    if not config.enable_ai_classification or not jobs:
        return jobs, 0

    # 1. Zero-Liability Guard: Ensure LLM API key is present
    has_api_key = bool(
        config.llm_api_key
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GROQ_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    if not has_api_key:
        logger.warning(
            "AI classification requested ('enableAIClassification': true), but no LLM API key ('llmApiKey') was provided. "
            "Skipping AI enrichment without error or charge."
        )
        return jobs, 0

    # Inject user-supplied key into environment for router resolution
    if config.llm_api_key:
        provider = (config.llm_provider or "gemini").lower()
        if provider == "gemini":
            os.environ["GEMINI_API_KEY"] = config.llm_api_key
        elif provider == "groq":
            os.environ["GROQ_API_KEY"] = config.llm_api_key

    # 2. Budget Guard: Check ACTOR_MAX_TOTAL_CHARGE_USD spending ceiling
    max_charge_str = os.environ.get("ACTOR_MAX_TOTAL_CHARGE_USD")
    if max_charge_str:
        try:
            max_charge = float(max_charge_str)
            estimated_base_cost = 0.05 + (len(jobs) * 0.002)
            if max_charge > 0 and (estimated_base_cost / max_charge) >= 0.80:
                logger.warning(
                    "ACTOR_MAX_TOTAL_CHARGE_USD ($%.2f) budget >= 80%% exhausted (projected base cost: $%.3f). Skipping AI classification to protect user wallet.",
                    max_charge,
                    estimated_base_cost,
                )
                return jobs, 0
        except ValueError:
            pass

    max_calls = config.max_ai_calls if config.max_ai_calls is not None else 200
    min_score = config.minimum_relevance_score or 0.0
    semaphore = asyncio.Semaphore(3)

    classified_count = 0
    passed_jobs: List[Job] = []

    for job in jobs:
        if classified_count < max_calls:
            clf = await classify_job(job, config, semaphore)
            if clf:
                classified_count += 1
                score_raw = clf.get("relevance_score")
                if score_raw is not None:
                    # Normalize score to 0.0 - 1.0 if returned as 0-100
                    score = float(score_raw)
                    if score > 1.0:
                        score = score / 100.0
                    job.relevance_score = round(score, 2)

                job.classification_track = clf.get("classification_track") or clf.get("track")
                job.classification_reason = clf.get("classification_reason") or clf.get("why")
                job.relevance_why = job.classification_reason
                job.is_ai_role = clf.get("is_ai_role") or clf.get("is_ai_ml_day_to_day")
                job.remote_scope_ai = clf.get("remote_scope")

                if clf.get("technologies") and isinstance(clf["technologies"], list):
                    existing_tech = set(job.technologies)
                    for t in clf["technologies"]:
                        if t not in existing_tech:
                            job.technologies.append(t)
        else:
            job.metadata["ai_skipped"] = True

        # Apply minimum relevance score filter if classified
        if job.relevance_score is not None and job.relevance_score < min_score:
            continue

        passed_jobs.append(job)

    logger.info("AI classification stage complete: %d jobs classified", classified_count)
    return passed_jobs, classified_count
