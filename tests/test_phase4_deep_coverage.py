"""Comprehensive deep test coverage for Phase 4 Python modules.
Targets 100% branch and statement coverage for:
  - job_radar.jobs.matcher
  - job_radar.jobs.scorer
  - job_radar.jobs.skill_extractor
  - job_radar.resume.extractors.pdf_extractor
  - job_radar.resume.extractors.docx_extractor
  - job_radar.resume.extractors.text_extractor
  - job_radar.resume.normalizers
  - job_radar.resume.parser
  - job_radar.resume.validators
  - job_radar.ai.ats_scorer
  - job_radar.errors.base
"""
from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock, patch
import pytest

from job_radar.jobs.matcher import (
    score_jobs_for_profile,
    write_match_scores,
    _match_label,
)
from job_radar.jobs.scorer import (
    compute_match_score,
    score_title_relevance,
    score_skills_overlap,
    score_experience_level,
    score_visa_sponsorship,
    score_location_preference,
)
from job_radar.jobs.skill_extractor import (
    extract_skills_rule_based,
    extract_skills_from_job,
    _ai_extract_skills,
    _derive_canonical_from_pattern,
    _derive_canonical_from_pattern_raw,
    _deduplicate,
)
from job_radar.resume.extractors.pdf_extractor import (
    PdfExtractor,
    PdfExtractionError,
    extract_text_from_pdf,
    _extract_with_pdfminer,
    _extract_with_pypdf,
)
from job_radar.resume.extractors.docx_extractor import (
    DocxExtractor,
    DocxExtractionError,
    extract_text_from_docx,
    _extract_legacy_doc,
    _extract_doc_text_heuristic,
    _is_encrypted_docx,
)
from job_radar.resume.extractors.text_extractor import (
    TextExtractor,
    TextExtractionError,
    extract_text_from_txt,
    extract_text_from_rtf,
    extract_text_from_odt,
    _strip_rtf_naive,
)
from job_radar.resume.normalizers import (
    normalize_date,
    normalize_email,
    normalize_phone,
    normalize_url,
    normalize_skills,
    normalize_name,
    normalize_parsed_data,
)
from job_radar.resume.validators import (
    validate_file_size,
    validate_file_type,
    validate_not_empty,
    validate_content_plausibility,
    validate_upload,
)
from job_radar.resume.parser import (
    parse_resume,
    create_fresher_profile,
    ResumeParseResult,
    FresherProfile,
    _extract_text,
    _ai_parse_resume,
    _build_parse_prompt,
    _detect_fresher,
    _detect_sections,
    _detect_file_type,
    _elapsed_ms,
    _user_error,
)
from job_radar.ai.ats_scorer import (
    compute_ats_score,
    score_keyword_overlap,
    score_skills_overlap as ats_score_skills_overlap,
    score_title_match,
    score_format_quality,
    _extract_keywords,
)
from job_radar.errors.base import (
    VisaLaneError,
    AuthenticationError,
    AuthorizationError,
    ValidationError,
    FileSizeError,
    FileTypeError,
    ContentError,
    NotFoundError,
    JobNotFoundError,
    ResumeNotFoundError,
    UsageLimitError,
    GenerationError,
    HallucinationError,
    ResumeParseError,
    ScannedPdfError,
    EncryptedFileError,
    ExternalServiceError,
    EmailDeliveryError,
    DatabaseError,
    from_exception,
)


# ── 1. Matcher tests ─────────────────────────────────────────────────────────

