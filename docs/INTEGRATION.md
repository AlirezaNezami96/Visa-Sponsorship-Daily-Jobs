# VisaLane — Backend Build Summary, Website Integration & Secrets Guide

This document answers three questions:

1. **What was built** in the backend (this repo).
2. **How the website** (`AlirezaNezami96/global-job-pass`) consumes it.
3. **Which secrets/credentials are needed**, with step-by-step instructions for
   getting each one.

The live API contract for all endpoints is in [`docs/api/README.md`](api/README.md).
This guide is the operational companion to it.

---

## 1. What the backend does

The backend is a two-runtime system around one Supabase Postgres database:

| Component | Where it lives | What it does |
|---|---|---|
| **Python scrape pipeline** | repo root (`fetchers*.py`, `engine/`) + GitHub Actions | Scrapes ~12 job sources daily, dedupes, classifies visa-sponsorship confidence, syncs into Supabase, matches user alerts, stages social posts |
| **Supabase Edge Functions** (Deno/TS) | `supabase/functions/` | User-facing AI actions (resume parsing, tailored resumes, cover letters, outreach messages), usage quotas, application completion, feedback, cron orchestration |
| **PostgREST** (automatic) | Supabase core | All table CRUD, protected by Row-Level Security (RLS) |
| **Database schema** | `supabase/migrations/` + `seed.sql` | jobs, companies, job_people, profiles, resumes, generated_documents, applications, saved_jobs, alerts, usage_limits, feedback, analytics_events, social_post_queue, scrape_runs, alert_sent_jobs |
| **Apify actor** | `.actor/` | Scheduled scraping on the Apify platform |

Key properties:

- **AI waterfall**: every AI call tries `Gemini → Groq → OpenRouter` (Python also
  falls back to local Ollama). If one provider 429s/5xxs, the call advances and an
  `ai_fallback_triggered` analytics event is logged. Verified end-to-end: with
  Gemini + Groq keys broken, requests still succeed through OpenRouter.
- **Usage quotas**: daily per-user limits per action (`resume_generations`,
  `cover_letter_generations` — shared with outreach messages —, `alert_sends`,
  `import_attempts`), with free/pro plan resolution and trial logic. Enforced in
  Edge Functions before any AI call (402 when exhausted).
- **RLS isolation verified**: user A can never read/patch/delete user B's rows;
  internal tables (`social_post_queue`, `scrape_runs`, …) have no FE policies at all.
- **Prompt contracts**: JSON-schemas in `docs/contracts/` + server-side validators
  (no hallucinated experience, no generic cover-letter openers, 250–400 words,
  LinkedIn outreach hard-capped at 300 chars).
- **Service-role key is server-only** — it is never exposed to any frontend code
  path; the FE only ever sees the anon key.

Verified state: 423 pytest + 35 vitest tests green, clean lints (ruff/mypy/deno),
migrations apply from scratch (`supabase db reset`), 16 GitHub workflows valid.

---

## 2. How the website uses the backend

The website repo (`global-job-pass`, Lovable React app) talks to Supabase only —
there is **no** custom backend server to host. Two access layers share one
Postgres:

```
Browser (global-job-pass)
│
├── PostgREST  https://<project-ref>.supabase.co/rest/v1/...
│   jobs, companies, job_people            → public read (catalog, search)
│   profiles, resumes, saved_jobs, alerts,
│   applications, usage_limits, feedback   → owner-only via auth.uid() RLS
│
└── Edge Functions  https://<project-ref>.supabase.co/functions/v1/...
    parse-resume, generate-tailored-resume, generate-cover-letter,
    generate-outreach-messages, complete-application, usage-limits, feedback
    (all require a valid Supabase Auth JWT; process-new-jobs is cron-only)
```

### 2.1 The frontend adapter

`global-job-pass/src/services/api.ts` is written as a **1:1 adapter**: every
exported function maps to exactly one backend endpoint (the file header states
this explicitly). Today those functions return mock data (`mock-data.ts`,
`mock-jobs-generator.ts`, localStorage). Going live means swapping each adapter
function's body for its real call — **no component changes required**, because
components only know the adapter.

