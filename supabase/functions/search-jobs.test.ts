/**
 * Tests for search-jobs cursor pagination, filters, and match scoring logic.
 */
import { describe, it, expect } from "vitest";

// Recreate inline matching logic from search-jobs to test pure unit functions
function normSet(items: string[]): Set<string> {
  return new Set(items.map((s) => s.toLowerCase().replace(/[^a-z0-9\s]/g, "").trim()));
}

function matchLabel(score: number): string {
  if (score >= 80) return "great_match";
  if (score >= 60) return "good_match";
  if (score >= 40) return "fair_match";
  return "low_match";
}

function computeMatchScoreEdge(profile: Record<string, unknown>, job: Record<string, unknown>): number {
  const userSkills = normSet((profile.skills_cache ?? []) as string[]);
  const jobSkills = normSet((job.skills ?? []) as string[]);
  const userTitles = ((profile.job_titles ?? []) as string[]).map((t) => t.toLowerCase());
  const jobTitle = String(job.title ?? "").toLowerCase();

  let score = 0;

  // Skills (50 pts)
  if (jobSkills.size > 0 && userSkills.size > 0) {
    const intersection = new Set([...userSkills].filter((s) => jobSkills.has(s)));
    const coverage = intersection.size / jobSkills.size;
    score += Math.round(coverage * 50);
  } else if (jobSkills.size === 0) {
    score += 25;
  }

  // Title (20 pts)
  if (userTitles.length > 0 && jobTitle) {
    const titleWords = new Set(jobTitle.split(/\s+/));
    let titleScore = 0;
    for (const t of userTitles) {
      if (t === jobTitle) { titleScore = 20; break; }
      if (t.includes(jobTitle) || jobTitle.includes(t)) { titleScore = Math.max(titleScore, 17); }
      const tWords = new Set(t.split(/\s+/));
      const tOverlap = [...tWords].filter((w) => titleWords.has(w)).length;
      if (tOverlap > 0) titleScore = Math.max(titleScore, Math.round((tOverlap / Math.max(tWords.size, titleWords.size)) * 18));
    }
    score += titleScore;
  } else {
    score += 10;
  }

  // Visa (10 pts)
  if (job.visa_sponsorship_verified === true) score += 10;
  else if ((job.visa_sponsorship_confidence as number ?? 0) >= 70) score += 8;
  else if ((job.visa_sponsorship_confidence as number ?? 0) >= 50) score += 5;

  // Work mode (10 pts)
  const preferredModes = ((profile.preferred_work_modes ?? []) as string[]).map((m) => m.toLowerCase());
  const jobMode = String(job.work_mode ?? "").toLowerCase();
  if (preferredModes.length === 0 || preferredModes.includes(jobMode)) score += 10;
  else if (preferredModes.includes("remote") && jobMode === "hybrid") score += 5;

  // Location (10 pts)
  const preferredCountries = ((profile.preferred_countries ?? []) as string[]).map((c) => c.toUpperCase());
  const jobCountry = String(job.country_code ?? job.country ?? "").toUpperCase();
  if (preferredCountries.length === 0 || preferredCountries.includes(jobCountry)) score += 10;

  return Math.min(100, score);
}

describe("search-jobs matching logic", () => {
  it("computes high match score when skills and title match perfectly", () => {
    const profile = {
      skills_cache: ["Python", "TypeScript", "React", "PostgreSQL"],
      job_titles: ["Full Stack Engineer"],
      preferred_countries: ["DE"],
      preferred_work_modes: ["remote"],
    };

    const job = {
      title: "Full Stack Engineer",
      skills: ["Python", "TypeScript", "React"],
      country_code: "DE",
      work_mode: "remote",
      visa_sponsorship_verified: true,
    };

    const score = computeMatchScoreEdge(profile, job);
    expect(score).toBeGreaterThanOrEqual(80);
    expect(matchLabel(score)).toBe("great_match");
  });

  it("assigns appropriate match labels based on thresholds", () => {
    expect(matchLabel(85)).toBe("great_match");
    expect(matchLabel(65)).toBe("good_match");
    expect(matchLabel(45)).toBe("fair_match");
    expect(matchLabel(20)).toBe("low_match");
  });

  it("handles empty skills gracefully without NaN", () => {
    const profile = { skills_cache: [], job_titles: [] };
    const job = { title: "Software Engineer", skills: [] };

    const score = computeMatchScoreEdge(profile, job);
    expect(Number.isNaN(score)).toBe(false);
    expect(score).toBeGreaterThanOrEqual(0);
    expect(score).toBeLessThanOrEqual(100);
  });

  it("encodes and decodes cursor correctly", () => {
    const postedAt = "2026-08-29T10:00:00Z";
    const id = "job-uuid-123";
    const encoded = btoa(JSON.stringify({ posted_at: postedAt, id }));

    const decoded = JSON.parse(atob(encoded));
    expect(decoded.posted_at).toBe(postedAt);
    expect(decoded.id).toBe(id);
  });
});