class TestMatcherDeep:
    def test_write_match_scores_success(self):
        client = MagicMock()
        client.table.return_value.upsert.return_value.execute.return_value = None

        scored_jobs = [
            {"id": "job-1", "resume_match_score": 85, "match_label": "great_match"},
            {"job_db_id": "job-2", "resume_match_score": 50, "match_label": "fair_match"},
            {"other_key": "ignored"},
        ]
        count = write_match_scores(client, scored_jobs, "user-123")
        assert count == 2
        client.table.assert_called_with("user_job_scores")
        # Column payload uses the schema column name `score` (not match_score)
        upsert_arg = client.table.return_value.upsert.call_args[0][0]
        assert all("score" in row for row in upsert_arg)
        assert all("calculated_at" in row for row in upsert_arg)

    def test_write_match_scores_no_client_or_empty(self):
        assert write_match_scores(None, [{"id": "1"}], "user-1") == 0
        assert write_match_scores(MagicMock(), [], "user-1") == 0
        assert write_match_scores(MagicMock(), [{"no_id": True}], "user-1") == 0

    def test_write_match_scores_exception_handled(self):
        client = MagicMock()
        client.table.side_effect = Exception("DB error")
        count = write_match_scores(client, [{"id": "1"}], "user-1")
        assert count == 0

    def test_read_cached_scores_fresh_rows(self):
        from datetime import datetime, timezone
        from job_radar.jobs.matcher import read_cached_scores

        client = MagicMock()
        client.table.return_value.select.return_value.eq.return_value.in_.return_value \
            .gte.return_value.execute.return_value = MagicMock(
                data=[{"job_id": "job-1", "score": 85}, {"job_id": "job-2", "score": 40}]
            )
        result = read_cached_scores(client, "user-1", ["job-1", "job-2"])
        assert result == {"job-1": 85, "job-2": 40}
        # The query filters by freshness (calculated_at >= TTL cutoff)
        chain = client.table.return_value.select.return_value.eq.return_value.in_.return_value
        assert chain.gte.call_args.args[0] == "calculated_at"

    def test_read_cached_scores_empty_and_errors(self):
        from job_radar.jobs.matcher import read_cached_scores, purge_stale_scores

        assert read_cached_scores(None, "u", ["j"]) == {}
        assert read_cached_scores(MagicMock(), "u", []) == {}

        client = MagicMock()
        client.table.side_effect = Exception("DB down")
        assert read_cached_scores(client, "u", ["j"]) == {}

        purge = MagicMock()
        purge.table.return_value.delete.return_value.lt.return_value.execute \
            .return_value = MagicMock(data=[{"job_id": "x"}])
        assert purge_stale_scores(purge) == 1
        assert purge_stale_scores(None) == 0

    def test_match_labels_all_brackets(self):
        assert _match_label(95) == "great_match"
        assert _match_label(80) == "great_match"
        assert _match_label(70) == "good_match"
        assert _match_label(60) == "good_match"
        assert _match_label(50) == "fair_match"
        assert _match_label(40) == "fair_match"
        assert _match_label(30) == "low_match"
        assert _match_label(0) == "low_match"

    def test_match_cache_ttl_is_24h(self):
        from datetime import timedelta
        from job_radar.jobs.matcher import MATCH_CACHE_TTL
        assert MATCH_CACHE_TTL == timedelta(hours=24)


# ── 2. Scorer tests ──────────────────────────────────────────────────────────

class TestScorerDeep:
    def test_score_title_relevance_variations(self):
        assert score_title_relevance(["Frontend Engineer"], "Frontend", 20) > 10
        assert score_title_relevance(["Senior Dev"], "Dev Lead", 20) > 0
        assert score_title_relevance([], "Engineer", 20) == 5
        assert score_title_relevance(["Engineer"], "", 20) == 5

    def test_spec_weights_title_40_skills_50_exp_10(self):
        # Spec §3.2: title 40%, skills 50%, experience 10% + bonuses
        assert score_title_relevance(["A"], "A") == 40
        assert score_skills_overlap(["a"], ["a"]) == 50
        assert score_experience_level(3, 2, 5) == 10
        from job_radar.jobs.scorer import score_visa_sponsorship
        assert score_visa_sponsorship(True, None) == 5  # +5 bonus

    def test_rare_skills_weighted_higher_than_common(self):
        # Matching a rare skill should contribute more than matching a common one
        common = score_skills_overlap(
            ["javascript", "kafka"], ["javascript", "kafka", "terraform", "graphql", "spark"], 50
        )
        rare = score_skills_overlap(
            ["spark", "kafka"], ["javascript", "kafka", "terraform", "graphql", "spark"], 50
        )
        # Both cover 2/5 skills, but rare matches weigh more per-skill
        assert rare >= common

    def test_score_experience_level_variations(self):
        assert score_experience_level(4, 2, 5, 10) == 10
        assert score_experience_level(1, 2, 5, 10) == 8
        assert score_experience_level(0, 2, 5, 10) == 5
        assert score_experience_level(0, 4, 8, 10) == 0
        assert score_experience_level(7, 2, 5, 10) == 9
        assert score_experience_level(15, 2, 5, 10) == 0
        assert score_experience_level(None, 2, 5, 10) == 5

    def test_score_location_preference_variations(self):
        assert score_location_preference(["US"], ["remote"], "US", "remote", 10) == 10
        assert score_location_preference(["US"], ["remote"], "US", "hybrid", 10) == 7
        assert score_location_preference(["US"], ["onsite"], "US", "hybrid", 10) == 5
        assert score_location_preference(None, None, None, None, 10) == 10

    def test_compute_match_score_full_profile(self):
        profile = {
            "skills": ["python", "docker"],
            "job_titles": ["Python Engineer"],
            "experience_years": 3,
            "preferred_countries": ["DE"],
            "preferred_work_modes": ["remote"],
        }
        job = {
            "title": "Python Engineer",
            "skills": ["python", "docker"],
            "min_experience_years": 2,
            "max_experience_years": 5,
            "country": "DE",
            "work_mode": "remote",
            "visa_sponsorship_verified": True,
        }
        score = compute_match_score(profile, job)
        assert score >= 90


