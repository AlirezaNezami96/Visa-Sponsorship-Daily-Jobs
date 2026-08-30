/**
 * /functions/v1/admin-users
 * Admin Allowlist Management Endpoint.
 *
 * GET: Lists all admin accounts.
 * POST: Adds, modifies, or deactivates admin accounts (Owner only + Step-up MFA required).
 */
import { createAdminClient } from "../_shared/supabase-clients.ts";
import { handleOptions, adminJson, adminError, badRequest, serverError } from "../_shared/http.ts";
import { verifyAdminSession } from "../_shared/admin-auth.ts";

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(async (req) => {
    const preflight = handleOptions(req);
    if (preflight) return preflight;

    if (req.method === "GET") {
      try {
        const authResult = await verifyAdminSession(req, {
          action: "list_admin_users",
          resource: "admin_users",
        });

        if (!authResult.ok || !authResult.context) {
          return authResult.response || adminError(403, "forbidden", "Admin authorization required");
        }

        const admin = createAdminClient();
        const { data: users, error: dbError } = await admin
          .from("admin_users")
          .select("id, email, role, active, created_at")
          .order("created_at", { ascending: true });

        if (dbError) throw dbError;

        return adminJson({
          admins: users || [],
          count: users?.length || 0,
        });
      } catch (err) {
        console.error("admin-users GET error:", err);
        return serverError("Failed to fetch admin users");
      }
    }

    if (req.method === "POST") {
      try {
        const body = await req.json().catch(() => ({}));
        const email = String(body.email || "").toLowerCase().trim();
        const role = String(body.role || "admin").toLowerCase().trim();
        const active = typeof body.active === "boolean" ? body.active : true;
        const action = String(body.action || "upsert").toLowerCase().trim();

        if (!email || !email.includes("@")) {
          return badRequest("Valid email is required");
        }

        if (!["admin", "owner"].includes(role)) {
          return badRequest("Role must be 'admin' or 'owner'");
        }

        // Destructive action: Owner role AND Step-Up auth required
        const authResult = await verifyAdminSession(req, {
          action: `manage_admin_users:${action}`,
          resource: "admin_users",
          requireStepUp: true,
          meta: { target_email: email, target_role: role, target_active: active },
        });

        if (!authResult.ok || !authResult.context) {
          return authResult.response || adminError(403, "forbidden", "Admin authorization required");
        }

        if (authResult.context.role !== "owner") {
          return adminError(403, "forbidden", "Only workspace owners can modify the admin allowlist");
        }

        const admin = createAdminClient();

        if (action === "upsert") {
          const { data, error: dbError } = await admin
            .from("admin_users")
            .upsert(
              { email, role, active },
              { onConflict: "email" },
            )
            .select("id, email, role, active, created_at")
            .single();

          if (dbError) throw dbError;

          return adminJson({
            ok: true,
            action: "upserted",
            admin: data,
          });
        }

        if (action === "deactivate") {
          const { data, error: dbError } = await admin
            .from("admin_users")
            .update({ active: false })
            .eq("email", email)
            .select("id, email, role, active, created_at")
            .single();

          if (dbError) throw dbError;

          return adminJson({
            ok: true,
            action: "deactivated",
            admin: data,
          });
        }

        return badRequest(`Invalid action '${action}'. Supported: upsert, deactivate`);
      } catch (err) {
        console.error("admin-users POST error:", err);
        return serverError("Failed to manage admin allowlist");
      }
    }

    return adminError(405, "method_not_allowed", "GET or POST only");
  });
}
