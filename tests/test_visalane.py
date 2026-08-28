"""Critical-path tests for the VisaLane backend services.

Covers master plan section 10 critical paths:
  4. Alert matching over complex filters with exact-subset assertions
  5. Dedup/fingerprint: two sources -> one row; tracking params stripped
  6. (promo/subscription math lives in Edge Function tests)
  7. Contact enrichment safety: pattern guesses labeled, no verified fakes
Plus: email fallback chain failover and classifier visa-field backfill.
"""

from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import MagicMock, patch

from job_radar.filters.dedupe import extract_canonical_job_url
from job_radar.visalane.alert_matching import job_matches_alert, match_jobs_to_alerts
from job_radar.visalane.enrichment_stage import (
    PATTERN_GUESS_CONFIDENCE,
    extract_posting_emails,
    guess_pattern_emails,
)
from job_radar.visalane.social_queue import build_caption, enqueue_jobs
from job_radar.visalane.writer import canonical_url_hash, job_to_row, sync_jobs

# ── Fakes ─────────────────────────────────────────────────────────────────────


class FakeQuery:
    """Minimal supabase-py query builder recorder."""

    def __init__(self, table: FakeTable, op: str, payload: Any = None):
        self._table = table
        self._op = op
        self._payload = payload
        self._filters: list[Any] = []
        self._on_conflict = None
        self._ignore_duplicates = False

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def ilike(self, col, val):
        self._filters.append(("ilike", col, val))
        return self

    def neq(self, col, val):
        self._filters.append(("neq", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, vals))
        return self

    def or_(self, expr):
        self._filters.append(("or", expr))
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def upsert(self, payload, on_conflict=None, ignore_duplicates=False):
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        self._ignore_duplicates = ignore_duplicates
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def execute(self):
        return self._table.record(self)


class FakeResult:
    def __init__(self, data):
        self.data = data
        self.count = len(data)


class FakeTable:
    def __init__(self, store: dict[str, list[dict]], name: str):
        self._store = store
        self.name = name

    def select(self, *a, **k):
        return FakeQuery(self, "select")

    def insert(self, payload):
        return FakeQuery(self, "insert", payload)

    def upsert(self, payload, **kw):
        q = FakeQuery(self, "upsert", payload)
        q._on_conflict = kw.get("on_conflict")
        q._ignore_duplicates = kw.get("ignore_duplicates", False)
        return q

    def update(self, payload):
        return FakeQuery(self, "update", payload)

    def record(self, query: FakeQuery):
        rows = query._payload if isinstance(query._payload, list) else ([query._payload] if query._payload else [])

        if self.name == "companies" and query._op == "select":
            wanted = None
            for kind, col, val in query._filters:
                if col == "name":
                    wanted = str(val).lower()
            found = [
                {"id": c["id"]}
                for c in self._store.setdefault("companies", [])
                if wanted and c["name"].lower() == wanted
            ]
            return FakeResult(found)

        if self.name == "jobs" and query._op == "upsert":
            jobs = self._store.setdefault("jobs", [])
            existing_hashes = {j["canonical_url_hash"] for j in jobs}
            inserted = []
            for row in rows:
                if row["canonical_url_hash"] in existing_hashes and query._ignore_duplicates:
                    continue
                row = dict(row)
                row.setdefault("id", f"job-{len(jobs) + 1}")
                jobs.append(row)
                existing_hashes.add(row["canonical_url_hash"])
                inserted.append(row)
            return FakeResult(inserted)

        if self.name == "companies" and query._op == "insert":
            companies = self._store.setdefault("companies", [])
            out = []
            for row in rows:
                row = dict(row)
                row["id"] = f"comp-{len(companies) + 1}"
                companies.append(row)
                out.append(row)
            return FakeResult(out)

        if query._op in ("insert", "upsert"):
            self._store.setdefault(self.name, []).extend(dict(r) for r in rows)
            return FakeResult([dict(r) for r in rows])

        # generic select -> return matching alert_sent_jobs or empty
        if self.name == "alert_sent_jobs":
            alert_ids = [v for kind, col, v in query._filters if col == "alert_id"]
            job_id_filter = [set(v) for kind, col, v in query._filters if col == "job_id" and kind == "in"]
            wanted = job_id_filter[0] if job_id_filter else None
            data = [
                r
                for r in self._store.setdefault("alert_sent_jobs", [])
                if (not alert_ids or r["alert_id"] == alert_ids[0]) and (wanted is None or r["job_id"] in wanted)
            ]
            return FakeResult(data)

        if self.name == "alerts":
            return FakeResult([a for a in self._store.setdefault("alerts", []) if a.get("is_active", True)])
        if self.name == "profiles":
            return FakeResult(self._store.setdefault("profiles", []))

        return FakeResult([])


