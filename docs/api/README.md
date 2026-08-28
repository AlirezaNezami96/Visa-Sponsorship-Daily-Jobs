# VisaLane Backend API

Single source of truth for the frontend-facing API. Two access layers share one
Supabase Postgres (master plan section 3):

| Layer | Runtime | Auth | Purpose |
|---|---|---|---|
| PostgREST (`/rest/v1/*`) | Supabase core | anon JWT + RLS | CRUD on catalog + user-owned tables |
| Edge Functions (`/functions/v1/*`) | Deno on Supabase | Supabase Auth JWT (verified) | On-demand AI + orchestration |

The Python scrape pipeline writes via the **service-role** key (bypasses RLS);
that key is never exposed to any FE code path.

Base URLs:

```
https://<project-ref>.supabase.co/rest/v1/...
https://<project-ref>.supabase.co/functions/v1/...
```

All Edge Function responses are JSON. Preflight `OPTIONS` is handled on every
function (CORS: `*`).

---

## 1. PostgREST endpoints (RLS-backed)

### Jobs & companies — public read

```
GET /rest/v1/jobs?select=*,companies(name,logo_url,ats_type)
    &status=eq.active
    &country_code=in.(DE,NL)
    &visa_sponsorship_verified=eq.true
    &order=created_at.desc
    &range=0-49
```

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| company_id | uuid | join `companies` |
| source_name, source_url | text | provenance |
| canonical_url_hash | text | unique — cross-source dedup key |
| fingerprint | text | (company,title,location) fingerprint |
| title, location_raw, city, country, country_code | text | |
| work_mode | text | remote / hybrid / onsite / unspecified |
| contract_type | text | |
| salary_raw, salary_min, salary_max, salary_currency | | |
| description_text, description_html, requirements | | |
| visa_sponsorship_confidence | int 0-100 | calibrated |
| visa_sponsorship_verified | bool | JD-stated or known sponsor ONLY |
| visa_types | text[] | named programs when stated |
| apply_url | text | |
| posted_at, expires_at, status | | status: active/expired/removed |

`GET /rest/v1/jobs/{id}?select=*,companies(*),job_people(*)` — nested company +
hiring contacts. `removed` jobs are hidden by RLS.

`job_people` columns: `name, title, email, email_status
(verified|unverified|pattern_guess|generic|not_found), email_confidence,
linkedin_url, linkedin_search_url, source_type, confidence`. FE MUST label
`pattern_guess` rows as guesses — never as verified emails.

### User-owned tables (owner RLS: `id = auth.uid()` / `user_id = auth.uid()`)

- `profiles` — GET/PATCH own row (PK = auth.users id)
- `resumes` — GET/POST/PATCH/DELETE own resumes (`file_path` points at Storage `resumes/{user_id}/...`)
- `generated_documents` — GET own; rows created by generation functions
- `applications` — GET/PATCH own; unique per (user, job)
- `saved_jobs` — GET/POST/DELETE own
- `alerts` — GET/POST/PATCH/DELETE own. `filters` and `channels` JSONB vocab:

```jsonc
// alerts.filters (all keys optional)
{
  "keywords": ["react"],
  "countries": ["DE", "Netherlands"],
  "work_modes": ["remote", "hybrid"],
  "exclude_companies": ["Acme"],
  "min_confidence": 70,
  "verified_only": true,
  "min_match": 80
}
// alerts.channels
{ "email": true, "telegram": true, "discord": false, "slack": false }
// alerts.frequency
"instant" | "hourly" | "daily" | "weekly"
```

- `usage_limits` — GET own rows (also available via the function below)
- `feedback` — INSERT (any authenticated user); SELECT own only

Service-only tables (`social_post_queue`, `scrape_runs`, `alert_sent_jobs`,
`analytics_events`) have **no** RLS policies for anon/authenticated and are not
accessible via PostgREST from the FE.

---

## 2. Edge Functions

Common error envelope:

