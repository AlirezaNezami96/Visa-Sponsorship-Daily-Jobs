-- Supabase Migration: VisaLane Unified Backend Schema
-- Extends the existing migrations (source_posts, sent_jobs dedup) with the
-- FE-facing tables for the VisaLane product: jobs, companies, profiles,
-- resumes, generated documents, applications, saved jobs, contacts,
-- alerts, social queue, usage limits, analytics, feedback, scrape runs.
--
-- Design rules honored:
--   * No destructive changes to existing tables.
--   * The Python pipeline writes with the service-role key (bypasses RLS).
--   * FE reads user-owned data through PostgREST with owner-only RLS.
--   * jobs / companies are public-read.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- 0. updated_at trigger helper
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END $$;

-- ---------------------------------------------------------------------------
-- 1. companies
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    website TEXT,
    linkedin_url TEXT,
    logo_url TEXT,
    ats_type TEXT,                          -- greenhouse|lever|ashby|workable|smartrecruiters|personio|custom
    funding_info JSONB,                     -- from funding_scraper
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name, website)
);

DROP TRIGGER IF EXISTS trg_companies_updated_at ON companies;
CREATE TRIGGER trg_companies_updated_at
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 2. jobs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id) ON DELETE SET NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    canonical_url_hash TEXT UNIQUE NOT NULL,    -- sha256 of canonical URL (filters/dedupe normalization)
    fingerprint TEXT,                           -- (company,title,location) fingerprint from job_fingerprint()
    title TEXT NOT NULL,
    location_raw TEXT,
    city TEXT,
    country TEXT,
    country_code TEXT,
    work_mode TEXT,
    contract_type TEXT,
    salary_raw TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    salary_currency TEXT,
    description_text TEXT,
    description_html TEXT,
    requirements TEXT[],
    visa_sponsorship_confidence INTEGER CHECK (visa_sponsorship_confidence BETWEEN 0 AND 100),
    visa_sponsorship_verified BOOLEAN NOT NULL DEFAULT FALSE,
    visa_types TEXT[],
    apply_url TEXT NOT NULL,
    posted_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','expired','removed')),
    is_new BOOLEAN NOT NULL DEFAULT TRUE,
    processed_social BOOLEAN NOT NULL DEFAULT FALSE,
    processed_alerts BOOLEAN NOT NULL DEFAULT FALSE,
    processed_enrichment BOOLEAN NOT NULL DEFAULT FALSE,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_country ON jobs(country_code);
CREATE INDEX IF NOT EXISTS idx_jobs_visa_verified ON jobs(visa_sponsorship_verified);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint);
-- Queue-processing partial indexes (alert dispatch / social / enrichment workers)
CREATE INDEX IF NOT EXISTS idx_jobs_pending_alerts ON jobs(created_at DESC)
    WHERE processed_alerts = FALSE AND status = 'active';
CREATE INDEX IF NOT EXISTS idx_jobs_pending_social ON jobs(created_at DESC)
    WHERE processed_social = FALSE AND status = 'active';
CREATE INDEX IF NOT EXISTS idx_jobs_pending_enrichment ON jobs(created_at DESC)
    WHERE processed_enrichment = FALSE AND status = 'active';

DROP TRIGGER IF EXISTS trg_jobs_updated_at ON jobs;
CREATE TRIGGER trg_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 3. profiles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT,
    job_titles TEXT[],
    about_me TEXT,
    skills TEXT[],
    links JSONB,
    contact JSONB,
    resume_format_preference TEXT NOT NULL DEFAULT 'professional',
    remember_resume_format BOOLEAN NOT NULL DEFAULT FALSE,
    profile_complete BOOLEAN NOT NULL DEFAULT FALSE,
    subscription_plan TEXT NOT NULL DEFAULT 'free',
    trial_started_at TIMESTAMPTZ,
    trial_ends_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_profiles_updated_at ON profiles;
CREATE TRIGGER trg_profiles_updated_at
    BEFORE UPDATE ON profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 4. resumes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS resumes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_size INTEGER,
    raw_text TEXT,
    parsed_data JSONB,
    ats_baseline JSONB,                       -- from resume_matcher
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_resumes_user ON resumes(user_id);

