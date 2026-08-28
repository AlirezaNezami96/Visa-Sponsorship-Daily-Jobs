/**
 * Critical-path test for alert matching (master plan section 10.4):
 * complex filters (Remote OR Hybrid, exclude Company X, min match 80) over 50
 * mock jobs must produce the exact correct subset. This mirrors the Python
 * test_visalane.py fixture so both runtimes stay semantically identical.
 */
import { describe, it, expect } from "vitest";
import { jobMatchesAlert, type AlertFilters, type JobLike } from "./alert-matching.ts";

function mkJob(i: number, overrides: Partial<JobLike> = {}): JobLike {
  return {
    id: `job-${i}`,
    job_db_id: `job-${i}`,
    title: `Backend Engineer #${i}`,
    company: `Company${i}`,
    description: "Build distributed systems in Python.",
    country_code: "DE",
    country: "Germany",
    work_mode: "remote",
    visa_sponsorship_confidence: 80,
    visa_sponsorship_verified: true,
    resume_match_score: 85,
    ...overrides,
  };
}

describe("alert matching over 50 mock jobs", () => {
  it("Remote OR Hybrid + exclude Company X + min match 80 -> exact subset", () => {
    const jobs: JobLike[] = [];
    for (let i = 0; i < 50; i++) {
      const o: Partial<JobLike> = {};
      if (i % 3 === 0) o.work_mode = "onsite"; // excluded by work_modes
      if (i % 5 === 0) o.resume_match_score = 50; // excluded by min_match
      if (i % 7 === 0) o.company = "BlockedCorp"; // excluded by exclude_companies
      if (i % 4 === 0) o.work_mode = "hybrid"; // allowed
      jobs.push(mkJob(i, o));
    }

    const filters: AlertFilters = {
      work_modes: ["remote", "hybrid"],
      exclude_companies: ["BlockedCorp"],
      min_match: 80,
    };

    const expected = jobs
      .filter(
        (j) =>
          (j.work_mode === "remote" || j.work_mode === "hybrid") &&
          j.company !== "BlockedCorp" &&
          Number(j.resume_match_score ?? 0) >= 80,
      )
      .map((j) => j.id);

    const matched = jobs.filter((j) => jobMatchesAlert(j, filters)).map((j) => j.id);

    expect(new Set(matched)).toEqual(new Set(expected));
    expect(expected.length).toBeGreaterThan(0);
    expect(expected.length).toBeLessThan(50);
  });

  it("country + confidence + verified_only filters", () => {
    const filters: AlertFilters = { countries: ["DE"], min_confidence: 70, verified_only: true };
    const good = mkJob(1, { visa_sponsorship_confidence: 75, visa_sponsorship_verified: true });
    const wrongCountry = mkJob(2, { country_code: "FR" });
    const lowConf = mkJob(3, { visa_sponsorship_confidence: 20 });
    const unverified = mkJob(4, { visa_sponsorship_verified: false });

    const results = [good, wrongCountry, lowConf, unverified].filter((j) => jobMatchesAlert(j, filters));
    expect(results.map((j) => j.id)).toEqual(["job-1"]);
  });

  it("country codes match case-insensitively; names match by substring", () => {
    const byCode: AlertFilters = { countries: ["de"] };
    expect(jobMatchesAlert(mkJob(1, { country_code: "DE" }), byCode)).toBe(true);

    const byName: AlertFilters = { countries: ["Germany"] };
    expect(jobMatchesAlert(mkJob(2, { country: "Germany" }), byName)).toBe(true);
    expect(jobMatchesAlert(mkJob(3, { country: "France" }), byName)).toBe(false);
  });

  it("keyword matches title/description case-insensitively", () => {
    const filters: AlertFilters = { keywords: ["kubernetes"] };
    const hit = mkJob(1, { title: "Platform Engineer", description: "We run KUBERNETES at scale." });
    const miss = mkJob(2, { title: "Platform Engineer", description: "Docker only." });
    expect(jobMatchesAlert(hit, filters)).toBe(true);
    expect(jobMatchesAlert(miss, filters)).toBe(false);
  });

  it("exclude_companies is normalization-insensitive (suffix/case/punctuation)", () => {
    const filters: AlertFilters = { exclude_companies: ["Acme Inc."] };
    // normCompany lowercases and strips non-alphanumerics but keeps spaces.
    const job = mkJob(1, { company: "Acme Inc." });
    expect(jobMatchesAlert(job, filters)).toBe(false);
  });

  it("empty/null filters match everything", () => {
    expect(jobMatchesAlert(mkJob(1), {})).toBe(true);
    expect(jobMatchesAlert(mkJob(2), null)).toBe(true);
    expect(jobMatchesAlert(mkJob(3), undefined)).toBe(true);
  });

  it("min_match falls back to resume_match.ats_score when resume_match_score absent", () => {
    const filters: AlertFilters = { min_match: 80 };
    const viaNested = mkJob(1, { resume_match_score: undefined, resume_match: { ats_score: 90 } });
    const tooLow = mkJob(2, { resume_match_score: undefined, resume_match: { ats_score: 50 } });
    expect(jobMatchesAlert(viaNested, filters)).toBe(true);
    expect(jobMatchesAlert(tooLow, filters)).toBe(false);
  });
});
