/**
 * Tests for extract-job-skills inline skill extraction and validation.
 */
import { describe, it, expect } from "vitest";

const SKILL_PATTERNS: [RegExp, string][] = [
  [/\bPython\b/i, "Python"],
  [/\bJavaScript\b/i, "JavaScript"],
  [/\bTypeScript\b/i, "TypeScript"],
  [/\bReact(?:\.js)?\b/i, "React"],
  [/\bPostgreSQL\b/i, "PostgreSQL"],
  [/\bDocker\b/i, "Docker"],
  [/\bKubernetes\b/i, "Kubernetes"],
  [/\bAWS\b/i, "AWS"],
  [/\bFastAPI\b/i, "FastAPI"],
  [/\bGraphQL\b/i, "GraphQL"],
];

function extractSkillsInline(title: string, description: string): string[] {
  const text = [title, description].join(" ");
  const found = new Map<string, string>();
  for (const [pattern, canonical] of SKILL_PATTERNS) {
    if (pattern.test(text)) {
      found.set(canonical.toLowerCase(), canonical);
    }
  }
  return [...found.values()];
}

describe("extract-job-skills inline regex rules", () => {
  it("extracts tech stack from combined title and description", () => {
    const skills = extractSkillsInline(
      "Senior Python Engineer",
      "We build microservices with FastAPI, PostgreSQL, Docker, and deploy on AWS with Kubernetes.",
    );
    expect(skills).toContain("Python");
    expect(skills).toContain("FastAPI");
    expect(skills).toContain("PostgreSQL");
    expect(skills).toContain("Docker");
    expect(skills).toContain("Kubernetes");
    expect(skills).toContain("AWS");
  });

  it("handles case insensitivity cleanly", () => {
    const skills = extractSkillsInline("Frontend Dev", "proficient in react and typescript");
    expect(skills).toContain("React");
    expect(skills).toContain("TypeScript");
  });

  it("returns empty array for text with no matches", () => {
    const skills = extractSkillsInline("Accountant", "Manage quarterly taxes and invoices");
    expect(skills).toEqual([]);
  });
});