-- ---------------------------------------------------------------------------
-- 5. generated_documents
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS generated_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    document_type TEXT NOT NULL CHECK (document_type IN ('resume','cover_letter','outreach_email','outreach_linkedin')),
    format_type TEXT CHECK (format_type IN ('own','professional')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','generating','completed','failed')),
    ai_provider TEXT,
    ai_model TEXT,
    prompt_version TEXT,
    input_profile_snapshot JSONB,
    output_json JSONB,
    file_path TEXT,
    file_size INTEGER,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gen_docs_user_job ON generated_documents(user_id, job_id);

DROP TRIGGER IF EXISTS trg_gen_docs_updated_at ON generated_documents;
CREATE TRIGGER trg_gen_docs_updated_at
    BEFORE UPDATE ON generated_documents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 6. applications
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'applied' CHECK (status IN ('applied','response','interview','offer','rejected')),
    resume_document_id UUID REFERENCES generated_documents(id) ON DELETE SET NULL,
    cover_letter_document_id UUID REFERENCES generated_documents(id) ON DELETE SET NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_applications_user ON applications(user_id, updated_at DESC);

DROP TRIGGER IF EXISTS trg_applications_updated_at ON applications;
CREATE TRIGGER trg_applications_updated_at
    BEFORE UPDATE ON applications
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 7. saved_jobs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS saved_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, job_id)
);

-- ---------------------------------------------------------------------------
-- 8. job_people (hiring contacts)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_people (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
    name TEXT,
    title TEXT,
    email TEXT,
    email_status TEXT CHECK (email_status IN ('verified','unverified','pattern_guess','generic','not_found')),
    email_confidence INTEGER CHECK (email_confidence BETWEEN 0 AND 100),
    linkedin_url TEXT,
    linkedin_search_url TEXT,
    source_url TEXT,
    source_type TEXT,
    confidence INTEGER CHECK (confidence BETWEEN 0 AND 100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_people_job ON job_people(job_id);
CREATE INDEX IF NOT EXISTS idx_job_people_company ON job_people(company_id);

-- ---------------------------------------------------------------------------
-- 9. alerts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    frequency TEXT NOT NULL CHECK (frequency IN ('instant','hourly','daily','weekly')),
    filters JSONB NOT NULL DEFAULT '{}',
    channels JSONB NOT NULL DEFAULT '{}',
    subject_template TEXT,
    content_template TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_user_active ON alerts(user_id) WHERE is_active = TRUE;

DROP TRIGGER IF EXISTS trg_alerts_updated_at ON alerts;
CREATE TRIGGER trg_alerts_updated_at
    BEFORE UPDATE ON alerts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 10. alert_sent_jobs (per-alert dedup)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_sent_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id UUID REFERENCES alerts(id) ON DELETE CASCADE,
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (alert_id, job_id)
);

-- ---------------------------------------------------------------------------
-- 11. social_post_queue
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS social_post_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_ids UUID[] NOT NULL,
    platform TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','completed','failed','manual_review')),
    caption TEXT,
    image_path TEXT,
    post_url TEXT,
    error_message TEXT,
    scheduled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_social_queue_pending ON social_post_queue(scheduled_at)
    WHERE status = 'pending';

-- ---------------------------------------------------------------------------
-- 12. usage_limits
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    resume_generations INTEGER NOT NULL DEFAULT 0,
    cover_letter_generations INTEGER NOT NULL DEFAULT 0,
    alert_sends INTEGER NOT NULL DEFAULT 0,
    import_attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, date)
);

DROP TRIGGER IF EXISTS trg_usage_limits_updated_at ON usage_limits;
CREATE TRIGGER trg_usage_limits_updated_at
    BEFORE UPDATE ON usage_limits
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 13. analytics_events (vendor-neutral; no Firebase)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analytics_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_name TEXT NOT NULL,
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_event_name ON analytics_events(event_name);
CREATE INDEX IF NOT EXISTS idx_analytics_created_at ON analytics_events(created_at DESC);

