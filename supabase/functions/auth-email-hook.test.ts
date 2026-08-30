import { describe, it, expect } from "vitest";
import { handleEmailHookRequest } from "./auth-email-hook/index.ts";

describe("auth-email-hook Edge Function", () => {
  it("handles OPTIONS preflight request", async () => {
    const req = new Request("https://visalane.online/auth-email-hook", {
      method: "OPTIONS",
    });
    const res = await handleEmailHookRequest(req);
    expect(res.status).toBe(200);
    expect(res.headers.get("Access-Control-Allow-Origin")).toBe("*");
  });

  it("rejects non-POST methods with 405", async () => {
    const req = new Request("https://visalane.online/auth-email-hook", {
      method: "GET",
    });
    const res = await handleEmailHookRequest(req);
    expect(res.status).toBe(405);
  });

  it("rejects payload missing user email", async () => {
    const req = new Request("https://visalane.online/auth-email-hook", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email_data: { token: "123456" } }),
    });
    const res = await handleEmailHookRequest(req);
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.message).toContain("Recipient user email is missing");
  });

  it("rejects payload missing OTP token", async () => {
    const req = new Request("https://visalane.online/auth-email-hook", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user: { email: "user@example.com" } }),
    });
    const res = await handleEmailHookRequest(req);
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.message).toContain("OTP token is missing");
  });

  it("returns rendered VisaLane branded HTML email with token", async () => {
    const token = "859302";
    const req = new Request("https://visalane.online/auth-email-hook", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user: { email: "user@example.com" },
        email_data: { token, email_action_type: "signup" },
      }),
    });
    const res = await handleEmailHookRequest(req);
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.ok).toBe(true);
    expect(data.subject).toContain("859302");
    expect(data.html).toContain("859302");
    expect(data.html).toContain("VisaLane");
  });
});