class FakeClient:
    def __init__(self):
        self.store: dict[str, list[dict]] = {}

    def table(self, name: str):
        return FakeTable(self.store, name)


# ── 4. Alert matching: complex filters, exact subset ─────────────────────────


def _mk_job(i: int, **overrides) -> dict[str, Any]:
    job = {
        "job_db_id": f"job-{i}",
        "title": f"Backend Engineer #{i}",
        "company": overrides.pop("company", f"Company{i}"),
        "description": "Build distributed systems in Python.",
        "country_code": "DE",
        "country": "Germany",
        "work_mode": "remote",
        "visa_sponsorship_confidence": 80,
        "visa_sponsorship_verified": True,
        "resume_match_score": 85,
    }
    job.update(overrides)
    return job


def test_alert_matching_complex_filters_exact_subset():
    """Remote OR Hybrid + Exclude Company X + min match 80 over 50 mock jobs."""
    jobs = []
    for i in range(50):
        overrides: dict[str, Any] = {}
        if i % 3 == 0:
            overrides["work_mode"] = "onsite"  # excluded by work_modes
        if i % 5 == 0:
            overrides["resume_match_score"] = 50  # excluded by min_match
        if i % 7 == 0:
            overrides["company"] = "BlockedCorp"  # excluded by exclude_companies
        if i % 4 == 0:
            overrides["work_mode"] = "hybrid"  # allowed
        jobs.append(_mk_job(i, **overrides))

    filters = {
        "work_modes": ["remote", "hybrid"],
        "exclude_companies": ["BlockedCorp"],
        "min_match": 80,
    }

    expected = {
        j["job_db_id"]
        for j in jobs
        if j["work_mode"] in ("remote", "hybrid")
        and j["company"] != "BlockedCorp"
        and (j.get("resume_match_score") or 0) >= 80
    }

    matched = {j["job_db_id"] for j in jobs if job_matches_alert(j, filters)}
    assert matched == expected
    assert len(expected) > 0, "test fixture must produce a non-empty subset"
    assert len(expected) < 50, "filters must actually exclude jobs"


def test_alert_matching_country_and_confidence():
    alert = {"id": "a1", "filters": {"countries": ["DE"], "min_confidence": 70, "verified_only": True}}
    good = _mk_job(1, country_code="DE", visa_sponsorship_confidence=75, visa_sponsorship_verified=True)
    wrong_country = _mk_job(2, country_code="FR")
    low_conf = _mk_job(3, visa_sponsorship_confidence=20)
    unverified = _mk_job(4, visa_sponsorship_verified=False)

    result = match_jobs_to_alerts([good, wrong_country, low_conf, unverified], [alert])
    assert [j["job_db_id"] for j in result["a1"]] == ["job-1"]


def test_alert_matching_keyword_in_description():
    filters = {"keywords": ["kubernetes"]}
    hit = _mk_job(1, title="Platform Engineer", description="We run Kubernetes at scale.")
    miss = _mk_job(2, title="Platform Engineer", description="Docker only.")
    assert job_matches_alert(hit, filters)
    assert not job_matches_alert(miss, filters)


# ── 5. Dedup / canonical URL / fingerprint ────────────────────────────────────


def test_canonical_url_hash_strips_tracking_params():
    a = "https://boards.greenhouse.io/stripe/jobs/12345?utm_source=newsletter&utm_medium=email&gh_src=abc"
    b = "https://boards.greenhouse.io/stripe/jobs/12345"
    assert extract_canonical_job_url(a) == extract_canonical_job_url(b)
    assert canonical_url_hash(a) == canonical_url_hash(b)
    assert canonical_url_hash(a) == hashlib.sha256(extract_canonical_job_url(b).encode()).hexdigest()


