-- Supabase Migration: VisaLane Phase 3 Match Reports Table
-- Persists filter states for shareable match report links with dynamic re-counting.

CREATE TABLE IF NOT EXISTS match_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT UNIQUE NOT NULL,
    title TEXT,
    filters JSONB NOT NULL DEFAULT '{}',
    original_match_count INTEGER NOT NULL DEFAULT 0,
    session_id TEXT,
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_match_reports_slug ON match_reports(slug);
CREATE INDEX IF NOT EXISTS idx_match_reports_created_at ON match_reports(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_match_reports_session ON match_reports(session_id);

ALTER TABLE match_reports ENABLE ROW LEVEL SECURITY;

-- Allow anonymous and authenticated visitors to create and view match reports
DROP POLICY IF EXISTS "public_insert_match_reports" ON match_reports;
CREATE POLICY "public_insert_match_reports" ON match_reports
    FOR INSERT
    TO public
    WITH CHECK (true);

DROP POLICY IF EXISTS "public_read_match_reports" ON match_reports;
CREATE POLICY "public_read_match_reports" ON match_reports
    FOR SELECT
    TO public
    USING (true);

-- Service-role full access
DROP POLICY IF EXISTS "service_all_match_reports" ON match_reports;
CREATE POLICY "service_all_match_reports" ON match_reports
    FOR ALL
    TO service_role
    USING (true);
