"""
Core Service Layer for VisaLane Phase 10:
Internal Analytics, Cohort Retention, Rollup Engine, and Channel Attribution.
"""
from __future__ import annotations

import datetime
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict

from engine.api.analytics_models import (
    DailyTrendPoint,
    OverviewAnalyticsResponse,
    RetentionCohortRow,
    RetentionCohortResponse,
    ChannelBreakdownItem,
    ChannelsAnalyticsResponse,
    RevenuePlanBreakdown,
    RevenueAnalyticsResponse,
    ViralityAnalyticsResponse,
    RollupJobResult,
)

logger = logging.getLogger("visalane.analytics")

# ─────────────────────────────────────────────────────────────────────────────
# In-Memory Mock Stores for Offline Testing and Rollup Caching
# ─────────────────────────────────────────────────────────────────────────────

_ANALYTICS_MUTEX = threading.Lock()

# First-touch attribution captured per session_id:
# session_id -> { utm_source, utm_medium, utm_campaign, referrer, captured_at }
_MOCK_FIRST_TOUCH_STORE: Dict[str, Dict[str, Any]] = {}

# Permanent user signups ledger:
# user_id -> { user_id, email, acquisition_channel, created_at, session_id }
_MOCK_USER_SIGNUPS: Dict[str, Dict[str, Any]] = {}

# Pre-aggregated daily summaries:
# date_str (YYYY-MM-DD) -> dict of daily counts & channels
_MOCK_DAILY_ROLLUPS: Dict[str, Dict[str, Any]] = {}

# Pre-aggregated weekly retention cohorts:
# cohort_week (YYYY-Www) -> dict of cohort size and retention counts
_MOCK_COHORT_ROLLUPS: Dict[str, Dict[str, Any]] = {}

# Channel ad spend table (for CAC calculation):
# channel -> total spend USD
_MOCK_CHANNEL_SPEND: Dict[str, float] = {
    "paid_search": 1200.0,
    "social": 800.0,
    "direct": 0.0,
    "organic_search": 0.0,
    "referral": 0.0,
    "email": 150.0,
}


def clear_mock_analytics_stores() -> None:
    """Wipes in-memory analytics stores between test runs."""
    global _MOCK_FIRST_TOUCH_STORE, _MOCK_USER_SIGNUPS, _MOCK_DAILY_ROLLUPS, _MOCK_COHORT_ROLLUPS
    with _ANALYTICS_MUTEX:
        _MOCK_FIRST_TOUCH_STORE.clear()
        _MOCK_USER_SIGNUPS.clear()
        _MOCK_DAILY_ROLLUPS.clear()
        _MOCK_COHORT_ROLLUPS.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 1. First-Touch Channel Attribution Capture & Locking
# ─────────────────────────────────────────────────────────────────────────────

def resolve_acquisition_channel(
    utm_source: Optional[str] = None,
    utm_medium: Optional[str] = None,
    referrer: Optional[str] = None,
) -> str:
    """
    Resolves raw touch telemetry into a standardized acquisition channel.
    Rules:
    - Paid Search: source in (google, bing, duckduckgo) with medium in (cpc, ppc, paid, search)
    - Organic Search: search engine source with non-paid medium or search engine referrer
    - Social: source in (linkedin, twitter, x, reddit, facebook, instagram) or social referrer
    - Referral: source in (referral, invite, share) or match_report referrer
    - Email: source in (newsletter, email) or medium=email
    - Fallback: 'direct' (strictly guaranteed, never null/omitted)
    """
    src = (utm_source or "").strip().lower()
    med = (utm_medium or "").strip().lower()
    ref = (referrer or "").strip().lower()

    if src:
        if src in ("google", "bing", "yahoo", "duckduckgo"):
            if med in ("cpc", "ppc", "paid", "search"):
                return "paid_search"
            return "organic_search"
        if src in ("linkedin", "twitter", "x", "reddit", "facebook", "instagram", "tiktok", "youtube") or med == "social":
            return "social"
        if src in ("newsletter", "email") or med == "email":
            return "email"
        if src in ("referral", "invite", "share", "friend") or med == "referral":
            return "referral"
        return src

    if ref:
        if any(engine in ref for engine in ("google.", "bing.", "duckduckgo.", "search.yahoo")):
            return "organic_search"
        if any(soc in ref for soc in ("linkedin.", "t.co", "twitter.", "x.com", "reddit.", "facebook.")):
            return "social"
        if "visalane.com/match-report" in ref or "referral" in ref:
            return "referral"

    return "direct"


