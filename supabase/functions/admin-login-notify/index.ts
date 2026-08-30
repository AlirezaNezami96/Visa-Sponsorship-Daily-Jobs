/**
 * POST /functions/v1/admin-login-notify
 * Login Notification & Alerting Endpoint.
 *
 * Dispatches Telegram & Email alerts upon successful admin authentication.
 */
import { handleOptions, adminJson, adminError, serverError } from "../_shared/http.ts";
import {
  verifyAdminSession,
  sendAdminLoginAlert,
} from "../_shared/admin-auth.ts";

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(async (req) => {
    const preflight = handleOptions(req);
    if (preflight) return preflight;

    if (req.method !== "POST") {
      return adminError(405, "method_not_allowed", "POST method only");
    }

    try {
      const authResult = await verifyAdminSession(req, {
        action: "login_notification",
        resource: "admin_auth",
        skipRateLimit: true,
      });

      if (!authResult.ok || !authResult.context) {
        return authResult.response || adminError(403, "forbidden", "Admin authorization required");
      }

      await sendAdminLoginAlert(
        authResult.context.email,
        authResult.context.ip,
        authResult.context.userAgent,
      );

      return adminJson({
        ok: true,
        message: "Login alert recorded and dispatched",
        admin_email: authResult.context.email,
        timestamp: new Date().toISOString(),
      });
    } catch (err) {
      console.error("admin-login-notify error:", err);
      return serverError("Failed to process login notification");
    }
  });
}
