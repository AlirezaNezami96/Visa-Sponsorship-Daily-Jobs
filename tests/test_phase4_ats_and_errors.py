"""Phase 4 tests — ATS scorer (Python) and unified error hierarchy.

ATS scorer is fully deterministic — no mocking needed.
Error tests verify error codes, HTTP statuses, and serialization.
"""
from __future__ import annotations


# ── ATS Scorer ────────────────────────────────────────────────────────────────

class TestKeywordOverlap:
    def test_full_overlap(self):
        from job_radar.ai.ats_scorer import score_keyword_overlap
        text = "Python Django REST API developer with SQL experience"
        score = score_keyword_overlap(text, text, 40)
        assert score == 40

    def test_no_overlap(self):
        from job_radar.ai.ats_scorer import score_keyword_overlap
        score = score_keyword_overlap("Ruby Rails gems", "Python Django databases", 40)
        assert score < 20

    def test_empty_resume_neutral(self):
        from job_radar.ai.ats_scorer import score_keyword_overlap
        assert score_keyword_overlap("", "Python Developer needed", 40) == 20

    def test_empty_jd_neutral(self):
        from job_radar.ai.ats_scorer import score_keyword_overlap
        assert score_keyword_overlap("Python developer", "", 40) == 20

    def test_stop_words_excluded(self):
        from job_radar.ai.ats_scorer import score_keyword_overlap
        # JD is only stop words — should give neutral score
        score = score_keyword_overlap("Our team is the best and we are great", "the and are for", 40)
        assert score == 20  # neutral when jd_keywords is empty


class TestAtsSkillsOverlap:
    def test_full_match(self):
        from job_radar.ai.ats_scorer import score_skills_overlap
        assert score_skills_overlap(["Python", "Django"], ["python", "django"], 30) == 30

    def test_case_insensitive(self):
        from job_radar.ai.ats_scorer import score_skills_overlap
        score = score_skills_overlap(["PYTHON"], ["python"], 30)
        assert score == 30

    def test_no_job_skills_neutral(self):
        from job_radar.ai.ats_scorer import score_skills_overlap
        assert score_skills_overlap(["Python"], [], 30) == 15


class TestAtsTitleMatch:
    def test_exact_match_full(self):
        from job_radar.ai.ats_scorer import score_title_match
        assert score_title_match(["Software Engineer"], "Software Engineer", 20) == 20

    def test_no_titles_partial(self):
        from job_radar.ai.ats_scorer import score_title_match
        score = score_title_match([], "Software Engineer", 20)
        assert score <= 5  # slight penalty, not zero

    def test_word_overlap_partial(self):
        from job_radar.ai.ats_scorer import score_title_match
        score = score_title_match(["Backend Engineer"], "Senior Backend Developer", 20)
        assert 0 < score < 20


class TestAtsFormatQuality:
    def test_complete_resume_full_score(self):
        from job_radar.ai.ats_scorer import score_format_quality
        parsed = {
            "summary": "Experienced engineer",
            "skills": ["Python"],
            "experience": [{"company": "Acme"}],
            "education": [{"institution": "MIT"}],
        }
        assert score_format_quality(parsed, 10) == 10

    def test_missing_summary_deducts(self):
        from job_radar.ai.ats_scorer import score_format_quality
        parsed = {
            "summary": "",
            "skills": ["Python"],
            "experience": [{}],
            "education": [{}],
        }
        score = score_format_quality(parsed, 10)
        assert score < 10

    def test_missing_everything_minimum(self):
        from job_radar.ai.ats_scorer import score_format_quality
        assert score_format_quality({}, 10) == 0
        assert score_format_quality(None, 10) == 0


class TestComputeAtsScore:
    def _full_args(self):
        return {
            "resume_text": "Python Django REST API developer PostgreSQL SQL",
            "resume_skills": ["Python", "Django", "PostgreSQL"],
            "resume_titles": ["Backend Engineer"],
            "parsed_resume": {
                "summary": "5 years backend",
                "skills": ["Python", "Django"],
                "experience": [{"company": "Acme"}],
                "education": [{"institution": "MIT"}],
            },
            "job_description": "Looking for a Python Django developer with SQL skills",
            "job_skills": ["Python", "Django", "SQL"],
            "job_title": "Backend Engineer",
        }

    def test_composite_score_0_100(self):
        from job_radar.ai.ats_scorer import compute_ats_score
        score = compute_ats_score(**self._full_args())
        assert 0 <= score <= 100

    def test_perfect_match_high_score(self):
        from job_radar.ai.ats_scorer import compute_ats_score
        score = compute_ats_score(**self._full_args())
        assert score >= 70

    def test_mismatch_lower_score(self):
        from job_radar.ai.ats_scorer import compute_ats_score
        args = self._full_args()
        args["resume_text"] = "Ruby Rails gems Sinatra"
        args["resume_skills"] = ["Ruby", "Rails"]
        args["resume_titles"] = ["Ruby Developer"]
        score = compute_ats_score(**args)
        # Significantly lower than the matched version
        matched = compute_ats_score(**self._full_args())
        assert score < matched


