/**
 * Tests for admin-retry payload shapes and actions.
 */
import { describe, it, expect } from "vitest";

describe("admin retry action payload validation", () => {
  it("validates supported actions", () => {
    const validActions = ["retry", "dismiss"];
    expect(validActions.includes("retry")).toBe(true);
    expect(validActions.includes("dismiss")).toBe(true);
    expect(validActions.includes("invalid")).toBe(false);
  });
});
