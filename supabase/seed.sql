-- Local development seed for `supabase db reset`.
-- Creates one demo auth user, a profile, sample companies/jobs, and an alert
-- so Edge Functions can be exercised locally without a live scrape.

-- Demo user (fixed UUID for reproducible local testing)
INSERT INTO auth.users (instance_id, id, aud, role, email, encrypted_password,
                        email_confirmed_at, created_at, updated_at,
                        confirmation_token, recovery_token, raw_app_meta_data, raw_user_meta_data)
VALUES ('00000000-0000-0000-0000-000000000000',
        '11111111-1111-4111-8111-111111111111',
        'authenticated', 'authenticated', 'demo@visalane.test',
        crypt('password123', gen_salt('bf')),
        NOW(), NOW(), NOW(), '', '',
        '{"provider":"email","providers":["email"]}', '{}')
ON CONFLICT (id) DO NOTHING;

INSERT INTO profiles (id, email, full_name, job_titles, skills, profile_complete)
VALUES ('11111111-1111-4111-8111-111111111111',
        'demo@visalane.test', 'Demo Candidate',
        ARRAY['Software Engineer'], ARRAY['TypeScript','React','Node.js'], TRUE)
ON CONFLICT (id) DO NOTHING;

INSERT INTO companies (id, name, website, ats_type)
VALUES ('22222222-2222-4222-8222-222222222222', 'Stripe', 'https://stripe.com', 'greenhouse'),
       ('33333333-3333-4333-8333-333333333333', 'Datadog', 'https://datadoghq.com', 'greenhouse')
ON CONFLICT (name, website) DO NOTHING;

INSERT INTO jobs (company_id, source_name, source_url, canonical_url_hash, fingerprint,
                  title, location_raw, country, country_code, work_mode,
                  visa_sponsorship_confidence, visa_sponsorship_verified, apply_url, posted_at)
SELECT c.id, 'seed', 'https://boards.greenhouse.io/stripe/jobs/demo1',
       encode(digest('https://boards.greenhouse.io/stripe/jobs/demo1', 'sha256'), 'hex'),
       'fp|seed-stripe-swe', 'Software Engineer, Payments', 'Remote - EMEA',
       'Germany', 'DE', 'remote', 92, TRUE,
       'https://boards.greenhouse.io/stripe/jobs/demo1', NOW() - INTERVAL '1 day'
FROM companies c WHERE c.name = 'Stripe'
ON CONFLICT (canonical_url_hash) DO NOTHING;

INSERT INTO jobs (company_id, source_name, source_url, canonical_url_hash, fingerprint,
                  title, location_raw, country, country_code, work_mode,
                  visa_sponsorship_confidence, visa_sponsorship_verified, apply_url, posted_at)
SELECT c.id, 'seed', 'https://boards.greenhouse.io/datadog/jobs/demo2',
       encode(digest('https://boards.greenhouse.io/datadog/jobs/demo2', 'sha256'), 'hex'),
       'fp|seed-datadog-swe', 'Backend Engineer', 'Berlin, Germany (Hybrid)',
       'Germany', 'DE', 'hybrid', 74, FALSE,
       'https://boards.greenhouse.io/datadog/jobs/demo2', NOW() - INTERVAL '2 days'
FROM companies c WHERE c.name = 'Datadog'
ON CONFLICT (canonical_url_hash) DO NOTHING;

INSERT INTO alerts (user_id, name, frequency, filters, channels)
VALUES ('11111111-1111-4111-8111-111111111111',
        'Remote backend in EU', 'daily',
        '{"keywords":["backend","engineer"],"countries":["DE"],"work_modes":["remote","hybrid"]}',
        '{"email":true}');
