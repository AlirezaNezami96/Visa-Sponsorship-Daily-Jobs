/**
 * Tests for the hallucination cross-check validators (GAP 3.1, TS mirror of
 * engine/ai/validators.py).
 */
import { describe, it, expect } from "vitest";
import {
  validateTailoredResume,
  validateCoverLetter,
  validateOutreach,
  LINKEDIN_HARD_LIMIT,
  EMAIL_WORD_LIMIT,
} from "./validators.ts";

const SNAPSHOT = {
  full_name: "Alireza Nezami",
  skills: ["Kotlin", "Flutter", "Jetpack Compose"],
  experience: [
    { company: "Devotel", title: "Senior Android & Flutter Developer", start: "April 2024", end: "Present" },
    { company: "Golden Equator Group", title: "Android Developer", start: "2017", end: "2024" },
  ],
  education: [{ institution: "Anadolu University", degree: "BSc Computer Engineering", year: "2017" }],
};

describe("validateTailoredResume", () => {
  it("accepts output grounded in the snapshot", () => {
    const parsed = {
      sections: {
        experience: [
          { company: "Devotel", title: "Senior Android & Flutter Developer", start: "April 2024", end: "Present", bullets: [] },
          { company: "Golden Equator Group", title: "Android Developer", start: "2017", end: "2024", bullets: [] },
        ],
        education: [{ institution: "Anadolu University", degree: "BSc", year: "2017" }],
      },
    };
    expect(validateTailoredResume(parsed, SNAPSHOT)).toBeNull();
  });

  it("rejects an invented employer", () => {
    const parsed = {
      sections: {
        experience: [{ company: "Google", title: "Android Developer", start: "2017", end: "2024", bullets: [] }],
      },
    };
    const result = validateTailoredResume(parsed, SNAPSHOT);
    expect(result).toMatch(/Google/);
  });

  it("rejects an invented job title", () => {
    const parsed = {
      sections: {
        experience: [{ company: "Devotel", title: "Engineering Manager", start: "April 2024", end: "Present", bullets: [] }],
      },
    };
    expect(validateTailoredResume(parsed, SNAPSHOT)).toMatch(/Engineering Manager/);
  });

  it("rejects an invented year", () => {
    const parsed = {
      sections: {
        experience: [{ company: "Devotel", title: "Android Developer", start: "2010", end: "Present", bullets: [] }],
      },
    };
    expect(validateTailoredResume(parsed, SNAPSHOT)).toMatch(/2010/);
  });

  it("rejects an invented education institution", () => {
    const parsed = {
      sections: { education: [{ institution: "MIT", degree: "PhD", year: "2017" }] },
    };
    expect(validateTailoredResume(parsed, SNAPSHOT)).toMatch(/MIT/);
  });

  it("is lenient without a snapshot (nothing to cross-check)", () => {
    const parsed = { sections: { experience: [{ company: "Acme", title: "Dev", start: "2020", end: "2024", bullets: [] }] } };
    expect(validateTailoredResume(parsed, null)).toBeNull();
  });

  it("validates flat output without the sections wrapper (model shape drift)", () => {
    const flat = {
      summary: "s",
      experience: [{ company: "Google", title: "Staff Engineer", start: "2015", end: "Present", bullets: [] }],
    };
    const result = validateTailoredResume(flat, SNAPSHOT);
    expect(result).toMatch(/Google/);
    expect(result).toMatch(/2015/);

    const flatGrounded = {
      experience: [{ company: "Devotel", title: "Senior Android & Flutter Developer", start: "April 2024", end: "Present", bullets: [] }],
      education: [{ institution: "Anadolu University", degree: "BSc", year: "2017" }],
    };
    expect(validateTailoredResume(flatGrounded, SNAPSHOT)).toBeNull();
  });
});

