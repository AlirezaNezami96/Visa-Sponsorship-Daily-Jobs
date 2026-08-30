import { describe, it, expect } from "vitest";
import { decodeState } from "./oauth-callback/index.ts";

describe("oauth-callback Edge Function", () => {
  it("decodes valid state token correctly", () => {
    const rawState = btoa(JSON.stringify({
      provider: "google",
      nonce: "random_nonce_123",
      timestamp: Date.now(),
      client_state: "view_job",
    }));

    const decoded = decodeState(rawState);
    expect(decoded).not.toBeNull();
    expect(decoded?.provider).toBe("google");
    expect(decoded?.nonce).toBe("random_nonce_123");
    expect(decoded?.client_state).toBe("view_job");
  });

  it("returns null for malformed or empty state", () => {
    expect(decodeState(null)).toBeNull();
    expect(decodeState("")).toBeNull();
    expect(decodeState("invalid_base64!!!")).toBeNull();
    expect(decodeState(btoa("just a string"))).toBeNull();
  });
});
