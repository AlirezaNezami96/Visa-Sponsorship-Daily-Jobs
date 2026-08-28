/**
 * Plan-aware daily usage limits.
 *
 * Enforcement MUST happen before any AI provider call (master plan critical
 * path #3): a user at their limit gets 402 and the providers are never called.
 *
 * Counters are incremented atomically via the `increment_usage_limit` RPC so
 * concurrent requests cannot race past the cap.
 */
import { getEnv } from "./env.ts";

export interface ProfileRow {
  id?: string;
  subscription_plan?: string | null;
  trial_started_at?: string | null;
  trial_ends_at?: string | null;
  // Permissive: callers pass full profiles/rows with extra columns
  // (full_name, skills, resume_format_preference, ...) used by prompt builders.
  [key: string]: unknown;
}

export interface LimitDecision {
  allowed: boolean;
  count: number;
  limit: number;
  plan: "free" | "pro";
}

export const DAILY_LIMITS: Record<"free" | "pro", Record<string, number>> = {
  free: {
    resume_generations: 2,
    cover_letter_generations: 2,
    alert_sends: 5,
    import_attempts: 3,
  },
  pro: {
    resume_generations: 200,
    cover_letter_generations: 200,
    alert_sends: 500,
    import_attempts: 50,
  },
};

export type UsageField = keyof (typeof DAILY_LIMITS)["free"];

export const USAGE_FIELDS: UsageField[] = [
  "resume_generations",
  "cover_letter_generations",
  "alert_sends",
  "import_attempts",
];

/** Resolve effective plan: explicit pro subscription OR an unexpired trial. */
export function effectivePlan(profile: ProfileRow | null | undefined, now: Date = new Date()): "free" | "pro" {
  if (!profile) return "free";
  if (profile.subscription_plan === "pro") return "pro";
  if (profile.trial_ends_at) {
    const ends = new Date(profile.trial_ends_at);
    if (!Number.isNaN(ends.getTime()) && ends.getTime() >= now.getTime()) return "pro";
  }
  return "free";
}

export function isTrialActive(profile: ProfileRow | null | undefined, now: Date = new Date()): boolean {
  if (!profile?.trial_ends_at) return false;
  const ends = new Date(profile.trial_ends_at);
  return !Number.isNaN(ends.getTime()) && ends.getTime() >= now.getTime();
}

/** Minimal RPC client surface (keeps this module DI-friendly for tests). */
export interface AdminClientLike {
  rpc(fn: "increment_usage_limit", args: { p_field: string; p_limit: number }): PromiseLike<{
    data?: unknown;
    error?: { message: string } | null;
  }>;
}

/**
 * Atomically consume one unit of a usage field for the current user.
 * Uses the caller's authenticated client; the RPC is SECURITY DEFINER keyed on
 * auth.uid(), supplied by the user client's JWT.
 */
export async function consumeUsage(
  client: AdminClientLike,
  field: UsageField,
  profile: ProfileRow | null | undefined,
): Promise<LimitDecision> {
  if (!USAGE_FIELDS.includes(field)) {
    throw new Error(`unknown usage field: ${field}`);
  }
  const plan = effectivePlan(profile);
  const limit = DAILY_LIMITS[plan][field];
  const { data, error } = await client.rpc("increment_usage_limit", { p_field: field, p_limit: limit });
  if (error) {
    throw new Error(`usage RPC failed: ${error.message}`);
  }
  const payload = (data ?? {}) as { allowed?: boolean; count?: number; limit?: number };
  return {
    allowed: Boolean(payload.allowed),
    count: Number(payload.count ?? 0),
    limit: Number(payload.limit ?? limit),
    plan,
  };
}

export function serviceRoleConfigured(): boolean {
  return Boolean(getEnv("SUPABASE_URL") && getEnv("SUPABASE_SERVICE_ROLE_KEY"));
}
