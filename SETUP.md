# Instant Telegram Relay Setup Guide (Cloudflare Worker)

This guide walks you through deploying the Cloudflare Worker relay to instantly trigger the GitHub Actions publishing workflow whenever you approve or reject a draft on Telegram.

---

## 1. Deploy the Cloudflare Worker

Open your terminal in the project root:

```bash
cd worker
npm install
npx wrangler deploy
```

Once deployment completes, Wrangler will print your live Worker URL (e.g., `https://telegram-relay.<subdomain>.workers.dev`).

---

## 2. Set Cloudflare Worker Secrets

Run each command below to securely add required secrets to your Cloudflare Worker:

```bash
# 1. Telegram Bot Token
npx wrangler secret put TELEGRAM_BOT_TOKEN
# Paste: 8738296989:AAE4pj_GT34SFxdek2ffavymT7TFync-D5w

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

## 3. Register Telegram Webhook

Replace `<WORKER_URL>` with your live Worker URL and `<YOUR_TELEGRAM_WEBHOOK_SECRET>` with the secret token you set above:

```bash
curl -X POST "https://api.telegram.org/bot8738296989:AAE4pj_GT34SFxdek2ffavymT7TFync-D5w/setWebhook" \
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

Now, clicking **Approve**, **Reject**, or **Regenerate** buttons in Telegram will instantly trigger the GitHub Actions workflow in real-time!
