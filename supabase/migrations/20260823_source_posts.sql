-- Supabase Migration: Source Posts Lifecycle & Normalized Media Tables
-- Creates tables and atomic reservation RPC function for the LinkedIn Repurposing Pipeline.

-- 1. Main source_posts Table
CREATE TABLE IF NOT EXISTS source_posts (
    id BIGSERIAL PRIMARY KEY,
    source_platform TEXT NOT NULL DEFAULT 'linkedin',
    source_post_id TEXT NOT NULL,
    source_url TEXT,
    author_name TEXT,
    author_username TEXT,
    content TEXT NOT NULL,
    normalized_content TEXT,
    content_hash TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'none', -- 'none', 'image', 'multi_image', 'video', 'document'
    media_count INT NOT NULL DEFAULT 0,
    source_json JSONB,
    source_posted_at TIMESTAMPTZ,
    media_archived BOOLEAN NOT NULL DEFAULT FALSE,
    media_status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'archived', 'failed', 'not_applicable'
    processing_status TEXT NOT NULL DEFAULT 'available', -- 'available', 'reserved', 'processing', 'published', 'failed', 'skipped'
    reserved_at TIMESTAMPTZ,
    reserved_by TEXT,
    generated_content TEXT,
    final_content TEXT,
    published_linkedin_post_id TEXT,
    published_linkedin_url TEXT,
    published_at TIMESTAMPTZ,
    failure_count INT NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_source_platform_post_id UNIQUE (source_platform, source_post_id)
);

-- 2. Indexes for efficient lookup & atomic selection
CREATE INDEX IF NOT EXISTS idx_source_posts_status ON source_posts (processing_status);
CREATE INDEX IF NOT EXISTS idx_source_posts_content_hash ON source_posts (content_hash);
CREATE INDEX IF NOT EXISTS idx_source_posts_platform_id ON source_posts (source_platform, source_post_id);
CREATE INDEX IF NOT EXISTS idx_source_posts_media_status ON source_posts (media_status);

-- 3. Normalized source_post_media Table
CREATE TABLE IF NOT EXISTS source_post_media (
    id BIGSERIAL PRIMARY KEY,
    source_post_id BIGINT NOT NULL REFERENCES source_posts(id) ON DELETE CASCADE,
    media_type TEXT NOT NULL, -- 'image', 'video', 'thumbnail'
    source_url TEXT,
    thumbnail_url TEXT,
    storage_provider TEXT NOT NULL DEFAULT 'supabase_storage', -- 'supabase_storage', 'google_drive', 'local'
    storage_file_id TEXT, -- Supabase object path or Google Drive file ID
    storage_path TEXT,
    mime_type TEXT,
    file_size BIGINT,
    checksum TEXT,
    download_status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'downloaded', 'failed'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Supabase Storage Bucket for LinkedIn Media
INSERT INTO storage.buckets (id, name, public)
VALUES ('linkedin-media', 'linkedin-media', true)
ON CONFLICT (id) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_source_post_media_post_id ON source_post_media (source_post_id);
CREATE INDEX IF NOT EXISTS idx_source_post_media_status ON source_post_media (download_status);

-- 4. Atomic Post Reservation Function (RPC)
-- Safely selects and locks exactly one eligible post using FOR UPDATE SKIP LOCKED.
-- Returns the reserved row and updates its status to 'reserved'.
CREATE OR REPLACE FUNCTION reserve_next_source_post(
    p_worker_id TEXT DEFAULT 'github_action',
    p_max_failures INT DEFAULT 3
)
RETURNS SETOF source_posts
LANGUAGE plpgsql
AS $$
DECLARE
    v_post_id BIGINT;
BEGIN
    -- Select one available post with concurrency-safe locking
    SELECT id INTO v_post_id
    FROM source_posts
    WHERE processing_status = 'available'
      AND failure_count < p_max_failures
    ORDER BY 
      media_archived DESC, -- Prioritize archived media
      id ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1;

    IF v_post_id IS NOT NULL THEN
        RETURN QUERY
        UPDATE source_posts
        SET 
            processing_status = 'reserved',
            reserved_at = NOW(),
            reserved_by = p_worker_id,
            updated_at = NOW()
        WHERE id = v_post_id
        RETURNING *;
    END IF;

    RETURN;
END;
$$;
