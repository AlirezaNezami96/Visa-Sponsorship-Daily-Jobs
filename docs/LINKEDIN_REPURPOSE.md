# LinkedIn Content Repurposing & Automated Publishing Pipeline

The **LinkedIn Content Repurposing Pipeline** is an unattended, production-grade system that selects an unused technical post from a curated ~200-post dataset in Supabase, adapts it using **Gemini 3.7 Flash**, archives media directly to **Supabase Storage** (`linkedin-media` bucket), re-brands demo videos with the personal creator badge (**Alireza Nezami**), and publishes directly to LinkedIn on a twice-daily schedule via GitHub Actions.

---

## 🏗️ Architecture & Pipeline Flow

```
[ Curated JSON Dataset (~200 Posts) ]
                ↓ (One-time ingestion via `job-radar-import-posts`)
[ Supabase `source_posts` & `source_post_media` (Deduplicated) ]
                ↓ (Scheduled twice daily at 07:30 & 15:30 UTC)
[ Atomic Post Selection (`reserve_next_source_post()` RPC) ]
                ↓
    ┌───────────┴────────────────────────────┐
    ↓                                        ↓
[ Text Post ]                        [ Media Post ]
    ↓                                        ↓
    │                        ┌───────────────┴───────────────┐
    │                        ↓                               ↓
    │                 [ Image Post ]                  [ Video Post ]
    │                        ↓                               ↓
    │                 (Download & Archive             (Download & Archive
    │                  to Supabase Storage)            to Supabase Storage)
    │                        ↓                               ↓
    │                        │                       [ CreatorBadgeService ]
    │                        │                       (Replaces old creator badge
    │                        │                        with @alireza-nezami badge)
    │                        └───────────────┬───────────────┘
    │                                        ↓
    └────────────────────────────────────────┤
                                             ↓
                         [ Gemini 3.7 Flash Adaptation ]
                         (Transforms post to first-person tech authority,
                          scrubs original author handles & CTAs)
                                             ↓
                         [ Deterministic Quality Validation ]
                         (Length bounds, anti-copying similarity < 0.90)
                                             ↓
                         [ LinkedIn REST API Publication ]
                         (Registers media upload, uploads binary, publishes UGC post)
                                             ↓
                         [ Supabase State Update: `published` ]
                         (Records LinkedIn Post URN, public URL & timestamp)
```

---

## 🗄️ Database & Storage Setup (Supabase)

