# Prompt Changelog

## v1 — Initial Release (2025-08)

### resume_tailor_v1.txt
- Model: `gemini-2.5-pro`
- 6-step Chain-of-Thought with structured JSON output
- Explicit honesty constraints: no fabricated skills, tools, or projects
- Keywords classified as: required / preferred / implicit
- Output: full structured JSON resume matching `GeminiResumeOutput` schema
- MAX_NEW_BULLETS: controlled per-request (default 3)

### cover_letter_v1.txt
- Model: `gemini-2.0-flash`
- 3-paragraph structure: Hook → Evidence → Close
- Anti-AI-voice forbidden patterns listed explicitly
- Tone modes: professional / startup / casual
- Output: plain body text only (no salutation/sign-off — added by template)
