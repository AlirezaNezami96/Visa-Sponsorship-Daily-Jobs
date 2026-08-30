"""Enrichment worker — claims pending jobs and enriches metadata concurrently.

Runs as: python -m job_radar.pipeline.enrichment_worker

Claims jobs with `metadata_status='pending'` via the state machine, then runs
concurrent sub-tasks (skills with AI + rule fallback, salary, work mode, company logo)
in a thread pool with circuit breakers and field-level failure isolation.
"""
from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger(__name__)

BATCH_SIZE = int(os.getenv("ENRICH_BATCH_SIZE", "50"))
THREAD_POOL_SIZE = int(os.getenv("ENRICH_THREADS", "8"))


def _create_client() -> Any:
    """Create a Supabase service-role client."""
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def _extract_skills_rule_based(text: str) -> list[str]:
    """Extract skills using keyword matching."""
    KNOWN_SKILLS = {
        "python", "javascript", "typescript", "react", "vue", "angular",
        "nodejs", "java", "kotlin", "swift", "go", "rust", "ruby",
        "php", "sql", "postgresql", "mysql", "mongodb", "redis",
        "docker", "kubernetes", "aws", "gcp", "azure", "terraform",
        "git", "ci/cd", "graphql", "rest", "grpc", "kafka",
        "elasticsearch", "machine learning", "deep learning", "nlp",
        "tensorflow", "pytorch", "pandas", "numpy", "scipy",
        "flutter", "dart", "c++", "c#", ".net", "spring", "django",
        "fastapi", "flask", "express", "nextjs", "nuxtjs", "svelte",
        "tailwind", "css", "html", "sass", "webpack", "vite",
        "figma", "sketch", "agile", "scrum", "jira", "confluence",
        "linux", "nginx", "apache", "cloudflare", "vercel", "netlify",
        "supabase", "firebase", "heroku", "digitalocean",
    }
    if not text:
        return []
    lower = text.lower()
    found = []
    for skill in KNOWN_SKILLS:
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, lower):
            found.append(skill)
    return sorted(set(found))


def _extract_skills_ai(text: str, client: Any = None) -> list[str]:
    """Extract skills using fast LLM call (<=3s) with circuit breaker."""
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key or len(text.strip()) < 50:
        return []

    cb = None
    if client:
        try:
            from job_radar.pipeline.circuit_breaker import CircuitBreaker
            cb = CircuitBreaker(client)
            if cb.is_open("ai_skills"):
                return []
        except Exception:
            pass

    import requests
    prompt = (
        "Extract a JSON array of up to 10 technical and professional skills from this job description. "
        "Return ONLY a JSON array of strings, e.g. [\"Python\", \"PostgreSQL\", \"AWS\"].\n\n"
        f"Job text: {text[:2000]}"
    )
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 80,
                "temperature": 0.1,
            },
            timeout=3,
        )
        if resp.status_code == 200:
            if cb:
                cb.record_success("ai_skills")
            content = resp.json()["choices"][0]["message"]["content"].strip()
            # Clean JSON fences if present
            content = re.sub(r"^```(json)?|```$", "", content).strip()
            import json
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return [str(s).lower().strip() for s in parsed if s]
        else:
            if cb:
                cb.record_failure("ai_skills")
    except Exception as e:
        if cb:
            cb.record_failure("ai_skills")
        logger.debug("AI skill extraction failed: %s", e)

    return []


