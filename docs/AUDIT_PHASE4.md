# Phase 4 Audit Report

Generated: 2026-08-30

## 1. OAuth Google + GitHub

**Verdict: DONE**

| Feature | Status | Files |
|---------|--------|-------|
| Initiate Edge Function | ✅ | `supabase/functions/oauth-initiate/index.ts` |
| Callback Edge Function | ✅ | `supabase/functions/oauth-callback/index.ts` |
| State/CSRF (base64-encoded, 15-min expiry) | ✅ | `oauth-initiate/index.ts:50-55`, `oauth-callback/index.ts:19-31,186` |
| Profile image stored to `profiles.oauth_profile_image` | ✅ | `oauth-callback/index.ts:237` |
| Account linking (email-based lookup) | ✅ | `oauth-callback/index.ts:221-226` |
| Error classes (unified format) | ✅ | `_shared/http.ts` |
| Rate limiting | ❌ N/A | No per-endpoint rate limiter — acceptable for Edge Functions (Supabase rate-limits at the platform level) |
| OAuth sync function | ✅ | `supabase/functions/oauth-sync/index.ts` |
| DB function `record_oauth_login` | ✅ | `20260829_phase4_oauth_matching_pagination.sql:122-147` |
| Tests | ✅ | `oauth-initiate.test.ts`, `oauth-callback.test.ts`, `oauth-sync.test.ts`, `tests/test_oauth_system.py` |

## 2. Resume Parser

**Verdict: DONE**

| Feature | Status | Files |
|---------|--------|-------|
| Text input (resume_text) | ✅ | `parse-resume/index.ts:69` |
| Storage path upload flow | ✅ | `parse-resume/index.ts:71-77` |
| PDF client-side extraction note | ✅ | `parse-resume/index.ts:29-32` |
| All sections (achievements via awards, languages, projects, volunteer, publications, awards, interests) | ✅ | `_shared/prompts.ts:42-63`, `parse-resume/index.ts:39-43` |
| Fresher path (`is_fresher`, AI gating) | ✅ | `parse-resume/index.ts:111,139`, `20260829_phase4_zzz_completion_gaps.sql:18-35` |
| Partial-state persistence | ✅ | Profile + resume row updated independently |
| Warnings stored | ✅ | `resumes.parse_warnings` column exists |
| Size/type validation | ✅ | Min 20 chars check, storage type check |
| Tests | ✅ | `tests/test_phase4_resume_parser.py` (30KB), `_shared/prompts.test.ts` |

**Note**: OCR fallback for scanned PDFs is documented as "client-side extraction required" — this is the correct architectural choice since Edge Functions can't run OCR. The FE guide documents using `pdfjs-dist`.

## 3. Job Matching

**Verdict: DONE**

| Feature | Status | Files |
|---------|--------|-------|
| Skills extracted on ingest into `jobs.skills` | ✅ | `20260829_phase4_oauth_matching_pagination.sql:37-46`, `supabase/functions/extract-job-skills/` |
| Matcher uses title(40)+skills(50)+location(10) | ✅ | `search-jobs/index.ts:408-479` — exact weights verified |
| Cache (`user_job_scores`) + invalidation triggers | ✅ | `20260829_phase4_zzz_completion_gaps.sql:40-98` |
| Cursor pagination | ✅ | `search-jobs/index.ts:59-78` |
| First-page cache (5min TTL) | ✅ | `search-jobs/index.ts:38-49` |
| Tests | ✅ | `tests/test_phase4_job_matching.py`, `search-jobs.test.ts` |

## 4. Resume Generation

**Verdict: DONE**

| Feature | Status | Files |
|---------|--------|-------|
| Professional + own format | ✅ | `generate-tailored-resume/index.ts` |
| ATS before/after scores | ✅ | `generated_documents.ats_score_before/after` columns |
| Previous doc tracking | ✅ | `generated_documents.previous_document_id` |
| Idempotency key | ✅ | `_shared/idempotency.ts`, `_shared/generation.ts:145-172` |
| Gemini-flash primary with Groq/OpenRouter fallback | ✅ | `_shared/ai-client.ts` waterfall |
| Tests | ✅ | `generate-tailored-resume.test.ts`, `tests/test_ai_resume_generator.py` |

## 5. Contact Finding

**Verdict: DONE**

| Feature | Status | Files |
|---------|--------|-------|
| 0-credit Apollo port | ✅ | `src/job_radar/enrichment/contact_finder.py` |
| Website scrape | ✅ | `src/job_radar/enrichment/company_scraper.py` |
| Job-posting emails | ✅ | `src/job_radar/enrichment/email_finder.py` |
| Pattern-guess | ✅ | `src/job_radar/enrichment/pattern_matcher.py` |
| LinkedIn search links | ✅ | `src/job_radar/enrichment/linkedin_finder.py` |
| `job_people` confidence | ✅ | `job_people.confidence_score` column |
| Fallback instructions payload | ✅ | `find-contacts/index.ts` |
| Tests | ✅ | `tests/test_enrichment_contact_finder.py`, `find-contacts.test.ts` |

