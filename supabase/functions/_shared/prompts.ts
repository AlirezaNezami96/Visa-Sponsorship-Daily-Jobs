/**
 * Prompt contracts for on-demand AI generation (Edge Function runtime).
 * Mirrors docs/contracts/*.schema.json — the Python pipeline honors the same
 * contracts for any bulk generation it performs.
 */

export const PROMPT_VERSIONS = {
  parseResume: "parse-v2",
  tailoredResume: "tailor-v3",
  coverLetter: "cl-v1",
  outreach: "out-v1",
} as const;

export const LINKEDIN_CHAR_LIMIT = 300;

export function enforceLinkedinLimit(body: string, limit: number = LINKEDIN_CHAR_LIMIT): { body: string; trimmed: boolean } {
  const trimmedInput = body.trim();
  if (!trimmedInput) return { body: "", trimmed: false };
  if (body.length <= limit) return { body, trimmed: false };
  const truncated = body.slice(0, limit - 1);
  const lastSpace = truncated.lastIndexOf(" ");
  const clean = lastSpace > 0 ? truncated.slice(0, lastSpace).trimEnd() : truncated.trimEnd();
  return { body: clean + "…", trimmed: true };
}

export type SectionType =
  | "summary"
  | "skills"
  | "experience"
  | "education"
  | "projects"
  | "certifications"
  | "publications"
  | "awards"
  | "languages"
  | "volunteer_work"
  | "links"
  | "interests"
  | "custom";

export interface ResumeSection {
  type: SectionType;
  /**
   * The heading text as the candidate wrote it in their original resume (e.g. "Technical Proficiencies").
   * Preserved verbatim in "own" mode; replaced with canonical label in "professional" mode.
   */
  label: string;
  items: unknown[];
}

export interface ProfileSnapshot {
  full_name?: string | null;
  job_titles?: string[] | null;
  skills?: string[] | null;
  about_me?: string | null;
  contact?: Record<string, unknown> | null;
  experience?: unknown[] | null;
  education?: unknown[] | null;
  projects?: unknown[] | null;
  certifications?: unknown[] | null;
  publications?: unknown[] | null;
  awards?: unknown[] | null;
  languages?: unknown[] | null;
  volunteer_work?: unknown[] | null;
  links?: unknown[] | null;
  interests?: unknown[] | null;
  detected_structure?: Array<{ type: string; label: string }> | null;
  [key: string]: unknown;
}

export interface JobContext {
  title: string;
  company: string;
  location?: string | null;
  description?: string | null;
  requirements?: string[] | null;
  skills?: string[] | null;
  must_haves?: string[] | null;
}

const FACT_RULES = `
HARD RULES:
- Use ONLY facts present in the candidate data below. NEVER invent experience, employers, metrics, or education.
- If a claim cannot be grounded in the candidate data, omit it.
- Return ONLY valid JSON, no markdown fences.`;

export const SECTION_FACT_RULES = `
HARD RULES (GROUNDING & ZERO FABRICATION):
- Use ONLY facts present in the candidate data below. NEVER invent employers, titles, dates, tools, metrics, certifications, publications, or education.
- Every number, percentage, or dollar figure in your output MUST already appear in the matching source bullet. If the source has no number, do not add one — rephrase for impact using the real scope/tools instead of inventing a metric.
- If a JD keyword has no honest basis in the candidate's data, do not include it in the skills or rewrite.
- Return ONLY valid JSON, no markdown fences.`;

