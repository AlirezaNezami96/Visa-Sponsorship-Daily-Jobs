import json
import os
import tempfile
import time
import unittest

from fetchers_jobboards import (
    JobListing,
    build_indeed_url,
    canonicalize_indeed_url,
    extract_jobs_from_indeed_html,
    get_indeed_domain,
    load_cache,
    load_config,
    save_cache,
)
from filter import _load_seen, dedupe_junior_ai, dedupe_junior_ai_multi, matches_junior_ai


class JobboardsDomainAndUrlTests(unittest.TestCase):
    def test_domain_mapping_and_resolution(self):
        config = {
            "country_domains": {
                "usa": "www.indeed.com",
                "uk": "uk.indeed.com",
                "canada": "ca.indeed.com",
                "germany": "de.indeed.com",
                "netherlands": "nl.indeed.com",
                "ireland": "ie.indeed.com",
            }
        }
        self.assertEqual(get_indeed_domain("USA", config), "www.indeed.com")
        self.assertEqual(get_indeed_domain("uk", config), "uk.indeed.com")
        self.assertEqual(get_indeed_domain("Canada", config), "ca.indeed.com")
        self.assertEqual(get_indeed_domain("Germany", config), "de.indeed.com")
        self.assertEqual(get_indeed_domain("Netherlands", config), "nl.indeed.com")
        self.assertEqual(get_indeed_domain("Ireland", config), "ie.indeed.com")
        # Unmapped fallback
        self.assertEqual(get_indeed_domain("UnknownCountry", config), "www.indeed.com")

    def test_build_indeed_url(self):
        url = build_indeed_url("ca.indeed.com", "Junior AI Engineer", location="Toronto")
        self.assertIn("https://ca.indeed.com/jobs?", url)
        self.assertIn("q=Junior+AI+Engineer", url)
        self.assertIn("l=Toronto", url)

    def test_canonicalize_indeed_url(self):
        url_with_tracking = (
            "https://www.indeed.com/viewjob?jk=abcdef1234567890&from=vjs&utm_source=jobseeker"
        )
        self.assertEqual(
            canonicalize_indeed_url(url_with_tracking),
            "https://www.indeed.com/viewjob?jk=abcdef1234567890",
        )

        relative_clk = "/rc/clk?jk=9876543210fedcba&from=serp"
        self.assertEqual(
            canonicalize_indeed_url(relative_clk, "uk.indeed.com"),
            "https://uk.indeed.com/viewjob?jk=9876543210fedcba",
        )


class JobboardsHtmlExtractionTests(unittest.TestCase):
    def test_extract_jobs_from_mosaic_job_cards(self):
        sample_html = """
        <div id="mosaic-provider-jobcards">
            <div class="job_seen_beacon" data-jk="1111111111111111">
                <h2 class="jobTitle">
                    <a class="jcs-JobTitle" href="/rc/clk?jk=1111111111111111" data-jk="1111111111111111">Junior AI Engineer</a>
                </h2>
                <span data-testid="company-name" class="css-63koeb">Anthropic AI</span>
                <div data-testid="text-location" class="css-1p0sjhy">London, UK</div>
                <div data-testid="attribute_snippet_testid">£45,000 - £60,000 a year</div>
                <span data-testid="myJobsStateDate">Just posted</span>
            </div>
            <div class="cardOutline" data-jk="2222222222222222">
                <h2 class="jobTitle">
                    <a href="/viewjob?jk=2222222222222222">Entry Level Machine Learning Developer (Remote)</a>
                </h2>
                <span class="companyName">DeepMind Tech</span>
                <div class="companyLocation">Remote</div>
                <span class="date">3 days ago</span>
            </div>
        </div>
        """
        listings = extract_jobs_from_indeed_html(sample_html, "uk.indeed.com")
        self.assertEqual(len(listings), 2)

        j1 = listings[0]
        self.assertEqual(j1.title, "Junior AI Engineer")
        self.assertEqual(j1.company, "Anthropic AI")
        self.assertEqual(j1.location, "London, UK")
        self.assertEqual(j1.url, "https://uk.indeed.com/viewjob?jk=1111111111111111")
        self.assertEqual(j1.salary, "£45,000 - £60,000 a year")
        self.assertEqual(j1.date_posted, "Just posted")

        j2 = listings[1]
        self.assertEqual(j2.title, "Entry Level Machine Learning Developer (Remote)")
        self.assertEqual(j2.company, "DeepMind Tech")
        self.assertEqual(j2.location, "Remote")
        self.assertTrue(j2.remote)

    def test_extract_jobs_from_json_ld(self):
        sample_json_ld_html = """
        <html>
        <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "title": "Graduate Machine Learning Engineer",
          "url": "https://www.indeed.com/viewjob?jk=3333333333333333",
          "hiringOrganization": {"name": "Mistral AI"},
          "jobLocation": {
            "address": {
              "addressLocality": "Paris",
              "addressCountry": "FR"
            }
          },
          "baseSalary": {"value": "€50,000/yr"}
        }
        </script>
        </head>
        <body></body>
        </html>
        """
        listings = extract_jobs_from_indeed_html(sample_json_ld_html, "fr.indeed.com")
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].title, "Graduate Machine Learning Engineer")
        self.assertEqual(listings[0].company, "Mistral AI")
        self.assertEqual(listings[0].location, "Paris")
        self.assertEqual(listings[0].salary, "€50,000/yr")


