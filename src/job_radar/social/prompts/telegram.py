"""Telegram channel prompts and template formatting (Part 3.1)."""
from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are the content voice for Visa Lane's Telegram channel, a live feed of visa-sponsorship
job openings read by people actively job-hunting internationally. Your only output is the
message text — no explanations, no meta-commentary.

Style rules:
- Casual, energetic, direct. Short lines. This is a feed people skim fast on mobile.
- Use MarkdownV2 formatting: *bold* for job titles and company names, plain text elsewhere.
- Use 1-3 emoji per job line, drawn only from this palette: 🌍 🛂 💼 📍 💰 🔗 🆕 ✅ 🔥 📌.
  Never invent emoji outside this list.
- Each job gets its own short block: title, company, location, one-line why-it-matters
  (confidence/salary/visa type), and the apply link.
- Never editorialize or add hype language the job data doesn't support ("amazing
  opportunity," "don't miss out"). If the data doesn't say it, don't say it.
- Open the message with a one-line header stating how many new jobs are in this batch.
- Total message length must stay under 3800 characters.
- Output nothing but the final message text."""


def build_user_prompt(jobs: list[dict[str, Any]]) -> str:
    """Format batch jobs into Telegram user prompt."""
    lines = [f"Generate a Telegram batch post for these {len(jobs)} new jobs:\n"]
    for j in jobs:
        title = j.get("title") or "Role"
        company = j.get("company") or "Company"
        city = j.get("city") or j.get("location_raw") or j.get("location") or "Worldwide"
        country = j.get("country") or ""
        location_str = f"{city}, {country}".strip(", ")
        conf_label = j.get("confidence_label") or ("High" if j.get("visa_sponsorship_verified") else "Likely")
        conf_score = j.get("visa_sponsorship_confidence") or j.get("visa_score") or 85
        visa_types = ", ".join(j.get("visa_types") or []) if isinstance(j.get("visa_types"), list) else str(j.get("visa_types") or "Work Visa")
        salary = j.get("salary_raw") or (f"{j.get('salary_min')}-{j.get('salary_max')} {j.get('salary_currency', 'USD')}" if j.get("salary_min") else "Not disclosed")
        summary = j.get("summary") or j.get("snippet") or "Full-time position with visa sponsorship support."
        apply_link = j.get("apply_url") or j.get("url") or "https://visalane.app"

        lines.append(f"- Title: {title}")
        lines.append(f"  Company: {company}")
        lines.append(f"  Location: {location_str}")
        lines.append(f"  Sponsorship confidence: {conf_label} ({conf_score})")
        lines.append(f"  Visa type(s): {visa_types}")
        lines.append(f"  Salary: {salary}")
        lines.append(f"  Summary: {summary}")
        lines.append(f"  Apply: {apply_link}\n")

    lines.append("Follow the system style rules exactly. Output only the final Telegram message.")
    return "\n".join(lines)
