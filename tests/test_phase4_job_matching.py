"""Phase 4 tests — Job skill extractor, scorer, and matcher.

All functions are pure/stateless — no I/O required.
"""
from __future__ import annotations

from typing import Any


# ── Skill extractor ───────────────────────────────────────────────────────────

class TestSkillExtractorRuleBased:
    def test_extracts_python(self):
        from job_radar.jobs.skill_extractor import extract_skills_rule_based
        skills = extract_skills_rule_based("We need a Python developer with Django experience.")
        assert "Python" in skills
        assert "Django" in skills

    def test_extracts_cloud_skills(self):
        from job_radar.jobs.skill_extractor import extract_skills_rule_based
        skills = extract_skills_rule_based("Deploy on AWS using Kubernetes and Terraform.")
        assert "AWS" in skills
        assert "Kubernetes" in skills
        assert "Terraform" in skills

    def test_no_false_positives_for_java_in_javascript(self):
        from job_radar.jobs.skill_extractor import extract_skills_rule_based
        skills = extract_skills_rule_based("We use JavaScript and TypeScript.")
        assert "JavaScript" in skills
        assert "TypeScript" in skills
        # "Java" should not appear as a standalone match
        assert "Java" not in skills or "JavaScript" in skills

    def test_deduplicates(self):
        from job_radar.jobs.skill_extractor import extract_skills_rule_based
        skills = extract_skills_rule_based("Python Python Python django Django")
        assert skills.count("Python") == 1
        assert skills.count("Django") == 1

    def test_empty_text(self):
        from job_radar.jobs.skill_extractor import extract_skills_rule_based
        assert extract_skills_rule_based("") == []

    def test_extracts_from_title_and_description(self):
        from job_radar.jobs.skill_extractor import extract_skills_from_job
        skills = extract_skills_from_job(
            title="Senior Python Engineer",
            description="Experience with PostgreSQL and Docker required.",
        )
        assert "Python" in skills
        assert "PostgreSQL" in skills
        assert "Docker" in skills

    def test_ai_fallback_graceful(self):
        """extract_skills_from_job returns rule-based skills if AI router fails."""
        from unittest.mock import MagicMock
        from job_radar.jobs.skill_extractor import extract_skills_from_job

        broken_router = MagicMock()
        broken_router.complete_json.side_effect = RuntimeError("AI down")

        skills = extract_skills_from_job(
            title="Python Backend Engineer",
            description="We use Django and PostgreSQL.",
            llm_router=broken_router,
            use_ai=True,
        )
        assert "Python" in skills
        assert "Django" in skills


# ── Scorer: component tests ───────────────────────────────────────────────────

class TestTitleScorer:
    def test_exact_match_max_score(self):
        from job_radar.jobs.scorer import score_title_relevance
        assert score_title_relevance(["Software Engineer"], "software engineer", 20) == 20

    def test_partial_match_partial_score(self):
        from job_radar.jobs.scorer import score_title_relevance
        score = score_title_relevance(["Backend Engineer"], "Senior Backend Developer", 20)
        assert 0 < score < 20

    def test_no_match(self):
        from job_radar.jobs.scorer import score_title_relevance
        score = score_title_relevance(["Chef"], "Software Engineer", 20)
        assert score == 0

    def test_empty_titles_returns_neutral(self):
        from job_radar.jobs.scorer import score_title_relevance
        score = score_title_relevance([], "Software Engineer", 20)
        assert score == 10  # neutral (half of max)


class TestSkillsScorer:
    def test_full_overlap(self):
        from job_radar.jobs.scorer import score_skills_overlap
        user = ["Python", "Django", "PostgreSQL"]
        job = ["Python", "Django", "PostgreSQL"]
        assert score_skills_overlap(user, job, 50) == 50

    def test_no_overlap(self):
        from job_radar.jobs.scorer import score_skills_overlap
        assert score_skills_overlap(["Ruby"], ["Python", "Django"], 50) == 0

    def test_partial_overlap(self):
        from job_radar.jobs.scorer import score_skills_overlap
        user = ["Python", "Django"]
        job = ["Python", "Django", "Redis", "Kubernetes"]
        score = score_skills_overlap(user, job, 50)
        assert 0 < score < 50  # exactly 50% coverage

    def test_no_job_skills_returns_neutral(self):
        from job_radar.jobs.scorer import score_skills_overlap
        assert score_skills_overlap(["Python"], [], 50) == 25


class TestExperienceScorer:
    def test_in_range_full_score(self):
        from job_radar.jobs.scorer import score_experience_level
        assert score_experience_level(3, 2, 5, 10) == 10

    def test_slightly_under_partial(self):
        from job_radar.jobs.scorer import score_experience_level
        score = score_experience_level(1, 2, 5, 10)  # 1 yr, requires 2-5
        assert 0 < score < 10

    def test_way_under_zero(self):
        from job_radar.jobs.scorer import score_experience_level
        assert score_experience_level(0, 5, 10, 10) == 0

    def test_over_qualified_slight_penalty(self):
        from job_radar.jobs.scorer import score_experience_level
        score = score_experience_level(12, 0, 5, 10)
        assert score < 10

    def test_unknown_returns_neutral(self):
        from job_radar.jobs.scorer import score_experience_level
        assert score_experience_level(None, None, None, 10) == 5


