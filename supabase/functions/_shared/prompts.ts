/**
 * Prompt contracts for on-demand AI generation (Edge Function runtime).
 * Mirrors docs/contracts/*.schema.json — the Python pipeline honors the same
 * contracts for any bulk generation it performs.
 */

export const PROMPT_VERSIONS = {
  parseResume: "parse-v1",
  tailoredResume: "tailor-v2",
  coverLetter: "cl-v1",
  outreach: "out-v1",
} as const;

export interface ProfileSnapshot {
  full_name?: string | null;
  job_titles?: string[] | null;
  skills?: string[] | null;
  about_me?: string | null;
  contact?: Record<string, unknown> | null;
}

export interface JobContext {
  title: string;
  company: string;
  location?: string | null;
  description?: string | null;
  requirements?: string[] | null;
}

const FACT_RULES = `
HARD RULES:
- Use ONLY facts present in the candidate data below. NEVER invent experience, employers, metrics, or education.
- If a claim cannot be grounded in the candidate data, omit it.
- Return ONLY valid JSON, no markdown fences.`;

export function buildParseResumePrompt(resumeText: string): string {
  return `Extract structured data from this resume.
${FACT_RULES}

Respond with JSON matching this shape:
{
  "full_name": string|null,
  "email": string|null,
  "phone": string|null,
  "location": string|null,
  "linkedin_url": string|null,
  "github_url": string|null,
  "website_url": string|null,
  "job_titles": string[],
  "skills": string[],
  "summary": string|null,
  "experience": [{"company": string, "title": string, "start": string|null, "end": string|null, "highlights": string[]}],
  "education": [{"institution": string, "degree": string|null, "field": string|null, "year": string|null, "gpa": string|null}],
  "projects": [{"name": string, "description": string|null, "technologies": string[]}],
  "certifications": [{"name": string, "issuer": string|null, "year": string|null}],
  "languages": [{"language": string, "proficiency": string|null}],
  "volunteer_work": [{"organization": string, "role": string|null, "description": string|null}],
  "publications": [{"title": string, "venue": string|null, "year": string|null}],
  "awards": [{"title": string, "issuer": string|null, "year": string|null}],
  "interests": string[],
  "references": [{"name": string, "relationship": string|null, "contact": string|null}],
  "prompt_version": "${PROMPT_VERSIONS.parseResume}"
}

RESUME TEXT:
${resumeText.slice(0, 14000)}`;
}

export function buildTailoredResumePrompt(args: {
  resumeText: string;
  parsedData?: unknown;
  job: JobContext;
  keywordsToAdd?: string[];
  formatPreference?: string;
}): string {
  return `Tailor this candidate's resume to the job description. Keep every true fact; re-order, re-word emphasis, and weave in the listed JD keywords where they are genuinely supported by the candidate's experience.
${FACT_RULES}

Respond with JSON matching this shape:
{"tailored_resume_markdown": string, "keywords_added": string[],
 "tailoring_notes": string[], "estimated_ats_score": number|null,
 "sections": {
   "summary": string,
   "skills": string[],
   "experience": [{"title": string, "company": string, "start": string, "end": string, "bullets": string[]}],
   "education": [{"institution": string, "degree": string, "year": string}],
   "links": string[]
 },
 "prompt_version": "${PROMPT_VERSIONS.tailoredResume}"}

SECTIONS RULES (used for deterministic PDF assembly + hallucination checks):
- "experience" entries MUST reuse the candidate's real employers, job titles and dates exactly — only the bullets may be reworded for this JD.
- Never invent an employer, degree, or date. "end" may be "Present".
- "skills" = the candidate's real skills, ordered for this JD, plus at most the KEYWORDS listed below where truthful.

FORMAT PREFERENCE: ${args.formatPreference ?? "professional"}
KEYWORDS TO WEAVE IN (only where truthful): ${JSON.stringify(args.keywordsToAdd ?? [])}

JOB:
Title: ${args.job.title}
Company: ${args.job.company}
Location: ${args.job.location ?? ""}
Description: ${(args.job.description ?? "").slice(0, 6000)}

CANDIDATE RESUME:
${args.resumeText.slice(0, 12000)}

PARSED CANDIDATE DATA:
${JSON.stringify(args.parsedData ?? {}).slice(0, 3000)}`;
}

