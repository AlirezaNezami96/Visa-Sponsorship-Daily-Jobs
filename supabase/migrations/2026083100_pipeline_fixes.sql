-- Pipeline Fixes Migration (Phase 5.1)
-- Adds: slack_post_published, skill_extraction_error, job-cards bucket,
-- platform pending partial indexes, atomic record_metric RPC, and claim_next_post_job RPC.

-- 1. Missing columns on jobs
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS slack_post_published BOOLEAN DEFAULT FALSE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS skill_extraction_error TEXT;

-- 2. Storage bucket for job-cards
INSERT INTO storage.buckets (id, name, public)
VALUES ('job-cards', 'job-cards', TRUE)
ON CONFLICT (id) DO NOTHING;

DROP POLICY IF EXISTS "public_read_job_cards" ON storage.objects;
CREATE POLICY "public_read_job_cards" ON storage.objects
    FOR SELECT TO anon, authenticated
    USING (bucket_id = 'job-cards');

-- 3. Partial indexes for all social platform pending states
CREATE INDEX IF NOT EXISTS idx_jp_slack_pending ON job_processing(updated_at)
    WHERE slack_status = 'pending' AND post_text_status = 'done';
CREATE INDEX IF NOT EXISTS idx_jp_bluesky_pending ON job_processing(updated_at)
    WHERE bluesky_status = 'pending' AND post_text_status = 'done';
CREATE INDEX IF NOT EXISTS idx_jp_mastodon_pending ON job_processing(updated_at)
    WHERE mastodon_status = 'pending' AND post_text_status = 'done';
CREATE INDEX IF NOT EXISTS idx_jp_linkedin_pending ON job_processing(updated_at)
    WHERE linkedin_status = 'pending' AND post_text_status = 'done';
CREATE INDEX IF NOT EXISTS idx_jp_x_pending ON job_processing(updated_at)
    WHERE x_status = 'pending' AND post_text_status = 'done';

-- 4. Atomic record_metric RPC function
CREATE OR REPLACE FUNCTION record_metric(p_metric text, p_ok boolean, p_ms bigint DEFAULT 0)
RETURNS void LANGUAGE sql AS $$
  INSERT INTO metrics_daily (day, metric, count, error_count, sum_ms)
  VALUES (CURRENT_DATE, p_metric, 1, (NOT p_ok)::int, p_ms)
  ON CONFLICT (day, metric) DO UPDATE SET
    count = metrics_daily.count + 1,
    error_count = metrics_daily.error_count + (NOT p_ok)::int,
    sum_ms = metrics_daily.sum_ms + p_ms;
$$;

-- 5. Atomic claim_next_post_job RPC function using FOR UPDATE SKIP LOCKED
CREATE OR REPLACE FUNCTION claim_next_post_job(p_platform text)
RETURNS TABLE (
  job_id uuid,
  post_text text,
  image_url text
) LANGUAGE plpgsql AS $$
DECLARE
  v_job_id uuid;
  v_post_text text;
  v_image_url text;
BEGIN
  -- Lock and fetch the oldest pending post for the requested platform
  EXECUTE format(
    'SELECT jp.job_id, jp.post_text, j.image_url
     FROM job_processing jp
     JOIN jobs j ON j.id = jp.job_id
     WHERE jp.post_text_status = ''done''
       AND jp.%I_status = ''pending''
     ORDER BY jp.updated_at ASC
     LIMIT 1
     FOR UPDATE OF jp SKIP LOCKED',
    p_platform
  ) INTO v_job_id, v_post_text, v_image_url;

  IF v_job_id IS NOT NULL THEN
    EXECUTE format(
      'UPDATE job_processing SET %I_status = ''processing'', updated_at = NOW() WHERE job_id = $1',
      p_platform
    ) USING v_job_id;

    RETURN QUERY SELECT v_job_id, v_post_text, v_image_url;
  END IF;
END;
$$;
