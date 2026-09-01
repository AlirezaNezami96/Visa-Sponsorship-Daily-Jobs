"""Tests for the Independent, Platform-Native Social Posting Engine.

Validates:
1. Independent generation across all 7 platforms (meaningfully distinct copy, structure, tone, emoji sets).
2. Content-tier routing boundaries (DEV.to article only, X single job, Telegram batched).
3. Randomized jittered scheduling.
4. Cross-platform staggering queue (10-90 min delays for same job across different platforms).
5. Daily budget tracking and quota hard stops.
6. Per-platform, per-job deduplication.
7. HTTP 429 Retry-After header and body extraction.
8. Constraint validation (X <= 260 chars, Bluesky <= 300 chars / 3000 bytes, Mastodon <= 500 chars).
"""
from __future__ import annotations

import datetime
import json
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any

import pytest

from job_radar.social.adapters import (
    extract_emojis,
    get_adapter,
)
from job_radar.social.error_taxonomy import classify_http_error
from job_radar.social.scheduler import (
    CrossPlatformStaggerQueue,
    DailyBudgetTracker,
    PlatformDeduplicator,
    next_post_time,
)
from job_radar.social.tier_router import RoutingError, validate_tier_routing


@pytest.fixture
def sample_job() -> dict[str, Any]:
    return {
        "id": "job_test_uuid_101",
        "job_db_id": "job_test_uuid_101",
        "title": "Senior Distributed Systems Engineer",
        "company": "Acme Cloud Technologies",
        "location": "Berlin, Germany",
        "city": "Berlin",
        "country": "Germany",
        "country_code": "DE",
        "visa_types": ["EU Blue Card", "German Skilled Worker"],
        "visa_sponsorship_confidence": 95,
        "visa_sponsorship_verified": True,
        "salary_min": 85000,
        "salary_max": 110000,
        "salary_currency": "EUR",
        "salary_raw": "€85,000 - €110,000",
        "employment_type": "Full-time",
        "work_mode": "Hybrid",
        "apply_url": "https://visalane.app/apply/acme-101",
        "short_link": "visalane.app/j/acme101",
        "skills": ["Go", "Kubernetes", "gRPC", "Distributed Systems"],
        "summary": "Build high-throughput global edge gateways with verified EU Blue Card visa sponsorship.",
    }