```json
{ "error": { "code": "unauthorized|bad_request|usage_limit_reached|ai_providers_exhausted|invalid_ai_output|contract_violation|internal_error|method_not_allowed", "message": "..." } }
```

| Status | Meaning |
|---|---|
| 400 | bad_request — missing/invalid input |
| 401 | unauthorized — missing/invalid JWT |
| 402 | usage_limit_reached — daily quota exhausted (AI never invoked) |
| 405 | method_not_allowed |
| 502 | AI failure — all providers exhausted OR malformed/contract-violating output |
| 500 | internal_error |

### 2.1 POST /functions/v1/parse-resume

Extracts structured data from resume text in-memory (raw text is never written
to disk; privacy pattern ported from `resume_fetch.py`).

Request:

```json
{ "resume_text": "...>= 20 chars...", "resume_id": "optional-uuid" }
```

Response 200:

```json
{
  "document_id": "uuid|null",
  "ai_provider": "gemini|groq|openrouter",
  "ai_model": "gemini-2.5-flash",
  "cached": false,
  "output": {
    "full_name": "...", "email": "...", "phone": null,
    "job_titles": ["..."], "skills": ["..."], "summary": "...",
    "experience": [{"company":"...","title":"...","start":"...","end":"...","highlights":["..."]}],
    "education": [{"institution":"...","degree":"...","year":"..."}],
    "prompt_version": "parse-v1"
  }
}
```

Usage: `import_attempts` quota. If `resume_id` given, `parsed_data` is also
written onto that resume row.

### 2.2 POST /functions/v1/generate-tailored-resume

Request:

```json
{ "resume_id": "uuid", "job_id": "uuid", "format_preference": "own|professional" }
```

`format_preference` is ignored when the profile has `remember_resume_format`
set (profile preference wins). Grounded in `resume_matcher.py` output
(`ats_baseline.keywords_to_add` woven in where truthful).

Response 200:

```json
{
  "document_id": "uuid",
  "ai_provider": "...", "ai_model": "...", "cached": false,
  "output": {
    "tailored_resume_markdown": "...",
    "keywords_added": ["..."],
    "tailoring_notes": ["Emphasized ... to match ..."],
    "estimated_ats_score": 87,
    "format_type": "professional",
    "prompt_version": "tailor-v1"
  }
}
```

Usage: `resume_generations` quota → 402 beyond plan limit.

### 2.3 POST /functions/v1/generate-cover-letter

Request:

```json
{ "job_id": "uuid", "resume_id": "optional-uuid", "format_preference": "own|professional" }
```

Guarantees enforced by prompt contract + validator
(`docs/contracts/cover_letter.schema.json`): no generic openers, no
hallucinated experience, 250–400 words, hook grounded in company intel.

Response 200 `output`:

```json
{
  "cover_letter_markdown": "...",
  "overlap_skills": ["...", "..."],
  "company_hook": "...",
  "word_count": 312,
  "format_type": "professional",
  "prompt_version": "cl-v1"
}
```

Usage: `cover_letter_generations` quota → 402 beyond plan limit.

### 2.4 POST /functions/v1/generate-outreach-messages

Request:

```json
{ "job_id": "uuid", "resume_id": "optional-uuid", "tone": "professional|friendly|natural" }
```

Defaults: `tone="natural"`. Contacts come from `job_people` (0-credit Apollo +
fallbacks). **LinkedIn body is hard-capped at 300 characters server-side before
storing** (`trimmed_to_limit` reports whether capping occurred). A companion
`outreach_linkedin` document row is persisted alongside.

Response 200 `output`:

```json
{
  "email": { "subject": "...", "body": "...", "tone": "natural" },
  "linkedin": { "body": "...<=300 chars...", "tone": "natural", "trimmed_to_limit": false },
  "prompt_version": "out-v1"
}
```

Usage: shares the `cover_letter_generations` quota (no separate outreach
counter in `usage_limits`) → 402 once that daily limit is exhausted.

### 2.5 POST /functions/v1/complete-application

Request:

```json
{ "job_id": "uuid", "resume_document_id": "optional", "cover_letter_document_id": "optional" }
```

