/**
 * Critical-path tests for outreach guardrails (master plan section 9):
 *   - LinkedIn hard 300-char cap enforced server-side before storing
 *   - trim happens at a word boundary, never mid-word
 *   - under-limit content passes through untouched
 */
import { describe, it, expect } from "vitest";
import {
  enforceLinkedinLimit,
  LINKEDIN_CHAR_LIMIT,
  buildOutreachPrompt,
  buildCoverLetterPrompt,
  buildParseResumePrompt,
  PROMPT_VERSIONS,
} from "./prompts.ts";

describe("enforceLinkedinLimit", () => {
  it("passes short content through unchanged", () => {
    const body = "Hi Jane, loved your talk on infra. Open to a quick chat about the SWE role?";
    const { body: out, trimmed } = enforceLinkedinLimit(body);
    expect(out).toBe(body);
    expect(trimmed).toBe(false);
    expect(out.length).toBeLessThanOrEqual(LINKEDIN_CHAR_LIMIT);
  });

  it("caps over-limit content to at most the hard limit", () => {
    const body = "word ".repeat(200); // ~1000 chars
    const { body: out, trimmed } = enforceLinkedinLimit(body);
    expect(trimmed).toBe(true);
    expect(out.length).toBeLessThanOrEqual(LINKEDIN_CHAR_LIMIT);
  });

  it("never trims mid-word when a word boundary is available", () => {
    const long =
      "Dear hiring team, I am reaching out because I have spent several years building distributed systems and I would love to discuss how my background aligns with your opening. " +
      "additional filler ".repeat(20);
    const { body: out } = enforceLinkedinLimit(long);
    expect(out.length).toBeLessThanOrEqual(LINKEDIN_CHAR_LIMIT);
    // Ends with an ellipsis and the char before it is not a space (clean boundary)
    expect(out.endsWith("…")).toBe(true);
    const beforeEllipsis = out.slice(0, -1);
    expect(beforeEllipsis.endsWith(" ")).toBe(false);
  });

  it("handles empty/whitespace input without crashing", () => {
    expect(enforceLinkedinLimit("").body).toBe("");
    expect(enforceLinkedinLimit("   ").body).toBe("");
  });
});

describe("prompt builders embed contract rules + version", () => {
  const job = { title: "SWE", company: "Acme", location: "Berlin", description: "build things" };

  it("cover letter prompt forbids generic openers and hallucination", () => {
    const p = buildCoverLetterPrompt({ profile: { full_name: "A" }, job });
    expect(p).toContain("I am writing to apply"); // listed as FORBIDDEN opener
    expect(p).toContain("NEVER invent");
    expect(p).toContain(PROMPT_VERSIONS.coverLetter);
    expect(p).toContain("250-400 words");
  });

  it("outreach prompt states the 300-char LinkedIn cap", () => {
    const p = buildOutreachPrompt({ profile: {}, job, tone: "natural" });
    expect(p).toContain("300");
    expect(p).toContain(PROMPT_VERSIONS.outreach);
  });

  it("parse-resume prompt only-uses-facts rule + version", () => {
    const p = buildParseResumePrompt("some resume text with enough length to matter");
    expect(p).toContain("NEVER invent");
    expect(p).toContain(PROMPT_VERSIONS.parseResume);
  });
});
