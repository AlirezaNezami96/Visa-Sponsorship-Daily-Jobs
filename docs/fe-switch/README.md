# VisaLane — Frontend Live Switch Checklist & Architecture Guide

This guide documents the exact process to transition the VisaLane frontend (`AlirezaNezami96/global-job-pass`) from mock mode to live Supabase backend operations.

---

## 1. Environment Configuration

In the frontend repository (`global-job-pass`), create or update `.env.production` (and `.env.local` for development):

```bash
# Supabase API Endpoint & Public Anonymous Key
VITE_SUPABASE_URL=https://<your-project-ref>.supabase.co
VITE_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# Mock Kill-Switch (Must default to false in production builds)
VITE_USE_MOCKS=false
```

> [!IMPORTANT]
> The `SUPABASE_SERVICE_ROLE_KEY` is **server-only** and must **NEVER** be included in frontend code or environment variables. Row-Level Security (RLS) policies enforce user data isolation.

---

## 2. Replacing the Frontend Adapter

The frontend uses an abstraction layer at `src/services/api.ts`. To go live:

1. Copy [`docs/fe-switch/adapter-live.ts`](file:///Users/alirezanezami/Documents/Visa-Sponsorship-Daily-Jobs/docs/fe-switch/adapter-live.ts) to `global-job-pass/src/services/api.ts` (or apply as a patch).
2. Install the Supabase JS client if not already present:
   ```bash
   npm install @supabase/supabase-js
   ```

### 1:1 Adapter Method Mapping

| Frontend Function | Backend Target | Description |
|---|---|---|
| `searchJobs(params)` | `GET /rest/v1/jobs` | Catalog query with filters, pagination, and joins (`companies`, `job_people`). |
| `getJob(id)` | `GET /rest/v1/jobs?id=eq.<id>` | Single job details with company and verified sponsorship metadata. |
| `getUserProfile()` | `GET /rest/v1/profiles?id=eq.<uid>` | Authenticated user profile with format preferences and skills. |
| `updateUserProfile(data)` | `PATCH /rest/v1/profiles?id=eq.<uid>` | Update user profile snapshot. |
| `uploadAndParseResume(file)` | `PUT storage/resumes/<uid>/...` + `POST /functions/v1/parse-resume` | Uploads resume and extracts structured data. |
| `generateTailoredResume(args)` | `POST /functions/v1/generate-tailored-resume` | Tailors resume to job; returns structured data and signed PDF preview URL. |
| `generateCoverLetter(args)` | `POST /functions/v1/generate-cover-letter` | Generates 250–400 word grounded cover letter with signed PDF preview URL. |
| `generateOutreachMessages(args)` | `POST /functions/v1/generate-outreach-messages` | Generates LinkedIn (≤300 chars) & email outreach messages. |
| `completeApplication(args)` | `POST /functions/v1/complete-application` | Marks application as complete, updates job status, and tracks metrics. |
| `getUsageLimits()` | `GET /functions/v1/usage-limits` | Fetches daily quotas and remaining credits. |
| `saveJob(jobId)` / `getSavedJobs()` | PostgREST CRUD on `saved_jobs` | User bookmarks. |
| `createAlert(data)` / `getAlerts()` | PostgREST CRUD on `alerts` | User search alerts and notifications. |
| `submitFeedback(data)` | `POST /functions/v1/feedback` | User feedback submissions. |

---

## 3. Key Frontend Behaviors & Patterns

### 3.1 Resume Upload & Parsing
1. Plain-text/markdown resumes can be uploaded directly to `resumes/{uid}/{filename}` in Supabase Storage.
2. PDF resumes should extract text in the browser (or send text extracted via standard PDF parsers) and call `/functions/v1/parse-resume`.
3. The returned `parsed_data` is saved to the user's `resumes` row and profile.

### 3.2 PDF Preview & Download
- The backend engine deterministically renders ATS-safe PDFs with bundled OFL fonts (Inter & Poppins).
- The Edge Functions return a 1-hour signed URL in `pdf_url`.
- Frontend preview: `<iframe src={pdf_url} className="w-full h-[600px]" />`.
- Frontend download: `<a href={pdf_url} download="Tailored_Resume.pdf">Download PDF</a>`.

### 3.3 Quota Gating & Upgrade Modal (402 Payment Required)
- When a user exhausts daily credits, Edge Functions return HTTP status `402` with `{ error: { code: "quota_exceeded", message: "..." } }`.
- The adapter intercepts `402` and opens the subscription upgrade modal.

### 3.4 Network Resilience & Error Handling
- Every network call in `adapter-live.ts` retries once automatically on network/5xx drops.
- User-facing error messages are typed and surfaced via toasts.

---

## 4. End-to-End Acceptance Test

Run the Playwright test suite to verify the complete user journey against the live backend:

```bash
# Run the E2E verification test
npx playwright test docs/fe-switch/apply-flow.spec.ts
```

The test validates:
1. User registration / login via Supabase Auth.
2. Resume upload and structured parsing.
3. Job selection and tailored resume generation + PDF preview rendering.
4. Cover letter & outreach message generation.
5. Application submission (`complete-application`).
6. Verification that "Applied" status appears in the user's **My Jobs** dashboard.
