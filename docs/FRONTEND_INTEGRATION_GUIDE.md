# VisaLane Phase 4 — Frontend API Integration & Manual Setup Guide

This document is the single source of truth for connecting the VisaLane Frontend with the Phase 4 Backend and Supabase Edge Functions.

---

## Part 1: What You Need to Do Manually (Admin Checklist)

You only need to complete these **3 simple steps** once:

### 1. How to Get `YOUR_SUPABASE_PROJECT_REF` and `YOUR_SERVICE_ROLE_KEY`

1. Log in to [Supabase Dashboard](https://supabase.com/dashboard).
2. Click on your project.
3. Look at your browser URL bar:
   `https://supabase.com/dashboard/project/<PROJECT_REF_IS_HERE>`
   *(For example, if the URL is `https://supabase.com/dashboard/project/abcxyz12345`, your Project Ref is `abcxyz12345`)*.
4. Go to **Project Settings** (⚙️ bottom left) > **API**:
   - **Project URL**: `https://<PROJECT_REF>.supabase.co`
   - **Project Ref**: Found under Reference ID (e.g. `abcxyz12345`)
   - **Backend Secret Key (`SUPABASE_SERVICE_ROLE_KEY`)**: 
     - If using the modern **Publishable and secret API keys** tab: copy the **Secret key** (`sb_sec_...`).
     - If using the **Legacy API keys** tab: copy the **`service_role`** key.
     - *(Both work identically — they grant administrative backend access. Never expose this key on the frontend!)*
   - **Frontend Public Key (`NEXT_PUBLIC_SUPABASE_ANON_KEY`)**:
     - Use the **Publishable key** (`sb_pub_...`) or the legacy **`anon`** key in your frontend app.

---

### 2. Get Your OAuth Credentials
* **Google OAuth**:
  1. Go to [Google Cloud Console > Credentials](https://console.cloud.google.com/apis/credentials).
  2. Create **OAuth 2.0 Client ID** (Web application).
  3. Set Authorized Redirect URI: `https://<YOUR_SUPABASE_PROJECT_REF>.supabase.co/functions/v1/oauth-callback`
  4. Note `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
* **GitHub OAuth**:
  1. Go to [GitHub > Developer Settings > OAuth Apps](https://github.com/settings/developers).
  2. Create **New OAuth App**.
  3. Set Callback URL: `https://<YOUR_SUPABASE_PROJECT_REF>.supabase.co/functions/v1/oauth-callback`
  4. Note `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`.

---

### 3. Get Your AI Keys (Multi-Account Quota Rotation Supported!)

**Yes! You can add 2 or 3 Gemini API keys from different Google accounts.**

If Account 1 hits the free daily quota limit (`429 Too Many Requests`), the backend automatically tries Account 2, then Account 3, and then falls back to Groq / OpenRouter.

1. **Google Gemini Keys**:
   - Sign into [Google AI Studio](https://aistudio.google.com/) with Google Account 1 $\to$ Create API Key (`AIza...`).
   - Sign into [Google AI Studio](https://aistudio.google.com/) with Google Account 2 $\to$ Create API Key (`AIza...`).
   - Sign into [Google AI Studio](https://aistudio.google.com/) with Google Account 3 $\to$ Create API Key (`AIza...`).
   - You can supply them as a comma-separated list: `GEMINI_API_KEY="key1,key2,key3"` or `GEMINI_API_KEYS="key1,key2,key3"`.

2. **Optional Extra Resilience (Free Fallback Models)**:
   - [Groq Console](https://console.groq.com/) (`GROQ_API_KEY`) $\to$ Ultra-fast Llama 3.3 70B fallback.
   - [OpenRouter](https://openrouter.ai/) (`OPENROUTER_API_KEY`) $\to$ Multi-model fallback.

---

### 4. Set Supabase Secrets & Deploy Functions
Run this single command in your terminal:

```bash
supabase secrets set \
  SUPABASE_URL="https://<YOUR_PROJECT_REF>.supabase.co" \
  SUPABASE_SERVICE_ROLE_KEY="<YOUR_SERVICE_ROLE_KEY>" \
  FRONTEND_URL="https://visalane.online" \
  GOOGLE_CLIENT_ID="<YOUR_GOOGLE_CLIENT_ID>" \
  GOOGLE_CLIENT_SECRET="<YOUR_GOOGLE_CLIENT_SECRET>" \
  GITHUB_CLIENT_ID="<YOUR_GITHUB_CLIENT_ID>" \
  GITHUB_CLIENT_SECRET="<YOUR_GITHUB_CLIENT_SECRET>" \
  GEMINI_API_KEY="<GEMINI_KEY_1>,<GEMINI_KEY_2>,<GEMINI_KEY_3>"

# Deploy all Edge Functions:
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
```

---

## Part 2: Resume PDF Text Extraction on the Frontend

Extracting text directly in the browser ensures fast uploads with no binary parsing errors on the server.

### 1. Install `pdfjs-dist`
```bash
npm install pdfjs-dist
```

### 2. Create the Client-Side Extractor Utility (`lib/pdfExtractor.ts`)

```typescript
import * as pdfjsLib from "pdfjs-dist";

// Set worker path (use unpkg or local public assets)
pdfjsLib.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjsLib.version}/pdf.worker.min.mjs`;

export async function extractTextFromPDF(file: File): Promise<string> {
  const arrayBuffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
  let fullText = "";

  for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
    const page = await pdf.getPage(pageNum);
    const content = await page.getTextContent();
    const pageText = content.items
      .map((item: any) => item.str)
      .join(" ");
    fullText += pageText + "\n\n";
  }

  return fullText.trim();
}
```

### 3. Frontend Upload Flow (Example React Component)

```typescript
import { extractTextFromPDF } from "@/lib/pdfExtractor";
import { supabase } from "@/lib/supabaseClient";

export async function handleResumeUpload(file: File) {
  // 1. Extract plain text on client
  const resumeText = await extractTextFromPDF(file);

  if (resumeText.length < 50) {
    throw new Error("Could not extract readable text. Please upload a standard text PDF.");
  }

  // 2. Get user session JWT
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  // 3. Send text to parse-resume Edge Function
  const response = await fetch(
    `${process.env.NEXT_PUBLIC_SUPABASE_URL}/functions/v1/parse-resume`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        resume_text: resumeText,
      }),
    }
  );

  const result = await response.json();
  // result contains { output: { full_name, email, skills, experience, ... }, sections_detected, is_fresher, confidence }
  return result;
}
```

---

## Part 3: Full API Integration Reference for Frontend

Base URL: `https://<YOUR_PROJECT_REF>.supabase.co/functions/v1`

---

### 1. Resume Parsing & Profile Sync
* **Endpoint**: `POST /parse-resume`
* **Headers**: `Authorization: Bearer <USER_JWT>`
* **Request Body**:
```json
{
  "resume_text": "Alireza Nezami\nSenior Backend Engineer\nSkills: Python, TypeScript, Supabase, Postgres..."
}
```
* **Response (200 OK)**:
```json
{
  "output": {
    "full_name": "Alireza Nezami",
    "email": "alireza@example.com",
    "phone": "+1 555-0199",
    "location": "Berlin, Germany",
    "job_titles": ["Senior Backend Engineer", "Lead Developer"],
    "skills": ["Python", "TypeScript", "PostgreSQL", "Supabase", "Docker", "FastAPI"],
    "summary": "Senior backend engineer with 8+ years experience building scalable systems.",
    "experience": [
      {
        "company": "Tech Corp",
        "title": "Senior Engineer",
        "start": "2021",
        "end": "Present",
        "highlights": ["Scaled backend from 10k to 500k DAU", "Optimized database queries by 40%"]
      }
    ],
    "education": [
      {
        "institution": "University of Technology",
        "degree": "B.S. Computer Science",
        "year": "2018"
      }
    ]
  },
  "sections_detected": ["summary", "skills", "experience", "education"],
  "is_fresher": false,
  "confidence": 0.9
}
```

---

### 2. Job Search with Match Scores & Filters
* **Endpoint**: `GET /search-jobs`
* **Query Parameters**:
  - `q`: Search query string (e.g. `python backend`)
  - `country`: Filter by country name
  - `work_mode`: `remote` | `hybrid` | `onsite`
  - `limit`: Number of jobs per page (default: `20`, max: `100`)
  - `cursor`: Base64 cursor for infinite scroll
  - `offset`: Numeric offset (alternative to cursor)
* **Headers**: `Authorization: Bearer <USER_JWT>` *(Optional: pass JWT to automatically get personalized match scores)*
* **Response (200 OK)**:
```json
{
  "jobs": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "title": "Senior Python Engineer",
      "company": "Spotify",
      "location_raw": "Stockholm, Sweden",
      "country": "Sweden",
      "work_mode": "hybrid",
      "skills": ["Python", "PostgreSQL", "Docker", "GCP"],
      "visa_sponsorship_verified": true,
      "apply_url": "https://jobs.spotify.com/...",
      "posted_at": "2026-08-29T10:00:00Z",
      "match_score": 92,
      "match_label": "great_match"
    }
  ],
  "next_cursor": "eyJwb3N0ZWRfYXQiOiIyMDI2LTA4LTI5VDEwOjAwOjAwWiIsImlkIjoiYTFhYSJ9",
  "has_more": true,
  "total_count": 1420
}
```

---

### 3. Generate Tailored Resume
* **Endpoint**: `POST /generate-tailored-resume`
* **Headers**: `Authorization: Bearer <USER_JWT>`
* **Request Body**:
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "format_type": "professional",
  "idempotency_key": "res_a1b2c3d4_v1"
}
```
*Note: `format_type` can be `"professional"` (standard ATS template) or `"own_format"` (mirrors candidate's existing layout).*
* **Response (200 OK)**:
```json
{
  "output": {
    "full_name": "Alireza Nezami",
    "title": "Senior Python Engineer",
    "summary": "Targeted summary highlighting Python and scalable backend architectures...",
    "skills": ["Python", "PostgreSQL", "Docker", "GCP", "FastAPI"],
    "experience": [...]
  },
  "ats_score_before": 68,
  "ats_score_after": 94,
  "format_type": "professional",
  "document_id": "doc_882910"
}
```

---

### 4. Generate Personalized Cover Letter
* **Endpoint**: `POST /generate-cover-letter`
* **Headers**: `Authorization: Bearer <USER_JWT>`
* **Request Body**:
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "company_hook": "admire Spotify's high-throughput audio streaming infrastructure",
  "idempotency_key": "cl_a1b2c3d4_v1"
}
```
* **Response (200 OK)**:
```json
{
  "cover_letter": "Dear Hiring Team at Spotify,\n\nI am writing to express my enthusiasm for the Senior Python Engineer role...",
  "word_count": 310,
  "status": "ready"
}
```

---

### 5. Generate Multi-Channel Outreach Messages
* **Endpoint**: `POST /generate-outreach-messages`
* **Headers**: `Authorization: Bearer <USER_JWT>`
* **Request Body**:
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "contact_name": "Sarah Connor",
  "contact_title": "Technical Recruiter"
}
```
* **Response (200 OK)**:
```json
{
  "linkedin_connection_note": "Hi Sarah, I saw the Senior Python Engineer opening at Spotify and would love to connect! My background in scalable distributed systems aligns closely with your team's mission.",
  "linkedin_inmail": "Hi Sarah,\n\nI noticed the Senior Python Engineer role at Spotify and wanted to reach out directly...",
  "cold_email": "Subject: Senior Python Engineer Application - Alireza Nezami\n\nHi Sarah,\n\nI hope this email finds you well...",
  "follow_up_email": "Subject: Following up on Senior Python Engineer application\n\nHi Sarah,\n\nChecking in regarding my note from last week..."
}
```

---

### 6. Find Company Contacts & 4 Actionable Fallback Steps
* **Endpoint**: `POST /find-contacts`
* **Headers**: `Authorization: Bearer <USER_JWT>`
* **Request Body**:
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```
* **Response (200 OK)**:
```json
{
  "contacts": [
    {
      "id": "c1",
      "name": "Sarah Connor",
      "title": "Technical Recruiter",
      "email": "sarah.connor@spotify.com",
      "email_status": "verified",
      "email_confidence": "high",
      "confidence_score": 90
    }
  ],
  "count": 1,
  "search_links": {
    "recruiter_search": "https://www.linkedin.com/search/results/people/?keywords=Spotify%20recruiter",
    "hiring_manager_search": "https://www.linkedin.com/search/results/people/?keywords=Spotify%20Engineering%20Manager"
  },
  "fallback_instructions": [
    {
      "step": 1,
      "title": "Search LinkedIn for Recruiters",
      "action_url": "https://www.linkedin.com/search/results/people/?keywords=Spotify%20recruiter",
      "action_label": "Find Recruiters at Spotify"
    },
    {
      "step": 2,
      "title": "Search for Hiring Manager",
      "action_url": "https://www.linkedin.com/search/results/people/?keywords=Spotify%20Engineering%20Manager",
      "action_label": "Find Engineering Managers"
    },
    {
      "step": 3,
      "title": "Check Original Job Posting",
      "action_url": "https://jobs.spotify.com/...",
      "action_label": "View Original Job Posting"
    },
    {
      "step": 4,
      "title": "Try General Department Mailboxes",
      "suggested_emails": ["careers@spotify.com", "talent@spotify.com", "jobs@spotify.com"],
      "action_label": "Copy Email Addresses"
    }
  ]
}
```

---

### 7. Usage Limits & Plan Quotas
* **Endpoint**: `GET /usage-limits`
* **Headers**: `Authorization: Bearer <USER_JWT>`
* **Response (200 OK)**:
```json
{
  "plan": "free",
  "limits": {
    "resume_generations_daily": 3,
    "cover_letters_daily": 5,
    "outreach_messages_daily": 5,
    "contact_lookups_daily": 10
  },
  "usage": {
    "resume_generations": 1,
    "cover_letters": 2,
    "outreach_messages": 0,
    "contact_lookups": 3
  },
  "remaining": {
    "resume_generations": 2,
    "cover_letters": 3,
    "outreach_messages": 5,
    "contact_lookups": 7
  }
}
```
