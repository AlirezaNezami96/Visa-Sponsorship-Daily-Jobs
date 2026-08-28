/**
 * POST /functions/v1/generate-cover-letter
 * Auth required + usage-limit gated (cover_letter_generations).
 * Produces a hallucination-guarded, best-in-class cover letter
 * (docs/contracts/cover_letter.schema.json).
 *
 * Body: { job_id: string, resume_id?: string, format_preference?: "own"|"professional" }
 */
import type { ProfileSnapshot } from "../_shared/prompts.ts";
import { createUserClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { handleOptions, json, badRequest, unauthorized, serverError } from "../_shared/http.ts";
import { buildCoverLetterPrompt, PROMPT_VERSIONS } from "../_shared/prompts.ts";
import { runGeneration } from "../_shared/generation.ts";
import { createGenerationStore } from "../_shared/supabase-store.ts";
import { loadCompanyIntel, loadJob, loadResume } from "../_shared/jobs.ts";
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
    const jobId: string = typeof body.job_id === "string" ? body.job_id : "";
    if (!jobId) return badRequest("job_id is required");

    const { data: profile } = await client.from("profiles").select("*").eq("id", user.id).maybeSingle();
    const prof = (profile ?? {}) as ProfileRow & Record<string, unknown>;

    const job = await loadJob(client, jobId);
    if (!job) return badRequest("job not found");

    let resumeText = "";
    if (typeof body.resume_id === "string") {
      const resume = await loadResume(client, user.id, body.resume_id);
      if (resume) resumeText = String(resume.raw_text ?? "") || JSON.stringify(resume.parsed_data ?? {});
    }

    const companyId = (job as unknown as { company_id?: string | null }).company_id;
    const hook = companyId ? await loadCompanyIntel(client, companyId) : null;

    const store = createGenerationStore(client);
    const outcome = await runGeneration(
      {
        userId: user.id,
        profile: prof as ProfileRow,
        usageField: "cover_letter_generations",
        documentType: "cover_letter",
        jobId,
        promptVersion: PROMPT_VERSIONS.coverLetter,
        buildPrompt: () =>
          buildCoverLetterPrompt({
            profile: prof as unknown as ProfileSnapshot,
            resumeText,
            job,
            companyHookContext: hook ?? undefined,
          }),
        validate: (p) => {
          if (typeof p.cover_letter_markdown !== "string" || !p.cover_letter_markdown.trim()) {
            return "missing cover_letter_markdown";
          }
          return null;
        },
        postProcess: (p) => ({
          ...p,
          format_type: body.format_preference === "own" ? "own" : "professional",
        }),
        analyticsEvent: "cover_letter_generated",
      },
      { store },
    );

    if (!outcome.ok) {
      return json({ error: { code: outcome.code, message: outcome.message } }, { status: outcome.status });
    }
    return json(outcome.body);
  } catch (err) {
    console.error("generate-cover-letter error:", err);
    return serverError();
  }
});
