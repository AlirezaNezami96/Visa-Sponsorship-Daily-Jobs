/**
 * Shared on-demand document generation pipeline (Edge Functions).
 *
 * Order of operations (GAP 3 hard rules enforced here):
 *   1. idempotency lookup  -> completed document for the exact key is returned
 *      with no quota charge and no AI call
 *   2. usage-limit CHECK (read-only) -> 402 BEFORE any provider call
 *   3. AI waterfall with repair: on validation failure one repair retry to the
 *      SAME provider with the violation list appended; still failing -> advance
 *      Gemini -> Groq -> OpenRouter. Fallback + repair events are recorded.
 *   4. atomic quota INCREMENT only after validation passes (charge-before-push)
 *      — failed or idempotent generations are never charged
 *   5. persist completed generated_documents row (with idempotency key) + analytics
 *
 * Persistence is hidden behind the minimal `GenerationStore` interface so the
 * pipeline is fully unit-testable without supabase-js; each handler adapts the
 * real client, tests inject fakes.
 */
import type { AIResult, ProviderAttempt } from "./ai-client.ts";
import { aiTryProvider, parseAIJson, PROVIDER_CHAIN, type AIClientOptions } from "./ai-client.ts";
import {
  effectivePlan,
  type LimitDecision,
  type ProfileRow,
  type UsageField,
  USAGE_FIELDS,
} from "./usage-limits.ts";
import { logSystemEvent } from "./system-logger.ts";

export interface GeneratedDocumentInput {
  user_id: string;
  job_id: string | null;
  document_type: string;
  status: "pending" | "generating" | "completed" | "failed";
  ai_provider?: string | null;
  ai_model?: string | null;
  prompt_version?: string | null;
  format_type?: string | null;
  output_json?: unknown;
  input_profile_snapshot?: unknown;
  idempotency_key?: string | null;
  profile_updated_at?: string | null;
  error_message?: string | null;
}

export interface AnalyticsEventInput {
  event_name: string;
  user_id?: string | null;
  job_id?: string | null;
  metadata?: Record<string, unknown>;
}

export interface CompletedDocument {
  id: string;
  output_json?: unknown;
  file_path?: string | null;
  ai_provider?: string | null;
  ai_model?: string | null;
}

/** Minimal persistence surface; implemented by a supabase adapter, faked in tests. */
export interface GenerationStore {
  /** Read-only limit check — MUST NOT mutate counters. */
  checkUsage(field: UsageField, profile: ProfileRow | null): Promise<LimitDecision> | LimitDecision;
  /** Atomically consume one usage unit (RPC); only called after validation. */
  consumeUsage(field: UsageField, profile: ProfileRow | null): Promise<LimitDecision> | LimitDecision;
  /** Idempotency lookup for completed documents of an exact key. */
  findCompletedDocument(key: string, userId: string): Promise<CompletedDocument | null>;
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
  /** Idempotency inputs (GAP 3.3). Omit profileUpdatedAt to skip idempotency. */
  formatType?: string | null;
  profileUpdatedAt?: string | null;
  buildPrompt: () => string;
  /** Structural + grounding validation. Returns violation text or null. */
  validate: (parsed: Record<string, unknown>) => string | null;
  postProcess?: (parsed: Record<string, unknown>) => Record<string, unknown>;
  analyticsEvent: string;
  /** Grounds the idempotency key + snapshot persistence. */
  inputProfileSnapshot?: Record<string, unknown> | null;
}

export interface GenerationDeps {
  store: GenerationStore;
  aiOptions?: AIClientOptions;
}

export type GenerationOutcome =
  | { ok: true; status: number; body: Record<string, unknown> }
  | { ok: false; status: number; code: string; message: string };

export function computeIdempotencyKey(parts: {
  userId: string;
  jobId: string | null;
  documentType: string;
  formatType?: string | null;
  profileUpdatedAt?: string | null;
  promptVersion: string;
}): string {
  return [
    parts.userId,
    parts.jobId ?? "-",
    parts.documentType,
    parts.formatType ?? "-",
    parts.profileUpdatedAt ?? "-",
    parts.promptVersion,
  ].join("|");
}

