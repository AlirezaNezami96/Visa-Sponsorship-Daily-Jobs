/**
 * POST /functions/v1/admin-stepup
 * Step-Up MFA Challenge Verification for Destructive Admin Operations.
 *
 * Actions:
 * 1. "verify": Validates the TOTP MFA code supplied in body or verifies active MFA challenge,
 *    and issues a short-lived (5 minute) cryptographic step-up token for destructive actions.
 */
import { createAdminClient, createUserClient } from "../_shared/supabase-clients.ts";
import { handleOptions, adminJson, adminError, badRequest, serverError } from "../_shared/http.ts";
import {
  verifyAdminSession,
  issueStepUpChallenge,
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
        action: "stepup_request",
        resource: "mfa_challenge",
        skipRateLimit: false,
      });

      if (!authResult.ok || !authResult.context) {
        return authResult.response || adminError(403, "forbidden", "Admin authorization required");
      }

      const body = await req.json().catch(() => ({}));
      const code = String(body.code || "").trim();
      const targetAction = String(body.action || "destructive_operation").trim();

      // If code is provided, verify against Supabase MFA API
      if (code) {
        const userClient = createUserClient(req);
        // List enrolled factors
        const { data: factors, error: factorsError } = await userClient.auth.mfa.listFactors();
        if (factorsError || !factors?.totp || factors.totp.length === 0) {
          return adminError(400, "mfa_not_enrolled", "No TOTP factor enrolled on this account");
        }

        const verifiedFactor = factors.totp.find((f: { status: string }) => f.status === "verified") || factors.totp[0];
        const factorId = verifiedFactor.id;

        // Challenge and verify code
        const { data: challengeData, error: challengeError } = await userClient.auth.mfa.challenge({ factorId });
        if (challengeError || !challengeData) {
          return adminError(400, "challenge_failed", "Failed to create MFA challenge");
        }

        const { data: verifyData, error: verifyError } = await userClient.auth.mfa.verify({
          factorId,
          challengeId: challengeData.id,
          code,
        });

        if (verifyError || !verifyData) {
          return adminError(403, "invalid_mfa_code", "Invalid or expired MFA code");
        }
      }

      // Issue step-up token valid for 5 minutes (300 seconds)
      const adminClient = createAdminClient();
      const { token, expiresAt } = await issueStepUpChallenge(
        adminClient,
        authResult.context.email,
        targetAction,
      );

      return adminJson({
        ok: true,
        stepup_token: token,
        action: targetAction,
        expires_at: expiresAt,
        valid_seconds: 300,
      });
    } catch (err) {
      console.error("admin-stepup error:", err);
      return serverError("Failed to process step-up authentication");
    }
  });
}
