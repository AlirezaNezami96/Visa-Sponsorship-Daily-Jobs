import unittest
from email_sender import _build_radar_html, send_radar_digest


class TestEmailTemplate(unittest.TestCase):
    def test_build_radar_html_dual_track(self):
        internships = [{
            "title": "AI Research Intern",
            "company": "DeepMind",
            "url": "https://example.com/intern1",
            "location": "Remote (Worldwide)",
            "remote_scope": "worldwide",
            "relevance_score": 98,
            "why_matched": "Cutting-edge research on world models.",
            "source": "Greenhouse",
            "visa_sponsorship": True,
            "salary": "$55/hr",
        }]
        engineers = [{
            "title": "Junior ML Engineer",
            "company": "Scale AI",
            "url": "https://example.com/eng1",
            "location": "Remote (US/Canada)",
            "remote_scope": "region_restricted",
            "allowed_regions": ["US", "Canada"],
            "relevance_score": 85,
            "why_matched": "Deploying data annotation and RLHF pipelines.",
            "source": "RemoteOK",
            "visa_sponsorship": False,
            "salary": "$110,000 - $130,000",
        }]

        health = {"companies_scanned": 150, "boards_scanned": 5, "errors": 0}
        html = _build_radar_html(internships, engineers, health, show_visa_tag=True)

        self.assertIn("AI Research Intern", html)
        self.assertIn("DeepMind", html)
        self.assertIn("Junior ML Engineer", html)
        self.assertIn("Scale AI", html)
        self.assertIn("98% Match", html)
        self.assertIn("85% Match", html)
        self.assertIn("Visa Sponsor", html)
        self.assertIn("Scanned 150 companies", html)

    def test_send_radar_digest_skips_when_empty(self):
        result = send_radar_digest([], [], send_empty=False)
        self.assertFalse(result, "Should skip sending email when job lists are empty and send_empty=False")


if __name__ == "__main__":
    unittest.main()
