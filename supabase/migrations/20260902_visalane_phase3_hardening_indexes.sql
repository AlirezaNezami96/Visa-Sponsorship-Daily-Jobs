-- Supabase Migration: VisaLane Phase 1-3 Performance & Search Optimization Indexes
-- Ensures high-throughput query performance without full table scans.

CREATE INDEX IF NOT EXISTS idx_jobs_posted_at ON jobs(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_work_mode ON jobs(work_mode);
CREATE INDEX IF NOT EXISTS idx_jobs_confidence ON jobs(visa_sponsorship_confidence DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_salary_max ON jobs(salary_max DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status_country ON jobs(status, country_code);
CREATE INDEX IF NOT EXISTS idx_jobs_status_posted ON jobs(status, posted_at DESC);
