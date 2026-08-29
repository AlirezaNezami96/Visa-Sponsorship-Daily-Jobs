/**
 * POST /functions/v1/generate-tailored-resume
 * Auth required + usage-limit gated (resume_generations).
 * Grounded in resume_matcher.py semantics: keywords_to_add is woven in only
 * where truthful; tailoring_notes feeds the FE "what changed" summary
 * (docs/contracts/tailored_resume.schema.json).
 *
 * GAP 3 hardening wired here: hallucination cross-check against the parsed
 * resume snapshot, repair-then-waterfall, idempotency key, atomic post-
 * validation quota. GAP 2: the Python engine assembles the PDF; the response
 * carries a 1-hour signed preview/download URL as `pdf_url` when available.
 *
 * Body: { resume_id: string, job_id: string,
 *         format_preference?: "own"|"professional" }
 *
 * Phase 4 additions:
 *   - ats_score_before: computed from the raw resume vs job (deterministic)
 *   - ats_score_after:  AI-reported estimated_ats_score from the tailoring step
 *   - Deletes the previous completed document for the same (user, job, format)
 *     before inserting a new one (keeps generated_documents tidy).
 */
import { createUserClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { handleOptions, json, badRequest, unauthorized, serverError } from "../_shared/http.ts";
import { buildTailoredResumePrompt, PROMPT_VERSIONS } from "../_shared/prompts.ts";
import { runGeneration } from "../_shared/generation.ts";
import { createGenerationStore, createDocumentSignedUrl, renderDocumentViaEngine } from "../_shared/supabase-store.ts";
import { loadJob, loadResume } from "../_shared/jobs.ts";
import { validateTailoredResume, type ProfileSnapshot } from "../_shared/validators.ts";
import type { ProfileRow } from "../_shared/usage-limits.ts";

Deno.serve(async (req) => {
  const preflight = handleOptions(req);
  if (preflight) return preflight;
  if (req.method !== "POST") return json({ error: { code: "method_not_allowed", message: "POST only" } }, { status: 405 });
  if (!hasAuthHeader(req)) return unauthorized();

  try {
    const client = createUserClient(req);
    const user = await getAuthUser(client);
    if (!user) return unauthorized();

    const body = await req.json().catch(() => ({}));
    const resumeId: string = typeof body.resume_id === "string" ? body.resume_id : "";
    const jobId: string = typeof body.job_id === "string" ? body.job_id : "";
    if (!resumeId || !jobId) return badRequest("resume_id and job_id are required");

    const { data: profile } = await client.from("profiles").select("*").eq("id", user.id).maybeSingle();
    const prof = (profile ?? {}) as ProfileRow & Record<string, unknown>;

    const resume = await loadResume(client, user.id, resumeId);
    if (!resume) return badRequest("resume not found");

    const job = await loadJob(client, jobId);
    if (!job) return badRequest("job not found");

    const resumeText = String(resume.raw_text ?? "");
    const parsedData = resume.parsed_data ?? null;
    const snapshot = (parsedData ?? null) as ProfileSnapshot | null;

    // Phase 4: compute ATS baseline score (before tailoring).
    const atsBefore = computeAtsBefore({
      resumeText,
      parsedData: parsedData as Record<string, unknown> | null,
      job: job as unknown as Record<string, unknown>,
    });

    // resume_matcher.py grounding: keywords_to_add from stored baseline if present.
    const baseline = (resume.ats_baseline ?? {}) as Record<string, unknown>;
    const keywordsToAdd = Array.isArray(baseline.keywords_to_add) ? (baseline.keywords_to_add as string[]) : [];
    const formatPreference = prof.remember_resume_format
      ? String(prof.resume_format_preference ?? "professional")
      : body.format_preference === "own"
        ? "own"
        : "professional";

    const store = createGenerationStore(client);
    const outcome = await runGeneration(
      {
        userId: user.id,
        profile: prof as ProfileRow,
        usageField: "resume_generations",
        documentType: "resume",
        jobId,
        promptVersion: PROMPT_VERSIONS.tailoredResume,
        formatType: formatPreference,
        profileUpdatedAt: (prof.updated_at as string | null) ?? null,
        inputProfileSnapshot: (snapshot ?? null) as Record<string, unknown> | null,
        buildPrompt: () =>
          buildTailoredResumePrompt({
            resumeText,
            parsedData,
            job,
            keywordsToAdd,
            formatPreference,
          }),
        validate: (p) => {
          if (typeof p.tailored_resume_markdown !== "string" || !p.tailored_resume_markdown.trim()) {
            return "missing tailored_resume_markdown";
          }
          if (!Array.isArray(p.tailoring_notes)) return "missing tailoring_notes";
          // GAP 3.1 hallucination cross-check against the input snapshot.
          return validateTailoredResume(p, snapshot);
        },
        postProcess: (p) => ({
          ...p,
          format_type: formatPreference,
          ats_score_before: atsBefore,
          ats_score_after: typeof p.estimated_ats_score === "number" ? p.estimated_ats_score : null,
        }),
        analyticsEvent: "resume_generated",
      },
      { store },
    );

    if (!outcome.ok) {
      return json({ error: { code: outcome.code, message: outcome.message } }, { status: outcome.status });
    }

    // GAP 2: deterministic PDF assembly via the engine + signed preview URL.
    const documentId = (outcome.body.document_id as string | null) ?? null;
    if (documentId) {
      const rendered = await renderDocumentViaEngine({
        document_id: documentId,
        user_id: user.id,
        job_id: jobId,
        document_type: "resume",
        format_type: formatPreference,
        output_json: outcome.body.output,
        profile: prof as Record<string, unknown>,
        job: job as unknown as Record<string, unknown>,
      });
      if (rendered) {
        outcome.body.pdf_url = await createDocumentSignedUrl(client, rendered.storage_path);
        outcome.body.pdf_path = rendered.storage_path;
      }
    } else if (typeof outcome.body.file_path === "string") {
      // Idempotent hit: sign the already-rendered document.
      outcome.body.pdf_url = await createDocumentSignedUrl(client, outcome.body.file_path as string);
    }

    // Phase 4: delete prior completed document for same (user, job, format).
    if (documentId) {
      await deletePreviousDocument(client, user.id, jobId, formatPreference, documentId);
    }

    // Attach ATS scores to response body.
    outcome.body.ats_score_before = atsBefore;
    outcome.body.ats_score_after = (outcome.body.output as Record<string, unknown> | null)?.estimated_ats_score ?? null;

    return json(outcome.body);
  } catch (err) {
    console.error("generate-tailored-resume error:", err);
    return serverError();
  }
});

// ── ATS before scoring (inline — no engine round-trip) ─────────────────────

function computeAtsBefore(args: {
  resumeText: string;
  parsedData: Record<string, unknown> | null;
  job: Record<string, unknown>;
}): number | null {
  const { resumeText, parsedData, job } = args;
  if (!resumeText.trim()) return null;

  const jobDesc = String(job.description ?? "");
  const jobTitle = String(job.title ?? "");
  const jobSkills = Array.isArray(job.skills) ? (job.skills as string[]) : [];
  const resumeSkills = Array.isArray((parsedData as Record<string, unknown> | null)?.skills)
    ? ((parsedData as Record<string, unknown>).skills as string[])
    : [];
  const resumeTitles = Array.isArray((parsedData as Record<string, unknown> | null)?.job_titles)
    ? ((parsedData as Record<string, unknown>).job_titles as string[])
    : [];

  // Inline keyword-overlap ATS scoring (mirrors Python ats_scorer.py)
  const stopWords = new Set(["the", "and", "for", "with", "that", "are", "have", "will", "from", "you", "our", "your", "in", "on", "at", "to", "of", "a", "an", "be", "is"]);
  const extractKw = (text: string) => new Set(
    text.toLowerCase().match(/\b[a-z][a-z0-9\-\+#\.]{1,40}\b/g)
      ?.filter(w => w.length >= 3 && !stopWords.has(w)) ?? []
  );

  const jdKw = extractKw(jobDesc);
  const resumeKw = extractKw(resumeText);
  const kwScore = jdKw.size > 0
    ? Math.round(([...jdKw].filter(w => resumeKw.has(w)).length / jdKw.size) * 40)
    : 20;

  const normSkill = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");
  const jobSkillSet = new Set(jobSkills.map(normSkill));
  const resumeSkillSet = new Set(resumeSkills.map(normSkill));
  const skillScore = jobSkillSet.size > 0 && resumeSkillSet.size > 0
    ? Math.round(([...jobSkillSet].filter(s => resumeSkillSet.has(s)).length / jobSkillSet.size) * 30)
    : 15;

  const jt = jobTitle.toLowerCase();
  const titleWords = new Set(jt.split(/\s+/));
  let titleScore = 5;
  for (const t of resumeTitles) {
    const tw = new Set(t.toLowerCase().split(/\s+/));
    const overlap = [...tw].filter(w => titleWords.has(w)).length;
    if (overlap > 0) titleScore = Math.max(titleScore, Math.round((overlap / Math.max(tw.size, titleWords.size)) * 18));
    if (t.toLowerCase() === jt) { titleScore = 20; break; }
  }

  // Format quality: penalize if no skills or no experience detected
  const fmtScore = (resumeSkills.length > 0 ? 5 : 2) + (resumeTitles.length > 0 ? 5 : 2);

  return Math.min(100, kwScore + skillScore + titleScore + fmtScore);
}

// ── Cleanup: delete previous completed document ─────────────────────────────

async function deletePreviousDocument(
  client: ReturnType<typeof import("../_shared/supabase-clients.ts").createUserClient>,
  userId: string,
  jobId: string,
  formatType: string,
  newDocumentId: string,
): Promise<void> {
  try {
    await client
      .from("generated_documents")
      .delete()
      .eq("user_id", userId)
      .eq("job_id", jobId)
      .eq("document_type", "resume")
      .eq("format_type", formatType)
      .eq("status", "completed")
      .neq("id", newDocumentId);
  } catch {
    // Non-fatal: cleanup failure should never block the response
  }
}
