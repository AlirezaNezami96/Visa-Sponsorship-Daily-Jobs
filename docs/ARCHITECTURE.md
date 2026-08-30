# VisaLane Pipeline State Machine Architecture

## 1. System Overview

VisaLane operates on a **5-stage queued, watched, metric-emitting state machine** hosted on GitHub Actions, Python 3.11/3.14, and Supabase at $0 operating cost.

```mermaid
flowchart TD
    A[Scrape Cron / Ingest] -->|Insert job| B[(jobs table)]
    B -->|Trigger: trg_auto_job_processing| C[(job_processing)]
    
    subgraph Stage 1: Ingest
        A
    end

    subgraph Stage 2: Enrichment Worker
        C -->|metadata_status='pending'| D[Enrichment Worker]
        D -->|ThreadPool: skills, salary, mode, logo| D
        D -->|metadata_status='done'| C
    end

    subgraph Stage 3: Alerts Worker
        C -->|metadata_status='done'| E[Alert Worker]
        E -->|Match filters & dedup| E
        E -->|Instant Telegram, Discord, Slack, Email| F[Channels]
        E -->|alerts_status='done'| C
    end

    subgraph Stage 4: Image Pipeline
        C -->|image_status='pending'| G[Image Worker]
        G -->|Pillow / Deterministic Card Renderer| G
        G -->|Upload PNG to job-cards bucket| H[(Supabase Storage)]
        G -->|image_status='done' + jobs.image_url| C
    end

    subgraph Stage 5: Social Publishing
        C -->|post_text_status='pending'| I[Post Text Worker]
        I -->|Rotating Hook + Summary| I
        I -->|post_text_status='done'| C
        C -->|telegram_status='pending'| J[Telegram Publisher]
        C -->|discord_status='pending'| K[Discord Publisher]
        C -->|slack_status='pending'| L[Slack / Social Publisher]
        C -->|manual_review| M[Telegram Approval Bot]
    end

    subgraph Watchdog & Health
        N[Watchdog Cron] -->|Every 2h: Reset stuck >30m| C
        N -->|Quarantine after 3 failures| O[(processing_quarantine)]
        N -->|Update backlogs| P[(pipeline_health)]
        N -->|Check circuits| Q[(service_circuits)]
        N -->|Anomaly alert| R[Owner Telegram & Email]
    end
```

---

## 2. Pipeline Stages

| Stage | Worker / Trigger | Prerequisite | Outputs | Failure Behavior |
|-------|------------------|--------------|---------|------------------|
| **1. Ingest** | `daily-jobs.yml`, `europe-jobs.yml` | None | `jobs` row + `job_processing` row | Retry on next scrape, circuit breaker per source |
| **2. Enrich** | `enrichment_worker.py` | `jobs` row | `skills`, `salary_*`, `work_mode`, `company_logo_url` | Field-level NULL; attempts +1, max 3 -> quarantine |
| **3. Alerts** | `alert_worker.py` | `metadata_status='done'` | Instant notifications sent, `alert_sent_jobs` | Channel isolation (one dead channel doesn't block others) |
| **4. Images** | `image_worker.py` | `metadata_status='done'` | `job-cards/{id}.png` in Storage, `jobs.image_url` | Attempts +1, max 3 -> quarantine |
| **5. Post Text** | `post_text_worker.py` | `image_status='done'` | `job_processing.post_text` JSON payload | Attempts +1, max 3 -> quarantine |
| **6. Publish** | `platform_publisher.py` | `post_text_status='done'` | Post URL, `jobs.*_post_published = true` | Pacing checked, manual review routing for LinkedIn/X |

---

## 3. Reliability Primitives

### Circuit Breakers (`service_circuits`)
- External services (AI providers, Wikimedia, scrapers, APIs) are wrapped in database-backed circuit breakers.
- **States**: `closed` -> `open` (after 5 consecutive failures) -> `half_open` (after 30-minute cooldown) -> `closed` (on success).

### Dead-Letter Quarantine (`processing_quarantine`)
- Any job that fails 3 attempts at any stage is automatically quarantined with its payload and error trace.
- Quarantined jobs do not block future jobs from progressing.
- The Watchdog alerts the owner immediately when new quarantines occur.

### Daily Aggregated Metrics (`metrics_daily`)
- Atomic single-row daily metrics (`day`, `metric`, `count`, `error_count`, `sum_ms`).
- Dashboard endpoints read aggregated rows directly — zero raw event scans.