function buildRepairPrompt(basePrompt: string, violations: string): string {
  return `${basePrompt}

The previous response was REJECTED for these exact violations:
- ${violations}
Fix ONLY these violations. Keep every grounded fact unchanged. Return the complete corrected JSON again, no markdown fences.`;
}

async function observeFallback(store: GenerationStore, req: GenerationRequest, fromProvider: string, reason: string): Promise<void> {
  try {
    await store.insertEvent({
      event_name: "ai_fallback_triggered",
      user_id: req.userId,
      metadata: { from_provider: fromProvider, reason, document_type: req.documentType },
    });
    await logSystemEvent({
      level: "warn",
      source: "ai-generation-waterfall",
      message: `AI provider fallback: ${fromProvider} failed (${reason.slice(0, 100)}). Advancing waterfall for ${req.documentType}.`,
      userId: req.userId,
      details: { from_provider: fromProvider, reason, document_type: req.documentType, job_id: req.jobId },
    });
  } catch { /* analytics must never break generation */ }
}

export async function runGeneration(req: GenerationRequest, deps: GenerationDeps): Promise<GenerationOutcome> {
  const { store } = deps;

  if (!USAGE_FIELDS.includes(req.usageField)) {
    return { ok: false, status: 400, code: "bad_request", message: `unknown usage field ${req.usageField}` };
  }

  // 0. Idempotency: an already-completed document for this exact key is
  //    returned as-is — no quota charge, no AI call (GAP 3.3).
  const idempotencyKey = computeIdempotencyKey({
    userId: req.userId,
    jobId: req.jobId,
    documentType: req.documentType,
    formatType: req.formatType,
    profileUpdatedAt: req.profileUpdatedAt,
    promptVersion: req.promptVersion,
  });
  try {
    const existing = await store.findCompletedDocument(idempotencyKey, req.userId);
    if (existing) {
      const output = (existing.output_json ?? {}) as Record<string, unknown>;
      return {
        ok: true,
        status: 200,
        body: {
          document_id: existing.id,
          ai_provider: existing.ai_provider ?? null,
          ai_model: existing.ai_model ?? null,
          cached: true,
          from_cache: true,
          idempotent: true,
          file_path: existing.file_path ?? null,
          output: { ...output, prompt_version: req.promptVersion },
        },
      };
    }
  } catch { /* idempotency is a fast path; fall through to generation */ }

  // 1. Usage-limit CHECK (read-only) — MUST precede any provider interaction.
  let decision: LimitDecision;
  try {
    decision = await store.checkUsage(req.usageField, req.profile);
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

  // 2. AI waterfall with per-provider repair retry (GAP 3.2).
  const basePrompt = req.buildPrompt();
  let chosen: AIResult | null = null;
  let chosenParsed: Record<string, unknown> | null = null;
  let lastViolation = "";
  let previousProvider: string | null = null;
  let previousReason = "";

  for (const provider of PROVIDER_CHAIN) {
    if (previousProvider) {
      await observeFallback(store, req, previousProvider, previousReason);
      await deps.aiOptions?.onFallback?.(previousProvider, previousReason);
    }

    const attempt: ProviderAttempt = await aiTryProvider(provider, basePrompt, {
      json: true,
      fetchImpl: deps.aiOptions?.fetchImpl,
    });
    if (!attempt.result) {
      previousProvider = provider;
      previousReason = attempt.reason;
      continue;
    }

    let parsed = parseAIJson<Record<string, unknown>>(attempt.result.text);
    let violation = parsed ? req.validate(parsed) ?? "" : "AI response was not valid JSON";

    if (violation) {
      // One repair retry to the SAME provider with the violation list.
      const repairAttempt = await aiTryProvider(provider, buildRepairPrompt(basePrompt, violation), {
        json: true,
        fetchImpl: deps.aiOptions?.fetchImpl,
        cache: new Map(), // repair prompt is never served from cache
      });
      const repaired = repairAttempt.result ? parseAIJson<Record<string, unknown>>(repairAttempt.result.text) : null;
      const repairedViolation = repaired ? (req.validate(repaired) ?? "") : "repair response was not valid JSON";
      try {
        await store.insertEvent({
          event_name: "ai_validation_repair",
          user_id: req.userId,
          metadata: {
            provider,
            document_type: req.documentType,
            violations: violation.slice(0, 500),
            resolved: !repairedViolation,
          },
        });
      } catch { /* non-fatal */ }

      if (!repairedViolation && repaired) {
        chosen = repairAttempt.result;
        chosenParsed = repaired;
        break;
      }
      parsed = repaired ?? parsed;
      violation = repairedViolation;
    }

    if (!violation && parsed) {
      chosen = attempt.result;
      chosenParsed = parsed;
      break;
    }

    // Validation still failing after repair -> advance the waterfall.
    previousProvider = provider;
    previousReason = `validation_failed: ${violation.slice(0, 120)}`;
    lastViolation = violation;
  }

  if (!chosen || !chosenParsed) {
    // All providers exhausted (failed or failed validation): structured 500
    // with a friendly message + ai_error analytics (GAP 3.2).
    const message = lastViolation
      ? `We couldn't generate a verified document right now: ${lastViolation}. Please try again in a few minutes.`
      : "All AI providers are temporarily unavailable. Please try again in a few minutes.";
    try {
      await store.insertDocument({
        user_id: req.userId,
        job_id: req.jobId,
        document_type: req.documentType,
        status: "failed",
        prompt_version: req.promptVersion,
        format_type: req.formatType ?? null,
        idempotency_key: idempotencyKey,
        error_message: message.slice(0, 1000),
      });
      await store.insertEvent({
        event_name: "ai_error",
        user_id: req.userId,
        job_id: req.jobId,
        metadata: { where: "generation", document_type: req.documentType, message: message.slice(0, 300) },
      });
      await logSystemEvent({
        level: "error",
        source: "ai-generation-waterfall",
        message: `All AI providers failed for ${req.documentType}: ${message.slice(0, 150)}`,
        userId: req.userId,
        details: { lastViolation, documentType: req.documentType, jobId: req.jobId },
      });
    } catch { /* best-effort bookkeeping */ }
    return { ok: false, status: 500, code: "ai_generation_failed", message };
  }

  // 3. Atomic quota increment — only after validation passed (GAP 3.3).
  //    Charge-before-push: the counter is reserved before the document row is
  //    persisted; a concurrent race that now exceeds the cap returns 402 and
  //    persists nothing (failed/excess generations are never charged).
  let consumed: LimitDecision;
  try {
    consumed = await store.consumeUsage(req.usageField, req.profile);
  } catch (err) {
    return { ok: false, status: 500, code: "usage_consume_failed", message: String(err) };
  }
  if (!consumed.allowed) {
    return {
      ok: false,
      status: 402,
      code: "usage_limit_reached",
      message: `Daily ${req.usageField.replace(/_/g, " ")} limit reached (${consumed.count}/${consumed.limit}). Resets at midnight UTC.`,
    };
  }

  // 4. Persist completed document (with idempotency key) + analytics.
  const output = { ...chosenParsed, prompt_version: req.promptVersion };
  const finalOutput = req.postProcess ? req.postProcess(output) : output;

  let documentId: string | null = null;
  try {
    documentId = await store.insertDocument({
      user_id: req.userId,
      job_id: req.jobId,
      document_type: req.documentType,
      status: "completed",
      ai_provider: chosen.provider,
      ai_model: chosen.model,
      prompt_version: req.promptVersion,
      format_type: req.formatType ?? null,
      output_json: finalOutput,
      input_profile_snapshot: req.inputProfileSnapshot ?? null,
      idempotency_key: idempotencyKey,
      profile_updated_at: req.profileUpdatedAt ?? null,
    });
  } catch { /* document row is bookkeeping; response still returns content */ }

  try {
    await store.insertEvent({
      event_name: req.analyticsEvent,
      user_id: req.userId,
      job_id: req.jobId,
      metadata: { provider: chosen.provider, model: chosen.model, cached: chosen.cached, latency_ms: chosen.latency_ms },
    });
  } catch { /* non-fatal */ }

  return {
    ok: true,
    status: 200,
    body: {
      document_id: documentId,
      ai_provider: chosen.provider,
      ai_model: chosen.model,
      cached: chosen.cached,
      output: finalOutput,
    },
  };
}
