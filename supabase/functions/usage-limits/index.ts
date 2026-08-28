/**
 * GET /functions/v1/usage-limits
 * Auth required. Returns the caller's effective plan, today's consumed
 * counters, and remaining allowance per action (drives the FE quota UI).
 */
import { createUserClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { handleOptions, json, unauthorized, serverError } from "../_shared/http.ts";
import { DAILY_LIMITS, effectivePlan, isTrialActive, USAGE_FIELDS, type ProfileRow } from "../_shared/usage-limits.ts";

Deno.serve(async (req) => {
  const preflight = handleOptions(req);
  if (preflight) return preflight;
  if (req.method !== "GET") return json({ error: { code: "method_not_allowed", message: "GET only" } }, { status: 405 });
  if (!hasAuthHeader(req)) return unauthorized();

  try {
    const client = createUserClient(req);
    const user = await getAuthUser(client);
    if (!user) return unauthorized();

    const { data: profile } = await client.from("profiles").select("*").eq("id", user.id).maybeSingle();
    const prof = (profile ?? null) as ProfileRow | null;
    const plan = effectivePlan(prof);
    const limits = DAILY_LIMITS[plan];

    const today = new Date().toISOString().slice(0, 10);
    const { data: row } = await client
      .from("usage_limits")
      .select("*")
      .eq("user_id", user.id)
      .eq("date", today)
      .maybeSingle();

    const consumed = (row ?? {}) as Record<string, number>;
    const usage: Record<string, { used: number; limit: number; remaining: number }> = {};
    for (const field of USAGE_FIELDS) {
      const used = Number(consumed[field] ?? 0);
      const limit = limits[field];
      usage[field] = { used, limit, remaining: Math.max(0, limit - used) };
    }

    return json({
      plan,
      trial_active: isTrialActive(prof),
      trial_ends_at: prof?.trial_ends_at ?? null,
      date: today,
      usage,
    });
  } catch (err) {
    console.error("usage-limits error:", err);
    return serverError();
  }
});
