"""Parity tests for engine/ai/validators.py (Python mirror of validators.ts)."""

from __future__ import annotations

import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1] / "engine"
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from ai.validators import (
    COVER_LETTER_BLOCKLIST,
    EMAIL_WORD_LIMIT,
    LINKEDIN_HARD_LIMIT,
    validate_cover_letter,
    validate_outreach,
    validate_tailored_resume,
)

SNAPSHOT = {
    "full_name": "Alireza Nezami",
    "skills": ["Kotlin", "Android", "CI/CD"],
    "experience": [
        {"company": "TechCorp", "title": "Senior Android Developer", "start": "2022", "end": "Present"},
        {"company": "StartupX", "title": "Android Developer", "start": "2019", "end": "2022"},
    ],
    "education": [{"institution": "Tehran University", "degree": "BSc CS", "year": "2019"}],
}

GROUNDED = {
    "sections": {
        "experience": [
            {"company": "TechCorp", "title": "Senior Android Developer", "start": "2022", "end": "Present"},
        ],
        "education": [{"institution": "Tehran University", "degree": "BSc CS", "year": "2019"}],
    }
}


def test_grounded_resume_passes():
    assert validate_tailored_resume(GROUNDED, SNAPSHOT) is None


def test_flat_sections_shape_also_validated():
    """Models sometimes omit the 'sections' wrapper — grounding must still run."""
    from ai.validators import resolve_sections

    flat = {
        "summary": "s",
        "experience": [{"company": "Google", "title": "Staff Engineer", "start": "2015", "end": "Present"}],
    }
    assert resolve_sections(flat).get("experience")
    out = validate_tailored_resume(flat, SNAPSHOT)
    assert out and "Google" in out, "flat payload slipped past grounding checks"
    assert resolve_sections(GROUNDED).get("experience"), "wrapped shape must still resolve"
    assert resolve_sections({"unrelated": 1}) == {}


def test_invented_employer_rejected():
    parsed = {
        "sections": {
            "experience": [
                {"company": "Google", "title": "Senior Android Developer", "start": "2022", "end": "Present"}
            ]
        }
    }
    out = validate_tailored_resume(parsed, SNAPSHOT)
    assert out and "Google" in out and "does not exist" in out


def test_invented_title_rejected():
    parsed = {
        "sections": {
            "experience": [{"company": "TechCorp", "title": "Staff Engineer", "start": "2022", "end": "Present"}]
        }
    }
    out = validate_tailored_resume(parsed, SNAPSHOT)
    assert out and "Staff Engineer" in out


def test_invented_year_rejected():
    parsed = {
        "sections": {
            "experience": [
                {"company": "TechCorp", "title": "Senior Android Developer", "start": "2015", "end": "Present"}
            ]
        }
    }
    out = validate_tailored_resume(parsed, SNAPSHOT)
    assert out and "2015" in out


def test_present_marker_never_flagged():
    parsed = {
        "sections": {
            "experience": [{"company": "TechCorp", "title": "Senior Android Developer", "start": "2022", "end": ""}]
        }
    }
    assert validate_tailored_resume(parsed, SNAPSHOT) is None


def test_invented_degree_rejected():
    parsed = {"sections": {"education": [{"institution": "MIT", "degree": "PhD"}]}}
    out = validate_tailored_resume(parsed, SNAPSHOT)
    assert out and "MIT" in out and "invented" in out


def test_company_alias_substring_match_passes():
    parsed = {
        "sections": {
            "experience": [
                {"company": "TechCorp GmbH", "title": "Senior Android Developer", "start": "2022", "end": "Present"}
            ]
        }
    }
    assert validate_tailored_resume(parsed, SNAPSHOT) is None


def _letter_body(opening: str = "Your team's work on mobile platform reliability stood out") -> str:
    words = [
        opening,
        "because it maps directly onto what I have built at TechCorp: a Kotlin codebase",
        "serving 2M+ installs where I cut crash rates 38% and led the CI/CD migration.",
        "I care about Android internals, profiling and shipping quality. At StartupX I",
        "took an app from 61 to 94 days on the Play store stability ranking by rewriting",
        "the networking layer and adding deterministic build pipelines. Your posting",
        "mentions platform tooling and developer experience, two areas where I have",
        "shipped measurable wins, including a 45% cut in build times and a component",
        "library reused by 6 squads. I would bring that same rigor to your mobile",
        "platform team and I am glad to walk through specifics in a conversation.",
    ]
    body = " ".join(words)
    # pad deterministically into the 250-400 window
    filler = " I value transparent engineering culture and pragmatic delivery."
    while len(body.split()) < 255:
        body += filler
    return body


