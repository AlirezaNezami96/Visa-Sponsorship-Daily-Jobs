-- Phase-4 extensions: OAuth profile sync, fresher flow, job skill matching,
-- resume parse metadata, pagination indexes, contact-finding improvements.
-- Builds on all prior migrations; safe to re-run (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).

-- ---------------------------------------------------------------------------
-- A. profiles — OAuth metadata + fresher flag
-- ---------------------------------------------------------------------------
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS oauth_provider       TEXT;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS oauth_provider_id    TEXT;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS oauth_profile_image  TEXT;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS last_login_at        TIMESTAMPTZ;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS login_count          INTEGER NOT NULL DEFAULT 0;

-- Fresher / resume-onboarding
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS is_fresher                    BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS parsed_resume                 JSONB;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS last_resume_parse             TIMESTAMPTZ;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS resume_onboarding_complete    BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS skills_cache                  TEXT[];
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS skills_cache_updated_at       TIMESTAMPTZ;

-- Unique index for OAuth provider+id pair (partial — NULL rows are excluded)
CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_oauth_provider_id
    ON profiles(oauth_provider, oauth_provider_id)
    WHERE oauth_provider IS NOT NULL;

-- Fast email lookup during OAuth account-linking
CREATE INDEX IF NOT EXISTS idx_profiles_email ON profiles(email);

-- GIN index for fast profile-skill matching
CREATE INDEX IF NOT EXISTS idx_profiles_parsed_resume ON profiles USING GIN (parsed_resume);
CREATE INDEX IF NOT EXISTS idx_profiles_skills_cache  ON profiles USING GIN (skills_cache);

-- ---------------------------------------------------------------------------
-- B. jobs — skill extraction
-- ---------------------------------------------------------------------------
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS skills                TEXT[];
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS skills_extracted_at   TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS skill_extraction_error TEXT;

-- GIN index on extracted skills array
CREATE INDEX IF NOT EXISTS idx_jobs_skills ON jobs USING GIN (skills);

-- Partial index: jobs that still need skill extraction
CREATE INDEX IF NOT EXISTS idx_jobs_pending_skill_extract ON jobs(created_at DESC)
    WHERE skills_extracted_at IS NULL AND status = 'active';

-- Composite indexes for common filter combos used by search-jobs
CREATE INDEX IF NOT EXISTS idx_jobs_status_posted
    ON jobs(status, posted_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_jobs_status_country_posted
    ON jobs(status, country, posted_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_jobs_status_work_mode_posted
    ON jobs(status, work_mode, posted_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_jobs_status_visa_posted
    ON jobs(status, visa_sponsorship_verified, posted_at DESC, id);

-- ---------------------------------------------------------------------------
-- C. resumes — parse metadata
-- ---------------------------------------------------------------------------
ALTER TABLE resumes ADD COLUMN IF NOT EXISTS file_type          TEXT;
ALTER TABLE resumes ADD COLUMN IF NOT EXISTS parse_status       TEXT NOT NULL DEFAULT 'pending'
    CHECK (parse_status IN ('pending','processing','completed','failed','partial'));
ALTER TABLE resumes ADD COLUMN IF NOT EXISTS parse_error        TEXT;
ALTER TABLE resumes ADD COLUMN IF NOT EXISTS parse_confidence   FLOAT CHECK (parse_confidence BETWEEN 0 AND 1);
ALTER TABLE resumes ADD COLUMN IF NOT EXISTS parse_warnings     TEXT[];
ALTER TABLE resumes ADD COLUMN IF NOT EXISTS sections_detected  TEXT[];
ALTER TABLE resumes ADD COLUMN IF NOT EXISTS parse_duration_ms  INTEGER;

CREATE INDEX IF NOT EXISTS idx_resumes_user_status ON resumes(user_id, parse_status);

-- ---------------------------------------------------------------------------
-- D. generated_documents — ATS scores + delete-previous support
-- ---------------------------------------------------------------------------
ALTER TABLE generated_documents ADD COLUMN IF NOT EXISTS ats_score_before   INTEGER CHECK (ats_score_before BETWEEN 0 AND 100);
ALTER TABLE generated_documents ADD COLUMN IF NOT EXISTS ats_score_after    INTEGER CHECK (ats_score_after  BETWEEN 0 AND 100);
ALTER TABLE generated_documents ADD COLUMN IF NOT EXISTS previous_document_id UUID REFERENCES generated_documents(id) ON DELETE SET NULL;
ALTER TABLE generated_documents ADD COLUMN IF NOT EXISTS generation_metadata JSONB;

-- Index for finding the most recent resume for a (user, job, format)
CREATE INDEX IF NOT EXISTS idx_gen_docs_latest
    ON generated_documents(user_id, job_id, document_type, format_type, created_at DESC);

-- ---------------------------------------------------------------------------
-- E. job_people — contact enrichment improvements
-- ---------------------------------------------------------------------------
ALTER TABLE job_people ADD COLUMN IF NOT EXISTS confidence_score INTEGER CHECK (confidence_score BETWEEN 0 AND 100);
ALTER TABLE job_people ADD COLUMN IF NOT EXISTS source_method    TEXT;
ALTER TABLE job_people ADD COLUMN IF NOT EXISTS found_at         TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE job_people ADD COLUMN IF NOT EXISTS metadata         JSONB;

CREATE INDEX IF NOT EXISTS idx_job_people_confidence ON job_people(confidence_score DESC);

-- ---------------------------------------------------------------------------
-- F. Trigger: update profile skills_cache when parsed_resume changes
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION sync_profile_skills_cache()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.parsed_resume IS DISTINCT FROM OLD.parsed_resume THEN
        NEW.skills_cache := ARRAY(
            SELECT DISTINCT jsonb_array_elements_text(
                COALESCE(NEW.parsed_resume -> 'skills', '[]'::jsonb)
            )
        );
        NEW.skills_cache_updated_at := NOW();
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_sync_skills_cache ON profiles;
CREATE TRIGGER trg_sync_skills_cache
    BEFORE UPDATE ON profiles
    FOR EACH ROW
    EXECUTE FUNCTION sync_profile_skills_cache();

-- ---------------------------------------------------------------------------
-- G. Function: atomically record OAuth login (upsert + increment login_count)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION record_oauth_login(
    p_user_id        UUID,
    p_provider       TEXT,
    p_provider_id    TEXT,
    p_profile_image  TEXT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    UPDATE profiles
    SET
        oauth_provider      = p_provider,
        oauth_provider_id   = p_provider_id,
        oauth_profile_image = COALESCE(p_profile_image, oauth_profile_image),
        last_login_at       = NOW(),
        login_count         = login_count + 1,
        updated_at          = NOW()
    WHERE id = p_user_id;
END $$;

REVOKE ALL ON FUNCTION record_oauth_login(UUID, TEXT, TEXT, TEXT) FROM anon;
GRANT EXECUTE ON FUNCTION record_oauth_login(UUID, TEXT, TEXT, TEXT) TO authenticated;
