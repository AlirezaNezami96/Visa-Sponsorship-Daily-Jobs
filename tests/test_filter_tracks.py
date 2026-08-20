import unittest
from filter import match_track, job_fingerprint, normalize_company_name, normalize_job_title


class TestFilterTracks(unittest.TestCase):
    def test_internship_track_matching(self):
        intern_titles = [
            "Machine Learning Research Intern",
            "AI Intern - Summer 2026",
            "Applied AI Intern",
            "Deep Learning Research Intern",
            "NLP Intern",
            "Computer Vision Internship",
            "Generative AI Fellowship",
            "Data Science Intern",
        ]
        for title in intern_titles:
            track = match_track(title)
            self.assertEqual(track, "internship", f"Failed for title: {title}")

    def test_engineer_track_matching(self):
        eng_titles = [
            "AI Engineer",
            "Machine Learning Engineer",
            "Junior AI Engineer",
            "Junior Machine Learning Engineer",
            "Associate AI Engineer",
            "Graduate ML Engineer",
            "Applied AI Engineer",
            "LLM Engineer",
            "MLOps Engineer",
            "AI Agent Engineer",
        ]
        for title in eng_titles:
            track = match_track(title)
            self.assertEqual(track, "engineer", f"Failed for title: {title}")

    def test_seniority_exclusion(self):
        senior_titles = [
            "Senior Machine Learning Engineer",
            "Staff AI Engineer",
            "Principal ML Engineer",
            "Lead AI Engineer",
            "Director of AI",
            "Head of Machine Learning",
            "VP of AI",
            "Senior AI Research Intern",  # Senior overrides
        ]
        for title in senior_titles:
            track = match_track(title)
            self.assertIsNone(track, f"Should reject senior role: {title}")

    def test_borderline_review(self):
        borderline_titles = [
            "Prompt Engineer",
            "Data Scientist",
            "AI Specialist",
        ]
        for title in borderline_titles:
            track = match_track(title)
            self.assertEqual(track, "borderline", f"Failed for borderline: {title}")

    def test_fingerprint_normalization(self):
        fp1 = job_fingerprint("Anthropic PBC", "Machine Learning Intern", "Remote - US")
        fp2 = job_fingerprint("Anthropic Inc.", "Machine Learning Internship", "Remote (United States)")
        self.assertEqual(fp1, fp2)


if __name__ == "__main__":
    unittest.main()
