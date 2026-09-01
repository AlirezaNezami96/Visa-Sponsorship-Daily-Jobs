-- Migration 2026090112: Seed Initial Publishing Pipeline System Logs
-- Provides operational telemetry entries for the System Observability & Logs dashboard.

INSERT INTO public.system_logs (level, source, message, details, environment, created_at)
VALUES
  (
    'info',
    'publishing-pipeline',
    'Syndicated 6 jobs across [Telegram, Discord, Bluesky, Dev.to, Mastodon, X]',
    jsonb_build_object(
      'platforms', jsonb_build_array('telegram', 'discord', 'bluesky', 'devto', 'mastodon', 'twitter'),
      'published_count', 6,
      'triggered_by', 'alireza@visalane.app',
      'force', true,
      'jobs', jsonb_build_array(
        jsonb_build_object('title', 'Senior Backend Engineer', 'company', 'Stripe', 'apply_url', 'https://stripe.com/jobs/123'),
        jsonb_build_object('title', 'AI Research Scientist', 'company', 'Google DeepMind', 'apply_url', 'https://deepmind.google/careers/456')
      )
    ),
    'production',
    NOW() - INTERVAL '15 minutes'
  ),
  (
    'info',
    'publishing-pipeline',
    'Successfully posted 2 verified role(s) to Telegram (@visalane)',
    jsonb_build_object(
      'platform', 'telegram',
      'display_name', 'Telegram',
      'post_url', 'https://t.me/visalane/104',
      'triggered_by', 'alireza@visalane.app',
      'jobs', jsonb_build_array(
        jsonb_build_object('title', 'Senior Backend Engineer', 'company', 'Stripe', 'apply_url', 'https://stripe.com/jobs/123'),
        jsonb_build_object('title', 'AI Research Scientist', 'company', 'Google DeepMind', 'apply_url', 'https://deepmind.google/careers/456')
      )
    ),
    'production',
    NOW() - INTERVAL '14 minutes'
  ),
  (
    'info',
    'publishing-pipeline',
    'Successfully posted 1 verified role(s) to Discord (#visa-jobs)',
    jsonb_build_object(
      'platform', 'discord',
      'display_name', 'Discord',
      'post_url', 'https://discord.com/channels/123456789/987654321',
      'triggered_by', 'alireza@visalane.app',
      'jobs', jsonb_build_array(
        jsonb_build_object('title', 'Senior Backend Engineer', 'company', 'Stripe', 'apply_url', 'https://stripe.com/jobs/123')
      )
    ),
    'production',
    NOW() - INTERVAL '13 minutes'
  ),
  (
    'warn',
    'publishing-pipeline',
    'Pacing check: skipped platform linkedin (Minimum gap not elapsed)',
    jsonb_build_object(
      'platform', 'linkedin',
      'reason', 'Minimum gap not elapsed (120 min gap required)',
      'published_today', 2,
      'daily_cap', 3
    ),
    'production',
    NOW() - INTERVAL '12 minutes'
  )
ON CONFLICT DO NOTHING;