Adapter function → backend endpoint mapping:

| Frontend adapter function | Backend call |
|---|---|
| `searchJobs` / `searchJobsPage` / `getJob` / `suggestJobs` | `GET /rest/v1/jobs` (+ `companies`, `job_people` joins), filters via PostgREST params |
| `loginWithEmail` and auth flows | Supabase Auth (`supabase.auth.signUp / signInWithOtp …`) |
| profile get/save | `GET`/`PATCH /rest/v1/profiles?id=eq.<uid>` |
| resume import/parse | upload file to Storage `resumes/<uid>/`, then `POST /functions/v1/parse-resume` |
| tailored resume | `POST /functions/v1/generate-tailored-resume` |
| cover letter | `POST /functions/v1/generate-cover-letter` |
| outreach messages | `POST /functions/v1/generate-outreach-messages` |
| apply flow completion | `POST /functions/v1/complete-application` |
| saved jobs / applications / alerts | PostgREST CRUD on `saved_jobs` / `applications` / `alerts` |
| quota display | `GET /functions/v1/usage-limits` |
| feedback form | `POST /functions/v1/feedback` |

### 2.2 What the website needs to deploy

Only two values, both **public by design** (RLS is the security boundary):

| Value | Where to get it |
|---|---|
| `SUPABASE_URL` | Supabase dashboard → Project Settings → API → *Project URL* |
| `SUPABASE_ANON_KEY` | Supabase dashboard → Project Settings → API → *anon public* key |

In the Lovable/Vite app these are exposed as `VITE_SUPABASE_URL` /
`VITE_SUPABASE_ANON_KEY` (or via a thin proxy). The service-role key **must
never** appear in this repo.

### 2.3 Data freshness

The website reads whatever the Python pipeline wrote to `jobs`/`companies`.
Freshness is controlled by the schedule in `.github/workflows/daily-*.yml` and
the Apify actor schedule (`APIFY_WORKFLOW_KEY`). The cron Edge Function
`process-new-jobs` (hit by `visalane-dispatch.yml`, authenticated with
`PROCESS_JOBS_SECRET`) does alert matching + social queue staging after a scrape.
LinkedIn and X posts always land in `manual_review`; other channels go to
`pending` for auto-posting (Discord/Slack/Telegram webhooks).

---

## 3. Secrets & credentials — what to get and how

> Never commit secrets. Locally: copy `.env.example` → `.env`. In CI: GitHub
> repo → Settings → Secrets and variables → Actions. For Edge Functions:
> Supabase dashboard → Project → Edge Functions → Secrets (or
> `supabase secrets set NAME=value`).

### 3.0 Suggested order

Do Supabase first (everything points at it), then the AI providers, then email,
then the scrape/social integrations, then GitHub Actions secrets last.

---

### 3.1 Supabase — project, keys, migrations, Edge Functions ⭐ core

Used by: **everything**.

1. Go to https://app.supabase.com → sign in (GitHub login works) → **New project**.
   Name: e.g. `visalane`. Region: closest to your users (Frankfurt is a good EU
   default). Set a strong DB password, save it in a password manager.
2. Wait for the project to initialize. Open **Project Settings → API**. Copy:
   - **Project URL** → `SUPABASE_URL`
   - **anon public** key → `SUPABASE_ANON_KEY` (safe for the website)
   - **service_role** key → `SUPABASE_KEY` / `SUPABASE_SERVICE_ROLE_KEY`
     (server-side only — pipeline + Edge Functions. **Never** put it in the
     website repo or client code.)
3. Install the CLI: `brew install supabase/tap/supabase`, then log in:
   `supabase login` (opens the browser).
4. Deploy schema + functions from this repo root:
   ```bash
   supabase link --project-ref <project-ref>   # ref = first part of the Project URL
   supabase db reset                            # runs supabase/migrations + seed.sql on the cloud project
   supabase functions deploy                    # deploys supabase/functions/*
   ```
   `supabase db reset` against a fresh project is safe; against a project with
   real user data it **wipes data** — use `supabase db push` instead once live.
