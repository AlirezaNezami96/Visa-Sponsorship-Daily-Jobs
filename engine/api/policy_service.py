"""
Core Service Layer for VisaLane Phase 11:
AI Policy-Shock Detection and Warm Outreach Drafting with Zero Contact Persistence.
"""
from __future__ import annotations

import datetime
import logging
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import HTTPException

from engine.api.policy_models import (
    PolicyShockSignal,
    CompanyPolicyShockStatus,
    CompanyFilingRecord,
    OutreachDraftRequest,
    OutreachDraftResponse,
)

logger = logging.getLogger("visalane.policy")

# ─────────────────────────────────────────────────────────────────────────────
# Deliberately Set Policy-Shock Thresholds (Section 0 Decisions)
# ─────────────────────────────────────────────────────────────────────────────

# 1. Posting Velocity Signal Thresholds
MIN_HISTORICAL_POSTINGS = 10          # Companies with < 10 jobs lack baseline validity
MIN_HISTORY_SPAN_DAYS = 60            # Minimum timeline span to establish cadence
MIN_BASELINE_MONTHLY_JOBS = 2.0       # Minimum baseline velocity to detect drops
VELOCITY_DROP_THRESHOLD_PCT = 75.0    # 75.0% drop required to flag

# 2. Filing Recency Signal Thresholds
MIN_HISTORICAL_FILINGS = 2            # Minimum filings to establish historical cadence
MAX_HISTORICAL_FILING_INTERVAL = 365  # Must historically file at least once every 12 months
FILING_STALENESS_THRESHOLD_DAYS = 548 # 18 months without a filing triggers flag

# 3. Confidence Score Penalty
SCORE_PENALTY_PER_SIGNAL = -15        # Fixed, consistent downward adjustment

# In-memory mock store for filings and policy status
_POLICY_MUTEX = threading.Lock()
_MOCK_COMPANY_FILINGS: Dict[str, List[Dict[str, Any]]] = {}
_MOCK_COMPANY_POLICY_STATUS: Dict[str, Dict[str, Any]] = {}


def clear_mock_policy_stores() -> None:
    """Wipes in-memory policy and filing stores between test runs."""
    with _POLICY_MUTEX:
        _MOCK_COMPANY_FILINGS.clear()
        _MOCK_COMPANY_POLICY_STATUS.clear()


def set_mock_company_filings(company_slug: str, filings: List[Dict[str, Any]]) -> None:
    """Helper to seed historical visa filings (LCA/PERM) for tests."""
    with _POLICY_MUTEX:
        _MOCK_COMPANY_FILINGS[company_slug.strip().lower()] = filings