def test_cover_letter_grounded_passes():
    parsed = {"cover_letter_markdown": _letter_body()}
    assert (
        validate_cover_letter(
            parsed, SNAPSHOT, company="Vectorshift", company_hook_context="mobile platform reliability"
        )
        is None
    )


def test_cover_letter_blocklist_rejected():
    for phrase in ["I am writing to apply", "To whom it may concern", "I hope this finds you well"]:
        body = _letter_body(opening=phrase)
        out = validate_cover_letter({"cover_letter_markdown": body}, SNAPSHOT, company="Vectorshift")
        assert out and "blocklisted" in out


def test_cover_letter_word_bounds_rejected():
    short = {"cover_letter_markdown": "Short note about Vectorshift with Kotlin and 40% wins."}
    out = validate_cover_letter(short, SNAPSHOT, company="Vectorshift")
    assert out and "word count" in out


def test_cover_letter_missing_markdown():
    assert validate_cover_letter({}, SNAPSHOT) == "missing cover_letter_markdown"


def test_cover_letter_no_company_reference_rejected():
    parsed = {"cover_letter_markdown": _letter_body()}
    out = validate_cover_letter(parsed, SNAPSHOT, company="Zephyrion", company_hook_context="unique rocketry")
    assert out and "company-specific token" in out


def test_cover_letter_no_user_fact_rejected():
    body_words = []
    seed = "The team's direction caught my eye and I believe I fit the role's demands nicely today."
    body_words.append(seed)
    body = " ".join(body_words)
    filler = " Collaboration and ownership matter to me in equal measure at work."
    while len(body.split()) < 255:
        body += filler
    out = validate_cover_letter({"cover_letter_markdown": body}, SNAPSHOT, company="Teamco")
    assert out and "user metric or profile fact" in out


def _outreach(linkedin_len: int = 280, email_words: int = 150, tone: str = "natural") -> dict:
    return {
        "email": {
            "subject": "Senior Android Developer role",
            "body": " ".join(["word"] * email_words),
            "tone": tone,
        },
        "linkedin": {
            "body": "x" * linkedin_len,
            "tone": tone,
        },
    }


def test_outreach_grounded_passes():
    assert validate_outreach(_outreach()) is None


def test_linkedin_hard_cap():
    out = validate_outreach(_outreach(linkedin_len=LINKEDIN_HARD_LIMIT + 1))
    assert out and "hard cap" in out
    assert validate_outreach(_outreach(linkedin_len=LINKEDIN_HARD_LIMIT)) is None


def test_email_word_cap():
    out = validate_outreach(_outreach(email_words=EMAIL_WORD_LIMIT + 5))
    assert out and "exceeds" in out


def test_tone_mismatch_rejected():
    out = validate_outreach(_outreach(tone="formal"), expected_tone="natural")
    assert out and "tone" in out


def test_missing_bodies_rejected():
    out = validate_outreach({"email": {}, "linkedin": {}})
    assert out and "missing email.body" in out and "missing linkedin.body" in out


def test_constants_match_ts_mirror():
    assert LINKEDIN_HARD_LIMIT == 300
    assert EMAIL_WORD_LIMIT == 220
    assert "delve" in COVER_LETTER_BLOCKLIST
    assert "thrilled to apply" in COVER_LETTER_BLOCKLIST


def test_cover_letter_blocklist_delve_and_thrilled():
    for phrase in ["delve", "thrilled to apply", "I would like to express my interest"]:
        body = _letter_body(opening=f"We will {phrase} into mobile architecture and delivery.")
        out = validate_cover_letter({"cover_letter_markdown": body}, SNAPSHOT, company="Vectorshift")
        assert out and ("blocklisted" in out or "phrase" in out)


def test_unicode_and_case_insensitive_company_matching():
    unicode_snapshot = {
        "experience": [{"company": "Société Générale", "title": "Senior Engineer", "start": "2021", "end": "2023"}]
    }
    grounded = {
        "sections": {
            "experience": [{"company": "Societe Generale", "title": "Senior Engineer", "start": "2021", "end": "2023"}]
        }
    }
    assert validate_tailored_resume(grounded, unicode_snapshot) is None


def test_year_range_in_dates():
    range_snapshot = {
        "experience": [{"company": "Acme Corp", "title": "Lead Developer", "start": "2018-05", "end": "2023-12"}]
    }
    grounded = {
        "sections": {
            "experience": [{"company": "Acme Corp", "title": "Lead Developer", "start": "2018", "end": "2023"}]
        }
    }
    assert validate_tailored_resume(grounded, range_snapshot) is None


def test_outreach_edge_case_empty_and_validations():
    assert validate_outreach(None) == "output is not a dictionary"
    assert "missing email object" in (validate_outreach({"linkedin": {"body": "hi"}}) or "")
    assert "missing linkedin object" in (validate_outreach({"email": {"body": "hi"}}) or "")
