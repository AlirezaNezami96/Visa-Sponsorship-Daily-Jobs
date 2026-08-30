-- Pipeline State Machine Migration
-- Adds: job_processing (per-stage tracking), processing_quarantine (dead-letter),
-- service_circuits (circuit breaker), platform_post_config (pacing),
-- metrics_daily (aggregated metrics), pipeline_health (stage health),
-- admin_users (admin access control).
-- New columns on jobs for image/social publishing state.
-- Auto-insert trigger for job_processing on jobs INSERT.
-- Safe to re-run (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).

-- ---------------------------------------------------------------------------
-- 1. job_processing — per-job pipeline stage tracking
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_processing (
  job_id UUID PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  -- Stage 2: metadata enrichment
  metadata_status TEXT NOT NULL DEFAULT 'pending',
  metadata_attempts INT NOT NULL DEFAULT 0,
  metadata_last_error TEXT,
  metadata_done_at TIMESTAMPTZ,
  -- Stage 3: alerts
  alerts_status TEXT NOT NULL DEFAULT 'pending',
  alerts_done_at TIMESTAMPTZ,
  -- Stage 4: image
  image_status TEXT NOT NULL DEFAULT 'pending',
  image_attempts INT NOT NULL DEFAULT 0,
  image_last_error TEXT,
  image_done_at TIMESTAMPTZ,
  -- Stage 5: post text + per-platform publishing
  post_text TEXT,
  post_text_status TEXT NOT NULL DEFAULT 'pending',
  telegram_status TEXT NOT NULL DEFAULT 'pending',  telegram_at TIMESTAMPTZ, telegram_url TEXT,
  discord_status  TEXT NOT NULL DEFAULT 'pending',  discord_at  TIMESTAMPTZ, discord_url  TEXT,
  slack_status    TEXT NOT NULL DEFAULT 'pending',  slack_at    TIMESTAMPTZ, slack_url    TEXT,
  bluesky_status  TEXT NOT NULL DEFAULT 'pending',  bluesky_at  TIMESTAMPTZ, bluesky_url  TEXT,
  mastodon_status TEXT NOT NULL DEFAULT 'pending',  mastodon_at TIMESTAMPTZ, mastodon_url TEXT,
  linkedin_status TEXT NOT NULL DEFAULT 'pending',  linkedin_at TIMESTAMPTZ, linkedin_url TEXT,
  x_status        TEXT NOT NULL DEFAULT 'pending',  x_at        TIMESTAMPTZ, x_url        TEXT,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Partial indexes for stage workers to find pending work efficiently
CREATE INDEX IF NOT EXISTS idx_jp_metadata_pending ON job_processing(updated_at)
    WHERE metadata_status IN ('pending', 'failed');
CREATE INDEX IF NOT EXISTS idx_jp_image_pending ON job_processing(updated_at)
    WHERE image_status IN ('pending', 'failed');
CREATE INDEX IF NOT EXISTS idx_jp_post_text_pending ON job_processing(updated_at)
    WHERE post_text_status IN ('pending', 'failed');
CREATE INDEX IF NOT EXISTS idx_jp_alerts_pending ON job_processing(updated_at)
    WHERE alerts_status = 'pending';

-- Per-platform partial indexes for publisher workers
CREATE INDEX IF NOT EXISTS idx_jp_telegram_pending ON job_processing(updated_at)
    WHERE telegram_status = 'pending' AND post_text_status = 'done';
CREATE INDEX IF NOT EXISTS idx_jp_discord_pending ON job_processing(updated_at)
    WHERE discord_status = 'pending' AND post_text_status = 'done';

-- updated_at trigger
CREATE OR REPLACE FUNCTION update_job_processing_timestamp()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_job_processing_updated ON job_processing;
CREATE TRIGGER trg_job_processing_updated
    BEFORE UPDATE ON job_processing
    FOR EACH ROW EXECUTE FUNCTION update_job_processing_timestamp();

-- ---------------------------------------------------------------------------
-- 2. processing_quarantine — dead-letter table for persistent failures
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS processing_quarantine (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  reason TEXT NOT NULL,
  attempts INT NOT NULL,
  payload JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_quarantine_unresolved ON processing_quarantine(created_at DESC)
    WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_quarantine_job ON processing_quarantine(job_id);

-- ---------------------------------------------------------------------------
-- 3. service_circuits — circuit breaker state per external service
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS service_circuits (
  name TEXT PRIMARY KEY,
  consecutive_failures INT DEFAULT 0,
  state TEXT DEFAULT 'closed',
  opened_at TIMESTAMPTZ,
  last_failure_at TIMESTAMPTZ,
  last_success_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 4. platform_post_config — per-platform posting pacing rules
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS platform_post_config (
  platform TEXT PRIMARY KEY,
  min_gap_minutes INT NOT NULL,
  daily_cap INT NOT NULL,
  active_start_hour INT NOT NULL,
  active_end_hour INT NOT NULL,
  enabled BOOLEAN DEFAULT TRUE
);

INSERT INTO platform_post_config VALUES
  ('telegram', 5, 40, 0, 24, TRUE),
  ('discord', 5, 40, 0, 24, TRUE),
  ('slack', 5, 40, 0, 24, TRUE),
  ('bluesky', 30, 12, 6, 23, FALSE),
  ('mastodon', 30, 12, 6, 23, FALSE),
  ('x', 60, 5, 7, 22, FALSE),
  ('linkedin', 120, 3, 7, 19, FALSE)
ON CONFLICT (platform) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 5. metrics_daily — aggregated daily metrics (one row per metric per day)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metrics_daily (
  day DATE NOT NULL,
  metric TEXT NOT NULL,
  count BIGINT DEFAULT 0,
  error_count BIGINT DEFAULT 0,
  sum_ms BIGINT DEFAULT 0,
  PRIMARY KEY (day, metric)
);

CREATE INDEX IF NOT EXISTS idx_metrics_daily_metric ON metrics_daily(metric, day DESC);

-- ---------------------------------------------------------------------------
-- 6. pipeline_health — per-stage last success/error/backlog
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_health (
  stage TEXT PRIMARY KEY,
  last_success_at TIMESTAMPTZ,
  last_error_at TIMESTAMPTZ,
  last_error TEXT,
  backlog INT DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 7. admin_users — email allowlist for admin endpoints
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin_users (
  email TEXT PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 8. New columns on jobs for image/social publishing state
-- ---------------------------------------------------------------------------
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS image_url TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS company_logo_url TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS applicants_count INTEGER;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS linkedin_post_published BOOLEAN DEFAULT FALSE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS x_post_published BOOLEAN DEFAULT FALSE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS telegram_post_published BOOLEAN DEFAULT FALSE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS discord_post_published BOOLEAN DEFAULT FALSE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS bluesky_post_published BOOLEAN DEFAULT FALSE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS mastodon_post_published BOOLEAN DEFAULT FALSE;

-- ---------------------------------------------------------------------------
-- 9. Auto-insert job_processing row when a new job is inserted
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION auto_insert_job_processing()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO job_processing (job_id)
    VALUES (NEW.id)
    ON CONFLICT (job_id) DO NOTHING;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_auto_job_processing ON jobs;
CREATE TRIGGER trg_auto_job_processing
    AFTER INSERT ON jobs
    FOR EACH ROW EXECUTE FUNCTION auto_insert_job_processing();

-- ---------------------------------------------------------------------------
-- 10. RLS — pipeline tables are service-role only (no anon/authenticated)
-- ---------------------------------------------------------------------------
ALTER TABLE job_processing ENABLE ROW LEVEL SECURITY;
ALTER TABLE processing_quarantine ENABLE ROW LEVEL SECURITY;
ALTER TABLE service_circuits ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform_post_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE metrics_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_health ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_users ENABLE ROW LEVEL SECURITY;
-- No policies = only service_role can access these tables

-- ---------------------------------------------------------------------------
-- 11. Storage bucket for company logos
-- ---------------------------------------------------------------------------
INSERT INTO storage.buckets (id, name, public)
VALUES ('companies', 'companies', TRUE)
ON CONFLICT (id) DO NOTHING;

DROP POLICY IF EXISTS "public_read_company_logos" ON storage.objects;
CREATE POLICY "public_read_company_logos" ON storage.objects
    FOR SELECT TO anon, authenticated
    USING (bucket_id = 'companies');
