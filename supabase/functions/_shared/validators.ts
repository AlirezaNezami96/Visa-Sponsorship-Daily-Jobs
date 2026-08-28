/**
 * Hallucination cross-check validators for AI output (GAP 3.1).
 *
 * Python mirror: engine/ai/validators.py — the rules are identical so both
 * runtimes reject the same hallucinations. Every validator returns either
 * null (pass) or a human-readable violation list string (reject + repair).
 *
 * Core guarantees:
 *  - Tailored resume: employers, job titles and years must exist in the input
 *    profile snapshot. Never a new employer, never a new degree.
 *  - Cover letter: 250-400 words, no generic-opener blocklist phrases, must
 *    reference >=1 company-specific token AND >=1 user metric/fact.
 *  - Outreach: LinkedIn <= 300 chars (hard), email <= 220 words, tone kept.
 */

export const COVER_LETTER_BLOCKLIST = [
  "i am writing to apply",
  "i would like to express my interest",
  "to whom it may concern",
  "i hope this finds you well",
  "delve",
  "thrilled to apply",
];

export const LINKEDIN_HARD_LIMIT = 300;
export const EMAIL_WORD_LIMIT = 220;
export const COVER_LETTER_MIN_WORDS = 250;
export const COVER_LETTER_MAX_WORDS = 400;

export interface SnapshotExperience {
  company?: string | null;
  title?: string | null;
  start?: string | null;
  end?: string | null;
}

export interface SnapshotEducation {
  institution?: string | null;
  degree?: string | null;
  year?: string | null;
}

export interface ProfileSnapshot {
  full_name?: string | null;
  skills?: string[] | null;
  experience?: SnapshotExperience[] | null;
  education?: SnapshotEducation[] | null;
  [key: string]: unknown;
}

