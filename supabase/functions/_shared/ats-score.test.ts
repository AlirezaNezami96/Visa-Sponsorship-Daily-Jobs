import { describe, it, expect } from "vitest";
import { computeAtsScore, extractKeywords } from "./ats-score.ts";

describe("ats-score module", () => {
  it("extractKeywords filters stop words and normalizes tokens", () => {
    const text = "Experienced Software Engineer with React, TypeScript, and Docker!";
    const kws = extractKeywords(text);
    expect(kws).toContain("software");
    expect(kws).toContain("engineer");
    expect(kws).toContain("react");
    expect(kws).toContain("typescript");
    expect(kws).toContain("docker");
    expect(kws).not.toContain("and");
    expect(kws).not.toContain("with");
  });

  it("computeAtsScore produces deterministic score in healthy 70-95 range for matching profile", () => {
    const input = {
      resumeText: `
        Jane Doe
        jane@example.com | (555) 123-4567 | San Francisco, CA | linkedin.com/in/janedoe

        PROFESSIONAL SUMMARY
        Senior Backend Engineer with 6+ years building distributed cloud platforms in Go, Python, and Kubernetes.

        TECHNICAL SKILLS
        Go, Python, Kubernetes, Docker, PostgreSQL, Redis, AWS, gRPC

        EXPERIENCE
        Senior Backend Engineer | Cloud Scale Inc (2021 – Present)
        • Architected real-time streaming pipeline processing 250k events/sec with 99.99% availability.
        • Reduced database query latency by 45% through Redis caching and query indexing.
        • Led migration of 15 microservices from EC2 to Kubernetes, saving $120k annually.

        EDUCATION
        B.S. in Computer Science | UC Berkeley (2018)
      `,
      parsedData: {
        full_name: "Jane Doe",
        job_titles: ["Senior Backend Engineer", "Backend Engineer"],
        skills: ["Go", "Python", "Kubernetes", "Docker", "PostgreSQL", "Redis", "AWS", "gRPC"],
        experience: [
          {
            title: "Senior Backend Engineer",
            company: "Cloud Scale Inc",
            start: "2021",
            end: "Present",
            highlights: [
              "Architected real-time streaming pipeline processing 250k events/sec with 99.99% availability.",
              "Reduced database query latency by 45% through Redis caching and query indexing.",
              "Led migration of 15 microservices from EC2 to Kubernetes, saving $120k annually."
            ]
          }
        ],
        education: [
          { institution: "UC Berkeley", degree: "B.S. in Computer Science", year: "2018" }
        ]
      },
      job: {
        title: "Senior Backend Engineer",
        company: "Stripe",
        description: "We are seeking a Senior Backend Engineer proficient in Go, Kubernetes, and PostgreSQL to scale high-throughput payment infrastructure.",
        skills: ["Go", "Kubernetes", "PostgreSQL", "Redis", "Distributed Systems"],
        must_haves: ["Go", "Kubernetes", "PostgreSQL"]
      }
    };

    const score1 = computeAtsScore(input);
    const score2 = computeAtsScore(input);

    // Determinism assertion
    expect(score1.total).toBe(score2.total);
    expect(score1.keywordScore).toBe(score2.keywordScore);
    expect(score1.titleScore).toBe(score2.titleScore);
    expect(score1.quantificationScore).toBe(score2.quantificationScore);
    expect(score1.completenessScore).toBe(score2.completenessScore);

    // Sweet spot range assertion
    expect(score1.total).toBeGreaterThanOrEqual(75);
    expect(score1.total).toBeLessThanOrEqual(95);
    expect(score1.mustHavesFound).toHaveLength(3);
    expect(score1.mustHavesMissing).toHaveLength(0);
  });

  it("computeAtsScore applies repetition penalty for keyword stuffing", () => {
    const naturalInput = {
      resumeText: "Software Engineer experienced in Go and Kubernetes. Built scalable services.",
      job: { title: "Software Engineer", description: "Need Go developer" }
    };

    const stuffedInput = {
      resumeText: "Go Go Go Go Go Go Go Go Go Go Kubernetes Kubernetes Kubernetes Kubernetes Kubernetes Kubernetes Kubernetes",
      job: { title: "Software Engineer", description: "Need Go developer" }
    };

    const naturalScore = computeAtsScore(naturalInput);
    const stuffedScore = computeAtsScore(stuffedInput);

    expect(stuffedScore.penaltyScore).toBeLessThan(0);
    expect(stuffedScore.total).toBeLessThanOrEqual(naturalScore.total);
  });
});
