/**
 * POST /functions/v1/generate-tailored-resume
 * Auth required + usage-limit gated (resume_generations).
 * Grounded in resume_matcher.py semantics: keywords_to_add is woven in only
 * where truthful; tailoring_notes feeds the FE "what changed" summary
 * (docs/contracts/tailored_resume.schema.json).
 *
 * Body: { resume_id: string, job_id: string,
 *         format_preference?: "own"|"professional" }
 */
import type { ProfileSnapshot } from "../_shared/prompts.ts";
import { createUserClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { handleOptions, json, badRequest, unauthorized, serverError } from "../_shared/http.ts";
import { buildTailoredResumePrompt, PROMPT_VERSIONS } from "../_shared/prompts.ts";
import { runGeneration } from "../_shared/generation.ts";
import { createGenerationStore } from "../_shared/supabase-store.ts";
import { loadJob, loadResume } from "../_shared/jobs.ts";
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
          return null;
        },
        postProcess: (p) => ({ ...p, format_type: formatPreference }),
        analyticsEvent: "resume_generated",
      },
      { store },
    );

    if (!outcome.ok) {
      return json({ error: { code: outcome.code, message: outcome.message } }, { status: outcome.status });
    }
    return json(outcome.body);
  } catch (err) {
    console.error("generate-tailored-resume error:", err);
    return serverError();
  }
});
