-- Supabase Migration: VisaLane Phase 4 Content & i18n Data Layer
-- Manages Policy Radar posts, evergreen visa guides, and localized translations.

CREATE TABLE IF NOT EXISTS posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('policy-radar', 'guide', 'data-report')),
    author TEXT NOT NULL DEFAULT 'VisaLane Policy Team',
    canonical_locale TEXT NOT NULL DEFAULT 'en',
    status TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('published', 'draft', 'archived')),
    featured_image_url TEXT,
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS post_translations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    locale TEXT NOT NULL,
    title TEXT NOT NULL,
    body_markdown TEXT NOT NULL,
    meta_description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (post_id, locale)
);

CREATE INDEX IF NOT EXISTS idx_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_posts_category ON posts(category);
CREATE INDEX IF NOT EXISTS idx_posts_status_published ON posts(status, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_post_translations_post_locale ON post_translations(post_id, locale);
CREATE INDEX IF NOT EXISTS idx_post_translations_locale ON post_translations(locale);

ALTER TABLE posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE post_translations ENABLE ROW LEVEL SECURITY;

-- Public read for published posts and their translations
DROP POLICY IF EXISTS "public_read_published_posts" ON posts;
CREATE POLICY "public_read_published_posts" ON posts
    FOR SELECT
    TO public
    USING (status = 'published');

DROP POLICY IF EXISTS "public_read_post_translations" ON post_translations;
CREATE POLICY "public_read_post_translations" ON post_translations
    FOR SELECT
    TO public
    USING (EXISTS (
        SELECT 1 FROM posts p WHERE p.id = post_translations.post_id AND p.status = 'published'
    ));

-- Admin write policies
DROP POLICY IF EXISTS "admin_all_posts" ON posts;
CREATE POLICY "admin_all_posts" ON posts
    FOR ALL
    TO authenticated
    USING (
        auth.jwt() ->> 'role' = 'admin' OR 
        (auth.jwt() -> 'user_metadata' ->> 'is_admin')::boolean = true OR
        EXISTS (SELECT 1 FROM profiles pr WHERE pr.id = auth.uid() AND (pr.subscription_plan = 'admin' OR (pr.contact ->> 'is_admin')::boolean = true))
    );

DROP POLICY IF EXISTS "admin_all_post_translations" ON post_translations;
CREATE POLICY "admin_all_post_translations" ON post_translations
    FOR ALL
    TO authenticated
    USING (
        auth.jwt() ->> 'role' = 'admin' OR 
        (auth.jwt() -> 'user_metadata' ->> 'is_admin')::boolean = true OR
        EXISTS (SELECT 1 FROM profiles pr WHERE pr.id = auth.uid() AND (pr.subscription_plan = 'admin' OR (pr.contact ->> 'is_admin')::boolean = true))
    );

-- Service-role full access
DROP POLICY IF EXISTS "service_all_posts" ON posts;
CREATE POLICY "service_all_posts" ON posts FOR ALL TO service_role USING (true);

DROP POLICY IF EXISTS "service_all_post_translations" ON post_translations;
CREATE POLICY "service_all_post_translations" ON post_translations FOR ALL TO service_role USING (true);
