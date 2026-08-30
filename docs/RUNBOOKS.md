# VisaLane Operational Runbooks

## 1. Inspecting Pipeline Health

### Via Supabase Edge Function
```bash
curl -H "x-admin-key: YOUR_ADMIN_API_KEY" \
  "https://YOUR_PROJECT_REF.supabase.co/functions/v1/admin-metrics?from=2026-08-25&to=2026-08-30"
```

### Via Supabase SQL Editor
```sql
-- Check current stage backlogs and health
SELECT * FROM pipeline_health ORDER BY stage;

-- Check any open or tripped circuit breakers
SELECT * FROM service_circuits WHERE state != 'closed';

-- View recent unhandled quarantined items
SELECT * FROM processing_quarantine WHERE resolved_at IS NULL ORDER BY created_at DESC LIMIT 20;

-- Check today's error rates
SELECT metric, count, error_count, (error_count::float / NULLIF(count, 0) * 100) AS err_rate
FROM metrics_daily
WHERE day = CURRENT_DATE
ORDER BY err_rate DESC NULLS LAST;
```

---

## 2. Retrying Quarantined Jobs

When a transient issue (e.g. storage outage or AI outage) has been resolved:

```sql
-- 1. Identify quarantined jobs for a stage
SELECT job_id, stage, reason, attempts FROM processing_quarantine WHERE resolved_at IS NULL;

-- 2. Reset the job in job_processing
UPDATE job_processing
SET metadata_status = 'pending', metadata_attempts = 0, metadata_last_error = NULL
WHERE job_id = 'YOUR_JOB_UUID';

-- Or for image stage:
UPDATE job_processing
SET image_status = 'pending', image_attempts = 0, image_last_error = NULL
WHERE job_id = 'YOUR_JOB_UUID';

-- 3. Mark the quarantine item as resolved
UPDATE processing_quarantine
SET resolved_at = NOW()
WHERE job_id = 'YOUR_JOB_UUID';
```

---

## 3. Resetting a Tripped Circuit Breaker

```sql
-- Manually close a circuit breaker
UPDATE service_circuits
SET state = 'closed', consecutive_failures = 0, opened_at = NULL, updated_at = NOW()
WHERE name = 'groq_api';
```

---

## 4. Adjusting Social Posting Pacing

```sql
-- Adjust posting rates or enable/disable a platform
UPDATE platform_post_config
SET min_gap_minutes = 15, daily_cap = 20, enabled = TRUE
WHERE platform = 'telegram';
```
