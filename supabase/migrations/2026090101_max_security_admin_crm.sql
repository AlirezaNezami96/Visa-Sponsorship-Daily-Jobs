-- ===========================================================================
-- MAX-SECURITY ADMIN/CRM ACCESS — 8-LAYER DEFENSE IN DEPTH
-- Migration: 20260901_max_security_admin_crm.sql
-- ===========================================================================

-- 1. admin_users — Strict allowlist with role and active flags
CREATE TABLE IF NOT EXISTS public.admin_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('admin', 'owner')),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Ensure all required columns exist if table already existed with just email
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'admin_users' AND column_name = 'id') THEN
    ALTER TABLE public.admin_users ADD COLUMN id UUID DEFAULT gen_random_uuid();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'admin_users' AND column_name = 'role') THEN
    ALTER TABLE public.admin_users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('admin', 'owner'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'admin_users' AND column_name = 'active') THEN
    ALTER TABLE public.admin_users ADD COLUMN active BOOLEAN NOT NULL DEFAULT TRUE;
  END IF;
END $$;

-- 2. Security-Definer Admin Check Functions
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.admin_users
    WHERE lower(email) = lower(auth.jwt() ->> 'email')
      AND active = true
  );
$$;

CREATE OR REPLACE FUNCTION public.is_admin_owner()
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.admin_users
    WHERE lower(email) = lower(auth.jwt() ->> 'email')
      AND role = 'owner'
      AND active = true
  );
$$;

-- 3. admin_audit_log — Immutable security audit trail
CREATE TABLE IF NOT EXISTS public.admin_audit_log (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  admin_email TEXT NOT NULL,
  action TEXT NOT NULL,
  resource TEXT,
  meta JSONB,
  ip INET,
  user_agent TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_email ON public.admin_audit_log(admin_email);
CREATE INDEX IF NOT EXISTS idx_admin_audit_log_created_at ON public.admin_audit_log(created_at DESC);

-- 4. admin_stepup_challenges — Cryptographic step-up verification records
CREATE TABLE IF NOT EXISTS public.admin_stepup_challenges (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  admin_email TEXT NOT NULL,
  action TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL,
  used BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_admin_stepup_token ON public.admin_stepup_challenges(token_hash);
CREATE INDEX IF NOT EXISTS idx_admin_stepup_expires ON public.admin_stepup_challenges(expires_at);

-- 5. Row Level Security (RLS) on Admin Tables
ALTER TABLE public.admin_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_stepup_challenges ENABLE ROW LEVEL SECURITY;

-- admin_users policies
DROP POLICY IF EXISTS "admin_read_users" ON public.admin_users;
CREATE POLICY "admin_read_users" ON public.admin_users
  FOR SELECT TO authenticated
  USING (public.is_admin());

DROP POLICY IF EXISTS "owner_write_users" ON public.admin_users;
CREATE POLICY "owner_write_users" ON public.admin_users
  FOR ALL TO authenticated
  USING (public.is_admin_owner());

-- admin_audit_log policies
DROP POLICY IF EXISTS "admin_read_audit" ON public.admin_audit_log;
CREATE POLICY "admin_read_audit" ON public.admin_audit_log
  FOR SELECT TO authenticated
  USING (public.is_admin());

-- admin_stepup_challenges is service-role only (no direct anon/authenticated select)
DROP POLICY IF EXISTS "service_role_stepup" ON public.admin_stepup_challenges;

-- Pipeline & Metrics RLS policies for admin read access
DROP POLICY IF EXISTS "admin_read_quarantine" ON public.processing_quarantine;
CREATE POLICY "admin_read_quarantine" ON public.processing_quarantine
  FOR SELECT TO authenticated
  USING (public.is_admin());

DROP POLICY IF EXISTS "admin_read_metrics" ON public.metrics_daily;
CREATE POLICY "admin_read_metrics" ON public.metrics_daily
  FOR SELECT TO authenticated
  USING (public.is_admin());

DROP POLICY IF EXISTS "admin_read_pipeline_health" ON public.pipeline_health;
CREATE POLICY "admin_read_pipeline_health" ON public.pipeline_health
  FOR SELECT TO authenticated
  USING (public.is_admin());

DROP POLICY IF EXISTS "admin_read_circuits" ON public.service_circuits;
CREATE POLICY "admin_read_circuits" ON public.service_circuits
  FOR SELECT TO authenticated
  USING (public.is_admin());

-- 6. Initial Seed: Owner account
INSERT INTO public.admin_users (email, role, active)
VALUES ('alirezanezami96@gmail.com', 'owner', TRUE)
ON CONFLICT (email) DO UPDATE SET role = 'owner', active = TRUE;
