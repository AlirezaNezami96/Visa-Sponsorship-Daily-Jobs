"""
Pydantic schemas for VisaLane Phase 7 Alert & Lifecycle Notification Engine.
Defines data structures for alert filter criteria, CRUD requests/responses,
Telegram bot integration, token-based unsubscriptions, and user notification preferences.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class AlertFilterCriteria(BaseModel):
    """Filter criteria for matching jobs (mirrors /api/v1/jobs query parameters)."""
    country: Optional[str] = Field(None, description="Country slug or code, e.g. 'germany', 'united-kingdom'")
    visa_type: Optional[str] = Field(None, description="Visa type slug or code, e.g. 'eu-blue-card', 'skilled-worker'")
    keyword: Optional[str] = Field(None, description="Search query string matching job title or description")
    min_salary: Optional[int] = Field(None, description="Minimum annualized salary filter")
    is_remote: Optional[bool] = Field(None, description="Filter for remote eligible opportunities")
    company_name: Optional[str] = Field(None, description="Filter for specific hiring employer")
    min_confidence: Optional[int] = Field(None, description="Minimum sponsorship verification confidence (0-100)")
    role_category: Optional[str] = Field(None, description="Job category, e.g. 'engineering', 'product', 'design'")


class AlertCreateRequest(BaseModel):
    """Payload to create a new job alert."""
    email: str = Field(..., description="Recipient email address for digest notifications")
    user_id: Optional[str] = Field(None, description="Optional authenticated user ID (if logged in)")
    filter_criteria: AlertFilterCriteria = Field(default_factory=AlertFilterCriteria, description="Job search filter criteria")
    cadence: Literal["instant", "daily", "weekly"] = Field("daily", description="Notification frequency: 'instant' (Plus tier only), 'daily', or 'weekly'")
    channels: List[Literal["email", "telegram"]] = Field(default=["email"], description="Notification channels to dispatch to")
    telegram_chat_id: Optional[str] = Field(None, description="Telegram chat ID if linked via bot")
    downgrade_to_daily: bool = Field(False, description="If True, silently downgrade 'instant' to 'daily' if free tier user is ineligible instead of 403")


class AlertUpdateRequest(BaseModel):
    """Payload to update an existing job alert."""
    filter_criteria: Optional[AlertFilterCriteria] = None
    cadence: Optional[Literal["instant", "daily", "weekly"]] = None
    channels: Optional[List[Literal["email", "telegram"]]] = None
    telegram_chat_id: Optional[str] = None
    is_active: Optional[bool] = None
    downgrade_to_daily: bool = False


class AlertResponse(BaseModel):
    """Response representation of a saved job alert."""
    id: str
    user_id: Optional[str] = None
    email: str
    filter_criteria: AlertFilterCriteria
    cadence: str
    channels: List[str]
    telegram_chat_id: Optional[str] = None
    is_active: bool
    created_at: str
    last_notified_at: Optional[str] = None
    downgraded: bool = False
    downgrade_reason: Optional[str] = None


class AlertListResponse(BaseModel):
    """List of alerts belonging to a user or session."""
    alerts: List[AlertResponse]
    total_count: int


class TelegramLinkTokenResponse(BaseModel):
    """Link token payload for binding Telegram account to VisaLane."""
    token: str
    bot_username: str
    link_command: str
    link_url: str
    expires_at: str


class TelegramWebhookUpdate(BaseModel):
    """Incoming Telegram Webhook Update model."""
    update_id: int
    message: Optional[Dict[str, Any]] = None
    callback_query: Optional[Dict[str, Any]] = None


class UnsubscribeRequest(BaseModel):
    """Payload for granular programmatic unsubscribe."""
    token: str = Field(..., description="Cryptographically signed unsubscribe token")
    alert_id: Optional[str] = Field(None, description="Specific alert ID to deactivate")
    scope: Literal["alert_only", "all_marketing", "all_notifications"] = Field("alert_only", description="Unsubscribe scope")


class UnsubscribeResponse(BaseModel):
    """Response confirmation for unsubscribe action."""
    success: bool
    scope: str
    message: str
    unsubscribed_email: str
    alert_id: Optional[str] = None


class UserPreferencesResponse(BaseModel):
    """Current notification preferences for a user."""
    email: str
    marketing_opt_out: bool
    telegram_linked: bool
    telegram_chat_id: Optional[str] = None
    active_alerts_count: int
    configured_channels: List[str]


class UserPreferencesUpdateRequest(BaseModel):
    """Payload to update notification preferences."""
    email: Optional[str] = None
    marketing_opt_out: Optional[bool] = None
    telegram_chat_id: Optional[str] = None


class NotificationLog(BaseModel):
    """Audit log of a dispatched notification."""
    id: str
    alert_id: Optional[str] = None
    user_id: Optional[str] = None
    recipient_email: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    channel: str
    notification_type: str
    consent_classification: Literal["transactional", "marketing"]
    job_count: int
    job_ids: List[str]
    subject: str
    status: Literal["sent", "suppressed", "failed"]
    sent_at: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ScheduledDigestRunResponse(BaseModel):
    """Response summary from running scheduled alert digests."""
    cadence: str
    alerts_evaluated: int
    digests_sent: int
    alerts_suppressed_zero_matches: int
    marketing_suppressed: int
    errors: int
    execution_time_ms: float
