/**
 * GET /functions/v1/admin-audit
 * Admin Audit Log Viewer Endpoint.
 *
 * Query params:
 *   email   string (optional filter)
 *   action  string (optional filter)
 *   limit   number (default 50, max 200)
 */
import { createAdminClient } from "../_shared/supabase-clients.ts";
import { handleOptions, adminJson, adminError, serverError } from "../_shared/http.ts";
import { verifyAdminSession } from "../_shared/admin-auth.ts";

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(async (req) => {
    const preflight = handleOptions(req);
    if (preflight) return preflight;

    if (req.method !== "GET") {
      return adminError(405, "method_not_allowed", "GET method only");
    }

    try {
      const authResult = await verifyAdminSession(req, {
        action: "read_audit_log",
        resource: "admin_audit_log",
      });

      if (!authResult.ok || !authResult.context) {
        return authResult.response || adminError(403, "forbidden", "Admin authorization required");
      }

      const url = new URL(req.url);
      const emailFilter = url.searchParams.get("email");
      const actionFilter = url.searchParams.get("action");
      const limit = Math.min(200, Math.max(1, parseInt(url.searchParams.get("limit") || "50", 10)));

      const admin = createAdminClient();
      let query = admin
        .from("admin_audit_log")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(limit);

      if (emailFilter) {
        query = query.eq("admin_email", emailFilter.toLowerCase().trim());
      }
      if (actionFilter) {
        query = query.eq("action", actionFilter);
      }

      const { data: logs, error: dbError } = await query;
      if (dbError) {
        throw dbError;
      }

      return adminJson({
        logs: logs || [],
        count: logs?.length || 0,
        filters: { email: emailFilter, action: actionFilter, limit },
      });
    } catch (err) {
      console.error("admin-audit error:", err);
      return serverError("Failed to fetch admin audit logs");
    }
  });
}
