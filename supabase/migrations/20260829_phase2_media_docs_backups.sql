-- Phase-2 extensions: media asset cache (brand cards), document idempotency,
-- alert delivery logs, backup logs, and the private per-user storage bucket.
-- Builds on 20260828_visalane_backend.sql; safe to re-run (IF NOT EXISTS).

-- ---------------------------------------------------------------------------
-- 20. media_assets — licensed landmark photo cache (GAP 1)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS media_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_kind TEXT NOT NULL DEFAULT 'landmark',
    city TEXT,
    country TEXT,
    source_url TEXT,
    license TEXT,
    attribution TEXT,
    storage_path TEXT,
    width INTEGER,
    height INTEGER,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (asset_kind, city, country)
);

CREATE INDEX IF NOT EXISTS idx_media_assets_lookup
    ON media_assets (asset_kind, city, country);

-- ---------------------------------------------------------------------------
-- 21. generated_documents — idempotency keys (GAP 3)
-- ---------------------------------------------------------------------------
ALTER TABLE generated_documents
    ADD COLUMN IF NOT EXISTS profile_updated_at TIMESTAMPTZ;

ALTER TABLE generated_documents
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

-- Only completed documents are idempotency hits; partial/failed rows never are.
CREATE INDEX IF NOT EXISTS idx_gen_docs_idempotency
    ON generated_documents (idempotency_key)
    WHERE status = 'completed';

-- ---------------------------------------------------------------------------
-- 22. alert_delivery_logs — per-channel delivery bookkeeping (GAP 5)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_delivery_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id UUID REFERENCES alerts(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('sent', 'failed')),
    job_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_delivery_alert
    ON alert_delivery_logs (alert_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- 23. backup_logs — database / storage backup runs (GAP 5)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backup_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    artifact_path TEXT,
    size_bytes BIGINT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backup_logs_kind
    ON backup_logs (kind, created_at DESC);

-- ---------------------------------------------------------------------------
-- 24. Storage buckets: media (landmarks, server-only) + users (own prefix)
-- ---------------------------------------------------------------------------
INSERT INTO storage.buckets (id, name, public)
VALUES ('media', 'media', FALSE)
ON CONFLICT (id) DO NOTHING;

INSERT INTO storage.buckets (id, name, public)
VALUES ('users', 'users', FALSE)
ON CONFLICT (id) DO NOTHING;

-- media bucket: no FE policies at all — service_role bypass is the only path
-- (landmarks are consumed server-side by the card renderer).

-- users bucket: RLS — a user can only read/write/delete their own prefix
-- (users/{uid}/...). Generated PDFs live at
-- users/{uid}/jobs/{job_id}/{type}/{document_id}.pdf; the FE reads them via
-- signed URLs minted by Edge Functions.
DROP POLICY IF EXISTS "users_read_own_files" ON storage.objects;
CREATE POLICY "users_read_own_files" ON storage.objects
    FOR SELECT TO authenticated
    USING (bucket_id = 'users'
           AND (storage.foldername(name))[1] = auth.uid()::text);

DROP POLICY IF EXISTS "users_write_own_files" ON storage.objects;
CREATE POLICY "users_write_own_files" ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (bucket_id = 'users'
                AND (storage.foldername(name))[1] = auth.uid()::text);

DROP POLICY IF EXISTS "users_delete_own_files" ON storage.objects;
CREATE POLICY "users_delete_own_files" ON storage.objects
    FOR DELETE TO authenticated
    USING (bucket_id = 'users'
           AND (storage.foldername(name))[1] = auth.uid()::text);
