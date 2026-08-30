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

---

## 5. Retrying Quarantine via Admin API
```bash
# Retry quarantined job
curl -X POST \
  -H "x-admin-key: YOUR_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"quarantine_id": "QUARANTINE_UUID", "action": "retry"}' \
  "https://YOUR_PROJECT_REF.supabase.co/functions/v1/admin-retry"

# Dismiss quarantined job
curl -X POST \
  -H "x-admin-key: YOUR_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"quarantine_id": "QUARANTINE_UUID", "action": "dismiss"}' \
  "https://YOUR_PROJECT_REF.supabase.co/functions/v1/admin-retry"
```

---

## 6. Schema Column Notes
- `applicants_count`: Intentionally `NULL` by default unless explicitly provided by upstream ATS scrapers (e.g. LinkedIn/Adzuna metadata).
- `skill_extraction_error`: Populated when AI/rule skill extraction finds no valid skills for a job description.

---

## 7. Max-Security Admin & CRM Operations

### Layer 8: Network Gate Setup (Cloudflare Access / Tailscale Zero Trust)
For maximum defense-in-depth protection, the `/admin` web routes and admin Edge Functions can be placed behind **Cloudflare Access Zero Trust**:
1. In Cloudflare Zero Trust dashboard, create an Application for `app.visalane.com/admin/*`.
2. Add Access Policy: Allow rule requiring Identity Provider (Google) and matching the exact owner/admin email allowlist.
3. Configure Service Token or JWT verification header (`Cf-Access-Jwt-Assertion`) forwarded to origin.
4. Result: Non-allowlisted traffic is terminated at Cloudflare's edge before ever reaching Supabase or the frontend server.

### Break-Glass Procedure (Emergency Admin Access)
If Google OAuth or TOTP MFA provider undergoes an outage and emergency database or pipeline access is required:
1. **Access Method**: Direct access via Supabase Dashboard SQL Editor using the Project Owner credentials (protected by hardware security key / backup MFA).
2. **Emergency Query**:
   ```sql
   -- View and inspect system status directly
   SELECT * FROM pipeline_health ORDER BY stage;
   SELECT * FROM processing_quarantine WHERE resolved_at IS NULL ORDER BY created_at DESC;

   -- Temporary emergency allowlist addition (if required)
   INSERT INTO public.admin_users (email, role, active)
   VALUES ('emergency-admin@visalane.com', 'admin', TRUE)
   ON CONFLICT (email) DO UPDATE SET active = TRUE;
   ```
3. **Post-Incident Remediation**:
   - Deactivate temporary credentials immediately after incident resolution:
     ```sql
     UPDATE public.admin_users SET active = FALSE WHERE email = 'emergency-admin@visalane.com';
     ```
   - Audit all actions taken in `public.admin_audit_log` during the window.

### Quarterly Admin Allowlist & MFA Review
Every 90 days, the workspace owner must execute the quarterly security audit:
1. Query active admins:
   ```sql
   SELECT id, email, role, active, created_at FROM public.admin_users ORDER BY created_at;
   ```
2. Deactivate any former contributors or unnecessary administrator privileges:
   ```sql
   UPDATE public.admin_users SET active = FALSE WHERE email = 'former-admin@visalane.com';
   ```
3. Review audit log anomalies:
   ```sql
   SELECT admin_email, action, resource, ip, count(*)
   FROM public.admin_audit_log
   WHERE created_at >= NOW() - INTERVAL '90 days'
   GROUP BY admin_email, action, resource, ip
   ORDER BY count(*) DESC;
   ```
4. Confirm all active admins have verified TOTP MFA factors in `auth.mfa_factors`.


