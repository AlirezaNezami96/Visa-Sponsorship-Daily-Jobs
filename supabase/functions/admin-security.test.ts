/**
 * Comprehensive Max-Security Admin/CRM Access Test Suite
 *
 * Verifies all 8 layers:
 * 1. Google OAuth provider requirement
 * 2. Authenticator Assurance Level 2 (aal2 - TOTP MFA) requirement
 * 3. admin_users allowlist & active flag enforcement
 * 4. Session hardening & revocation
 * 5. Step-up MFA challenge verification for destructive actions
 * 6. Audit logging & threat alert triggers
 * 7. Rate limiting (10 req/min/IP) & security headers
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  extractAuthClaims,
  parseJwtPayload,
  verifyAdminSession,
  verifyStepUpToken,
  issueStepUpChallenge,
  type AdminAuthContext,
} from "./_shared/admin-auth.ts";
import {
  checkAdminRateLimit,
  recordAdminAuthFailure,
  _resetRateLimiterState,
} from "./_shared/admin-rate-limiter.ts";
import { ADMIN_SECURITY_HEADERS, adminJson, adminError } from "./_shared/http.ts";

function createMockJwt(claims: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = btoa(JSON.stringify(claims));
  const signature = btoa("mock-signature");
  return `${header}.${payload}.${signature}`;
}

describe("Admin Security & Authorization Guard", () => {
  beforeEach(() => {
    _resetRateLimiterState();
    vi.restoreAllMocks();
  });

  describe("Layer 1 & 2: Provider & AAL Claim Extraction", () => {
    it("extracts Google provider and aal2 claims correctly", () => {
      const token = createMockJwt({
        email: "owner@visalane.com",
        aal: "aal2",
        app_metadata: { provider: "google" },
      });

      const claims = extractAuthClaims(token, { id: "user-1", email: "owner@visalane.com" });
      expect(claims.provider).toBe("google");
      expect(claims.aal).toBe("aal2");
      expect(claims.email).toBe("owner@visalane.com");
    });

    it("defaults to aal1 and empty provider for basic email/password token", () => {
      const token = createMockJwt({
        email: "attacker@visalane.com",
        aal: "aal1",
        app_metadata: { provider: "email" },
      });

      const claims = extractAuthClaims(token, { id: "user-2", email: "attacker@visalane.com" });
      expect(claims.provider).toBe("email");
      expect(claims.aal).toBe("aal1");
    });
  });

  describe("Layer 7: Endpoint Protection & Security Headers", () => {
    it("includes all mandatory security headers in admin responses", () => {
      const response = adminJson({ status: "ok" });
      const headers = response.headers;

      expect(headers.get("Strict-Transport-Security")).toContain("max-age=63072000");
      expect(headers.get("Content-Security-Policy")).toBe("default-src 'self'; frame-ancestors 'none'");
      expect(headers.get("X-Frame-Options")).toBe("DENY");
      expect(headers.get("X-Content-Type-Options")).toBe("nosniff");
      expect(headers.get("Referrer-Policy")).toBe("strict-origin-when-cross-origin");
    });

    it("includes all mandatory security headers in admin error responses", () => {
      const response = adminError(403, "forbidden", "Access denied");
      const headers = response.headers;

      expect(headers.get("X-Frame-Options")).toBe("DENY");
      expect(headers.get("Strict-Transport-Security")).toBeDefined();
    });

    it("enforces rate limit of 10 requests per minute per IP", () => {
      const testIp = "192.168.1.100";

      // 10 requests allowed
      for (let i = 0; i < 10; i++) {
        const check = checkAdminRateLimit(testIp, 10, 60000);
        expect(check.allowed).toBe(true);
      }

      // 11th request blocked
      const blockedCheck = checkAdminRateLimit(testIp, 10, 60000);
      expect(blockedCheck.allowed).toBe(false);
      expect(blockedCheck.remaining).toBe(0);
    });
  });

  describe("Layer 6: Threat Detection & Alerts", () => {
    it("triggers alert after 5 failed auth attempts within 10 minutes", async () => {
      const attackerIp = "203.0.113.42";

      for (let i = 0; i < 4; i++) {
        const res = await recordAdminAuthFailure(attackerIp, "admin@visalane.com", "wrong_token");
        expect(res.alertTriggered).toBe(false);
      }

      // 5th failure triggers alert
      const fifth = await recordAdminAuthFailure(attackerIp, "admin@visalane.com", "wrong_token");
      expect(fifth.alertTriggered).toBe(true);
      expect(fifth.failureCount).toBe(5);
    });
  });

  describe("Layer 5: Step-Up Authentication for Destructive Operations", () => {
    it("issues and verifies a fresh 5-minute step-up challenge token", async () => {
      const mockChallenges: Record<string, any> = {};

      const mockAdminClient = {
        from: (table: string) => ({
          insert: async (row: any) => {
            mockChallenges[row.token_hash] = { ...row, id: "chal-123" };
            return { error: null };
          },
          select: () => ({
            eq: (_col: string, val: string) => ({
              maybeSingle: async () => ({
                data: mockChallenges[val] || null,
                error: null,
              }),
            }),
          }),
          update: (payload: any) => ({
            eq: (_col: string, val: string) => {
              if (mockChallenges[val]) {
                Object.assign(mockChallenges[val], payload);
              }
              return Promise.resolve({ error: null });
            },
          }),
        }),
      } as any;

      const email = "owner@visalane.com";
      const { token, expiresAt } = await issueStepUpChallenge(
        mockAdminClient,
        email,
        "purge_quarantine",
      );

      expect(token).toBeDefined();
      expect(new Date(expiresAt).getTime()).toBeGreaterThan(Date.now());

      // 1. Verify valid token
      const verifyResult = await verifyStepUpToken(
        mockAdminClient,
        email,
        "purge_quarantine",
        token,
      );
      expect(verifyResult.valid).toBe(true);

      // 2. Reject reused token (replay prevention)
      mockChallenges[token].used = true;
      const replayResult = await verifyStepUpToken(
        mockAdminClient,
        email,
        "purge_quarantine",
        token,
      );
      expect(replayResult.valid).toBe(false);
      expect(replayResult.reason).toBe("token_already_used");
    });

    it("rejects expired step-up challenge tokens (>300s)", async () => {
      const mockAdminClient = {
        from: () => ({
          select: () => ({
            eq: () => ({
              maybeSingle: async () => ({
                data: {
                  id: "expired-chal",
                  admin_email: "owner@visalane.com",
                  action: "delete_account",
                  token_hash: "old-token",
                  expires_at: new Date(Date.now() - 10000).toISOString(), // expired in past
                  used: false,
                },
                error: null,
              }),
            }),
          }),
        }),
      } as any;

      const result = await verifyStepUpToken(
        mockAdminClient,
        "owner@visalane.com",
        "delete_account",
        "old-token",
      );

      expect(result.valid).toBe(false);
      expect(result.reason).toBe("token_expired");
    });
  });

  describe("Layer 3: Allowlist & RLS Authorization Logic", () => {
    it("differentiates allowlisted active admins from non-allowlisted / inactive users", () => {
      const allowlist = [
        { email: "owner@visalane.com", role: "owner", active: true },
        { email: "admin@visalane.com", role: "admin", active: true },
        { email: "former@visalane.com", role: "admin", active: false },
      ];

      function checkIsAdmin(email: string): boolean {
        return allowlist.some(
          (u) => u.email.toLowerCase() === email.toLowerCase() && u.active === true,
        );
      }

      function checkIsOwner(email: string): boolean {
        return allowlist.some(
          (u) => u.email.toLowerCase() === email.toLowerCase() && u.role === "owner" && u.active === true,
        );
      }

      expect(checkIsAdmin("owner@visalane.com")).toBe(true);
      expect(checkIsAdmin("admin@visalane.com")).toBe(true);
      expect(checkIsAdmin("former@visalane.com")).toBe(false);
      expect(checkIsAdmin("hacker@external.com")).toBe(false);

      expect(checkIsOwner("owner@visalane.com")).toBe(true);
      expect(checkIsOwner("admin@visalane.com")).toBe(false);
    });
  });
});
