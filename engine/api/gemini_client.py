"""
Gemini AI client for resume tailoring and cover letter generation.

Uses google-genai SDK with:
  - gemini-3.7-flash → resume_tailor  (hybrid reasoning + structured JSON)
  - gemini-3.7-flash → cover_letter   (human-toned text generation)
"""
from __future__ import annotations

import json
import logging
import os
import textwrap
import time
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from .config import get_settings
from .models import GeminiResumeOutput

logger = logging.getLogger(__name__)

# Load prompt templates once at import time
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    raise FileNotFoundError(f"Prompt template not found: {path}")


def _get_client() -> genai.Client:
    key = get_settings().gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
    key = key.strip().strip("'\"")
    if not key or key == "your-gemini-api-key-here":
        raise ValueError(
            "GEMINI_API_KEY is not configured or is still the placeholder value. "
            "Please add your valid Gemini API key to engine/.env and restart the server."
        )
    return genai.Client(api_key=key)


def _generate_with_fallback(
    client: genai.Client,
    primary_model: str,
    contents: str,
    config: Optional[types.GenerateContentConfig] = None,
) -> str:
    """Generate content with automatic fallback to secondary models on 503/429/errors."""
    # Ordered fallback: confirmed available models via API as of 2026-08
    # gemini-3.6-flash is the stable default; others are tried on 503/404
    fallbacks = [
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-flash-latest",
    ]
    candidate_models = [primary_model] + [m for m in fallbacks if m != primary_model]
    seen: set = set()
    models_to_try = [m for m in candidate_models if not (m in seen or seen.add(m))]

    last_error = None
    for model_name in models_to_try:
        try:
            logger.info("Calling Gemini model: %s", model_name)
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
            text = (response.text or "").strip()
            if text:
                return text
        except Exception as exc:
            last_error = exc
            logger.warning("Gemini model %s failed: %s — trying next fallback", model_name, exc)

    raise RuntimeError(f"All Gemini models failed. Last error: {last_error}") from last_error


# ── Resume Tailoring ──────────────────────────────────────────────────────────

def tailor_resume(
    resume_text: str,
    job_description: str,
    company_name: str,
    job_title: str,
    max_bullet_additions: int = 3,
) -> GeminiResumeOutput:
    """
    Use Gemini 3.7 Flash (with fallback) to rewrite the resume to match the job description.

    Returns a GeminiResumeOutput parsed from the model's structured JSON output.
    """
    settings = get_settings()
    client = _get_client()

    system_prompt = _load_prompt("resume_tailor_v1.txt")

    user_content = textwrap.dedent(f"""
        COMPANY: {company_name}
        ROLE: {job_title}
        MAX_NEW_BULLETS: {max_bullet_additions}

        ===== MASTER RESUME =====
        {resume_text.strip()}

        ===== JOB DESCRIPTION =====
        {job_description.strip()[:8000]}
    """).strip()

    full_input = f"{system_prompt}\n\n---\n\n{user_content}"

    logger.info(
        "Calling Gemini for resume tailoring [%s at %s]",
        job_title, company_name,
    )
    t0 = time.perf_counter()

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
    )
    raw_text = _generate_with_fallback(
        client=client,
        primary_model=settings.gemini_pro_model,
        contents=full_input,
        config=config,
    )

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    logger.info("Resume tailoring completed in %dms", elapsed_ms)

    return _parse_resume_output(raw_text)


def _parse_resume_output(raw_text: str) -> GeminiResumeOutput:
    """Parse and validate the structured JSON output from Gemini."""
    try:
        # Strip any accidental markdown fences
        text = raw_text
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]

        data = json.loads(text)
        return GeminiResumeOutput.model_validate(data)
    except Exception as exc:
        logger.error("Failed to parse Gemini resume output: %s\nRaw: %.500s", exc, raw_text)
        raise ValueError(f"Gemini returned invalid JSON for resume: {exc}") from exc


# ── Cover Letter Generation ───────────────────────────────────────────────────

def generate_cover_letter(
    resume_text: str,
    job_description: str,
    company_name: str,
    job_title: str,
    user_name: str,
    tone: str = "professional",
) -> str:
    """
    Use Gemini 3.7 Flash (with fallback) to generate a human-toned cover letter.

    Returns the body text of the cover letter (3 paragraphs, no headers/sign-off).
    """
    settings = get_settings()
    client = _get_client()

    system_prompt = _load_prompt("cover_letter_v1.txt")

    user_content = textwrap.dedent(f"""
        APPLICANT_NAME: {user_name}
        COMPANY: {company_name}
        ROLE: {job_title}
        TONE: {tone}

        ===== MASTER RESUME =====
        {resume_text.strip()[:4000]}

        ===== JOB DESCRIPTION =====
        {job_description.strip()[:6000]}
    """).strip()

    full_input = f"{system_prompt}\n\n---\n\n{user_content}"

    logger.info(
        "Calling Gemini for cover letter [%s at %s]",
        job_title, company_name,
    )
    t0 = time.perf_counter()

    letter_body = _generate_with_fallback(
        client=client,
        primary_model=settings.gemini_flash_model,
        contents=full_input,
    )

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    logger.info("Cover letter generated in %dms (%d chars)", elapsed_ms, len(letter_body))

    if len(letter_body) < 100:
        raise ValueError("Gemini returned an empty or too-short cover letter.")

    return letter_body