def test_same_job_two_sources_single_row():
    """The same job fetched via two sources must produce exactly one jobs row."""
    client = FakeClient()
    job_a = _mk_job(1, title="SWE", company="Stripe", url="https://boards.greenhouse.io/stripe/jobs/9?utm_source=x")
    job_b = _mk_job(1, title="SWE", company="Stripe", url="https://boards.greenhouse.io/stripe/jobs/9")

    inserted, skipped = sync_jobs(client, [job_a, job_b], source_name="t")
    assert (inserted, skipped) == (1, 1)
    assert len(client.store["jobs"]) == 1
    assert client.store["jobs"][0]["title"] == "SWE"


def test_job_to_row_requires_url_and_title():
    assert job_to_row({"title": "SWE", "url": ""}, None) is None
    assert job_to_row({"title": "", "url": "https://x.test/j/1"}, None) is None
    row = job_to_row(
        _mk_job(1, url="https://x.test/j/1", apply_url="https://x.test/j/1/apply", salary_min="52000.0"),
        company_id="c1",
    )
    assert row is not None
    assert row["salary_min"] == 52000
    assert row["canonical_url_hash"] == canonical_url_hash("https://x.test/j/1")
    assert row["apply_url"] == "https://x.test/j/1/apply"


# ── 7. Contact enrichment safety ─────────────────────────────────────────────


def test_extract_posting_emails_generic_only():
    text = "Send your CV to talent@acme.io or careers@acme.io. Personal: jane@gmail.com is not harvested."
    emails = extract_posting_emails(text)
    assert set(emails) == {"talent@acme.io", "careers@acme.io"}


def test_pattern_emails_low_confidence_only():
    guesses = guess_pattern_emails("Jane Doe", "acme.io")
    assert guesses == ["jane@acme.io", "jane.doe@acme.io"]
    assert PATTERN_GUESS_CONFIDENCE <= 40
    assert guess_pattern_emails("Jane", "localhost") == []  # not a real domain


def test_enrichment_rows_never_claim_verified_personal_emails():
    """No enrichment path may mark a guessed/unknown email as verified."""
    from job_radar.visalane import enrichment_stage

    fake_service = MagicMock()
    fake_service.find_hiring_contacts.return_value = {
        "success": True,
        "company_name": "Acme",
        "company_domain": "acme.io",
        "linkedin_search_url": "https://www.linkedin.com/search/results/people/?keywords=recruiter%20acme",
        "contacts": [{"name": "Jane Doe", "title": "Technical Recruiter", "score": 80, "id": "p1"}],
        "count": 1,
    }

    client = FakeClient()
    job = _mk_job(
        1,
        company="Acme",
        company_domain="acme.io",
        url="https://acme.io/jobs/1",
        apply_url="https://acme.io/jobs/1",
        description="Apply via talent@acme.io",
    )
    job["job_db_id"] = "job-1"
    job["company_db_id"] = "comp-1"

    written = enrichment_stage.enrich_job_contacts(client, job, service=fake_service)
    assert written >= 2

    rows = client.store["job_people"]
    statuses = {r.get("email_status") for r in rows if r.get("email")}
    assert "verified" not in statuses
    assert "pattern_guess" in statuses
    assert "generic" in statuses
    for row in rows:
        if row.get("email_status") == "pattern_guess":
            assert (row.get("email_confidence") or 0) <= 40

    # The sanctioned path is the LinkedIn SEARCH deep-link, never a profile scrape.
    linkedin_rows = [r for r in rows if r.get("linkedin_search_url")]
    assert linkedin_rows, "LinkedIn search deep-link must be attached"
    for row in linkedin_rows:
        assert "/search/results/" in row["linkedin_search_url"]
        assert "/in/" not in row["linkedin_search_url"]


# ── Social queue platform policy ─────────────────────────────────────────────


def test_social_queue_manual_review_for_linkedin_and_x():
    client = FakeClient()
    jobs = [_mk_job(i, url=f"https://x.test/j/{i}", apply_url=f"https://x.test/j/{i}") for i in range(1, 4)]
    for j in jobs:
        j["job_db_id"] = j["job_db_id"]

    created = enqueue_jobs(client, jobs, platforms=["telegram", "linkedin", "x"])
    rows = client.store["social_post_queue"]
    assert created == len(rows) == 3
    by_platform = {r["platform"]: r for r in rows}
    assert by_platform["telegram"]["status"] == "pending"
    assert by_platform["linkedin"]["status"] == "manual_review"
    assert by_platform["x"]["status"] == "manual_review"
    assert "Apply:" in by_platform["telegram"]["caption"]


