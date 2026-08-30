"""Post text generator with rotating hooks, AI summarization, and deterministic fallbacks.

Generates tailored text across platforms (X <= 280 chars, Telegram/Discord full markdown,
LinkedIn with tags, Bluesky/Mastodon).
Uses a deterministic hash of job_id to rotate through hook templates.
AI summary waterfall: OpenRouter / Gemini -> Groq -> Extractive rule-based fallback.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, Optional

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
        summary = summary[:277] + "..."
    return summary


def generate_job_summary(job: Dict[str, Any]) -> str:
    """Generate a 2-3 sentence AI summary of the job description, or fall back to extractive."""
    desc = job.get("description_text") or job.get("description") or ""
    skills = job.get("skills") or []

    # Try OpenRouter / Groq / Gemini if keys are available
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEYS")

    prompt = (
        f"Summarize this job in 2 concise sentences for social media. "
        f"Mention what the company does, the core responsibilities, and key stack. "
        f"Do not include hype, emojis, or markdown headings.\n\n"
        f"Title: {job.get('title', '')}\n"
        f"Company: {job.get('company', '')}\n"
        f"Description: {desc[:2500]}"
    )

    # 1. Try Groq (fastest)
    if groq_key:
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
                    return text
        except Exception as e:
            logger.debug("Groq social summary failed: %s", e)

    # 2. Try OpenRouter
    if openrouter_key:
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
                    return text
        except Exception as e:
            logger.debug("OpenRouter social summary failed: %s", e)

    # 3. Deterministic fallback
    return _extractive_summary(desc, skills)


def build_platform_post_text(job: Dict[str, Any], platform: str = "telegram") -> str:
    """Build platform-specific post text.

    Supported platforms: telegram, discord, slack, x, linkedin, bluesky, mastodon.
    """
    job_id = str(job.get("id") or "")
    hook = get_rotating_hook(job_id)
    title = job.get("title", "Software Engineer")
    company = job.get("company", "Company")
    country = job.get("country") or job.get("country_code") or "Global"
    location = job.get("location") or country
    work_mode = job.get("work_mode", "Remote")
    url = job.get("apply_url") or job.get("url") or "https://visalane.online"
    skills = job.get("skills") or []
    skills_str = ", ".join(skills[:5]) if skills else "Tech"
    summary = generate_job_summary(job)

    salary_min = job.get("salary_min")
    salary_max = job.get("salary_max")
    salary_cur = job.get("salary_currency", "USD")
    salary_line = ""
    if salary_min and salary_max:
        salary_line = f"\n💰 {salary_cur} {salary_min:,} - {salary_max:,}"
    elif salary_min:
        salary_line = f"\n💰 From {salary_cur} {salary_min:,}"

    if platform == "x":
        # Hard limit: 280 characters
        # Structure: Hook \n Title @ Company \n 📍 Location (Mode) \n 🛂 Visa Sponsored \n 🔗 URL
        header = f"{hook}\n\n📌 {title} @ {company}\n📍 {location} ({work_mode}){salary_line}\n🛂 Visa Sponsored\n\nApply: {url}"
        if len(header) > 280:
            # Compact format
            header = f"🛂 {title} @ {company}\n📍 {location} | {work_mode}\nApply: {url}"
        return header[:280]

    if platform in ("telegram", "discord", "slack"):
        # Full rich markdown
        lines = [
            f"{hook}",
            "",
            f"📌 **{title}**",
            f"🏢 **{company}**",
            f"📍 {location} ({work_mode.capitalize()})",
            f"🛂 **Visa Sponsorship:** Verified ✅",
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
        # Professional post format
        tags = "#VisaSponsorship #TechJobs #GlobalCareers #Relocation #Hiring"
        lines = [
            f"{hook}",
            "",
            f"Role: {title}",
            f"Company: {company}",
            f"Location: {location} ({work_mode.capitalize()})",
            f"Visa Sponsorship: Verified",
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
        # 300-500 char format
        lines = [
            f"{hook}",
            "",
            f"📌 {title} @ {company}",
            f"📍 {location} ({work_mode})",
            f"🛂 Visa Sponsorship Verified",
        ]
        if skills:
            lines.append(f"🛠 {skills_str}")
        lines.append("")
        lines.append(summary)
        lines.append("")
        lines.append(f"Apply: {url}")
        return "\n".join(lines)[:500]

    # Default fallback
    return f"{hook}\n\n{title} @ {company}\nLocation: {location}\nApply: {url}"
