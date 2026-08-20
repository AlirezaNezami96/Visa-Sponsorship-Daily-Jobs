"""Tests for the resume matcher module."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch


VALID_MATCH_RESPONSE = {
    "ats_score": 75,
    "score_rationale": "Strong Kotlin and Android background with relevant ML project.",
    "keywords_to_add": ["Kotlin Coroutines", "ONNX", "MLOps"],
    "keywords_to_deemphasize": ["Objective-C"],
    "section_suggestions": [
        {
            "section": "Experience — Acme Corp / Android Developer",
            "suggestion": "Reframe the on-device inference bullet to mention 'model optimization' and 'TFLite'."
        }
    ],
    "resume_editing_prompt": "In the Acme Corp bullet, change 'built inference module' to 'built TFLite inference module with 30ms p95 latency'. Do not change dates, employer names, or job titles."
}


class TestParseMatchResponse(unittest.TestCase):
    """Test the JSON parser for Gemini resume match output."""

    def _parse(self, raw):
        from job_radar.resume.matcher import _parse_match_response
        return _parse_match_response(raw)

    def test_valid_json_parsed(self):
        raw = json.dumps(VALID_MATCH_RESPONSE)
        result = self._parse(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["ats_score"], 75)

    def test_json_with_markdown_fence(self):
        raw = "```json\n" + json.dumps(VALID_MATCH_RESPONSE) + "\n```"
        result = self._parse(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["ats_score"], 75)

    def test_json_with_plain_fence(self):
        raw = "```\n" + json.dumps(VALID_MATCH_RESPONSE) + "\n```"
        result = self._parse(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["ats_score"], 75)

    def test_empty_string_returns_none(self):
        self.assertIsNone(self._parse(""))

    def test_garbage_returns_none(self):
        self.assertIsNone(self._parse("I'm sorry, I cannot ..."))

    def test_missing_ats_score_returns_none(self):
        raw = json.dumps({"keywords_to_add": ["Python"]})
        self.assertIsNone(self._parse(raw))

    def test_ats_score_not_int_returns_none(self):
        data = dict(VALID_MATCH_RESPONSE, ats_score="seventy-five")
        self.assertIsNone(self._parse(json.dumps(data)))

    def test_whitespace_stripped_before_parse(self):
        raw = "   \n" + json.dumps(VALID_MATCH_RESPONSE) + "\n   "
        result = self._parse(raw)
        self.assertIsNotNone(result)


class TestMatchResumeToJob(unittest.TestCase):
    """Test match_resume_to_job resilience and caching."""

    def _make_job(self, **kwargs):
        defaults = {
            "company": "DeepMind",
            "title": "Junior ML Engineer",
            "url": "https://deepmind.com/careers/123",
            "location": "London, UK",
            "description": "We are looking for a junior ML engineer...",
        }
        defaults.update(kwargs)
        return defaults

    def test_returns_none_on_empty_resume(self):
        from job_radar.resume.matcher import match_resume_to_job
        job = self._make_job()
        result = match_resume_to_job(job, resume_text="")
        self.assertIsNone(result)

    def test_returns_none_on_none_resume(self):
        from job_radar.resume.matcher import match_resume_to_job
        job = self._make_job()
        result = match_resume_to_job(job, resume_text=None)
        self.assertIsNone(result)

    def test_returns_none_when_disabled_via_config(self):
        from job_radar.resume.matcher import match_resume_to_job
        cfg = MagicMock()
        cfg.resume_matcher.enabled = False
        job = self._make_job()
        result = match_resume_to_job(job, resume_text="My resume...", config=cfg)
        self.assertIsNone(result)

    def test_cache_hit_skips_gemini(self):
        from job_radar.resume.matcher import match_resume_to_job, _cache_key
        job = self._make_job()
        key = _cache_key(job["company"], job["title"], job["url"])

        cache = MagicMock()
        cache.get.return_value = dict(VALID_MATCH_RESPONSE)

        with patch("job_radar.resume.matcher._call_gemini_resume") as mock_call:
            result = match_resume_to_job(job, resume_text="Some resume text", cache=cache)

        mock_call.assert_not_called()
        self.assertEqual(result["ats_score"], 75)

    @patch("job_radar.resume.matcher._call_gemini_resume")
    def test_successful_call_returns_dict(self, mock_call):
        from job_radar.resume.matcher import match_resume_to_job
        mock_call.return_value = json.dumps(VALID_MATCH_RESPONSE)

        cache = MagicMock()
        cache.get.return_value = None  # cache miss

        job = self._make_job()
        result = match_resume_to_job(job, resume_text="Experienced developer...", cache=cache)

        self.assertIsNotNone(result)
        self.assertEqual(result["ats_score"], 75)

    @patch("job_radar.resume.matcher._call_gemini_resume")
    def test_gemini_failure_returns_none_no_raise(self, mock_call):
        """Failure must not propagate — must return None."""
        from job_radar.resume.matcher import match_resume_to_job
        mock_call.side_effect = RuntimeError("API quota exceeded")

        cache = MagicMock()
        cache.get.return_value = None

        job = self._make_job()
        result = match_resume_to_job(job, resume_text="My resume...", cache=cache)
        self.assertIsNone(result)

    @patch("job_radar.resume.matcher._call_gemini_resume")
    def test_bad_json_returns_none(self, mock_call):
        from job_radar.resume.matcher import match_resume_to_job
        mock_call.return_value = "I apologize, I cannot complete this request."

        cache = MagicMock()
        cache.get.return_value = None

        job = self._make_job()
        result = match_resume_to_job(job, resume_text="My resume...", cache=cache)
        self.assertIsNone(result)


class TestMatchResumeBatch(unittest.TestCase):
    """Test the batch matching helper."""

    def test_empty_batch_returns_empty(self):
        from job_radar.resume.matcher import match_resume_batch
        result = match_resume_batch([], resume_text="My resume")
        self.assertEqual(result, [])

    def test_no_resume_sets_none_for_all(self):
        from job_radar.resume.matcher import match_resume_batch
        jobs = [{"company": "A", "title": "B", "url": "http://a.com"}]
        result = match_resume_batch(jobs, resume_text="")
        self.assertIsNone(result[0].get("resume_match"))

    @patch("job_radar.resume.matcher._call_gemini_resume")
    def test_batch_injects_resume_match_key(self, mock_call):
        from job_radar.resume.matcher import match_resume_batch
        mock_call.return_value = json.dumps(VALID_MATCH_RESPONSE)

        cache = MagicMock()
        cache.get.return_value = None

        jobs = [
            {"company": "Alpha", "title": "ML Intern", "url": "http://alpha.com"},
            {"company": "Beta", "title": "AI Trainee", "url": "http://beta.com"},
        ]

        with patch("job_radar.resume.matcher.ClassificationCache", return_value=cache):
            result = match_resume_batch(jobs, resume_text="My background includes...")

        for j in result:
            self.assertIn("resume_match", j)


if __name__ == "__main__":
    unittest.main()
