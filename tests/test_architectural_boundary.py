"""Architectural boundary tests asserting complete purity between Core, Actor, and Personal Workflows."""
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_core_contains_no_apify_imports():
    """Assert that core src/job_radar/ directory never imports apify or references Actor/Dataset runtime calls."""
    core_dir = REPO_ROOT / "src" / "job_radar"
    py_files = list(core_dir.rglob("*.py"))
    assert len(py_files) > 0

    apify_import_pattern = re.compile(r"^\s*(import\s+apify|from\s+apify\s+import|Actor\.[a-z_]+)", re.MULTILINE)

    violations = []
    for f in py_files:
        content = f.read_text(encoding="utf-8")
        matches = apify_import_pattern.findall(content)
        if matches:
            violations.append(f"{f.relative_to(REPO_ROOT)}: {matches}")

    assert not violations, f"Core framework-agnostic code violated boundary with Apify imports: {violations}"


def test_apify_actor_contains_no_personal_alerts_or_secrets():
    """Assert that apify_actor/ and .actor/ contain zero references to personal workflows or alert credentials."""
    actor_dirs = [REPO_ROOT / "apify_actor", REPO_ROOT / ".actor"]
    files = []
    for d in actor_dirs:
        files.extend([f for f in d.rglob("*") if f.is_file() and f.suffix in (".py", ".json")])

    personal_pattern = re.compile(
        r"(send_worker_run_alert|RESEND_API_KEY|EMAIL_TO|telegram|supabase|seen_jobs)",
        re.IGNORECASE,
    )

    violations = []
    for f in files:
        content = f.read_text(encoding="utf-8")
        matches = personal_pattern.findall(content)
        if matches:
            violations.append(f"{f.relative_to(REPO_ROOT)}: {matches}")

    assert not violations, f"Apify Actor contaminated with personal credentials or workflows: {violations}"
