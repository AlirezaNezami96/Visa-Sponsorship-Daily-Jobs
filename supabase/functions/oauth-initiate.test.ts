import { describe, it, expect } from "vitest";
import { buildOAuthUrl, generateStateToken } from "./oauth-initiate/index.ts";

describe("oauth-initiate Edge Function", () => {
  it("generates valid state token with provider and timestamp", () => {
    const token = generateStateToken("google", "redirect_dashboard");
    expect(token).toBeTruthy();
    const decoded = JSON.parse(atob(token));
    expect(decoded.provider).toBe("google");
    expect(decoded.client_state).toBe("redirect_dashboard");
    expect(typeof decoded.timestamp).toBe("number");
  });

  it("builds correct Google authorization URL", () => {
    const url = buildOAuthUrl("google", "test_g_id", "https://app.visalane.online/cb", "state_123");
    expect(url).toContain("accounts.google.com");
    expect(url).toContain("client_id=test_g_id");
    expect(url).toContain("state=state_123");
    expect(url).toContain("openid");
  });

  it("builds correct GitHub authorization URL", () => {
    const url = buildOAuthUrl("github", "test_gh_id", "https://app.visalane.online/cb", "state_456");
    expect(url).toContain("github.com/login/oauth/authorize");
    expect(url).toContain("client_id=test_gh_id");
    expect(url).toContain("state=state_456");
    expect(url).toContain("read%3Auser");
  });

  it("throws for unsupported providers", () => {
    expect(() => buildOAuthUrl("unsupported", "id", "uri", "st")).toThrow();
  });
});
