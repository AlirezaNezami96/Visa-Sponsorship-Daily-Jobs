/**
 * Supabase client factories for Edge Functions.
 *
 * - userClient: carries the caller's JWT; all user-owned reads/writes and the
 *   usage-limit RPC go through it so RLS applies natively.
 * - adminClient: service-role; used only for service-owned reads/writes
 *   (analytics bookkeeping, job contact lookups). NEVER returned to the FE.
 */
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { getEnv } from "./env.ts";

function requireEnv(name: string): string {
  const value = getEnv(name);
  if (!value) throw new Error(`missing env: ${name}`);
  return value;
}

export function createUserClient(req: Request): SupabaseClient {
  const authHeader = req.headers.get("Authorization") ?? "";
  return createClient(requireEnv("SUPABASE_URL"), requireEnv("SUPABASE_ANON_KEY"), {
    global: { headers: { Authorization: authHeader } },
  });
}

export function createAdminClient(): SupabaseClient {
  return createClient(requireEnv("SUPABASE_URL"), requireEnv("SUPABASE_SERVICE_ROLE_KEY"), {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

export function hasAuthHeader(req: Request): boolean {
  const header = req.headers.get("Authorization") ?? "";
  return header.toLowerCase().startsWith("bearer ") && header.length > "bearer ".length;
}
