/**
 * Critical-path tests for the generation pipeline (GAP 3 contracts):
 *   - idempotent completed documents return instantly (no charge, no AI)
 *   - usage-limit CHECK rejects 402 BEFORE any provider is contacted
 *   - quota is consumed ONLY after validation passes (failed runs free)
 *   - repair retry on the same provider, then waterfall advance
 *   - all-providers-failed -> friendly 500 + ai_error
 *   - fallback events recorded when the chain advances
 */
import { describe, it, expect, beforeEach } from "vitest";
import {
  runGeneration,
  computeIdempotencyKey,
  type GenerationStore,
  type GeneratedDocumentInput,
  type AnalyticsEventInput,
  type CompletedDocument,
} from "./generation.ts";
import type { LimitDecision, ProfileRow, UsageField } from "./usage-limits.ts";
import { DAILY_LIMITS } from "./usage-limits.ts";
import { setEnvForTest, clearEnvOverrides } from "./env.ts";
import { PROMPT_VERSIONS } from "./prompts.ts";

class FakeStore implements GenerationStore {
  checkVerdict: LimitDecision = { allowed: true, count: 0, limit: 10, plan: "free" };
  consumeVerdict: LimitDecision = { allowed: true, count: 1, limit: 10, plan: "free" };
  existing: CompletedDocument | null = null;
  documents: GeneratedDocumentInput[] = [];
  events: AnalyticsEventInput[] = [];
  checkCalls = 0;
  consumeCalls = 0;

  checkUsage(_field: UsageField, _profile: ProfileRow | null) {
    this.checkCalls += 1;
    return this.checkVerdict;
  }
  consumeUsage(_field: UsageField, _profile: ProfileRow | null) {
    this.consumeCalls += 1;
    return this.consumeVerdict;
  }
  async findCompletedDocument(_key: string, _userId: string) {
    return this.existing;
  }
  async insertDocument(doc: GeneratedDocumentInput) {
    this.documents.push(doc);
    return `doc-${this.documents.length}`;
  }
  async insertEvent(event: AnalyticsEventInput) {
    this.events.push(event);
  }
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function geminiOk(text: string): Response {
  return jsonResponse(200, { candidates: [{ content: { parts: [{ text }] } }] });
}

const baseReq = {
  userId: "user-1",
  profile: { id: "user-1", subscription_plan: "free" } as ProfileRow,
  usageField: "cover_letter_generations" as const,
  documentType: "cover_letter" as const,
  jobId: "job-1",
  promptVersion: PROMPT_VERSIONS.coverLetter,
  buildPrompt: () => "PROMPT",
  validate: () => null,
  analyticsEvent: "cover_letter_generated",
};

beforeEach(() => {
  clearEnvOverrides();
  setEnvForTest("GEMINI_API_KEY", "g-key");
});

describe("idempotency (GAP 3.3)", () => {
  it("returns a completed document without charge or AI call", async () => {
    const store = new FakeStore();
    store.existing = {
      id: "doc-77",
      output_json: { cover_letter_markdown: "cached letter", prompt_version: PROMPT_VERSIONS.coverLetter },
      file_path: "user-1/jobs/job-1/cover_letter/doc-77.pdf",
      ai_provider: "gemini",
      ai_model: "gemini-2.5-flash",
    };
    let fetchCalls = 0;
    const fetchImpl: typeof fetch = async () => {
      fetchCalls += 1;
      return geminiOk("{}");
    };

    const outcome = await runGeneration(baseReq, { store, aiOptions: { fetchImpl, cache: new Map() } });

    expect(outcome.ok).toBe(true);
    if (outcome.ok) {
      expect(outcome.body.document_id).toBe("doc-77");
      expect(outcome.body.idempotent).toBe(true);
      expect(outcome.body.cached).toBe(true);
      expect(outcome.body.file_path).toBe("user-1/jobs/job-1/cover_letter/doc-77.pdf");
    }
    expect(store.checkCalls).toBe(0);
    expect(store.consumeCalls).toBe(0);
    expect(fetchCalls).toBe(0);
  });

  it("derives stable keys from (user, job, type, format, profile.updated_at, prompt_version)", () => {
    const key = computeIdempotencyKey({
      userId: "u",
      jobId: "j",
      documentType: "resume",
      formatType: "professional",
      profileUpdatedAt: "2026-08-28T10:00:00Z",
      promptVersion: "tailor-v2",
    });
    const keyAgain = computeIdempotencyKey({
      userId: "u",
      jobId: "j",
      documentType: "resume",
      formatType: "professional",
      profileUpdatedAt: "2026-08-28T10:00:00Z",
      promptVersion: "tailor-v2",
    });
    const keyAfterProfileEdit = computeIdempotencyKey({
      userId: "u",
      jobId: "j",
      documentType: "resume",
      formatType: "professional",
      profileUpdatedAt: "2026-08-29T00:00:00Z",
      promptVersion: "tailor-v2",
    });
    expect(key).toBe(keyAgain);
    expect(key).not.toBe(keyAfterProfileEdit);
  });
});

describe("usage-limit gate (402 before AI)", () => {
  it("rejects with 402 BEFORE calling any AI provider when the limit is reached", async () => {
    const store = new FakeStore();
    store.checkVerdict = {
      allowed: false,
      count: DAILY_LIMITS.free.cover_letter_generations,
      limit: DAILY_LIMITS.free.cover_letter_generations,
      plan: "free",
    };

    let providerCalls = 0;
    const fetchImpl: typeof fetch = async () => {
      providerCalls += 1;
      return geminiOk("{}");
    };

    const outcome = await runGeneration(baseReq, { store, aiOptions: { fetchImpl, cache: new Map() } });

    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.status).toBe(402);
      expect(outcome.code).toBe("usage_limit_reached");
    }
    expect(providerCalls).toBe(0);
    expect(store.checkCalls).toBe(1);
    expect(store.consumeCalls).toBe(0);
    expect(store.documents.length).toBe(0);
  });
});

