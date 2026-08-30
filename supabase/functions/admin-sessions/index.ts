/**
 * /functions/v1/admin-sessions
 * Admin Session Management Endpoint.
 *
 * GET: Lists active session metadata for current admin.
 * POST: Revokes specific session or all sessions (Revoke All requires step-up).
 */
import { createUserClient, createAdminClient } from "../_shared/supabase-clients.ts";
import { handleOptions, adminJson, adminError, badRequest, serverError } from "../_shared/http.ts";
import { verifyAdminSession } from "../_shared/admin-auth.ts";

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(async (req) => {
    const preflight = handleOptions(req);
    if (preflight) return preflight;

    if (req.method === "GET") {
      try {
        const authResult = await verifyAdminSession(req, {
          action: "list_sessions",
          resource: "admin_sessions",
        });

        if (!authResult.ok || !authResult.context) {
          return authResult.response || adminError(403, "forbidden", "Admin authorization required");
        }

        // Return current session info and active factor status
        const userClient = createUserClient(req);
        const { data: factors } = await userClient.auth.mfa.listFactors();

        const sessionPayload = {
          current_session: {
            email: authResult.context.email,
            role: authResult.context.role,
            aal: authResult.context.aal,
            provider: authResult.context.provider,
            ip: authResult.context.ip,
            user_agent: authResult.context.userAgent,
            timestamp: new Date().toISOString(),
          },
          mfa_factors: factors?.totp || [],
        };

        return adminJson(sessionPayload);
      } catch (err) {
        console.error("admin-sessions GET error:", err);
        return serverError("Failed to fetch admin sessions");
      }
    }

    if (req.method === "POST") {
      try {
        const body = await req.json().catch(() => ({}));
        const action = String(body.action || "revoke_all").toLowerCase();

        // Destructive action: Revoking sessions requires step-up auth
        const authResult = await verifyAdminSession(req, {
          action: `session_${action}`,
          resource: "admin_sessions",
          requireStepUp: true,
          meta: { action },
        });

        if (!authResult.ok || !authResult.context) {
          return authResult.response || adminError(403, "forbidden", "Admin authorization required");
        }

        const admin = createAdminClient();
        const userClient = createUserClient(req);

        if (action === "revoke_all") {
          // Sign out user globally via admin client
          await admin.auth.admin.signOut(authResult.context.user.id, "global");

          return adminJson({
            ok: true,
            action: "revoked_all_sessions",
            email: authResult.context.email,
            timestamp: new Date().toISOString(),
          });
        }

        return badRequest(`Invalid session action '${action}'. Supported: revoke_all`);
      } catch (err) {
        console.error("admin-sessions POST error:", err);
        return serverError("Failed to revoke admin sessions");
      }
    }

    return adminError(405, "method_not_allowed", "GET or POST only");
  });
}