class DedupeJuniorAiMultiTests(unittest.TestCase):
    def test_matches_junior_ai_filter(self):
        self.assertTrue(matches_junior_ai("Junior AI Engineer"))
        self.assertTrue(matches_junior_ai("Entry Level Machine Learning Scientist"))
        self.assertTrue(matches_junior_ai("Graduate AI Developer"))
        self.assertTrue(matches_junior_ai("Associate ML Engineer"))
        self.assertTrue(matches_junior_ai("Early Career Deep Learning Researcher"))

        # Should exclude senior or non-junior roles
        self.assertFalse(matches_junior_ai("Senior AI Engineer"))
        self.assertFalse(matches_junior_ai("Lead Machine Learning Engineer"))
        self.assertFalse(matches_junior_ai("Principal AI Architect"))
        self.assertFalse(matches_junior_ai("Senior Android Engineer"))
        self.assertFalse(matches_junior_ai("Java Developer"))

    def test_dedupe_junior_ai_multi_with_seen_store(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "open ai|https://www.indeed.com/viewjob?jk=1010101010101010": {"t": int(time.time())}
            }, f)
            temp_seen_path = f.name

        try:
            seen = _load_seen(temp_seen_path)
            candidate_batch = [
                # Already seen
                {
                    "title": "Junior AI Engineer",
                    "url": "https://www.indeed.com/viewjob?jk=1010101010101010&utm_source=email",
                    "company": "Open AI",
                    "location": "San Francisco, CA",
                },
                # New valid junior AI job
                {
                    "title": "Entry Level Machine Learning Engineer",
                    "url": "https://www.indeed.com/viewjob?jk=2020202020202020",
                    "company": "Anthropic",
                    "location": "Remote",
                },
                # Excluded (Senior)
                {
                    "title": "Senior AI Researcher",
                    "url": "https://www.indeed.com/viewjob?jk=3030303030303030",
                    "company": "Google",
                    "location": "Mountain View, CA",
                },
            ]

            new_jobs = dedupe_junior_ai_multi(candidate_batch, seen)
            self.assertEqual(len(new_jobs), 1)
            self.assertEqual(new_jobs[0]["title"], "Entry Level Machine Learning Engineer")
            self.assertEqual(new_jobs[0]["company"], "Anthropic")

            # Check seen store update
            self.assertIn("anthropic|https://www.indeed.com/viewjob?jk=2020202020202020", seen)

            # Test backward-compatible dedupe_junior_ai
            single_co_jobs = dedupe_junior_ai(
                "Cohort",
                [
                    {
                        "title": "Associate AI Engineer",
                        "url": "https://www.indeed.com/viewjob?jk=4040404040404040",
                    }
                ],
                seen,
            )
            self.assertEqual(len(single_co_jobs), 1)
            self.assertEqual(single_co_jobs[0]["company"], "Cohort")
        finally:
            if os.path.exists(temp_seen_path):
                os.unlink(temp_seen_path)


class CacheManagementTests(unittest.TestCase):
    def test_save_and_load_cache(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            temp_cache_path = f.name

        try:
            cache_data = {
                "indeed_usa": {
                    "last_success": time.time(),
                    "strategy": "deterministic_html",
                }
            }
            save_cache(cache_data, temp_cache_path)
            loaded = load_cache(temp_cache_path)
            self.assertEqual(loaded["indeed_usa"]["strategy"], "deterministic_html")
        finally:
            if os.path.exists(temp_cache_path):
                os.unlink(temp_cache_path)


class CircuitBreakerTests(unittest.TestCase):
    def test_circuit_breaker_trips_on_consecutive_failures(self):
        from unittest.mock import patch
        from job_radar.fetchers.jobboards import fetch_all_jobboard_jobs

        with patch("job_radar.fetchers.jobboards.fetch_indeed_jobs", return_value=[]) as mock_fetch:
            countries = ["USA", "UK", "Canada", "Germany", "France"]
            queries = ["Junior AI Engineer", "Junior ML Engineer"]
            # 5 * 2 = 10 total queries
            jobs = fetch_all_jobboard_jobs(countries=countries, queries=queries)
            self.assertEqual(len(jobs), 0)
            # Circuit breaker should trip after 3 consecutive failures, calling mock_fetch exactly 3 times instead of 10
            self.assertEqual(mock_fetch.call_count, 3)


if __name__ == "__main__":
    unittest.main()