describe("quota correctness (GAP 3.3)", () => {
  it("consumes quota exactly once and only after validation passes", async () => {
    const store = new FakeStore();
    const fetchImpl: typeof fetch = async () => geminiOk('{"cover_letter_markdown":"hi"}');

    const outcome = await runGeneration(baseReq, { store, aiOptions: { fetchImpl, cache: new Map() } });

    expect(outcome.ok).toBe(true);
    expect(store.consumeCalls).toBe(1);
    const completed = store.documents.find((d) => d.status === "completed");
    expect(completed?.document_type).toBe("cover_letter");
    expect(completed?.idempotency_key).toBeTruthy();
  });

  it("never charges quota when every provider/validation fails", async () => {
    const store = new FakeStore();
    setEnvForTest("GROQ_API_KEY", "q");
    setEnvForTest("OPENROUTER_API_KEY", "o");
    const fetchImpl: typeof fetch = async () => jsonResponse(500, {});

    const outcome = await runGeneration(baseReq, { store, aiOptions: { fetchImpl, cache: new Map() } });

    expect(outcome.ok).toBe(false);
    expect(store.consumeCalls).toBe(0);
    expect(store.documents.some((d) => d.status === "failed")).toBe(true);
  });

  it("returns 402 without persisting when the atomic increment loses a race", async () => {
    const store = new FakeStore();
    store.consumeVerdict = { allowed: false, count: 2, limit: 2, plan: "free" };
    const fetchImpl: typeof fetch = async () => geminiOk('{"cover_letter_markdown":"hi"}');

    const outcome = await runGeneration(baseReq, { store, aiOptions: { fetchImpl, cache: new Map() } });

    expect(outcome.ok).toBe(false);
    if (!outcome.ok) expect(outcome.status).toBe(402);
    expect(store.documents.length).toBe(0);
  });
});

