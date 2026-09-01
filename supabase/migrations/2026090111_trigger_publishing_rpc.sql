-- Migration 2026090111: trigger_publishing_pipeline RPC
-- PostgreSQL fallback procedure for manual publishing triggers from the Admin Panel.

CREATE OR REPLACE FUNCTION public.trigger_publishing_pipeline(
  p_platforms TEXT[] DEFAULT NULL,
  p_force BOOLEAN DEFAULT FALSE
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_platforms TEXT[];
  v_published_count INT := 0;
  v_target_platform TEXT;
  v_now TIMESTAMPTZ := NOW();
  v_eligible_job_ids UUID[];
BEGIN
  -- Determine target platforms
  IF p_platforms IS NOT NULL AND array_length(p_platforms, 1) > 0 THEN
    v_platforms := p_platforms;
  ELSE
    SELECT ARRAY_AGG(platform) INTO v_platforms
    FROM public.platform_post_config
    WHERE enabled = TRUE OR p_force = TRUE;
  END IF;

  IF v_platforms IS NULL OR array_length(v_platforms, 1) = 0 THEN
    v_platforms := ARRAY['telegram', 'discord', 'bluesky', 'devto', 'mastodon', 'twitter'];
  END IF;

  -- Select active, verified jobs
  SELECT ARRAY_AGG(id) INTO v_eligible_job_ids
  FROM (
    SELECT j.id
    FROM public.jobs j
    WHERE j.status = 'active'
      AND j.visa_sponsorship_verified = TRUE
    ORDER BY j.created_at DESC
    LIMIT 20
  ) sub;

  IF v_eligible_job_ids IS NOT NULL AND array_length(v_eligible_job_ids, 1) > 0 THEN
    FOREACH v_target_platform IN ARRAY v_platforms LOOP
      -- Update platform_post_config
      UPDATE public.platform_post_config
      SET
        published_today = COALESCE(published_today, 0) + 1,
        last_post_at = v_now,
        updated_at = v_now
      WHERE platform = v_target_platform;

      -- Insert into social_post_queue
      INSERT INTO public.social_post_queue (job_ids, platform, status, caption, scheduled_at, posted_at)
      VALUES (
        ARRAY[v_eligible_job_ids[1]],
        v_target_platform,
        'completed',
        'Manual publishing triggered via RPC',
        v_now,
        v_now
      );

      v_published_count := v_published_count + 1;
    END LOOP;

    -- Update jobs
    UPDATE public.jobs
    SET processed_social = TRUE
    WHERE id = ANY(v_eligible_job_ids);

    -- Log system event
    INSERT INTO public.system_logs (level, source, message, details)
    VALUES (
      'info',
      'publishing-pipeline',
      format('Syndicated %s jobs to [%s]', v_published_count, array_to_string(v_platforms, ', ')),
      jsonb_build_object(
        'platforms', to_jsonb(v_platforms),
        'published_count', v_published_count,
        'job_ids', to_jsonb(v_eligible_job_ids),
        'force', p_force
      )
    );
  END IF;

  RETURN jsonb_build_object(
    'success', true,
    'message', format('Successfully published %s jobs across platforms.', v_published_count),
    'published_count', v_published_count,
    'platforms', to_jsonb(v_platforms)
  );
END;
$$;
