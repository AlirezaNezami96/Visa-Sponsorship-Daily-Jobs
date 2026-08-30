# Changelog

All notable changes to the **VisaLane Platform & Visa Sponsorship Jobs Scraper** are documented here.

## [2.3.0] - 2026-08-30

### ⚙️ 5-Stage Queued Pipeline State Machine
- **Formal State Machine**: Database-backed `job_processing` table tracking per-stage status (`pending` $\to$ `processing` $\to$ `done` / `failed` / `quarantined`) with atomic transitions and attempt tracking.
- **Circuit Breakers (`service_circuits`)**: Dynamic circuit breaker wrapping all external APIs (AI providers, image scrapers, Wikimedia, ATS platforms) with automatic cooldown and half-open probing.
- **Dead-Letter Quarantine (`processing_quarantine`)**: Automatic isolation for jobs failing 3 consecutive attempts, preventing poison-pill blocking and emitting owner alerts.
- **Metadata Enrichment Worker**: Multi-threaded metadata extraction worker (`enrichment_worker.py`) with field-level fault tolerance for skills, salary normalization, work mode detection, and company favicon logos.
- **Alert Worker**: Instant multi-channel notification engine (`alert_worker.py`) with channel-level fault isolation (Telegram, Discord, Slack, Resend Email).

### 🎨 Image Generation Queue Pipeline
- **Deterministic Card Rendering**: Incremental image generator worker (`image_worker.py`) executing Pillow-based card rendering with public Supabase Storage upload and budget-aware concurrency caps.

### 📱 Social Publishing & Anti-Spam Pacing
- **Multi-Platform Publisher**: Dedicated publisher engine (`platform_publisher.py`) enforcing platform-specific active hours, hourly/daily post caps, and minimum post gap intervals.
- **Dynamic Post Text Generator**: Hook rotation algorithm (`hash(job_id) % len`) with 280-char enforcement for Twitter/X, rich Markdown for Telegram/Discord, and manual-review Telegram bot routing for LinkedIn and X.

### 📊 Observability, Health & Watchdog
- **Daily Aggregated Metrics (`metrics_daily`)**: Zero raw-event table scan design — single-row daily upserts tracking event counts, error counts, and latency sums.
- **Pipeline Watchdog**: Autonomous background supervisor (`watchdog.py`) resetting stale processing locks (>30m), monitoring stage backlogs, and dispatching owner alerts on anomalies.
- **Admin Metrics API**: Secure `GET /admin-metrics` Edge Function delivering full pipeline health, circuit breaker states, and quarantine lists in a single request.
- **Public Health Endpoint**: Lightweight `GET /health` endpoint compatible with status monitors (Upptime / GitHub Pages).

---

## [2.2.0] - 2026-08-30

### 🔐 Phase 4: Full OAuth 2.0 Subsystem
- **Providers**: Production-ready `GoogleOAuthProvider` and `GitHubOAuthProvider` with PKCE / CSRF HMAC-signed state tokens.
- **Edge Functions**: Implemented `oauth-initiate` and `oauth-callback` in Supabase Deno with automated profile creation and metadata synchronization.
- **Unified Error Handling**: Added `OAuthError` hierarchy (`InvalidStateError`, `TokenExchangeError`, `ProviderUnavailableError`, `ProfileFetchError`).

### 📄 Universal Resume Parser & Section Detection
- **Multi-Format Extraction**: Robust extractors for PDF (PDFMiner / `pypdf`), DOCX (`python-docx`), and plain text.
- **12-Section Contract**: Multilingual section detector supporting English, German, French, Spanish, Italian, and Portuguese across 12 standard resume categories.
- **AI Extraction Fallback**: Multi-model parser with anti-hallucination validation, confidence scoring, and fresher detection.
- **Database Persistence**: Automatic synchronization with `resumes` and `profiles` tables.

### 🎯 Job Match Scoring & Database Cache
- **Rarity-Weighted Algorithm**: 40pt Title, 50pt Skills (1.5x for rare technical skills, 1.0x for common/soft skills), 10pt Experience, +10 Location bonus, +5 Visa bonus.
- **Synonym & Version Normalizer**: Collapses synonyms (`JS` $\to$ `JavaScript`, `TS` $\to$ `TypeScript`, `NodeJS` $\to$ `Node`, `K8s` $\to$ `Kubernetes`, `AWS`, `GCP`, `CI/CD`) and strips version noise (`Python 3.9` $\to$ `Python`).
- **Two-Tier Cache**: In-memory LRU with TTL + persistent `user_job_scores` table with deterministic cursor tie-breaking (`posted_at DESC, id DESC`).

