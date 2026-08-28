/**
 * POST /functions/v1/generate-cover-letter
 * Auth required + usage-limit gated (cover_letter_generations).
 * Produces a hallucination-guarded, best-in-class cover letter
 * (docs/contracts/cover_letter.schema.json).
 *
 * GAP 3 hardening: validators.ts cross-check (word count, blocklist, company
 * + user-fact grounding), repair-then-waterfall, idempotency, post-validation
 * quota. GAP 2: PDF assembled by the engine; `pdf_url` signed for 1 hour.
 *
 * Body: { job_id: string, resume_id?: string, format_preference?: "own"|"professional" }
 */
import type { ProfileSnapshot as PromptProfileSnapshot } from "../_shared/prompts.ts";
import { createUserClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { handleOptions, json, badRequest, unauthorized, serverError } from "../_shared/http.ts";
import { buildCoverLetterPrompt, PROMPT_VERSIONS } from "../_shared/prompts.ts";
import { runGeneration } from "../_shared/generation.ts";
import { createGenerationStore, createDocumentSignedUrl, renderDocumentViaEngine } from "../_shared/supabase-store.ts";
import { loadCompanyIntel, loadJob, loadResume } from "../_shared/jobs.ts";
import { validateCoverLetter, type ProfileSnapshot } from "../_shared/validators.ts";
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
    let parsedData: Record<string, unknown> | null = null;
    if (typeof body.resume_id === "string") {
      const resume = await loadResume(client, user.id, body.resume_id);
      if (resume) {
        resumeText = String(resume.raw_text ?? "") || JSON.stringify(resume.parsed_data ?? {});
        parsedData = (resume.parsed_data ?? null) as Record<string, unknown> | null;
      }
    }

    const companyId = (job as unknown as { company_id?: string | null }).company_id;
    const hook = companyId ? await loadCompanyIntel(client, companyId) : null;

    // Grounding snapshot: profile facts + parsed resume (skills/metrics).
    const profileSkills = Array.isArray(prof.skills) ? (prof.skills as string[]) : [];
    const parsedSkills = Array.isArray(parsedData?.skills) ? (parsedData?.skills as string[]) : [];
    const snapshot: ProfileSnapshot = {
      full_name: (prof.full_name as string | null) ?? null,
      skills: [...profileSkills, ...parsedSkills],
      experience: (parsedData?.experience as ProfileSnapshot["experience"]) ?? null,
      education: (parsedData?.education as ProfileSnapshot["education"]) ?? null,
    };
    const formatPreference = body.format_preference === "own" ? "own" : "professional";

    const store = createGenerationStore(client);
    const outcome = await runGeneration(
      {
        userId: user.id,
        profile: prof as ProfileRow,
        usageField: "cover_letter_generations",
        documentType: "cover_letter",
        jobId,
        promptVersion: PROMPT_VERSIONS.coverLetter,
        formatType: formatPreference,
        profileUpdatedAt: (prof.updated_at as string | null) ?? null,
        inputProfileSnapshot: snapshot as unknown as Record<string, unknown>,
        buildPrompt: () =>
          buildCoverLetterPrompt({
            profile: prof as unknown as PromptProfileSnapshot,
            resumeText,
            job,
            companyHookContext: hook ?? undefined,
          }),
        validate: (p) =>
          validateCoverLetter(p, snapshot, { company: job.company, companyHookContext: hook ?? undefined }),
        postProcess: (p) => ({ ...p, format_type: formatPreference }),
        analyticsEvent: "cover_letter_generated",
      },
      { store },
    );

    if (!outcome.ok) {
      return json({ error: { code: outcome.code, message: outcome.message } }, { status: outcome.status });
    }

    const documentId = (outcome.body.document_id as string | null) ?? null;
    if (documentId) {
      const rendered = await renderDocumentViaEngine({
        document_id: documentId,
        user_id: user.id,
        job_id: jobId,
        document_type: "cover_letter",
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
      outcome.body.pdf_url = await createDocumentSignedUrl(client, outcome.body.file_path as string);
    }

    return json(outcome.body);
  } catch (err) {
    console.error("generate-cover-letter error:", err);
    return serverError();
  }
});