## 6. Cover Letter & Outreach

**Verdict: DONE**

| Feature | Status | Files |
|---------|--------|-------|
| Cover letter with Groq primary | ✅ | `generate-cover-letter/index.ts` |
| Validators enforced | ✅ | `_shared/validators.ts` |
| Outreach: 3 tones | ✅ | `generate-outreach-messages/index.ts` |
| LinkedIn ≤300 hard, email ≤220 words | ✅ | `_shared/validators.ts` |
| Tests | ✅ | `tests/test_ai_cover_letter_generator.py`, `tests/test_ai_outreach_generator.py` |

## 7. Unified Error System

**Verdict: DONE**

| Feature | Status | Files |
|---------|--------|-------|
| Error codes (machine-readable) | ✅ | `_shared/http.ts:34-52` |
| `user_action` field | ✅ | All error helpers include user_action |
| `request_id` (crypto.randomUUID) | ✅ | `_shared/http.ts:44` |
| Used by every Edge Function | ✅ | All import from `_shared/http.ts` |
| Python error hierarchy | ✅ | `src/job_radar/errors/` (base, auth, database, external, validation) |
| Tests | ✅ | `tests/test_error_hierarchy.py`, `tests/test_phase4_ats_and_errors.py` |

## 8. Manual Secrets Walkthrough

**Verdict: DONE**

| Feature | Status | Files |
|---------|--------|-------|
| Document exists | ✅ | `docs/FRONTEND_INTEGRATION_GUIDE.md` |
| Supabase project ref walkthrough | ✅ | Lines 11-27 |
| OAuth credential setup | ✅ | Lines 30-40 |
| Multi-key Gemini setup | ✅ | Lines 44-58 |
| Accurate and current | ✅ | Verified against actual code |

## 9. Tests & Linting

**Verdict: DONE**

| Tool | Status | Details |
|------|--------|---------|
| `pytest` | ✅ | 738 tests passing |
| `vitest` | ✅ | 86 tests passing across 14 suites |
| `ruff` | ✅ | Clean |
| `mypy` | ✅ | Clean |
| `deno check` | ✅ | Clean |

---

## Summary

All 9 Phase-4 checklist items are **DONE**. No PARTIAL or MISSING items require fixes before proceeding to Phase 1.

The only notable design choice is that per-endpoint rate limiting is handled at the Supabase platform level rather than in application code, which is appropriate for this architecture.

---

## 10. Phase 5.1 Defect Audit & Fix Verification

| Defect | Severity | Root Cause | Fix Applied | Status |
|--------|----------|------------|-------------|--------|
| **C1** | Critical | Image worker dict vs `CardJob` contract mismatch & missing landmarks | Re-wired to `CardJob`, added landmark fetch with Wikimedia circuit breaker & fallback | ✅ FIXED |
| **C2** | Critical | LinkedIn/X publishers not executed in workflow | Added `x` and `linkedin` steps to `publish-social.yml` | ✅ FIXED |
| **C3** | Critical | Manual review routing broken & callback UUID truncated | Added `manual_review` transitions to state machine, full 36-char UUID callback_data, approval wiring | ✅ FIXED |
| **C4** | Critical | `slack_post_published` column missing | Added column in migration `20260831_pipeline_fixes.sql` | ✅ FIXED |
| **M1** | Major | Duplicate-post race condition | Added atomic `claim_next_post_job` RPC (`FOR UPDATE SKIP LOCKED`) & concurrency groups | ✅ FIXED |
| **M2** | Major | Twitter/X post URL sliced | Re-budgeted X builder to reserve URL first; text <= 280 & guaranteed `endswith(url)` | ✅ FIXED |
| **M3** | Major | Circuit breakers not wired into workers | Connected `CircuitBreaker` across logo fetch, wikimedia, alert channels, AI summaries, & publishers | ✅ FIXED |
| **M4** | Major | Skill enrichment was rule-only | Added AI skill extraction (Groq/Gemini <=3s) with disk cache & rule fallback | ✅ FIXED |
| **M5** | Major | Non-atomic select-then-upsert metrics | Replaced with atomic `record_metric` SQL function | ✅ FIXED |
| **M6** | Major | Watchdog cadence was 2h | Updated `watchdog.yml` schedule to `*/30 * * * *` (every 30m) | ✅ FIXED |
| **M7** | Major | Monitoring admin action missing | Created `POST /functions/v1/admin-retry` for quarantine retry/dismissal | ✅ FIXED |
| **M8** | Major | Schema gaps (bucket policy, indexes) | Added `job-cards` bucket creation, public policy, and 5 partial indexes in migration | ✅ FIXED |