-- ---------------------------------------------------------------------------
-- 14. feedback
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE SET NULL,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    page TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 15. scrape_runs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scrape_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running','completed','failed')),
    jobs_found INTEGER NOT NULL DEFAULT 0,
    jobs_added INTEGER NOT NULL DEFAULT 0,
    jobs_updated INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_started ON scrape_runs(started_at DESC);

-- ---------------------------------------------------------------------------
-- 16. Row Level Security
-- ---------------------------------------------------------------------------

-- Public catalog tables: anyone can read, only service-role writes
-- (service_role bypasses RLS, so no write policies are defined).
ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_people ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "public_read_companies" ON companies;
CREATE POLICY "public_read_companies" ON companies
    FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "public_read_jobs" ON jobs;
CREATE POLICY "public_read_jobs" ON jobs
    FOR SELECT TO anon, authenticated USING (status <> 'removed');

DROP POLICY IF EXISTS "public_read_job_people" ON job_people;
CREATE POLICY "public_read_job_people" ON job_people
    FOR SELECT TO anon, authenticated USING (true);

-- User-owned tables: owner-only full access keyed on auth.uid().
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "owner_select_profile" ON profiles;
CREATE POLICY "owner_select_profile" ON profiles
    FOR SELECT TO authenticated USING (id = auth.uid());
DROP POLICY IF EXISTS "owner_insert_profile" ON profiles;
CREATE POLICY "owner_insert_profile" ON profiles
    FOR INSERT TO authenticated WITH CHECK (id = auth.uid());
DROP POLICY IF EXISTS "owner_update_profile" ON profiles;
CREATE POLICY "owner_update_profile" ON profiles
    FOR UPDATE TO authenticated USING (id = auth.uid()) WITH CHECK (id = auth.uid());
DROP POLICY IF EXISTS "owner_delete_profile" ON profiles;
CREATE POLICY "owner_delete_profile" ON profiles
    FOR DELETE TO authenticated USING (id = auth.uid());

ALTER TABLE resumes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "owner_all_resumes" ON resumes;
CREATE POLICY "owner_all_resumes" ON resumes
    FOR ALL TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

ALTER TABLE generated_documents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "owner_all_gen_docs" ON generated_documents;
CREATE POLICY "owner_all_gen_docs" ON generated_documents
    FOR ALL TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

ALTER TABLE applications ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "owner_all_applications" ON applications;
CREATE POLICY "owner_all_applications" ON applications
    FOR ALL TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

ALTER TABLE saved_jobs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "owner_all_saved_jobs" ON saved_jobs;
CREATE POLICY "owner_all_saved_jobs" ON saved_jobs
    FOR ALL TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "owner_all_alerts" ON alerts;
CREATE POLICY "owner_all_alerts" ON alerts
    FOR ALL TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

ALTER TABLE alert_sent_jobs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "owner_read_alert_sent" ON alert_sent_jobs;
CREATE POLICY "owner_read_alert_sent" ON alert_sent_jobs
    FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM alerts a WHERE a.id = alert_sent_jobs.alert_id AND a.user_id = auth.uid()));

ALTER TABLE usage_limits ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "owner_read_usage" ON usage_limits;
CREATE POLICY "owner_read_usage" ON usage_limits
    FOR SELECT TO authenticated USING (user_id = auth.uid());

ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "authenticated_insert_feedback" ON feedback;
CREATE POLICY "authenticated_insert_feedback" ON feedback
    FOR INSERT TO authenticated WITH CHECK (true);
DROP POLICY IF EXISTS "owner_select_feedback" ON feedback;
CREATE POLICY "owner_select_feedback" ON feedback
    FOR SELECT TO authenticated USING (user_id = auth.uid());

-- Pipeline/system tables: no anon/authenticated access at all
-- (RLS enabled, zero policies => only service_role can touch them).
ALTER TABLE social_post_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE scrape_runs ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- 17. Usage-limit atomic increment (race-free, whitelist-guarded)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION increment_usage_limit(p_field TEXT, p_limit INTEGER)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_user UUID := auth.uid();
    v_current INTEGER;
    v_allowed BOOLEAN;
