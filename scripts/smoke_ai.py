#!/usr/bin/env python3
"""End-to-end AI smoke test (GAP 3.4).

Synthetic profile + fixture job -> parse -> tailored resume -> cover letter
-> outreach, asserting the hallucination validators and deterministic PDF
assembly at every step.

Modes:
  --mock   scripted provider responses (every PR, no API keys needed)
  default  real provider waterfall Gemini -> Groq -> OpenRouter (nightly CI)

Exits non-zero on any failed assertion so CI can alert on it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "engine"))

# ---------------------------------------------------------------------------
# Synthetic candidate + fixture job (grounded facts used by the validators)
# ---------------------------------------------------------------------------

SYNTHETIC_RESUME = """Sana Karimi
Senior Android Developer
sana.karimi@example.com | +34 600 111 222 | Barcelona, Spain

SUMMARY
Android engineer with 7 years building consumer apps at scale.

SKILLS
Kotlin, Android SDK, Jetpack Compose, CI/CD, gRPC, Firebase

EXPERIENCE
Senior Android Developer, TechCorp — 2022 to Present
- Cut crash rate 38% by hardening the networking layer
- Led CI/CD migration, build times down 45%

Android Developer, StartupX — 2019 to 2022
- Shipped the flagship app to 2M+ installs
- Raised Play Store stability ranking from 61 to 94 days

