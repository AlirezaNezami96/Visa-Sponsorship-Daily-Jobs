-- Migration 2026090105: System Logs for Centralized Admin Panel Observability
-- Provides filtered error, warning, info, and debug logs with automatic 14-day rolling retention.

CREATE TABLE IF NOT EXISTS public.system_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  level VARCHAR(16) NOT NULL CHECK (level IN ('error', 'warn', 'info', 'debug')),
  source VARCHAR(64) NOT NULL,
  message TEXT NOT NULL,
  details JSONB DEFAULT '{}'::jsonb,
  user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  environment VARCHAR(32) DEFAULT 'production'
);

-- Fast indexes for admin filtering and time-range queries
CREATE INDEX IF NOT EXISTS idx_system_logs_created_at ON public.system_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_system_logs_level_created ON public.system_logs(level, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_system_logs_source ON public.system_logs(source);
CREATE INDEX IF NOT EXISTS idx_system_logs_user_id ON public.system_logs(user_id) WHERE user_id IS NOT NULL;

-- Automatic cleanup procedure (retains last 14 days to minimize storage overhead)
CREATE OR REPLACE FUNCTION public.prune_old_system_logs()
RETURNS void
LANGUAGE sql
SECURITY DEFINER
AS $$
  DELETE FROM public.system_logs WHERE created_at < now() - INTERVAL '14 days';
$$;

-- Security: Row Level Security (RLS)
ALTER TABLE public.system_logs ENABLE ROW LEVEL SECURITY;

-- Admins can view all system logs
DROP POLICY IF EXISTS "Admins can view system logs" ON public.system_logs;
CREATE POLICY "Admins can view system logs" ON public.system_logs
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.admin_users
      WHERE admin_users.email = (auth.jwt() ->> 'email')
        AND admin_users.active = true
    )
  );

-- Service role has full access (Edge Functions / background scrapers)
DROP POLICY IF EXISTS "Service role manages system logs" ON public.system_logs;
CREATE POLICY "Service role manages system logs" ON public.system_logs
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);
