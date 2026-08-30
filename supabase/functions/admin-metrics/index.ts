/**
 * GET /functions/v1/admin-metrics
 * Admin-only metrics and system health endpoint.
 *
 * Auth options:
 *   1. User JWT with email matching a row in `admin_users` table.
 *   2. `x-admin-key` header matching the ADMIN_API_KEY secret.
 *
 * Query params:
 *   from   string (YYYY-MM-DD) — default: 7 days ago
 *   to     string (YYYY-MM-DD) — default: today
 *
 * Returns aggregated stats, pipeline health, circuit breaker states,
 * and recent quarantine items without any raw event table scans.
 */
import { createUserClient, createAdminClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { handleOptions, json, unauthorized, forbidden, serverError } from "../_shared/http.ts";
import { getEnv } from "../_shared/env.ts";

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

export async function verifyAdmin(req: Request): Promise<{ isAdmin: boolean; email?: string }> {
  // Option 1: Admin API Key header
  const adminKey = req.headers.get("x-admin-key");
  const expectedKey = getEnv("ADMIN_API_KEY");
  if (adminKey && expectedKey && adminKey === expectedKey) {
    return { isAdmin: true, email: "api-key-admin" };
  }

  // Option 2: JWT Auth
  if (!hasAuthHeader(req)) {
    return { isAdmin: false };
  }

  const userClient = createUserClient(req);
  const user = await getAuthUser(userClient);
  if (!user || !user.email) {
    return { isAdmin: false };
  }

  // Check admin_users table via adminClient
  const admin = createAdminClient();
  const { data } = await admin
    .from("admin_users")
    .select("email")
    .eq("email", user.email.toLowerCase().trim())
    .maybeSingle();

  if (data?.email) {
    return { isAdmin: true, email: user.email };
  }

  return { isAdmin: false, email: user.email };
}

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(async (req) => {
    const preflight = handleOptions(req);
    if (preflight) return preflight;

    if (req.method !== "GET") {
      return json({ error: { code: "method_not_allowed", message: "GET only" } }, { status: 405 });
    }

    try {
      const auth = await verifyAdmin(req);
      if (!auth.isAdmin) {
        if (!hasAuthHeader(req) && !req.headers.get("x-admin-key")) {
          return unauthorized("Authentication required to access admin metrics");
        }
        return forbidden("Your account is not authorized as an admin");
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
          .is_("resolved_at", null)
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

      return json(payload);
    } catch (err) {
      console.error("admin-metrics error:", err);
      return serverError("Failed to fetch admin metrics");
    }
  });
}
