"""Mastodon bot prompts and template formatting (Part 3.6)."""
from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are the voice for Visa Lane's Mastodon account, which is registered and labeled as a
bot account. Your output is a single post, nothing else.

Style rules:
- Direct, transparent, no marketing voice. This community responds badly to anything
  that reads as trying to manipulate engagement.
- Hard limit: 500 characters.
- Maximum 2 emoji, only from: 🌍 💼 📍.
- Always include 2-4 relevant hashtags at the end (e.g. #VisaSponsorship #H1B #TechJobs
  #Relocation) — pick ones that actually match this job's country/field, never generic
  filler tags.
- Include the application link as plain text.
- Output only the final post text."""


def build_user_prompt(job: dict[str, Any] | None = None) -> str:
    """Format single job into Mastodon post user prompt."""
    j = job or {}
    title = j.get("title") or "Role"
    company = j.get("company") or "Company"
    city = j.get("city") or j.get("location_raw") or j.get("location") or "Worldwide"
    country = j.get("country") or ""
    location_str = f"{city}, {country}".strip(", ")
    conf_label = j.get("confidence_label") or ("Verified" if j.get("visa_sponsorship_verified") else "Likely")
    visa_types = ", ".join(j.get("visa_types") or []) if isinstance(j.get("visa_types"), list) else str(j.get("visa_types") or "Work Visa")
    salary = j.get("salary_raw") or (f"{j.get('salary_min')}-{j.get('salary_max')} {j.get('salary_currency', 'USD')}" if j.get("salary_min") else "Not listed")
    summary = j.get("summary") or j.get("snippet") or "Full-time opening offering visa sponsorship support."
    apply_link = j.get("apply_url") or j.get("url") or "https://visalane.app"

    return (
        "Generate one Mastodon post about this job:\n\n"
        f"Title: {title} | Company: {company} | Location: {location_str}\n"
        f"Confidence: {conf_label} | Visa type(s): {visa_types} | Salary: {salary}\n"
        f"Summary: {summary} | Link: {apply_link}\n\n"
        "Follow the system rules exactly."
    )
