import json
import os
import tempfile
import time
import unittest

from fetcher_custom import extract_jobs_from_html
from filter import _load_seen, dedupe
from funding_scraper import is_funding_announcement


class CustomExtractorTests(unittest.TestCase):
    def test_extracts_json_ld_and_detail_links_without_nav_links(self):
        html = """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"ItemList","itemListElement":[
          {"@type":"JobPosting","title":"Android Engineer","url":"/careers/jobs/42",
           "jobLocation":{"address":{"addressLocality":"Berlin"}}}
        ]}
        </script>
        <a href="/jobs/43">Flutter Developer</a>
        <a href="/careers">Careers</a>
        """

        jobs = extract_jobs_from_html(html, "https://example.com/careers")

        self.assertEqual(
            jobs,
            [
                {
                    "title": "Android Engineer",
                    "url": "https://example.com/careers/jobs/42",
                    "location": "Berlin",
                    "department": "",
                },
                {
                    "title": "Flutter Developer",
                    "url": "https://example.com/jobs/43",
                    "location": "",
                    "department": "",
                },
            ],
        )

    def test_trusts_opaque_urls_only_for_structured_job_postings(self):
        html = """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"JobPosting",
         "title":"Kotlin Multiplatform Engineer","url":"/open/42"}
        </script>
        """

        self.assertEqual(
            extract_jobs_from_html(html, "https://example.com/careers"),
            [
                {
                    "title": "Kotlin Multiplatform Engineer",
                    "url": "https://example.com/open/42",
                    "location": "",
                    "department": "",
                }
            ],
        )


class SeenStoreTests(unittest.TestCase):
    def test_migrates_legacy_urls_and_ignores_tracking_parameters(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as handle:
            json.dump(
                {
                    "Example|https://example.com/jobs/42?utm_source=old": {
                        "t": int(time.time())
                    }
                },
                handle,
            )
            path = handle.name
        try:
            seen = _load_seen(path)
            new = dedupe(
                "Example",
                [
                    {
                        "title": "Android Engineer",
                        "url": "https://example.com/jobs/42?utm_source=new",
                    }
                ],
                seen,
            )
            self.assertEqual(new, [])
        finally:
            os.unlink(path)


class FundingFilterTests(unittest.TestCase):
    def test_only_funding_announcements_match(self):
        self.assertTrue(is_funding_announcement("Mistral AI raises €100m in Series C funding"))
        self.assertFalse(is_funding_announcement("Five practical lessons from scaling an engineering team"))


if __name__ == "__main__":
    unittest.main()