5. Set Edge Function secrets (dashboad → Edge Functions → Secrets, or CLI):
   ```bash
   supabase secrets set SUPABASE_SERVICE_ROLE_KEY=<value>
   supabase secrets set GEMINI_API_KEY=<value>
   supabase secrets set GROQ_API_KEY=<value>
   supabase secrets set OPENROUTER_API_KEY=<value>
   supabase secrets set PROCESS_JOBS_SECRET=<value>
   ```
   `SUPABASE_URL` and `SUPABASE_ANON_KEY` are injected into functions
   automatically by Supabase — do not set them.
6. Verify:
   ```bash
   curl "https://<project-ref>.supabase.co/rest/v1/jobs?select=id&limit=1" \
     -H "apikey: $SUPABASE_ANON_KEY"
   ```
   Should return `[]` or rows (not a 401/403).

**Cost**: free plan is sufficient for this stack.

---

### 3.2 Gemini API key (AI provider 1)

1. Go to https://aistudio.google.com/apikey → sign in with a Google account.
2. Click **Create API key** → **Create API key in new project**.
3. Copy the `AIza…` key → `GEMINI_API_KEY`.
4. Optional model overrides: `GEMINI_FLASH_MODEL` (default `gemini-2.5-flash`),
   `GEMINI_PRO_MODEL`.

**Cost**: generous free tier (gemini-2.5-flash free tier is enough for dev).

---

### 3.3 Groq API key (AI provider 2 — fast fallback)

1. Go to https://console.groq.com → sign in (Google supported).
2. Left sidebar → **API keys** → **Create API key** → copy the `gsk_…` key
   → `GROQ_API_KEY`.
3. Optional: `GROQ_MODEL` (default `llama-3.3-70b-versatile`).

**Cost**: free tier available; the waterfall only uses it when Gemini fails.

---

### 3.4 OpenRouter API key (AI provider 3 — last-resort fallback)

1. Go to https://openrouter.ai → sign in → **Keys** (top-right menu) →
   **Create Key** → copy the `sk-or-…` key → `OPENROUTER_API_KEY`.
2. Optional: `OPENROUTER_MODEL` (default `minimax/minimax-m3:free`).
3. Free `:free` models have daily limits (~50–1000 requests depending on
   account credit). Add a few dollars of credit if you want guaranteed fallback:
   **Buy credits**.

This is the safety net: if free models go stale again, update the default model
here and in `supabase/functions/_shared/ai-client.ts` + `engine/api/router.py`.

---

### 3.5 Email delivery (pick ONE provider)

Set `EMAIL_PROVIDER` to match your choice. All four are supported; the Python
`email_sender.py` uses whichever is configured, and the alert/notification path
falls back Resend → Brevo → SendGrid → Gmail SMTP.

#### Resend (recommended — free 3,000 emails/month)

1. https://resend.com → sign up → **API Keys** → **Create API Key** →
   `re_…` key → `RESEND_API_KEY`.
2. Sending address: either use their free `onboarding@resend.dev` for testing,
   or add your domain: **Domains → Add Domain** → add the DNS records (TXT/SPF/
   DKIM/MX) at your DNS provider → wait for **Verified**. Then set
   `EMAIL_FROM=noreply@yourdomain.com`.
3. `EMAIL_TO=your@email.com` (where the daily job reports land when no per-user
   channel matches), `EMAIL_PROVIDER=resend`.

#### Brevo (free 300/day)

1. https://www.brevo.com → sign up → top-right avatar → **SMTP & API** →
   **API keys** → create a v3 key → `BREVO_API_KEY`.

#### SendGrid (free 100/day)

1. https://sendgrid.com → sign up → **Settings → API Keys → Create API Key**
   (Full Access) → `SG.…` key → `SENDGRID_API_KEY`.

#### Gmail SMTP (small volume only)

1. Google account → https://myaccount.google.com/security → enable
   **2-Step Verification**.
2. Search “App passwords” → create app password → 16-char code →
   `GMAIL_APP_PASSWORD`. `GMAIL_USER=your@gmail.com`.

---

### 3.6 Adzuna (job-source API — free)

