# VisaLane Database Schema & Table Reference

This document provides a visual table-by-table reference of the entire VisaLane Supabase PostgreSQL database architecture, including data types, constraints, defaults, relationships, and functional descriptions.

---

## 1. Core Job Discovery & Pipeline Tables

### 1.1 `public.jobs`
*Primary repository of scraped, verified, and active job postings.*

| Column | Type | Constraints | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY` | `gen_random_uuid()` | Unique identifier for the job posting |
| `company_id` | `UUID` | `REFERENCES companies(id) ON DELETE SET NULL` | `NULL` | Associated company record |
| `source_name` | `TEXT` | `NOT NULL` | — | Scraper source (e.g. `greenhouse`, `lever`, `adzuna`, `workable`) |
| `source_url` | `TEXT` | `NOT NULL` | — | Original job URL from the source |
| `canonical_url_hash` | `TEXT` | `UNIQUE NOT NULL` | — | SHA-256 hash of normalized canonical URL for deduplication |
| `fingerprint` | `TEXT` | — | `NULL` | Hash of `(company, title, location)` for cross-source deduplication |
| `title` | `TEXT` | `NOT NULL` | — | Job title (e.g. `Senior Machine Learning Engineer`) |
| `location_raw` | `TEXT` | — | `NULL` | Raw unparsed location string (e.g. `Berlin, Germany / Remote`) |
| `city` | `TEXT` | — | `NULL` | Normalized city name |
| `country` | `TEXT` | — | `NULL` | Full country name (e.g. `Germany`) |
| `country_code` | `TEXT` | — | `NULL` | ISO 2-letter country code (e.g. `DE`, `GB`, `NL`) |
| `work_mode` | `TEXT` | — | `NULL` | Work mode: `remote_worldwide`, `remote_in_country`, `hybrid`, `onsite` |
| `contract_type` | `TEXT` | — | `NULL` | Contract type: `full_time`, `part_time`, `contract`, `internship`, `b2b` |
| `salary_raw` | `TEXT` | — | `NULL` | Unparsed salary text (e.g. `€75,000 - €95,000 / year`) |
| `salary_min` | `INTEGER` | — | `NULL` | Minimum annual base salary |
| `salary_max` | `INTEGER` | — | `NULL` | Maximum annual base salary |
| `salary_currency` | `TEXT` | — | `NULL` | 3-letter currency code (e.g. `EUR`, `GBP`, `USD`, `CHF`) |
| `description_text` | `TEXT` | — | `NULL` | Clean plain text job description |
| `description_html` | `TEXT` | — | `NULL` | Formatted HTML description if available |
| `requirements` | `TEXT[]` | — | `NULL` | Extracted bullet points of job requirements |
| `visa_sponsorship_confidence` | `INTEGER` | `CHECK (0-100)` | `NULL` | Visa sponsorship verification score (0 to 100) |
| `visa_sponsorship_verified` | `BOOLEAN` | `NOT NULL` | `FALSE` | `TRUE` if employer is confirmed licensed sponsor |
| `visa_types` | `TEXT[]` | — | `NULL` | Eligible visa categories (e.g. `["Skilled Worker Visa", "EU Blue Card"]`) |
| `apply_url` | `TEXT` | `NOT NULL` | — | Direct application link for candidates |
| `posted_at` | `TIMESTAMPTZ` | — | `NULL` | Date and time the job was published by employer |
| `expires_at` | `TIMESTAMPTZ` | — | `NULL` | Date after which job is marked expired |
| `status` | `TEXT` | `CHECK (active, expired, removed)` | `'active'` | Job lifecycle status |
| `is_new` | `BOOLEAN` | `NOT NULL` | `TRUE` | Flag indicating job has not yet been processed in digest/social |
| `processed_social` | `BOOLEAN` | `NOT NULL` | `FALSE` | Pipeline flag for social media syndication |
| `processed_alerts` | `BOOLEAN` | `NOT NULL` | `FALSE` | Pipeline flag for candidate notification alerts |
| `processed_enrichment` | `BOOLEAN` | `NOT NULL` | `FALSE` | Pipeline flag for AI metadata enrichment |
| `raw_payload` | `JSONB` | — | `NULL` | Raw JSON data from scraper |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Database record insertion timestamp |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Last modification timestamp (updated by trigger) |

---

### 1.2 `public.companies`
*Company profiles, verified sponsor status, and ATS endpoints.*

| Column | Type | Constraints | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY` | `gen_random_uuid()` | Unique company identifier |
| `name` | `TEXT` | `NOT NULL` | — | Company registered name (e.g. `Spotify`) |
| `website` | `TEXT` | — | `NULL` | Primary company website URL |
| `linkedin_url` | `TEXT` | — | `NULL` | Official LinkedIn company page URL |
| `logo_url` | `TEXT` | — | `NULL` | URL to company brand logo |
| `ats_type` | `TEXT` | — | `NULL` | ATS platform: `greenhouse`, `lever`, `ashby`, `workable`, etc. |
| `funding_info` | `JSONB` | — | `NULL` | Funding stage, last round, total capital raised, lead investors |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Record creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Record update timestamp |

