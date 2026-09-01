-- Migration 2026090110: Add published_today and last_post_at tracking to platform_post_config
-- Enables pacing, daily budget enforcement, and last-post timestamp tracking for social syndication.

ALTER TABLE public.platform_post_config
ADD COLUMN IF NOT EXISTS published_today INT NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS last_post_at TIMESTAMPTZ;

-- Index to optimize querying enabled platforms with pacing info
CREATE INDEX IF NOT EXISTS idx_platform_post_config_enabled 
ON public.platform_post_config(enabled) 
WHERE enabled = TRUE;