1. https://developer.adzuna.com → **Create an account** → verify email.
2. Once logged in, your dashboard shows the key pair → `ADZUNA_APP_ID` (app id)
   and `ADZUNA_APP_KEY` (app key; regenerate if missing).

**Cost**: free for non-commercial use; sufficient for scraping.

---

### 3.7 Apify (scheduled scraping platform)

1. https://apify.com → sign up (GitHub supported).
2. The actor is already in this repo (`.actor/`). Push it to Apify:
   install CLI `npm i -g apify-cli`, then `apify login` and `apify push` from
   `.actor/`.
3. In the Apify console → your actor → **Scheduling** → create a schedule.
4. **Settings → Integrations** (or actor settings) → copy the token →
   `APIFY_TOKEN` (GitHub Actions). For the Python workflow key: actor →
   **API → Schedule** or the workflow run URL key → `APIFY_WORKFLOW_KEY`.

**Cost**: free plan ($5 platform credit/month) covers daily runs.

---

### 3.8 Telegram bot (LinkedIn post publishing notifications)

1. In Telegram, open **@BotFather** → `/newbot` → pick a name and username.
2. BotFather returns the token (`123456789:AAH…`) → `TELEGRAM_BOT_TOKEN`.
3. Send any message to your new bot (it must receive a message before it can
   reply).
4. Get the chat id: open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser → find
   `"chat":{"id":123456789}` → that number is both `TELEGRAM_CHAT_ID` and
   `TELEGRAM_AUTHORIZED_USER_ID` (a personal chat id).

**Cost**: free.

---

### 3.9 LinkedIn API (optional — social posting)

LinkedIn only grants API access for approved use cases; if you get access:

1. https://www.linkedin.com/developers → **Create app** → fill company details,
   add an app logo (required to submit).
2. Verify the app via the verification email LinkedIn sends.
3. **Products** tab → request access to **Share on LinkedIn** (and
   **Sign In** if you want OAuth login). Some products are instant-approve,
   others wait for LinkedIn review.
4. **Auth → Access tokens** (dev tokens) or run an OAuth flow; the token →
   `LINKEDIN_ACCESS_TOKEN`. Client credentials → `LINKEDIN_CLIENT_ID` /
   `LINKEDIN_CLIENT_SECRET`.
5. Your person URN: call `https://api.linkedin.com/v2/userinfo` with the token;
   the `sub` → `LINKEDIN_PERSON_URN=urn:li:person:<sub>`.

If approval is pending, leave these empty — the pipeline still works; LinkedIn
posts stay in the manual review queue.

---

### 3.10 Apollo.io (hiring-contact discovery — optional)

1. https://app.apollo.io → sign up (free tier: 50 exported credits/month).
2. **Settings → Integrations → API** → copy the key → `APOLLO_API_KEY`.

Used by the enrichment stage (`job_people`); the website degrades gracefully
(contacts section shows LinkedIn search links instead of emails when
unavailable). Leave empty to skip enrichment entirely.

---

### 3.11 Discord / Slack webhooks (notification channels — optional)

**Discord**
1. Server Settings → **Integrations → Webhooks → New webhook** → choose the
   channel → **Copy webhook URL** → `DISCORD_WEBHOOK_URL`.

**Slack**
1. https://api.slack.com/apps?new_app=1 → **From scratch** → pick workspace.
2. **Incoming Webhooks** → Activate → **Add New Webhook to Workspace** → pick
   channel → copy URL → `SLACK_WEBHOOK_URL`.

---

### 3.12 Pipeline cron secret

`PROCESS_JOBS_SECRET` guards the internal `process-new-jobs` Edge Function.
Generate one:

```bash
openssl rand -hex 32
```

Store the same value in Supabase Edge Function secrets **and** GitHub Actions
secrets (the `visalane-dispatch.yml` workflow sends it as the `x-cron-secret`
header).

---

### 3.13 Google Drive DB backups (optional)