# ── 3. Skill Extractor tests ─────────────────────────────────────────────────

class TestSkillExtractorDeep:
    def test_ai_extract_skills_dict_format(self):
        llm = MagicMock()
        llm.complete_json.return_value = {"skills": ["Kubernetes", "GraphQL"]}
        res = _ai_extract_skills("job text", ["Python"], llm)
        assert res == ["Kubernetes", "GraphQL"]

    def test_ai_extract_skills_list_format(self):
        llm = MagicMock()
        llm.complete_json.return_value = ["Rust", "Solidity"]
        res = _ai_extract_skills("job text", [], llm)
        assert res == ["Rust", "Solidity"]

    def test_ai_extract_skills_invalid(self):
        llm = MagicMock()
        llm.complete_json.return_value = "invalid"
        res = _ai_extract_skills("job text", [], llm)
        assert res == []

    def test_derive_canonical(self):
        assert _derive_canonical_from_pattern(r"\bPython\b") == "Python"
        assert _derive_canonical_from_pattern_raw(r"\bDocker\b") == "Docker"

    def test_deduplicate(self):
        assert _deduplicate(["Python", "python", "  ", "Docker"]) == ["Python", "Docker"]

    def test_nodejs_normalized(self):
        # Spec §3.2: NodeJS → node.js
        assert extract_skills_rule_based("NodeJS and Node.js and Node") == ["Node.js"]

    def test_js_javascript_synonyms(self):
        # Spec §3.4: JS vs JavaScript treated as same skill
        assert _deduplicate(["JS", "JavaScript"]) == ["JavaScript"]

    def test_acronyms_expanded(self):
        # Spec §3.4: ML, AI, NLP expanded to full names
        skills = extract_skills_rule_based("Experience with ML, AI, and NLP required")
        assert "Machine Learning" in skills
        assert "Artificial Intelligence" in skills
        assert "Natural Language Processing" in skills

    def test_version_specific_skill_normalized(self):
        # Spec §3.4: Python 3.9 → Python
        assert extract_skills_rule_based("Requires Python 3.9 or Python3") == ["Python"]

    def test_compound_skills_kept(self):
        # Spec §3.4: compound skills kept as compound
        skills = extract_skills_rule_based("React Native and Ruby on Rails shop")
        assert "React Native" in skills
        assert "Ruby on Rails" in skills
        assert "React" not in skills  # absorbed into compound
        assert "Rails" not in skills   # absorbed into compound
        assert "Ruby" not in skills    # absorbed into compound

    def test_extraction_confidence(self):
        from job_radar.jobs.skill_extractor import extraction_confidence
        # Long description + skills found → high confidence
        assert extraction_confidence("Dev", "x" * 900, ["Python"]) >= 0.8
        # Short description → lower confidence
        assert extraction_confidence("Dev", "short", ["Python"]) < 0.7
        # No description (title-only) → lowest band
        assert extraction_confidence("Dev", "", []) <= 0.3

    def test_soft_and_domain_skills(self):
        skills = extract_skills_rule_based(
            "Leadership and communication in a fintech SaaS environment with problem solving"
        )
        assert "Leadership" in skills
        assert "Communication" in skills
        assert "Fintech" in skills or "SaaS" in skills


# ── 4. PDF Extractor tests ───────────────────────────────────────────────────

class TestPdfExtractorDeep:
    def test_pdf_extractor_class(self):
        extractor = PdfExtractor()
        data = b"%PDF-1.5\n" + b"x" * 200
        with pytest.raises(Exception):
            extractor.extract(data)

    def test_pdfminer_password_error(self, monkeypatch):
        monkeypatch.setattr("job_radar.resume.extractors.pdf_extractor._extract_with_pdfminer", MagicMock(side_effect=PdfExtractionError("PDF is password-protected")))
        with pytest.raises(PdfExtractionError, match="password"):
            extract_text_from_pdf(b"%PDF-1.4\n" + b"x" * 200)

    def test_pypdf_fallback_execution(self, monkeypatch):
        # When pypdf is called
        monkeypatch.setattr("job_radar.resume.extractors.pdf_extractor._extract_with_pdfminer", MagicMock(return_value=("", 0)))
        monkeypatch.setattr("job_radar.resume.extractors.pdf_extractor._extract_with_pypdf", MagicMock(return_value=("Extracted text from resume with sufficient length over fifty chars.", 1)))
        res = extract_text_from_pdf(b"%PDF-1.4\n" + b"x" * 200)
        assert "Extracted text" in res.text
        assert res.is_scanned is False


