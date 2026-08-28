/**
 * Shared on-demand document generation pipeline (Edge Functions).
 *
 * Order of operations is a critical-path contract (master plan section 10.3):
 *   1. usage-limit check/consume  -> 402 BEFORE any provider call
 *   2. AI waterfall with fallback observation (ai_fallback_triggered events)
 *   3. persist generated_documents row + analytics
 *
 * Persistence is hidden behind the minimal `GenerationStore` interface so the
 * pipeline is fully unit-testable without supabase-js; each handler adapts the
 * real client, tests inject fakes.
 */
import type { AIResult } from "./ai-client.ts";
import { aiComplete, parseAIJson, type AIClientOptions } from "./ai-client.ts";
import {
  effectivePlan,
  type LimitDecision,
  type ProfileRow,
  type UsageField,
  USAGE_FIELDS,
} from "./usage-limits.ts";

export interface GeneratedDocumentInput {
  user_id: string;
  job_id: string | null;
  document_type: string;
  status: "pending" | "generating" | "completed" | "failed";
  ai_provider?: string | null;
  ai_model?: string | null;
  prompt_version?: string | null;
  output_json?: unknown;
  error_message?: string | null;
}

export interface AnalyticsEventInput {
  event_name: string;
  user_id?: string | null;
  job_id?: string | null;
  metadata?: Record<string, unknown>;
}

/** Minimal persistence surface; implemented by a supabase adapter, faked in tests. */
export interface GenerationStore {
  /** Atomically consume one usage unit. Throws only on infrastructure failure. */
  consumeUsage(field: UsageField, profile: ProfileRow | null): Promise<LimitDecision> | LimitDecision;
  insertDocument(doc: GeneratedDocumentInput): Promise<string | null>;
  insertEvent(event: AnalyticsEventInput): Promise<void>;
}

export interface GenerationRequest {
  userId: string;
  profile: ProfileRow | null;
  usageField: UsageField;
  documentType: "resume" | "cover_letter" | "outreach_email" | "outreach_linkedin";
  jobId: string | null;
  promptVersion: string;
  buildPrompt: () => string;
  validate: (parsed: Record<string, unknown>) => string | null;
  postProcess?: (parsed: Record<string, unknown>) => Record<string, unknown>;
  analyticsEvent: string;
}

export interface GenerationDeps {
  store: GenerationStore;
  aiOptions?: AIClientOptions;
}

export type GenerationOutcome =
  | { ok: true; status: number; body: Record<string, unknown> }
  | { ok: false; status: number; code: string; message: string };

/**
 * Run the full gate -> generate -> persist pipeline.
 * Expected failures return structured outcomes; only unexpected ones throw.
 */
export async function runGeneration(req: GenerationRequest, deps: GenerationDeps): Promise<GenerationOutcome> {
  const { store } = deps;

  if (!USAGE_FIELDS.includes(req.usageField)) {
    return { ok: false, status: 400, code: "bad_request", message: `unknown usage field ${req.usageField}` };
  }

  // 1. Usage-limit gate — MUST precede any provider interaction.
  let decision: LimitDecision;
  try {
    decision = await store.consumeUsage(req.usageField, req.profile);
  } catch (err) {
    return { ok: false, status: 500, code: "usage_check_failed", message: String(err) };
  }
  if (!decision.allowed) {
    return {
      ok: false,
      status: 402,
      code: "usage_limit_reached",
      message: `Daily ${req.usageField.replace(/_/g, " ")} limit reached (${decision.count}/${decision.limit} on ${effectivePlan(req.profile)} plan). Resets at midnight UTC.`,
    };
  }

  // 2. AI waterfall with fallback observation.
  let ai: AIResult;
  try {
    ai = await aiComplete(req.buildPrompt(), {
      json: true,
      ...deps.aiOptions,
      onFallback: async (fromProvider, reason) => {
        // Analytics must never break generation.
        try {
          await store.insertEvent({
            event_name: "ai_fallback_triggered",
            user_id: req.userId,
            metadata: { from_provider: fromProvider, reason, document_type: req.documentType },
          });
        } catch { /* ignore */ }
        await deps.aiOptions?.onFallback?.(fromProvider, reason);
      },
    });
  } catch (err) {
    // Structured error only when ALL providers fail (master plan 6.1).
    const message = err instanceof Error ? err.message : String(err);
    try {
      await store.insertDocument({
        user_id: req.userId,
        job_id: req.jobId,
        document_type: req.documentType,
        status: "failed",
        prompt_version: req.promptVersion,
        error_message: message.slice(0, 1000),
      });
      await store.insertEvent({
        event_name: "api_error",
        user_id: req.userId,
        job_id: req.jobId,
        metadata: { where: "ai_complete", document_type: req.documentType, message: message.slice(0, 300) },
      });
    } catch { /* best-effort */ }
    return { ok: false, status: 502, code: "ai_providers_exhausted", message };
  }

  const parsed = parseAIJson<Record<string, unknown>>(ai.text);
  if (!parsed) {
    try {
      await store.insertDocument({
        user_id: req.userId,
        job_id: req.jobId,
        document_type: req.documentType,
        status: "failed",
        ai_provider: ai.provider,
        ai_model: ai.model,
        prompt_version: req.promptVersion,
        error_message: "unparseable_ai_json",
      });
    } catch { /* best-effort */ }
    return { ok: false, status: 502, code: "invalid_ai_output", message: "Model returned malformed JSON." };
  }

  const validationError = req.validate(parsed);
  if (validationError) {
    return { ok: false, status: 502, code: "contract_violation", message: validationError };
  }

  // 3. Persist completed document + analytics.
  const output = { ...parsed, prompt_version: req.promptVersion };
  const finalOutput = req.postProcess ? req.postProcess(output) : output;

  let documentId: string | null = null;
  try {
    documentId = await store.insertDocument({
      user_id: req.userId,
      job_id: req.jobId,
      document_type: req.documentType,
      status: "completed",
      ai_provider: ai.provider,
      ai_model: ai.model,
      prompt_version: req.promptVersion,
      output_json: finalOutput,
    });
  } catch { /* document row is bookkeeping; response still returns content */ }

  try {
    await store.insertEvent({
      event_name: req.analyticsEvent,
      user_id: req.userId,
      job_id: req.jobId,
      metadata: { provider: ai.provider, model: ai.model, cached: ai.cached, latency_ms: ai.latency_ms },
    });
  } catch { /* non-fatal */ }

  return {
    ok: true,
    status: 200,
    body: {
      document_id: documentId,
      ai_provider: ai.provider,
      ai_model: ai.model,
      cached: ai.cached,
      output: finalOutput,
    },
  };
}
