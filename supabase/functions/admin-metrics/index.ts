/**
 * GET /functions/v1/admin-metrics
 * Hardened Admin Metrics & System Health Endpoint (Max Security)
 *
 * Enforces:
 * 1. Google OAuth session
 * 2. Authenticator Assurance Level 2 (aal2 - TOTP MFA)
 * 3. Active entry in admin_users allowlist
 * 4. Security headers (HSTS, CSP, X-Frame-Options DENY, nosniff, strict-origin)
 * 5. Rate limiting (10 req/min/IP)
 * 6. Audit logging on every access
 */
import { createAdminClient } from "../_shared/supabase-clients.ts";
import { handleOptions, adminJson, adminError, serverError } from "../_shared/http.ts";
import { verifyAdminSession, type AdminAuthContext } from "../_shared/admin-auth.ts";

export interface AdminMetricsPayload {
  range: { from: string; to: string };
  summary: {
    total_events: number;
    total_errors: number;
    error_rate_percent: number;
    avg_latency_ms: number;
  };
  pipeline_health: Array<Record<string, unknown>>;
  circuits: Array<Record<string, unknown>>;
  metrics_daily: Array<Record<string, unknown>>;
  quarantine: Array<Record<string, unknown>>;
}

export async function verifyAdmin(req: Request): Promise<{ isAdmin: boolean; email?: string; context?: AdminAuthContext }> {
  const result = await verifyAdminSession(req, {
    action: "read_admin_metrics",
    resource: "metrics_daily,pipeline_health,service_circuits,processing_quarantine",
  });
  if (!result.ok || !result.context) {
    return { isAdmin: false };
  }
  return { isAdmin: true, email: result.context.email, context: result.context };
}

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(async (req) => {
    const preflight = handleOptions(req);
    if (preflight) return preflight;

    if (req.method !== "GET") {
      return adminError(405, "method_not_allowed", "GET method only");
    }

    try {
      const authResult = await verifyAdminSession(req, {
        action: "read_admin_metrics",
        resource: "metrics_daily",
      });

      if (!authResult.ok || !authResult.context) {
        return authResult.response || adminError(403, "forbidden", "Admin authorization required");
      }

      const url = new URL(req.url);
      const today = new Date();
      const sevenDaysAgo = new Date();
      sevenDaysAgo.setDate(today.getDate() - 7);

      const defaultFrom = sevenDaysAgo.toISOString().split("T")[0];
      const defaultTo = today.toISOString().split("T")[0];

      const fromParam = url.searchParams.get("from") || defaultFrom;
      const toParam = url.searchParams.get("to") || defaultTo;

      const admin = createAdminClient();

      // Parallel queries
      const [metricsResp, healthResp, circuitsResp, quarantineResp] = await Promise.all([
        admin
          .from("metrics_daily")
          .select("*")
          .gte("day", fromParam)
          .lte("day", toParam)
          .order("day", { ascending: false })
          .order("metric"),
        admin
          .from("pipeline_health")
          .select("*")
          .order("stage"),
        admin
          .from("service_circuits")
          .select("*")
          .order("name"),
        admin
          .from("processing_quarantine")
          .select("id, job_id, stage, reason, attempts, created_at, resolved_at")
          .is("resolved_at", null)
          .order("created_at", { ascending: false })
          .limit(50),
      ]);

      const metricsDaily = metricsResp.data || [];
      const pipelineHealth = healthResp.data || [];
      const circuits = circuitsResp.data || [];
      const quarantine = quarantineResp.data || [];

      // Compute aggregate stats across range
      let totalEvents = 0;
      let totalErrors = 0;
      let totalSumMs = 0;

      for (const row of metricsDaily) {
        const count = Number(row.count || 0);
        const errs = Number(row.error_count || 0);
        const sumMs = Number(row.sum_ms || 0);
        totalEvents += count;
        totalErrors += errs;
        totalSumMs += sumMs;
      }

      const errorRatePercent = totalEvents > 0 ? Number(((totalErrors / totalEvents) * 100).toFixed(2)) : 0;
      const avgLatencyMs = totalEvents > 0 ? Math.round(totalSumMs / totalEvents) : 0;

      const payload: AdminMetricsPayload = {
        range: { from: fromParam, to: toParam },
        summary: {
          total_events: totalEvents,
          total_errors: totalErrors,
          error_rate_percent: errorRatePercent,
          avg_latency_ms: avgLatencyMs,
        },
        pipeline_health: pipelineHealth,
        circuits: circuits,
        metrics_daily: metricsDaily,
        quarantine: quarantine,
      };

      return adminJson(payload);
    } catch (err) {
      console.error("admin-metrics error:", err);
      return serverError("Failed to fetch admin metrics");
    }
  });
}
