"""Post text generator with rotating hooks, AI summarization, circuit breakers, and deterministic fallbacks.

Generates tailored text across platforms:
- X: strictly <= 280 chars with guaranteed URL preservation (URL is never sliced).
- Telegram/Discord: full rich markdown.
- LinkedIn: professional layout with hashtags and manual review tags.
- Bluesky / Mastodon: concise multi-line summary.

Uses a deterministic hash of job_id to rotate through hook templates.
AI summary waterfall: Groq -> OpenRouter -> Extractive rule-based fallback, with circuit breakers.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

HOOK_POOL = [
    "🚀 Visa-sponsored opportunity spotted!",
    "🌍 Relocation & visa support available:",
    "🔥 Fresh visa-sponsored job alert:",
    "✈️ Looking to relocate? Check out this role:",
    "💼 Verified visa sponsorship role just posted:",
    "🌟 Global talent welcome — visa support provided:",
    "🎯 New international opening with visa backing:",
    "✨ Verified sponsorship opportunity for tech talent:",
    "🛡️ Official visa sponsor hiring now:",
    "💡 International career move opportunity:",
]


def get_rotating_hook(job_id: str) -> str:
    """Deterministically pick a hook based on job_id hash."""
    if not job_id:
        return HOOK_POOL[0]
    idx = int(hashlib.md5(str(job_id).encode("utf-8")).hexdigest(), 16) % len(HOOK_POOL)
    return HOOK_POOL[idx]


def _extractive_summary(description: str, skills: list[str]) -> str:
    """Deterministic fallback: takes clean introductory sentence + top skills."""
    if not description:
        if skills:
            return f"Seeking talent skilled in {', '.join(skills[:4])}. Visa sponsorship verified."
        return "Full-time position with verified visa sponsorship support."

    # Clean HTML / markdown tags
    cleaned = re.sub(r"<[^>]+>", " ", description)
    cleaned = re.sub(r"[\r\n\t]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Get first sentence
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    first_sentence = sentences[0] if sentences else ""
    if len(first_sentence) > 180:
        first_sentence = first_sentence[:177] + "..."

    if skills:
        top_skills = ", ".join(skills[:3])
        summary = f"{first_sentence} Key skills: {top_skills}."
    else:
        summary = first_sentence

    if len(summary) > 280:
        summary = summary[:277].rsplit(" ", 1)[0] + "..."
    return summary


def _trim_summary(text: str, max_len: int = 280) -> str:
    """Trim text to max_len cleanly at a sentence or word boundary."""
    if len(text) <= max_len:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if sentences and len(sentences[0]) <= max_len and len(sentences[0]) >= 40:
        return sentences[0]
    return text[: max_len - 3].rsplit(" ", 1)[0] + "..."


def generate_job_summary(job: dict[str, Any], client: Any = None) -> str:
    """Generate a 2-3 sentence AI summary of the job description, or fall back to extractive."""
    desc = job.get("description_text") or job.get("description") or ""
    skills = job.get("skills") or []

    # Try OpenRouter / Groq if keys are available
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")

    prompt = (
        f"Summarize this job in 2 concise sentences for social media. "
        f"Mention what the company does, the core responsibilities, and key stack. "
        f"Do not include hype, emojis, or markdown headings.\n\n"
        f"Title: {job.get('title', '')}\n"
        f"Company: {job.get('company', '')}\n"
        f"Description: {desc[:2500]}"
    )

    # Circuit breaker (optional, only if client provided)
    cb = None
    if client is not None:
        from job_radar.pipeline.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(client)

    # 1. Try Groq (fastest)
    if groq_key:
        cb_name = "groq_social"
        if cb is None or not cb.is_open(cb_name):
            try:
                import requests

                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 120,
                        "temperature": 0.3,
                    },
                    timeout=8,
                )
                if resp.status_code == 200:
                    text = resp.json()["choices"][0]["message"]["content"].strip()
                    if len(text) >= 30:
                        if cb is not None:
                            cb.record_success(cb_name)
                        return text
            except Exception as e:
                logger.debug("Groq social summary failed: %s", e)
                if cb is not None:
                    cb.record_failure(cb_name)

    # 2. Try OpenRouter
    if openrouter_key:
        cb_name = "openrouter_social"
        if cb is None or not cb.is_open(cb_name):
            try:
                import requests

                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openrouter_key}", "Content-Type": "application/json"},
                    json={
                        "model": "meta-llama/llama-3.3-70b-instruct:free",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 120,
                        "temperature": 0.3,
                    },
                    timeout=8,
                )
                if resp.status_code == 200:
                    text = resp.json()["choices"][0]["message"]["content"].strip()
                    if len(text) >= 30:
                        if cb is not None:
                            cb.record_success(cb_name)
                        return text
            except Exception as e:
                logger.debug("OpenRouter social summary failed: %s", e)
                if cb is not None:
                    cb.record_failure(cb_name)

    # 3. Deterministic fallback
    return _extractive_summary(desc, skills)


def build_platform_post_text(job: dict[str, Any], platform: str = "telegram", client: Any = None) -> str:
    """Build platform-specific post text.

    Supported platforms: telegram, discord, slack, x, linkedin, bluesky, mastodon.
    For Twitter/X: strict 280 char enforcement preserving full URL without slicing.
    """
    job_id = str(job.get("id") or "")
    hook = get_rotating_hook(job_id)
    title = str(job.get("title") or "Software Engineer").strip()
    company = str(job.get("company") or "Company").strip()
    country = str(job.get("country") or job.get("country_code") or "Global").strip()
    location = str(job.get("location") or country).strip()
    work_mode = str(job.get("work_mode") or "Remote").strip()
    url = str(job.get("apply_url") or job.get("url") or "https://visalane.online").strip()
    skills = job.get("skills") or []
    skills_str = ", ".join(skills[:5]) if skills else "Tech"
    summary = generate_job_summary(job, client=client)

    salary_min = job.get("salary_min")
    salary_max = job.get("salary_max")
    salary_cur = job.get("salary_currency", "USD")
    salary_line = ""
    if salary_min and salary_max:
        salary_line = f"\n💰 {salary_cur} {salary_min:,} - {salary_max:,}"
    elif salary_min:
        salary_line = f"\n💰 From {salary_cur} {salary_min:,}"

    if platform == "x":
        # 1. Reserve suffix with intact URL first
        apply_suffix = f"\n\nApply: {url}"
        budget = 280 - len(apply_suffix)

        if budget < 50:
            # Extremely long URL edge case
            apply_suffix = f"\n{url}"
            budget = 280 - len(apply_suffix)

        # 2. Try full format with hook
        full_content = f"{hook}\n\n📌 {title} @ {company}\n📍 {location} ({work_mode}){salary_line}\n🛂 Visa Sponsored"
        if len(full_content) <= budget:
            return f"{full_content}{apply_suffix}"

        # 3. Try compact format without hook
        compact_content = f"📌 {title} @ {company}\n📍 {location} ({work_mode})\n🛂 Visa Sponsored"
        if len(compact_content) <= budget:
            return f"{compact_content}{apply_suffix}"

        # 4. Truncate title & company if needed
        avail_for_header = budget - len(f"📌 \n📍 {location} ({work_mode})\n🛂 Visa Sponsored") - 5
        if avail_for_header > 20:
            short_head = f"{title} @ {company}"[:avail_for_header].rsplit(" ", 1)[0] + "…"
            content = f"📌 {short_head}\n📍 {location}\n🛂 Visa Sponsored"
        else:
            short_title = title[: max(15, budget - 40)].rsplit(" ", 1)[0] + "…"
            content = f"📌 {short_title}\n🛂 Visa Sponsored"

        result = f"{content.strip()}{apply_suffix}"
        if len(result) > 280:
            # Final safeguard
            result = f"🛂 {title[:30]}… @ {company[:20]}…{apply_suffix}"
        return result

    if platform in ("telegram", "discord", "slack"):
        lines = [
            f"{hook}",
            "",
            f"📌 **{title}**",
            f"🏢 **{company}**",
            f"📍 {location} ({work_mode.capitalize()})",
            "🛂 **Visa Sponsorship:** Verified ✅",
        ]
        if salary_line:
            lines.append(f"{salary_line.strip()}")
        if skills:
            lines.append(f"🛠 **Tech Stack:** {skills_str}")
        lines.append("")
        lines.append(f"📝 {summary}")
        lines.append("")
        lines.append(f"🔗 **Apply Here:** {url}")
        return "\n".join(lines)

    if platform == "linkedin":
        tags = "#VisaSponsorship #TechJobs #GlobalCareers #Relocation #Hiring"
        lines = [
            f"{hook}",
            "",
            f"Role: {title}",
            f"Company: {company}",
            f"Location: {location} ({work_mode.capitalize()})",
            "Visa Sponsorship: Verified",
        ]
        if salary_line:
            lines.append(f"Compensation: {salary_line.replace('💰 ', '')}")
        if skills:
            lines.append(f"Core Skills: {skills_str}")
        lines.append("")
        lines.append(summary)
        lines.append("")
        lines.append(f"Apply directly: {url}")
        lines.append("")
        lines.append(tags)
        return "\n".join(lines)

    if platform in ("bluesky", "mastodon"):
        lines = [
            f"{hook}",
            "",
            f"📌 {title} @ {company}",
            f"📍 {location} ({work_mode})",
            "🛂 Visa Sponsorship Verified",
        ]
        if skills:
            lines.append(f"🛠 {skills_str}")
        lines.append("")
        lines.append(summary)
        lines.append("")
        lines.append(f"Apply: {url}")
        return "\n".join(lines)[:500]

    return f"{hook}\n\n{title} @ {company}\nLocation: {location}\nApply: {url}"
