import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from classify_relevance import ClassificationCache, classify_single_job, classify_and_filter_jobs
from config_loader import RadarConfig, ClassifierConfig


class TestClassifier(unittest.TestCase):
    def setUp(self):
        self.tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.tmp_file.close()

    def tearDown(self):
        if os.path.exists(self.tmp_file.name):
            os.unlink(self.tmp_file.name)

    def test_cache_set_and_get(self):
        cache = ClassificationCache(self.tmp_file.name)
        val = {
            "is_ai_ml_role": True,
            "track": "internship",
            "remote_scope": "worldwide",
            "relevance_score": 90,
            "why": "Great ML intern role"
        }
        cache.set("job1", val)
        cache.save()

        # Reload from disk
        cache2 = ClassificationCache(self.tmp_file.name)
        cached_val = cache2.get("job1")
        self.assertIsNotNone(cached_val)
        self.assertEqual(cached_val["relevance_score"], 90)

    @patch("classify_relevance._call_gemini")
    def test_classify_single_job_gemini_success(self, mock_gemini):
        mock_gemini.return_value = json.dumps({
            "is_ai_ml_role": True,
            "track": "new_grad_engineer",
            "remote_scope": "worldwide",
            "allowed_regions": ["Worldwide"],
            "relevance_score": 85,
            "why": "Direct AI engineering role building agentic workflows."
        })

        cfg = RadarConfig(classifier=ClassifierConfig(enabled=True, provider="gemini", cache_file=self.tmp_file.name))
        job = {
            "title": "Junior AI Engineer",
            "company": "Test AI",
            "location": "Remote",
            "url": "https://example.com/job123"
        }
        res = classify_single_job(job, config=cfg)
        self.assertTrue(res["is_ai_ml_role"])
        self.assertEqual(res["track"], "new_grad_engineer")
        self.assertEqual(res["relevance_score"], 85)

    def test_classify_and_filter_jobs_threshold(self):
        cfg = RadarConfig(classifier=ClassifierConfig(enabled=False, min_relevance_score=60, cache_file=self.tmp_file.name))
        jobs = [
            {"title": "Machine Learning Intern", "company": "Co A", "location": "Remote", "url": "https://a.com"},
            {"title": "Senior AI Architect", "company": "Co B", "location": "Remote", "url": "https://b.com"},
            {"title": "Backend Go Developer", "company": "Co C", "location": "Onsite", "url": "https://c.com"},
        ]
        passed, stats = classify_and_filter_jobs(jobs, config=cfg)
        self.assertEqual(stats["total_evaluated"], 3)
        self.assertEqual(len(passed), 2)
        self.assertEqual(passed[0]["company"], "Co A")
        self.assertEqual(passed[0]["classified_track"], "internship")
        self.assertEqual(passed[1]["company"], "Co B")


if __name__ == "__main__":
    unittest.main()
