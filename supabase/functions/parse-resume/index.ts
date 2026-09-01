/**
 * POST /functions/v1/parse-resume
 * Auth required. Extracts structured data from uploaded resume text in-memory.
 * Privacy rule (ported from resume_fetch.py): raw text is processed in memory
 * and never persisted to disk; only structured data is stored under user RLS.
 *
 * Body: { resume_text: string }  OR  { resume_id: string, resume_text?: string }
 *       OR  { storage_path: "resumes/{uid}/file.txt" }  (GAP-4 upload flow)
 *
 * storage_path downloads the object from the `resumes` bucket with the CALLER'S
 * JWT, so RLS restricts it to the user's own prefix. Plain-text files are read
 * directly; PDFs must be extracted client-side and sent as resume_text.
 */
import { createUserClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { handleOptions, json, badRequest, unauthorized, serverError } from "../_shared/http.ts";
import { buildParseResumePrompt, PROMPT_VERSIONS } from "../_shared/prompts.ts";
import { runGeneration } from "../_shared/generation.ts";
import { createGenerationStore } from "../_shared/supabase-store.ts";
import { logSystemEvent } from "../_shared/system-logger.ts";
import type { ProfileRow } from "../_shared/usage-limits.ts";

async function resumeTextFromStorage(client: ReturnType<typeof createUserClient>, storagePath: string): Promise<string> {
  const path = storagePath.replace(/^resumes\//, "");
  const { data, error } = await client.storage.from("resumes").download(path);
  if (error || !data) {
    throw new Error(`storage download failed: ${error?.message ?? "not found"}`);
  }
  const lower = path.toLowerCase();
  if (lower.endsWith(".pdf")) {
    throw new Error(
      "PDF resumes must be text-extracted client-side and sent as resume_text (storage_path supports .txt/.md)",
    );
  }
  const text = await data.text();
  if (text.trim().length < 20) throw new Error("stored resume text is shorter than 20 chars");
  return text;
}

const SECTION_KEYS = [
  "summary", "experience", "education", "skills", "certifications",
  "projects", "languages", "volunteer_work", "publications", "awards",
  "interests", "references",
];

const HEADING_PATTERNS: Array<{ type: string; defaultLabel: string; regex: RegExp }> = [
  { type: "summary", defaultLabel: "Professional Summary", regex: /^(?:professional\s+)?summary|profile|about\s+me|objective/i },
  { type: "skills", defaultLabel: "Core Skills", regex: /^(?:technical\s+)?skills|core\s+competencies|technologies|proficiencies/i },
  { type: "experience", defaultLabel: "Work Experience", regex: /^(?:work\s+|professional\s+)?experience|employment(?:\s+history)?|work\s+history/i },
  { type: "projects", defaultLabel: "Projects", regex: /^(?:key\s+|personal\s+)?projects|what\s+i'?ve\s+built/i },
  { type: "education", defaultLabel: "Education", regex: /^education|academic\s+background|academics/i },
  { type: "certifications", defaultLabel: "Certifications", regex: /^certifications?|certificates?|licenses/i },
  { type: "publications", defaultLabel: "Publications", regex: /^publications?|papers/i },
  { type: "awards", defaultLabel: "Honors & Awards", regex: /^awards?|honors(?:\s+&\s+awards)?/i },
  { type: "languages", defaultLabel: "Languages", regex: /^languages?/i },
  { type: "volunteer_work", defaultLabel: "Volunteer Experience", regex: /^volunteer(?:ing|\s+work|\s+experience)?|community\s+service/i },
  { type: "interests", defaultLabel: "Interests", regex: /^interests?|hobbies/i },
  { type: "links", defaultLabel: "Links", regex: /^(?:social\s+|portfolio\s+)?links|websites/i },
];

function detectResumeStructure(resumeText: string, parsed: Record<string, unknown>): Array<{ type: string; label: string }> {
  // If LLM returned valid detected_structure, sanitize and use it
  if (Array.isArray(parsed.detected_structure) && parsed.detected_structure.length > 0) {
    const validStructure: Array<{ type: string; label: string }> = [];
    const seen = new Set<string>();
    for (const item of parsed.detected_structure) {
      if (item && typeof item.type === "string" && !seen.has(item.type)) {
        seen.add(item.type);
        validStructure.push({
          type: item.type,
          label: typeof item.label === "string" && item.label.trim() ? item.label.trim() : item.type,
        });
      }
    }
    if (validStructure.length > 0) return validStructure;
  }

  // Deterministic line heading scanning fallback
  const lines = resumeText.split("\n");
  const found: Array<{ type: string; label: string; index: number }> = [];
  const seen = new Set<string>();

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line.length > 0 && line.length < 50 && !line.includes("  |  ")) {
      const cleanLine = line.replace(/^[\#\*\-\s]+/, "").replace(/[\:\#\*]+$/, "").trim();
      for (const p of HEADING_PATTERNS) {
        if (!seen.has(p.type) && p.regex.test(cleanLine)) {
          seen.add(p.type);
          found.push({ type: p.type, label: cleanLine, index: i });
          break;
        }
      }
    }
  }

  found.sort((a, b) => a.index - b.index);
  return found.map(({ type, label }) => ({ type, label }));
}

function detectSections(parsed: Record<string, unknown>): string[] {
  const detected: string[] = [];
  for (const k of SECTION_KEYS) {
    const val = parsed[k];
    if (Array.isArray(val) && val.length > 0) detected.push(k);
    else if (typeof val === "string" && val.trim().length > 0) detected.push(k);
    else if (val && typeof val === "object" && Object.keys(val).length > 0) detected.push(k);
  }
  return detected;
}

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(async (req) => {
    const preflight = handleOptions(req);
    if (preflight) return preflight;
    if (req.method !== "POST") return json({ error: { code: "method_not_allowed", message: "POST only" } }, { status: 405 });
    if (!hasAuthHeader(req)) return unauthorized();

    let userId: string | null = null;

    try {
      const client = createUserClient(req);
      const user = await getAuthUser(client);
      if (!user) return unauthorized();
      userId = user.id;

      const body = await req.json().catch(() => ({}));
      let resumeText: string = typeof body.resume_text === "string" ? body.resume_text : "";

      if (resumeText.trim().length < 20 && typeof body.storage_path === "string" && body.storage_path.trim()) {
        try {
          resumeText = await resumeTextFromStorage(client, String(body.storage_path));
        } catch (err) {
          const errMsg = String((err as Error).message ?? err);
          await logSystemEvent({
            level: "warn",
            source: "parse-resume",
            message: `Resume storage read failed: ${errMsg}`,
            details: { storage_path: body.storage_path, error: errMsg },
            userId,
          });
          return badRequest(errMsg);
        }
      }

      if (resumeText.trim().length < 20) {
        await logSystemEvent({
          level: "warn",
          source: "parse-resume",
          message: "Resume parsing rejected: text is shorter than 20 characters",
          details: { textLength: resumeText.trim().length },
          userId,
        });
        return badRequest("resume_text must be provided (>= 20 chars)");
      }

      const { data: profile } = await client.from("profiles").select("*").eq("id", user.id).maybeSingle();
      const userProfile: ProfileRow = { id: user.id, ...(profile ?? {}) };
      const store = createGenerationStore(client);

      const outcome = await runGeneration(
        {
          userId: user.id,
          profile: userProfile,
          usageField: "import_attempts",
          documentType: "resume",
          jobId: null,
          promptVersion: PROMPT_VERSIONS.parseResume,
          buildPrompt: () => buildParseResumePrompt(resumeText),
          validate: (p) => {
            if (!Array.isArray(p.skills) || !Array.isArray(p.job_titles)) return "missing skills/job_titles arrays";
            return null;
          },
          analyticsEvent: "resume_parsed",
        },
        { store },
      );

      if (!outcome.ok) {
        await logSystemEvent({
          level: "error",
          source: "parse-resume",
          message: `AI resume parsing failed: ${outcome.message}`,
          details: { code: outcome.code, status: outcome.status },
          userId,
        });
        return json({ error: { code: outcome.code, message: outcome.message } }, { status: outcome.status });
      }

      const parsedOutput = outcome.body.output as Record<string, unknown>;
      const sectionsDetected = detectSections(parsedOutput);
      const sectionOrder = detectResumeStructure(resumeText, parsedOutput);
      const exp = Array.isArray(parsedOutput.experience) ? parsedOutput.experience : [];
      const isFresher = exp.length === 0;
      const nowIso = new Date().toISOString();

      // Persist structured parsed data & section_order onto the resume row when provided
      if (typeof body.resume_id === "string") {
        try {
          await client
            .from("resumes")
            .update({
              parsed_data: parsedOutput,
              sections_detected: sectionsDetected,
              section_order: sectionOrder,
              parse_status: "completed",
              parse_confidence: 0.9,
            })
            .eq("id", body.resume_id)
            .eq("user_id", user.id);
        } catch (err) {
          console.warn("Failed to update resumes row:", err);
        }
      }

      // Persist to user profile
      try {
        const profileUpdate: Record<string, unknown> = {
          parsed_resume: parsedOutput,
          skills_cache: Array.isArray(parsedOutput.skills) ? parsedOutput.skills : [],
          is_fresher: isFresher,
          last_resume_parse: nowIso,
          resume_onboarding_complete: true,
          full_name: typeof parsedOutput.full_name === "string" ? parsedOutput.full_name : undefined,
        };
        if (Array.isArray(parsedOutput.links)) {
          profileUpdate.links = parsedOutput.links;
        }
        await client
          .from("profiles")
          .update(profileUpdate)
          .eq("id", user.id);
      } catch (err) {
        console.warn("Failed to update profile row:", err);
      }



      await logSystemEvent({
        level: "info",
        source: "parse-resume",
        message: `Successfully parsed resume (${sectionsDetected.length} sections detected, ${(parsedOutput.skills as unknown[])?.length ?? 0} skills)`,
        details: {
          sections: sectionsDetected,
          skillsCount: (parsedOutput.skills as unknown[])?.length ?? 0,
          isFresher,
          resumeId: body.resume_id || null,
        },
        userId,
      });

      const responsePayload = {
        ...outcome.body,
        sections_detected: sectionsDetected,
        is_fresher: isFresher,
        confidence: 0.9,
      };

      return json(responsePayload);
    } catch (err) {
      const errMsg = String((err as Error).message ?? err);
      await logSystemEvent({
        level: "error",
        source: "parse-resume",
        message: `Unhandled exception during resume parsing: ${errMsg}`,
        details: { error: errMsg, stack: (err as Error).stack },
        userId,
      });
      return serverError();
    }
  });
}
