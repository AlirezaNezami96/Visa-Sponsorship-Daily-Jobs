/**
 * Adapter: wraps a supabase-js client as the GenerationStore interface used by
 * the generation pipeline. The client SHOULD be the user client (carries the
 * caller's JWT) so RLS applies to document/event inserts and the usage-limit
 * RPC runs as auth.uid().
 */
import type { SupabaseClient } from "@supabase/supabase-js";
import type { AnalyticsEventInput, GeneratedDocumentInput, GenerationStore } from "./generation.ts";
import { consumeUsage, type LimitDecision, type ProfileRow, type UsageField } from "./usage-limits.ts";

interface RpcClient {
  rpc(fn: string, args: Record<string, unknown>): PromiseLike<{ data: unknown; error: { message: string } | null }>;
}

export function createGenerationStore(client: SupabaseClient): GenerationStore {
  return {
    consumeUsage(field: UsageField, profile: ProfileRow | null): Promise<LimitDecision> | LimitDecision {
      // The RPC is SECURITY DEFINER keyed on auth.uid(); the user client's JWT
      // supplies that identity. RLS prevents cross-user reads elsewhere.
      return Promise.resolve(consumeUsage(client as unknown as RpcClient, field, profile));
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
