-- ===========================================================================
-- Migration: 20260901_social_publish_disabled.sql
-- Multi-Platform Social Publishing (Shipped DISABLED by default)
-- ===========================================================================

-- 1. Ensure platform_post_config table exists with pacing and enabled flag
CREATE TABLE IF NOT EXISTS public.platform_post_config (
  platform TEXT PRIMARY KEY,
  min_gap_minutes INT NOT NULL DEFAULT 60,
  daily_cap INT NOT NULL DEFAULT 5,
  active_start_hour INT NOT NULL DEFAULT 7,
  active_end_hour INT NOT NULL DEFAULT 22,
  enabled BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Explicitly disable all existing rows
UPDATE public.platform_post_config SET enabled = FALSE;

-- 3. Upsert default pacing rules for all 7 platforms with enabled = FALSE
INSERT INTO public.platform_post_config (platform, min_gap_minutes, daily_cap, active_start_hour, active_end_hour, enabled)
VALUES
  ('x', 60, 5, 7, 22, FALSE),
  ('linkedin', 120, 3, 7, 19, FALSE),
  ('devto', 30, 10, 6, 23, FALSE),
  ('bluesky', 30, 10, 7, 22, FALSE),
  ('mastodon', 30, 10, 7, 22, FALSE),
  ('telegram', 15, 20, 7, 23, FALSE),
  ('discord', 15, 20, 7, 23, FALSE)
ON CONFLICT (platform) DO UPDATE SET enabled = FALSE;
