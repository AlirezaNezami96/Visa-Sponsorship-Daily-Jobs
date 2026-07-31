# Visa Job Scraper

Daily job scraper for 100+ visa-sponsoring companies. Runs on **GitHub Actions** (free), no paid services needed.

**What it does:** Every day at a time you choose, it scans 160+ companies' job boards, filters for roles matching your keywords (e.g., "mobile", "android", "software engineer"), deduplicates against previously seen jobs, and emails you only the new matches.

**How it works:** ~70% of the companies use Greenhouse, Lever, Ashby, or SmartRecruiters — all have **free public JSON APIs**, so there's no HTML scraping or anti-bot issues for the majority. The remaining ~30% use Playwright (headless browser) as a fallback.

---

## Architecture

```
companies.json ──► run.py (orchestrator)
                        │
          ┌─────────────┼──────────────┐
          ▼             ▼              ▼
   API Fetchers   Playwright      filter.py
   (Greenhouse,   Fetcher        (keyword match
    Lever, Ashby,   (custom/      + dedup)
    SmartRecruiters)  Workday)       │
                                        ▼
                                  email_sender.py
                                  (Resend/SendGrid/
                                   Gmail SMTP)
```

## Project Files

| File | Purpose |
|------|----------|
| `run.py` | Main orchestrator. Run this. |
| `build_companies.py` | Builds `companies.json` from GitHub repos + curated list |
| `classify.py` | ATS detection from URLs |
| `fetchers.py` | JSON API fetchers for Greenhouse, Lever, Ashby, SmartRecruiters, Personio |
| `fetcher_custom.py` | Playwright-based fetcher for Workday and custom career pages |
| `filter.py` | Keyword matching + dedup (edit `KEYWORDS_INCLUDE` here) |
| `email_sender.py` | Email dispatch via Resend, SendGrid, or Gmail SMTP |
| `discover_ats.py` | Optional: probes companies to auto-discover their ATS |
| `companies.json` | Company list with ATS classification |
| `seen_jobs.json` | State store for deduplication (committed to repo) |
| `.github/workflows/daily-jobs.yml` | GitHub Actions cron job |

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
playwright install chromium

# Dry run (no email)
python run.py --dry-run

# Show ATS classification stats
python run.py --classify-only

# Full run with email
python run.py

# Rebuild companies list from GitHub repos
python run.py --build
```

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

- `seen_jobs.json` tracks every job URL we've already alerted you about
- It's committed to the repo so GitHub Actions can read/write it across runs
- Entries older than 30 days are automatically pruned
- **Don't delete this file** — if you do, you'll get re-alerted on every job

---

## Cost: $0/month

| Component | Cost | Free Tier |
|-----------|------|-----------|
| GitHub Actions | $0 | 2,000 min/month free (this uses ~10-15 min/day) |
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
- The 30-minute timeout is generous. If it hits this, reduce the company list
- Custom/Playwright companies are slow; consider removing some

**Rate limited by an ATS?**
- The script already includes a 0.5s delay between requests
- If you still get 429s, increase `REQUEST_DELAY` in `run.py`

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