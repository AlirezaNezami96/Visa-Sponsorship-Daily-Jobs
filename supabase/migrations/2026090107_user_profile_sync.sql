-- ===========================================================================
-- User Profile Sync & Auto-Creation Trigger
-- Ensures every auth.users row has a matching public.profiles row and
-- fixes usage_limits insert dependencies.
-- ===========================================================================

-- 1. Sync any existing auth.users that are missing from public.profiles
INSERT INTO public.profiles (id, email, created_at, updated_at)
SELECT id, email, created_at, created_at
FROM auth.users
ON CONFLICT (id) DO UPDATE
SET email = EXCLUDED.email
WHERE profiles.email IS NULL OR profiles.email = '';

-- 2. Trigger on auth.users for automatic profile creation
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
BEGIN
  INSERT INTO public.profiles (id, email, created_at, updated_at)
  VALUES (new.id, new.email, now(), now())
  ON CONFLICT (id) DO NOTHING;
  RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- 3. Update increment_usage_limit to ensure profile exists before inserting into usage_limits
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

    -- Ensure profile exists
    INSERT INTO public.profiles (id, created_at, updated_at)
    VALUES (v_user, NOW(), NOW())
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
