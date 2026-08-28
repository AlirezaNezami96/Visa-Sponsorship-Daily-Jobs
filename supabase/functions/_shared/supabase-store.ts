/**
 * Adapter: wraps a supabase-js client as the GenerationStore interface used by
 * the generation pipeline. The client SHOULD be the user client (carries the
 * caller's JWT) so RLS applies to document/event inserts, the usage-limit
 * read + RPC run as auth.uid(), and idempotency lookups only see the caller's
 * own documents.
 */
import type { SupabaseClient } from "@supabase/supabase-js";
import type { AnalyticsEventInput, CompletedDocument, GeneratedDocumentInput, GenerationStore } from "./generation.ts";
import { checkUsage, consumeUsage, type LimitDecision, type ProfileRow, type UsageField } from "./usage-limits.ts";
import { getEnv } from "./env.ts";

interface RpcClient {
  rpc(fn: string, args: Record<string, unknown>): PromiseLike<{ data: unknown; error: { message: string } | null }>;
}

export const DOCUMENTS_BUCKET = "users";
export const SIGNED_URL_EXPIRY_SECONDS = 3600;

export function createGenerationStore(client: SupabaseClient): GenerationStore {
  return {
    checkUsage(field: UsageField, profile: ProfileRow | null): Promise<LimitDecision> | LimitDecision {
      // Read-only gate (RLS owner_read_usage policy scopes to auth.uid()).
      return Promise.resolve(
        checkUsage(client as unknown as Parameters<typeof checkUsage>[0], field, profile),
      );
    },

    consumeUsage(field: UsageField, profile: ProfileRow | null): Promise<LimitDecision> | LimitDecision {
      // Atomic increment via SECURITY DEFINER RPC keyed on auth.uid(); the
      // user client's JWT supplies the identity.
      return Promise.resolve(consumeUsage(client as unknown as RpcClient, field, profile));
    },

    async findCompletedDocument(key: string, userId: string): Promise<CompletedDocument | null> {
      const { data, error } = await client
        .from("generated_documents")
        .select("id, output_json, file_path, ai_provider, ai_model")
        .eq("idempotency_key", key)
        .eq("user_id", userId)
        .eq("status", "completed")
        .order("created_at", { ascending: false })
        .limit(1)
        .maybeSingle();
      if (error || !data) return null;
      const row = data as Record<string, unknown>;
      return {
        id: String(row.id),
        output_json: row.output_json ?? null,
        file_path: (row.file_path as string | null) ?? null,
        ai_provider: (row.ai_provider as string | null) ?? null,
        ai_model: (row.ai_model as string | null) ?? null,
      };
    },

    async insertDocument(doc: GeneratedDocumentInput): Promise<string | null> {
      const { data, error } = await client.from("generated_documents").insert(doc).select("id").single();
      if (error || !data) return null;
      const row = Array.isArray(data) ? data[0] : data;
      return (row as { id?: string })?.id ?? null;
    },

    async insertEvent(event: AnalyticsEventInput): Promise<void> {
      const { error } = await client.from("analytics_events").insert(event);
      if (error) throw new Error(error.message);
    },
  };
}

/**
 * Ask the Python engine to assemble the deterministic PDF for a completed
 * document (GAP 2), upload it to Storage, and record file_path. Returns the
 * storage path, or null when the engine is not configured / fails — the JSON
 * output remains fully usable without a PDF (graceful degradation).
 */
export async function renderDocumentViaEngine(args: {
  document_id: string;
  user_id: string;
  job_id: string | null;
  document_type: string;
  format_type: string | null;
  output_json: unknown;
  profile: Record<string, unknown>;
  job: Record<string, unknown>;
}): Promise<{ storage_path: string } | null> {
  const engineUrl = (getEnv("ENGINE_URL") ?? "").replace(/\/$/, "");
  const internalKey = getEnv("INTERNAL_API_KEY") ?? "";
  if (!engineUrl || !internalKey) return null;

  try {
    const resp = await fetch(`${engineUrl}/internal/documents/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-internal-key": internalKey },
      body: JSON.stringify(args),
    });
    if (!resp.ok) return null;
    const body = (await resp.json()) as { storage_path?: string };
    return body.storage_path ? { storage_path: body.storage_path } : null;
  } catch {
    return null;
  }
}

/** Mint a 1-hour signed preview/download URL for a stored document. */
export async function createDocumentSignedUrl(
  client: SupabaseClient,
  storagePath: string | null | undefined,
): Promise<string | null> {
  if (!storagePath) return null;
  try {
    const { data, error } = await client.storage
      .from(DOCUMENTS_BUCKET)
      .createSignedUrl(storagePath, SIGNED_URL_EXPIRY_SECONDS);
    if (error || !data?.signedUrl) return null;
    return data.signedUrl;
  } catch {
    return null;
  }
}
