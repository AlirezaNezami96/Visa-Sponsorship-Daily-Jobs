"""Python mirror of the repair-then-waterfall generation loop (GAP 3.2).

Mirrors `_shared/generation.ts` step 2 so both runtimes behave identically:

  for each provider in Gemini -> Groq -> OpenRouter -> Ollama:
      attempt = provider(base_prompt)
      on validation failure -> ONE repair retry to the SAME provider with the
      explicit violation list appended; still failing -> advance the waterfall.

Events logged through the shared `analytics_events` emitter:
  - ai_fallback_triggered  (provider advanced)
  - ai_validation_repair   (repair retry + resolved flag)
  - ai_error               (all providers exhausted)

Quota/idempotency live in the Edge Function layer (user-facing on-demand
generation); this helper is for pipeline/script callers (smoke tests, batch
jobs) that need the same grounding guarantees without the HTTP surface.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .router import PROVIDER_CHAIN, ProviderAttempt, get_llm_router

logger = logging.getLogger(__name__)

Validator = Callable[[dict[str, Any]], str | None]


class ProviderRouter(Protocol):
    """Structural surface this loop needs (LLMRouter and test fakes both fit)."""

    def try_provider(
        self,
        provider: str,
        prompt: str,
        *,
        json_schema: dict[str, Any] | None = None,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        use_cache: bool = True,
    ) -> ProviderAttempt: ...

    def evict_cache(self, provider: str, prompt: str, json_schema: dict[str, Any] | None = None) -> None: ...


@dataclass
class ValidatedCompletion:
    ok: bool
    parsed: dict[str, Any] | None = None
    provider: str | None = None
    model: str | None = None
    violation: str = ""
    repair_attempts: int = 0
    fallbacks: list[str] = field(default_factory=list)


def build_repair_prompt(base_prompt: str, violations: str) -> str:
    """Identical wording to buildRepairPrompt in _shared/generation.ts."""
    return f"""{base_prompt}

The previous response was REJECTED for these exact violations:
- {violations}
Fix ONLY these violations. Keep every grounded fact unchanged. Return the complete corrected JSON again, no markdown fences."""


def parse_ai_json(text: str) -> dict[str, Any] | None:
    """Robust JSON object extraction (strips fences, tolerates leading prose).

    Mirror of parseAIJson in _shared/ai-client.ts.
    """
    candidate = (text or "").strip()
    if not candidate:
        return None
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    start = candidate.find("{")
    if start == -1:
        return None
    for end in range(len(candidate), start, -1):
        if candidate[end - 1] != "}":
            continue
        try:
            parsed = json.loads(candidate[start:end])
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def run_validated_completion(
    prompt: str,
    validate: Validator,
    *,
    router: ProviderRouter | None = None,
    json_schema: dict[str, Any] | None = None,
    system_instruction: str | None = None,
    temperature: float = 0.2,
    document_type: str = "document",
    user_id: str | None = None,
    event_sink: Callable[[str, dict[str, Any]], None] | None = None,
) -> ValidatedCompletion:
    """Repair-then-waterfall generation with grounding validation.

    Returns a ValidatedCompletion; never raises on provider failure.
    ``event_sink`` overrides the default analytics emitter (tests inject fakes).
    """
    llm = router or get_llm_router()

    def _default_sink(name: str, meta: dict[str, Any]) -> None:
        # Lazy import: keeps the module import chain out of module-load time.
        from ..analytics import emit_event

        emit_event(name, user_id=user_id, metadata=meta)

    sink = event_sink or _default_sink

    base_prompt = prompt
    previous_provider: str | None = None
    previous_reason = ""
    last_violation = ""
    repair_attempts = 0
    fallbacks: list[str] = []

    for provider in PROVIDER_CHAIN:
        if previous_provider:
            fallbacks.append(f"{previous_provider} -> {provider}")
            try:
                sink(
                    "ai_fallback_triggered",
                    {
                        "from_provider": previous_provider,
                        "reason": previous_reason,
                        "document_type": document_type,
                        "runtime": "python",
                    },
                )
            except Exception:  # analytics must never break generation
                logger.debug("analytics sink failed", exc_info=True)

        attempt = llm.try_provider(
            provider,
            base_prompt,
            json_schema=json_schema,
            system_instruction=system_instruction,
            temperature=temperature,
        )
        if attempt.result is None:
            previous_provider = provider
            previous_reason = attempt.reason
            continue

        parsed = parse_ai_json(attempt.result.text)
        violation = validate(parsed) if parsed is not None else "AI response was not valid JSON"
        violation = violation or ""

        if violation:
            # The base response is unusable — evict it from the cache so the
            # next request with the same prompt retries fresh instead of
            # replaying a known-bad response.
            try:
                llm.evict_cache(provider, base_prompt, json_schema)
            except Exception:
                logger.debug("cache eviction failed", exc_info=True)
            repair_attempts += 1
            repair = llm.try_provider(
                provider,
                build_repair_prompt(base_prompt, violation),
                json_schema=json_schema,
                system_instruction=system_instruction,
                temperature=temperature,
                use_cache=False,  # repair prompt is never served from cache
            )
            repaired = parse_ai_json(repair.result.text) if repair.result is not None else None
            repaired_violation = (
                (validate(repaired) or "") if repaired is not None else "repair response was not valid JSON"
            )
            try:
                sink(
                    "ai_validation_repair",
                    {
                        "provider": provider,
                        "document_type": document_type,
                        "violations": violation[:500],
                        "resolved": not repaired_violation,
                        "runtime": "python",
                    },
                )
            except Exception:
                logger.debug("analytics sink failed", exc_info=True)

            if not repaired_violation and repaired is not None and repair.result is not None:
                return ValidatedCompletion(
                    ok=True,
                    parsed=repaired,
                    provider=repair.result.provider,
                    model=repair.result.model_used,
                    violation="",
                    repair_attempts=repair_attempts,
                    fallbacks=fallbacks,
                )
            parsed = repaired if repaired is not None else parsed
            violation = repaired_violation

        if not violation and parsed is not None:
            return ValidatedCompletion(
                ok=True,
                parsed=parsed,
                provider=attempt.result.provider,
                model=attempt.result.model_used,
                violation="",
                repair_attempts=repair_attempts,
                fallbacks=fallbacks,
            )

        # Validation still failing after repair -> advance the waterfall.
        previous_provider = provider
        previous_reason = f"validation_failed: {violation[:120]}"
        last_violation = violation

    message = last_violation or "all AI providers are temporarily unavailable"
    try:
        sink(
            "ai_error",
            {
                "where": "python_validated_completion",
                "document_type": document_type,
                "message": message[:300],
                "runtime": "python",
            },
        )
    except Exception:
        logger.debug("analytics sink failed", exc_info=True)

    return ValidatedCompletion(
        ok=False,
        parsed=None,
        violation=message,
        repair_attempts=repair_attempts,
        fallbacks=fallbacks,
    )