describe("repair-then-waterfall (GAP 3.2)", () => {
  it("repairs on the same provider and logs ai_validation_repair", async () => {
    const store = new FakeStore();
    let calls = 0;
    const fetchImpl: typeof fetch = async (input, init) => {
      calls += 1;
      const prompt = JSON.parse(String(init?.body)).contents[0].parts[0].text as string;
      // First attempt is bad; the repair prompt (containing REJECTED) is fixed.
      return geminiOk(prompt.includes("REJECTED") ? '{"cover_letter_markdown":"fixed"}' : '{"other":1}');
    };

    const outcome = await runGeneration(
      { ...baseReq, validate: (p) => (typeof p.cover_letter_markdown === "string" ? null : "missing letter") },
      { store, aiOptions: { fetchImpl, cache: new Map() } },
    );

    expect(outcome.ok).toBe(true);
    expect(calls).toBe(2);
    const repair = store.events.find((e) => e.event_name === "ai_validation_repair");
    expect(repair).toBeDefined();
    expect((repair?.metadata as Record<string, unknown>).resolved).toBe(true);
    // No provider change occurred, so no fallback event.
    expect(store.events.some((e) => e.event_name === "ai_fallback_triggered")).toBe(false);
  });

  it("advances the waterfall when the repair also fails (fallback observed)", async () => {
    const store = new FakeStore();
    setEnvForTest("GROQ_API_KEY", "q-key");
    const fetchImpl: typeof fetch = async (input) => {
      const url = String(input);
      if (url.includes("api.groq.com")) {
        return jsonResponse(200, { choices: [{ message: { content: '{"cover_letter_markdown":"from groq"}' } }] });
      }
      return geminiOk('{"other":1}'); // gemini: always invalid, even after repair
    };

    const outcome = await runGeneration(
      { ...baseReq, validate: (p) => (typeof p.cover_letter_markdown === "string" ? null : "missing letter") },
      { store, aiOptions: { fetchImpl, cache: new Map() } },
    );

    expect(outcome.ok).toBe(true);
    if (outcome.ok) {
      expect((outcome.body.output as Record<string, unknown>).cover_letter_markdown).toBe("from groq");
      expect(outcome.body.ai_provider).toBe("groq");
    }
    const fallback = store.events.find((e) => e.event_name === "ai_fallback_triggered");
    expect(fallback).toBeDefined();
    expect((fallback?.metadata as Record<string, unknown>).from_provider).toBe("gemini");
    expect(String((fallback?.metadata as Record<string, unknown>).reason)).toContain("validation_failed");
  });

  it("returns friendly 500 + ai_error when all providers fail (no charge)", async () => {
    const store = new FakeStore();
    setEnvForTest("GROQ_API_KEY", "q");
    setEnvForTest("OPENROUTER_API_KEY", "o");
    const fetchImpl: typeof fetch = async () => jsonResponse(500, {});

    const outcome = await runGeneration(baseReq, { store, aiOptions: { fetchImpl, cache: new Map() } });

    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.status).toBe(500);
      expect(outcome.code).toBe("ai_generation_failed");
      expect(outcome.message).toMatch(/try again/i);
    }
    expect(store.documents.some((d) => d.status === "failed")).toBe(true);
    expect(store.events.some((e) => e.event_name === "ai_error")).toBe(true);
    expect(store.consumeCalls).toBe(0);
  });
});

describe("success bookkeeping", () => {
  it("persists a completed document and emits the analytics event", async () => {
    const store = new FakeStore();
    const fetchImpl: typeof fetch = async () => geminiOk('{"cover_letter_markdown":"hi"}');

    const outcome = await runGeneration(baseReq, { store, aiOptions: { fetchImpl, cache: new Map() } });

    expect(outcome.ok).toBe(true);
    if (outcome.ok) {
      expect(outcome.status).toBe(200);
      expect(outcome.body.document_id).toBe("doc-1");
      expect((outcome.body.output as Record<string, unknown>).cover_letter_markdown).toBe("hi");
    }
    expect(store.events.some((e) => e.event_name === "cover_letter_generated")).toBe(true);
  });

  it("falls back on provider HTTP errors and still succeeds downstream", async () => {
    const store = new FakeStore();
    setEnvForTest("GROQ_API_KEY", "q-key");
    const fetchImpl: typeof fetch = async (input) => {
      const url = String(input);
      if (url.includes("generativelanguage.googleapis.com")) return jsonResponse(429, {});
      if (url.includes("api.groq.com")) {
        return jsonResponse(200, { choices: [{ message: { content: '{"cover_letter_markdown":"x"}' } }] });
      }
      return jsonResponse(500, {});
    };

    const outcome = await runGeneration(baseReq, { store, aiOptions: { fetchImpl, cache: new Map() } });

    expect(outcome.ok).toBe(true);
    const fallback = store.events.find((e) => e.event_name === "ai_fallback_triggered");
    expect(fallback).toBeDefined();
    expect((fallback?.metadata as Record<string, unknown>).from_provider).toBe("gemini");
  });
});
