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
        postProcess: (p) => ({ ...p, format_type: formatPreference }),
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

    return json(outcome.body);
  } catch (err) {
    console.error("generate-tailored-resume error:", err);
    return serverError();
  }
});
