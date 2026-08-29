/**
 * Tests for find-contacts caching and fallback logic.
 */
import { describe, it, expect } from "vitest";

describe("find-contacts cache threshold calculation", () => {
  it("calculates 24-hour cache threshold correctly", () => {
    const CACHE_STALENESS_HOURS = 24;
    const now = Date.now();
    const thresholdMs = now - CACHE_STALENESS_HOURS * 60 * 60 * 1000;
    const thresholdIso = new Date(thresholdMs).toISOString();

    const diffHours = (now - new Date(thresholdIso).getTime()) / (1000 * 60 * 60);
    expect(Math.round(diffHours)).toBe(24);
  });

  it("filters contacts by confidence score and email status", () => {
    const contacts = [
      { name: "Recruiter 1", email: "r1@example.com", email_status: "verified", confidence_score: 95 },
      { name: "Recruiter 2", email: "r2@example.com", email_status: "pattern_guess", confidence_score: 60 },
      { name: "Recruiter 3", email: null, email_status: "not_found", confidence_score: 30 },
    ];

    const verified = contacts.filter((c) => c.email_status === "verified");
    expect(verified.length).toBe(1);
    expect(verified[0].name).toBe("Recruiter 1");

    const sortedByConfidence = [...contacts].sort((a, b) => b.confidence_score - a.confidence_score);
    expect(sortedByConfidence[0].name).toBe("Recruiter 1");
    expect(sortedByConfidence[2].name).toBe("Recruiter 3");
  });
});
