"""
src/job_radar/llm/router.py

Unified multi-provider LLM router with automatic waterfall fallback:
  1. Gemini (AI Studio / Vertex API keys) -> gemini-2.5-flash / gemini-3.6-flash / gemini-flash-latest
  2. Groq (free tier) -> llama-3.3-70b-versatile
  3. OpenRouter (free tier) -> OPENROUTER_MODEL (e.g. minimax/minimax-m3:free)
  4. Ollama (local) -> OLLAMA_HOST (e.g. http://localhost:11434)
  5. Heuristic fallback -> returns empty or structured mock without raising

Features:
- Deterministic response caching by SHA256(provider + model + prompt + schema)
- Daily API call counter & cap (LLM_DAILY_CAP, default 400)
- Fail-open architecture: catches all provider errors and proceeds to the next
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import requests

logger = logging.getLogger(__name__)

CACHE_FILE_PATH = Path("state/llm_cache.json")
DAILY_TRACKER_PATH = Path("state/llm_daily_tracker.json")

# Waterfall order — keep in sync with PROVIDER_CHAIN in _shared/ai-client.ts.
PROVIDER_CHAIN = ("gemini", "groq", "openrouter", "ollama")


@dataclass
class LLMResult:
    text: str
    model_used: str
    provider: str
    cached: bool = False
    latency_ms: int = 0
    raw_response: Optional[Any] = None


@dataclass
class ProviderAttempt:
    """One provider call result (mirror of TS ProviderAttempt)."""

    result: Optional[LLMResult]
    reason: str = ""


class LLMRouter:
    def __init__(
        self,
        cache_path: Path = CACHE_FILE_PATH,
        tracker_path: Path = DAILY_TRACKER_PATH,
        daily_cap: Optional[int] = None,
    ):
        self.cache_path = cache_path
        self.tracker_path = tracker_path
        self.daily_cap = daily_cap if daily_cap is not None else int(os.getenv("LLM_DAILY_CAP", "400"))
        self._cache: Dict[str, str] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception as e:
                logger.warning("Failed to load LLM cache from %s: %s", self.cache_path, e)
                self._cache = {}

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Failed to save LLM cache to %s: %s", self.cache_path, e)

    def _check_and_increment_daily_cap(self) -> bool:
        today_str = datetime.date.today().isoformat()
        tracker: Dict[str, Any] = {"date": today_str, "calls": 0}
        if self.tracker_path.exists():
            try:
                with open(self.tracker_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("date") == today_str:
                        tracker = data
            except Exception:
                pass

        if tracker["calls"] >= self.daily_cap:
            logger.warning("LLM daily cap reached (%d/%d calls today).", tracker["calls"], self.daily_cap)
            return False

        tracker["calls"] += 1
        try:
            self.tracker_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.tracker_path, "w", encoding="utf-8") as f:
                json.dump(tracker, f)
        except Exception:
            pass

        return True

    def _compute_cache_key(self, prompt: str, schema: Optional[Dict[str, Any]], custom_key: Optional[str]) -> str:
        if custom_key:
            return custom_key
        content = prompt + (json.dumps(schema, sort_keys=True) if schema else "")
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def complete(
        self,
        prompt: str,
        *,
        json_schema: Optional[Dict[str, Any]] = None,
        max_tokens: int = 4096,
        cache_key: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
    ) -> LLMResult:
        """
        Executes an LLM completion through the unified provider waterfall.
        Always fails open and never raises unhandled provider exceptions.
        """
        # 1. Check disk/memory cache
        key = self._compute_cache_key(prompt, json_schema, cache_key)
        if key in self._cache:
            return LLMResult(
                text=self._cache[key],
                model_used="cache",
                provider="cache",
                cached=True,
                latency_ms=0,
            )

        # 2. Check daily budget cap
        if not self._check_and_increment_daily_cap():
            logger.info("Daily LLM budget exhausted. Returning fallback empty response.")
            return LLMResult(
                text="{}" if json_schema else "",
                model_used="cap_exceeded",
                provider="fallback",
                cached=False,
                latency_ms=0,
            )

        t0 = time.perf_counter()

        # 3. Provider Waterfall
        # Provider 1: Gemini
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if gemini_key and gemini_key != "PLACEHOLDER_KEY":
            res = self._try_gemini(
                api_key=gemini_key,
                prompt=prompt,
                json_schema=json_schema,
                system_instruction=system_instruction,
                temperature=temperature,
            )
            if res:
                self._cache[key] = res.text
                self._save_cache()
                res.latency_ms = int((time.perf_counter() - t0) * 1000)
                return res

        # Provider 2: Groq
        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        if groq_key:
            res = self._try_groq(
                api_key=groq_key,
                prompt=prompt,
                json_schema=json_schema,
                system_instruction=system_instruction,
                temperature=temperature,
            )
            if res:
                self._cache[key] = res.text
                self._save_cache()
                res.latency_ms = int((time.perf_counter() - t0) * 1000)
                return res

        # Provider 3: OpenRouter
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if openrouter_key:
            res = self._try_openrouter(
                api_key=openrouter_key,
                prompt=prompt,
                json_schema=json_schema,
                system_instruction=system_instruction,
                temperature=temperature,
            )
            if res:
                self._cache[key] = res.text
                self._save_cache()
                res.latency_ms = int((time.perf_counter() - t0) * 1000)
                return res

        # Provider 4: Ollama
        ollama_host = os.getenv("OLLAMA_HOST", "").strip()
        if ollama_host:
            res = self._try_ollama(
                host=ollama_host,
                prompt=prompt,
                json_schema=json_schema,
                system_instruction=system_instruction,
            )
            if res:
                self._cache[key] = res.text
                self._save_cache()
                res.latency_ms = int((time.perf_counter() - t0) * 1000)
                return res

        # Provider 5: Fail-open fallback
        logger.warning("All LLM providers failed or no API keys configured. Returning empty fallback.")
        return LLMResult(
            text="{}" if json_schema else "",
            model_used="heuristic_fallback",
            provider="fallback",
            cached=False,
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    def try_provider(
        self,
        provider: str,
        prompt: str,
        *,
        json_schema: Optional[Dict[str, Any]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        use_cache: bool = True,
    ) -> ProviderAttempt:
        """Single-provider primitive (mirror of TS `aiTryProvider`).

        Never raises. Returns the result or a human-readable failure reason.
        Repair retries call this with ``use_cache=False`` so a rejected draft
        is never served from cache.
        """
        if provider not in PROVIDER_CHAIN:
            return ProviderAttempt(None, f"unknown provider {provider}")

        key = self._compute_cache_key(f"{provider}:{prompt}", json_schema, None)
        if use_cache and key in self._cache:
            return ProviderAttempt(
                LLMResult(text=self._cache[key], model_used="cache", provider=provider, cached=True)
            )

        if not self._check_and_increment_daily_cap():
            return ProviderAttempt(None, "daily LLM budget exhausted")

        t0 = time.perf_counter()
        result: Optional[LLMResult] = None
        reason = "no api key configured"

        if provider == "gemini":
            gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
            if gemini_key and gemini_key != "PLACEHOLDER_KEY":
                result = self._try_gemini(
                    api_key=gemini_key,
                    prompt=prompt,
                    json_schema=json_schema,
                    system_instruction=system_instruction,
                    temperature=temperature,
                )
                reason = "provider error or empty response"
        elif provider == "groq":
            groq_key = os.getenv("GROQ_API_KEY", "").strip()
            if groq_key:
                result = self._try_groq(
                    api_key=groq_key,
                    prompt=prompt,
                    json_schema=json_schema,
                    system_instruction=system_instruction,
                    temperature=temperature,
                )
                reason = "provider error or empty response"
        elif provider == "openrouter":
            openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
            if openrouter_key:
                result = self._try_openrouter(
                    api_key=openrouter_key,
                    prompt=prompt,
                    json_schema=json_schema,
                    system_instruction=system_instruction,
                    temperature=temperature,
                )
                reason = "provider error or empty response"
        elif provider == "ollama":
            ollama_host = os.getenv("OLLAMA_HOST", "").strip()
            if ollama_host:
                result = self._try_ollama(
                    host=ollama_host,
                    prompt=prompt,
                    json_schema=json_schema,
                    system_instruction=system_instruction,
                )
                reason = "provider error or empty response"

        if result is not None:
            if use_cache:
                self._cache[key] = result.text
                self._save_cache()
            result.latency_ms = int((time.perf_counter() - t0) * 1000)
        return ProviderAttempt(result, "" if result else reason)

    def evict_cache(self, provider: str, prompt: str, json_schema: Optional[Dict[str, Any]] = None) -> None:
        """Drop a cached provider response (used when it failed validation)."""
        key = self._compute_cache_key(f"{provider}:{prompt}", json_schema, None)
        if key in self._cache:
            del self._cache[key]
            self._save_cache()

    def _try_gemini(
        self,
        api_key: str,
        prompt: str,
        json_schema: Optional[Dict[str, Any]],
        system_instruction: Optional[str],
        temperature: float,
    ) -> Optional[LLMResult]:
        candidate_models = [
            os.getenv("GEMINI_PRO_MODEL", "gemini-2.5-flash"),
            os.getenv("GEMINI_FLASH_MODEL", "gemini-3.6-flash"),
            "gemini-flash-latest",
            "gemini-2.5-flash",
        ]
        seen = set()
        models = []
        for m in candidate_models:
            if m not in seen:
                seen.add(m)
                models.append(m)

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)

            for model_name in models:
                try:
                    config_kwargs: Dict[str, Any] = {"temperature": temperature}
                    if json_schema:
                        config_kwargs["response_mime_type"] = "application/json"
                    if system_instruction:
                        config_kwargs["system_instruction"] = system_instruction

                    config = types.GenerateContentConfig(**config_kwargs)
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=config,
                    )
                    text = (response.text or "").strip()
                    if text:
                        return LLMResult(text=text, model_used=model_name, provider="gemini")
                except Exception as e:
                    logger.debug("Gemini model %s failed: %s", model_name, e)
        except Exception as exc:
            logger.debug("Gemini initialization failed: %s", exc)

        return None

    def _try_groq(
        self,
        api_key: str,
        prompt: str,
        json_schema: Optional[Dict[str, Any]],
        system_instruction: Optional[str],
        temperature: float,
    ) -> Optional[LLMResult]:
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_schema:
            payload["response_format"] = {"type": "json_object"}

        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=25.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data["choices"][0]["message"]["content"].strip()
                return LLMResult(text=text, model_used=model, provider="groq")
            logger.debug("Groq returned status %d: %s", resp.status_code, resp.text)
        except Exception as e:
            logger.debug("Groq call failed: %s", e)

        return None

    def _try_openrouter(
        self,
        api_key: str,
        prompt: str,
        json_schema: Optional[Dict[str, Any]],
        system_instruction: Optional[str],
        temperature: float,
    ) -> Optional[LLMResult]:
        model = os.getenv("OPENROUTER_MODEL", "minimax/minimax-m3:free")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/AlirezaNezami96/Visa-Sponsorship-Daily-Jobs",
            "X-Title": "Job OS",
        }
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_schema:
            payload["response_format"] = {"type": "json_object"}

        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data["choices"][0]["message"]["content"].strip()
                return LLMResult(text=text, model_used=model, provider="openrouter")
            logger.debug("OpenRouter returned status %d: %s", resp.status_code, resp.text)
        except Exception as e:
            logger.debug("OpenRouter call failed: %s", e)

        return None

    def _try_ollama(
        self,
        host: str,
        prompt: str,
        json_schema: Optional[Dict[str, Any]],
        system_instruction: Optional[str],
    ) -> Optional[LLMResult]:
        model = os.getenv("OLLAMA_MODEL", "qwen2.5:latest")
        endpoint = f"{host.rstrip('/')}/api/chat"
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if json_schema:
            payload["format"] = "json"

        try:
            resp = requests.post(endpoint, json=payload, timeout=40.0)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("message", {}).get("content", "").strip()
                return LLMResult(text=text, model_used=model, provider="ollama")
        except Exception as e:
            logger.debug("Ollama call failed: %s", e)

        return None


# Global singleton router instance
_GLOBAL_ROUTER: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    global _GLOBAL_ROUTER
    if _GLOBAL_ROUTER is None:
        _GLOBAL_ROUTER = LLMRouter()
    return _GLOBAL_ROUTER


def complete(
    prompt: str,
    *,
    json_schema: Optional[Dict[str, Any]] = None,
    max_tokens: int = 4096,
    cache_key: Optional[str] = None,
    tools: Optional[List[Any]] = None,
    system_instruction: Optional[str] = None,
    temperature: float = 0.2,
) -> LLMResult:
    """Convenience functional wrapper for the global LLM router."""
    return get_llm_router().complete(
        prompt=prompt,
        json_schema=json_schema,
        max_tokens=max_tokens,
        cache_key=cache_key,
        tools=tools,
        system_instruction=system_instruction,
        temperature=temperature,
    )
