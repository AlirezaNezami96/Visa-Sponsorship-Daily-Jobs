/**
 * Tests for OAuth sync metadata extraction and provider parsing logic.
 */
import { describe, it, expect } from "vitest";

function extractAvatarUrl(meta: Record<string, unknown> | null | undefined): string | null {
  if (!meta) return null;
  const candidates = [meta.picture, meta.avatar_url, meta.photo_url];
  for (const c of candidates) {
    if (typeof c === "string" && c.startsWith("http")) return c;
  }
  return null;
}

function extractProvider(appMeta: Record<string, unknown> | null | undefined): string | null {
  if (!appMeta) return null;
  return typeof appMeta.provider === "string" ? appMeta.provider : null;
}

function extractProviderId(
  meta: Record<string, unknown> | null | undefined,
  user: { id: string },
): string {
  if (meta?.sub && typeof meta.sub === "string") return meta.sub;
  if (meta?.provider_id && typeof meta.provider_id === "string") return meta.provider_id;
  return user.id;
}

describe("oauth-sync metadata extractors", () => {
  it("extracts Google profile picture from user_metadata.picture", () => {
    const meta = {
      picture: "https://lh3.googleusercontent.com/a/test-avatar",
      full_name: "Google User",
    };
    expect(extractAvatarUrl(meta)).toBe("https://lh3.googleusercontent.com/a/test-avatar");
  });

  it("extracts GitHub avatar from user_metadata.avatar_url", () => {
    const meta = {
      avatar_url: "https://avatars.githubusercontent.com/u/123456",
      user_name: "octocat",
    };
    expect(extractAvatarUrl(meta)).toBe("https://avatars.githubusercontent.com/u/123456");
  });

  it("returns null if no valid image URL is present", () => {
    expect(extractAvatarUrl(null)).toBeNull();
    expect(extractAvatarUrl({})).toBeNull();
    expect(extractAvatarUrl({ picture: "not-a-url" })).toBeNull();
  });

  it("extracts provider name from app_metadata", () => {
    expect(extractProvider({ provider: "google", providers: ["google"] })).toBe("google");
    expect(extractProvider({ provider: "github", providers: ["github"] })).toBe("github");
    expect(extractProvider(null)).toBeNull();
    expect(extractProvider({})).toBeNull();
  });

  it("extracts provider ID with sub, provider_id, or user.id fallback", () => {
    const user = { id: "supabase-user-uuid" };
    expect(extractProviderId({ sub: "google-sub-999" }, user)).toBe("google-sub-999");
    expect(extractProviderId({ provider_id: "github-12345" }, user)).toBe("github-12345");
    expect(extractProviderId({}, user)).toBe("supabase-user-uuid");
    expect(extractProviderId(null, user)).toBe("supabase-user-uuid");
  });
});