def test_caption_includes_apply_link_for_text_fallback():
    job = _mk_job(1, url="https://x.test/j/1", apply_url="https://x.test/j/1")
    caption = build_caption([job])
    assert "https://x.test/j/1" in caption
    assert "Company1" in caption


# ── 6.2 Email fallback chain ─────────────────────────────────────────────────


def test_email_fallback_chain_advances_on_failure(monkeypatch):
    from job_radar.notifications import email as email_mod

    monkeypatch.setenv("RESEND_API_KEY", "rk")
    monkeypatch.setenv("BREVO_API_KEY", "bk")
    monkeypatch.setenv("EMAIL_TO", "ops@example.com")

    calls = []

    def boom(*a, **k):
        calls.append("resend")
        raise RuntimeError("429 rate limited")

    def ok(*a, **k):
        calls.append("brevo")

    monkeypatch.setattr(email_mod, "_send_via_resend", boom)
    monkeypatch.setattr(email_mod, "_send_via_brevo", ok)
    # rebuild chain with patched senders
    chain = [
        ("resend", boom, lambda: True),
        ("brevo", ok, lambda: True),
        ("sendgrid", email_mod._send_via_sendgrid, lambda: False),
        ("gmail", email_mod._send_via_gmail_smtp, lambda: False),
    ]
    monkeypatch.setattr(email_mod, "EMAIL_FALLBACK_CHAIN", chain)

    with patch("job_radar.analytics.emit_event") as emit:
        provider = email_mod.send_email_with_fallback("subj", "<html></html>")

    assert provider == "brevo"
    assert calls == ["resend", "brevo"]
    emit.assert_called_once()
    assert emit.call_args.args[0] == "pipeline_fallback_triggered"


def test_email_fallback_chain_prefers_configured_provider(monkeypatch):
    from job_radar.notifications import email as email_mod

    calls = []

    def brevo_first(*a, **k):
        calls.append("brevo")

    chain = [
        ("resend", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")), lambda: True),
        ("brevo", brevo_first, lambda: True),
    ]
    monkeypatch.setattr(email_mod, "EMAIL_FALLBACK_CHAIN", chain)
    provider = email_mod.send_email_with_fallback("s", "<p/>", preferred="brevo")
    assert provider == "brevo"
    assert calls == ["brevo"]  # preferred tried first, no resend attempt


# ── Classifier visa extension backfill ───────────────────────────────────────


def test_classifier_fallback_populates_visalane_fields():
    """Deterministic fallback output carries confidence/verified/visa_types keys."""
    from job_radar.classifiers.relevance import classify_single_job
    from job_radar.config import get_config

    cfg = get_config()
    cfg.classifier.enabled = False  # force deterministic path

    job = {
        "company": "Acme Robotics",
        "title": "Machine Learning Engineer",
        "location": "Remote",
        "url": "https://acme.test/jobs/ml-1",
        "description": "Train and deploy LLMs. We sponsor work visas (Skilled Worker).",
    }
    clf = classify_single_job(job, config=cfg)
    assert "visa_sponsorship_confidence" in clf
    assert "visa_sponsorship_verified" in clf
    assert isinstance(clf.get("visa_types"), list)


def test_classify_and_filter_enriches_jobs_with_confidence():
    from job_radar.classifiers.relevance import classify_and_filter_jobs
    from job_radar.config import get_config

    cfg = get_config()
    cfg.classifier.enabled = False
    cfg.classifier.min_relevance_score = 0

    job = {
        "company": "Acme Robotics",
        "title": "Machine Learning Engineer",
        "location": "Remote",
        "url": "https://acme.test/jobs/ml-2",
        "description": "We build LLM products. Sponsorship available.",
        "remote": True,
    }
    qualified, _stats = classify_and_filter_jobs([job], config=cfg)
    assert len(qualified) == 1
    enriched = qualified[0]
    assert 0 <= enriched["visa_sponsorship_confidence"] <= 100
    assert isinstance(enriched["visa_sponsorship_verified"], bool)
    assert isinstance(enriched["visa_types"], list)
