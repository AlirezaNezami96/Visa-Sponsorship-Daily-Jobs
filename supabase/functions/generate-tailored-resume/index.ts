/**
 * POST /functions/v1/generate-tailored-resume
 * Auth required + usage-limit gated (resume_generations).
 * Grounded in resume_matcher.py semantics: keywords_to_add is woven in only
 * where truthful; tailoring_notes feeds the FE "what changed" summary
 * (docs/contracts/tailored_resume.schema.json).
 *
 * Grounding & Rendering Architecture:
 *   - Supports full 12-section model with zero silent omissions.
 *   - "own" format mode: preserves candidate's exact section sequence and heading labels.
 *   - "professional" format mode: renders canonical ATS order.
 *   - Format preference priority: explicit request body.format_preference ALWAYS wins.
 *   - ats_score_before & ats_score_after: both computed with the exact same deterministic
 *     5-component rubric via computeAtsScore(). Zero AI score hallucination.
 *   - Document rendering: Python engine generates both .docx (primary) and .pdf (secondary).
 *
 * Body: { resume_id: string, job_id: string, format_preference?: "own"|"professional" }
 */
import { createUserClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { handleOptions, json, badRequest, unauthorized, serverError } from "../_shared/http.ts";
import { buildTailoredResumePrompt, PROMPT_VERSIONS, type ResumeSection } from "../_shared/prompts.ts";
import { runGeneration } from "../_shared/generation.ts";
import { createGenerationStore, createDocumentSignedUrl, renderDocumentViaEngine } from "../_shared/supabase-store.ts";
import { loadJob, loadResume } from "../_shared/jobs.ts";
import { validateTailoredResume, type ProfileSnapshot } from "../_shared/validators.ts";
import { computeAtsScore } from "../_shared/ats-score.ts";
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
    const parsedData = (resume.parsed_data ?? null) as Record<string, unknown> | null;
    const snapshot: ProfileSnapshot = {
      ...(parsedData ?? {}),
      raw_text: resumeText,
    };

    // Format preference precedence: explicit request body ALWAYS wins over saved profile default
    const formatPreference: "own" | "professional" =
      body.format_preference === "own" || body.format_preference === "professional"
        ? body.format_preference
        : prof.remember_resume_format && prof.resume_format_preference === "own"
          ? "own"
          : "professional";

    // Candidate structure for "own" mode
    const sectionOrder = Array.isArray(resume.section_order) && resume.section_order.length > 0
      ? (resume.section_order as Array<{ type: string; label: string }>)
      : Array.isArray(parsedData?.detected_structure)
        ? (parsedData.detected_structure as Array<{ type: string; label: string }>)
        : undefined;

    // Deterministic ATS baseline score (before tailoring)
    const atsBefore = computeAtsScore({
      resumeText,
      parsedData,
      job: job as unknown as Record<string, unknown>,
      isFresher: Boolean(prof.is_fresher),
    });

    const baseline = (resume.ats_baseline ?? {}) as Record<string, unknown>;
    const keywordsToAdd = Array.isArray(baseline.keywords_to_add) ? (baseline.keywords_to_add as string[]) : [];

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
            sectionOrder,
          }),
        validate: (p) => {
          if (typeof p.tailored_resume_markdown !== "string" || !p.tailored_resume_markdown.trim()) {
            return "missing tailored_resume_markdown";
          }
          if (!Array.isArray(p.tailoring_notes)) return "missing tailoring_notes";
          // Grounding & metric hallucination cross-check against input snapshot
          return validateTailoredResume(p, snapshot);
        },
        postProcess: (p) => {
          const outSections = Array.isArray(p.sections) ? (p.sections as ResumeSection[]) : [];
          const tailoredText = String(p.tailored_resume_markdown ?? "");
          // Compute deterministic ATS score AFTER tailoring using identical formula
          const atsAfter = computeAtsScore({
            resumeText: tailoredText,
            sections: outSections,
            parsedData: { ...snapshot, sections: outSections },
            job: job as unknown as Record<string, unknown>,
            isFresher: Boolean(prof.is_fresher),
          });

          return {
            ...p,
            format_type: formatPreference,
            ats_score_before: atsBefore.total,
            ats_score_after: atsAfter.total,
            ats_breakdown_before: atsBefore,
            ats_breakdown_after: atsAfter,
          };
        },
        analyticsEvent: "resume_generated",
      },
      { store },
    );

    if (!outcome.ok) {
      return json({ error: { code: outcome.code, message: outcome.message } }, { status: outcome.status });
    }

    // Deterministic DOCX & PDF assembly via engine
    const documentId = (outcome.body.document_id as string | null) ?? null;
    if (documentId) {
      const rendered = await renderDocumentViaEngine({
        document_id: documentId,
        user_id: user.id,
        job_id: jobId,
        document_type: "resume",
        format_type: formatPreference,
        output_json: outcome.body.output,
        profile: { ...(prof as Record<string, unknown>), section_order: sectionOrder },
        job: job as unknown as Record<string, unknown>,
      });
      if (rendered) {
        if (rendered.docx_path) {
          outcome.body.docx_url = await createDocumentSignedUrl(client, rendered.docx_path);
          outcome.body.docx_path = rendered.docx_path;
        }
        if (rendered.storage_path) {
          outcome.body.pdf_url = await createDocumentSignedUrl(client, rendered.storage_path);
          outcome.body.pdf_path = rendered.storage_path;
        }
      }
    } else if (typeof outcome.body.file_path === "string") {
      // Idempotent hit: sign existing paths
      outcome.body.pdf_url = await createDocumentSignedUrl(client, outcome.body.file_path as string);
      const docxPath = outcome.body.file_path.replace(/\.pdf$/, ".docx");
      outcome.body.docx_url = await createDocumentSignedUrl(client, docxPath);
    }

    // Delete prior completed document for same (user, job, format)
    if (documentId) {
      await deletePreviousDocument(client, user.id, jobId, formatPreference, documentId);
    }

    return json(outcome.body);
  } catch (err) {
    console.error("generate-tailored-resume error:", err);
    return serverError();
  }
});

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
    // Non-fatal cleanup
  }
}
