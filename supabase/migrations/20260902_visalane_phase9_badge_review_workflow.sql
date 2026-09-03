-- VisaLane Phase 9 Migration: Verified Sponsor Badge Admin Review Workflow & Audit Trail
-- Tables: badge_applications, badge_review_log

-- 1. Badge Applications Table
CREATE TABLE IF NOT EXISTS public.badge_applications (
    id TEXT PRIMARY KEY,
    employer_id TEXT NOT NULL,
    company_slug TEXT NOT NULL,
    company_name TEXT NOT NULL,
    contact_email TEXT NOT NULL,
    license_or_reg_number TEXT,
    sponsorship_history_summary TEXT NOT NULL,
    evidence_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes TEXT,
    badge_status TEXT NOT NULL DEFAULT 'pending_review' CHECK (badge_status IN ('pending_review', 'verified', 'rejected')),
    badge_payment_status TEXT NOT NULL DEFAULT 'paid' CHECK (badge_payment_status IN ('paid', 'pending', 'refunded')),
    verified_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    renewal_notified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for efficient querying by employer, company, and admin queue status
CREATE INDEX IF NOT EXISTS idx_badge_applications_employer_id ON public.badge_applications (employer_id);
CREATE INDEX IF NOT EXISTS idx_badge_applications_company_slug ON public.badge_applications (company_slug);
CREATE INDEX IF NOT EXISTS idx_badge_applications_status ON public.badge_applications (badge_status);
CREATE INDEX IF NOT EXISTS idx_badge_applications_expires_at ON public.badge_applications (expires_at) WHERE badge_status = 'verified';

-- 2. Badge Review Log Table (Immutable Audit Trail)
CREATE TABLE IF NOT EXISTS public.badge_review_log (
    id TEXT PRIMARY KEY,
    application_id TEXT REFERENCES public.badge_applications (id) ON DELETE SET NULL,
    employer_id TEXT NOT NULL,
    company_slug TEXT,
    reviewer_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for audit log lookups
CREATE INDEX IF NOT EXISTS idx_badge_review_log_employer_id ON public.badge_review_log (employer_id);
CREATE INDEX IF NOT EXISTS idx_badge_review_log_reviewer_id ON public.badge_review_log (reviewer_id);
CREATE INDEX IF NOT EXISTS idx_badge_review_log_created_at ON public.badge_review_log (created_at DESC);

-- Enable Row Level Security (RLS)
ALTER TABLE public.badge_applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.badge_review_log ENABLE ROW LEVEL SECURITY;

-- Service Role full access policies
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'badge_applications' AND policyname = 'service_role_all_badge_applications') THEN
        CREATE POLICY service_role_all_badge_applications ON public.badge_applications
            FOR ALL TO service_role USING (true) WITH CHECK (true);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'badge_review_log' AND policyname = 'service_role_all_badge_review_log') THEN
        CREATE POLICY service_role_all_badge_review_log ON public.badge_review_log
            FOR ALL TO service_role USING (true) WITH CHECK (true);
    END IF;
END $$;