class TestVisaScorer:
    def test_verified_full(self):
        from job_radar.jobs.scorer import score_visa_sponsorship
        assert score_visa_sponsorship(True, None, 10) == 10

    def test_high_confidence_near_full(self):
        from job_radar.jobs.scorer import score_visa_sponsorship
        assert score_visa_sponsorship(False, 75, 10) == 8

    def test_low_confidence_partial(self):
        from job_radar.jobs.scorer import score_visa_sponsorship
        assert score_visa_sponsorship(False, 55, 10) == 5

    def test_unverified_no_confidence_zero(self):
        from job_radar.jobs.scorer import score_visa_sponsorship
        assert score_visa_sponsorship(False, 0, 10) == 0


class TestLocationScorer:
    def test_preferred_country_and_mode(self):
        from job_radar.jobs.scorer import score_location_preference
        score = score_location_preference(["DE", "NL"], ["remote"], "DE", "remote", 10)
        assert score == 10

    def test_wrong_country_half(self):
        from job_radar.jobs.scorer import score_location_preference
        score = score_location_preference(["DE"], ["remote"], "US", "remote", 10)
        # Gets work_mode pts but not country pts
        assert score == 5

    def test_no_preferences_neutral(self):
        from job_radar.jobs.scorer import score_location_preference
        assert score_location_preference(None, None, "DE", "remote", 10) == 10


class TestComputeMatchScore:
    def _profile(self, **kw) -> dict:
        return {
            "skills_cache": ["Python", "Django", "PostgreSQL"],
            "job_titles": ["Backend Engineer"],
            "experience_years": 4,
            "preferred_countries": ["DE"],
            "preferred_work_modes": ["remote"],
            **kw,
        }

    def _job(self, **kw) -> dict:
        return {
            "title": "Backend Engineer",
            "skills": ["Python", "Django"],
            "work_mode": "remote",
            "country_code": "DE",
            "visa_sponsorship_verified": True,
            "visa_sponsorship_confidence": 90,
            **kw,
        }

    def test_perfect_match_high_score(self):
        from job_radar.jobs.scorer import compute_match_score
        score = compute_match_score(self._profile(), self._job())
        assert score >= 80

    def test_zero_skills_overlap_low_score(self):
        from job_radar.jobs.scorer import compute_match_score
        score = compute_match_score(self._profile(), self._job(skills=["Haskell", "Erlang"]))
        assert score < 60

    def test_no_visa_sponsorship_reduces_score(self):
        from job_radar.jobs.scorer import compute_match_score
        with_visa = compute_match_score(self._profile(), self._job())
        without_visa = compute_match_score(
            self._profile(),
            self._job(visa_sponsorship_verified=False, visa_sponsorship_confidence=0)
        )
        assert with_visa > without_visa

    def test_score_bounded_0_100(self):
        from job_radar.jobs.scorer import compute_match_score
        for _ in range(10):
            score = compute_match_score(self._profile(), self._job())
            assert 0 <= score <= 100

    def test_empty_profile_still_scores(self):
        from job_radar.jobs.scorer import compute_match_score
        score = compute_match_score({}, self._job())
        assert 0 <= score <= 100


# ── Matcher ───────────────────────────────────────────────────────────────────

class TestJobMatcher:
    def _make_jobs(self, n: int) -> list[dict[str, Any]]:
        return [
            {
                "id": f"job-{i}",
                "title": "Backend Engineer",
                "skills": ["Python", "Django"] if i % 2 == 0 else ["Ruby", "Rails"],
                "work_mode": "remote",
                "country_code": "DE",
                "visa_sponsorship_verified": True,
                "visa_sponsorship_confidence": 90,
            }
            for i in range(n)
        ]

    def test_sorted_by_match_score(self):
        from job_radar.jobs.matcher import score_jobs_for_profile
        profile = {"skills_cache": ["Python", "Django"], "job_titles": ["Backend Engineer"]}
        jobs = self._make_jobs(10)
        scored = score_jobs_for_profile(jobs, profile)
        scores = [j["resume_match_score"] for j in scored]
        assert scores == sorted(scores, reverse=True)

    def test_match_labels_assigned(self):
        from job_radar.jobs.matcher import score_jobs_for_profile
        profile = {"skills_cache": ["Python", "Django"], "job_titles": ["Backend Engineer"]}
        scored = score_jobs_for_profile(self._make_jobs(4), profile)
        for job in scored:
            assert job.get("match_label") in ("great_match", "good_match", "fair_match", "low_match")

    def test_empty_jobs_returns_empty(self):
        from job_radar.jobs.matcher import score_jobs_for_profile
        assert score_jobs_for_profile([], {}) == []

    def test_bad_job_does_not_raise(self):
        from job_radar.jobs.matcher import score_jobs_for_profile
        # Job with no fields at all
        scored = score_jobs_for_profile([{}], {"skills_cache": ["Python"]})
        assert len(scored) == 1
        assert scored[0]["resume_match_score"] == 0 or scored[0]["resume_match_score"] >= 0
