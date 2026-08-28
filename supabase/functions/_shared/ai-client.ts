/**
 * Multi-provider AI client for on-demand Edge Function generation.
 *
 * Mirrors the Python `job_radar/llm/router.py` waterfall so both runtimes
 * behave identically (master plan section 6.1 / docs/contracts/README.md):
 *
 *   Gemini -> Groq -> OpenRouter
 *
 * On 429/5xx or a missing key the chain advances and the injected
 * `onFallback` observer is called (used to log `ai_fallback_triggered`).
 * An in-memory deterministic cache (sha256 of prompt+schema) makes repeated
 * identical generations free within a function instance's lifetime.
 */
import { getEnv } from "./env.ts";

export interface AIResult {
  text: string;
  provider: string;
  model: string;
  cached: boolean;
  latency_ms: number;
}

export interface AIClientOptions {
  /** Observation hook invoked when the chain advances past a provider. */
  onFallback?: (from: string, reason: string) => void | Promise<void>;
  /** Injected fetch for tests. */
  fetchImpl?: typeof fetch;
  /** Injected cache store override (defaults to shared in-memory map). */
  cache?: Map<string, AIResult>;
}

const memoryCache = new Map<string, AIResult>();

async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function isRetryable(status: number): boolean {
  return status === 429 || status >= 500;
}

async function tryGemini(prompt: string, wantJson: boolean, f: typeof fetch): Promise<AIResult | null> {
  const key = getEnv("GEMINI_API_KEY");
  if (!key) return null;
  const model = getEnv("GEMINI_PRO_MODEL") || "gemini-2.5-flash";
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${key}`;
  const body: Record<string, unknown> = {
    contents: [{ role: "user", parts: [{ text: prompt }] }],
    generationConfig: { temperature: 0.2 },
  };
  if (wantJson) {
    (body.generationConfig as Record<string, unknown>).responseMimeType = "application/json";
  }
  const resp = await f(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new AIFailure("gemini", resp.status, await resp.text().catch(() => ""));
  }
  const data = await resp.json();
  const text = data?.candidates?.[0]?.content?.parts?.map((p: { text?: string }) => p.text ?? "").join("") ?? "";
  if (!text.trim()) return null;
  return { text, provider: "gemini", model, cached: false, latency_ms: 0 };
}

async function tryGroq(prompt: string, wantJson: boolean, f: typeof fetch): Promise<AIResult | null> {
  const key = getEnv("GROQ_API_KEY");
  if (!key) return null;
  const model = getEnv("GROQ_MODEL") || "llama-3.3-70b-versatile";
  const payload: Record<string, unknown> = {
    model,
    messages: [{ role: "user", content: prompt }],
    temperature: 0.2,
  };
  if (wantJson) payload.response_format = { type: "json_object" };
  const resp = await f("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    throw new AIFailure("groq", resp.status, await resp.text().catch(() => ""));
  }
  const data = await resp.json();
  const text = data?.choices?.[0]?.message?.content ?? "";
  if (!text.trim()) return null;
  return { text, provider: "groq", model, cached: false, latency_ms: 0 };
}

async function tryOpenRouter(prompt: string, wantJson: boolean, f: typeof fetch): Promise<AIResult | null> {
  const key = getEnv("OPENROUTER_API_KEY");
  if (!key) return null;
  const model = getEnv("OPENROUTER_MODEL") || "minimax/minimax-m3:free";
  const payload: Record<string, unknown> = {
    model,
    messages: [{ role: "user", content: prompt }],
    temperature: 0.2,
  };
  if (wantJson) payload.response_format = { type: "json_object" };
  const resp = await f("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      "HTTP-Referer": "https://github.com/AlirezaNezami96/Visa-Sponsorship-Daily-Jobs",
      "X-Title": "VisaLane",
    },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    throw new AIFailure("openrouter", resp.status, await resp.text().catch(() => ""));
  }
  const data = await resp.json();
  const text = data?.choices?.[0]?.message?.content ?? "";
  if (!text.trim()) return null;
  return { text, provider: "openrouter", model, cached: false, latency_ms: 0 };
}

export class AIFailure extends Error {
  constructor(
    public provider: string,
    public status: number,
    public detail: string,
  ) {
    super(`${provider} failed with ${status}`);
  }
}

export class AllProvidersFailedError extends Error {
  constructor(
    public readonly attempts: Array<{ provider: string; reason: string }>,
  ) {
    super(`All AI providers failed: ${attempts.map((a) => `${a.provider}(${a.reason})`).join(", ")}`);
  }
}

const CHAIN: Array<{ name: string; fn: typeof tryGemini }> = [
  { name: "gemini", fn: tryGemini },
  { name: "groq", fn: tryGroq },
  { name: "openrouter", fn: tryOpenRouter },
];

/**
 * Run a completion through the provider waterfall.
 * Throws AllProvidersFailedError only when every provider fails (structured
 * error, never a raw provider exception — master plan section 6.1).
 */
export async function aiComplete(
  prompt: string,
  options: AIClientOptions & { json?: boolean } = {},
): Promise<AIResult> {
  const cache = options.cache ?? memoryCache;
  const cacheKey = await sha256Hex(`${prompt}::json=${options.json ? "1" : "0"}`);
  const hit = cache.get(cacheKey);
  if (hit) {
    return { ...hit, cached: true };
  }

  const f = options.fetchImpl ?? fetch;
  const attempts: Array<{ provider: string; reason: string }> = [];
  const started = Date.now();
  const last = CHAIN.length - 1;

  for (let i = 0; i < CHAIN.length; i++) {
    const { name, fn } = CHAIN[i];
    let reason: string | null = null;
    try {
      const result = await fn(prompt, options.json ?? false, f);
      if (result) {
        result.latency_ms = Date.now() - started;
        cache.set(cacheKey, result);
        return result;
      }
      reason = "empty_response";
    } catch (err) {
      reason = err instanceof AIFailure ? `http_${err.status}${isRetryable(err.status) ? "" : "_fatal"}` : "network_error";
    }
    attempts.push({ provider: name, reason });
    // Advancing to the next provider is a fallback event (observed for analytics).
    if (i < last && options.onFallback) {
      await options.onFallback(name, reason);
    }
  }

  throw new AllProvidersFailedError(attempts);
}

/** Parse a JSON AI response tolerantly (strips ```json fences like the Python side). */
export function parseAIJson<T = Record<string, unknown>>(text: string): T | null {
  let cleaned = text.trim();
  if (cleaned.startsWith("```json")) cleaned = cleaned.split("```json", 2)[1]?.split("```", 1)[0] ?? "";
  else if (cleaned.startsWith("```")) cleaned = cleaned.split("```", 2)[1]?.split("```", 1)[0] ?? "";
  cleaned = cleaned.trim();
  try {
    return JSON.parse(cleaned) as T;
  } catch {
    return null;
  }
}