def _normalize_salary(raw: str | None) -> dict[str, Any]:
    """Parse salary string into structured fields."""
    result: dict[str, Any] = {"min": None, "max": None, "currency": None}
    if not raw:
        return result

    raw_clean = raw.replace(",", "").replace(" ", "")

    currency_map = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR"}
    for sym, code in currency_map.items():
        if sym in raw:
            result["currency"] = code
            break
    if not result["currency"]:
        for code in ("USD", "EUR", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK"):
            if code.lower() in raw.lower():
                result["currency"] = code
                break

    numbers = re.findall(r'\d+(?:\.\d+)?', raw_clean)
    nums = []
    for n in numbers:
        val = float(n)
        if f"{n}k" in raw_clean.lower() or f"{n}K" in raw_clean:
            val *= 1000
        nums.append(int(val))

    if len(nums) >= 2:
        result["min"] = min(nums[0], nums[1])
        result["max"] = max(nums[0], nums[1])
    elif len(nums) == 1:
        result["min"] = nums[0]
        result["max"] = nums[0]

    return result


def _normalize_work_mode(raw: str | None) -> str | None:
    """Normalize work mode to standard values."""
    if not raw:
        return None
    lower = raw.lower().strip()
    if any(kw in lower for kw in ("remote", "fully remote", "work from home", "wfh")):
        return "remote"
    if any(kw in lower for kw in ("hybrid", "flexible")):
        return "hybrid"
    if any(kw in lower for kw in ("onsite", "on-site", "in-office", "office")):
        return "onsite"
    return raw


def _fetch_company_logo(client: Any, company_name: str, website: str | None) -> str | None:
    """Fetch company logo via Google's S2 favicon service with circuit breaker."""
    if not website:
        return None

    domain = website.replace("https://", "").replace("http://", "").split("/")[0]
    if not domain:
        return None

    cb = None
    try:
        from job_radar.pipeline.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(client)
        if cb.is_open("s2_favicons"):
            from job_radar.pipeline.metrics import record_metric
            record_metric(client, "circuit:open:s2_favicons", True, 0)
            return None
    except Exception:
        pass

    import requests
    try:
        favicon_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
        resp = requests.get(favicon_url, timeout=6)
        if resp.status_code != 200 or len(resp.content) < 100:
            if cb:
                cb.record_failure("s2_favicons")
            return None

        path = f"logos/{domain.replace('.', '_')}.png"
        client.storage.from_("companies").upload(
            path, resp.content,
            file_options={"content-type": "image/png", "upsert": "true"},
        )

        if cb:
            cb.record_success("s2_favicons")

        supabase_url = os.environ.get("SUPABASE_URL", "")
        return f"{supabase_url}/storage/v1/object/public/companies/{path}"
    except Exception as e:
        if cb:
            cb.record_failure("s2_favicons")
        logger.debug("Logo fetch failed for %s: %s", domain, e)
        return None


def enrich_job(client: Any, job_id: str) -> dict[str, Any]:
    """Enrich a single job with metadata. Returns result dict."""
    from job_radar.pipeline.state_machine import transition_stage
    from job_radar.pipeline.metrics import record_metric

    start = time.time()
    errors: list[str] = []

    # Fetch job data
    resp = (
        client.table("jobs")
        .select("*")
        .eq("id", job_id)
        .maybe_single()
        .execute()
    )
    if not resp or not resp.data:
        transition_stage(client, job_id, "metadata", "failed", error="job not found")
        return {"ok": False, "error": "job not found"}

    job = resp.data
    update: dict[str, Any] = {}

    # --- Sub-task 1: Skill extraction (AI with rule fallback) ---
    skills_ok = False
    try:
        desc = job.get("description_text") or job.get("description") or ""
        title = job.get("title") or ""
        full_text = f"{title} {desc}"

        # 1. Try AI skill extraction
        ai_skills = _extract_skills_ai(full_text, client=client)
        if ai_skills:
            update["skills"] = ai_skills
            update["skills_extracted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            skills_ok = True
            record_metric(client, "enrich:skills:ai", True, 0)
        else:
            # 2. Rule-based fallback
            rule_skills = _extract_skills_rule_based(full_text)
            if rule_skills:
                update["skills"] = rule_skills
                update["skills_extracted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                skills_ok = True
                record_metric(client, "enrich:skills:rule", True, 0)
            else:
                update["skill_extraction_error"] = "no skills detected"
    except Exception as e:
        errors.append(f"skills: {e}")
        update["skill_extraction_error"] = str(e)[:200]

    # --- Sub-task 2: Salary normalization ---
    try:
        salary = _normalize_salary(job.get("salary_raw"))
        if salary["min"]:
            update["salary_min"] = salary["min"]
        if salary["max"]:
            update["salary_max"] = salary["max"]
        if salary["currency"]:
            update["salary_currency"] = salary["currency"]
    except Exception as e:
        errors.append(f"salary: {e}")

    # --- Sub-task 3: Work mode normalization ---
    try:
        wm = _normalize_work_mode(job.get("work_mode"))
        if wm:
            update["work_mode"] = wm
    except Exception as e:
        errors.append(f"work_mode: {e}")

    # --- Sub-task 4: Company logo ---
    try:
        company_id = job.get("company_id")
        if company_id:
            co_resp = (
                client.table("companies")
                .select("name, website")
                .eq("id", company_id)
                .maybe_single()
                .execute()
            )
            if co_resp and co_resp.data:
                # Circuit breaker for logo fetch
                from job_radar.pipeline.circuit_breaker import CircuitBreaker
                cb = CircuitBreaker(client)
                cb_name = "s2_favicons"

                if not cb.is_open(cb_name):
                    logo_url = _fetch_company_logo(
                        client,
                        co_resp.data.get("name", ""),
                        co_resp.data.get("website"),
                    )
                    if logo_url:
                        update["company_logo_url"] = logo_url
                        cb.record_success(cb_name)
                    else:
                        cb.record_failure(cb_name)
                else:
                    record_metric(client, f"circuit:open:{cb_name}", True, 0)
                    logger.debug("Circuit open for %s, skipping logo fetch", cb_name)
    except Exception as e:
        errors.append(f"logo: {e}")

    # Apply updates to job
    if update:
        update["processed_enrichment"] = True
        client.table("jobs").update(update).eq("id", job_id).execute()

    duration_ms = int((time.time() - start) * 1000)

    if skills_ok or not job.get("description_text"):
        transition_stage(client, job_id, "metadata", "done",
                        metrics_fn=lambda n, o, d: record_metric(client, n, o, d))
        record_metric(client, "enrich:ok", True, duration_ms)
        return {"ok": True, "errors": errors, "duration_ms": duration_ms}
    else:
        err_msg = "; ".join(errors) if errors else "skill extraction failed"
        transition_stage(client, job_id, "metadata", "failed", error=err_msg,
                        metrics_fn=lambda n, o, d: record_metric(client, n, o, d))
        record_metric(client, "enrich:fail", False, duration_ms)
        return {"ok": False, "errors": errors, "duration_ms": duration_ms}


def run_enrichment_batch() -> dict[str, Any]:
    """Run one enrichment batch. Entry point for the GitHub Actions workflow."""
    from job_radar.pipeline.state_machine import claim_pending
    from job_radar.pipeline.metrics import update_pipeline_health

    client = _create_client()
    claimed = claim_pending(client, "metadata", limit=BATCH_SIZE)

    if not claimed:
        logger.info("No pending jobs to enrich")
        update_pipeline_health(client, "metadata", backlog=0)
        return {"processed": 0, "succeeded": 0, "failed": 0}

    logger.info("Claimed %d jobs for enrichment", len(claimed))
    succeeded = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE) as pool:
        futures = {pool.submit(enrich_job, client, jid): jid for jid in claimed}
        for future in as_completed(futures):
            jid = futures[future]
            try:
                result = future.result()
                if result["ok"]:
                    succeeded += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error("Enrichment crashed for job %s: %s", jid, e)
                failed += 1

    update_pipeline_health(
        client, "metadata",
        success=succeeded > 0,
        error=f"{failed} jobs failed" if failed else None,
    )

    logger.info(
        "Enrichment batch complete: %d processed, %d succeeded, %d failed",
        len(claimed), succeeded, failed,
    )
    return {"processed": len(claimed), "succeeded": succeeded, "failed": failed}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    result = run_enrichment_batch()
    logger.info("Result: %s", result)
