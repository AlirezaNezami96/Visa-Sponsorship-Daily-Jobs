# AI Internship & Early-Career Engineer Remote Job Radar

A dedicated, autonomous radar for **AI/ML internships** and **early-career (0–2 yrs) remote engineer roles**. Runs 100% free on **GitHub Actions**, scans direct company ATS APIs + public remote job boards, uses Gemini/LLM relevance filtering, deduplicates cross-source postings, and delivers clean daily email digests.

---

## ⚡ What It Does

1. **Two-Track Targeting**:
   - **Track 1: AI & ML Internships** (Student, Intern, Co-op, Fellowship, Trainee).
   - **Track 2: Early-Career AI Engineers** (Junior, Entry-level, Associate, 0–2 yrs exp).
   - Strictly filters out senior, staff, principal, lead, and management postings.
2. **Direct ATS APIs & Public Job Boards**:
   - Hits live JSON APIs for Greenhouse, Lever, Ashby, Workable, SmartRecruiters, and Personio across top AI labs and tech employers (Anthropic, OpenAI, Databricks, Scale AI, Mistral, Together AI, etc.).
   - Fetches free, compliant public remote job board APIs: **RemoteOK**, **Remotive**, **Arbeitnow**, **Himalayas**, and **Hacker News "Who is Hiring"**.
3. **LLM Relevance & Remote Scope Classifier**:
   - Optional AI auditor powered by `gemini-3.6-flash` (or Anthropic/OpenAI) that screens candidate descriptions, scores relevance (0–100), detects genuine AI/ML day-to-day focus vs. non-AI roles, and checks worldwide/regional remote scope.
   - **Disk Caching**: Results are hashed and saved to `state/classifier_cache.json` for 0 repeated API costs.
4. **Smart Cross-Source Deduplication**:
   - Canonical URL normalization and `(normalized_company, normalized_title, normalized_location)` fingerprinting prevent duplicate alerts when a role is syndicated across multiple boards.
5. **Dual-Track Email Digest**:
   - Responsive HTML digest grouped into Internships and Early-Career Engineers with match score pills, one-line "why it matched" explanations, direct apply buttons, and run health stats.

---

## Architecture

```
                      ┌──────────────────────────────────────────────┐
                      │                 config.yaml                  │
                      └──────────────────────┬───────────────────────┘
                                             │
      ┌──────────────────────────────────────┴──────────────────────────────────────┐
      │                                                                             │
      ▼                                                                             ▼
Direct ATS APIs & Custom                              Public Remote Job Board APIs
(Greenhouse, Lever, Ashby,                            (RemoteOK, Remotive, Arbeitnow,
 Workable, SmartRecruiters)                            Himalayas, Hacker News)
      │                                                                             │
      └──────────────────────────────────────┬──────────────────────────────────────┘
                                             ▼
                                  filter.py (Pre-filter)
                               - Seniority Exclusions
                               - Multi-Track Regex Matching
                               - Cross-Source Fingerprint Dedup
                                             │
                                             ▼
                             classify_relevance.py (LLM Filter)
                               - Gemini 3.6 Flash / Anthropic / OpenAI
                               - Relevance Scoring (0-100) & Why snippet
                               - Disk Cache: state/classifier_cache.json
                                             │
                                             ▼
                                email_sender.py (Dual-Track HTML)
                               - 🎓 AI & ML Internships
                               - 🚀 Early-Career AI Engineers
                               - Run Health & Source Attribution
                                             │
                                             ▼
                                 GitHub Actions Cron (Daily)
```

## Project Files

| File | Purpose |
|------|----------|
| `config.yaml` | Central configuration for tracks, keywords, geography, LLM classifier, and email settings |
| `config_loader.py` | Typed dataclass loader for `config.yaml` with environment variable overrides |
| `run.py` | Main orchestrator for the AI Internship & Engineer Remote Job Radar |
| `classify_relevance.py` | LLM relevance scoring, remote scope auditor, and disk cache manager |
| `fetchers_public_apis.py` | Public job board integrations (RemoteOK, Remotive, Arbeitnow, Himalayas, HN) |
| `filter.py` | Keyword pre-filter, seniority exclusion, and cross-source fingerprint deduplication |
| `email_sender.py` | Dual-track HTML email builder and delivery via Resend, SendGrid, or Gmail SMTP |
| `ai_companies.json` | Curated AI employers and specialized job portals |
| `build_ai_companies.py` | Generator script for `ai_companies.json` |
| `companies.json` | Global company target list with ATS classifications |
| `seen_jobs.json` | State store for deduplication (persisted to repo via CI) |
| `state/classifier_cache.json`| On-disk cache for LLM classification outputs |
| `.github/workflows/daily-jobs.yml` | GitHub Actions cron workflow for automated daily execution |

