# Setup Guide

## 1. Junior AI Agentic Job-Board Scanner Setup

The Junior AI scanner (`run_junior_ai.py` / `.github/workflows/daily-junior-ai-jobs.yml`) scans international Indeed job boards for entry-level, junior, trainee, and associate AI/ML roles.

### Setting Secrets in GitHub Actions
Go to your GitHub repository → **Settings** → **Secrets and variables** → **Actions** and add:

1. **Email Secrets** (Same as main pipeline):
   - `RESEND_API_KEY` (or `GMAIL_APP_PASSWORD` / `SENDGRID_API_KEY`)
   - `EMAIL_TO`
   - `EMAIL_FROM` (optional, defaults to `onboarding@resend.dev`)
   - `EMAIL_PROVIDER` (defaults to `resend`)

2. **LLM Provider Secret (Optional / Recommended for Self-Healing Navigation)**:
   - `ANTHROPIC_API_KEY`: API key from Anthropic Console (defaults to `claude-3-5-haiku-20241022` for cheap, fast navigation).
   - *(Alternative)* `OPENAI_API_KEY`: API key from OpenAI Platform (`gpt-4o-mini`).

3. **Proxy / Anti-Bot Secrets (Optional)**:
   - `BROWSER_USE_API_KEY`: For browser-use cloud managed proxy & solver.
   - `BROWSERBASE_API_KEY`: For Stagehand/Browserbase remote browser sessions.
   - `PROXY_URL`: Residential / datacenter HTTP(S) proxy (e.g. `http://user:pass@proxy.example.com:8080`).

### Customizing Target Countries and Search Queries
Edit `jobboard_config.json` in the root directory:
```json
{
  "active_countries": [
    "USA",
    "UK",
    "Canada",
    "Germany",
    "Netherlands",
    "Ireland"
  ],
  "search_queries": [
    "Junior AI Engineer",
    "Junior Machine Learning Engineer",
    "Entry Level AI Engineer",
    "Graduate Machine Learning"
  ],
  "max_results_per_query": 15,
  "request_delay_seconds": 2.0
}
```

---

## 2. Instant Telegram Relay Setup Guide (Cloudflare Worker)

This guide walks you through deploying the Cloudflare Worker relay to instantly trigger the GitHub Actions publishing workflow whenever you approve or reject a draft on Telegram.

### 1. Deploy the Cloudflare Worker

Open your terminal in the project root:

```bash
cd worker
npm install
npx wrangler deploy
```

Once deployment completes, Wrangler will print your live Worker URL (e.g., `https://telegram-relay.<subdomain>.workers.dev`).

---

### 2. Set Cloudflare Worker Secrets

Run each command below to securely add required secrets to your Cloudflare Worker:

```bash
# 1. Telegram Bot Token
npx wrangler secret put TELEGRAM_BOT_TOKEN
# Paste your token

# 2. Telegram Webhook Secret Token (a random secure string, e.g. my_secret_token_9988)
npx wrangler secret put TELEGRAM_WEBHOOK_SECRET
# Paste your generated secret string

# 3. Authorized Telegram User ID
npx wrangler secret put TELEGRAM_AUTHORIZED_USER_ID
# Paste: 444556030

# 4. GitHub Personal Access Token (Needs repo / Contents: Read & Write permissions)
npx wrangler secret put GH_PAT
# Paste your GitHub PAT token

# 5. GitHub Repository Owner
npx wrangler secret put GH_OWNER
# Paste: AlirezaNezami96

# 6. GitHub Repository Name
npx wrangler secret put GH_REPO
# Paste: Visa-Sponsorship-Daily-Jobs
```

---

### 3. Register Telegram Webhook

Replace `<WORKER_URL>` with your live Worker URL and `<YOUR_TELEGRAM_WEBHOOK_SECRET>` with the secret token you set above:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -d "url=<WORKER_URL>" \
  -d "secret_token=<YOUR_TELEGRAM_WEBHOOK_SECRET>"
```

### Verification Response

Telegram will return:
```json
{
  "ok": true,
  "result": true,
  "description": "Webhook was set"
}
```