# ── Error hierarchy ───────────────────────────────────────────────────────────

class TestErrorBase:
    def test_code_and_message(self):
        from job_radar.errors import VisaLaneError
        e = VisaLaneError("Something went wrong")
        assert e.code == "internal_error"
        assert e.message == "Something went wrong"
        assert e.http_status == 500

    def test_to_dict_shape(self):
        from job_radar.errors import VisaLaneError
        e = VisaLaneError("Test error")
        d = e.to_dict()
        assert "error" in d
        assert d["error"]["code"] == "internal_error"
        assert "request_id" in d["error"]
        assert "timestamp" in d["error"]

    def test_user_message_default(self):
        from job_radar.errors import VisaLaneError
        e = VisaLaneError("Dev message")
        assert "unexpected" in e.user_message.lower()


class TestSpecificErrors:
    def test_authentication_error(self):
        from job_radar.errors import AuthenticationError
        e = AuthenticationError("JWT expired")
        assert e.code == "unauthorized"
        assert e.http_status == 401
        assert "sign in" in e.user_message.lower()

    def test_authorization_error(self):
        from job_radar.errors import AuthorizationError
        e = AuthorizationError("No access")
        assert e.code == "forbidden"
        assert e.http_status == 403

    def test_validation_error_with_field(self):
        from job_radar.errors import ValidationError
        e = ValidationError("Invalid email", field="email")
        assert e.code == "validation_error"
        assert e.http_status == 400
        assert e.metadata.get("field") == "email"

    def test_file_size_error(self):
        from job_radar.errors import FileSizeError
        e = FileSizeError("File is 15 MB, max 10 MB")
        assert e.code == "file_too_large"
        assert "10 mb" in e.user_message.lower()

    def test_file_type_error(self):
        from job_radar.errors import FileTypeError
        e = FileTypeError("Unsupported extension .xlsx")
        assert e.code == "unsupported_file_type"

    def test_usage_limit_error(self):
        from job_radar.errors import UsageLimitError
        e = UsageLimitError("Daily limit reached", field="resume_generations", limit=5, plan="free")
        assert e.code == "usage_limit_reached"
        assert e.http_status == 402
        assert e.metadata["limit"] == 5

    def test_hallucination_error(self):
        from job_radar.errors import HallucinationError
        e = HallucinationError("Company mismatch", violations=["company_name"])
        assert e.code == "hallucination_detected"
        assert e.metadata["violations"] == ["company_name"]

    def test_resume_parse_error(self):
        from job_radar.errors import ResumeParseError
        e = ResumeParseError("pdfminer failed")
        assert e.code == "resume_parse_failed"
        assert e.http_status == 422

    def test_scanned_pdf_error(self):
        from job_radar.errors import ScannedPdfError
        e = ScannedPdfError("No text layer")
        assert e.code == "scanned_pdf_detected"
        assert "docx" in e.user_message.lower() or "word" in e.user_message.lower()

    def test_encrypted_file_error(self):
        from job_radar.errors import EncryptedFileError
        e = EncryptedFileError("Password protected")
        assert e.code == "encrypted_file"

    def test_external_service_error(self):
        from job_radar.errors import ExternalServiceError
        e = ExternalServiceError("Apollo API 500", service="apollo")
        assert e.code == "external_service_error"
        assert e.metadata["service"] == "apollo"

    def test_not_found_error(self):
        from job_radar.errors import NotFoundError
        e = NotFoundError("Resume 123 not found")
        assert e.code == "not_found"
        assert e.http_status == 404


class TestFromException:
    def test_wraps_non_visalane_exceptions(self):
        from job_radar.errors import VisaLaneError, from_exception
        exc = ValueError("bad value")
        wrapped = from_exception(exc)
        assert isinstance(wrapped, VisaLaneError)
        assert "bad value" in wrapped.message

    def test_passthrough_for_visalane(self):
        from job_radar.errors import AuthenticationError, from_exception
        original = AuthenticationError("JWT expired")
        result = from_exception(original)
        assert result is original
        assert result.code == "unauthorized"