# ── 5. DOCX Extractor tests ──────────────────────────────────────────────────

class TestDocxExtractorDeep:
    def test_docx_extractor_class(self):
        extractor = DocxExtractor()
        with pytest.raises(DocxExtractionError):
            extractor.extract(b"not-docx", "test.docx")

    def test_is_encrypted_docx(self):
        assert _is_encrypted_docx(b"PK\x03\x04EncryptedPackage") is True
        assert _is_encrypted_docx(b"PK\x03\x04normal") is False

    def test_extract_doc_legacy(self):
        doc_bytes = b"\xd0\xcf\x11\xe0" + b"Software Engineer Resume text " * 10
        res = _extract_legacy_doc(doc_bytes, [])
        assert len(res.text) > 0
        assert res.is_scanned is False

    def test_extract_doc_legacy_short(self):
        doc_bytes = b"\xd0\xcf\x11\xe0" + b"short"
        res = _extract_legacy_doc(doc_bytes, [])
        assert res.is_scanned is False


# ── 6. Text Extractor tests ──────────────────────────────────────────────────

class TestTextExtractorDeep:
    def test_text_extractor_class(self):
        extractor = TextExtractor()
        res = extractor.extract(b"Plain text resume with skills and experience", "resume.txt")
        assert "Plain text" in res.text

    def test_strip_rtf_naive(self):
        rtf = r"{\rtf1\ansi Hello \b World\b0\par Next line}"
        plain = _strip_rtf_naive(rtf)
        assert "Hello" in plain

    def test_extract_rtf_size_limit(self):
        big = b"{\\rtf1 " + b"x" * (11 * 1024 * 1024)
        with pytest.raises(TextExtractionError):
            extract_text_from_rtf(big)

    def test_extract_txt_size_limit(self):
        big = b"x" * (11 * 1024 * 1024)
        with pytest.raises(TextExtractionError):
            extract_text_from_txt(big)


# ── 7. Normalizers tests ─────────────────────────────────────────────────────

class TestNormalizersDeep:
    def test_normalize_url(self):
        assert normalize_url("github.com/user") == "https://github.com/user"
        assert normalize_url("http://site.com") == "http://site.com"
        assert normalize_url("https://site.com") == "https://site.com"
        assert normalize_url(None) is None
        assert normalize_url("") is None

    def test_normalize_name(self):
        assert normalize_name("john doe") == "John Doe"
        assert normalize_name("  JANE   DOE  ") == "Jane Doe"
        assert normalize_name(None) is None
        assert normalize_name("") is None

    def test_normalize_skills(self):
        assert normalize_skills(["python", "Python", "a", "valid skill"]) == ["python", "valid skill"]

    def test_normalize_parsed_data_projects_languages(self):
        data = {
            "linkedin_url": "linkedin.com/in/test",
            "github_url": "github.com/test",
            "website_url": "test.dev",
            "projects": [
                {"name": "App", "technologies": ["python", "PYTHON"]},
            ],
            "certifications": [
                {"name": "AWS Pro", "year": "2023"},
            ],
            "languages": [
                {"language": "english", "proficiency": "Native"},
            ],
        }
        norm = normalize_parsed_data(data)
        assert norm["linkedin_url"] == "https://linkedin.com/in/test"
        assert norm["projects"][0]["technologies"] == ["python"]


# ── 8. Parser orchestrator tests ─────────────────────────────────────────────

class TestParserDeep:
    def test_detect_file_type(self):
        assert _detect_file_type("resume.pdf") == "pdf"
        assert _detect_file_type("resume.docx") == "docx"
        assert _detect_file_type("noextension") == "unknown"

    def test_elapsed_ms(self):
        import time
        t0 = time.monotonic() - 0.05
        assert _elapsed_ms(t0) >= 40

    def test_user_error(self):
        err = PdfExtractionError("Internal error", "Friendly user message")
        assert _user_error(err) == "Friendly user message"
        assert _user_error(ValueError("Standard error")) == "Standard error"

    def test_detect_sections(self):
        sections = _detect_sections({
            "summary": "Experienced engineer",
            "skills": ["Python"],
            "experience": [{"company": "X"}],
            "empty_section": [],
        })
        assert "summary" in sections
        assert "skills" in sections
        assert "experience" in sections
        assert "empty_section" not in sections

    def test_extract_text_dispatcher(self):
        res_txt = _extract_text(b"Software Engineer Resume text with experience", "resume.txt")
        assert "Software" in res_txt.text