---

### 1.3 `public.job_processing`
*Per-job pipeline state machine tracking processing stages and per-platform publishing status.*

| Column | Type | Constraints | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `job_id` | `UUID` | `PRIMARY KEY, REFERENCES jobs(id) ON DELETE CASCADE` | — | Target job being processed |
| `metadata_status` | `TEXT` | `NOT NULL` | `'pending'` | Stage 2 status: `pending`, `in_progress`, `done`, `failed` |
| `metadata_attempts` | `INTEGER` | `NOT NULL` | `0` | Retry counter for metadata enrichment |
| `metadata_last_error` | `TEXT` | — | `NULL` | Last error trace for Stage 2 |
| `metadata_done_at` | `TIMESTAMPTZ` | — | `NULL` | Completion timestamp for Stage 2 |
| `alerts_status` | `TEXT` | `NOT NULL` | `'pending'` | Stage 3 status: candidate alert notifications |
| `alerts_done_at` | `TIMESTAMPTZ` | — | `NULL` | Completion timestamp for Stage 3 |
| `image_status` | `TEXT` | `NOT NULL` | `'pending'` | Stage 4 status: branded social card rendering |
| `image_attempts` | `INTEGER` | `NOT NULL` | `0` | Retry counter for social card generation |
| `image_last_error` | `TEXT` | — | `NULL` | Last error trace for Stage 4 |
| `image_done_at` | `TIMESTAMPTZ` | — | `NULL` | Completion timestamp for Stage 4 |
| `post_text` | `TEXT` | — | `NULL` | Generated multi-platform social text snippet |
| `post_text_status` | `TEXT` | `NOT NULL` | `'pending'` | Stage 5 post text generation status |
| `telegram_status` | `TEXT` | `NOT NULL` | `'pending'` | Telegram channel publishing status |
| `telegram_at` | `TIMESTAMPTZ` | — | `NULL` | Timestamp Telegram post was published |
| `telegram_url` | `TEXT` | — | `NULL` | Direct link to Telegram message |
| `discord_status` | `TEXT` | `NOT NULL` | `'pending'` | Discord community publishing status |
| `discord_at` | `TIMESTAMPTZ` | — | `NULL` | Timestamp Discord message was sent |
| `discord_url` | `TEXT` | — | `NULL` | Direct link to Discord message |
| `linkedin_status` | `TEXT` | `NOT NULL` | `'pending'` | LinkedIn page publishing status |
| `linkedin_at` | `TIMESTAMPTZ` | — | `NULL` | Timestamp LinkedIn post was created |
| `linkedin_url` | `TEXT` | — | `NULL` | Direct link to LinkedIn post |
| `x_status` | `TEXT` | `NOT NULL` | `'pending'` | X / Twitter publishing status |
| `x_at` | `TIMESTAMPTZ` | — | `NULL` | Timestamp X post was published |
| `x_url` | `TEXT` | — | `NULL` | Direct link to X post |
| `bluesky_status` | `TEXT` | `NOT NULL` | `'pending'` | Bluesky syndication status |
| `bluesky_at` | `TIMESTAMPTZ` | — | `NULL` | Timestamp Bluesky post was published |
| `bluesky_url` | `TEXT` | — | `NULL` | Direct link to Bluesky post |
| `mastodon_status` | `TEXT` | `NOT NULL` | `'pending'` | Mastodon syndication status |
| `mastodon_at` | `TIMESTAMPTZ` | — | `NULL` | Timestamp Mastodon toot was posted |
| `mastodon_url` | `TEXT` | — | `NULL` | Direct link to Mastodon post |
| `updated_at` | `TIMESTAMPTZ` | — | `NOW()` | Timestamp of last status change |

