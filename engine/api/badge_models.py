"""
Phase 9: Verified Sponsor Badge Admin Review Workflow & Audit Trail Models.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, EmailStr, Field


class BadgeApplicationSubmitRequest(BaseModel):
    """Payload for submitting verified sponsor badge evidence."""
    employer_id: str = Field(..., min_length=1, description="Employer account ID")
    company_slug: str = Field(..., min_length=1, description="Canonical company slug")
    company_name: str = Field(..., min_length=1, description="Official company legal name")
    contact_email: EmailStr = Field(..., description="Official business contact email")
    license_or_reg_number: Optional[str] = Field(None, description="Government sponsor license or company registration number")
    sponsorship_history_summary: str = Field(..., min_length=10, description="Summary of past sponsorship track record")
    evidence_urls: List[str] = Field(..., min_length=1, description="List of URLs pointing to verification evidence/certificates")
    notes: Optional[str] = Field(None, description="Additional context or notes for the reviewer")


class BadgeApplicationResubmitRequest(BaseModel):
    """Payload for resubmitting evidence following an application rejection."""
    employer_id: str = Field(..., min_length=1, description="Employer account ID")
    company_slug: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    license_or_reg_number: Optional[str] = None
    sponsorship_history_summary: Optional[str] = None
    evidence_urls: Optional[List[str]] = None
    notes: Optional[str] = Field(None, description="Explanation of amendments and additional evidence")


class BadgeReviewDecisionRequest(BaseModel):
    """Payload for admin approve or reject decision."""
    notes: Optional[str] = Field(None, description="Mandatory review notes for rejection, optional for approval")


class BadgeReviewLogEntry(BaseModel):
    """Immutable audit log record for verified sponsor badge decisions."""
    id: str
    application_id: Optional[str] = None
    employer_id: str
    company_slug: Optional[str] = None
    reviewer_id: str
    decision: str  # "approved" | "rejected"
    notes: Optional[str] = None
    created_at: str


class BadgeApplicationResponse(BaseModel):
    """Public and admin representation of a verified sponsor badge application."""
    id: str
    employer_id: str
    company_slug: str
    company_name: str
    contact_email: str
    license_or_reg_number: Optional[str] = None
    sponsorship_history_summary: str
    evidence_urls: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    badge_status: str = "pending_review"  # "pending_review" | "verified" | "rejected"
    badge_payment_status: str = "paid"    # "paid" | "pending" | "refunded"
    verified_at: Optional[str] = None
    expires_at: Optional[str] = None
    renewal_notified_at: Optional[str] = None
    created_at: str
    updated_at: str
    review_logs: List[BadgeReviewLogEntry] = Field(default_factory=list)


class BadgeRenewalCheckResult(BaseModel):
    """Result of scheduled 30-day badge renewal expiration check."""
    checked_count: int
    flagged_count: int
    flagged_applications: List[Dict[str, Any]] = Field(default_factory=list)
