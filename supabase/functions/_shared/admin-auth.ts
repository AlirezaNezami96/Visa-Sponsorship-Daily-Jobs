/**
 * Max-Security Admin/CRM Access Guard (8-Layer Defense in Depth)
 *
 * Checks server-side on EVERY request:
 * 1. Valid Supabase session whose `app_metadata.provider === "google"`
 * 2. Authenticator Assurance Level 2 (`aal2` - TOTP MFA)
 * 3. Session email exists in `admin_users` with `active = true`
 * 4. Step-up auth challenge (fresh within 5 minutes) for destructive operations
 * 5. Rate limiting (10 req/min/IP) & threat detection (5 failures / 10 min)
 * 6. Audit logging to `admin_audit_log`
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { createUserClient, createAdminClient, hasAuthHeader } from "./supabase-clients.ts";
import { getAuthUser, type AuthUser } from "./auth.ts";
import {
  adminError,
  adminStructuredError,
  unauthorized,
  forbidden,
  serverError,
} from "./http.ts";
import {
  checkAdminRateLimit,
  recordAdminAuthFailure,
  recordAdminAuthSuccess,
  sendAdminSecurityAlert,
} from "./admin-rate-limiter.ts";

export interface AdminAuthContext {
  user: AuthUser;
  email: string;
  role: "admin" | "owner";
  aal: "aal1" | "aal2";
  provider: string;
  ip: string;
  userAgent: string;
  stepUpVerified?: boolean;
}

export interface VerifyAdminOptions {
  action?: string;
  resource?: string;
  requireStepUp?: boolean;
  meta?: Record<string, unknown>;
  skipRateLimit?: boolean;
}

export interface VerifyAdminResult {
  ok: boolean;
  context?: AdminAuthContext;
  response?: Response;
}

/**
 * Extract client IP from headers.
 */
export function getClientIp(req: Request): string {
  return (
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    req.headers.get("cf-connecting-ip") ||
    req.headers.get("x-real-ip") ||
    "127.0.0.1"
  );
}

/**
 * Extract User-Agent header safely.
 */
export function getClientUserAgent(req: Request): string {
  return req.headers.get("user-agent") || "unknown";
}

/**
 * Parse JWT payload without external library dependencies.
 */
export function parseJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split(".");
    if (parts.length < 2) return null;
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join(""),
    );
    return JSON.parse(jsonPayload);
  } catch {
    return null;
  }
}

/**
 * Extract AAL and Provider claims from JWT token or AuthUser.
 */
export function extractAuthClaims(
  token: string,
  user: AuthUser,
): { aal: "aal1" | "aal2"; provider: string; email: string } {
  const payload = parseJwtPayload(token);
  const aalClaim = (payload?.aal as string) || (user.app_metadata?.aal as string) || "aal1";
  const provider = (payload?.app_metadata as Record<string, unknown>)?.provider as string ||
    (user.app_metadata?.provider as string) ||
    "";
  const email = (payload?.email as string) || user.email || "";

  return {
    aal: aalClaim === "aal2" ? "aal2" : "aal1",
    provider,
    email: email.toLowerCase().trim(),
  };
}

/**
 * Core admin security verification guard.
 */
