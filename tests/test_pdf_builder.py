"""Tests for deterministic ATS-safe PDF assembly (fpdf2)."""

from __future__ import annotations

import io
import unittest
import pytest

pytest.importorskip("fpdf")
pytest.importorskip("pypdf")

from pypdf import PdfReader

from job_radar.ai.pdf_builder import (
    build_cover_letter_pdf,
    build_resume_pdf,
)

PROFILE = {
    "full_name": "Alireza Nezami",
    "email": "alireza.nezami75@gmail.com",
    "phone": "+90 543 743 7966",
    "location": "Istanbul, Türkiye",
    "skills": ["Kotlin", "Flutter", "Jetpack Compose", "MVVM"],
    "section_order": ["summary", "experience", "education", "skills", "links"],
    "contact": {"linkedin": "linkedin.com/in/alireza-nezami"},
}

TAILORED = {
    "tailored_resume_markdown": "# fallback not used",
    "keywords_added": ["Kotlin Multiplatform"],
    "tailoring_notes": ["Emphasized KMM"],
    "estimated_ats_score": 87,
    "sections": {
        "summary": "Senior mobile engineer with 9+ years building Android and Flutter apps.",
        "skills": ["Kotlin", "Flutter", "Kotlin Multiplatform", "Jetpack Compose"],
        "experience": [
            {
                "title": "Senior Android & Flutter Developer",
                "company": "Devotel",
                "start": "April 2024",
                "end": "Present",
                "bullets": [
                    "Led a Flutter fitness app serving 400K+ MAU with a 4.7 Play Store rating.",
                    "Built Kotlin Platform Channel modules for real-time DSP processing.",
                ],
            },
            {
                "title": "Android Developer",
                "company": "Golden Equator Group",
                "start": "2017",
                "end": "2024",
                "bullets": ["Reduced crash rate by 60% using LeakCanary and Macrobenchmark."],
            },
        ],
        "education": [{"institution": "Anadolu University", "degree": "BSc Computer Engineering", "year": "2017"}],
        "links": ["github.com/AlirezaNezami96", "alirezanezami96.github.io"],
    },
}

JOB = {"title": "Senior Android Engineer", "company": "Spotify", "location": "Stockholm, Sweden"}

COVER_LETTER = {
    "cover_letter_markdown": (
        "Spotify's investment in in-car audio experiences is exactly the kind of "
        "platform problem I have spent nine years solving.\n\n"
        "At Devotel I led a Flutter app serving 400K+ monthly users and cut build "
        "times by 35% while keeping a 4.7 store rating.\n\n"
        "I would welcome the chance to bring that mobile depth to your Android team."
    ),
    "overlap_skills": ["Kotlin", "Jetpack Compose"],
    "company_hook": "in-car audio",
    "word_count": 320,
}


def _extract(pdf: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


class TestResumePdf(unittest.TestCase):
    def test_contains_profile_facts(self):
        pdf = build_resume_pdf(PROFILE, TAILORED, format_type="professional")
        text = _extract(pdf)
        self.assertIn("Alireza Nezami", text)
        self.assertIn("Devotel", text)
        self.assertIn("Golden Equator Group", text)
        self.assertIn("April 2024", text)
        self.assertIn("Present", text)
        self.assertIn("EXPERIENCE", text.upper())
        self.assertIn("SUMMARY", text.upper())

    def test_page_cap_two_pages(self):
        reader = PdfReader(io.BytesIO(build_resume_pdf(PROFILE, TAILORED)))
        self.assertLessEqual(len(reader.pages), 2)

    def test_huge_resume_truncates_bullets_not_words(self):
        bloated = {
            "sections": {
                **TAILORED["sections"],
                "experience": [
                    {
                        "title": "Engineer",
                        "company": "Acme",
                        "start": "2020",
                        "end": "2026",
                        "bullets": [f"Delivered capability number {i} with measurable impact." for i in range(120)],
                    }
                ],
            }
        }
        pdf = build_resume_pdf(PROFILE, bloated)
        reader = PdfReader(io.BytesIO(pdf))
        self.assertLessEqual(len(reader.pages), 2)
        self.assertIn("Delivered capability number 0", _extract(pdf))

    def test_professional_vs_own_section_order(self):
        professional_text = _extract(build_resume_pdf(PROFILE, TAILORED, format_type="professional"))
        own_text = _extract(build_resume_pdf(PROFILE, TAILORED, format_type="own"))
        prof_upper, own_upper = professional_text.upper(), own_text.upper()
        self.assertLess(prof_upper.index("SKILLS"), prof_upper.index("EXPERIENCE"))
        self.assertLess(own_upper.index("EXPERIENCE"), own_upper.index("SKILLS"))

    def test_deterministic_bytes(self):
        first = build_resume_pdf(PROFILE, TAILORED)
        second = build_resume_pdf(PROFILE, TAILORED)
        self.assertEqual(first, second)

    def test_markdown_fallback_when_no_structured_sections(self):
        markdown_only = {
            "tailored_resume_markdown": (
                "## Summary\n\nSenior engineer.\n\n"
                "## Experience\n\n- Shipped a major release.\n\n"
                "## Skills\n\nKotlin, Flutter\n"
            )
        }
        text = _extract(build_resume_pdf(PROFILE, markdown_only))
        self.assertIn("Senior engineer", text)
        self.assertIn("Shipped a major release", text)


class TestCoverLetterPdf(unittest.TestCase):
    def test_single_page_with_signature(self):
        pdf = build_cover_letter_pdf(PROFILE, COVER_LETTER, JOB)
        reader = PdfReader(io.BytesIO(pdf))
        self.assertLessEqual(len(reader.pages), 1)
        text = _extract(pdf)
        self.assertIn("Alireza Nezami", text)
        self.assertIn("Spotify", text)
        self.assertIn("Sincerely", text)

    def test_long_letter_truncates_to_one_page(self):
        long_letter = {
            "cover_letter_markdown": "\n\n".join(
                f"Paragraph {i} elaborating on achievements with metrics and outcomes." * 6 for i in range(14)
            )
        }
        pdf = build_cover_letter_pdf(PROFILE, long_letter, JOB)
        reader = PdfReader(io.BytesIO(pdf))
        self.assertLessEqual(len(reader.pages), 1)

    def test_deterministic_bytes(self):
        first = build_cover_letter_pdf(PROFILE, COVER_LETTER, JOB)
        second = build_cover_letter_pdf(PROFILE, COVER_LETTER, JOB)
        self.assertEqual(first, second)

    def test_cover_letter_fallback_on_empty_job(self):
        pdf = build_cover_letter_pdf(PROFILE, COVER_LETTER, {})
        reader = PdfReader(io.BytesIO(pdf))
        self.assertLessEqual(len(reader.pages), 1)
        text = _extract(pdf)
        self.assertIn("Alireza Nezami", text)
        self.assertIn("Sincerely", text)

    def test_special_characters_handling(self):
        profile_special = {
            **PROFILE,
            "full_name": "Alireza Nezami & Co.",
            "location": "München, Germany — Remote / Hybrid",
        }
        pdf = build_resume_pdf(profile_special, TAILORED)
        text = _extract(pdf)
        self.assertIn("Alireza Nezami", text)


if __name__ == "__main__":
    unittest.main()
