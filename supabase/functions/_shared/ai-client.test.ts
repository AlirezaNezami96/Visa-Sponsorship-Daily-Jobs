/**
 * Critical-path tests for the AI provider waterfall (master plan section 10.2):
 *   - primary 429 -> advance chain, observe fallback, secondary succeeds
 *   - all providers fail -> structured AllProvidersFailedError (never raw throw)
 *   - deterministic cache prevents repeat provider calls
 */
import { describe, it, expect, beforeEach } from "vitest";
import { aiComplete, parseAIJson, AllProvidersFailedError } from "./ai-client.ts";
import { setEnvForTest, clearEnvOverrides } from "./env.ts";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function geminiOk(text: string): Response {
  return jsonResponse(200, { candidates: [{ content: { parts: [{ text }] } }] });
}
function groqOk(text: string): Response {
  return jsonResponse(200, { choices: [{ message: { content: text } }] });
}
function openRouterOk(text: string): Response {
  return jsonResponse(200, { choices: [{ message: { content: text } }] });
}

beforeEach(() => {
  clearEnvOverrides();
});

describe("aiComplete provider waterfall", () => {
  it("advances past a 429 primary and succeeds on the secondary, observing the fallback", async () => {
    setEnvForTest("GEMINI_API_KEY", "g-key");
    setEnvForTest("GROQ_API_KEY", "groq-key");

    const calls: string[] = [];
    const fallbacks: Array<{ from: string; reason: string }> = [];
    const fetchImpl: typeof fetch = async (input) => {
      const url = String(input);
      calls.push(url);
      if (url.includes("generativelanguage.googleapis.com")) {
        return jsonResponse(429, { error: "rate limited" });
      }
      if (url.includes("api.groq.com")) {
        return groqOk('{"ok":true}');
      }
      return jsonResponse(500, {});
    };

    const cache = new Map();
    const result = await aiComplete("hello", {
      json: true,
      fetchImpl,
      cache,
      onFallback: (from, reason) => {
        fallbacks.push({ from, reason });
      },
    });

    expect(result.provider).toBe("groq");
    expect(result.text).toBe('{"ok":true}');
    expect(fallbacks).toEqual([{ from: "gemini", reason: "http_429" }]);
    // Gemini attempted once, then Groq — chain advanced exactly once.
    expect(calls.filter((c) => c.includes("generativelanguage")).length).toBe(1);
    expect(calls.filter((c) => c.includes("groq")).length).toBe(1);
  });

  it("throws a structured AllProvidersFailedError when every provider fails", async () => {
    setEnvForTest("GEMINI_API_KEY", "g");
    setEnvForTest("GROQ_API_KEY", "q");
    setEnvForTest("OPENROUTER_API_KEY", "o");

    const fetchImpl: typeof fetch = async () => jsonResponse(500, { error: "down" });

    await expect(
      aiComplete("boom", { fetchImpl, cache: new Map() }),
    ).rejects.toBeInstanceOf(AllProvidersFailedError);
  });

  it("serves identical prompts from cache without re-calling any provider", async () => {
    setEnvForTest("GEMINI_API_KEY", "g");
    let providerCalls = 0;
    const fetchImpl: typeof fetch = async () => {
      providerCalls += 1;
      return geminiOk('{"cached":true}');
    };
    const cache = new Map();

    const first = await aiComplete("same-prompt", { fetchImpl, cache });
    const second = await aiComplete("same-prompt", { fetchImpl, cache });

    expect(first.provider).toBe("gemini");
    expect(second.cached).toBe(true);
    expect(providerCalls).toBe(1); // repeat short-circuits at $0
  });

  it("skips providers with no API key configured", async () => {
    // Only OpenRouter configured.
    setEnvForTest("OPENROUTER_API_KEY", "or-key");
    const fetchImpl: typeof fetch = async (input) => {
      if (String(input).includes("openrouter.ai")) return openRouterOk('{"via":"openrouter"}');
      return jsonResponse(500, {});
    };
    const result = await aiComplete("hi", { fetchImpl, cache: new Map() });
    expect(result.provider).toBe("openrouter");
  });
});

describe("parseAIJson tolerance", () => {
  it("parses plain and fenced JSON, returns null on garbage", () => {
    expect(parseAIJson('{"a":1}')).toEqual({ a: 1 });
    expect(parseAIJson('```json\n{"a":2}\n```')).toEqual({ a: 2 });
    expect(parseAIJson("```\n{\"a\":3}\n```")).toEqual({ a: 3 });
    expect(parseAIJson("not json")).toBeNull();
  });
});
