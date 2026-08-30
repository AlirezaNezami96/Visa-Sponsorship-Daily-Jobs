/**
 * POST /functions/v1/admin-retry
 * Admin-only endpoint to retry or dismiss quarantined jobs.
 *
 * Body:
 * {
 *   quarantine_id?: string,
 *   job_id?: string,
 *   stage?: string,
 *   action: "retry" | "dismiss"
 * }
 */
import { createAdminClient } from "../_shared/supabase-clients.ts";
import { handleOptions, json, badRequest, unauthorized, forbidden, serverError } from "../_shared/http.ts";
import { verifyAdmin } from "../admin-metrics/index.ts";

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(async (req) => {
    const preflight = handleOptions(req);
    if (preflight) return preflight;

    if (req.method !== "POST") {
      return json({ error: { code: "method_not_allowed", message: "POST only" } }, { status: 405 });
    }

    try {
      const auth = await verifyAdmin(req);
      if (!auth.isAdmin) {
        return forbidden("Admin authorization required to retry or dismiss quarantine items");
      }

      const body = await req.json().catch(() => ({}));
      const action = String(body.action || "retry").toLowerCase();
      const quarantineId = body.quarantine_id ? String(body.quarantine_id) : null;
      let jobId = body.job_id ? String(body.job_id) : null;
      let stage = body.stage ? String(body.stage) : null;

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

        return json({
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

        return json({
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