# -----------------------------------------------------------------------------
# 1. Independent Generation Test (All 7 Platforms)
# -----------------------------------------------------------------------------
def test_independent_generation_all_platforms(sample_job: dict[str, Any]):
    """Assert all 7 platforms generate distinct, platform-native copy from the same job."""
    outputs: dict[str, Any] = {}

    # 1. Telegram
    tg_adapter = get_adapter("telegram")
    tg_text = tg_adapter.generate_content([sample_job])
    assert isinstance(tg_text, str)
    outputs["telegram"] = tg_text
    assert "🆕" in tg_text
    assert "Acme Cloud Technologies" in tg_text
    assert "📍 Berlin, Germany" in tg_text
    assert "🛂" in tg_text
    assert len(tg_text) < 3800

    # 2. Discord
    discord_adapter = get_adapter("discord")
    discord_embed = discord_adapter.generate_content(sample_job)
    assert isinstance(discord_embed, dict)
    outputs["discord"] = discord_embed
    assert "title" in discord_embed
    assert "fields" in discord_embed
    assert "🟢" in discord_embed["fields"]["confidence"]
    assert "🌍" in discord_embed["fields"]["location"]
    assert "💰" in discord_embed["fields"]["salary"]

    # 3. X (Twitter)
    x_adapter = get_adapter("x")
    x_text = x_adapter.generate_content(sample_job)
    assert isinstance(x_text, str)
    outputs["x"] = x_text
    assert len(x_text) <= 260
    assert len(extract_emojis(x_text)) <= 2
    assert "link in bio" in x_text
    assert "http://" not in x_text and "https://" not in x_text  # No raw URLs on X

    # 4. LinkedIn
    li_adapter = get_adapter("linkedin")
    li_text = li_adapter.generate_content(sample_job)
    assert isinstance(li_text, str)
    outputs["linkedin"] = li_text
    assert len(li_text) >= 150
    assert len(extract_emojis(li_text)) <= 3
    assert "📍" in li_text
    assert "✅" in li_text
    assert "https://visalane.app" in li_text

    # 5. Bluesky
    bsky_adapter = get_adapter("bluesky")
    bsky_text = bsky_adapter.generate_content(sample_job, short_link="visalane.app/j/acme101")
    assert isinstance(bsky_text, str)
    outputs["bluesky"] = bsky_text
    assert len(bsky_text) <= 300
    assert len(bsky_text.encode("utf-8")) <= 3000
    assert len(extract_emojis(bsky_text)) <= 2
    assert "visalane.app/j/acme101" in bsky_text

    # 6. Mastodon
    masto_adapter = get_adapter("mastodon")
    masto_text = masto_adapter.generate_content(sample_job)
    assert isinstance(masto_text, str)
    outputs["mastodon"] = masto_text
    assert len(masto_text) <= 500
    assert len(extract_emojis(masto_text)) <= 2
    assert "#VisaSponsorship" in masto_text or "#TechJobs" in masto_text

    # 7. DEV.to
    devto_adapter = get_adapter("devto")
    devto_article = devto_adapter.generate_content(
        sample_job,
        topic="Germany Tech Visa Sponsorship Surge: 2026 Analysis",
        stats_block="Over 1,200 verified EU Blue Card positions added this quarter.",
    )
    assert isinstance(devto_article, str)
    outputs["devto"] = devto_article
    assert "---" in devto_article
    assert "title: Germany Tech Visa" in devto_article
    assert "tags:" in devto_article
    assert len(devto_article.split()) >= 40


    # Cross-Platform Diversity Check:
    # Ensure text outputs across all platforms are completely distinct
    text_outputs = [
        tg_text,
        json.dumps(discord_embed),
        x_text,
        li_text,
        bsky_text,
        masto_text,
        devto_article,
    ]
    unique_set = set(text_outputs)
    assert len(unique_set) == 7, "Each platform must produce uniquely tailored text!"


# -----------------------------------------------------------------------------
# 2. Content-Tier Routing Validation
# -----------------------------------------------------------------------------
def test_content_tier_routing(sample_job: dict[str, Any]):
    """Validate tier routing rules across Tier 1, 2/3, and Tier 4 platforms."""
    # DEV.to (Tier 4) MUST reject raw single jobs or batch dumps
    is_valid, reason = validate_tier_routing("devto", "single_job", [sample_job])
    assert is_valid is False
    assert "Tier 4" in reason

    is_valid, _ = validate_tier_routing("devto", "batch_jobs", [sample_job, sample_job])
    assert is_valid is False

    with pytest.raises(RoutingError):
        validate_tier_routing("devto", "single_job", [sample_job], raise_on_error=True)

    # DEV.to MUST accept articles
    is_valid, _ = validate_tier_routing("devto", "article")
    assert is_valid is True

    # Telegram (Tier 1) accepts batches
    is_valid, _ = validate_tier_routing("telegram", "batch_jobs", [sample_job, sample_job])
    assert is_valid is True

    # X (Tier 2) rejects multi-job batch dumps
    is_valid, reason = validate_tier_routing("x", "batch_jobs", [sample_job, sample_job])
    assert is_valid is False
    assert "multi-job dumps" in reason

    # X (Tier 2) accepts single curated jobs
    is_valid, _ = validate_tier_routing("x", "single_job", [sample_job])
    assert is_valid is True