---

## Setup Guide (Your Manual Steps)

### Step 1: Create a GitHub Repository

1. Go to [github.com/new](https://github.com/new)
2. Create a **private** repository (recommended — your job search is private)
3. Name it something like `visa-job-scraper`
4. Do **not** initialize with README (we'll push our files)

### Step 2: Push This Project to Your Repo

```bash
# Clone your empty repo
git clone https://github.com/YOUR_USERNAME/visa-job-scraper.git
cd visa-job-scraper

# Copy all project files into this directory
# (the files from this project)

git add .
git commit -m "Initial visa job scraper setup"
git push origin main
```

### Step 3: Set Up Email (Pick ONE option)

#### Option A: Resend (Recommended — Easiest, 3,000 emails/month free)

1. Go to [resend.com/signup](https://resend.com/signup) and create a free account
2. Go to [resend.com/api-keys](https://resend.com/api-keys) and click **"Create API Key"**
3. Copy the API key (starts with `re_`)
4. Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions**
5. Add these secrets:
   - `RESEND_API_KEY` = `re_xxxxxxxx` (your API key)
   - `EMAIL_TO` = `your-real-email@example.com`
   - `EMAIL_FROM` = `onboarding@resend.dev` (this works for testing; to use your own domain, verify it in Resend dashboard)

#### Option B: Gmail SMTP (Free, ~500 emails/day)

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Enable **2-Step Verification** if not already on
3. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
4. Create an **App Password** (select "Mail" and "Other", name it "Job Scraper")
5. Copy the 16-character password
6. Add these GitHub secrets:
   - `GMAIL_USER` = `your@gmail.com`
   - `GMAIL_APP_PASSWORD` = `the-16-char-password`
   - `EMAIL_TO` = `your-real-email@example.com`
7. Also add a repo variable (not secret):
   - `EMAIL_PROVIDER` = `gmail`

#### Option C: SendGrid (Free, 100 emails/day)

1. Go to [sendgrid.com](https://sendgrid.com) and create a free account
2. Create a **Sender Identity** (verify your email)
3. Go to **Settings** → **API Keys** → Create API Key
4. Add these GitHub secrets:
   - `SENDGRID_API_KEY` = `SG.xxxxxxxx`
   - `EMAIL_TO` = `your-real-email@example.com`
   - `EMAIL_FROM` = `your-verified@email.com`

### Step 4: Configure Your Secrets in GitHub

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add ALL of these (even if some are blank — they won't be used):

| Secret | Value | Required |
|--------|-------|----------|
| `RESEND_API_KEY` | `re_xxxxxxxx` | Yes (if using Resend) |
| `EMAIL_TO` | `your@email.com` | Yes |
| `EMAIL_FROM` | `onboarding@resend.dev` | No (has default) |
| `EMAIL_PROVIDER` | `resend` / `gmail` / `sendgrid` | No (defaults to resend) |
| `SENDGRID_API_KEY` | `SG.xxxxxxxx` | Only if using SendGrid |
| `GMAIL_USER` | `your@gmail.com` | Only if using Gmail |
| `GMAIL_APP_PASSWORD` | `xxxx xxxx xxxx xxxx` | Only if using Gmail |

> **To set EMAIL_PROVIDER**: Go to **Settings** → **Secrets and variables** → **Actions** → **Variables** tab (not Secrets) → Add `EMAIL_PROVIDER` as a repository variable.

### Step 5: Customize Your Job Keywords

Edit `filter.py` and change these lists:

```python
KEYWORDS_INCLUDE = [
    "android", "mobile", "flutter", "ios", "react native",
    "software engineer", "developer", "backend", "frontend", "fullstack",
    # Add your own keywords here
]

KEYWORDS_EXCLUDE = [
    "senior", "staff", "principal",  # Remove these if you want senior roles
    # Add more exclusions here
]
```

Commit and push after editing:
```bash
git add filter.py
git commit -m "Customize job keywords"
git push
```

### Step 6: Set the Schedule (Timezone)

Edit `.github/workflows/daily-jobs.yml` and change the cron time:

```yaml
schedule:
  - cron: "0 8 * * *"  # 08:00 UTC daily
```

Convert your preferred time to UTC:
- 09:00 Berlin → `0 8 * * *`
- 08:00 London → `0 8 * * *`
- 00:00 San Francisco → `0 8 * * *`
- 16:00 Singapore → `0 8 * * *`

Use [crontab.guru](https://crontab.guru) to convert your time.

### Step 7: Enable GitHub Actions

1. Go to your repo → **Actions** tab
2. If you see "Workflows aren't being run on this repository", click **"I understand my workflows, go ahead and enable them"**
3. Go to **Actions** → **Daily Job Scan** → **Run workflow** (manual trigger to test)
4. Check the run logs to verify everything works

---

## Usage

### Local Testing

```bash
# Install dependencies
pip install -r requirements.txt
python -m playwright install --only-shell chromium

# Dry run (no email)
python run.py --dry-run

# Show ATS classification stats
python run.py --classify-only

# Full run with email
python run.py

# Rebuild companies list from GitHub repos
python run.py --build
```

`--dry-run` never writes the seen-state file, so previewing a run cannot suppress the next email alert.

### Scraper Tuning

The defaults are safe for GitHub-hosted runners. On a smaller self-hosted runner, lower these environment variables instead of changing source code:

```bash
SCRAPER_API_WORKERS=12       # Public ATS requests
SCRAPER_STATIC_WORKERS=24    # Static career-page requests
SCRAPER_BROWSER_WORKERS=6    # Concurrent pages in the one shared Chromium browser
```

Set `SCRAPER_DISABLE_BROWSER=true` for a fast, static-only diagnostic run.

### GitHub Actions

- **Automatic**: Runs daily at the cron time you set
- **Manual**: Go to Actions → Daily Job Scan → Run workflow
- **Dry run from Actions**: Check the "Dry run" checkbox

---

## Adding More Companies

### Quick way: Edit `build_companies.py`

Add entries to the `CURATED` list:

```python
CURATED = [
    # ... existing entries ...
    ("Company Name", "greenhouse", "company-slug", "curated"),
    ("Another Co", "lever", "anotherco", "curated"),
]
```

Then run:
```bash
python build_companies.py
git add companies.json build_companies.py
git commit -m "Add more companies"
git push
```

### How to find a company's ATS:

1. Google: `"company name" careers site:boards.greenhouse.io OR site:jobs.lever.co OR site:ashbyhq.com`
2. Visit their careers page and check the URL
3. If it matches a known ATS pattern, add it to `CURATED`

### Re-discover ATS for existing companies:

```bash
python discover_ats.py
```

This probes each company to find if they use Greenhouse/Lever/Ashby. Takes ~10 minutes for 100 companies.

---

## How State Works (Deduplication)

- `seen_jobs.json` tracks every job URL we've already alerted you about (with tracking parameters normalized)
- It's committed to the repo so GitHub Actions can read/write it across runs
- Entries older than 30 days are automatically pruned
- **Don't delete this file** — if you do, you'll get re-alerted on every job

---

## Cost: $0/month

| Component | Cost | Free Tier |
|-----------|------|-----------|
| GitHub Actions | $0 | 2,000 min/month free; usage depends on custom career pages |
| Resend | $0 | 3,000 emails/month |
| Gmail SMTP | $0 | ~500 emails/day |
| SendGrid | $0 | 100 emails/day |
| Playwright | $0 | Open source |
| Job board APIs | $0 | Public, no auth needed |

---

## Troubleshooting

**No email received?**
- Check the Actions run log for errors
- Verify your API key secret is set correctly
- For Resend: check your email in the Resend dashboard → Emails
- For Gmail: make sure App Password is correct and 2FA is enabled

**Too many/false positive results?**
- Edit `KEYWORDS_EXCLUDE` in `filter.py` to add more filters
- Make `KEYWORDS_INCLUDE` more specific

**Too few results?**
- Remove items from `KEYWORDS_EXCLUDE` (e.g., remove "senior" if you want senior roles)
- Add more keywords to `KEYWORDS_INCLUDE`
- Run `python run.py --classify-only` to verify companies are classified correctly

**GitHub Actions timing out?**
- The scanner has a 60-minute timeout. First check the custom-source summary in the log.
- Lower `SCRAPER_BROWSER_WORKERS` only on constrained self-hosted runners; on GitHub-hosted runners, first rebuild the company list to remove stale sources.

**Rate limited by an ATS?**
- Public ATS calls retry transient 429/5xx responses with backoff.
- If a provider still rate-limits you, lower `SCRAPER_API_WORKERS` for the next run.

---

## Current Stats

Run `python run.py --classify-only` to see live stats.

As of initial build:
- **160 companies** total
- **112 API-scrapable** (Greenhouse: 80, Lever: 24, Ashby: 7, SmartRecruiters: 1)
- **48 custom ATS** (Playwright-based)

---

## License

MIT
