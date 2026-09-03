"""
Pydantic data models for VisaLane Phase 11:
AI Policy-Shock Detection and Warm Outreach Drafting.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PolicyShockSignal(BaseModel):
    """Evaluation result for a specific sponsorship posture signal."""
    signal_type: str = Field(..., description="'posting_velocity' or 'filing_recency'")
    flagged: bool = Field(False, description="True if the signal fired a policy-shock warning")
    status: str = Field(..., description="'normal', 'shock_flagged', 'insufficient_history', 'no_filing_history'")
    confidence_impact: int = Field(0, description="Score delta (e.g. -15 points when flagged)")
    reason_detail: Optional[str] = Field(None, description="Human-readable mathematical reasoning for the flag")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Raw mathematical baseline and recent metrics")


class CompanyPolicyShockStatus(BaseModel):
    """Aggregate policy shock assessment for an employer."""
    company_slug: str
    company_name: str
    base_confidence_score: int
    adjusted_confidence_score: int
    total_penalty: int = 0
    signals: List[PolicyShockSignal] = Field(default_factory=list)
    confidence_factors: List[Dict[str, str]] = Field(default_factory=list)
    alerts_triggered: int = 0
    evaluated_at: str


class CompanyFilingRecord(BaseModel):
    """Historical visa filing record (LCA, PERM, or government petition)."""
    filing_date: str = Field(..., description="ISO Date (YYYY-MM-DD)")
    case_number: Optional[str] = None
    visa_type: Optional[str] = "H-1B"
    status: Optional[str] = "certified"


class OutreachDraftRequest(BaseModel):
    """Candidate input for generating a personalized warm outreach draft."""
    company_id: str = Field(..., description="Company slug or company name")
    target_job_id: str = Field(..., description="Target job ID or job slug")
    contact_name: Optional[str] = Field(None, description="Candidate-identified contact name (ephemeral only)")
    contact_role: Optional[str] = Field(None, description="Candidate-identified contact title (ephemeral only)")
    contact_linkedin_url: Optional[str] = Field(None, description="Candidate-identified contact LinkedIn URL (ephemeral only)")
    candidate_notes: Optional[str] = Field(None, description="Candidate background, skills, or visa context")
    user_id: Optional[str] = Field(None, description="Authenticated candidate user ID for entitlement tracking")


class OutreachDraftResponse(BaseModel):
    """Personalized warm outreach draft response (strictly returns draft text only)."""
    draft_text: str = Field(..., description="Personalized outreach message body")
    company_name: str
    target_job_title: str
    sponsorship_highlight: str
    generated_at: str