def capture_first_touch_attribution(
    session_id: str,
    utm_source: Optional[str] = None,
    utm_medium: Optional[str] = None,
    utm_campaign: Optional[str] = None,
    referrer: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Captures first-touch attribution on visitor session start.
    If session_id already exists, preserves original first-touch (never overwrites).
    """
    if not session_id:
        return {}

    with _ANALYTICS_MUTEX:
        existing = _MOCK_FIRST_TOUCH_STORE.get(session_id)
        if existing is not None:
            return existing

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        channel = resolve_acquisition_channel(utm_source=utm_source, utm_medium=utm_medium, referrer=referrer)
        record = {
            "session_id": session_id,
            "utm_source": utm_source,
            "utm_medium": utm_medium,
            "utm_campaign": utm_campaign,
            "referrer": referrer,
            "acquisition_channel": channel,
            "captured_at": now_iso,
        }
        _MOCK_FIRST_TOUCH_STORE[session_id] = record
        return record


def lock_user_acquisition_channel(
    user_id: str,
    session_id: Optional[str] = None,
    email: Optional[str] = None,
    explicit_channel: Optional[str] = None,
    created_at: Optional[str] = None,
) -> str:
    """
    Locks the user's permanent acquisition_channel upon account creation.
    First-touch rule: locked once and NEVER overwritten by subsequent interactions.
    Explicit fallback: 'direct'.
    """
    with _ANALYTICS_MUTEX:
        existing = _MOCK_USER_SIGNUPS.get(user_id)
        if existing is not None and existing.get("acquisition_channel"):
            return existing["acquisition_channel"]

        from engine.api.billing_service import _MOCK_USER_PROFILES
        prof = _MOCK_USER_PROFILES.get(user_id) or {}
        if prof.get("acquisition_channel"):
            channel = prof["acquisition_channel"]
            _MOCK_USER_SIGNUPS[user_id] = {
                "user_id": user_id,
                "email": email or prof.get("email"),
                "acquisition_channel": channel,
                "created_at": created_at or prof.get("created_at") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "session_id": session_id,
            }
            return channel

        # Resolve channel from explicit param, first-touch session, or fallback
        if explicit_channel:
            channel = resolve_acquisition_channel(utm_source=explicit_channel)
        elif session_id and session_id in _MOCK_FIRST_TOUCH_STORE:
            channel = _MOCK_FIRST_TOUCH_STORE[session_id].get("acquisition_channel") or "direct"
        else:
            channel = "direct"

        now_iso = created_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
        record = {
            "user_id": user_id,
            "email": email,
            "acquisition_channel": channel,
            "created_at": now_iso,
            "session_id": session_id,
        }
        _MOCK_USER_SIGNUPS[user_id] = record

        # Sync with user profile store if available
        prof["acquisition_channel"] = channel
        _MOCK_USER_PROFILES[user_id] = prof
        return channel


# ─────────────────────────────────────────────────────────────────────────────
# 2. Locked Activation Event Evaluator
# ─────────────────────────────────────────────────────────────────────────────

def is_user_or_session_activated(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    events: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """
    Strict Activation Definition:
    A candidate or session is 'Activated' if they:
    1. Set a job alert ('alert_created' event or active alert in alert store), OR
    2. Viewed 3+ distinct jobs ('job_viewed' or 'job_clicked' with >= 3 distinct job IDs).
    """
    from engine.api.alert_service import _MOCK_ALERTS_STORE
    from engine.api.jobs_routes import _MOCK_EVENTS_STORE

    # 1. Check Alert Creation
    if user_id:
        for a in _MOCK_ALERTS_STORE.values():
            if a.get("user_id") == user_id:
                return True
    if session_id:
        for a in _MOCK_ALERTS_STORE.values():
            if a.get("session_id") == session_id:
                return True

    all_evts = events if events is not None else _MOCK_EVENTS_STORE

    distinct_viewed_jobs: Set[str] = set()
    for e in all_evts:
        evt_uid = e.get("user_id")
        evt_sid = e.get("session_id")

        matches_target = False
        if user_id and evt_uid == user_id:
            matches_target = True
        elif session_id and evt_sid == session_id:
            matches_target = True

        if not matches_target:
            continue

        evt_type = str(e.get("event_type", "")).lower()

        # Alert event match
        if evt_type in ("alert_created", "job_alert_created"):
            return True

        # Job view match
        if evt_type in ("job_viewed", "job_clicked", "job_detail_view"):
            metadata = e.get("metadata") or {}
            job_id = metadata.get("job_id") or e.get("job_id")
            if job_id:
                distinct_viewed_jobs.add(str(job_id))
            else:
                # If no explicit job_id in metadata, count by session view index
                distinct_viewed_jobs.add(f"anon_view_{len(distinct_viewed_jobs)}")

            if len(distinct_viewed_jobs) >= 3:
                return True

    return len(distinct_viewed_jobs) >= 3


# ─────────────────────────────────────────────────────────────────────────────
# 3. Rollup Engine: Daily & Cohort Aggregation Runner
# ─────────────────────────────────────────────────────────────────────────────

def _parse_iso_date(date_str: str) -> Optional[datetime.date]:
    try:
        dt = datetime.datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        return dt.date()
    except Exception:
        return None


def run_analytics_rollups(
    target_date: Optional[str] = None,
    full_rebuild: bool = False,
) -> RollupJobResult:
    """
    Computes pre-aggregated daily summaries and weekly retention cohorts.
    Prevents raw table scan bottlenecks on dashboard read endpoints.
    """
    t0 = time.time()
    from engine.api.jobs_routes import _MOCK_EVENTS_STORE
    from engine.api.alert_service import _MOCK_NOTIFICATION_LOGS

    with _ANALYTICS_MUTEX:
        if full_rebuild:
            _MOCK_DAILY_ROLLUPS.clear()
            _MOCK_COHORT_ROLLUPS.clear()

        # Step A: Collect all events grouped by date
        daily_visitors: Dict[str, Set[str]] = defaultdict(set)
        daily_active_users: Dict[str, Set[str]] = defaultdict(set)
        daily_alert_sent: Dict[str, int] = defaultdict(int)
        daily_alert_clicked: Dict[str, int] = defaultdict(int)

        for evt in _MOCK_EVENTS_STORE:
            ts = evt.get("created_at")
            d = _parse_iso_date(ts) if ts else None
            if not d:
                continue
            d_str = d.isoformat()

            sid = evt.get("session_id")
            uid = evt.get("user_id")

            if sid:
                daily_visitors[d_str].add(sid)
            if uid:
                daily_active_users[d_str].add(uid)
            elif sid:
                daily_active_users[d_str].add(sid)

            etype = evt.get("event_type")
            if etype in ("alert_clicked", "alert_email_clicked"):
                daily_alert_clicked[d_str] += 1

        # Email notifications sent from Phase 7 logs
        for log in _MOCK_NOTIFICATION_LOGS:
            ts = log.get("sent_at")
            d = _parse_iso_date(ts) if ts else None
            if d:
                daily_alert_sent[d.isoformat()] += 1

        # Step B: Aggregate signups and activations by date & channel
        daily_signups: Dict[str, int] = defaultdict(int)
        daily_activations: Dict[str, int] = defaultdict(int)
        daily_signups_by_ch: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        daily_activations_by_ch: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # Track cohort memberships: cohort_week -> list of user signup records
        cohort_members: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for uid, user_rec in _MOCK_USER_SIGNUPS.items():
            ts = user_rec.get("created_at")
            d = _parse_iso_date(ts) if ts else None
            if not d:
                continue
            d_str = d.isoformat()
            ch = user_rec.get("acquisition_channel") or "direct"

            daily_signups[d_str] += 1
            daily_signups_by_ch[d_str][ch] += 1

            # Check activation
            is_act = is_user_or_session_activated(user_id=uid, session_id=user_rec.get("session_id"))
            if is_act:
                daily_activations[d_str] += 1
                daily_activations_by_ch[d_str][ch] += 1

            # Cohort weekly bucket (ISO calendar week, e.g. 2026-W32)
            year, week, _ = d.isocalendar()
            c_week = f"{year}-W{week:02d}"
            cohort_members[c_week].append({**user_rec, "signup_date": d, "is_activated": is_act})

        # Compile Daily Rollups
        all_dates = set(daily_visitors.keys()) | set(daily_signups.keys()) | set(daily_active_users.keys())
        if target_date:
            all_dates = {target_date}

        for d_str in all_dates:
            _MOCK_DAILY_ROLLUPS[d_str] = {
                "date": d_str,
                "visitors": len(daily_visitors[d_str]),
                "signups": daily_signups[d_str],
                "activations": daily_activations[d_str],
                "active_users": len(daily_active_users[d_str]),
                "signups_by_channel": dict(daily_signups_by_ch[d_str]),
                "activations_by_channel": dict(daily_activations_by_ch[d_str]),
                "alert_emails_sent": daily_alert_sent[d_str],
                "alert_emails_clicked": daily_alert_clicked[d_str],
            }

        # Step C: Compile Weekly Cohort Retention (W1, W4, W8)
        # Pre-index all user event activity dates for fast cohort lookups
        user_activity_dates: Dict[str, Set[datetime.date]] = defaultdict(set)
        for evt in _MOCK_EVENTS_STORE:
            uid = evt.get("user_id")
            ts = evt.get("created_at")
            d = _parse_iso_date(ts) if ts else None
            if uid and d:
                user_activity_dates[uid].add(d)

        for c_week, members in cohort_members.items():
            if not members:
                continue
            cohort_size = len(members)
            activated_count = sum(1 for m in members if m.get("is_activated"))
            min_date = min(m["signup_date"] for m in members)

            w1_count = 0
            w4_count = 0
            w8_count = 0

            for m in members:
                uid = m["user_id"]
                s_date = m["signup_date"]
                act_dates = user_activity_dates.get(uid, set())

                # W1 retention: active 7 to 13 days post-signup
                if any(7 <= (ad - s_date).days <= 13 for ad in act_dates):
                    w1_count += 1

                # W4 retention: active 28 to 34 days post-signup
                if any(28 <= (ad - s_date).days <= 34 for ad in act_dates):
                    w4_count += 1

                # W8 retention: active 56 to 62 days post-signup
                if any(56 <= (ad - s_date).days <= 62 for ad in act_dates):
                    w8_count += 1

            _MOCK_COHORT_ROLLUPS[c_week] = {
                "cohort_week": c_week,
                "cohort_start_date": min_date.isoformat(),
                "cohort_size": cohort_size,
                "activated_count": activated_count,
                "activation_rate_pct": round((activated_count / cohort_size) * 100.0, 2) if cohort_size else 0.0,
                "w1_retained_count": w1_count,
                "w1_retention_pct": round((w1_count / cohort_size) * 100.0, 2) if cohort_size else 0.0,
                "w4_retained_count": w4_count,
                "w4_retention_pct": round((w4_count / cohort_size) * 100.0, 2) if cohort_size else 0.0,
                "w8_retained_count": w8_count,
                "w8_retention_pct": round((w8_count / cohort_size) * 100.0, 2) if cohort_size else 0.0,
            }

    elapsed_ms = (time.time() - t0) * 1000.0
    return RollupJobResult(
        status="success",
        daily_rollups_computed=len(_MOCK_DAILY_ROLLUPS),
        cohort_rollups_computed=len(_MOCK_COHORT_ROLLUPS),
        execution_time_ms=round(elapsed_ms, 2),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Admin Analytics Query Handlers (Read from Rollups)
# ─────────────────────────────────────────────────────────────────────────────

def get_analytics_overview(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> OverviewAnalyticsResponse:
    """
    Overview dashboard metrics:
    - New visitors, new signups, activation rate, DAU/WAU/MAU, stickiness ratio, alert CTR.
    """
    now_dt = datetime.datetime.now(datetime.timezone.utc).date()
    end_d = _parse_iso_date(end_date) if end_date else now_dt
    start_d = _parse_iso_date(start_date) if start_date else (end_d - datetime.timedelta(days=30))

    # Auto-run rollups if empty
    if not _MOCK_DAILY_ROLLUPS:
        run_analytics_rollups()

    tot_visitors = 0
    tot_signups = 0
    tot_activations = 0
    tot_alerts_sent = 0
    tot_alerts_clicked = 0
    trends: List[DailyTrendPoint] = []

    # Daily aggregation over date window
    cur = start_d
    while cur <= end_d:
        d_str = cur.isoformat()
        r = _MOCK_DAILY_ROLLUPS.get(d_str, {})

        vis = r.get("visitors", 0)
        sig = r.get("signups", 0)
        act = r.get("activations", 0)
        au = r.get("active_users", 0)
        asent = r.get("alert_emails_sent", 0)
        aclick = r.get("alert_emails_clicked", 0)

        tot_visitors += vis
        tot_signups += sig
        tot_activations += act
        tot_alerts_sent += asent
        tot_alerts_clicked += aclick

        trends.append(DailyTrendPoint(
            date=d_str,
            visitors=vis,
            signups=sig,
            activations=act,
            active_users=au,
            alert_emails_sent=asent,
            alert_emails_clicked=aclick,
        ))
        cur += datetime.timedelta(days=1)

    # DAU, WAU, MAU calculation relative to end_d
    dau = _MOCK_DAILY_ROLLUPS.get(end_d.isoformat(), {}).get("active_users", 0)

    # WAU: distinct active users over past 7 days
    wau_users: Set[str] = set()
    for offset in range(7):
        target = (end_d - datetime.timedelta(days=offset)).isoformat()
        # Fallback to daily rollups active count or actual events
        wau_users.add(f"day_{target}_{_MOCK_DAILY_ROLLUPS.get(target, {}).get('active_users', 0)}")
    wau = sum(_MOCK_DAILY_ROLLUPS.get((end_d - datetime.timedelta(days=o)).isoformat(), {}).get("active_users", 0) for o in range(7))

    # MAU: distinct active users over past 30 days
    mau = sum(_MOCK_DAILY_ROLLUPS.get((end_d - datetime.timedelta(days=o)).isoformat(), {}).get("active_users", 0) for o in range(30))
    mau = max(mau, wau, 1) if (wau > 0 or mau > 0) else 0

    act_rate = round((tot_activations / tot_signups) * 100.0, 2) if tot_signups > 0 else (
        round((tot_activations / tot_visitors) * 100.0, 2) if tot_visitors > 0 else 0.0
    )
    stickiness = round(wau / mau, 3) if mau > 0 else 0.0
    alert_ctr = round((tot_alerts_clicked / tot_alerts_sent) * 100.0, 2) if tot_alerts_sent > 0 else 0.0

    return OverviewAnalyticsResponse(
        start_date=start_d.isoformat(),
        end_date=end_d.isoformat(),
        new_visitors=tot_visitors,
        new_signups=tot_signups,
        total_activations=tot_activations,
        activation_rate=act_rate,
        dau=dau,
        wau=wau,
        mau=mau,
        wau_mau_ratio=stickiness,
        alert_engagement_rate=alert_ctr,
        daily_trends=trends,
    )


def get_analytics_retention(weeks: int = 8) -> RetentionCohortResponse:
    """
    Returns weekly retention matrix: signup week x W1, W4, W8 retention %.
    """
    if not _MOCK_COHORT_ROLLUPS:
        run_analytics_rollups()

    sorted_cohorts = sorted(
        _MOCK_COHORT_ROLLUPS.values(),
        key=lambda c: c["cohort_week"],
        reverse=True,
    )[:weeks]

    rows = [RetentionCohortRow(**c) for c in sorted_cohorts]
    return RetentionCohortResponse(
        total_cohorts=len(rows),
        cohorts=rows,
    )


def get_analytics_channels(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> ChannelsAnalyticsResponse:
    """
    Channel attribution breakdown: signups, activation, retention, and CAC by channel.
    """
    now_dt = datetime.datetime.now(datetime.timezone.utc).date()
    end_d = _parse_iso_date(end_date) if end_date else now_dt
    start_d = _parse_iso_date(start_date) if start_date else (end_d - datetime.timedelta(days=30))

    if not _MOCK_DAILY_ROLLUPS:
        run_analytics_rollups()

    ch_visitors: Dict[str, int] = defaultdict(int)
    ch_signups: Dict[str, int] = defaultdict(int)
    ch_activations: Dict[str, int] = defaultdict(int)

    # Populate visitors from first-touch store
    for sess in _MOCK_FIRST_TOUCH_STORE.values():
        c = sess.get("acquisition_channel") or "direct"
        ts = sess.get("captured_at")
        d = _parse_iso_date(ts) if ts else None
        if d and start_d <= d <= end_d:
            ch_visitors[c] += 1

    # Populate signups & activations from daily rollups
    cur = start_d
    while cur <= end_d:
        d_str = cur.isoformat()
        r = _MOCK_DAILY_ROLLUPS.get(d_str, {})
        for ch, count in r.get("signups_by_channel", {}).items():
            ch_signups[ch] += count
        for ch, count in r.get("activations_by_channel", {}).items():
            ch_activations[ch] += count
        cur += datetime.timedelta(days=1)

    all_channels = sorted(list(set(list(ch_visitors.keys()) + list(ch_signups.keys()) + ["direct"])))

    channel_items: List[ChannelBreakdownItem] = []
    total_sig = 0
    top_channel = "direct"
    top_sig = -1

    for ch in all_channels:
        v = ch_visitors[ch]
        s = ch_signups[ch]
        a = ch_activations[ch]
        total_sig += s

        if s > top_sig:
            top_sig = s
            top_channel = ch

        conv_pct = round((s / v) * 100.0, 2) if v > 0 else 0.0
        act_pct = round((a / s) * 100.0, 2) if s > 0 else 0.0

        # Estimate W1 retention by looking up users attributed to this channel
        users_in_channel = [
            u for u in _MOCK_USER_SIGNUPS.values()
            if u.get("acquisition_channel") == ch
        ]
        w1_pct = 0.0
        if users_in_channel:
            # Check user retention against events
            from engine.api.jobs_routes import _MOCK_EVENTS_STORE
            retained_u = 0
            for u in users_in_channel:
                s_d = _parse_iso_date(u.get("created_at"))
                if not s_d:
                    continue
                has_w1 = any(
                    e.get("user_id") == u["user_id"] and _parse_iso_date(e.get("created_at")) and
                    7 <= (_parse_iso_date(e.get("created_at")) - s_d).days <= 13
                    for e in _MOCK_EVENTS_STORE
                )
                if has_w1:
                    retained_u += 1
            w1_pct = round((retained_u / len(users_in_channel)) * 100.0, 2)

        spend = _MOCK_CHANNEL_SPEND.get(ch, 0.0)
        cac = round(spend / s, 2) if s > 0 else 0.0

        channel_items.append(ChannelBreakdownItem(
            channel=ch,
            visitors=v,
            signups=s,
            signup_conversion_rate_pct=conv_pct,
            activations=a,
            activation_rate_pct=act_pct,
            w1_retention_pct=w1_pct,
            blended_cac=cac,
        ))

    return ChannelsAnalyticsResponse(
        start_date=start_d.isoformat(),
        end_date=end_d.isoformat(),
        total_signups=total_sig,
        top_performing_channel=top_channel,
        channels=channel_items,
    )


def get_analytics_revenue() -> RevenueAnalyticsResponse:
    """
    Revenue analytics sourced from Phase 6 Stripe subscriptions:
    - Candidate Plus: $19/mo
    - Employer Pro: $199/mo
    - Employer Featured: $99/mo
    """
    import engine.api.billing_service as bs

    plus_count = 0
    for prof in bs._MOCK_USER_PROFILES.values():
        plan = str(prof.get("subscription_plan", "")).lower()
        status = str(prof.get("subscription_status", "active")).lower()
        if plan in ("plus", "candidate_plus") and status in ("active", "trialing"):
            plus_count += 1

    pro_count = 0
    feat_count = 0
    for comp in bs._MOCK_COMPANY_BILLING.values():
        e_plan = str(comp.get("employer_plan", "")).lower()
        b_plan = str(comp.get("billing_plan", "")).lower()
        if e_plan in ("pro", "employer_pro") or b_plan in ("pro", "employer_pro"):
            pro_count += 1
        elif e_plan in ("featured", "employer_featured") or comp.get("featured_until"):
            feat_count += 1

    mrr_plus = plus_count * 19.0
    mrr_pro = pro_count * 199.0
    mrr_feat = feat_count * 99.0
    total_mrr = mrr_plus + mrr_pro + mrr_feat
    total_arr = total_mrr * 12.0
    total_subs = plus_count + pro_count + feat_count
    arpu = round(total_mrr / total_subs, 2) if total_subs > 0 else 0.0

    return RevenueAnalyticsResponse(
        current_mrr=round(total_mrr, 2),
        current_arr=round(total_arr, 2),
        active_subscribers=total_subs,
        arpu=arpu,
        subscribers_by_plan=RevenuePlanBreakdown(
            candidate_plus=plus_count,
            employer_pro=pro_count,
            employer_featured=feat_count,
        ),
        mrr_by_plan={
            "candidate_plus": round(mrr_plus, 2),
            "employer_pro": round(mrr_pro, 2),
            "employer_featured": round(mrr_feat, 2),
        },
    )


def get_analytics_virality() -> ViralityAnalyticsResponse:
    """
    K-factor and virality calculations based on Phase 3 referral events:
    - K = i * c
      where:
      i = invites / shares sent per sharer
      c = referral signups per share sent
      K = referral signups / unique sharers
    """
    from engine.api.jobs_routes import _MOCK_EVENTS_STORE

    shares_count = 0
    unique_sharers: Set[str] = set()
    referral_visits = 0

    for evt in _MOCK_EVENTS_STORE:
        etype = str(evt.get("event_type", "")).lower()
        uid = evt.get("user_id") or evt.get("session_id")
        meta = evt.get("metadata") or {}

        if etype in ("share_clicked", "share_generated", "match_report_shared"):
            shares_count += 1
            if uid:
                unique_sharers.add(uid)

        if etype in ("match_report_viewed", "page_view"):
            if meta.get("ref") or meta.get("utm_source") == "referral" or meta.get("token"):
                referral_visits += 1

    referral_signups = sum(
        1 for u in _MOCK_USER_SIGNUPS.values()
        if u.get("acquisition_channel") == "referral"
    )

    n_sharers = len(unique_sharers)
    invites_per_user = round(shares_count / n_sharers, 2) if n_sharers > 0 else 0.0
    conversion_rate = round(referral_signups / shares_count, 4) if shares_count > 0 else 0.0
    k_factor = round(invites_per_user * conversion_rate, 4) if shares_count > 0 else 0.0

    return ViralityAnalyticsResponse(
        total_shares_sent=shares_count,
        unique_sharers=n_sharers,
        invites_per_user=invites_per_user,
        referral_visits=referral_visits,
        referral_signups=referral_signups,
        conversion_rate_per_share=conversion_rate,
        k_factor=k_factor,
        is_viral=bool(k_factor >= 1.0),
    )
