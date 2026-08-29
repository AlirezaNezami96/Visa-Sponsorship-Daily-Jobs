/**
 * Tests for generate-tailored-resume idempotency & cache behavior (GAP C).
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { runGeneration, type GenerationStore, type GeneratedDocumentInput, type AnalyticsEventInput, type CompletedDocument } from "./_shared/generation.ts";
import type { LimitDecision, ProfileRow, UsageField } from "./_shared/usage-limits.ts";
import { setEnvForTest, clearEnvOverrides } from "./_shared/env.ts";
import { PROMPT_VERSIONS } from "./_shared/prompts.ts";

class MemoryStore implements GenerationStore {
  usageCount = 0;
  completedDocs = new Map<string, CompletedDocument>();
  documents: GeneratedDocumentInput[] = [];
  events: AnalyticsEventInput[] = [];
  checkCalls = 0;
  consumeCalls = 0;

  checkUsage(_field: UsageField, _profile: ProfileRow | null): LimitDecision {
    this.checkCalls += 1;
    return { allowed: this.usageCount < 10, count: this.usageCount, limit: 10, plan: "free" };
  }

  consumeUsage(_field: UsageField, _profile: ProfileRow | null): LimitDecision {
    this.consumeCalls += 1;
    this.usageCount += 1;
    return { allowed: true, count: this.usageCount, limit: 10, plan: "free" };
  }

  async findCompletedDocument(key: string, _userId: string): Promise<CompletedDocument | null> {
    return this.completedDocs.get(key) ?? null;
  }

  async insertDocument(doc: GeneratedDocumentInput): Promise<string | null> {
    const id = `doc-${this.documents.length + 1}`;
    this.documents.push(doc);
    if (doc.status === "completed" && doc.idempotency_key) {
      this.completedDocs.set(doc.idempotency_key, {
        id,
        output_json: doc.output_json,
        file_path: `users/${doc.user_id}/jobs/${doc.job_id}/resume/${id}.pdf`,
        ai_provider: doc.ai_provider,
        ai_model: doc.ai_model,
      });
    }
    return id;
  }

  async insertEvent(event: AnalyticsEventInput): Promise<void> {
    this.events.push(event);
  }
}

const mockProfile: ProfileRow = {
  id: "user-123",
  subscription_plan: "free",
};

const reqInput = {
  userId: "user-123",
  profile: mockProfile,
  usageField: "resume_generations" as const,
  documentType: "resume" as const,
  jobId: "job-456",
  promptVersion: PROMPT_VERSIONS.tailoredResume,
  formatType: "professional",
  profileUpdatedAt: "2026-08-28T12:00:00Z",
  buildPrompt: () => "Tailor resume prompt",
  validate: () => null,
  analyticsEvent: "resume_generated",
};

function geminiOk(text: string): Response {
  return new Response(
    JSON.stringify({
      candidates: [{ content: { parts: [{ text }] } }],
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

describe("generate-tailored-resume idempotency (GAP C)", () => {
  beforeEach(() => {
    clearEnvOverrides();
    setEnvForTest("GEMINI_API_KEY", "test-gemini-key");
  });

  it("first call invokes provider; second identical call returns cached result without invoking provider", async () => {
    const store = new MemoryStore();
    let providerCalls = 0;

    const fetchMock = vi.fn().mockImplementation(async () => {
      providerCalls += 1;
      return geminiOk(
        JSON.stringify({
          tailored_resume_markdown: "# Senior Android Developer\n\n- Engineered high throughput services",
          tailoring_notes: ["Emphasized Kotlin and performance"],
        }),
      );
    });

    // 1. First Call
    const outcome1 = await runGeneration(reqInput, {
      store,
      aiOptions: { fetchImpl: fetchMock as unknown as typeof fetch, cache: new Map() },
    });

    expect(outcome1.ok).toBe(true);
    expect(providerCalls).toBe(1);
    expect(store.consumeCalls).toBe(1);
    expect(store.usageCount).toBe(1);
    if (outcome1.ok) {
      expect(outcome1.body.from_cache).toBeUndefined();
      expect(outcome1.body.document_id).toBe("doc-1");
    }

    // 2. Second Call with identical inputs
    const outcome2 = await runGeneration(reqInput, {
      store,
      aiOptions: { fetchImpl: fetchMock as unknown as typeof fetch, cache: new Map() },
    });

    expect(outcome2.ok).toBe(true);
    // Provider was NOT called a second time
    expect(providerCalls).toBe(1);
    // Quota was NOT incremented again
    expect(store.consumeCalls).toBe(1);
    expect(store.usageCount).toBe(1);

    if (outcome2.ok) {
      expect(outcome2.body.from_cache).toBe(true);
      expect(outcome2.body.cached).toBe(true);
      expect(outcome2.body.idempotent).toBe(true);
      expect(outcome2.body.document_id).toBe("doc-1");
    }
  });
});
