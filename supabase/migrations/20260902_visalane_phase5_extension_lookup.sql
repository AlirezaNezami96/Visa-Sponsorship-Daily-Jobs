-- VisaLane Phase 5 Migration: Trigram Fuzzy Matching Index + Extension Analytics
-- Enables pg_trgm for fast sub-millisecond company name similarity queries and indexes extension events.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Trigram GIN index for fast fuzzy matching on company names
CREATE INDEX IF NOT EXISTS idx_companies_name_trgm 
ON companies USING gin (name gin_trgm_ops);

-- Partial index for extension analytics events (extension_badge_shown, extension_badge_clicked)
CREATE INDEX IF NOT EXISTS idx_events_extension_badges 
ON events(event_type, created_at DESC) 
WHERE event_type IN ('extension_badge_shown', 'extension_badge_clicked');

-- Function for backend trigram company matching query in PostgreSQL
CREATE OR REPLACE FUNCTION match_company_trigram(
    query_text text,
    similarity_threshold float DEFAULT 0.60
)
RETURNS TABLE (
    id uuid,
    name text,
    slug text,
    logo_url text,
    website text,
    ats_type text,
    similarity_score float
)
LANGUAGE sql
STABLE
AS $$
    SELECT 
        c.id,
        c.name,
        c.slug,
        c.logo_url,
        c.website,
        c.ats_type,
        similarity(c.name, query_text)::float AS similarity_score
    FROM companies c
    WHERE similarity(c.name, query_text) >= similarity_threshold
    ORDER BY similarity_score DESC
    LIMIT 1;
$$;