BEGIN
    IF v_user IS NULL THEN
        RAISE EXCEPTION 'not authenticated' USING ERRCODE = '42501';
    END IF;
    IF p_field NOT IN ('resume_generations','cover_letter_generations','alert_sends','import_attempts') THEN
        RAISE EXCEPTION 'invalid usage-limit field: %', p_field;
    END IF;
    IF p_limit <= 0 THEN
        RAISE EXCEPTION 'limit must be positive';
    END IF;

    INSERT INTO usage_limits (user_id, date)
    VALUES (v_user, CURRENT_DATE)
    ON CONFLICT (user_id, date) DO NOTHING;

    EXECUTE format(
        'UPDATE usage_limits SET %I = %I + 1, updated_at = NOW()
         WHERE user_id = $1 AND date = CURRENT_DATE AND %I < $2
         RETURNING %I', p_field, p_field, p_field, p_field
    ) USING v_user, p_limit
    INTO v_current;

    IF v_current IS NULL THEN
        EXECUTE format(
            'SELECT %I FROM usage_limits WHERE user_id = $1 AND date = CURRENT_DATE', p_field
        ) USING v_user INTO v_current;
        v_allowed := FALSE;
    ELSE
        v_allowed := TRUE;
    END IF;

    RETURN jsonb_build_object(
        'allowed', v_allowed,
        'count', COALESCE(v_current, 0),
        'limit', p_limit
    );
END $$;

REVOKE ALL ON FUNCTION increment_usage_limit(TEXT, INTEGER) FROM anon;
GRANT EXECUTE ON FUNCTION increment_usage_limit(TEXT, INTEGER) TO authenticated;

-- ---------------------------------------------------------------------------
-- 18. Social queue atomic claim (worker-safe reservation)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION claim_social_posts(p_platform TEXT, p_max INTEGER DEFAULT 5)
RETURNS SETOF social_post_queue
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    WITH claimed AS (
        SELECT q.id
        FROM social_post_queue q
        WHERE q.status = 'pending'
          AND q.platform = p_platform
          AND q.scheduled_at <= NOW()
        ORDER BY q.scheduled_at
        FOR UPDATE SKIP LOCKED
        LIMIT p_max
    )
    UPDATE social_post_queue q
    SET status = 'processing'
    FROM claimed
    WHERE q.id = claimed.id
    RETURNING q.*;
END $$;

REVOKE ALL ON FUNCTION claim_social_posts(TEXT, INTEGER) FROM anon, authenticated;

-- ---------------------------------------------------------------------------
-- 19. Storage buckets (resumes, generated documents, social images)
-- ---------------------------------------------------------------------------
INSERT INTO storage.buckets (id, name, public)
VALUES ('resumes', 'resumes', FALSE)
ON CONFLICT (id) DO NOTHING;

INSERT INTO storage.buckets (id, name, public)
VALUES ('generated-documents', 'generated-documents', FALSE)
ON CONFLICT (id) DO NOTHING;

INSERT INTO storage.buckets (id, name, public)
VALUES ('social-images', 'social-images', TRUE)
ON CONFLICT (id) DO NOTHING;

-- Storage policies: users manage their own folder only; service_role bypasses.
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "users_read_own_resumes" ON storage.objects;
CREATE POLICY "users_read_own_resumes" ON storage.objects
    FOR SELECT TO authenticated
    USING (bucket_id IN ('resumes','generated-documents')
           AND (storage.foldername(name))[1] = auth.uid()::text);

DROP POLICY IF EXISTS "users_write_own_resumes" ON storage.objects;
CREATE POLICY "users_write_own_resumes" ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (bucket_id IN ('resumes','generated-documents')
                AND (storage.foldername(name))[1] = auth.uid()::text);

DROP POLICY IF EXISTS "users_delete_own_resumes" ON storage.objects;
CREATE POLICY "users_delete_own_resumes" ON storage.objects
    FOR DELETE TO authenticated
    USING (bucket_id IN ('resumes','generated-documents')
           AND (storage.foldername(name))[1] = auth.uid()::text);

DROP POLICY IF EXISTS "public_read_social_images" ON storage.objects;
CREATE POLICY "public_read_social_images" ON storage.objects
    FOR SELECT TO anon, authenticated
    USING (bucket_id = 'social-images');
