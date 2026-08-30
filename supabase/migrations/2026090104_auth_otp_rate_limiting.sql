-- Migration: 2026090104_auth_otp_rate_limiting.sql
-- Description: Audit and rate limiting tracking for Auth OTP dispatches and verifications.

CREATE TABLE IF NOT EXISTS public.auth_otp_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('send_otp', 'verify_success', 'verify_failed', 'locked')),
    ip_address TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auth_otp_logs_email ON public.auth_otp_logs(email, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_otp_logs_action ON public.auth_otp_logs(action, created_at DESC);

-- Enable RLS (Service role only, no public reads)
ALTER TABLE public.auth_otp_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access to auth_otp_logs"
    ON public.auth_otp_logs
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
