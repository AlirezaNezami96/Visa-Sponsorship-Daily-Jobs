"""
Pydantic data models for VisaLane Phase 12:
Partnership & Affiliate Infrastructure.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AffiliatePartner(BaseModel):
    """Affiliate or referral partner registration."""
    id: str = Field(..., description="Unique partner identifier (e.g., 'aff_revolut_expat')")
    slug: str = Field(..., description="URL slug for redirect service (e.g., 'revolut-expat')")
    name: str = Field(..., description="Partner business name")
    category: str = Field(..., description="'banking' | 'insurance' | 'relocation' | 'legal' | 'education'")
    destination_url_template: str = Field(..., description="Target landing page URL with {session_id} and tracking macros")
    commission_structure: Dict[str, Any] = Field(default_factory=dict, description="Payout rules (e.g., flat $35 or 15% rev-share)")
    status: str = Field("active", description="'active' | 'paused'")
    contact_email: Optional[str] = Field(None, description="Administrative contact email for the partner")
    created_at: Optional[str] = None


class AffiliateClick(BaseModel):
    """Recorded outbound affiliate click event."""
    id: str
    partner_id: str
    session_id: str
    user_id: Optional[str] = None
    is_duplicate: bool = False
    is_burst: bool = False
    created_at: str


class PartnerReferralCode(BaseModel):
    """Inbound candidate referral code."""
    id: str
    partner_id: str
    code: str = Field(..., description="Referral code string (case-insensitive)")
    created_at: str


class ReferralValidationResponse(BaseModel):
    """Validation status of an inbound referral code."""
    valid: bool
    code: str
    partner_id: Optional[str] = None
    partner_name: Optional[str] = None
    category: Optional[str] = None


class PartnerReportResponse(BaseModel):
    """Audit-grade partner performance and commission report."""
    partner_id: str
    partner_name: str
    category: str
    referral_code: Optional[str] = None
    total_clicks: int = 0
    unique_clicks: int = 0
    duplicate_clicks: int = 0
    burst_clicks: int = 0
    referred_signups: int = 0
    self_referrals_flagged: int = 0
    activated_users: int = 0
    activation_rate_pct: float = 0.0
    estimated_commission_usd: float = 0.0
    commission_breakdown: Dict[str, Any] = Field(default_factory=dict)
    period_start: str
    period_end: str


class MultiStepSignupStep1Request(BaseModel):
    """Step 1: Session binding, email, and landing referral code."""
    session_id: str
    email: str
    password: str
    referral_code: Optional[str] = None


class MultiStepSignupStep2Request(BaseModel):
    """Step 2: Candidate visa preferences and professional target."""
    session_id: str
    visa_status: str
    target_role: str


class MultiStepSignupCompleteRequest(BaseModel):
    """Step 3: Account creation finalization."""
    session_id: str
    full_name: str


class MultiStepSignupResponse(BaseModel):
    """Result of candidate signup flow step."""
    session_id: str
    user_id: Optional[str] = None
    email: str
    current_step: int
    referred_by_partner_code: Optional[str] = None
    status: str = "in_progress"
