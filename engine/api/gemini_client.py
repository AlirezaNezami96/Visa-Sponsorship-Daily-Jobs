"""
Gemini AI client for resume tailoring and cover letter generation.

Uses google-genai SDK with:
  - gemini-3.7-flash → resume_tailor  (hybrid reasoning + structured JSON)
  - gemini-3.7-flash → cover_letter   (human-toned text generation)
"""
from __future__ import annotations

import json
import logging
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


# ── Resume Tailoring ──────────────────────────────────────────────────────────

def tailor_resume(
    resume_text: str,
    job_description: str,
    company_name: str,
    job_title: str,
    max_bullet_additions: int = 3,
) -> GeminiResumeOutput:
    """
    Use Gemini 3.7 Flash to rewrite the resume to match the job description.

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
        "Calling Gemini %s for resume tailoring [%s at %s]",
        settings.gemini_pro_model, job_title, company_name,
    )
    t0 = time.perf_counter()

    interaction = client.interactions.create(
        model=settings.gemini_pro_model,
        input=full_input,
        response_mime_type="application/json",
    )
    raw_text = (interaction.output_text or "").strip()

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
    Use Gemini 3.7 Flash to generate a human-toned, pain-point-driven cover letter.

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
        "Calling Gemini %s for cover letter [%s at %s]",
        settings.gemini_flash_model, job_title, company_name,
    )
    t0 = time.perf_counter()

    interaction = client.interactions.create(
        model=settings.gemini_flash_model,
        input=full_input,
    )
    letter_body = (interaction.output_text or "").strip()

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    logger.info("Cover letter generated in %dms (%d chars)", elapsed_ms, len(letter_body))

    if len(letter_body) < 100:
        raise ValueError("Gemini returned an empty or too-short cover letter.")

    return letter_body