EDUCATION
BSc Computer Science, Polytechnic of Valencia — 2019
"""

PROFILE = {
    "full_name": "Sana Karimi",
    "email": "sana.karimi@example.com",
    "phone": "+34 600 111 222",
    "location": "Barcelona, Spain",
    "skills": ["Kotlin", "Android SDK", "Jetpack Compose", "CI/CD", "gRPC", "Firebase"],
    "experience": [
        {
            "company": "TechCorp",
            "title": "Senior Android Developer",
            "start": "2022",
            "end": "Present",
        },
        {
            "company": "StartupX",
            "title": "Android Developer",
            "start": "2019",
            "end": "2022",
        },
    ],
    "education": [{"institution": "Polytechnic of Valencia", "degree": "BSc Computer Science", "year": "2019"}],
}

JOB = {
    "title": "Senior Android Developer",
    "company": "Vectorshift",
    "location": "Barcelona, Spain",
    "description": (
        "Vectorshift builds automation tooling for logistics teams. We need a senior "
        "Android developer to own our driver-facing app: Kotlin, Jetpack Compose, "
        "offline-first sync, and platform tooling for developer experience."
    ),
}

# ---------------------------------------------------------------------------
# Canned responses for --mock mode (every JSON here passes the validators)
# ---------------------------------------------------------------------------

MOCK_PARSED = {
    "full_name": "Sana Karimi",
    "email": "sana.karimi@example.com",
    "skills": ["Kotlin", "Android SDK", "Jetpack Compose", "CI/CD"],
    "experience": [
        {"company": "TechCorp", "title": "Senior Android Developer", "start": "2022", "end": "Present"},
        {"company": "StartupX", "title": "Android Developer", "start": "2019", "end": "2022"},
    ],
    "education": [{"institution": "Polytechnic of Valencia", "degree": "BSc Computer Science", "year": "2019"}],
}

MOCK_TAILORED = {
    "sections": {
        "summary": (
            "Android engineer with 7 years shipping consumer apps at scale; cut crash "
            "rates 38% and build times 45% while leading CI/CD at TechCorp."
        ),
        "skills": ["Kotlin", "Jetpack Compose", "Android SDK", "CI/CD", "gRPC", "Firebase"],
        "experience": [
            {
                "company": "TechCorp",
                "title": "Senior Android Developer",
                "start": "2022",
                "end": "Present",
                "bullets": [
                    "Cut crash rate 38% by hardening the networking layer — directly relevant to Vectorshift's offline-first sync.",
                    "Led CI/CD migration and cut build times 45%, improving platform tooling and developer experience.",
                ],
            },
            {
                "company": "StartupX",
                "title": "Android Developer",
                "start": "2019",
                "end": "2022",
                "bullets": [
                    "Shipped the flagship app to 2M+ installs.",
                    "Raised Play Store stability ranking from 61 to 94 days.",
                ],
            },
        ],
        "education": [{"institution": "Polytechnic of Valencia", "degree": "BSc Computer Science", "year": "2019"}],
    }
}

_MOCK_LETTER = (
    "Your driver-facing app at Vectorshift has to keep working in tunnels, depots and "
    "dead zones — that offline-first constraint is exactly the kind of Android problem I "
    "have spent seven years solving. At TechCorp I own a Kotlin and Jetpack Compose "
    "codebase where I cut the crash rate 38% by rebuilding the networking layer around "
    "deterministic retry queues, and I led the CI/CD migration that brought build times "
    "down 45%. Your posting highlights platform tooling and developer experience, which "
    "is where my second act at TechCorp lives: build pipelines, modularization, and the "
    "component library now reused across squads. Before that, at StartupX, I took the "
    "flagship app from prototype to 2M+ installs and lifted the Play Store stability "
    "ranking from 61 to 94 days, learning how to ship fast without trading away quality. "
    "I understand Vectorshift is scaling logistics automation across Europe, and a "
    "driver-facing app that syncs reliably is the backbone of that growth. I would bring "
    "the same rigor to your offline sync engine: measurable reliability targets, tight "
    "feedback loops with backend, and tooling that keeps the whole team shipping. Beyond "
    "the app itself, I care about the developer experience around it: at TechCorp the "
    "modularization work and component library I drove now serve multiple squads, and the "
    "Kotlin and Jetpack Compose conventions I helped write are the ones new features are "
    "built on today. If helpful, I can share before-and-after stability dashboards from "
    "both roles, including the 2M+ install growth curve at StartupX. I am "
    "based in Barcelona and glad to come onsite. I would enjoy walking through your sync "
    "architecture and where the app hurts most today."
)

MOCK_COVER = {"cover_letter_markdown": _MOCK_LETTER}

MOCK_OUTREACH = {
    "email": {
        "subject": "Senior Android Developer — Sana Karimi",
        "body": (
            "Hi Vectorshift team,\n\nYour senior Android role caught my attention: "
            "offline-first driver tooling is exactly what I build. At TechCorp I cut "
            "crash rates 38% and build times 45% on a Kotlin/Compose codebase. Before "
            "that I scaled an app to 2M+ installs at StartupX.\n\nI am based in "
            "Barcelona and available for a call this week.\n\nBest,\nSana Karimi"
        ),
        "tone": "natural",
    },
    "linkedin": {
        "body": (
            "Hi! Your Senior Android Developer role at Vectorshift looks like a great "
            "match — I've spent 7 years on Kotlin apps, most recently cutting crash "
            "rates 38% at TechCorp. Happy to share details. — Sana"
        ),
        "tone": "natural",
    },
}

MOCK_RESPONSES = {
    "[PARSE_TASK]": json.dumps(MOCK_PARSED),
    "[TAILOR_TASK]": json.dumps(MOCK_TAILORED),
    "[COVER_TASK]": json.dumps(MOCK_COVER),
    "[OUTREACH_TASK]": json.dumps(MOCK_OUTREACH),
}


class MockRouter:
    """Scripted stand-in for LLMRouter.try_provider (dispatches on prompt marker)."""

    def __init__(self):
        self.calls = 0

    def try_provider(self, provider, prompt, **kwargs):
        from job_radar.llm.router import LLMResult, ProviderAttempt

        self.calls += 1
        for marker, text in MOCK_RESPONSES.items():
            if marker in prompt:
                return ProviderAttempt(LLMResult(text=text, model_used="mock", provider=provider))
        return ProviderAttempt(None, "no mock response for prompt")

    def evict_cache(self, provider, prompt, json_schema=None):
        """No-op: mock responses are stateless."""


# ---------------------------------------------------------------------------
# Smoke steps
# ---------------------------------------------------------------------------

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(f"{name}: {detail}")


def _extract_pdf_text(pdf_bytes: bytes) -> tuple[str, int]:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return text, len(reader.pages)


def run(mock: bool) -> int:
    from job_radar.llm.validated import ValidatedCompletion, run_validated_completion

    sys.path.insert(0, str(ROOT / "engine"))
    from ai.validators import (
        EMAIL_WORD_LIMIT,
        LINKEDIN_HARD_LIMIT,
        validate_cover_letter,
        validate_outreach,
        validate_tailored_resume,
    )

    from job_radar.ai.pdf_builder import build_cover_letter_pdf, build_resume_pdf

    router = MockRouter() if mock else None
    mode = "mock providers" if mock else "live provider waterfall"
    print(f"== Visalane AI smoke ({mode}) ==")

    retries = 1 if mock else 2  # free-tier providers are flaky: retry each step once

    def generate(prompt: str, validate, document_type: str) -> ValidatedCompletion:
        last = None
        for attempt in range(1, retries + 1):
            last = run_validated_completion(prompt, validate, router=router, document_type=document_type)
            if last.ok:
                return last
            print(f"  step '{document_type}' attempt {attempt} failed: {last.violation[:140]}")
        return last  # type: ignore[return-value]

    # -- 1. parse -----------------------------------------------------------
    print("\n[1/4] parse")
    parse_prompt = (
        "[PARSE_TASK] Extract structured JSON from this resume text. Keys: full_name, "
        "email, skills (list), experience (company/title/start/end), education "
        f"(institution/degree/year).\n\n{SYNTHETIC_RESUME}"
    )
    parse_res = generate(
        parse_prompt,
        lambda parsed: None if (parsed or {}).get("experience") else "missing experience",
        "resume_parse",
    )
    check("parse completed", parse_res.ok, parse_res.violation)
    parsed = parse_res.parsed or {}
    companies = {e.get("company") for e in parsed.get("experience", []) if isinstance(e, dict)}
    check("parse grounded (TechCorp + StartupX)", {"TechCorp", "StartupX"} <= companies, str(companies))
    print(f"  provider={parse_res.provider} model={parse_res.model} repairs={parse_res.repair_attempts}")

    # -- 2. tailored resume ---------------------------------------------------
    print("\n[2/4] tailored resume")
    tailor_prompt = (
        "[TAILOR_TASK] Tailor this candidate's resume to the job. Return JSON with "
        "sections: summary, skills, experience (company/title/start/end/bullets — every "
        f"employer, title and year MUST come from the candidate data), education.\n\n"
        f"=== CANDIDATE ===\n{json.dumps(PROFILE, indent=2)}\n\n=== JOB ===\n{json.dumps(JOB, indent=2)}"
    )
    tailor_res = generate(
        tailor_prompt,
        lambda parsed: validate_tailored_resume(parsed or {}, PROFILE),
        "resume",
    )
    check("tailored resume completed", tailor_res.ok, tailor_res.violation)
    tailored = tailor_res.parsed or {}
    check(
        "validator accepted tailored resume",
        validate_tailored_resume(tailored, PROFILE) is None,
        str(validate_tailored_resume(tailored, PROFILE)),
    )
    resume_pdf = build_resume_pdf(PROFILE, tailored, format_type="professional")
    resume_text, resume_pages = _extract_pdf_text(resume_pdf)
    check("resume PDF built", len(resume_pdf) > 1000, f"{len(resume_pdf)} bytes")
    check("resume <= 2 pages", resume_pages <= 2, f"{resume_pages} pages")
    check("resume contains candidate name", "Sana Karimi" in resume_text)
    check("resume contains real employers", "TechCorp" in resume_text and "StartupX" in resume_text)
    check("resume PDF deterministic", resume_pdf == build_resume_pdf(PROFILE, tailored, format_type="professional"))

    # -- 3. cover letter -------------------------------------------------------
    print("\n[3/4] cover letter")
    cover_prompt = (
        "[COVER_TASK] Write a cover letter (250-400 words, markdown in "
        "cover_letter_markdown). No generic openers. Reference the company specifically "
        f"and at least one candidate metric.\n\n=== CANDIDATE ===\n{json.dumps(PROFILE, indent=2)}\n\n"
        f"=== JOB ===\n{json.dumps(JOB, indent=2)}"
    )
    cover_res = generate(
        cover_prompt,
        lambda parsed: validate_cover_letter(
            parsed or {}, PROFILE, company=JOB["company"], company_hook_context=JOB["description"]
        ),
        "cover_letter",
    )
    check("cover letter completed", cover_res.ok, cover_res.violation)
    cover = cover_res.parsed or {}
    check(
        "validator accepted cover letter",
        validate_cover_letter(cover, PROFILE, company=JOB["company"], company_hook_context=JOB["description"]) is None,
        str(validate_cover_letter(cover, PROFILE, company=JOB["company"], company_hook_context=JOB["description"])),
    )
    letter_words = len(str(cover.get("cover_letter_markdown") or "").split())
    check("cover letter 250-400 words", 250 <= letter_words <= 400, f"{letter_words} words")
    check("cover letter references company", JOB["company"] in str(cover.get("cover_letter_markdown") or ""))
    cl_pdf = build_cover_letter_pdf(PROFILE, cover, JOB)
    cl_text, cl_pages = _extract_pdf_text(cl_pdf)
    check("cover letter PDF <= 1 page", cl_pages <= 1, f"{cl_pages} pages")
    check("cover letter PDF contains company", "Vectorshift" in cl_text)

    # -- 4. outreach ------------------------------------------------------------
    print("\n[4/4] outreach")
    outreach_prompt = (
        "[OUTREACH_TASK] Produce outreach JSON: email {subject, body <=220 words, tone} "
        "and linkedin {body <=300 chars, tone}. Tone: natural.\n\n"
        f"=== CANDIDATE ===\n{json.dumps(PROFILE, indent=2)}\n\n=== JOB ===\n{json.dumps(JOB, indent=2)}"
    )
    outreach_res = generate(
        outreach_prompt,
        lambda parsed: validate_outreach(parsed or {}, expected_tone="natural"),
        "outreach",
    )
    check("outreach completed", outreach_res.ok, outreach_res.violation)
    outreach = outreach_res.parsed or {}
    check(
        "validator accepted outreach",
        validate_outreach(outreach, expected_tone="natural") is None,
        str(validate_outreach(outreach, expected_tone="natural")),
    )
    li_body = str((outreach.get("linkedin") or {}).get("body") or "")
    email_body = str((outreach.get("email") or {}).get("body") or "")
    check("linkedin <= 300 chars", len(li_body) <= LINKEDIN_HARD_LIMIT, f"{len(li_body)} chars")
    check("email <= 220 words", len(email_body.split()) <= EMAIL_WORD_LIMIT, f"{len(email_body.split())} words")

    # -- summary -----------------------------------------------------------------
    print("\n== summary ==")
    if FAILURES:
        print(f"SMOKE FAILED — {len(FAILURES)} assertion(s):")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("SMOKE PASSED — parse, tailored resume, cover letter, outreach all validated")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Visalane end-to-end AI smoke test")
    parser.add_argument("--mock", action="store_true", help="use scripted responses (no API keys)")
    args = parser.parse_args()
    return run(mock=args.mock)


if __name__ == "__main__":
    sys.exit(main())