# ── 9. ATS Scorer tests ──────────────────────────────────────────────────────

class TestAtsScorerDeep:
    def test_extract_keywords(self):
        kws = _extract_keywords("We need a Senior Python & TypeScript Developer!")
        assert "python" in kws
        assert "typescript" in kws
        assert "developer" in kws
        assert _extract_keywords("") == set()

    def test_score_title_match_substring(self):
        assert score_title_match(["Software Engineer"], "Senior Software Engineer", 20) >= 15
        assert score_title_match(["Software Engineer"], "", 20) == 10


# ── 10. Errors hierarchy tests ───────────────────────────────────────────────

class TestErrorsDeep:
    def test_all_error_types(self):
        classes = [
            AuthenticationError,
            AuthorizationError,
            ValidationError,
            FileSizeError,
            FileTypeError,
            ContentError,
            NotFoundError,
            JobNotFoundError,
            ResumeNotFoundError,
            UsageLimitError,
            GenerationError,
            HallucinationError,
            ResumeParseError,
            ScannedPdfError,
            EncryptedFileError,
            ExternalServiceError,
            EmailDeliveryError,
            DatabaseError,
        ]
        for cls in classes:
            instance = cls("test message")
            assert isinstance(instance, VisaLaneError)
            d = instance.to_dict()
            assert "error" in d
            assert d["error"]["code"] == instance.code
            assert repr(instance).startswith(cls.__name__)

    def test_docx_mocked_document_extraction(self, monkeypatch):
        # Mock docx.Document
        mock_doc = MagicMock()
        mock_para = MagicMock()
        mock_para.text = "Senior Python Engineer Resume with extensive cloud experience"
        mock_doc.paragraphs = [mock_para]

        mock_table = MagicMock()
        mock_row = MagicMock()
        mock_cell = MagicMock()
        mock_cell.text = "Skill: Python"
        mock_row.cells = [mock_cell]
        mock_table.rows = [mock_row]
        mock_doc.tables = [mock_table]

        mock_section = MagicMock()
        mock_hf_para = MagicMock()
        mock_hf_para.text = "email: test@example.com"
        mock_section.header.paragraphs = [mock_hf_para]
        mock_section.footer.paragraphs = []
        mock_doc.sections = [mock_section]

        mock_docx_module = MagicMock()
        mock_docx_module.Document.return_value = mock_doc

        with patch.dict("sys.modules", {"docx": mock_docx_module, "docx.opc.exceptions": MagicMock()}):
            data = b"PK\x03\x04" + b"mock docx content " * 10
            res = extract_text_from_docx(data, "resume.docx")
            assert "Senior Python Engineer" in res.text
            assert "Skill: Python" in res.text
            assert "email: test@example.com" in res.text
            assert res.page_count == 1

    def test_pdfminer_and_pypdf_full_cycle(self, monkeypatch):
        # Mock pypdf.PdfReader
        mock_reader = MagicMock()
        mock_reader.is_encrypted = False
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Extracted resume content from pypdf page"
        mock_reader.pages = [mock_page]

        mock_pypdf_module = MagicMock()
        mock_pypdf_module.PdfReader.return_value = mock_reader
        mock_pypdf_module.errors.PdfReadError = Exception

        with patch.dict("sys.modules", {"pypdf": mock_pypdf_module, "pypdf.errors": mock_pypdf_module.errors}):
            warns = []
            text, pages = _extract_with_pypdf(b"%PDF-1.4 mock", warns)
            assert "Extracted resume" in text
            assert pages == 1

    def test_parser_confidence_and_fresher_scoring(self, monkeypatch):
        fake_router = MagicMock()
        fake_router.complete_json.return_value = {
            "full_name": "Senior Developer",
            "skills": ["Python", "Kubernetes"],
            "experience": [{"company": "Tech Corp", "title": "Lead", "start": "2020", "end": "Present"}],
            "education": [{"institution": "Stanford", "degree": "MS", "year": "2019"}],
        }
        data = (b"%PDF-1.4\n" + b"Software Engineer resume text with experience and education\n" * 30)
        # Mock extraction
        monkeypatch.setattr("job_radar.resume.parser._extract_text", MagicMock(return_value=MagicMock(text="Software Engineer resume text with experience and education", page_count=1, is_scanned=False, warnings=[])))
        res = parse_resume(data, "resume.pdf", llm_router=fake_router)
        assert res.status == "completed"
        assert res.confidence >= 0.8
        assert res.is_fresher is False
        assert "experience" in res.sections_detected

