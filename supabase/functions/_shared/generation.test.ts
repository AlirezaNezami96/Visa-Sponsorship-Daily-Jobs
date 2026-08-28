/**
 * Critical-path tests for the generation pipeline ordering
 * (master plan section 10.3): the usage-limit gate MUST reject before any AI
 * provider is contacted, and fallback events MUST be recorded.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { runGeneration, type GenerationStore, type GeneratedDocumentInput, type AnalyticsEventInput } from "./generation.ts";
import type { LimitDecision, ProfileRow, UsageField } from "./usage-limits.ts";
import { DAILY_LIMITS } from "./usage-limits.ts";
import { setEnvForTest, clearEnvOverrides } from "./env.ts";
import { PROMPT_VERSIONS } from "./prompts.ts";

class FakeStore implements GenerationStore {
  verdict: LimitDecision = { allowed: true, count: 1, limit: 10, plan: "free" };
  documents: GeneratedDocumentInput[] = [];
  events: AnalyticsEventInput[] = [];
  consumeCalls = 0;

  consumeUsage(_field: UsageField, _profile: ProfileRow | null) {
    this.consumeCalls += 1;
    if (!this.verdict.allowed) return this.verdict;
    return { ...this.verdict, count: this.verdict.count + 1 };
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

describe("runGeneration usage-limit gate", () => {
  it("rejects with 402 BEFORE calling any AI provider when the limit is reached", async () => {
    const store = new FakeStore();
    store.verdict = { allowed: false, count: DAILY_LIMITS.free.cover_letter_generations, limit: DAILY_LIMITS.free.cover_letter_generations, plan: "free" };

    let providerCalls = 0;
    const fetchImpl: typeof fetch = async () => {
      providerCalls += 1;
      return jsonResponse(200, { candidates: [{ content: { parts: [{ text: "{}" }] } }] });
    };

    const outcome = await runGeneration(baseReq, { store, aiOptions: { fetchImpl, cache: new Map() } });

    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.status).toBe(402);
      expect(outcome.code).toBe("usage_limit_reached");
    }
    // The provider was NEVER contacted.
    expect(providerCalls).toBe(0);
    expect(store.consumeCalls).toBe(1);
  });

  it("does not insert a document row for a usage-limit rejection", async () => {
    const store = new FakeStore();
    store.verdict = { allowed: false, count: 2, limit: 2, plan: "free" };
    const outcome = await runGeneration(baseReq, { store, aiOptions: { fetchImpl: async () => jsonResponse(200, {}), cache: new Map() } });
    expect(outcome.ok).toBe(false);
    expect(store.documents.length).toBe(0);
  });
});

describe("runGeneration success + fallback observability", () => {
  it("persists a completed document and emits the analytics event on success", async () => {
    const store = new FakeStore();
    const fetchImpl: typeof fetch = async () =>
      jsonResponse(200, { candidates: [{ content: { parts: [{ text: '{"cover_letter_markdown":"hi"}' }] } }] });

    const outcome = await runGeneration(baseReq, { store, aiOptions: { fetchImpl, cache: new Map() } });

    expect(outcome.ok).toBe(true);
    if (outcome.ok) {
      expect(outcome.status).toBe(200);
      expect(outcome.body.document_id).toBe("doc-1");
      expect((outcome.body.output as Record<string, unknown>).cover_letter_markdown).toBe("hi");
    }
    const completed = store.documents.find((d) => d.status === "completed");
    expect(completed?.document_type).toBe("cover_letter");
    expect(store.events.some((e) => e.event_name === "cover_letter_generated")).toBe(true);
  });

  it("records an ai_fallback_triggered event when the chain advances", async () => {
    const store = new FakeStore();
    setEnvForTest("GROQ_API_KEY", "q-key");
    const fetchImpl: typeof fetch = async (input) => {
      const url = String(input);
      if (url.includes("generativelanguage.googleapis.com")) return jsonResponse(429, {});
      if (url.includes("api.groq.com")) return jsonResponse(200, { choices: [{ message: { content: '{"cover_letter_markdown":"x"}' } }] });
      return jsonResponse(500, {});
    };

    const outcome = await runGeneration(baseReq, { store, aiOptions: { fetchImpl, cache: new Map() } });

    expect(outcome.ok).toBe(true);
    const fallback = store.events.find((e) => e.event_name === "ai_fallback_triggered");
    expect(fallback).toBeDefined();
    expect((fallback?.metadata as Record<string, unknown>).from_provider).toBe("gemini");
  });

  it("returns 502 and records a failed document when every provider is down", async () => {
    const store = new FakeStore();
    setEnvForTest("GROQ_API_KEY", "q");
    setEnvForTest("OPENROUTER_API_KEY", "o");
    const fetchImpl: typeof fetch = async () => jsonResponse(500, {});

    const outcome = await runGeneration(baseReq, { store, aiOptions: { fetchImpl, cache: new Map() } });

    expect(outcome.ok).toBe(false);
    if (!outcome.ok) expect(outcome.status).toBe(502);
    expect(store.documents.some((d) => d.status === "failed")).toBe(true);
    expect(store.events.some((e) => e.event_name === "api_error")).toBe(true);
  });

  it("rejects malformed AI JSON with invalid_ai_output (contract guard)", async () => {
    const store = new FakeStore();
    const fetchImpl: typeof fetch = async () =>
      jsonResponse(200, { candidates: [{ content: { parts: [{ text: "definitely not json" }] } }] });
    const outcome = await runGeneration(baseReq, { store, aiOptions: { fetchImpl, cache: new Map() } });
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) expect(outcome.code).toBe("invalid_ai_output");
  });

  it("enforces the validator contract (contract_violation)", async () => {
    const store = new FakeStore();
    const fetchImpl: typeof fetch = async () =>
      jsonResponse(200, { candidates: [{ content: { parts: [{ text: '{"other":1}' }] } }] });
    const outcome = await runGeneration(
      { ...baseReq, validate: (p) => (typeof p.cover_letter_markdown === "string" ? null : "missing letter") },
      { store, aiOptions: { fetchImpl, cache: new Map() } },
    );
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) expect(outcome.code).toBe("contract_violation");
  });
});
