# VisaLane — Phase-2 Walkthrough

Operational guide to the Phase-2 additions on top of INTEGRATION.md.

## What was added

| Area | Where | Purpose |
|---|---|---|
| Brand card renderer | `src/job_radar/social/` (brand.py, card_renderer.py, landmark.py, card_pipeline.py, publisher.py) | Deterministic PNG job cards from live data + licensed Wikimedia photos. |
| PDF assembly | `src/job_radar/ai/pdf_builder.py` | ATS-safe resume & cover-letter PDFs from validated AI JSON. |
| Hallucination validators | `engine/ai/validators.py` | Reject invented employers/titles/dates before any output is stored. |
| Repair-then-waterfall | `src/job_radar/llm/validated.py` → `run_validated_completion` | One repair retry on the same provider, then Gemini→Groq→OpenRouter→Ollama. |
| AI smoke test | `scripts/smoke_ai.py` | `--mock` (every PR) and live-waterfall (nightly) end-to-end flow. |
| Visual render helper | `scripts/render_cards.py` | Generate N cards from live or sample jobs for visual QA. |
| Backup workflows | `.github/workflows/db-backup.yml`, `storage-backup.yml` | Daily pg_dump → Drive (+Artifact fallback); weekly Storage zip → Drive. |
| Bundled OFL fonts | `assets/fonts/` (Poppins ×2, Inter ×3, OFL licenses) | No system fonts, ever — missing file is a hard error. |

## Brand-card rendering rules (GAP 1 — read carefully)

1. **No AI image generation.** Cards are rendered by pure Pillow primitives.
2. **Photo sourcing.** `landmark.fetch_landmark_photo` queries Wikimedia Commons, accepts only Public Domain / CC0 / CC BY / CC BY-SA, rejects NC/ND/unknown, caches in `media_assets` for 30 days, uploads to Storage `landmarks/{country}-{city}.jpg`. Any failure returns `(None, None)` → renderer uses deterministic navy + red diagonal-band fallback. Unlicensed images never ship.
3. **Determinism.** `render_card_png` is a pure function of `(CardJob, photo_bytes)`; identical inputs produce identical PNG bytes.
4. **Badge rule.** Visa badge shows only when `visa_sponsorship_verified == True OR visa_sponsorship_confidence >= 60`. When hidden, all rows at/below shift up by 120 px (deterministic `compute_layout`).
5. **Title auto-fit.** Title measured with real font metrics; tried at 96px → 80px → 66px, hard-capped at 2 lines.
6. **Fonts.** Six bundled OFL TTFs in `assets/fonts/`. `brand.font_path()` raises `FileNotFoundError` if any is missing — never silently falls back to a system font.

Run visual QA:
    python scripts/render_cards.py --limit 10 --out build/cards
    python scripts/render_cards.py --limit 5 --no-landmarks

## PDF assembly (GAP 2)

- `build_resume_pdf(profile, tailored, format_type)` — ≤ 2 pages; over-length documents are shrunk by dropping whole trailing bullets via binary search (never mid-word). `format_type="professional"` uses fixed `Summary→Skills→Experience→Education→Links`; `"own"` respects `profile["section_order"]`.
- `build_cover_letter_pdf(profile, cover_letter, job)` — ≤ 1 page; over-length drops trailing paragraphs.
- Fixed `CreationDate=2026-01-01 UTC` → identical inputs produce byte-identical PDFs (cacheable, signed-URL previewable).
- AI output is accepted in both wrapped `{"sections": {...}}` and flat `{"summary", "skills", ...}` shapes.

## AI hardening (GAP 3)

### Validators (`engine/ai/validators.py`)

- **`validate_tailored_resume(parsed, snapshot)`** — every employer, title, year, institution in `parsed.experience` / `parsed.education` must be grounded in the profile snapshot (normalized NFKD compare). New employer = reject. New degree = reject.
- **`validate_cover_letter(parsed, snapshot, company, company_hook_context)`** — 250–400 words, blocklist (6 phrases including "delve", "thrilled to apply", "to whom it may concern"), must reference ≥1 company token AND ≥1 user metric/fact.
- **`validate_outreach(parsed, expected_tone)`** — LinkedIn ≤ 300 chars hard, email ≤ 220 words, tone match.