describe("validateCoverLetter", () => {
  const body = (filler: string) =>
    `${filler} Spotify builds audio platforms used by millions. At Devotel I shipped a Flutter app serving 400K+ monthly users with a 4.7 rating, and my Kotlin expertise matches your stack requirements perfectly. ${filler}`;

  const longFiller = Array.from({ length: 130 }, (_, i) => `word${i}`).join(" ");
  const job = { company: "Spotify", companyHookContext: "Spotify in-car audio investment" };

  it("accepts a compliant grounded letter", () => {
    const parsed = { cover_letter_markdown: body(longFiller) };
    expect(validateCoverLetter(parsed, SNAPSHOT, job)).toBeNull();
  });

  it("rejects letters outside 250-400 words", () => {
    const short = { cover_letter_markdown: "Spotify is great and I know Kotlin and Flutter with 400K+ users." };
    expect(validateCoverLetter(short, SNAPSHOT, job)).toMatch(/word count/);
  });

  it("rejects blocklisted openers", () => {
    const parsed = { cover_letter_markdown: `I am writing to apply for the role. Spotify. ${longFiller} 400K+ users. Kotlin.` };
    expect(validateCoverLetter(parsed, SNAPSHOT, job)).toMatch(/blocklisted/);
  });

  it("rejects letters that never mention the company", () => {
    const parsed = { cover_letter_markdown: `I have great skills. ${longFiller} I reduced crashes by 60 percent.` };
    expect(validateCoverLetter(parsed, SNAPSHOT, { company: "Spotify" })).toMatch(/company/);
  });

  it("rejects letters with no user metric or profile fact", () => {
    const parsed = { cover_letter_markdown: `Spotify is wonderful and I would love to join. ${longFiller}` };
    expect(validateCoverLetter(parsed, { full_name: "X", skills: [] }, job)).toMatch(/metric|fact/);
  });
  it("rejects blocklisted words like delve and thrilled to apply", () => {
    const parsedDelve = { cover_letter_markdown: `We delve into mobile challenges. Spotify. ${longFiller} 400K+ users. Kotlin.` };
    expect(validateCoverLetter(parsedDelve, SNAPSHOT, job)).toMatch(/blocklisted|delve/);

    const parsedThrilled = { cover_letter_markdown: `I am thrilled to apply for this job. Spotify. ${longFiller} 400K+ users. Kotlin.` };
    expect(validateCoverLetter(parsedThrilled, SNAPSHOT, job)).toMatch(/blocklisted|thrilled/);
  });
});

describe("validateOutreach", () => {
  const okEmail = { subject: "s", body: Array.from({ length: 40 }, (_, i) => `w${i}`).join(" "), tone: "natural" };
  const okLinkedin = { body: "Hi! Saw your Android role. I have shipped Kotlin apps at scale.", tone: "natural" };

  it("accepts compliant outreach", () => {
    expect(validateOutreach({ email: okEmail, linkedin: okLinkedin }, "natural")).toBeNull();
  });

  it("rejects LinkedIn over the hard 300 char cap", () => {
    const parsed = { email: okEmail, linkedin: { body: "x".repeat(LINKEDIN_HARD_LIMIT + 1), tone: "natural" } };
    expect(validateOutreach(parsed, "natural")).toMatch(/300/);
  });

  it("rejects email over the 220 word cap", () => {
    const parsed = {
      email: { subject: "s", body: Array.from({ length: EMAIL_WORD_LIMIT + 1 }, (_, i) => `w${i}`).join(" "), tone: "natural" },
      linkedin: okLinkedin,
    };
    expect(validateOutreach(parsed, "natural")).toMatch(/220/);
  });

  it("rejects a tone mismatch", () => {
    const parsed = { email: { ...okEmail, tone: "corporate" }, linkedin: okLinkedin };
    expect(validateOutreach(parsed, "natural")).toMatch(/tone/);
  });

  it("rejects missing email or linkedin sub-objects", () => {
    expect(validateOutreach(null as unknown as Record<string, unknown>)).toMatch(/not an object/);
    expect(validateOutreach({ email: okEmail })).toMatch(/missing linkedin/);
    expect(validateOutreach({ linkedin: okLinkedin })).toMatch(/missing email/);
  });
});