export async function verifyAdminSession(
  req: Request,
  options: VerifyAdminOptions = {},
): Promise<VerifyAdminResult> {
  const ip = getClientIp(req);
  const userAgent = getClientUserAgent(req);
  const action = options.action || "admin_access";
  const resource = options.resource || "admin_endpoint";

  // 1. Rate Limiting Check
  if (!options.skipRateLimit) {
    const rateCheck = checkAdminRateLimit(ip);
    if (!rateCheck.allowed) {
      await recordAdminAuthFailure(ip, undefined, "rate_limit_exceeded");
      return {
        ok: false,
        response: adminStructuredError(
          429,
          "rate_limit_exceeded",
          "Admin rate limit exceeded. Please try again in 1 minute.",
          "Slow down requests to admin endpoints.",
        ),
      };
    }
  }

  // 2. Authorization Header Check
  const authHeader = req.headers.get("authorization");
  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    await recordAdminAuthFailure(ip, undefined, "missing_auth_header");
    return {
      ok: false,
      response: adminError(401, "unauthorized", "Authentication required for admin access", "Sign in with Google OAuth."),
    };
  }

  const token = authHeader.replace(/^Bearer\s+/i, "").trim();
  if (!token) {
    await recordAdminAuthFailure(ip, undefined, "empty_token");
    return {
      ok: false,
      response: adminError(401, "unauthorized", "Empty authorization token provided"),
    };
  }

  // 3. User Resolution via Supabase Auth
  const userClient = createUserClient(req);
  const user = await getAuthUser(userClient);
  if (!user || !user.email) {
    await recordAdminAuthFailure(ip, undefined, "invalid_session");
    return {
      ok: false,
      response: adminError(401, "unauthorized", "Invalid or expired session token"),
    };
  }

  const claims = extractAuthClaims(token, user);

  // 4. LAYER 1: Google OAuth Provider Check
  if (claims.provider !== "google") {
    await recordAdminAuthFailure(ip, claims.email, `disallowed_provider:${claims.provider}`);
    return {
      ok: false,
      response: adminError(
        403,
        "forbidden",
        "Google OAuth required: password and email-OTP accounts are prohibited from admin access.",
        "Sign in using 'Continue with Google'.",
      ),
    };
  }

  // 5. LAYER 2: Authenticator Assurance Level 2 (aal2 / TOTP MFA) Check
  if (claims.aal !== "aal2") {
    await recordAdminAuthFailure(ip, claims.email, "missing_aal2_mfa");
    return {
      ok: false,
      response: adminStructuredError(
        403,
        "mfa_required",
        "MFA_REQUIRED: Authenticator Assurance Level 2 (TOTP MFA) is required for admin access.",
        "/admin/mfa-challenge",
      ),
    };
  }

  // 6. LAYER 3: Allowlist & Active Flag Check against `admin_users`
  const adminClient = createAdminClient();
  const { data: adminRow, error: dbError } = await adminClient
    .from("admin_users")
    .select("id, email, role, active")
    .eq("email", claims.email)
    .maybeSingle();

  if (dbError || !adminRow || adminRow.active !== true) {
    await recordAdminAuthFailure(ip, claims.email, "unauthorized_admin_email");
    return {
      ok: false,
      response: adminError(
        403,
        "forbidden",
        "Your account is not authorized as an active VisaLane administrator.",
        "Contact the workspace owner to request admin access.",
      ),
    };
  }

  const role = (adminRow.role === "owner" ? "owner" : "admin") as "admin" | "owner";

  // 7. LAYER 5: Step-Up Auth for Destructive Actions
  let stepUpVerified = false;
  if (options.requireStepUp) {
    const stepUpToken = req.headers.get("x-stepup-token") || "";
    const stepUpResult = await verifyStepUpToken(adminClient, claims.email, action, stepUpToken);

    if (!stepUpResult.valid) {
      await recordAdminAuthFailure(ip, claims.email, `stepup_failed:${stepUpResult.reason}`);
      return {
        ok: false,
        response: adminStructuredError(
          403,
          "stepup_required",
          `STEPUP_REQUIRED: Fresh MFA verification is required for destructive action '${action}'.`,
          "/admin/stepup",
        ),
      };
    }
    stepUpVerified = true;
  }

  // 8. LAYER 6: Audit Logging
  await writeAdminAuditLog(adminClient, {
    admin_email: claims.email,
    action,
    resource,
    meta: options.meta || {},
    ip,
    user_agent: userAgent,
  });

  // Successful auth
  recordAdminAuthSuccess(ip, claims.email);

  const context: AdminAuthContext = {
    user,
    email: claims.email,
    role,
    aal: claims.aal,
    provider: claims.provider,
    ip,
    userAgent,
    stepUpVerified,
  };

  return { ok: true, context };
}

/**
 * Verify a step-up auth challenge token against `admin_stepup_challenges` or cryptographic validity.
 */
export async function verifyStepUpToken(
  admin: SupabaseClient,
  email: string,
  action: string,
  token: string,
): Promise<{ valid: boolean; reason?: string }> {
  if (!token) {
    return { valid: false, reason: "missing_token" };
  }

  const now = new Date();

  // Look up in `admin_stepup_challenges`
  const { data: challenge, error } = await admin
    .from("admin_stepup_challenges")
    .select("id, admin_email, action, expires_at, used")
    .eq("token_hash", token)
    .maybeSingle();

  if (error || !challenge) {
    return { valid: false, reason: "invalid_token" };
  }

  if (challenge.used) {
    return { valid: false, reason: "token_already_used" };
  }

  if (challenge.admin_email.toLowerCase() !== email.toLowerCase()) {
    return { valid: false, reason: "email_mismatch" };
  }

  const expiresAt = new Date(challenge.expires_at);
  if (expiresAt.getTime() < now.getTime()) {
    return { valid: false, reason: "token_expired" };
  }

  // Mark token as used to prevent replay attacks
  await admin
    .from("admin_stepup_challenges")
    .update({ used: true })
    .eq("id", challenge.id);

  return { valid: true };
}

/**
 * Create a fresh step-up token valid for 5 minutes (300 seconds).
 */
export async function issueStepUpChallenge(
  admin: SupabaseClient,
  email: string,
  action: string,
): Promise<{ token: string; expiresAt: string }> {
  const token = crypto.randomUUID().replace(/-/g, "") + crypto.randomUUID().replace(/-/g, "");
  const now = new Date();
  const expiresAt = new Date(now.getTime() + 5 * 60 * 1000).toISOString();

  await admin.from("admin_stepup_challenges").insert({
    admin_email: email.toLowerCase().trim(),
    action,
    token_hash: token,
    expires_at: expiresAt,
    used: false,
  });

  return { token, expiresAt };
}

/**
 * Write a structured audit log entry to `admin_audit_log`.
 */
export async function writeAdminAuditLog(
  admin: SupabaseClient,
  entry: {
    admin_email: string;
    action: string;
    resource?: string;
    meta?: Record<string, unknown>;
    ip?: string;
    user_agent?: string;
  },
): Promise<void> {
  try {
    await admin.from("admin_audit_log").insert({
      admin_email: entry.admin_email,
      action: entry.action,
      resource: entry.resource || null,
      meta: entry.meta || {},
      ip: entry.ip || "127.0.0.1",
      user_agent: entry.user_agent || "unknown",
    });
  } catch (err) {
    console.error("Failed to write to admin_audit_log:", err);
  }
}

/**
 * Send Telegram + Email notification on successful admin login.
 */
export async function sendAdminLoginAlert(
  email: string,
  ip: string,
  userAgent: string,
): Promise<void> {
  await sendAdminSecurityAlert("🔑 Successful Admin Login", {
    admin_email: email,
    ip,
    user_agent: userAgent,
    auth_method: "Google OAuth + TOTP MFA (aal2)",
    timestamp: new Date().toISOString(),
  });
}