---

### 1.4 `public.processing_quarantine`
*Dead-letter table capturing jobs that persistently fail pipeline stages.*

| Column | Type | Constraints | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY` | `gen_random_uuid()` | Unique quarantine record ID |
| `job_id` | `UUID` | `REFERENCES jobs(id) ON DELETE CASCADE` | — | Failed job reference |
| `stage` | `TEXT` | `NOT NULL` | — | Failed stage name (`metadata`, `image`, `publishing`, etc.) |
| `reason` | `TEXT` | `NOT NULL` | — | Failure error message or exception summary |
| `attempts` | `INTEGER` | `NOT NULL` | — | Number of retry attempts made before quarantine |
| `payload` | `JSONB` | — | `NULL` | Snapshot of job payload at time of failure |
| `created_at` | `TIMESTAMPTZ` | — | `NOW()` | Quarantine entry timestamp |
| `resolved_at` | `TIMESTAMPTZ` | — | `NULL` | Timestamp when admin retried or dismissed record |

---

### 1.5 `public.job_people`
*Discovered hiring team members, recruiters, and engineering managers for direct candidate outreach.*

| Column | Type | Constraints | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY` | `gen_random_uuid()` | Unique contact ID |
| `job_id` | `UUID` | `REFERENCES jobs(id) ON DELETE CASCADE` | — | Associated job posting |
| `name` | `TEXT` | `NOT NULL` | — | Full name of contact (e.g. `Maya Lindqvist`) |
| `title` | `TEXT` | — | `NULL` | Job title (e.g. `Talent Acquisition Lead`) |
| `email` | `TEXT` | — | `NULL` | Verified or inferred business email address |
| `email_status` | `TEXT` | — | `NULL` | Verification status (`verified`, `catch_all`, `unverified`) |
| `email_confidence` | `INTEGER` | — | `NULL` | Email delivery confidence percentage |
| `linkedin_url` | `TEXT` | — | `NULL` | Contact's personal LinkedIn profile URL |
| `confidence` | `FLOAT` | — | `0.0` | Overall relevance match score |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Record creation timestamp |

---

## 2. User Accounts, CRM & Application Tables

### 2.1 `public.profiles`
*Candidate profiles extending Supabase `auth.users`.*