def _parse_date(d_val: Any) -> Optional[datetime.date]:
    if isinstance(d_val, datetime.date):
        return d_val
    if not d_val:
        return None
    try:
        return datetime.datetime.fromisoformat(str(d_val).replace("Z", "+00:00")).date()
    except Exception:
        try:
            return datetime.datetime.strptime(str(d_val)[:10], "%Y-%m-%d").date()
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Posting-Velocity Signal Evaluator
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_posting_velocity_signal(
    company_slug: str,
    jobs_history: Optional[List[Dict[str, Any]]] = None,
    reference_date: Optional[datetime.date] = None,
) -> PolicyShockSignal:
    """
    Evaluates employer posting-velocity drop:
    - Rejects companies with insufficient posting history (< 10 jobs or < 60 days).
    - Compares baseline 90-day volume vs trailing 30-day volume.
    - Flags if drop >= 75.0% (exact boundary enforced).
    """
    ref_d = reference_date or datetime.datetime.now(datetime.timezone.utc).date()

    # Step A: Collect jobs for this company
    jobs = jobs_history
    if jobs is None:
        from engine.api.jobs_routes import _MOCK_JOBS_STORE
        slug_norm = company_slug.strip().lower()
        jobs = [
            j for j in _MOCK_JOBS_STORE
            if str(j.get("company_slug", "")).lower() == slug_norm
            or str(j.get("company", "")).lower() == slug_norm.replace("-", " ")
        ]

    # Step B: Check Insufficient History Condition
    if len(jobs) < MIN_HISTORICAL_POSTINGS:
        return PolicyShockSignal(
            signal_type="posting_velocity",
            flagged=False,
            status="insufficient_history",
            confidence_impact=0,
            reason_detail=None,
            metrics={"total_jobs": len(jobs), "required_minimum": MIN_HISTORICAL_POSTINGS},
        )

    # Check date span
    dates: List[datetime.date] = []
    for j in jobs:
        d = _parse_date(j.get("date_posted") or j.get("created_at"))
        if d:
            dates.append(d)

    if not dates or (max(dates) - min(dates)).days < MIN_HISTORY_SPAN_DAYS:
        return PolicyShockSignal(
            signal_type="posting_velocity",
            flagged=False,
            status="insufficient_history",
            confidence_impact=0,
            reason_detail=None,
            metrics={"date_span_days": (max(dates) - min(dates)).days if dates else 0, "min_span_required": MIN_HISTORY_SPAN_DAYS},
        )

    # Step C: Window Calculation
    # Recent Window: [ref_d - 30 days, ref_d]
    # Baseline Window: [ref_d - 120 days, ref_d - 30 days] (90 days baseline period)
    recent_cutoff = ref_d - datetime.timedelta(days=30)
    baseline_cutoff = ref_d - datetime.timedelta(days=120)

    recent_jobs = [d for d in dates if recent_cutoff <= d <= ref_d]
    baseline_jobs = [d for d in dates if baseline_cutoff <= d < recent_cutoff]

    v_recent = float(len(recent_jobs))
    v_baseline = (float(len(baseline_jobs)) / 90.0) * 30.0  # Normalized to monthly volume

    if v_baseline < MIN_BASELINE_MONTHLY_JOBS:
        return PolicyShockSignal(
            signal_type="posting_velocity",
            flagged=False,
            status="insufficient_baseline_volume",
            confidence_impact=0,
            reason_detail=None,
            metrics={"baseline_monthly": round(v_baseline, 2), "recent_monthly": v_recent},
        )

    # Compute drop percentage: (baseline - recent) / baseline * 100
    drop_pct = ((v_baseline - v_recent) / v_baseline) * 100.0
    drop_pct_rounded = round(drop_pct, 2)

    metrics = {
        "baseline_monthly_volume": round(v_baseline, 1),
        "recent_monthly_volume": round(v_recent, 1),
        "drop_percentage": drop_pct_rounded,
        "threshold_percentage": VELOCITY_DROP_THRESHOLD_PCT,
    }

    # Strict Boundary Check: >= 75.0%
    if drop_pct >= VELOCITY_DROP_THRESHOLD_PCT:
        return PolicyShockSignal(
            signal_type="posting_velocity",
            flagged=True,
            status="shock_flagged",
            confidence_impact=SCORE_PENALTY_PER_SIGNAL,
            reason_detail=(
                f"Posting volume dropped by {drop_pct_rounded:.1f}% "
                f"(from ~{v_baseline:.1f}/month baseline to {v_recent:.1f}/month over the trailing 30 days)."
            ),
            metrics=metrics,
        )

    return PolicyShockSignal(
        signal_type="posting_velocity",
        flagged=False,
        status="normal",
        confidence_impact=0,
        reason_detail=None,
        metrics=metrics,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Filing-Recency Signal Evaluator
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_filing_recency_signal(
    company_slug: str,
    filings_history: Optional[List[Dict[str, Any]]] = None,
    reference_date: Optional[datetime.date] = None,
) -> PolicyShockSignal:
    """
    Evaluates employer government-filing (LCA/PERM) staleness:
    - Flags when most recent filing is >= 548 days (18 months) old for a company that
      previously filed on an established cadence (avg gap <= 365 days).
    """
    ref_d = reference_date or datetime.datetime.now(datetime.timezone.utc).date()

    filings = filings_history
    if filings is None:
        filings = _MOCK_COMPANY_FILINGS.get(company_slug.strip().lower(), [])

    if len(filings) < MIN_HISTORICAL_FILINGS:
        return PolicyShockSignal(
            signal_type="filing_recency",
            flagged=False,
            status="no_filing_history",
            confidence_impact=0,
            reason_detail=None,
            metrics={"filing_count": len(filings), "min_required": MIN_HISTORICAL_FILINGS},
        )

    # Sort filings chronologically
    sorted_filings: List[Tuple[datetime.date, Dict[str, Any]]] = []
    for f in filings:
        d = _parse_date(f.get("filing_date") or f.get("certified_at"))
        if d:
            sorted_filings.append((d, f))

    sorted_filings.sort(key=lambda x: x[0])
    if len(sorted_filings) < MIN_HISTORICAL_FILINGS:
        return PolicyShockSignal(
            signal_type="filing_recency",
            flagged=False,
            status="no_filing_history",
            confidence_impact=0,
            metrics={"valid_dated_filings": len(sorted_filings)},
        )

    # Calculate historical cadence between consecutive filings
    intervals = [
        (sorted_filings[i][0] - sorted_filings[i - 1][0]).days
        for i in range(1, len(sorted_filings))
    ]
    avg_interval = float(sum(intervals)) / float(len(intervals))

    # If company historically filed irregularly (> 365 days gap), staleness cannot be confidently inferred
    if avg_interval > MAX_HISTORICAL_FILING_INTERVAL:
        return PolicyShockSignal(
            signal_type="filing_recency",
            flagged=False,
            status="irregular_cadence",
            confidence_impact=0,
            reason_detail=None,
            metrics={"avg_interval_days": round(avg_interval, 1), "max_allowed_cadence": MAX_HISTORICAL_FILING_INTERVAL},
        )

    latest_filing_date = sorted_filings[-1][0]
    days_since_filing = (ref_d - latest_filing_date).days

    metrics = {
        "latest_filing_date": latest_filing_date.isoformat(),
        "days_since_last_filing": days_since_filing,
        "historical_avg_cadence_days": round(avg_interval, 1),
        "staleness_threshold_days": FILING_STALENESS_THRESHOLD_DAYS,
    }

    # Strict Boundary Check: >= 548 days
    if days_since_filing >= FILING_STALENESS_THRESHOLD_DAYS:
        return PolicyShockSignal(
            signal_type="filing_recency",
            flagged=True,
            status="shock_flagged",
            confidence_impact=SCORE_PENALTY_PER_SIGNAL,
            reason_detail=(
                f"Government visa filing cadence lapsed: last recorded filing was {days_since_filing} days ago "
                f"(baseline filing cadence was every {int(avg_interval)} days)."
            ),
            metrics=metrics,
        )

    return PolicyShockSignal(
        signal_type="filing_recency",
        flagged=False,
        status="normal",
        confidence_impact=0,
        reason_detail=None,
        metrics=metrics,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Integration: Confidence Score Adjustment & Phase 7 Policy Alerts
# ─────────────────────────────────────────────────────────────────────────────

def trigger_company_policy_alert(
    company_name: str,
    company_slug: str,
    update_detail: str,
) -> int:
    """
    Triggers Phase 7 policy-alert email to candidates following that company.
    Enforces transactional consent classification.
    """
    from engine.api.alert_service import (
        _MOCK_ALERTS_STORE,
        _render_policy_alert_email,
        dispatch_email_notification,
    )

    slug_norm = company_slug.strip().lower()
    name_norm = company_name.strip().lower()

    # Find candidates with alerts configured for this company
    dispatched_count = 0
    notified_emails: Set[str] = set()

    for alert in _MOCK_ALERTS_STORE.values():
        if not alert.get("is_active"):
            continue

        email = alert.get("email")
        if not email or email in notified_emails:
            continue

        criteria = alert.get("filter_criteria") or {}
        kw = str(criteria.get("keyword") or "").strip().lower()
        companies_list = [c.strip().lower() for c in (criteria.get("companies") or [])]

        matches_company = (
            slug_norm in companies_list
            or name_norm in companies_list
            or slug_norm in kw
            or name_norm in kw
            or criteria.get("company_slug") == slug_norm
        )

        if matches_company:
            subject, html_content = _render_policy_alert_email(
                email=email,
                company_name=company_name,
                update_detail=update_detail,
            )
            sent = dispatch_email_notification(
                to_email=email,
                subject=subject,
                html_content=html_content,
                consent_classification="transactional",
            )
            if sent:
                notified_emails.add(email)
                dispatched_count += 1
                from engine.api.alert_service import _MOCK_NOTIFICATION_LOGS
                _MOCK_NOTIFICATION_LOGS.append({
                    "type": "company_policy_alert",
                    "company_slug": slug_norm,
                    "to_email": email,
                    "subject": subject,
                    "sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "consent_classification": "transactional",
                })

    logger.info("Triggered %d policy alert email(s) for company '%s'", dispatched_count, company_name)
    return dispatched_count


def run_company_policy_shock_check(
    company_slug: str,
    company_name: Optional[str] = None,
    base_confidence_score: int = 85,
    jobs_history: Optional[List[Dict[str, Any]]] = None,
    filings_history: Optional[List[Dict[str, Any]]] = None,
    reference_date: Optional[datetime.date] = None,
    trigger_alerts: bool = True,
) -> CompanyPolicyShockStatus:
    """
    Evaluates both policy-shock signals, applies score adjustments, updates confidence factors,
    and optionally dispatches Phase 7 policy alerts if any shock flag fired.
    """
    slug_norm = company_slug.strip().lower()
    comp_name = company_name or slug_norm.replace("-", " ").title()

    sig_velocity = evaluate_posting_velocity_signal(
        company_slug=slug_norm,
        jobs_history=jobs_history,
        reference_date=reference_date,
    )
    sig_filing = evaluate_filing_recency_signal(
        company_slug=slug_norm,
        filings_history=filings_history,
        reference_date=reference_date,
    )

    signals = [sig_velocity, sig_filing]
    total_penalty = sum(s.confidence_impact for s in signals)
    adjusted_score = max(0, min(100, base_confidence_score + total_penalty))

    factors: List[Dict[str, str]] = []
    reasons_for_alert: List[str] = []

    for s in signals:
        if s.flagged and s.reason_detail:
            factors.append({
                "label": f"Policy Shock: {s.signal_type.replace('_', ' ').title()}",
                "detail": s.reason_detail,
            })
            reasons_for_alert.append(s.reason_detail)

    # Trigger Phase 7 transactional policy alert email if flags fired
    alerts_count = 0
    if reasons_for_alert and trigger_alerts:
        combined_reason = " | ".join(reasons_for_alert)
        alerts_count = trigger_company_policy_alert(
            company_name=comp_name,
            company_slug=slug_norm,
            update_detail=combined_reason,
        )

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    status = CompanyPolicyShockStatus(
        company_slug=slug_norm,
        company_name=comp_name,
        base_confidence_score=base_confidence_score,
        adjusted_confidence_score=adjusted_score,
        total_penalty=total_penalty,
        signals=signals,
        confidence_factors=factors,
        alerts_triggered=alerts_count,
        evaluated_at=now_iso,
    )

    with _POLICY_MUTEX:
        _MOCK_COMPANY_POLICY_STATUS[slug_norm] = status.model_dump()

    return status


# ─────────────────────────────────────────────────────────────────────────────
# 4. Warm Outreach Drafting with Zero Contact Persistence
# ─────────────────────────────────────────────────────────────────────────────

def generate_outreach_draft(request: OutreachDraftRequest) -> OutreachDraftResponse:
    """
    Generates personalized warm outreach draft referencing real company and role data.
    Entitlement-gated via Phase 6 AI quota mechanism.
    
    STRICT PRIVACY BOUNDARY (Escalated Gate):
    - Strictly ephemeral: contact_name, contact_role, and contact_linkedin_url are used
      ONLY to synthesize the draft string and are NEVER saved or cached anywhere.
    - Quota tracking logs only that an outreach draft was generated by user_id.
    """
    from engine.api.billing_service import (
        check_ai_generation_entitlement,
        record_ai_generation_usage,
    )

    # 1. Enforce Entitlement Gate (Phase 6 mechanism reuse)
    can_gen, prompt_payload = check_ai_generation_entitlement(request.user_id)
    if not can_gen:
        raise HTTPException(status_code=403, detail=prompt_payload)

    # 2. Record Quota Usage (Zero Contact Data Logged)
    record_ai_generation_usage(request.user_id)

    # 3. Retrieve Real Company and Role Context
    from engine.api.jobs_routes import _MOCK_JOBS_STORE
    slug_norm = request.company_id.strip().lower()

    target_job: Optional[Dict[str, Any]] = None
    for j in _MOCK_JOBS_STORE:
        if j.get("id") == request.target_job_id or j.get("slug") == request.target_job_id:
            target_job = j
            break

    job_title = target_job.get("title", "Software Engineer") if target_job else "Target Role"
    company_name = (
        target_job.get("company") if target_job else request.company_id.replace("-", " ").title()
    )

    # Retrieve real confidence posture
    conf_score = target_job.get("confidence_score", 85) if target_job else 85
    visas = target_job.get("visa_types_supported", ["H-1B"]) if target_job else ["H-1B"]
    visa_str = ", ".join(visas)

    # 4. Synthesize Personalized Outreach Message (Ephemeral Contact Binding)
    salutation = f"Hi {request.contact_name}," if request.contact_name else "Hello,"
    contact_ref = f" in your role as {request.contact_role}" if request.contact_role else ""

    candidate_pitch = ""
    if request.candidate_notes:
        candidate_pitch = f"\n\nContext on my background:\n{request.candidate_notes.strip()}\n"

    sponsorship_highlight = (
        f"Verified VisaLane Sponsorship Confidence: {conf_score}/100 (Supporting {visa_str})"
    )

    draft_text = (
        f"{salutation}\n\n"
        f"I hope you're having a productive week. I am reaching out{contact_ref} regarding the "
        f"{job_title} opening at {company_name}.\n\n"
        f"I've been closely following {company_name}'s technical growth and commitment to hiring global engineering talent "
        f"({sponsorship_highlight}). "
        f"My background aligns closely with the technical challenges your team is currently solving.{candidate_pitch}\n"
        f"I would welcome the opportunity to connect for a brief 10-minute introductory conversation to learn more about "
        f"the team's roadmap and share how my domain experience can add immediate value.\n\n"
        f"Best regards,\n[Your Name]\n[Your Portfolio / LinkedIn]"
    )

    # 5. Audit Check: Log only operation success WITHOUT contact personal data
    logger.info(
        "Successfully generated warm outreach draft for user=%s, company=%s, job=%s (ephemeral)",
        request.user_id or "anon",
        company_name,
        request.target_job_id,
    )

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return OutreachDraftResponse(
        draft_text=draft_text,
        company_name=company_name,
        target_job_title=job_title,
        sponsorship_highlight=sponsorship_highlight,
        generated_at=now_iso,
    )
