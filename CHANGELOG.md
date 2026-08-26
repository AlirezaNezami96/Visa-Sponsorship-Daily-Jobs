# Changelog

All notable changes to the **Visa Sponsorship Jobs Scraper & Intelligence Feed** Actor are documented here.

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