### Repair-then-waterfall (`src/job_radar/llm/validated.py`)

`run_validated_completion(prompt, validate, router, document_type)`:
1. Send to primary provider.
2. Run validator. Pass → return.
3. Fail → **one** repair retry to the *same* provider with violation list appended.
4. Still failing → advance waterfall: Gemini → Groq → OpenRouter → Ollama (Python only).
5. All providers failing → return `ValidatedCompletion(ok=False, violation=...)` with `ai_error` analytics event.

### Idempotency (Edge Functions) — **VERIFY AND ADD IF MISSING**

In every on-demand Edge Function (`generate-tailored-resume`, `generate-cover-letter`, `generate-outreach-messages`), before calling AI:

```typescript
const idemKey = `${userId}:${jobId}:${docType}:${formatType}:${profileUpdatedAt}:${PROMPT_VERSION}`;
const cached = await supabase
  .from('generated_documents')
  .select('*')
  .eq('idempotency_key', idemKey)
  .eq('status', 'completed')
  .maybeSingle();
if (cached) return { ...cached, signed_url: await signUrl(cached.file_path), from_cache: true };
```

Quota increment happens **only** after validator passes. A cached hit must not charge quota or call AI. Add the `idempotency_key TEXT` column to `generated_documents` in a new migration if not already present.

## Smoke tests (GAP 3.4)

- `scripts/smoke_ai.py --mock` runs on every PR in CI (`smoke-ai.yml`) with scripted responses — zero API keys.
- Nightly run without `--mock` exercises the real Gemini→Groq→OpenRouter waterfall.
- Exits non-zero on any failed assertion, triggering the existing Resend run-alert to the owner.

Assertions in the smoke cover:
- parse → grounded (TechCorp + StartupX present)
- tailored resume validator accepts + PDF builds + ≤ 2 pages + deterministic bytes
- cover letter 250–400 words + references company + PDF ≤ 1 page
- outreach LinkedIn ≤ 300 chars + email ≤ 220 words + tone match

## Backup & alerting (GAP 5)

- `db-backup.yml` — daily 03:00 UTC: `pg_dump` → gzip → Google Drive (service-account secret) → prune >30d. Drive failure → same file as GitHub Artifact.
- `storage-backup.yml` — weekly: download user PDFs from Storage, zip, upload to Drive.
- `smoke-ai.yml` — nightly live AI waterfall smoke; failure emails owner via Resend.
- Alert channels (Email Resend→Brevo, Telegram Bot, Discord webhook, Slack webhook) were wired in the prior backend pass; this phase only added the smoke-test alert.

## Frontend live-switch checklist (GAP 4)

`global-job-pass/src/services/api.ts` is a 1:1 adapter — each function maps to exactly one backend endpoint. Going live means replacing the body of each adapter function with its real call; components stay untouched. See `docs/fe-switch/adapter-live.ts` for the exact call bodies.

Env vars (production build):
- `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`
- `VITE_USE_MOCKS=false` (kill-switch)

Acceptance: with mocks OFF against a seeded Supabase, the full apply flow (login → parse → tailor → PDF preview via signed URL → cover letter → outreach → complete-application → My Jobs shows Applied) passes the Playwright script.

## Verification pipeline (run before declaring done)

1. `pytest` + `vitest run` — green.
2. `ruff` + `mypy` + `deno lint/check` — clean.
3. `python scripts/smoke_ai.py --mock` — green.
4. `python scripts/render_cards.py --limit 10 --out build/cards` — visually inspect 10 cards against the reference layout.
5. `supabase db push` — clean.
6. `supabase functions deploy` — clean.
7. Idempotency manual test: call `generate-tailored-resume` twice with identical inputs → second call returns the cached row with `from_cache: true` and quota unchanged.
