/**
 * Auth helper: resolve the authenticated user from the caller's JWT.
 * Edge Functions verify the Supabase Auth JWT here and rely on RLS for
 * row-level ownership downstream (master plan section 3).
 */
import type { SupabaseClient } from "@supabase/supabase-js";

export interface AuthUser {
  id: string;
  email?: string;
  user_metadata?: Record<string, unknown>;
  app_metadata?: Record<string, unknown>;
}

/** Returns the authenticated user or null when the JWT is missing/invalid. */
export async function getAuthUser(client: SupabaseClient): Promise<AuthUser | null> {
  const { data, error } = await client.auth.getUser();
  if (error || !data?.user) return null;
  return {
    id: data.user.id,
    email: data.user.email,
    user_metadata: data.user.user_metadata,
    app_metadata: data.user.app_metadata,
  };
}

