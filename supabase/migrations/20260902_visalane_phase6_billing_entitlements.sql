-- VisaLane Phase 6 Migration: Stripe Subscriptions, Entitlements & Usage Metering
-- Adds Stripe customer IDs, subscription status, employer badge status, and feature usage tracking.

-- 1. Profiles Table Extension
ALTER TABLE profiles 
ADD COLUMN IF NOT EXISTS stripe_customer_id text,
ADD COLUMN IF NOT EXISTS stripe_subscription_id text,
ADD COLUMN IF NOT EXISTS subscription_plan text DEFAULT 'free',
ADD COLUMN IF NOT EXISTS subscription_status text DEFAULT 'none',
ADD COLUMN IF NOT EXISTS current_period_end timestamptz;

CREATE INDEX IF NOT EXISTS idx_profiles_stripe_customer ON profiles(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_profiles_subscription ON profiles(subscription_plan, subscription_status);

-- 2. Companies Table Extension (Employer Monetization)
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS badge_status text DEFAULT 'none', -- 'none' | 'pending_review' | 'verified' | 'rejected'
ADD COLUMN IF NOT EXISTS badge_payment_status text DEFAULT 'unpaid', -- 'unpaid' | 'paid' | 'refunded'
ADD COLUMN IF NOT EXISTS employer_plan text DEFAULT 'free', -- 'free' | 'pro'
ADD COLUMN IF NOT EXISTS featured_until timestamptz;

CREATE INDEX IF NOT EXISTS idx_companies_badge ON companies(badge_status, badge_payment_status);
CREATE INDEX IF NOT EXISTS idx_companies_featured ON companies(featured_until);

-- 3. Feature Usage Metering Table (e.g. Free Tier 1 AI generation / week)
CREATE TABLE IF NOT EXISTS feature_usage (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE,
    feature_name text NOT NULL, -- e.g. 'ai_resume_generation'
    usage_count integer NOT NULL DEFAULT 1,
    period_start date NOT NULL,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    CONSTRAINT uq_user_feature_period UNIQUE (user_id, feature_name, period_start)
);

CREATE INDEX IF NOT EXISTS idx_feature_usage_user_feature ON feature_usage(user_id, feature_name, period_start);

-- 4. Processed Webhooks Table for Idempotency
CREATE TABLE IF NOT EXISTS billing_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    stripe_event_id text UNIQUE NOT NULL,
    event_type text NOT NULL,
    customer_id text,
    payload jsonb NOT NULL,
    processed_at timestamptz DEFAULT now(),
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_billing_events_event_type ON billing_events(event_type, created_at DESC);
