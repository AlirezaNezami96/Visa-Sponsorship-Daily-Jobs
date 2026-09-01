import { describe, it, expect } from "vitest";
import { validateTailoredResume, extractMetrics, type ProfileSnapshot } from "./validators.ts";

describe("validators fabrication & hallucination checks", () => {
  it("extractMetrics catches %, multiplier, and $ figures correctly", () => {
    const text = "Increased throughput by 50%, sped up CI by 2.5x, and saved $15,000 annually ($100k budget).";
    const metrics = extractMetrics(text);
    expect(metrics).toContain("50%");
    expect(metrics).toContain("2.5x");
    expect(metrics).toContain("$15,000");
    expect(metrics).toContain("$100k");
  });

  it("validateTailoredResume passes grounded 12-section output", () => {
    const snapshot: ProfileSnapshot = {
      full_name: "Alex Smith",
      skills: ["Python", "Docker", "AWS"],
      experience: [
        {
          company: "Stripe",
          title: "Software Engineer",
          start: "2020",
          end: "2023",
          highlights: ["Built payment pipeline handling 50k transactions/sec with 99.9% uptime."]
        }
      ],
      education: [
        { institution: "MIT", degree: "BS Computer Science", year: "2020" }
      ],
      projects: [
        { name: "OpenRAG", description: "Open source RAG engine with 10k stars." }
      ],
      certifications: [
        { name: "AWS Certified Developer" }
      ]
    };

    const validOutput = {
      sections: [
        {
          type: "experience",
          label: "Work Experience",
          items: [
            {
              company: "Stripe",
              title: "Software Engineer",
              start: "2020",
              end: "2023",
              bullets: ["Optimized payment pipeline handling 50k transactions/sec with 99.9% uptime."]
            }
          ]
        },
        {
          type: "projects",
          label: "Open Source Projects",
          items: [
            { name: "OpenRAG", description: "Open source RAG engine with 10k stars." }
          ]
        },
        {
          type: "certifications",
          label: "Certifications",
          items: [
            { name: "AWS Certified Developer" }
          ]
        }
      ]
    };

    const err = validateTailoredResume(validOutput, snapshot);
    expect(err).toBeNull();
  });

  it("validateTailoredResume rejects newly invented metric percentage", () => {
    const snapshot: ProfileSnapshot = {
      experience: [
        {
          company: "Stripe",
          title: "Software Engineer",
          start: "2020",
          end: "2023",
          highlights: ["Refactored backend microservices for better reliability."]
        }
      ]
    };

    const hallucinatoryOutput = {
      sections: [
        {
          type: "experience",
          label: "Experience",
          items: [
            {
              company: "Stripe",
              title: "Software Engineer",
              start: "2020",
              end: "2023",
              bullets: ["Refactored backend microservices, increasing throughput by 85%."]
            }
          ]
        }
      ]
    };

    const err = validateTailoredResume(hallucinatoryOutput, snapshot);
    expect(err).not.toBeNull();
    expect(err).toContain('invented metric or percentage "85%"');
  });

  it("validateTailoredResume rejects fake employer or fake certification", () => {
    const snapshot: ProfileSnapshot = {
      experience: [
        { company: "Apple", title: "iOS Engineer", start: "2021", end: "2024" }
      ],
      certifications: [
        { name: "Apple Certified Developer" }
      ]
    };

    const fakeCompanyOutput = {
      sections: [
        {
          type: "experience",
          items: [{ company: "Google", title: "iOS Engineer", start: "2021", end: "2024", bullets: ["Worked on apps."] }]
        }
      ]
    };
    const errCompany = validateTailoredResume(fakeCompanyOutput, snapshot);
    expect(errCompany).toContain('employer "Google" does not exist');

    const fakeCertOutput = {
      sections: [
        {
          type: "experience",
          items: [{ company: "Apple", title: "iOS Engineer", start: "2021", end: "2024", bullets: ["Worked on apps."] }]
        },
        {
          type: "certifications",
          items: [{ name: "Google Cloud Professional Architect" }]
        }
      ]
    };
    const errCert = validateTailoredResume(fakeCertOutput, snapshot);
    expect(errCert).toContain('certification "Google Cloud Professional Architect" was invented');
  });
});
