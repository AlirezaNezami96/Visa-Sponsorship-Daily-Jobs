"""Enrichment worker — claims pending jobs and enriches metadata concurrently.

Runs as: python -m job_radar.pipeline.enrichment_worker

Claims jobs with `metadata_status='pending'` via the state machine, then runs
concurrent sub-tasks (skills, visa, salary, logo, etc.) in a thread pool.
Field-level NULL on sub-task failure; stage fails only if skills AND visa both
fail 3×.
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
    """Extract skills using simple keyword matching (no AI needed)."""
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
        # Word boundary matching
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, lower):
            found.append(skill)
    return sorted(set(found))


def _normalize_salary(raw: str | None) -> dict[str, Any]:
    """Parse salary string into structured fields."""
    result: dict[str, Any] = {"min": None, "max": None, "currency": None}
    if not raw:
        return result

    # Common patterns: "$80,000 - $120,000", "€50k-€70k", "80000-120000 USD"
    raw_clean = raw.replace(",", "").replace(" ", "")

    # Detect currency
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

    # Extract numbers
    numbers = re.findall(r'\d+(?:\.\d+)?', raw_clean)
    nums = []
    for n in numbers:
        val = float(n)
        # Handle "k" suffix
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
    """Fetch company logo via Google's S2 favicon service and upload to Storage."""
    import requests
    if not website:
        return None

    domain = website.replace("https://", "").replace("http://", "").split("/")[0]
    if not domain:
        return None

    try:
        favicon_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
        resp = requests.get(favicon_url, timeout=10)
        if resp.status_code != 200 or len(resp.content) < 100:
            return None

        # Upload to Storage
        path = f"logos/{domain.replace('.', '_')}.png"
        client.storage.from_("companies").upload(
            path, resp.content,
            file_options={"content-type": "image/png", "upsert": "true"},
        )

        # Return public URL
        supabase_url = os.environ.get("SUPABASE_URL", "")
        return f"{supabase_url}/storage/v1/object/public/companies/{path}"
    except Exception as e:
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

    # --- Sub-task 1: Skill extraction ---
    skills_ok = False
    try:
        desc = job.get("description_text") or ""
        title = job.get("title") or ""
        skills = _extract_skills_rule_based(f"{title} {desc}")
        if skills:
            update["skills"] = skills
            update["skills_extracted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            skills_ok = True
        else:
            update["skill_extraction_error"] = "no skills detected"
    except Exception as e:
        errors.append(f"skills: {e}")

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
                logo_url = _fetch_company_logo(
                    client,
                    co_resp.data.get("name", ""),
                    co_resp.data.get("website"),
                )
                if logo_url:
                    update["company_logo_url"] = logo_url
    except Exception as e:
        errors.append(f"logo: {e}")

    # Apply updates to job
    if update:
        update["processed_enrichment"] = True
        client.table("jobs").update(update).eq("id", job_id).execute()

    # Transition state
    duration_ms = int((time.time() - start) * 1000)

    # Stage fails only if skills extraction failed (critical sub-task)
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