### 1. Run the Migration
In your **Supabase Project $\rightarrow$ SQL Editor**, execute the migration file:
[`supabase/migrations/20260823_source_posts.sql`](file:///Users/alirezanezami/Documents/Visa-Sponsorship-Daily-Jobs/supabase/migrations/20260823_source_posts.sql)

This sets up:
- `source_posts`: Main table tracking post lifecycle, content hashes, reservation tokens, and publication metadata.
- `source_post_media`: Normalized storage for images, videos, thumbnails, and Supabase Storage object paths.
- `storage.buckets`: Auto-provisions the public `linkedin-media` bucket.
- `reserve_next_source_post()`: PostgreSQL stored procedure with `FOR UPDATE SKIP LOCKED` for concurrency-safe atomic reservations.

---

## 📥 Ingesting the 200 Source Posts

Place your source post dataset at `data/source_posts.json` and run:

```bash
# 1. Preview / Validate without database changes (Dry Run)
python scripts/import_source_posts.py --file data/source_posts.json --dry-run

# 2. Ingest into Supabase
python scripts/import_source_posts.py --file data/source_posts.json
```

### Ingestion Features:
- **Deduplication**: Computes SHA-256 hash on normalized text (NFKD Unicode, lowercase, stripped URL tracking params) and performs token Jaccard similarity ($\ge 85\%$).
- **Canonical Preservation**: Marks exact and near duplicates as `skipped` with reasons (e.g. `duplicate_of:7494632582014406656`).
- **Idempotent**: Safely re-runnable at any time without creating duplicate database records.

---

## ☁️ Google Drive Durable Media Archiving

Because GitHub Actions runners are ephemeral, media files are persistently stored in Google Drive:

- **Hierarchy**: `LinkedIn Automation/Source Media/<source_post_id>/original.<ext>`
- **Caching**: The pipeline checks if `storage_file_id` is already stored in Supabase before attempting downloads from LinkedIn source URLs.
- **Cleanup**: Downloaded media and processed branded videos on the runner are wiped at the end of each run.

---

## 🤖 Gemini 3.7 Flash Adaptation & Quality Checks

The rewriter prompt is tailored for a senior software engineer / AI builder profile:
- Preserves technical concepts, open-source tool recommendations, and core insights.
- Completely rewrites content in an original, authentic voice.
- Automatically removes author branding (`Ram Maheshwari`, `rammcodes`, "Follow me", etc.).
- Pre-publish verification checks:
  - Minimum 50 chars, max 3000 chars.
  - $\le 90\%$ sequence similarity and $\le 88\%$ token Jaccard similarity against source (prevents verbatim copying).
  - Verifies zero residual author mentions.

---

## 🎥 Video Creator Badge Overlay

For posts with demo videos, the video is routed through [`CreatorBadgeService`](file:///Users/alirezanezami/Documents/Visa-Sponsorship-Daily-Jobs/src/job_radar/creator_badge/):
- Replaces original creator watermark/badge in bottom-right corner.
- Embeds avatar for **Alireza Nezami** (`alireza-nezami`) with high-DPI antialiasing.
- Encodes at high visual quality (`libx264`, `crf 18`, `+faststart`).

---

## ⏰ Scheduling & GitHub Actions

Workflow file: [`.github/workflows/linkedin-republish.yml`](file:///Users/alirezanezami/Documents/Visa-Sponsorship-Daily-Jobs/.github/workflows/linkedin-republish.yml)

### Cron Schedule (UTC vs Iran Time)
Iran Standard Time is **UTC+03:30**:
- **11:00 Iran Time** $\rightarrow$ `07:30 UTC` (`30 7 * * *`)
- **19:00 Iran Time** $\rightarrow$ `15:30 UTC` (`30 15 * * *`)

```yaml
on:
  schedule:
    - cron: "30 7 * * *"
    - cron: "30 15 * * *"
  workflow_dispatch:
```

---

## 🔑 Required Secrets & Environment Variables

Configure these in your GitHub Repository under **Settings $\rightarrow$ Secrets and variables $\rightarrow$ Actions**:

| Secret Name | Description |
|---|---|
| `SUPABASE_URL` | Your Supabase project URL (`https://<project>.supabase.co`). |
| `SUPABASE_SERVICE_ROLE_KEY` / `SUPABASE_KEY` | Supabase Service Role Key or API Key. |
| `GEMINI_API_KEY` | Google AI Studio Gemini API Key. |
| `LINKEDIN_ACCESS_TOKEN` | LinkedIn OAuth2 User Access Token. |
| `LINKEDIN_PERSON_URN` | LinkedIn Author Person URN (e.g. `urn:li:person:aAOQrAt7pG`). |
| `GOOGLE_DRIVE_CREDENTIALS` | Service Account JSON string content. |
| `GOOGLE_DRIVE_ROOT_FOLDER_ID` | (Optional) Root Google Drive folder ID to store all automation assets. |

---

## 🧪 Local Testing & Dry-Run Guide

You can test the entire pipeline locally without publishing to LinkedIn or modifying Supabase:

```bash
# Test full repurposing flow in Dry Run mode
python republish_post.py --dry-run

# Force run a specific post ID
python republish_post.py --post-id 1 --dry-run

# Run full automated test suite
python3 -m pytest tests/test_repurpose_pipeline.py -v
```
