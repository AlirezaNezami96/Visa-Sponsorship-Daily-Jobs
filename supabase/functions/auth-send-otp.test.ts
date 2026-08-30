import { describe, it, expect, beforeEach } from "vitest";
import { handleSendOtpRequest } from "./auth-send-otp/index.ts";
import { globalOtpRateLimiter } from "./_shared/auth-otp.ts";

describe("auth-send-otp Edge Function", () => {
  beforeEach(() => {
    globalOtpRateLimiter.reset();
  });

  it("handles OPTIONS preflight request", async () => {
    const req = new Request("https://visalane.online/auth-send-otp", {
      method: "OPTIONS",
    });
    const res = await handleSendOtpRequest(req);
    expect(res.status).toBe(200);
    expect(res.headers.get("Access-Control-Allow-Origin")).toBe("*");
  });

  it("rejects non-POST HTTP methods with 405 Method Not Allowed", async () => {
    const req = new Request("https://visalane.online/auth-send-otp", {
      method: "GET",
    });
    const res = await handleSendOtpRequest(req);
    expect(res.status).toBe(405);
    const data = await res.json();
    expect(data.error.code).toBe("method_not_allowed");
  });

  it("rejects invalid JSON payloads with 400 Bad Request", async () => {
    const req = new Request("https://visalane.online/auth-send-otp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{ invalid_json }",
    });
    const res = await handleSendOtpRequest(req);
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.code).toBe("bad_request");
  });

  it("rejects missing or empty email field with 400 Bad Request", async () => {
    const req = new Request("https://visalane.online/auth-send-otp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const res = await handleSendOtpRequest(req);
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.message).toContain("Email address is required");
  });

  it("rejects invalid email formats with 400 Bad Request", async () => {
    const req = new Request("https://visalane.online/auth-send-otp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "invalid-email-address" }),
    });
    const res = await handleSendOtpRequest(req);
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.message).toContain("Invalid email address format");
  });

  it("enforces cooldown rate limiting on rapid consecutive requests", async () => {
    const email = "test.rate@visalane.online";
    const key = `email:${email}`;

    // Simulate an existing recent request
    globalOtpRateLimiter.recordRequest(key, "hash123", Date.now());

    const req = new Request("https://visalane.online/auth-send-otp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });

    const res = await handleSendOtpRequest(req);
    expect(res.status).toBe(429);
    const data = await res.json();
    expect(data.error.code).toBe("rate_limited_cooldown");
    expect(data.error.message).toContain("Please wait");
  });
});
