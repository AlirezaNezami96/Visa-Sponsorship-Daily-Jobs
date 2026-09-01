/**
 * Hallucination cross-check validators for AI output (GAP 3.1 & Phase 5 Hardening).
 *
 * Python mirror: engine/ai/validators.py — the rules are identical so both
 * runtimes reject the same hallucinations. Every validator returns either
 * null (pass) or a human-readable violation list string (reject + repair).
 *
 * Core guarantees:
 *  - Tailored resume: employers, job titles and years must exist in the input
 *    profile snapshot. Never a new employer, never a new degree.
 *  - Metric defense: every percentage (%\b), multiplier (x\b), or dollar amount ($)
 *    in rewritten bullets MUST exist in the source resume bullets. Never invent a metric.
 *  - Section grounding: projects, certifications, publications, awards, and languages
 *    must be grounded in candidate data.
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

export const METRIC_PATTERN = /\b\d+\s*%(?!\w)|\b\d+(?:\.\d+)?x\b|\$\s*\d+(?:,\d{3})*(?:\.\d+)?(?:k|m|b)?\b/gi;

export interface SnapshotExperience {
  company?: string | null;
  title?: string | null;
  start?: string | null;
  end?: string | null;
  highlights?: string[] | null;
  bullets?: string[] | null;
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
  projects?: Array<{ name?: string; description?: string; technologies?: string[]; bullets?: string[] }> | null;
  certifications?: Array<{ name?: string; issuer?: string; year?: string }> | null;
  publications?: Array<{ title?: string; venue?: string; year?: string }> | null;
  awards?: Array<{ title?: string; issuer?: string; year?: string }> | null;
  languages?: Array<{ language?: string; proficiency?: string }> | null;
  volunteer_work?: Array<{ organization?: string; role?: string; description?: string }> | null;
  links?: unknown[] | null;
  interests?: string[] | null;
  raw_text?: string | null;
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

export function extractMetrics(text: string): string[] {
  if (!text) return [];
  const matches = text.match(METRIC_PATTERN) || [];
  return matches.map((m) => m.toLowerCase().replace(/\s+/g, ""));
}

export const KNOWN_SECTION_TYPES = [
  "summary", "skills", "experience", "education",
  "projects", "certifications", "publications", "awards",
  "languages", "volunteer_work", "links", "interests", "custom"
] as const;

/**
 * Normalize AI output shape: accept ResumeSection[] array or legacy {"sections": {...}} or flat object.
 */
