/**
 * POST /functions/v1/generate-outreach-messages
 * Auth required. Personalized email + LinkedIn outreach per profile + JD +
 * company + contact. LinkedIn is hard-capped at 300 chars SERVER-SIDE before
 * storing (docs/contracts/outreach_messages.schema.json).
 *
 * GAP 3 hardening: validators.ts (LinkedIn hard cap, email word cap, tone),
 * repair-then-waterfall, idempotency, post-validation quota. The outreach
 * message shares the cover_letter_generations quota (no separate counter).
 *
 * Body: { job_id: string, resume_id?: string,
 *         tone?: "professional"|"friendly"|"natural" (default natural) }
 */
import type { ProfileSnapshot } from "../_shared/prompts.ts";
import { createUserClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { handleOptions, json, badRequest, unauthorized, serverError } from "../_shared/http.ts";
import { buildOutreachPrompt, enforceLinkedinLimit, PROMPT_VERSIONS } from "../_shared/prompts.ts";
import { runGeneration } from "../_shared/generation.ts";
import { createGenerationStore } from "../_shared/supabase-store.ts";
import { loadCompanyIntel, loadJob, loadResume } from "../_shared/jobs.ts";
import { validateOutreach } from "../_shared/validators.ts";
import type { ProfileRow } from "../_shared/usage-limits.ts";

const TONES = new Set(["professional", "friendly", "natural"]);

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
    const tone = TONES.has(body.tone) ? body.tone : "natural";

    const { data: profile } = await client.from("profiles").select("*").eq("id", user.id).maybeSingle();
    const prof = (profile ?? {}) as ProfileRow & Record<string, unknown>;

    const job = await loadJob(client, jobId);
    if (!job) return badRequest("job not found");

    let resumeText = "";
    if (typeof body.resume_id === "string") {
      const resume = await loadResume(client, user.id, body.resume_id);
      if (resume) resumeText = String(resume.raw_text ?? "") || JSON.stringify(resume.parsed_data ?? {});
    }

    const contacts = (job as unknown as { contacts?: Array<Record<string, unknown>> }).contacts ?? [];
    const primaryContact = contacts.find((c) => c?.name) ?? null;
    const companyId = (job as unknown as { company_id?: string | null }).company_id;
    const hook = companyId ? await loadCompanyIntel(client, companyId) : null;

    const store = createGenerationStore(client);
    const outcome = await runGeneration(
      {
        userId: user.id,
        profile: prof as ProfileRow,
        usageField: "cover_letter_generations",
        documentType: "outreach_email",
        jobId,
        promptVersion: PROMPT_VERSIONS.outreach,
        formatType: tone,
        profileUpdatedAt: (prof.updated_at as string | null) ?? null,
        inputProfileSnapshot: { full_name: prof.full_name ?? null, skills: prof.skills ?? null },
        buildPrompt: () =>
          buildOutreachPrompt({
            profile: prof as unknown as ProfileSnapshot,
            job,
            tone,
            contact: primaryContact,
            companyHookContext: hook ?? undefined,
          }),
        validate: (p) => {
          const email = p.email as Record<string, unknown> | undefined;
          const linkedin = p.linkedin as Record<string, unknown> | undefined;
          if (!email || typeof email.body !== "string") return "missing email.body";
          if (!linkedin || typeof linkedin.body !== "string") return "missing linkedin.body";
          // GAP 3.1 hard caps: LinkedIn <= 300 chars, email <= 220 words, tone kept.
          return validateOutreach(p, tone);
        },
        postProcess: (p) => {
          // Hard server-side LinkedIn cap BEFORE storing — never over-limit.
          const linkedin = p.linkedin as Record<string, unknown>;
          const capped = enforceLinkedinLimit(String(linkedin.body ?? ""));
          const linkedinRows = {
            body: capped.body,
            tone,
            trimmed_to_limit: capped.trimmed,
          };
          // Persist a companion outreach_linkedin document row too.
          store.insertDocument({
            user_id: user.id,
            job_id: jobId,
            document_type: "outreach_linkedin",
            status: "completed",
            prompt_version: PROMPT_VERSIONS.outreach,
            format_type: tone,
            output_json: linkedinRows,
          }).catch(() => undefined);
          return { ...p, linkedin: linkedinRows, resume_context: resumeText ? "used" : "absent" };
        },
        analyticsEvent: "cover_letter_generated",
      },
      { store },
    );

    if (!outcome.ok) {
      return json({ error: { code: outcome.code, message: outcome.message } }, { status: outcome.status });
    }
    return json(outcome.body);
  } catch (err) {
    console.error("generate-outreach-messages error:", err);
    return serverError();
  }
});
