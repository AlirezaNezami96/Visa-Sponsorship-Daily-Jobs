/**
 * POST /functions/v1/feedback
 * Auth required. Records user feedback (RLS: authenticated insert).
 *
 * Body: { category: string, message: string, page?: string, metadata?: object }
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
    const category = typeof body.category === "string" ? body.category.trim() : "";
    const message = typeof body.message === "string" ? body.message.trim() : "";
    if (!category || !message) return badRequest("category and message are required");

    const { data, error } = await client
      .from("feedback")
      .insert({
        user_id: user.id,
        category: category.slice(0, 100),
        message: message.slice(0, 10000),
        page: typeof body.page === "string" ? body.page.slice(0, 500) : null,
        metadata: body.metadata && typeof body.metadata === "object" ? body.metadata : null,
      })
      .select("id")
      .single();

    if (error) return serverError(error.message);
    return json({ ok: true, id: (data as { id?: string })?.id ?? null }, { status: 201 });
  } catch (err) {
    console.error("feedback error:", err);
    return serverError();
  }
});
