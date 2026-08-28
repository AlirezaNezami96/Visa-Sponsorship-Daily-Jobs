"""Unit tests for worker / Apify Actor email run alert notifications."""
import os
import unittest
from unittest.mock import MagicMock, patch

from job_radar.notifications.email import send_worker_run_alert
from job_radar.notifications.renderers import build_worker_run_alert_html


class TestWorkerEmailAlert(unittest.TestCase):
    def test_build_worker_run_alert_html_completed(self):
        html = build_worker_run_alert_html(
            run_id="run_1234567890",
            status="completed",
            inputs={
                "jobTitles": ["Software Engineer", "Backend Developer"],
                "keywords": ["Python", "Visa"],
                "countries": ["United Kingdom", "Germany"],
                "enableOverseasSources": True,
                "enableAiClassification": True,
                "maxResults": 50,
            },
            stats={
                "totalFetched": 500,
                "totalEmitted": 15,
                "visaEnrichedJobs": 12,
                "durationSeconds": 42.5,
            },
            run_url="https://console.apify.com/actors/abc/runs/123",
            dataset_url="https://console.apify.com/storage/datasets/xyz",
        )

        self.assertIn("COMPLETED", html)
        self.assertIn("run_1234567890", html)
        self.assertIn("Software Engineer", html)
        self.assertIn("United Kingdom", html)
        self.assertIn("500", html)
        self.assertIn("15", html)
        self.assertIn("42.5s", html)
        self.assertIn("https://console.apify.com/actors/abc/runs/123", html)
        self.assertIn("https://console.apify.com/storage/datasets/xyz", html)

    def test_build_worker_run_alert_html_failed(self):
        html = build_worker_run_alert_html(
            run_id="run_fail_123",
            status="failed",
            error_message="ConnectionError: DNS resolution failed for upstream ATS",
        )

        self.assertIn("FAILED", html)
        self.assertIn("run_fail_123", html)
        self.assertIn("ConnectionError: DNS resolution failed", html)

    def test_build_worker_run_alert_html_timed_out(self):
        html = build_worker_run_alert_html(
            run_id="run_timeout_456",
            status="timed_out",
            stats={"durationSeconds": 300, "totalEmitted": 8},
        )

        self.assertIn("TIMED OUT", html)
        self.assertIn("run_timeout_456", html)
        self.assertIn("300.0s", html)

    def test_send_worker_run_alert_skips_when_missing_email_to(self):
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_test_123"}, clear=True):
            result = send_worker_run_alert(run_id="test", status="completed")
            self.assertFalse(result, "Should return False when EMAIL_TO is not set")

    def test_send_worker_run_alert_skips_when_missing_api_key(self):
        with patch.dict(os.environ, {"EMAIL_TO": "dev@example.com"}, clear=True):
            result = send_worker_run_alert(run_id="test", status="completed", provider="resend")
            self.assertFalse(result, "Should return False when RESEND_API_KEY is not set")

    @patch("job_radar.notifications.email.http_requests.post")
    def test_send_worker_run_alert_resend_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        with patch.dict(
            os.environ,
            {
                "RESEND_API_KEY": "re_12345",
                "EMAIL_TO": "owner@example.com",
                "EMAIL_FROM": "alerts@jobradar.dev",
            },
            clear=True,
        ):
            result = send_worker_run_alert(
                run_id="run_abc12345",
                status="completed",
                stats={"totalEmitted": 10},
                provider="resend",
            )
            self.assertTrue(result)
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            self.assertEqual(call_args[0][0], "https://api.resend.com/emails")
            self.assertEqual(call_args[1]["headers"]["Authorization"], "Bearer re_12345")
            self.assertEqual(call_args[1]["json"]["to"], ["owner@example.com"])
            self.assertEqual(call_args[1]["json"]["from"], "alerts@jobradar.dev")
            self.assertIn("10 jobs found", call_args[1]["json"]["subject"])

    @patch("job_radar.notifications.email.http_requests.post")
    def test_send_worker_run_alert_handles_http_failure(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 500 Internal Error")
        mock_post.return_value = mock_resp

        with patch.dict(
            os.environ,
            {
                "RESEND_API_KEY": "re_12345",
                "EMAIL_TO": "owner@example.com",
            },
            clear=True,
        ):
            result = send_worker_run_alert(
                run_id="run_abc12345",
                status="completed",
                provider="resend",
            )
            self.assertFalse(result, "Should catch exception and return False safely")


if __name__ == "__main__":
    unittest.main()
