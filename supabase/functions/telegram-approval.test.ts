/**
 * Tests for Telegram approval webhook handler.
 */
import { describe, it, expect } from "vitest";

describe("telegram-approval callback query parser", () => {
  it("parses approve action with full 36-char uuid", () => {
    const data = "approve_linkedin_123e4567-e89b-12d3-a456-426614174000";
    const parts = data.split("_");
    const action = parts[0];
    const platform = parts[1];
    const jobId = parts.slice(2).join("_");

    expect(action).toBe("approve");
    expect(platform).toBe("linkedin");
    expect(jobId).toBe("123e4567-e89b-12d3-a456-426614174000");
  });

  it("parses reject action with full 36-char uuid", () => {
    const data = "reject_x_123e4567-e89b-12d3-a456-426614174000";
    const parts = data.split("_");
    const action = parts[0];
    const platform = parts[1];
    const jobId = parts.slice(2).join("_");

    expect(action).toBe("reject");
    expect(platform).toBe("x");
    expect(jobId).toBe("123e4567-e89b-12d3-a456-426614174000");
  });
});
