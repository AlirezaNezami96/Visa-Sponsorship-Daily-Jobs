/**
 * Critical-path tests for plan/trial math and usage-limit enforcement
 * (master plan sections 10.3, 10.6):
 *   - trial end-date math
 *   - Pro -> Free downgrade (expired trial) revokes elevated limits
 *   - atomic consume via RPC; at-limit -> allowed=false
 */
import { describe, it, expect } from "vitest";
import {
  effectivePlan,
  isTrialActive,
  consumeUsage,
  checkUsage,
  DAILY_LIMITS,
  type ProfileRow,
  type AdminClientLike,
  type UsageReadClient,
} from "./usage-limits.ts";

const day = 24 * 60 * 60 * 1000;

function profile(overrides: Partial<ProfileRow> = {}): ProfileRow {
  return { id: "u1", subscription_plan: "free", ...overrides };
}

describe("effectivePlan / trial math", () => {
  it("defaults to free with no profile", () => {
    expect(effectivePlan(null)).toBe("free");
    expect(effectivePlan(undefined)).toBe("free");
  });

  it("honors an explicit pro subscription regardless of trial", () => {
    const past = new Date(Date.now() - day).toISOString();
    expect(effectivePlan(profile({ subscription_plan: "pro", trial_ends_at: past }))).toBe("pro");
  });

  it("treats an unexpired trial as pro", () => {
    const now = new Date();
    const future = new Date(now.getTime() + day).toISOString();
    expect(effectivePlan(profile({ trial_ends_at: future }), now)).toBe("pro");
    expect(isTrialActive(profile({ trial_ends_at: future }), now)).toBe(true);
  });

  it("revokes pro when the trial end date has passed (downgrade to free)", () => {
    const now = new Date();
    const past = new Date(now.getTime() - day).toISOString();
    expect(effectivePlan(profile({ trial_ends_at: past }), now)).toBe("free");
    expect(isTrialActive(profile({ trial_ends_at: past }), now)).toBe(false);
    // The exact boundary: ending exactly now is still active (inclusive end).
    const exact = now.toISOString();
    expect(effectivePlan(profile({ trial_ends_at: exact }), now)).toBe("pro");
  });

  it("pro grants strictly higher daily limits than free", () => {
    for (const key of Object.keys(DAILY_LIMITS.free) as Array<keyof typeof DAILY_LIMITS.free>) {
      expect(DAILY_LIMITS.pro[key]).toBeGreaterThan(DAILY_LIMITS.free[key]);
    }
  });
});

function fakeRpc(responder: (args: { p_field: string; p_limit: number }) => unknown): AdminClientLike {
  return {
    rpc: (_fn, args) => Promise.resolve({ data: responder(args) }) as unknown as ReturnType<AdminClientLike["rpc"]>,
  };
}

describe("consumeUsage", () => {
  it("passes the plan-appropriate limit to the RPC and returns its verdict", async () => {
    let seen: { p_field?: string; p_limit?: number } = {};
    const client = fakeRpc((args) => {
      seen = args;
      return { allowed: true, count: 1, limit: args.p_limit };
    });

    const decision = await consumeUsage(client, "cover_letter_generations", profile());
    expect(seen.p_field).toBe("cover_letter_generations");
    expect(seen.p_limit).toBe(DAILY_LIMITS.free.cover_letter_generations);
    expect(decision.allowed).toBe(true);
    expect(decision.plan).toBe("free");
  });

  it("uses pro limits for a pro profile", async () => {
    let seenLimit = -1;
    const client = fakeRpc((args) => {
      seenLimit = args.p_limit;
      return { allowed: true, count: 1, limit: args.p_limit };
    });
    await consumeUsage(client, "resume_generations", profile({ subscription_plan: "pro" }));
    expect(seenLimit).toBe(DAILY_LIMITS.pro.resume_generations);
  });

  it("returns allowed=false when the RPC reports the counter at the cap", async () => {
    const client = fakeRpc((args) => ({ allowed: false, count: args.p_limit, limit: args.p_limit }));
    const decision = await consumeUsage(client, "cover_letter_generations", profile());
    expect(decision.allowed).toBe(false);
    expect(decision.count).toBe(decision.limit);
  });

  it("throws on an unknown usage field (no silent success)", async () => {
    const client = fakeRpc(() => ({ allowed: true, count: 0, limit: 1 }));
    await expect(
      consumeUsage(client, "bogus_field" as never, profile()),
    ).rejects.toThrow(/unknown usage field/);
  });
});

function fakeReadClient(row: Record<string, unknown> | null, error?: string): UsageReadClient {
  return {
    from: (_table: string) => ({
      select: (_cols: string) => ({
        eq: (_c: string, _v: string) => ({
          eq: (_c2: string, _v2: string) =>
            Promise.resolve({ data: row, error: error ? { message: error } : null }) as never,
        }),
      }),
    }),
  };
}

describe("checkUsage (read-only gate)", () => {
  it("allows when below the limit without mutating anything", async () => {
    const client = fakeReadClient({ cover_letter_generations: 1 });
    const decision = await checkUsage(client, "cover_letter_generations", profile());
    expect(decision.allowed).toBe(true);
    expect(decision.count).toBe(1);
    expect(decision.limit).toBe(DAILY_LIMITS.free.cover_letter_generations);
  });

  it("rejects at the limit", async () => {
    const client = fakeReadClient({ cover_letter_generations: DAILY_LIMITS.free.cover_letter_generations });
    const decision = await checkUsage(client, "cover_letter_generations", profile());
    expect(decision.allowed).toBe(false);
  });

  it("treats a missing row as zero usage", async () => {
    const decision = await checkUsage(fakeReadClient(null), "resume_generations", profile());
    expect(decision.allowed).toBe(true);
    expect(decision.count).toBe(0);
  });

  it("uses pro limits for pro profiles", async () => {
    const client = fakeReadClient({ resume_generations: 5 });
    const decision = await checkUsage(client, "resume_generations", profile({ subscription_plan: "pro" }));
    expect(decision.allowed).toBe(true);
    expect(decision.limit).toBe(DAILY_LIMITS.pro.resume_generations);
    expect(decision.plan).toBe("pro");
  });

  it("throws on infrastructure failure (no fail-open)", async () => {
    const client = fakeReadClient(null, "rpc down");
    await expect(checkUsage(client, "resume_generations", profile())).rejects.toThrow(/usage check failed/);
  });
});