Upserts `applications` (unique per user+job), emits `application_completed`
analytics. Response 200: `{ "application": { ...row } }`.

### 2.6 GET /functions/v1/usage-limits

Response 200:

```json
{
  "plan": "free|pro",
  "trial_active": true,
  "trial_ends_at": "2026-11-26T00:00:00Z",
  "date": "2026-08-28",
  "usage": {
    "resume_generations": { "used": 1, "limit": 2, "remaining": 1 },
    "cover_letter_generations": { "used": 0, "limit": 2, "remaining": 2 },
    "alert_sends": { "used": 0, "limit": 5, "remaining": 5 },
    "import_attempts": { "used": 1, "limit": 3, "remaining": 2 }
  }
}
```

Plan resolution: `subscription_plan='pro'` OR unexpired `trial_ends_at` → pro
limits; otherwise free. Downgrade is automatic at trial expiry.

### 2.7 POST /functions/v1/feedback

Request: `{ "category": "bug|ux|data|other", "message": "...", "page": "optional", "metadata": {} }`
Response 201: `{ "ok": true, "id": "uuid" }`.

### 2.8 POST /functions/v1/process-new-jobs  *(internal/cron)*

**Not user-facing.** Auth: `x-cron-secret: $PROCESS_JOBS_SECRET` header or
`Authorization: Bearer $PROCESS_JOBS_SECRET`. Orchestrates: alert matching
(instant/hourly alerts; idempotent via `alert_sent_jobs`), social queue staging
(`linkedin`/`x` → `manual_review`, others → `pending`), enrichment trigger
(handled by the Python enrichment worker).

Response 200:

```json
{ "jobs_processed": 12, "alerts_matched": 5, "social_queued": 60, "enrichment_pending": 12 }
```

---

## 3. AI behavior (both runtimes)

Provider chain: `Gemini → Groq → OpenRouter` (Python adds Ollama/local). On
429/5xx the chain advances and an `ai_fallback_triggered` analytics event is
written. Deterministic caching: Python uses the disk cache
(`state/classifier_cache.json`, hash of job content); Edge Functions use an
in-instance memory cache keyed by sha256(prompt+json-flag). Structured errors
are returned only when **all** providers fail.

Prompt contracts live in `docs/contracts/*.schema.json` and are shared by both
runtimes (`prompt_version` fields: `parse-v1`, `tailor-v1`, `cl-v1`, `out-v1`;
Python classifier: `v2-visa-conf`).

## 4. Analytics events

Written to `analytics_events` by both runtimes. Event names:
`user_signup`, `profile_completed`, `resume_parsed`, `resume_generated`,
`cover_letter_generated`, `application_completed`, `alert_created`, `alert_sent`,
`social_post_published`, `ai_fallback_triggered`, `api_error`,
`scrape_completed`, `jobs_added`, `pipeline_fallback_triggered`.

```sql
select event_name, count(*) from analytics_events
where created_at > now() - interval '7 days' group by 1 order by 2 desc;
```

## 5. Environment variables (Edge Functions)

| Var | Purpose |
|---|---|
| SUPABASE_URL, SUPABASE_ANON_KEY | injected by Supabase automatically |
| SUPABASE_SERVICE_ROLE_KEY | admin client (never returned to FE) |
| GEMINI_API_KEY / GEMINI_PRO_MODEL | provider 1 |
| GROQ_API_KEY / GROQ_MODEL | provider 2 |
| OPENROUTER_API_KEY / OPENROUTER_MODEL | provider 3 |
| PROCESS_JOBS_SECRET | guards process-new-jobs |

Python pipeline vars are documented in `.env.example` + `SETUP.md`; the
VisaLane stages add: `VISALANE_SYNC=1` (opt-in post-scrape sync),
`VISALANE_ENRICHMENT=1` (opt-in enrichment during sync), `BREVO_API_KEY`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DISCORD_WEBHOOK_URL`,
`SLACK_WEBHOOK_URL`.