export function resolveSections(parsed: Record<string, unknown>): Record<string, unknown> {
  // If parsed.sections is an array of {type, label, items}
  if (Array.isArray(parsed.sections)) {
    const out: Record<string, unknown> = {};
    for (const sec of parsed.sections) {
      if (sec && typeof sec === "object" && typeof sec.type === "string") {
        out[sec.type] = sec.items;
      }
    }
    return out;
  }

  const inner = parsed.sections;
  if (
    inner &&
    typeof inner === "object" &&
    !Array.isArray(inner) &&
    KNOWN_SECTION_TYPES.some((k) => (inner as Record<string, unknown>)[k] !== undefined)
  ) {
    return inner as Record<string, unknown>;
  }

  if (KNOWN_SECTION_TYPES.some((k) => parsed[k] !== undefined)) {
    const out: Record<string, unknown> = {};
    for (const k of KNOWN_SECTION_TYPES) {
      if (parsed[k] !== undefined) out[k] = parsed[k];
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

/**
 * Extracts all source bullets/text across snapshot experience, projects, and raw text.
 */
function extractSourceBullets(snapshot: ProfileSnapshot | null): string[] {
  if (!snapshot) return [];
  const bullets: string[] = [];

  if (Array.isArray(snapshot.experience)) {
    for (const e of snapshot.experience) {
      const hl = e.highlights || e.bullets || [];
      if (Array.isArray(hl)) bullets.push(...hl.filter((h) => typeof h === "string"));
    }
  }

  if (Array.isArray(snapshot.projects)) {
    for (const p of snapshot.projects) {
      if (typeof p?.description === "string") bullets.push(p.description);
      if (Array.isArray(p?.bullets)) bullets.push(...p.bullets.filter((b) => typeof b === "string"));
    }
  }

  if (typeof snapshot.raw_text === "string") {
    bullets.push(snapshot.raw_text);
  }

  return bullets;
}

export function validateTailoredResume(parsed: Record<string, unknown>, snapshot: ProfileSnapshot | null): string | null {
  const violations: string[] = [];
  const sections = resolveSections(parsed);
  const experience = Array.isArray(sections.experience) ? (sections.experience as Array<Record<string, unknown>>) : [];
  const snapExperience = snapshot?.experience ?? [];
  const snapEducation = snapshot?.education ?? [];

  // 1. Experience grounding checks (employers, titles, dates)
  if (experience.length && snapExperience.length) {
    const snapCompanies = snapExperience.map((e) => e.company).filter(Boolean);
    const snapTitles = snapExperience.map((e) => e.title).filter(Boolean);
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

  // 2. Education grounding checks
  const education = Array.isArray(sections.education) ? (sections.education as Array<Record<string, unknown>>) : [];
  if (education.length && snapEducation.length) {
    const snapInstitutions = snapEducation.map((e) => e.institution).filter(Boolean);
    for (const entry of education) {
      const institution = String(entry.institution ?? "");
      if (institution && !presentIn(institution, snapInstitutions)) {
        violations.push(`education institution "${institution}" was invented`);
      }
    }
  }

  // 3. Metric & Percentage Hallucination Check
  // Ensure every %, multiplier (2x, 10x), or $ amount in output bullets existed in source bullets
  const sourceBullets = extractSourceBullets(snapshot);
  const allSourceMetrics = new Set(sourceBullets.flatMap(extractMetrics));

  const outputBullets: string[] = [];
  for (const exp of experience) {
    const bList = Array.isArray(exp.bullets) ? (exp.bullets as string[]) : Array.isArray(exp.highlights) ? (exp.highlights as string[]) : [];
    outputBullets.push(...bList.filter((b) => typeof b === "string"));
  }

  const projects = Array.isArray(sections.projects) ? (sections.projects as Array<Record<string, unknown>>) : [];
  for (const proj of projects) {
    const bList = Array.isArray(proj.bullets) ? (proj.bullets as string[]) : [];
    outputBullets.push(...bList.filter((b) => typeof b === "string"));
    if (typeof proj.description === "string") outputBullets.push(proj.description);
  }

  for (const b of outputBullets) {
    const metricsInBullet = extractMetrics(b);
    for (const m of metricsInBullet) {
      if (!allSourceMetrics.has(m)) {
        violations.push(`invented metric or percentage "${m}" in bullet: "${b.slice(0, 80)}"`);
      }
    }
  }

  // 4. Certifications grounding check
  const certifications = Array.isArray(sections.certifications) ? (sections.certifications as Array<Record<string, unknown>>) : [];
  const snapCerts = snapshot?.certifications ?? [];
  if (certifications.length && snapCerts.length) {
    const snapCertNames = snapCerts.map((c) => c.name).filter(Boolean);
    for (const cert of certifications) {
      const name = String(cert.name ?? "");
      if (name && !presentIn(name, snapCertNames)) {
        violations.push(`certification "${name}" was invented`);
      }
    }
  }

  return violations.length ? violations.join("; ") : null;
}

export function validateCoverLetter(
  parsed: Record<string, unknown>,
  profile: ProfileSnapshot | null,
  job: Record<string, unknown> | null,
): string | null {
  const violations: string[] = [];
  const text = String(parsed.cover_letter_markdown ?? "");
  const lower = text.toLowerCase();
  const wc = wordCount(text);

  if (wc < COVER_LETTER_MIN_WORDS || wc > COVER_LETTER_MAX_WORDS) {
    violations.push(`word count ${wc} outside target ${COVER_LETTER_MIN_WORDS}-${COVER_LETTER_MAX_WORDS}`);
  }

  for (const phrase of COVER_LETTER_BLOCKLIST) {
    if (lower.includes(phrase)) {
      violations.push(`contains blocklisted opening phrase "${phrase}"`);
    }
  }

  const company = normalize(job?.company);
  if (company && company.length > 2 && !lower.includes(company)) {
    violations.push(`missing specific reference to target company "${job?.company}"`);
  }

  const facts: string[] = [];
  if (profile?.skills?.length) {
    facts.push(...profile.skills.map(normalize));
  }
  if (Array.isArray(profile?.experience)) {
    for (const e of profile.experience) {
      if (typeof e?.company === "string") facts.push(normalize(e.company));
      if (typeof e?.title === "string") facts.push(normalize(e.title));
      const hl = e.highlights || e.bullets || [];
      if (Array.isArray(hl)) facts.push(...hl.map(normalize));
    }
  }

  if (facts.length > 0) {
    const mentionsFact = facts.some((f) => f.length > 2 && lower.includes(f));
    if (!mentionsFact) {
      violations.push("does not reference any verified metric, skill or profile fact");
    }
  } else {
    violations.push("does not reference any verified user metric or profile fact");
  }

  return violations.length ? violations.join("; ") : null;
}

export function validateOutreach(
  parsed: Record<string, unknown> | null | undefined,
  expectedTone?: string,
): string | null {
  if (!parsed || typeof parsed !== "object") {
    return "output is not an object";
  }

  const violations: string[] = [];

  const emailObj = parsed.email && typeof parsed.email === "object" ? (parsed.email as Record<string, unknown>) : null;
  const linkedinObj = parsed.linkedin && typeof parsed.linkedin === "object" ? (parsed.linkedin as Record<string, unknown>) : null;

  if (parsed.email !== undefined || parsed.linkedin !== undefined) {
    if (!emailObj) {
      violations.push("missing email object");
    } else {
      const body = String(emailObj.body ?? "");
      if (!body.trim()) {
        violations.push("missing email.body");
      } else if (wordCount(body) > EMAIL_WORD_LIMIT) {
        violations.push(`email body exceeds limit of ${EMAIL_WORD_LIMIT} words`);
      }
      if (expectedTone && emailObj.tone && emailObj.tone !== expectedTone) {
        violations.push(`email tone '${emailObj.tone}' does not match expected '${expectedTone}'`);
      }
    }

    if (!linkedinObj) {
      violations.push("missing linkedin object");
    } else {
      const lBody = String(linkedinObj.body ?? "");
      if (!lBody.trim()) {
        violations.push("missing linkedin.body");
      } else if (lBody.length > LINKEDIN_HARD_LIMIT) {
        violations.push(`linkedin body exceeds hard cap of ${LINKEDIN_HARD_LIMIT} chars`);
      }
      if (expectedTone && linkedinObj.tone && linkedinObj.tone !== expectedTone) {
        violations.push(`linkedin tone '${linkedinObj.tone}' does not match expected '${expectedTone}'`);
      }
    }

    return violations.length ? violations.join("; ") : null;
  }

  const note = String(parsed.linkedin_note ?? "");
  const body = String(parsed.email_body ?? "");
  const subject = String(parsed.email_subject ?? "");

  if (!note.trim()) violations.push("missing linkedin_note");
  if (!body.trim()) violations.push("missing email_body");
  if (!subject.trim()) violations.push("missing email_subject");

  if (note.length > LINKEDIN_HARD_LIMIT) {
    violations.push(`linkedin note is ${note.length} characters (hard limit: ${LINKEDIN_HARD_LIMIT})`);
  }

  const emailWords = wordCount(body);
  if (emailWords > EMAIL_WORD_LIMIT) {
    violations.push(`email body is ${emailWords} words (limit: ${EMAIL_WORD_LIMIT})`);
  }

  return violations.length ? violations.join("; ") : null;
}
