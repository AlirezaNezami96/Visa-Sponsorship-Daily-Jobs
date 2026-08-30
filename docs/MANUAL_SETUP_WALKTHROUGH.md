# VisaLane Phase 4 — Manual Setup & Integration Walkthrough

This guide provides step-by-step instructions for acquiring credentials, configuring OAuth providers, provisioning AI keys, setting up the Google Doc resume template, and configuring environment secrets for both local development and Supabase production deployment.

---

## 1. Google OAuth 2.0 Credentials Setup

### Step 1.1: Create or Select a Google Cloud Project
1. Navigate to the [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project dropdown in the top bar and select **New Project**.
3. Name the project `VisaLane-Production` (or your preferred name) and click **Create**.

### Step 1.2: Configure OAuth Consent Screen
1. In the left sidebar, navigate to **APIs & Services** > **OAuth consent screen**.
2. Select **External** user type and click **Create**.
3. Fill in the required fields:
   - **App name**: `VisaLane`
   - **User support email**: `support@visalane.online`
   - **Developer contact information**: your admin email.
4. On the **Scopes** page, click **Add or Remove Scopes** and select:
   - `.../auth/userinfo.email`
   - `.../auth/userinfo.profile`
   - `openid`
5. Save and continue.

### Step 1.3: Create OAuth 2.0 Client Credentials
1. Navigate to **APIs & Services** > **Credentials**.
2. Click **+ Create Credentials** > **OAuth client ID**.
3. Select **Application type**: `Web application`.
4. Name: `VisaLane Web Client`.
5. Under **Authorized JavaScript origins**, add:
   - `https://visalane.online`
   - `http://localhost:3000` (for local development)
6. Under **Authorized redirect URIs**, add:
   - `https://<YOUR_SUPABASE_PROJECT_REF>.supabase.co/functions/v1/oauth-callback`
   - `http://localhost:54321/functions/v1/oauth-callback` (for local testing)
7. Click **Create** and securely save:
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`

---

## 2. GitHub OAuth Application Setup

### Step 2.1: Register a New OAuth App
1. Go to [GitHub Developer Settings](https://github.com/settings/developers).
2. Click **OAuth Apps** in the left sidebar, then click **New OAuth App**.
3. Enter application details:
   - **Application name**: `VisaLane`
   - **Homepage URL**: `https://visalane.online`
   - **Authorization callback URL**:
     `https://<YOUR_SUPABASE_PROJECT_REF>.supabase.co/functions/v1/oauth-callback`
4. Click **Register application**.

### Step 2.2: Generate Client Secret
1. On the app summary page, copy the **Client ID** (`GITHUB_CLIENT_ID`).
2. Click **Generate a new client secret** and copy the **Client Secret** (`GITHUB_CLIENT_SECRET`).

---

## 3. AI Provider API Keys Setup

VisaLane uses a multi-tier fallback architecture (`Gemini -> Groq -> OpenRouter -> Local/Ollama`).

### Step 3.1: Google Gemini API Key
1. Visit [Google AI Studio](https://aistudio.google.com/).
2. Sign in with your Google account.
3. Click **Get API key** > **Create API key**.
4. Save the generated key as `GEMINI_API_KEY`.

### Step 3.2: Groq API Key (Ultra-Fast Inference & Fallback)
1. Visit [Groq Console](https://console.groq.com/).
2. Sign up or log in.
3. Navigate to **API Keys** in the sidebar.
4. Click **Create API Key**, name it `VisaLane-Backend`, and copy the secret key as `GROQ_API_KEY`.

### Step 3.3: OpenRouter API Key (Multi-Model Resilience)
1. Visit [OpenRouter](https://openrouter.ai/).
2. Create an account and go to **Keys** (`openrouter.ai/keys`).
3. Click **Create Key**, give it an identifier, and copy the secret as `OPENROUTER_API_KEY`.

---

## 4. Google Doc Resume Template Setup

VisaLane supports the **Professional Format** utilizing a Google Doc template layout.

### Step 4.1: Create or Clone Template Doc
1. Open Google Docs and create a clean ATS-friendly resume template.
2. Structure the document with standard section headers:
   - `SUMMARY`
   - `SKILLS`
   - `EXPERIENCE`
   - `EDUCATION`
   - `PROJECTS`
   - `CERTIFICATIONS`
   - `LANGUAGES`
3. Click **Share** in the top right:
   - Set General access to: **Anyone with the link can view** (or share with your Google Cloud Service Account).
4. Copy the document ID from the URL:
   `https://docs.google.com/document/d/<TEMPLATE_ID>/edit`
5. Set `GOOGLE_DOC_TEMPLATE_ID=<TEMPLATE_ID>`.

---

## 5. Setting Supabase Secrets & Environment Variables

### Step 5.1: Set Supabase Edge Function Secrets
Run the following CLI commands to configure your Supabase deployment:

```bash
supabase secrets set \
  SUPABASE_URL="https://<YOUR_PROJECT_REF>.supabase.co" \
  SUPABASE_SERVICE_ROLE_KEY="<YOUR_SUPABASE_SERVICE_ROLE_KEY>" \
  FRONTEND_URL="https://visalane.online" \
  GOOGLE_CLIENT_ID="<YOUR_GOOGLE_CLIENT_ID>" \
  GOOGLE_CLIENT_SECRET="<YOUR_GOOGLE_CLIENT_SECRET>" \
  GITHUB_CLIENT_ID="<YOUR_GITHUB_CLIENT_ID>" \
  GITHUB_CLIENT_SECRET="<YOUR_GITHUB_CLIENT_SECRET>" \
  GEMINI_API_KEY="<YOUR_GEMINI_API_KEY>" \
  GROQ_API_KEY="<YOUR_GROQ_API_KEY>" \
  OPENROUTER_API_KEY="<YOUR_OPENROUTER_API_KEY>" \
  GOOGLE_DOC_TEMPLATE_ID="<YOUR_GOOGLE_DOC_TEMPLATE_ID>"
```

### Step 5.2: Local Python Backend `.env` Configuration
Create or update `.env` in the repository root:

```ini
# Supabase Database & Auth
SUPABASE_URL=https://<YOUR_PROJECT_REF>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<YOUR_SUPABASE_SERVICE_ROLE_KEY>
FRONTEND_URL=https://visalane.online

# OAuth Providers
GOOGLE_CLIENT_ID=<YOUR_GOOGLE_CLIENT_ID>
GOOGLE_CLIENT_SECRET=<YOUR_GOOGLE_CLIENT_SECRET>
GITHUB_CLIENT_ID=<YOUR_GITHUB_CLIENT_ID>
GITHUB_CLIENT_SECRET=<YOUR_GITHUB_CLIENT_SECRET>

# AI Inference Keys
GEMINI_API_KEY=<YOUR_GEMINI_API_KEY>
GROQ_API_KEY=<YOUR_GROQ_API_KEY>
OPENROUTER_API_KEY=<YOUR_OPENROUTER_API_KEY>

# Resume Templates
GOOGLE_DOC_TEMPLATE_ID=<YOUR_GOOGLE_DOC_TEMPLATE_ID>
```

---

## 6. Supabase Edge Functions Catalog

| Function Name | Method | Auth Required | Description |
|---|---|---|---|
| `oauth-initiate` | GET/POST | No | Generates Google / GitHub OAuth authorization URL with signed CSRF state |
| `oauth-callback` | GET/POST | No | Exchanges OAuth code, verifies HMAC state, syncs user profile in DB |
| `oauth-sync` | POST | Yes | Syncs external OAuth profile metadata for logged-in user |
| `parse-resume` | POST | Yes | Extracts structured JSON & sections from resume text or storage path |
| `search-jobs` | GET | Optional | Cursor & offset job search with filtering, caching, and match scoring |
| `generate-tailored-resume` | POST | Yes | Generates tailored resume (professional / own format) with ATS comparison |
| `generate-cover-letter` | POST | Yes | Generates 250–400 word personalized cover letter with company hook |
| `generate-outreach-messages` | POST | Yes | Generates 4 persona-specific outreach messages (LinkedIn note, InMail, cold email, follow-up) |
| `find-contacts` | POST | Yes | Enriches job with recruiters, hiring managers, and 4 fallback steps |
| `extract-job-skills` | POST | Yes / Service | Rule + AI skill extraction for unindexed jobs |
| `usage-limits` | GET | Yes | Checks current daily usage and remaining plan quotas |
| `complete-application` | POST | Yes | Auto-fill assistance / application logging |
| `process-new-jobs` | POST | Service | Pipeline webhook ingestion and alert triggering |
| `feedback` | POST | Yes | User feedback submissions and quality ratings |

---

## 7. Pre-Flight Verification & Deployment Checklist

Run all verification suites locally before deployment:

```bash
# 1. Run Python backend pytest suite (730+ tests)
pytest

# 2. Run Supabase Edge Function Vitest suite (80+ tests)
npx vitest run

# 3. Deploy all Supabase Edge Functions
supabase functions deploy oauth-initiate
supabase functions deploy oauth-callback
supabase functions deploy oauth-sync
supabase functions deploy parse-resume
supabase functions deploy search-jobs
supabase functions deploy generate-tailored-resume
supabase functions deploy generate-cover-letter
supabase functions deploy generate-outreach-messages
supabase functions deploy find-contacts
supabase functions deploy extract-job-skills
supabase functions deploy usage-limits
supabase functions deploy complete-application
supabase functions deploy process-new-jobs
supabase functions deploy feedback
```