| Column | Type | Constraints | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY, REFERENCES auth.users(id) ON DELETE CASCADE` | — | User auth ID |
| `email` | `TEXT` | `UNIQUE NOT NULL` | — | User primary email address |
| `full_name` | `TEXT` | — | `NULL` | Candidate full name |
| `job_titles` | `TEXT[]` | — | `NULL` | Desired job titles for matching |
| `about_me` | `TEXT` | — | `NULL` | Professional bio summary |
| `skills` | `TEXT[]` | — | `NULL` | Array of candidate skills |
| `links` | `JSONB` | — | `NULL` | Portfolio, GitHub, LinkedIn, and website links |
| `contact` | `JSONB` | — | `NULL` | Phone, location, and preferred contact channels |
| `resume_format_preference` | `TEXT` | `NOT NULL` | `'professional'` | Preferred format: `professional` or `own` |
| `remember_resume_format` | `BOOLEAN` | `NOT NULL` | `FALSE` | Persistent formatting preference flag |
| `profile_complete` | `BOOLEAN` | `NOT NULL` | `FALSE` | Onboarding completion flag |
| `subscription_plan` | `TEXT` | `NOT NULL` | `'free'` | Plan type: `free`, `pro_trial`, `pro` |
| `trial_started_at` | `TIMESTAMPTZ` | — | `NULL` | Pro trial start timestamp |
| `trial_ends_at` | `TIMESTAMPTZ` | — | `NULL` | Pro trial expiration timestamp |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Registration timestamp |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Last profile update timestamp |

---

### 2.2 `public.resumes`
*Uploaded source resumes and ATS parsing baselines.*

| Column | Type | Constraints | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY` | `gen_random_uuid()` | Unique resume ID |
| `user_id` | `UUID` | `REFERENCES profiles(id) ON DELETE CASCADE` | — | Owner profile ID |
| `file_path` | `TEXT` | `NOT NULL` | — | Path inside Supabase Storage `resumes` bucket |
| `file_name` | `TEXT` | `NOT NULL` | — | Original uploaded file name |
| `file_size` | `INTEGER` | — | `NULL` | File size in bytes |
| `raw_text` | `TEXT` | — | `NULL` | Extracted plain text content |
| `parsed_data` | `JSONB` | — | `NULL` | Structured JSON extracted from resume |
| `ats_baseline` | `JSONB` | — | `NULL` | ATS scoring baseline metrics |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Upload timestamp |

---

### 2.3 `public.generated_documents`
*AI-tailored resumes and cover letters saved in Storage.*

| Column | Type | Constraints | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY` | `gen_random_uuid()` | Unique document ID |
| `user_id` | `UUID` | `REFERENCES profiles(id) ON DELETE CASCADE` | — | Candidate ID |
| `job_id` | `UUID` | `REFERENCES jobs(id) ON DELETE CASCADE` | — | Target job for tailoring |
| `doc_type` | `TEXT` | `CHECK (resume, cover_letter)` | — | Document type |
| `format_type` | `TEXT` | — | `'professional'` | Formatting style (`professional` or `own`) |
| `storage_path` | `TEXT` | `NOT NULL` | — | File path in Storage `generated_docs` bucket |
| `ats_score` | `INTEGER` | `CHECK (0-100)` | `NULL` | Grounding and ATS match score |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Generation timestamp |

---

### 2.4 `public.applications`
*Candidate application Kanban tracker.*

| Column | Type | Constraints | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY` | `gen_random_uuid()` | Unique application tracker ID |
| `user_id` | `UUID` | `REFERENCES profiles(id) ON DELETE CASCADE` | — | Candidate ID |
| `job_id` | `UUID` | `REFERENCES jobs(id) ON DELETE CASCADE` | — | Applied job ID |
| `status` | `TEXT` | `CHECK (applied, response, interview, offer, rejected)` | `'applied'` | Current Kanban stage |
| `applied_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Timestamp application was submitted |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Last stage change timestamp |

---

### 2.5 `public.alerts`
*Configured candidate search alert criteria and notification webhooks.*

| Column | Type | Constraints | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY` | `gen_random_uuid()` | Unique alert trigger ID |
| `user_id` | `UUID` | `REFERENCES profiles(id) ON DELETE CASCADE` | — | Owner candidate ID |
| `name` | `TEXT` | `NOT NULL` | — | User-friendly alert label |
| `filters` | `JSONB` | `NOT NULL` | `'{}'` | Match filters (keywords, countries, work modes, contract types) |
| `frequency` | `TEXT` | `CHECK (instant, daily, weekly)` | `'daily'` | Notification frequency |
| `channels` | `JSONB` | `NOT NULL` | `'{"email": true}'` | Active channels: `email`, `telegram`, `discord`, `slack` |
| `active` | `BOOLEAN` | `NOT NULL` | `TRUE` | Enable/disable toggle |
| `last_sent_at` | `TIMESTAMPTZ` | — | `NULL` | Timestamp of last dispatched alert batch |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Creation timestamp |

