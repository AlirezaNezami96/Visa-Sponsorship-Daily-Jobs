/**
 * POST /functions/v1/parse-resume
 * Auth required. Extracts structured data from uploaded resume text in-memory.
 * Privacy rule (ported from resume_fetch.py): raw text is processed in memory
 * and never persisted to disk; only structured data is stored under user RLS.
 *
 * Body: { resume_text: string }  OR  { resume_id: string, resume_text?: string }
 */
import { createUserClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { handleOptions, json, badRequest, unauthorized, serverError } from "../_shared/http.ts";
import { buildParseResumePrompt, PROMPT_VERSIONS } from "../_shared/prompts.ts";
import { runGeneration } from "../_shared/generation.ts";
import { createGenerationStore } from "../_shared/supabase-store.ts";
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
    const resumeText: string = typeof body.resume_text === "string" ? body.resume_text : "";
    if (resumeText.trim().length < 20) {
      return badRequest("resume_text must be provided (>= 20 chars)");
    }

    const { data: profile } = await client.from("profiles").select("*").eq("id", user.id).maybeSingle();
    const store = createGenerationStore(client);

    const outcome = await runGeneration(
      {
        userId: user.id,
        profile: (profile ?? null) as ProfileRow | null,
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
      return json({ error: { code: outcome.code, message: outcome.message } }, { status: outcome.status });
    }

    // Persist structured parsed data back onto the resume row when provided.
    if (typeof body.resume_id === "string") {
      try {
        await client
          .from("resumes")
          .update({ parsed_data: outcome.body.output })
          .eq("id", body.resume_id)
          .eq("user_id", user.id);
      } catch {
        /* non-fatal: response already carries the parsed data */
      }
    }

    return json(outcome.body);
  } catch (err) {
    console.error("parse-resume error:", err);
    return serverError();
  }
});
