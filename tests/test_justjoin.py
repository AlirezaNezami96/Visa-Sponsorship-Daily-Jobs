"""Unit tests for JustJoin.it job scraper."""
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from job_radar.cli.justjoin_cmd import (
    _canonicalize_justjoin_url,
    dedupe_justjoin,
    run as run_justjoin,
)
from job_radar.fetchers.justjoin import (
    JUSTJOIN_URLS,
    extract_jobs_from_justjoin_html,
    fetch_justjoin_category_jobs,
    fetch_justjoin_jobs,
)
from job_radar.notifications.renderers import build_justjoin_html


class JustJoinExtractionTests(unittest.TestCase):
    def test_target_urls_match_exact_requirements(self):
        self.assertEqual(
            JUSTJOIN_URLS["AI / ML"],
            "https://justjoin.it/job-offers/all-locations/ai?published-date=1",
        )
        self.assertEqual(
            JUSTJOIN_URLS["Mobile"],
            "https://justjoin.it/job-offers/all-locations/mobile?published-date=1",
        )

    def test_extract_jobs_from_html_structure(self):
        sample_html = """
        <ul>
            <li data-index="0">
                <a class="offer-card" href="https://justjoin.it/job-offer/super-ai-senior-engineer-warszawa-ai" title="View offer Senior AI &amp; ML Engineer &#x2F; Architect"></a>
                <div>
                    <div>
                        <svg class="lucide-building"></svg>
                    </div>
                    <div>
                        <div>OpenAI Labs</div>
                    </div>
                </div>
                <div>
                    <button>
                        <svg class="lucide-map-pin"></svg>
                        <span>Warszawa, +2 Locations</span>
                    </button>
                </div>
                <span>Remote</span>
                <span>25 000 - 35 000 PLN/month</span>
            </li>
            <li data-index="1">
                <a class="offer-card" href="/job-offer/mobile-dev-ios-krakow-mobile" title="View offer iOS Developer"></a>
                <img alt="Apple Partner" src="/logo.png"/>
                <span>Kraków</span>
                <span>Hybrid</span>
            </li>
        </ul>
        """
        jobs = extract_jobs_from_justjoin_html(sample_html, "AI / ML")
        self.assertEqual(len(jobs), 2)

        j1 = jobs[0]
        # HTML entities properly unescaped
        self.assertEqual(j1["title"], "Senior AI & ML Engineer / Architect")
        self.assertEqual(j1["company"], "OpenAI Labs")
        self.assertEqual(j1["url"], "https://justjoin.it/job-offer/super-ai-senior-engineer-warszawa-ai")
        self.assertEqual(j1["location"], "Warszawa, +2 Locations")
        self.assertTrue(j1["remote"])
        self.assertIn("PLN/month", j1["salary"])
        self.assertEqual(j1["category"], "AI / ML")

        j2 = jobs[1]
        self.assertEqual(j2["title"], "iOS Developer")
        self.assertEqual(j2["company"], "Apple Partner")
        self.assertEqual(j2["url"], "https://justjoin.it/job-offer/mobile-dev-ios-krakow-mobile")
        self.assertFalse(j2["remote"])
        self.assertEqual(j2["category"], "AI / ML")

    def test_extract_jobs_empty_html(self):
        jobs = extract_jobs_from_justjoin_html("", "Mobile")
        self.assertEqual(jobs, [])


class JustJoinUrlCanonicalizationTests(unittest.TestCase):
    def test_canonicalize_url_strips_params(self):
        url = "https://justjoin.it/job-offer/some-role?utm_source=linkedin&ref=email"
        self.assertEqual(
            _canonicalize_justjoin_url(url),
            "https://justjoin.it/job-offer/some-role",
        )

    def test_canonicalize_url_empty(self):
        self.assertEqual(_canonicalize_justjoin_url(""), "")


class JustJoinDeduplicationTests(unittest.TestCase):
    def test_dedupe_justjoin(self):
        seen = {
            "openai|https://justjoin.it/job-offer/ai-lead": {"t": 1234567890}
        }
        candidate_jobs = [
            # Already in seen
            {
                "title": "AI Lead",
                "company": "OpenAI",
                "url": "https://justjoin.it/job-offer/ai-lead?ref=daily",
                "category": "AI / ML",
            },
            # New job
            {
                "title": "Flutter Engineer",
                "company": "Supercell",
                "url": "https://justjoin.it/job-offer/flutter-dev",
                "category": "Mobile",
            },
        ]

        new_jobs = dedupe_justjoin(candidate_jobs, seen)
        self.assertEqual(len(new_jobs), 1)
        self.assertEqual(new_jobs[0]["title"], "Flutter Engineer")
        self.assertIn("supercell|https://justjoin.it/job-offer/flutter-dev", seen)


class JustJoinHtmlRendererTests(unittest.TestCase):
    def test_build_justjoin_html_renders_categories(self):
        ai_jobs = [
            {
                "title": "AI Engineer",
                "company": "DeepMind",
                "url": "https://justjoin.it/job-offer/deepmind-ai",
                "location": "London / Remote",
                "remote": True,
                "salary": "£80,000/rok",
            }
        ]
        mobile_jobs = [
            {
                "title": "Android Developer",
                "company": "Spotify",
                "url": "https://justjoin.it/job-offer/spotify-android",
                "location": "Stockholm",
                "remote": False,
                "salary": None,
            }
        ]

        html = build_justjoin_html(ai_jobs, mobile_jobs)
        self.assertIn("JustJoin.it Daily Digest", html)
        self.assertIn("AI Engineer", html)
        self.assertIn("DeepMind", html)
        self.assertIn("Android Developer", html)
        self.assertIn("Spotify", html)
        self.assertIn("Apply on JustJoin →", html)


class JustJoinRunnerTests(unittest.TestCase):
    @patch("job_radar.cli.justjoin_cmd.fetch_justjoin_jobs")
    def test_run_dry_run(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "title": "Computer Vision Specialist",
                "company": "Robotics Inc",
                "url": "https://justjoin.it/job-offer/cv-spec",
                "category": "AI / ML",
                "location": "Warszawa",
                "remote": True,
            },
            {
                "title": "Senior iOS Engineer",
                "company": "Fintech Global",
                "url": "https://justjoin.it/job-offer/ios-lead",
                "category": "Mobile",
                "location": "Kraków",
                "remote": False,
            },
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_seen = os.path.join(tmp_dir, "seen.json")
            with patch("job_radar.cli.justjoin_cmd.JUSTJOIN_SEEN_FILE", temp_seen):
                ai_jobs, mobile_jobs = run_justjoin(dry_run=True)
                self.assertEqual(len(ai_jobs), 1)
                self.assertEqual(len(mobile_jobs), 1)
                self.assertEqual(ai_jobs[0]["title"], "Computer Vision Specialist")
                self.assertEqual(mobile_jobs[0]["title"], "Senior iOS Engineer")
                # Dry run should not write to file
                self.assertFalse(os.path.exists(temp_seen))


if __name__ == "__main__":
    unittest.main()
