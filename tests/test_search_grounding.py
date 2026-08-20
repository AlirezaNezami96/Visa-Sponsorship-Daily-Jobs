"""Tests for Gemini Search-Grounded Job Discovery (4th source)."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from job_radar.fetchers.search_grounding import (
    CATEGORY_PROFILES,
    _call_gemini_grounded,
    _is_blacklisted_url,
    _normalize,
    _parse_grounded_response,
    build_search_grounding_prompt,
    fetch_search_grounded_jobs,
)


SAMPLE_RAW_JOB = {
    "title": "Machine Learning Engineer",
    "company": "Anthropic",
    "apply_url": "https://jobs.ashbyhq.com/anthropic/123",
    "location": "Remote",
    "workplace_type": "Remote",
    "visa_sponsorship": True,
    "posted_date": "2026-08-18",
    "tech_stack": ["Python", "PyTorch", "Kubernetes"],
    "summary": "Build foundation models and inference infrastructure.",
}


class TestCategoryProfiles(unittest.TestCase):
    """Test category profiles and prompt construction."""

    def test_all_expected_categories_present(self):
        expected = {"remote", "visa_sponsorship", "ai_intern"}
        self.assertTrue(expected.issubset(set(CATEGORY_PROFILES.keys())))

    def test_profile_keys(self):
        for cat, profile in CATEGORY_PROFILES.items():
            self.assertIn("label", profile)
            self.assertIn("query_hints", profile)
            self.assertIn("verify", profile)
            self.assertIsInstance(profile["query_hints"], list)
            self.assertTrue(len(profile["query_hints"]) > 0)

    def test_prompt_contains_rules_and_hints(self):
        prompt = build_search_grounding_prompt("visa_sponsorship", max_age_days=5)
        self.assertIn("roles where the posting itself offers visa sponsorship", prompt)
        self.assertIn("SOURCE RESTRICTION", prompt)
        self.assertIn("STRICT BLACKLIST", prompt)
        self.assertIn("LinkedIn", prompt)
        self.assertIn("Indeed", prompt)
        self.assertIn("5 days", prompt)
        self.assertIn("url_context", prompt)
        self.assertIn("NO minimum result count", prompt)


class TestParseGroundedResponse(unittest.TestCase):
    """Test parsing of Gemini search-grounded JSON output."""

    def test_parse_valid_json_array(self):
        raw = json.dumps([SAMPLE_RAW_JOB])
        parsed = _parse_grounded_response(raw)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["title"], "Machine Learning Engineer")

    def test_parse_markdown_json_fence(self):
        raw = f"```json\n{json.dumps([SAMPLE_RAW_JOB])}\n```"
        parsed = _parse_grounded_response(raw)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["company"], "Anthropic")

    def test_parse_plain_fence(self):
        raw = f"```\n{json.dumps([SAMPLE_RAW_JOB])}\n```"
        parsed = _parse_grounded_response(raw)
        self.assertEqual(len(parsed), 1)

    def test_parse_wrapped_in_dict_jobs(self):
        raw = json.dumps({"jobs": [SAMPLE_RAW_JOB]})
        parsed = _parse_grounded_response(raw)
        self.assertEqual(len(parsed), 1)

    def test_parse_wrapped_in_dict_results(self):
        raw = json.dumps({"results": [SAMPLE_RAW_JOB]})
        parsed = _parse_grounded_response(raw)
        self.assertEqual(len(parsed), 1)

    def test_parse_empty_string(self):
        self.assertEqual(_parse_grounded_response(""), [])

    def test_parse_garbage_text(self):
        self.assertEqual(_parse_grounded_response("I searched Google and found nothing."), [])

    def test_parse_embedded_json_in_text(self):
        raw = f"Here are the found postings:\n[{json.dumps(SAMPLE_RAW_JOB)}]\nHope this helps!"
        parsed = _parse_grounded_response(raw)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["title"], "Machine Learning Engineer")


class TestNormalizeAndBlacklist(unittest.TestCase):
    """Test normalization and domain filtering."""

    def test_valid_job_normalization(self):
        norm = _normalize(SAMPLE_RAW_JOB, category="ai_intern")
        self.assertIsNotNone(norm)
        self.assertEqual(norm["title"], "Machine Learning Engineer")
        self.assertEqual(norm["url"], "https://jobs.ashbyhq.com/anthropic/123")
        self.assertEqual(norm["company"], "Anthropic")
        self.assertEqual(norm["category"], "ai_intern")
        self.assertEqual(norm["source"], "SEARCH_GROUNDING")
        self.assertTrue(norm["remote"])
        self.assertTrue(norm["visa_sponsorship"])

    def test_blacklisted_domains_dropped(self):
        blacklisted_jobs = [
            dict(SAMPLE_RAW_JOB, apply_url="https://www.linkedin.com/jobs/view/123"),
            dict(SAMPLE_RAW_JOB, apply_url="https://www.indeed.com/viewjob?jk=456"),
            dict(SAMPLE_RAW_JOB, apply_url="https://www.glassdoor.com/job-listing/789"),
            dict(SAMPLE_RAW_JOB, apply_url="https://remotive.com/remote-jobs/123"),
            dict(SAMPLE_RAW_JOB, apply_url="https://weworkremotely.com/remote-jobs/123"),
        ]
        for job in blacklisted_jobs:
            self.assertIsNone(_normalize(job, category="remote"))

    def test_missing_required_fields_dropped(self):
        self.assertIsNone(_normalize(dict(SAMPLE_RAW_JOB, title=""), category="remote"))
        self.assertIsNone(_normalize(dict(SAMPLE_RAW_JOB, apply_url=""), category="remote"))
        self.assertIsNone(_normalize(dict(SAMPLE_RAW_JOB, company=""), category="remote"))

    def test_is_blacklisted_url_helper(self):
        self.assertTrue(_is_blacklisted_url("https://www.linkedin.com/jobs/view/999"))
        self.assertTrue(_is_blacklisted_url("https://indeed.com/viewjob"))
        self.assertFalse(_is_blacklisted_url("https://boards.greenhouse.io/openai/jobs/123"))
        self.assertFalse(_is_blacklisted_url("https://jobs.ashbyhq.com/perplexity/456"))


class TestFetchSearchGroundedJobs(unittest.TestCase):
    """Test fetch_search_grounded_jobs orchestration and fail-open resilience."""

    def test_unknown_category_returns_empty(self):
        result = fetch_search_grounded_jobs("nonexistent_category")
        self.assertEqual(result, [])

    def test_missing_api_key_returns_empty(self):
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("GEMINI_API_KEY", None)
            result = fetch_search_grounded_jobs("remote")
            self.assertEqual(result, [])

    def test_disabled_in_config_returns_empty(self):
        cfg = MagicMock()
        cfg.search_grounding.enabled = False
        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}):
            result = fetch_search_grounded_jobs("remote", config=cfg)
            self.assertEqual(result, [])

    @patch("job_radar.fetchers.search_grounding._call_gemini_grounded")
    def test_successful_fetch_returns_normalized_jobs(self, mock_call):
        mock_call.return_value = (json.dumps([SAMPLE_RAW_JOB]), set())
        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}):
            cfg = MagicMock()
            cfg.search_grounding.enabled = True
            cfg.search_grounding.model = "gemini-3.7-flash"
            cfg.search_grounding.fallback_model = "gemini-3.6-flash"
            cfg.search_grounding.thinking_level = "HIGH"
            cfg.freshness.max_age_days = 5

            jobs = fetch_search_grounded_jobs("visa_sponsorship", config=cfg)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["company"], "Anthropic")
            self.assertEqual(jobs[0]["category"], "visa_sponsorship")

    @patch("job_radar.fetchers.search_grounding._call_gemini_grounded")
    def test_api_exception_returns_empty_without_raising(self, mock_call):
        mock_call.side_effect = RuntimeError("Google API Rate limit reached")
        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}):
            cfg = MagicMock()
            cfg.search_grounding.enabled = True
            jobs = fetch_search_grounded_jobs("remote", config=cfg)
            self.assertEqual(jobs, [])


if __name__ == "__main__":
    unittest.main()
