-- Supabase Migration: VisaLane Phase 1 Events Logging Table
-- Supports first-party anonymous and authenticated event tracking.

CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    session_id TEXT,
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);

ALTER TABLE events ENABLE ROW LEVEL SECURITY;

-- Allow anonymous and authenticated users to insert events
DROP POLICY IF EXISTS "public_insert_events" ON events;
CREATE POLICY "public_insert_events" ON events
    FOR INSERT
    TO public
    WITH CHECK (true);

-- Service-role full access
DROP POLICY IF EXISTS "service_all_events" ON events;
CREATE POLICY "service_all_events" ON events
    FOR ALL
    TO service_role
    USING (true);
