import type { SupabaseClient } from "@supabase/supabase-js";

export function makeIdemKey(
  userId: string,
  jobId: string,
  docType: string,
  formatType: string,
  profileUpdatedAt: string,
  promptVersion: string,
): string {
  return [userId, jobId, docType, formatType, profileUpdatedAt, promptVersion].join(":");
}

export async function loadCached(supabase: SupabaseClient, key: string) {
  const { data } = await supabase
    .from("generated_documents")
    .select("*")
    .eq("idempotency_key", key)
    .eq("status", "completed")
    .maybeSingle();
  return data ?? null;
}