### ✍️ AI Document Generation & ATS Scoring
- **Tailored Resumes**: Generates tailored resumes supporting **Professional Format** (ATS layout) and **Own Format** (mirroring candidate structure).
- **Before / After ATS Comparison**: Real-time ATS scoring comparison showing match score improvements.
- **Anti-Hallucination Guard**: Grounding validator enforcing 100% factual accuracy against candidate resume facts.
- **Cover Letters & Outreach**: Generates 250–400 word personalized cover letters and 4-persona outreach messages (LinkedIn Note, InMail, Cold Email, Follow-up).

### 🔍 Contact Discovery & Company Website Enrichment
- **JSON-LD & Socials**: Ported `company-from-website` architecture to extract `schema.org/Organization` metadata, social profiles (LinkedIn company page, GitHub, Twitter/X), and phone numbers.
- **Team & Leadership Parsing**: Scrapes public team and leadership pages (`/about`, `/team`, `/leadership`, `/contact`) for hiring contacts.
- **4 Actionable Fallback Steps**: Returns LinkedIn recruiter search, hiring manager search, original job listing, and department mailboxes when direct contacts are unavailable.

### ⚡ Multi-Key AI Waterfall Router
- **Multi-Account Quota Rotation**: Automatically rotates across 2–3 Gemini API keys upon rate limits (`429 Too Many Requests`) before cascading to Groq (Llama 3.3 70B), OpenRouter, and safe heuristic fallbacks.

### 📚 Documentation & Developer Guides
- **Frontend Integration Guide**: [docs/FRONTEND_INTEGRATION_GUIDE.md](docs/FRONTEND_INTEGRATION_GUIDE.md) detailing all 7 core API endpoints, client-side PDF text extraction, and TypeScript examples.
- **Manual Setup Walkthrough**: [docs/MANUAL_SETUP_WALKTHROUGH.md](docs/MANUAL_SETUP_WALKTHROUGH.md) with step-by-step instructions for OAuth credentials, AI keys, and Supabase secrets.

---

## [2.1.0] - 2026-08-26

### 🛡️ P0 Billing Integrity & Store Hardening
- **Atomic Charge-Before-Push**: Implemented strict per-item charge verification in `ApifyDatasetSink` prior to dataset push. If spending limits trigger, uncharged items are dropped immediately.
- **Push Recovery**: In the event of network failures pushing to Apify dataset after retry, charged items are safely persisted to Key-Value Store under `RECOVERY_UNPUSHED_ITEMS`.
- **Cross-Run Deduplication**: Added `CrossRunDeduplicator` utilizing a persistent Named Key-Value store (`visa-jobs-dedup-state`) to prevent double-charging users on scheduled recurring runs (TTL default: 30 days, FIFO cap at 100,000 entries).
- **Decoupled Platform Alerts**: Stripped all operator email alerts and environment secrets from `apify_actor/` and `.actor/actor.json`.
- **Zero-Liability AI Classification**: AI evaluation requires user-supplied LLM API key (`llmApiKey`). Runs without an API key gracefully skip AI scoring with 0 `ai-classified-job` PPE charges.
- **Standard Apify Proxy**: Integrated `proxyConfiguration` with automated downstream resolution for HTTP fetchers.
- **Sponsor Registry Fallback**: Added `ensure_fresh_registries` with 30s timeout guard and fallback to pre-bundled SQLite database.
- **Memory Optimization**: Configured memory range to 512 MB – 2048 MB (recommended 1024 MB standard, 2048 MB for overseas detail extraction).

### 🚀 Volume Boost & Registry Intelligence
- **Known Visa Sponsors Fast-Path**: Added `data/known_sponsors.json` with 70+ top international tech employers (Google, Amazon, Meta, Microsoft, Apple, Stripe, Airbnb, OpenAI, Anthropic, Mistral AI, etc.) mapped to confidence `0.95`.
- **Curated ATS Slugs**: Integrated `data/curated_ats_slugs.json` covering Greenhouse, Lever, and Ashby.
- **Permissive Keyword Matching**: Added synonym expansion (e.g. `Software Engineer` ↔ `SWE` ↔ `Software Developer`, `Android` ↔ `Android Dev`).
