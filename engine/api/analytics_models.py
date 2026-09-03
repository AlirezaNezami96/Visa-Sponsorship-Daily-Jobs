"""
Pydantic data models for VisaLane Phase 10:
Internal Analytics, Cohort Retention, and Channel Attribution Dashboard.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DailyTrendPoint(BaseModel):
    """Single day aggregate metrics point."""
    date: str = Field(..., description="ISO Date (YYYY-MM-DD)")
    visitors: int = 0
    signups: int = 0
    activations: int = 0
    active_users: int = 0
    alert_emails_sent: int = 0
    alert_emails_clicked: int = 0


class OverviewAnalyticsResponse(BaseModel):
    """Summary overview KPIs for the selected date window."""
    start_date: str
    end_date: str
    new_visitors: int = 0
    new_signups: int = 0
    total_activations: int = 0
    activation_rate: float = Field(0.0, description="Activation rate percentage (0-100%)")
    dau: int = Field(0, description="Daily Active Users on end_date")
    wau: int = Field(0, description="Weekly Active Users (past 7 days)")
    mau: int = Field(0, description="Monthly Active Users (past 30 days)")
    wau_mau_ratio: float = Field(0.0, description="User stickiness ratio (WAU / MAU)")
    alert_engagement_rate: float = Field(0.0, description="Alert digest click rate percentage")
    daily_trends: List[DailyTrendPoint] = Field(default_factory=list)


class RetentionCohortRow(BaseModel):
    """Weekly cohort row tracking W1, W4, and W8 retention percentages."""
    cohort_week: str = Field(..., description="Cohort identifier (e.g., '2026-W32')")
    cohort_start_date: str = Field(..., description="Start date of the cohort week (YYYY-MM-DD)")
    cohort_size: int = Field(0, description="Number of users who signed up in this cohort week")
    activated_count: int = 0
    activation_rate_pct: float = 0.0
    w1_retained_count: int = 0
    w1_retention_pct: float = 0.0
    w4_retained_count: int = 0
    w4_retention_pct: float = 0.0
    w8_retained_count: int = 0
    w8_retention_pct: float = 0.0


class RetentionCohortResponse(BaseModel):
    """Retention matrix across all monitored weekly signup cohorts."""
    total_cohorts: int
    cohorts: List[RetentionCohortRow] = Field(default_factory=list)


class ChannelBreakdownItem(BaseModel):
    """Per-channel acquisition, activation, and unit economics metrics."""
    channel: str = Field(..., description="Acquisition channel name (e.g., 'direct', 'organic_search', 'social')")
    visitors: int = 0
    signups: int = 0
    signup_conversion_rate_pct: float = 0.0
    activations: int = 0
    activation_rate_pct: float = 0.0
    w1_retention_pct: float = 0.0
    blended_cac: float = Field(0.0, description="Estimated customer acquisition cost in USD")


class ChannelsAnalyticsResponse(BaseModel):
    """First-touch acquisition channels breakdown."""
    start_date: str
    end_date: str
    total_signups: int = 0
    top_performing_channel: str = "direct"
    channels: List[ChannelBreakdownItem] = Field(default_factory=list)


class RevenuePlanBreakdown(BaseModel):
    """Subscriber count breakdown by pricing plan tier."""
    candidate_plus: int = 0
    employer_pro: int = 0
    employer_featured: int = 0


class RevenueAnalyticsResponse(BaseModel):
    """Real-time MRR and ARR revenue analytics sourced from Stripe."""
    current_mrr: float = Field(..., description="Monthly Recurring Revenue in USD")
    current_arr: float = Field(..., description="Annualized Run Rate in USD (MRR * 12)")
    active_subscribers: int = 0
    arpu: float = Field(0.0, description="Average Revenue Per User in USD")
    subscribers_by_plan: RevenuePlanBreakdown
    mrr_by_plan: Dict[str, float] = Field(default_factory=dict)


class ViralityAnalyticsResponse(BaseModel):
    """K-factor and social referral virality metrics."""
    total_shares_sent: int = Field(0, description="Total match report and job share actions")
    unique_sharers: int = Field(0, description="Distinct users who initiated a share")
    invites_per_user: float = Field(0.0, description="Invites/shares sent per sharer (i)")
    referral_visits: int = Field(0, description="Visits with referral UTM or share token")
    referral_signups: int = Field(0, description="Attributed signups originating from referral shares")
    conversion_rate_per_share: float = Field(0.0, description="Conversion rate per share sent (c)")
    k_factor: float = Field(0.0, description="Virality coefficient K = i * c")
    is_viral: bool = Field(False, description="True if K-factor >= 1.0")


class RollupJobResult(BaseModel):
    """Result of scheduled pre-aggregation rollup execution."""
    status: str = "success"
    daily_rollups_computed: int = 0
    cohort_rollups_computed: int = 0
    execution_time_ms: float = 0.0
