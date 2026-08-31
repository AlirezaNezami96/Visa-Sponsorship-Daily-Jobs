-- ===========================================================================
-- Fix increment_usage_limit profile insert email NOT NULL constraint
-- ===========================================================================

CREATE OR REPLACE FUNCTION increment_usage_limit(p_field TEXT, p_limit INTEGER)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
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

    -- Ensure profile exists with email from auth.users
    INSERT INTO public.profiles (id, email, created_at, updated_at)
    SELECT id, COALESCE(email, id::text || '@visalane.online'), NOW(), NOW()
    FROM auth.users
    WHERE id = v_user
    ON CONFLICT (id) DO NOTHING;

    -- Ensure daily usage row exists
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
