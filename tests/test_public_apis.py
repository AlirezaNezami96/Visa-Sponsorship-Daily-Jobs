import unittest
from unittest.mock import MagicMock, patch

from fetchers_public_apis import (
    fetch_remoteok,
    fetch_remotive,
    fetch_arbeitnow,
    fetch_himalayas,
    fetch_hn_who_is_hiring,
)


class TestPublicApis(unittest.TestCase):
    @patch("fetchers_public_apis._session")
    def test_fetch_remoteok_parsing(self, mock_sess_fn):
        mock_sess = MagicMock()
        mock_sess_fn.return_value = mock_sess
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"legal": "notice"},
            {
                "id": "12345",
                "position": "AI Engineer",
                "company": "Smart AI Inc",
                "url": "https://remoteok.com/job/12345",
                "location": "Worldwide",
                "salary_min": 100000,
                "salary_max": 130000,
                "description": "<p>Build LLM features</p>",
            }
        ]
        mock_sess.get.return_value = mock_resp

        jobs = fetch_remoteok(tags=("ai",))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "AI Engineer")
        self.assertEqual(jobs[0]["company"], "Smart AI Inc")
        self.assertEqual(jobs[0]["source"], "RemoteOK")
        self.assertTrue(jobs[0]["remote"])

    @patch("fetchers_public_apis._session")
    def test_fetch_arbeitnow_parsing(self, mock_sess_fn):
        mock_sess = MagicMock()
        mock_sess_fn.return_value = mock_sess
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "title": "Junior Machine Learning Engineer",
                    "company_name": "Deep Tech GmbH",
                    "url": "https://arbeitnow.com/job/789",
                    "remote": True,
                    "location": "Berlin",
                    "tags": ["python", "visa sponsorship"],
                    "description": "Develop ML pipelines",
                }
            ]
        }
        mock_sess.get.return_value = mock_resp

        jobs = fetch_arbeitnow()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Junior Machine Learning Engineer")
        self.assertTrue(jobs[0]["visa_sponsorship"])
        self.assertTrue(jobs[0]["remote"])


if __name__ == "__main__":
    unittest.main()
