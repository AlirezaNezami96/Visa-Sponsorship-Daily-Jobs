-- Phase-4 completion migration:
--  - profiles: ai_features_enabled gate + trigger, resume_parse_warnings,
--    oauth_metadata (debugging/analytics per spec §1.2)
--  - user_job_scores: match-score cache table (spec §3.2) + TTL invalidation
--    triggers when profile skills or job skills change
--  - jobs: skills_updated_at bookkeeping for cache invalidation
-- Safe to re-run (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).

-- ---------------------------------------------------------------------------
-- A. profiles — AI feature gating (fresher flow spec §2.3)
-- ---------------------------------------------------------------------------
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS ai_features_enabled   BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS resume_parse_warnings TEXT[];
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS oauth_metadata        JSONB;

-- AI features are enabled only for complete, non-fresher profiles with a
-- parsed resume. Recomputed on every insert/update (spec §2.3 trigger).
CREATE OR REPLACE FUNCTION update_ai_features_enabled()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.ai_features_enabled := (
        COALESCE(NEW.profile_complete, FALSE)
        AND NEW.parsed_resume IS NOT NULL
        AND COALESCE(NEW.is_fresher, FALSE) = FALSE
    );
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trigger_update_ai_features ON profiles;
CREATE TRIGGER trigger_update_ai_features
    BEFORE INSERT OR UPDATE OF profile_complete, parsed_resume, is_fresher ON profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_ai_features_enabled();

-- ---------------------------------------------------------------------------
-- B. user_job_scores — per-(user, job) match-score cache (spec §3.2)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_job_scores (
    user_id     UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    job_id      UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    score       INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    match_label TEXT NOT NULL CHECK (match_label IN ('great_match','good_match','fair_match','low_match')),
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, job_id)
);

-- Index for TTL sweeps (stale rows are deleted by a periodic job or
-- lazily on read; NOW() cannot appear in an index predicate).
CREATE INDEX IF NOT EXISTS idx_user_job_scores_calculated_at
    ON user_job_scores(calculated_at);

GRANT SELECT, INSERT, UPDATE, DELETE ON user_job_scores TO authenticated;
REVOKE ALL ON user_job_scores FROM anon;

-- Invalidate cached scores when a user's skills change (profile skills cache
-- is maintained by trg_sync_skills_cache from the previous migration).
CREATE OR REPLACE FUNCTION invalidate_user_match_scores()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    DELETE FROM user_job_scores WHERE user_id = NEW.id;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_invalidate_scores_on_skills_change ON profiles;
CREATE TRIGGER trg_invalidate_scores_on_skills_change
    AFTER UPDATE OF skills_cache ON profiles
    FOR EACH ROW
    WHEN (NEW.skills_cache IS DISTINCT FROM OLD.skills_cache)
    EXECUTE FUNCTION invalidate_user_match_scores();

-- Invalidate cached scores when a job's skills change (spec §3.2 trigger).
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS skills_updated_at TIMESTAMPTZ;

CREATE OR REPLACE FUNCTION invalidate_job_match_scores()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NEW.skills IS DISTINCT FROM OLD.skills THEN
        NEW.skills_updated_at := NOW();
        DELETE FROM user_job_scores WHERE job_id = NEW.id;
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_invalidate_scores_on_job_skills ON jobs;
CREATE TRIGGER trg_invalidate_scores_on_job_skills
    BEFORE UPDATE OF skills ON jobs
    FOR EACH ROW
    EXECUTE FUNCTION invalidate_job_match_scores();

-- Bookkeeping for skills_updated_at on insert too
CREATE OR REPLACE FUNCTION set_skills_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.skills_extracted_at IS NOT NULL AND NEW.skills_updated_at IS NULL THEN
        NEW.skills_updated_at := NEW.skills_extracted_at;
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_set_skills_updated_at ON jobs;
CREATE TRIGGER trg_set_skills_updated_at
    BEFORE INSERT OR UPDATE OF skills_extracted_at ON jobs
    FOR EACH ROW
    EXECUTE FUNCTION set_skills_updated_at();

-- ---------------------------------------------------------------------------
-- C. RLS policies for user_job_scores (owner-only)
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS user_job_scores_owner_select ON user_job_scores;
CREATE POLICY user_job_scores_owner_select ON user_job_scores
    FOR SELECT TO authenticated
    USING (user_id = auth.uid());

DROP POLICY IF EXISTS user_job_scores_owner_write ON user_job_scores;
CREATE POLICY user_job_scores_owner_write ON user_job_scores
    FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());