export function buildParseResumePrompt(resumeText: string): string {
  return `You are an expert resume parsing engine. Extract all candidate information from the provided resume text into a strict JSON object.
Extract all 12 potential section types and detect the chronological sequence of sections in \`detected_structure\`.
Extract all social and professional links (LinkedIn, GitHub, Portfolios, Personal Websites, Blogs, etc.) from the header and contact sections into the \`links\` array.
${FACT_RULES}

Rules for links:
1. Always format links as valid absolute URLs starting with "https://".
2. If only a username or handle is given (e.g. "linkedin: johndoe" or "github: johndoe"), expand it to the full URL ("https://linkedin.com/in/johndoe", "https://github.com/johndoe").
3. Do not include email addresses in the links array.

JSON Schema to follow:
{
  "full_name": string,
  "email": string|null,
  "phone": string|null,
  "location": string|null,
  "job_titles": string[],
  "skills": string[],
  "summary": string,
  "links": [
    {
      "type": "linkedin" | "github" | "portfolio" | "website" | "other",
      "url": "https://..."
    }
  ],
  "experience": [
    {
      "company": string,
      "title": string,
      "start": string|null,
      "end": string|"Present"|null,
      "highlights": string[]
    }
  ],
  "education": [
    {
      "institution": string,
      "degree": string,
      "year": string
    }
  ],
  "projects": [{"name": string, "description": string|null, "technologies": string[], "bullets": string[]}],
  "certifications": [{"name": string, "issuer": string|null, "year": string|null}],
  "languages": [{"language": string, "proficiency": string|null}],
  "volunteer_work": [{"organization": string, "role": string|null, "description": string|null}],
  "publications": [{"title": string, "venue": string|null, "year": string|null}],
  "awards": [{"title": string, "issuer": string|null, "year": string|null}],
  "interests": string[],
  "references": [{"name": string, "relationship": string|null, "contact": string|null}],
  "detected_structure": [
    {"type": "summary"|"skills"|"experience"|"education"|"projects"|"certifications"|"publications"|"awards"|"languages"|"volunteer_work"|"links"|"interests", "label": string}
  ],
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
  sectionOrder?: Array<{ type: string; label: string }>;
}): string {
  return `You are an elite career coach and resume tailoring expert. Tailor this candidate's resume to the target job description.
Align vocabulary, surface relevant achievements, and emphasize matching technologies without fabricating a single claim, number, or entity.
${SECTION_FACT_RULES}

Respond with JSON matching this exact structure:
{
  "tailored_resume_markdown": string,
  "keywords_added": string[],
  "tailoring_notes": string[],
  "sections": [
    {
      "type": "summary" | "skills" | "experience" | "education" | "projects" | "certifications" | "publications" | "awards" | "languages" | "volunteer_work" | "links" | "interests",
      "label": string,
      "items": [ ... ]
    }
  ],
  "gaps": string[],
  "prompt_version": "${PROMPT_VERSIONS.tailoredResume}"
}

RULES FOR SECTIONS AND GROUNDING:
1. "sections" must be an array of ResumeSection objects. Include ALL non-empty section types from the source resume. Never drop certifications, projects, publications, awards, languages, or volunteer work if present.
2. In "own" format mode: preserve the original section sequence and heading labels as given in CANDIDATE SECTION STRUCTURE.
3. In "professional" format mode: output in canonical order:
   Summary -> Skills -> Experience -> Projects -> Education -> Certifications -> Publications -> Awards -> Languages -> Volunteer Work -> Links.
4. "experience" items must keep exact company, title, start, and end dates from candidate data:
   {"title": string, "company": string, "start": string, "end": string, "bullets": string[]}.
5. "skills" items: Array of string skills (or categories). Keep candidate's real skills, reordered by JD relevance, adding JD terms ONLY if genuinely practiced in source experience.
6. "projects" items: [{"name": string, "description": string|null, "technologies": string[], "bullets": string[]}].
7. "certifications" items: [{"name": string, "issuer": string|null, "year": string|null}].
8. "languages" items: [{"language": string, "proficiency": string|null}].
9. "publications" items: [{"title": string, "venue": string|null, "year": string|null}].
10. "awards" items: [{"title": string, "issuer": string|null, "year": string|null}].
11. "volunteer_work" items: [{"organization": string, "role": string|null, "description": string|null}].
12. "links" items: string[] or [{"type": string, "url": string}].
13. Metric rule: NEVER turn a qualitative statement into an invented percentage, dollar amount, or number.

FORMAT PREFERENCE: ${args.formatPreference ?? "professional"}
CANDIDATE SECTION STRUCTURE: ${JSON.stringify(args.sectionOrder ?? [])}
TARGET KEYWORDS TO WEAVE IN (only where truthful): ${JSON.stringify(args.keywordsToAdd ?? [])}

TARGET JOB:
Title: ${args.job.title}
Company: ${args.job.company}
Location: ${args.job.location ?? "Remote"}
Description: ${(args.job.description ?? "").slice(0, 6000)}

CANDIDATE SOURCE RESUME:
${args.resumeText.slice(0, 12000)}

PARSED CANDIDATE DATA:
${JSON.stringify(args.parsedData ?? {}).slice(0, 4000)}`;
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
  return `Write tailored outreach messages for LinkedIn connection requests and direct email for this candidate and job.
${FACT_RULES}

LENGTH LIMITS (HARD):
- LinkedIn connection note: MAX 300 characters (including spaces). Must be short, punchy, contextual.
- Email: MAX 220 words. 2-3 short paragraphs + clear call to action.

Respond with JSON matching this shape:
{"linkedin_note": string, "email_subject": string, "email_body": string,
 "character_counts": {"linkedin": number, "email_words": number},
 "prompt_version": "${PROMPT_VERSIONS.outreach}"}

CONTACT:
${args.contact ? `Recipient: ${args.contact.name ?? "Hiring Manager"} (${args.contact.title ?? ""})` : "General Hiring Team"}

COMPANY CONTEXT:
${args.companyHookContext ?? `Company: ${args.job.company}`}

JOB:
Title: ${args.job.title}
Company: ${args.job.company}
Location: ${args.job.location ?? ""}

CANDIDATE PROFILE:
${JSON.stringify(args.profile).slice(0, 2500)}`;
}
