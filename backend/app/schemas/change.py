"""Pydantic schemas for Change Management."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class ChangeCreate(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=255)
    change_type: str = "physical_part"
    reason: Optional[str] = None
    description: Optional[str] = None
    priority: str = "medium"
    lead_id: Optional[int] = None
    data_classification: str = "confidential"


class ChangeUpdate(BaseModel):
    title: Optional[str] = None
    reason: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    change_type: Optional[str] = None
    lead_id: Optional[int] = None
    estimated_cost: Optional[float] = None
    quoted_price: Optional[float] = None
    pnl_note: Optional[str] = None
    timing_milestone_id: Optional[int] = None


class TransitionRequest(BaseModel):
    to_status: str
    justification: Optional[str] = None
    cancellation_reason: Optional[str] = None


class CustomerResponseRequest(BaseModel):
    response: str  # accepted | declined | negotiating


class SignOffRequest(BaseModel):
    role: str  # pm | quality


class ImpactedItemCreate(BaseModel):
    part_id: int
    impact_note: Optional[str] = None
    eng_level_before: Optional[str] = None


class AssessmentSubmit(BaseModel):
    department_id: int
    verdict: str
    cost_impact: Optional[float] = None
    lead_time_impact_days: Optional[int] = None
    conditions: Optional[str] = None
    notes: Optional[str] = None
    responsible_id: Optional[int] = None


class ImpactedItemResponse(BaseModel):
    id: int
    part_id: int
    impact_note: Optional[str] = None
    eng_level_before: Optional[str] = None
    eng_level_after: Optional[str] = None
    resulting_revision_id: Optional[int] = None

    class Config:
        from_attributes = True


class AssessmentResponse(BaseModel):
    id: int
    department_id: int
    verdict: str
    cost_impact: Optional[float] = None
    lead_time_impact_days: Optional[int] = None
    conditions: Optional[str] = None
    notes: Optional[str] = None
    responsible_id: Optional[int] = None
    submitted_at: Optional[datetime] = None
    stage_order: int = 1
    rasic_letter: str = "R"
    status: str = "active"

    class Config:
        from_attributes = True


class AttachmentResponse(BaseModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime

    class Config:
        from_attributes = True


class ChangelogResponse(BaseModel):
    id: int
    action: str
    action_description: str
    performed_by: int
    performed_at: datetime
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class ChangeResponse(BaseModel):
    id: int
    change_number: str
    project_id: int
    title: str
    description: Optional[str] = None
    reason: Optional[str] = None
    change_type: str
    priority: str
    status: str
    lead_id: Optional[int] = None
    raised_by: int
    customer_response: str
    pm_signed_by: Optional[int] = None
    quality_signed_by: Optional[int] = None
    estimated_cost: Optional[float] = None
    quoted_price: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChangeDetailResponse(ChangeResponse):
    impacted_items: List[ImpactedItemResponse] = []
    assessments: List[AssessmentResponse] = []
    attachments: List[AttachmentResponse] = []
