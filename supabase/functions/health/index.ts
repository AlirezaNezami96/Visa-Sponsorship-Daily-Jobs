/**
 * GET /functions/v1/health
 * Public health check endpoint for Upptime and system monitoring.
 */
import { handleOptions, json } from "../_shared/http.ts";

export const HEALTH_RESPONSE = {
  status: "ok",
  version: "1.0.0",
  service: "visalane-backend",
};

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve((req) => {
    const preflight = handleOptions(req);
    if (preflight) return preflight;

    if (req.method !== "GET" && req.method !== "HEAD") {
      return json({ error: { code: "method_not_allowed", message: "GET or HEAD only" } }, { status: 405 });
    }

    return json({
      ...HEALTH_RESPONSE,
      timestamp: new Date().toISOString(),
    });
  });
}