export function buildCoverLetterPrompt(args: {
  profile: ProfileSnapshot;
  resumeText?: string;
  job: JobContext;
  companyHookContext?: string;
  matchScore?: number | null;
  keywordsToAdd?: string[];
}): string {
  return `Write a best-in-class cover letter for this candidate and job.
${FACT_RULES}

STYLE REQUIREMENTS:
1. Hook: open with a specific reference to the company's work or values (provided below). Forbidden openers: "I am writing to apply", "I would like to express my interest".
2. Structure: Hook -> Why this company -> Why me (evidence + metrics from the candidate data only) -> Call to action.
3. Length: 250-400 words, 3-4 paragraphs.
4. Identify the top 2 overlapping skills/experiences between candidate and JD and build the letter on them.
5. Tone: confident, specific, human. No generic filler.

Respond with JSON matching this shape:
{"cover_letter_markdown": string, "overlap_skills": string[],
 "company_hook": string, "word_count": number,
 "prompt_version": "${PROMPT_VERSIONS.coverLetter}"}

COMPANY CONTEXT (ground the hook ONLY in these facts):
${args.companyHookContext ?? `Company: ${args.job.company}`}

JOB:
Title: ${args.job.title}
Company: ${args.job.company}
Location: ${args.job.location ?? ""}
Description: ${(args.job.description ?? "").slice(0, 6000)}

CANDIDATE PROFILE:
${JSON.stringify(args.profile).slice(0, 2500)}
${args.resumeText ? `\nCANDIDATE RESUME:\n${args.resumeText.slice(0, 8000)}` : ""}
${args.matchScore != null ? `\nATS MATCH SCORE (grounding): ${args.matchScore}` : ""}
${args.keywordsToAdd?.length ? `\nOVERLAP KEYWORDS (resume_matcher): ${JSON.stringify(args.keywordsToAdd)}` : ""}`;
}

export function buildOutreachPrompt(args: {
  profile: ProfileSnapshot;
  job: JobContext;
  tone: "professional" | "friendly" | "natural";
  contact?: { name?: string | null; title?: string | null } | null;
  companyHookContext?: string;
}): string {
  return `Write outreach messages from this candidate to the hiring team about this role.
${FACT_RULES}

EMAIL REQUIREMENTS:
- Professional, concise (under 180 words), subject under 90 chars.
- Reference ONE specific JD requirement + ONE real candidate achievement + company context.

LINKEDIN REQUIREMENTS:
- MAX 300 CHARACTERS HARD LIMIT. Conversational, not a cover-letter copy.
- No subject line.

TONE: ${args.tone}
${args.contact?.name ? `ADDRESS TO: ${args.contact.name}${args.contact.title ? ` (${args.contact.title})` : ""}` : ""}

Respond with JSON matching this shape:
{"email": {"subject": string, "body": string, "tone": "${args.tone}"},
 "linkedin": {"body": string, "tone": "${args.tone}"},
 "prompt_version": "${PROMPT_VERSIONS.outreach}"}

JOB:
Title: ${args.job.title}
Company: ${args.job.company}
Description: ${(args.job.description ?? "").slice(0, 4000)}

CANDIDATE PROFILE:
${JSON.stringify(args.profile).slice(0, 2000)}`;
}

const LINKEDIN_LIMIT = 300;

/**
 * Server-side LinkedIn length enforcement (master plan section 9):
 * messages over the cap are trimmed at a word boundary BEFORE storing,
 * never stored over-limit.
 */
export function enforceLinkedinLimit(body: string): { body: string; trimmed: boolean } {
  const clean = (body ?? "").trim();
  if (clean.length <= LINKEDIN_LIMIT) return { body: clean, trimmed: false };
  const cut = clean.slice(0, LINKEDIN_LIMIT - 1);
  const lastSpace = cut.lastIndexOf(" ");
  const trimmed = (lastSpace > 120 ? cut.slice(0, lastSpace) : cut).trimEnd() + "…";
  return { body: trimmed, trimmed: true };
}

export const LINKEDIN_CHAR_LIMIT = LINKEDIN_LIMIT;
