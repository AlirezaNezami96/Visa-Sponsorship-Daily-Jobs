import unittest
from filter import dedupe_radar_jobs, job_fingerprint


class TestDedupeFingerprint(unittest.TestCase):
    def test_cross_source_deduplication(self):
        seen = {}
        # Job 1 from direct company Greenhouse
        job_direct = {
            "title": "Machine Learning Intern",
            "company": "Anthropic",
            "url": "https://boards.greenhouse.io/anthropic/jobs/101?gh_src=custom",
            "location": "Remote (US)",
        }
        # Job 2 from RemoteOK aggregator with a different URL but same company/title/location
        job_remoteok = {
            "title": "Machine Learning Internship",
            "company": "Anthropic Inc.",
            "url": "https://remoteok.com/remote-jobs/999?utm_source=feed",
            "location": "Remote - US",
        }

        # Step 1: Ingest direct job
        res1 = dedupe_radar_jobs([job_direct], seen)
        self.assertEqual(len(res1), 1)

        # Step 2: Ingest remoteok job -> should be recognized as duplicate by fingerprint!
        res2 = dedupe_radar_jobs([job_remoteok], seen)
        self.assertEqual(len(res2), 0, "Duplicate job across different URLs should be filtered out by fingerprint")


if __name__ == "__main__":
    unittest.main()
