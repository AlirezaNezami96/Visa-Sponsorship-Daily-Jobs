/**
 * Tests for the health check Edge Function.
 */
import { describe, it, expect } from "vitest";
import { HEALTH_RESPONSE } from "./health/index.ts";

describe("health endpoint", () => {
  it("returns status ok and version", () => {
    expect(HEALTH_RESPONSE.status).toBe("ok");
    expect(HEALTH_RESPONSE.version).toBe("1.0.0");
    expect(HEALTH_RESPONSE.service).toBe("visalane-backend");
  });
});
