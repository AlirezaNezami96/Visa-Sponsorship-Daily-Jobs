/**
 * POST /functions/v1/complete-application
 * Auth required. Upserts an application row (owner RLS), links generated
 * docs, and emits an application_completed analytics event.
 *
 * Body: { job_id: string, resume_document_id?: string, cover_letter_document_id?: string }
 */
import { createUserClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { handleOptions, json, badRequest, unauthorized, serverError } from "../_shared/http.ts";

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

    const payload = {
      user_id: user.id,
      job_id: jobId,
      status: "applied",
      resume_document_id: typeof body.resume_document_id === "string" ? body.resume_document_id : null,
      cover_letter_document_id: typeof body.cover_letter_document_id === "string" ? body.cover_letter_document_id : null,
    };

    const { data, error } = await client
      .from("applications")
      .upsert(payload, { onConflict: "user_id,job_id" })
      .select()
      .single();
    if (error) return serverError(error.message);

    // Fire-and-forget analytics; never blocks the response.
    client
      .from("analytics_events")
      .insert({ event_name: "application_completed", user_id: user.id, job_id: jobId, metadata: {} })
      .then(() => undefined, () => undefined);

    return json({ application: data });
  } catch (err) {
    console.error("complete-application error:", err);
    return serverError();
  }
});