---

## 3. Administrative Control & System Security Tables

### 3.1 `public.admin_users`
*Max-security Google OAuth + TOTP MFA administrative allowlist.*

| Column | Type | Constraints | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY` | `gen_random_uuid()` | Unique admin ID |
| `email` | `TEXT` | `UNIQUE NOT NULL` | — | Authorized Google Workspace email |
| `role` | `TEXT` | `CHECK (superadmin, admin, analyst)` | `'admin'` | Role-based access level |
| `active` | `BOOLEAN` | `NOT NULL` | `TRUE` | Active access toggle |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Enrollment timestamp |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Modification timestamp |

---

### 3.2 `public.admin_audit_log`
*Immutable security audit log capturing every administrative action.*

| Column | Type | Constraints | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY` | `gen_random_uuid()` | Unique audit event ID |
| `admin_email` | `TEXT` | `NOT NULL` | — | Authenticated admin email |
| `action` | `TEXT` | `NOT NULL` | — | Action executed (e.g. `quarantine_retry`, `toggle_platform`) |
| `resource` | `TEXT` | `NOT NULL` | — | Target entity (e.g. `job_processing:123`, `platform_post_config:x`) |
| `details` | `JSONB` | — | `NULL` | Parameter snapshot and diff |
| `ip_address` | `TEXT` | — | `NULL` | Client IP address |
| `user_agent` | `TEXT` | — | `NULL` | Browser / client user-agent string |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | `NOW()` | Event timestamp |

---

### 3.3 `public.platform_post_config`
*Social media syndication rate limits, operating hours, and kill-switches.*

| Column | Type | Constraints | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `platform` | `TEXT` | `PRIMARY KEY` | — | Platform key: `x`, `bluesky`, `mastodon`, `linkedin`, `telegram`, `discord` |
| `enabled` | `BOOLEAN` | `NOT NULL` | `FALSE` | Global channel enable switch (**disabled by default**) |
| `min_gap_minutes` | `INTEGER` | `NOT NULL` | `60` | Minimum gap between consecutive posts in minutes |
| `daily_cap` | `INTEGER` | `NOT NULL` | `10` | Maximum posts allowed per UTC calendar day |
| `active_start_hour` | `INTEGER` | `NOT NULL` | `7` | Starting active publication hour in UTC |
| `active_end_hour` | `INTEGER` | `NOT NULL` | `22` | Ending active publication hour in UTC |
| `last_post_at` | `TIMESTAMPTZ` | — | `NULL` | Timestamp of most recent post |
| `published_today` | `INTEGER` | `NOT NULL` | `0` | Daily publication counter (resets at 00:00 UTC) |

---

### 3.4 `public.service_circuits`
*Circuit breaker states preventing API quota drain during external provider outages.*

| Column | Type | Constraints | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `name` | `TEXT` | `PRIMARY KEY` | — | Service identifier (e.g. `gemini_flash`, `resend`, `linkedin`) |
| `consecutive_failures` | `INTEGER` | `NOT NULL` | `0` | Consecutive failure count |
| `state` | `TEXT` | `CHECK (closed, open, half_open)` | `'closed'` | Circuit state (`closed` = normal, `open` = tripped) |
| `opened_at` | `TIMESTAMPTZ` | — | `NULL` | Timestamp when circuit was tripped |
| `last_failure_at` | `TIMESTAMPTZ` | — | `NULL` | Timestamp of most recent error |
| `last_success_at` | `TIMESTAMPTZ` | — | `NULL` | Timestamp of last successful API call |
| `updated_at` | `TIMESTAMPTZ` | — | `NOW()` | Timestamp of last state change |