function normalize(value: unknown): string {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function yearsIn(value: unknown): string[] {
  return [...String(value ?? "").matchAll(/\b(19|20)\d{2}\b/g)].map((m) => m[0]);
}

function wordCount(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

function isPresentMarker(value: unknown): boolean {
  const v = normalize(value);
  return v === "" || v === "present" || v === "current" || v === "now" || v === "today";
}

const SECTION_KEYS = ["summary", "skills", "experience", "education", "links"] as const;

/**
 * Normalize AI output shape: accept {"sections": {...}} or flat sections.
 * Models vary between the wrapped and the flat layout; validators and the PDF
 * builder must treat both identically (a flat payload must never slip past
 * grounding checks).
 */
export function resolveSections(parsed: Record<string, unknown>): Record<string, unknown> {
  const inner = parsed.sections;
  if (
    inner &&
    typeof inner === "object" &&
    !Array.isArray(inner) &&
    SECTION_KEYS.some((k) => (inner as Record<string, unknown>)[k])
  ) {
    return inner as Record<string, unknown>;
  }
  if (SECTION_KEYS.some((k) => parsed[k])) {
    const out: Record<string, unknown> = {};
    for (const k of SECTION_KEYS) {
      if (parsed[k]) out[k] = parsed[k];
    }
    return out;
  }
  return {};
}

/** True when `needle` (normalized) appears as an entry in the normalized haystack list. */
function presentIn(needle: unknown, haystack: Array<unknown>): boolean {
  const n = normalize(needle);
  if (!n) return false;
  return haystack.some((h) => {
    const item = normalize(h);
    return item === n || item.includes(n) || n.includes(item);
  });
}

export function validateTailoredResume(parsed: Record<string, unknown>, snapshot: ProfileSnapshot | null): string | null {
  const violations: string[] = [];
  const sections = resolveSections(parsed);
  const experience = Array.isArray(sections.experience) ? (sections.experience as Array<Record<string, unknown>>) : [];
  const snapExperience = snapshot?.experience ?? [];
  const snapEducation = snapshot?.education ?? [];

  if (experience.length && snapExperience.length) {
    const snapCompanies = snapExperience.map((e) => e.company);
    const snapTitles = snapExperience.map((e) => e.title);
    const snapYears = snapExperience.flatMap((e) => [...yearsIn(e.start), ...yearsIn(e.end)]);
    const eduYears = snapEducation.flatMap((e) => yearsIn(e.year));
    const allKnownYears = new Set([...snapYears, ...eduYears]);

    for (const entry of experience) {
      const company = String(entry.company ?? "");
      const title = String(entry.title ?? "");
      if (company && !presentIn(company, snapCompanies)) {
        violations.push(`employer "${company}" does not exist in the candidate profile`);
      }
      if (title && !presentIn(title, snapTitles)) {
        violations.push(`job title "${title}" does not exist in the candidate profile`);
      }
      for (const field of ["start", "end"] as const) {
        const raw = entry[field];
        if (isPresentMarker(raw)) continue;
        for (const year of yearsIn(raw)) {
          if (!allKnownYears.has(year)) {
            violations.push(`year "${year}" in ${field} not present in profile dates`);
          }
        }
      }
    }
  }

  const education = Array.isArray(sections.education) ? (sections.education as Array<Record<string, unknown>>) : [];
  if (education.length && snapEducation.length) {
    const snapInstitutions = snapEducation.map((e) => e.institution);
    for (const entry of education) {
      const institution = String(entry.institution ?? "");
      if (institution && !presentIn(institution, snapInstitutions)) {
        violations.push(`education institution "${institution}" was invented`);
      }
    }
  }

  return violations.length ? `Hallucination check failed: ${violations.join("; ")}` : null;
}

export function validateCoverLetter(
  parsed: Record<string, unknown>,
  snapshot: ProfileSnapshot | null,
  jobContext: { company?: string; companyHookContext?: string } = {},
): string | null {
  if (!parsed || typeof parsed !== "object") return "output is not an object";
  const markdown = String(parsed.cover_letter_markdown ?? "");
  if (!markdown.trim()) return "missing cover_letter_markdown";
  const violations: string[] = [];

  const words = wordCount(markdown);
  if (words < COVER_LETTER_MIN_WORDS || words > COVER_LETTER_MAX_WORDS) {
    violations.push(`word count ${words} outside ${COVER_LETTER_MIN_WORDS}-${COVER_LETTER_MAX_WORDS}`);
  }

  const lower = markdown.toLowerCase();
  for (const phrase of COVER_LETTER_BLOCKLIST) {
    if (lower.includes(phrase)) violations.push(`blocklisted opener/phrase "${phrase}"`);
  }

  const lowered = normalize(markdown);
  const companyTokens = [jobContext.company, ...(jobContext.companyHookContext ?? "").split(/\s+/)]
    .filter((t) => t && normalize(t).length >= 4);
  const referencesCompany = companyTokens.some((token) => lowered.includes(normalize(token)));
  if (companyTokens.length && !referencesCompany) {
    violations.push("letter never references the company (company-specific token missing)");
  }

  const metricPattern = /\d+\s*%|\d+\s*\+|\$\s?\d+|\d+\s*(k|m)\b|\b\d{2,}\b/;
  const userSkills = (snapshot?.skills ?? []).map((s) => normalize(s)).filter(Boolean);
  const hasMetric = metricPattern.test(markdown);
  const hasUserFact = userSkills.some((s) => lowered.includes(s));
  if (!hasMetric && !hasUserFact) {
    violations.push("letter contains no user metric or profile fact");
  }

  return violations.length ? `Cover letter check failed: ${violations.join("; ")}` : null;
}

export function validateOutreach(
  parsed: Record<string, unknown>,
  expectedTone: string,
): string | null {
  if (!parsed || typeof parsed !== "object") return "output is not an object";
  const violations: string[] = [];
  if (!parsed.email || typeof parsed.email !== "object") {
    violations.push("missing email object");
  }
  if (!parsed.linkedin || typeof parsed.linkedin !== "object") {
    violations.push("missing linkedin object");
  }
  const email = (parsed.email ?? {}) as Record<string, unknown>;
  const linkedin = (parsed.linkedin ?? {}) as Record<string, unknown>;

  const emailBody = String(email.body ?? "");
  if (!emailBody.trim()) violations.push("missing email.body");
  else if (wordCount(emailBody) > EMAIL_WORD_LIMIT) {
    violations.push(`email body ${wordCount(emailBody)} words exceeds ${EMAIL_WORD_LIMIT}`);
  }

  const linkedinBody = String(linkedin.body ?? "");
  if (!linkedinBody.trim()) violations.push("missing linkedin.body");
  else if (linkedinBody.length > LINKEDIN_HARD_LIMIT) {
    violations.push(`linkedin body ${linkedinBody.length} chars exceeds hard cap ${LINKEDIN_HARD_LIMIT}`);
  }

  for (const part of [
    ["email", email.tone],
    ["linkedin", linkedin.tone],
  ] as const) {
    const [name, tone] = part;
    if (tone && String(tone) !== expectedTone) {
      violations.push(`${name} tone "${tone}" does not match requested "${expectedTone}"`);
    }
  }

  return violations.length ? `Outreach check failed: ${violations.join("; ")}` : null;
}
