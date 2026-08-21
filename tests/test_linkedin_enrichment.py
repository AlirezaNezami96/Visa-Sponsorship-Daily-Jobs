"""Unit tests for company LinkedIn enrichment module."""
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from job_radar.enrichment.linkedin import (
    enrich_jobs_with_linkedin,
    extract_linkedin_from_html,
    find_company_linkedin,
    is_slug_relevant,
    load_linkedin_cache,
    save_linkedin_cache,
)
from job_radar.notifications.renderers import (
    _render_job_card,
    build_justjoin_html,
    build_legacy_html,
)


class LinkedInValidationTests(unittest.TestCase):
    def test_is_slug_relevant_positive(self):
        self.assertTrue(is_slug_relevant("Anthropic", "anthropicresearch"))
        self.assertTrue(is_slug_relevant("OpenAI", "openai"))
        self.assertTrue(is_slug_relevant("Svitla Systems Inc", "svitla-systems-inc-"))
        self.assertTrue(is_slug_relevant("Mistral AI", "mistral-ai"))
        self.assertTrue(is_slug_relevant("DeepMind Technologies", "google-deepmind"))
        self.assertTrue(is_slug_relevant("Spotify", "spotify"))

    def test_is_slug_relevant_negative(self):
        self.assertFalse(is_slug_relevant("Svitla Systems", "windows-it-pro"))
        self.assertFalse(is_slug_relevant("Anthropic", "jobs"))
        self.assertFalse(is_slug_relevant("OpenAI", "in"))
        self.assertFalse(is_slug_relevant("OpenAI", "feed"))
        self.assertFalse(is_slug_relevant("", "openai"))
        self.assertFalse(is_slug_relevant("OpenAI", ""))


class LinkedInHtmlExtractionTests(unittest.TestCase):
    def test_extract_from_footer(self):
        sample_html = """
        <html>
        <body>
            <header>
                <nav><a href="/about">About</a></nav>
            </header>
            <main><h1>Welcome to Anthropic</h1></main>
            <footer>
                <div class="socials">
                    <a href="https://twitter.com/anthropic">Twitter</a>
                    <a href="https://www.linkedin.com/company/anthropicresearch/">LinkedIn</a>
                </div>
            </footer>
        </body>
        </html>
        """
        extracted = extract_linkedin_from_html(sample_html, target_company="Anthropic")
        self.assertEqual(extracted, "https://www.linkedin.com/company/anthropicresearch")

    def test_extract_empty_html(self):
        self.assertIsNone(extract_linkedin_from_html(""))
        self.assertIsNone(extract_linkedin_from_html("<html><body>No links</body></html>"))


class LinkedInCacheTests(unittest.TestCase):
    def test_load_and_save_cache(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_file = os.path.join(tmp_dir, "cache.json")
            cache = {"anthropic": "https://www.linkedin.com/company/anthropicresearch"}
            save_linkedin_cache(cache, cache_file)

            loaded = load_linkedin_cache(cache_file)
            self.assertEqual(loaded.get("anthropic"), "https://www.linkedin.com/company/anthropicresearch")


class LinkedInEnrichmentTests(unittest.TestCase):
    @patch("job_radar.enrichment.linkedin.find_company_linkedin")
    def test_enrich_jobs_with_linkedin(self, mock_find):
        mock_find.side_effect = lambda company, cache: (
            "https://www.linkedin.com/company/openai" if company.lower() == "openai"
            else "https://www.linkedin.com/company/anthropicresearch" if company.lower() == "anthropic"
            else None
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_file = os.path.join(tmp_dir, "cache.json")
            jobs = [
                {"title": "Research Scientist", "company": "OpenAI", "url": "https://openai.com/job/1"},
                {"title": "Member of Technical Staff", "company": "Anthropic", "url": "https://anthropic.com/job/2"},
                {"title": "Software Engineer", "company": "OpenAI", "url": "https://openai.com/job/3"},
                {"title": "Unknown Job", "company": "UnknownCo", "url": "https://unknown.com/job/4"},
            ]

            enrich_jobs_with_linkedin(jobs, cache_path=cache_file)

            self.assertEqual(jobs[0]["company_linkedin_url"], "https://www.linkedin.com/company/openai")
            self.assertEqual(jobs[1]["company_linkedin_url"], "https://www.linkedin.com/company/anthropicresearch")
            self.assertEqual(jobs[2]["company_linkedin_url"], "https://www.linkedin.com/company/openai")
            self.assertIsNone(jobs[3]["company_linkedin_url"])


class LinkedInRendererTests(unittest.TestCase):
    def test_render_job_card_includes_linkedin_link(self):
        job = {
            "title": "ML Engineer",
            "company": "Anthropic",
            "url": "https://anthropic.com/careers/1",
            "location": "Remote",
            "company_linkedin_url": "https://www.linkedin.com/company/anthropicresearch",
        }
        card_html = _render_job_card(job)
        self.assertIn("https://www.linkedin.com/company/anthropicresearch", card_html)
        self.assertIn("💼 LinkedIn", card_html)

    def test_build_justjoin_html_includes_linkedin_link(self):
        ai_jobs = [
            {
                "title": "AI Architect",
                "company": "DeepMind",
                "url": "https://justjoin.it/job-offer/deepmind-ai",
                "location": "London",
                "company_linkedin_url": "https://www.linkedin.com/company/google-deepmind",
            }
        ]
        html = build_justjoin_html(ai_jobs, [])
        self.assertIn("https://www.linkedin.com/company/google-deepmind", html)
        self.assertIn("💼 LinkedIn", html)

    def test_build_legacy_html_includes_linkedin_link(self):
        report = [
            (
                "OpenAI",
                [
                    {
                        "title": "Research Engineer",
                        "url": "https://openai.com/careers/1",
                        "location": "San Francisco",
                        "company_linkedin_url": "https://www.linkedin.com/company/openai",
                    }
                ],
            )
        ]
        html = build_legacy_html(report, 1)
        self.assertIn("https://www.linkedin.com/company/openai", html)
        self.assertIn("💼 LinkedIn", html)


if __name__ == "__main__":
    unittest.main()