1. https://console.cloud.google.com → create/select project → **IAM & Admin →
   Service Accounts** → create one → **Keys → Add key → JSON** → the JSON file
   contents → `GOOGLE_SERVICE_ACCOUNT_JSON`. Grant the service account Editor on
   a Drive folder (share the folder in Drive with the service-account email).
2. Open the folder in Drive, copy the folder id from the URL →
   `GDRIVE_BACKUP_FOLDER_ID`.

---

### 3.14 GitHub Actions secrets (put it all together)

Repo → **Settings → Secrets and variables → Actions → New repository secret**.
Create one secret per line — names must match exactly, values = the credentials
above:

**Required:**

| Secret | From |
|---|---|
| `SUPABASE_URL` | §3.1 |
| `SUPABASE_KEY` | §3.1 service_role key |
| `SUPABASE_SERVICE_ROLE_KEY` | §3.1 service_role key (same value) |
| `SUPABASE_DB_CONNECTION_STRING` | Supabase → Project Settings → Database → *Connection string* (URI), with your DB password substituted |
| `GEMINI_API_KEY` | §3.2 |
| `GROQ_API_KEY` | §3.3 |
| `OPENROUTER_API_KEY` | §3.4 |
| `PROCESS_JOBS_SECRET` | §3.12 |
| `EMAIL_PROVIDER` | §3.5 (`resend`) |
| `EMAIL_TO` / `EMAIL_FROM` | §3.5 |
| `RESEND_API_KEY` | §3.5 |

**Add per feature you enable:**

| Secret | From |
|---|---|
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | §3.6 |
| `APIFY_TOKEN` / `APIFY_WORKFLOW_KEY` | §3.7 |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `TELEGRAM_AUTHORIZED_USER_ID` | §3.8 |
| `LINKEDIN_ACCESS_TOKEN` / `LINKEDIN_PERSON_URN` | §3.9 |
| `APOLLO_API_KEY` | §3.10 |
| `BREVO_API_KEY` / `SENDGRID_API_KEY` | §3.5 |
| `GMAIL_USER` / `GMAIL_APP_PASSWORD` | §3.5 |
| `DISCORD_WEBHOOK_URL` / `SLACK_WEBHOOK_URL` | §3.11 |
| `GDRIVE_BACKUP_FOLDER_ID` / `GOOGLE_DRIVE_CREDENTIALS` / `GOOGLE_SERVICE_ACCOUNT_JSON` | §3.13 |
| `GH_PAT` | only if you turn on branch protection that blocks GITHUB_TOKEN (repo Settings → Developer settings → Fine-grained token) |

Workflows that use optional AI/browser providers (`OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `ZAI_API_KEY`, `BROWSERBASE_API_KEY`, `BROWSER_USE_API_KEY`,
`POLLINATIONS_API_KEY`, `PROXY_URL`) silently skip those steps when the secret
is absent — set them only if you use those sources.

---

## 4. Go-live checklist

- [ ] Supabase project created; migrations applied (`supabase db reset`); Edge
      Functions deployed; Edge Function secrets set (§3.1, §3.2–3.4, 3.12)
- [ ] `curl` smoke test on `/rest/v1/jobs` returns 200 (§3.1 step 6)
- [ ] Run one local scrape: `python run.py --dry-run` then a real run with
      `.env` filled (confirm rows appear in the Supabase Table Editor under `jobs`)
- [ ] GitHub Actions secrets filled (§3.14); push a commit and confirm the
      daily workflows go green
- [ ] `visalane-dispatch.yml` hits `process-new-jobs` successfully (check
      `analytics_events` / function logs)
- [ ] Website repo gets `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY`; each
      `src/services/api.ts` function swapped from mock to the mapped endpoint
      (§2.1 table)
- [ ] Create a test user in the website → import a resume → generate a cover
      letter → confirm quotas decrement (`GET /functions/v1/usage-limits`)

---

## 5. Reference

- Full endpoint contract: [`docs/api/README.md`](api/README.md)
- Python pipeline setup: [`SETUP.md`](../SETUP.md)
- Env var template: [`.env.example`](../.env.example)
- Prompt contracts (AI output validators): `docs/contracts/`
- Change history: [`CHANGELOG.md`](../CHANGELOG.md)