# -----------------------------------------------------------------------------
# 3. Jitter Scheduler Tests
# -----------------------------------------------------------------------------
def test_jittered_scheduler():
    """Verify that next_post_time applies non-zero randomized jitter within bounds."""
    base = datetime.datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
    interval = 20.0
    jitter_pct = 25.0

    times = [next_post_time(interval, jitter_pct, base_time=base) for _ in range(50)]
    delays_min = [(t - base).total_seconds() / 60.0 for t in times]

    # Bounds: 20 min ± 25% => [15.0, 25.0] minutes
    for d in delays_min:
        assert 15.0 <= d <= 25.0

    # Ensure delays are randomized, not constant
    assert len(set(delays_min)) > 10


# -----------------------------------------------------------------------------
# 4. Cross-Platform Staggering Queue Tests
# -----------------------------------------------------------------------------
def test_cross_platform_stagger_queue(tmp_path: Path):
    """Verify 10-90 min cross-platform delay when a job is posted on one platform."""
    queue_file = tmp_path / "stagger_queue.json"
    queue = CrossPlatformStaggerQueue(persistence_path=queue_file)

    job_id = "job_456"
    now = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)

    # Initially eligible on all platforms
    assert queue.is_job_eligible("x", job_id, current_time=now) is True
    assert queue.is_job_eligible("linkedin", job_id, current_time=now) is True

    # Post on Telegram
    queue.record_job_posted("telegram", job_id, post_time=now, min_stagger_min=20.0, max_stagger_min=60.0)

    # Immediately after, other platforms are staggered
    assert queue.is_job_eligible("x", job_id, current_time=now) is False
    assert queue.is_job_eligible("linkedin", job_id, current_time=now) is False

    # After 70 minutes, all platforms become eligible
    future = now + timedelta(minutes=70)
    assert queue.is_job_eligible("x", job_id, current_time=future) is True
    assert queue.is_job_eligible("linkedin", job_id, current_time=future) is True


# -----------------------------------------------------------------------------
# 5. Daily Budget Hard Stop Tests
# -----------------------------------------------------------------------------
def test_daily_budget_tracker_hard_stop(tmp_path: Path):
    """Verify daily quotas (e.g. X: 4/day, LinkedIn: 2/day) are strictly enforced."""
    budget_file = tmp_path / "budgets.json"
    tracker = DailyBudgetTracker(persistence_path=budget_file)

    # X has max 4 posts per day
    assert tracker.can_post("x") is True
    assert tracker.remaining_budget("x") == 4

    tracker.record_post("x")
    tracker.record_post("x")
    tracker.record_post("x")
    assert tracker.remaining_budget("x") == 1
    assert tracker.can_post("x") is True

    tracker.record_post("x")  # 4th post
    assert tracker.remaining_budget("x") == 0
    assert tracker.can_post("x") is False  # Hard stop reached


# -----------------------------------------------------------------------------
# 6. Deduplication Tracking Tests
# -----------------------------------------------------------------------------
def test_platform_deduplicator(tmp_path: Path):
    """Verify (platform, job_id) pairs cannot be reposted on the same platform."""
    dedup_file = tmp_path / "dedup.json"
    dedup = PlatformDeduplicator(persistence_path=dedup_file)

    assert dedup.is_posted("linkedin", "job_789") is False
    dedup.mark_posted("linkedin", "job_789")

    # Repost on LinkedIn is blocked
    assert dedup.is_posted("linkedin", "job_789") is True

    # Posting the same job on Bluesky or Mastodon is allowed
    assert dedup.is_posted("bluesky", "job_789") is False
    assert dedup.is_posted("mastodon", "job_789") is False


# -----------------------------------------------------------------------------
# 7. Rate-Limit Backoff Header Parsing
# -----------------------------------------------------------------------------
def test_rate_limit_backoff_header_parsing():
    """Verify HTTP Retry-After headers and JSON parameters are accurately extracted."""
    # Standard header
    retryable, permanent, delay = classify_http_error(429, headers={"Retry-After": "42"})
    assert retryable is True
    assert permanent is False
    assert delay == 42.0

    # Telegram JSON body
    telegram_json = '{"ok": false, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 85}}'
    retryable, permanent, delay = classify_http_error(429, response_text=telegram_json)
    assert retryable is True
    assert delay == 85.0
