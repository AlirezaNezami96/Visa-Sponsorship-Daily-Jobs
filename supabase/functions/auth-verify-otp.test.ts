import { describe, it, expect, beforeEach } from "vitest";
import { handleVerifyOtpRequest } from "./auth-verify-otp/index.ts";
import { globalOtpRateLimiter } from "./_shared/auth-otp.ts";

describe("auth-verify-otp Edge Function", () => {
  beforeEach(() => {
    globalOtpRateLimiter.reset();
  });

  it("handles OPTIONS preflight request", async () => {
    const req = new Request("https://visalane.online/auth-verify-otp", {
      method: "OPTIONS",
    });
    const res = await handleVerifyOtpRequest(req);
    expect(res.status).toBe(200);
    expect(res.headers.get("Access-Control-Allow-Origin")).toBe("*");
  });

  it("rejects non-POST HTTP methods with 405 Method Not Allowed", async () => {
    const req = new Request("https://visalane.online/auth-verify-otp", {
      method: "GET",
    });
    const res = await handleVerifyOtpRequest(req);
    expect(res.status).toBe(405);
    const data = await res.json();
    expect(data.error.code).toBe("method_not_allowed");
  });

  it("rejects missing email with 400 Bad Request", async () => {
    const req = new Request("https://visalane.online/auth-verify-otp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: "123456" }),
    });
    const res = await handleVerifyOtpRequest(req);
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.message).toContain("Email address is required");
  });

  it("rejects invalid email format with 400 Bad Request", async () => {
    const req = new Request("https://visalane.online/auth-verify-otp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "not-an-email", token: "123456" }),
    });
    const res = await handleVerifyOtpRequest(req);
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.message).toContain("Invalid email address format");
  });

  it("rejects missing or empty token with 400 Bad Request", async () => {
    const req = new Request("https://visalane.online/auth-verify-otp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "user@example.com" }),
    });
    const res = await handleVerifyOtpRequest(req);
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.message).toContain("Verification token is required");
  });

  it("rejects invalid token lengths or non-digit tokens with 400 Bad Request", async () => {
    const invalidTokens = ["123", "12345", "123456789", "abcdef", "12a456"];
    for (const token of invalidTokens) {
      const req = new Request("https://visalane.online/auth-verify-otp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: "user@example.com", token }),
      });
      const res = await handleVerifyOtpRequest(req);
      expect(res.status).toBe(400);
      const data = await res.json();
      expect(data.error.message).toContain("Invalid confirmation code format");
    }
  });

  it("enforces account lockout after repeated failed verification attempts", async () => {
    const email = "attacker@example.com";
    const key = `email:${email}`;

    // Simulate 5 prior failed attempts
    for (let i = 0; i < 5; i++) {
      globalOtpRateLimiter.recordVerifyFailure(key);
    }

    const req = new Request("https://visalane.online/auth-verify-otp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, token: "999999" }),
    });

    const res = await handleVerifyOtpRequest(req);
    expect(res.status).toBe(429);
    const data = await res.json();
    expect(data.error.code).toBe("too_many_failed_attempts");
  });
});
