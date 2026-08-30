/**
 * POST /functions/v1/admin-retry
 * Hardened Admin Endpoint to Retry or Dismiss Quarantined Jobs.
 *
 * Enforces:
 * 1. Google OAuth session
 * 2. Authenticator Assurance Level 2 (aal2 - TOTP MFA)
 * 3. Active entry in admin_users allowlist
 * 4. Fresh Step-Up MFA Challenge token (within last 5 minutes) for destructive operation
 * 5. Security headers (HSTS, CSP, X-Frame-Options DENY, nosniff, strict-origin)
 * 6. Rate limiting (10 req/min/IP)
 * 7. Audit logging to admin_audit_log
 */
import { createAdminClient } from "../_shared/supabase-clients.ts";
import { handleOptions, adminJson, adminError, badRequest, serverError } from "../_shared/http.ts";
import { verifyAdminSession } from "../_shared/admin-auth.ts";

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(async (req) => {
    const preflight = handleOptions(req);
    if (preflight) return preflight;

    if (req.method !== "POST") {
      return adminError(405, "method_not_allowed", "POST method only");
    }

    try {
      const body = await req.json().catch(() => ({}));
      const action = String(body.action || "retry").toLowerCase();
      const quarantineId = body.quarantine_id ? String(body.quarantine_id) : null;
      let jobId = body.job_id ? String(body.job_id) : null;
      let stage = body.stage ? String(body.stage) : null;

      const authResult = await verifyAdminSession(req, {
        action: `quarantine_${action}`,
        resource: "processing_quarantine",
        requireStepUp: true,
        meta: { action, quarantine_id: quarantineId, job_id: jobId, stage },
      });

      if (!authResult.ok || !authResult.context) {
        return authResult.response || adminError(403, "forbidden", "Admin authorization required");
      }

      if (!quarantineId && (!jobId || !stage)) {
        return badRequest("Either 'quarantine_id' or both 'job_id' and 'stage' are required");
      }

      const admin = createAdminClient();
      const nowIso = new Date().toISOString();

      if (quarantineId && (!jobId || !stage)) {
        const { data: qRow } = await admin
          .from("processing_quarantine")
          .select("job_id, stage")
          .eq("id", quarantineId)
          .maybeSingle();

        if (qRow) {
          jobId = qRow.job_id;
          stage = qRow.stage;
        }
      }

      if (action === "retry") {
        if (jobId && stage) {
          const statusCol = `${stage}_status`;
          const attemptsCol = `${stage}_attempts`;
          const errorCol = `${stage}_last_error`;

          const updatePayload: Record<string, unknown> = {
            [statusCol]: "pending",
            updated_at: nowIso,
          };
          if (stage === "metadata" || stage === "image") {
            updatePayload[attemptsCol] = 0;
            updatePayload[errorCol] = null;
          }

          await admin
            .from("job_processing")
            .update(updatePayload)
            .eq("job_id", jobId);
        }

        if (quarantineId) {
          await admin
            .from("processing_quarantine")
            .update({ resolved_at: nowIso })
            .eq("id", quarantineId);
        } else if (jobId) {
          await admin
            .from("processing_quarantine")
            .update({ resolved_at: nowIso })
            .eq("job_id", jobId)
            .is("resolved_at", null);
        }

        return adminJson({
          ok: true,
          action: "retried",
          job_id: jobId,
          stage: stage,
          timestamp: nowIso,
        });
      }

      if (action === "dismiss") {
        if (quarantineId) {
          await admin
            .from("processing_quarantine")
            .update({ resolved_at: nowIso })
            .eq("id", quarantineId);
        } else if (jobId) {
          await admin
            .from("processing_quarantine")
            .update({ resolved_at: nowIso })
            .eq("job_id", jobId)
            .is("resolved_at", null);
        }

        return adminJson({
          ok: true,
          action: "dismissed",
          quarantine_id: quarantineId,
          job_id: jobId,
          timestamp: nowIso,
        });
      }

      return badRequest(`Invalid action '${action}'. Supported: retry, dismiss`);
    } catch (err) {
      console.error("admin-retry error:", err);
      return serverError("Failed to perform quarantine action");
    }
  });
}
