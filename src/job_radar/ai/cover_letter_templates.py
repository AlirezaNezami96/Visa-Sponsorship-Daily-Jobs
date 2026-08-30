"""Templates and hooks for cover letter generation."""

from __future__ import annotations

# Opening hook templates that avoid cliché phrases
HOOK_TEMPLATES: list[str] = [
    "Having scaled {domain_skill} systems to handle {metric_achievement}, I was immediately drawn to {company}'s work on {company_focus}.",
    "When I saw that {company} is expanding its {domain_skill} capabilities, I knew my background in {user_specialty} would be an immediate fit.",
    "{company}'s reputation for {company_mission} resonates strongly with my experience in {user_specialty}.",
]

# Structure outline for high-impact cover letters
COVER_LETTER_STRUCTURE = """
1. Compelling opening hook referencing company focus and candidate specialty (NO 'I am writing to apply').
2. Why this specific role and company excites the candidate.
3. 2-3 core relevant accomplishments with metrics and technologies from profile.
4. Specific alignment with required job qualifications.
5. Professional, forward-looking closing.
"""
