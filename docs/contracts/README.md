# Shared AI Prompt Contracts

These JSON Schemas are the single source of truth for AI-generated output shapes.

Both runtimes MUST produce payloads conforming to these contracts:

- **Python pipeline** (`src/job_radar/`) — batch classification, enrichment, bulk
  generation. Uses the disk-cached `classify_relevance.py` + `llm/router.py`.
- **TypeScript Edge Functions** (`supabase/functions/`) — on-demand, FE-triggered,
  auth-aware generation. Uses `_shared/ai-client.ts` (same Gemini -> Groq ->
  OpenRouter waterfall).

## Why shared contracts

A job's visa confidence, a cover letter, an outreach message, or a parsed resume
must be identical regardless of which runtime produced it. The FE codes against
these shapes, not against a specific provider.

## Contract index

| File | Produced by | Consumed by |
|---|---|---|
| `classifier_visa.schema.json` | Python classifier | `jobs` table, FE job cards |
| `cover_letter.schema.json` | Edge Function | FE apply flow, PDF gen |
| `outreach_messages.schema.json` | Edge Function | FE reach-out step |
| `parsed_resume.schema.json` | Edge Function | profile, matching |
| `tailored_resume.schema.json` | Edge Function | FE tailor step, PDF gen |

## Versioning

Every generated payload carries a `prompt_version` string. When a prompt changes,
bump the version so the disk cache and downstream consumers can key on it. The
Python `classify_relevance.py` disk cache remains hash-based on the job content;
prompt bumps are tracked separately in `generated_documents.prompt_version`.

## Provider fallback chain (both runtimes)

```
Gemini -> Groq -> OpenRouter (:free)
```

On 429/5xx the chain advances and an `ai_fallback_triggered` analytics event is
emitted. Cached results short-circuit the chain at $0.
