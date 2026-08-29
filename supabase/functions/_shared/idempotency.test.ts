import { describe, it, expect, vi } from "vitest";
import { makeIdemKey, loadCached } from "./idempotency.ts";
import type { SupabaseClient } from "@supabase/supabase-js";

describe("idempotency helpers", () => {
  it("builds consistent colon-delimited idempotency keys", () => {
    const key = makeIdemKey("u-123", "j-456", "resume", "professional", "2026-08-28T00:00:00Z", "2026-08-28.1");
    expect(key).toBe("u-123:j-456:resume:professional:2026-08-28T00:00:00Z:2026-08-28.1");
  });

  it("loadCached queries generated_documents for completed rows", async () => {
    const maybeSingleMock = vi.fn().mockResolvedValue({
      data: {
        id: "doc-1",
        idempotency_key: "u-123:j-456:resume:professional:2026-08-28T00:00:00Z:2026-08-28.1",
        status: "completed",
        output_json: { tailored_resume_markdown: "# Summary" },
      },
      error: null,
    });

    const queryMock = {
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      maybeSingle: maybeSingleMock,
    };

    const supabaseMock = {
      from: vi.fn().mockReturnValue(queryMock),
    } as unknown as SupabaseClient;

    const result = await loadCached(supabaseMock, "u-123:j-456:resume:professional:2026-08-28T00:00:00Z:2026-08-28.1");

    expect(supabaseMock.from).toHaveBeenCalledWith("generated_documents");
    expect(queryMock.eq).toHaveBeenCalledWith("idempotency_key", "u-123:j-456:resume:professional:2026-08-28T00:00:00Z:2026-08-28.1");
    expect(queryMock.eq).toHaveBeenCalledWith("status", "completed");
    expect(result).not.toBeNull();
    expect(result?.id).toBe("doc-1");
  });

  it("loadCached returns null on missing or failed document", async () => {
    const queryMock = {
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
    };

    const supabaseMock = {
      from: vi.fn().mockReturnValue(queryMock),
    } as unknown as SupabaseClient;

    const result = await loadCached(supabaseMock, "missing-key");
    expect(result).toBeNull();
  });
});
