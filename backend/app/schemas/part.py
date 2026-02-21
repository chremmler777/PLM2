"""Pydantic schemas for parts and revisions."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# Part Schemas
class PartBase(BaseModel):
    """Base part information."""
    part_number: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    part_type: str = Field(..., description="purchased, internal_mfg, sub_assembly")
    supplier: Optional[str] = None
    data_classification: str = "confidential"


class PartCreate(PartBase):
    """Create a new part."""
    project_id: int


class PartUpdate(BaseModel):
    """Update part information."""
    name: Optional[str] = None
    description: Optional[str] = None
    part_type: Optional[str] = None
    supplier: Optional[str] = None


class PartResponse(PartBase):
    """Part response with metadata."""
    id: int
    project_id: int
    active_revision_id: Optional[int] = None
    created_by: int
    updated_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PartDetailResponse(PartResponse):
    """Part with revisions included."""
    revisions: List["PartRevisionResponse"] = []


# Revision Schemas
class PartRevisionBase(BaseModel):
    """Base revision information."""
    revision_name: str = Field(..., description="RFQ1, ENG1, ENG1.1, IND1, ECR1.1, etc")
    phase: str = Field(..., description="rfq_phase, engineering, freeze, ecn")
    status: str = Field(default="draft", description="draft, in_progress, in_review, approved, rejected, frozen, cancelled")
    summary: Optional[str] = None
    change_reason: Optional[str] = None
    impact_analysis: Optional[str] = None


class PartRevisionCreate(PartRevisionBase):
    """Create a new revision (used internally by services)."""
    part_id: int
    parent_revision_id: Optional[int] = None
    test_data_status: Optional[str] = None


class PartRevisionResponse(PartRevisionBase):
    """Revision response with full details."""
    id: int
    part_id: int
    parent_revision_id: Optional[int] = None
    supersedes_revision_id: Optional[int] = None
    test_data_status: Optional[str] = None
    frozen_at: Optional[datetime] = None
    frozen_by: Optional[int] = None
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[int] = None
    cancellation_reason: Optional[str] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[int] = None
    approval_notes: Optional[str] = None
    created_by: int
    updated_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PartRevisionDetailResponse(PartRevisionResponse):
    """Revision with files and changelog."""
    files: List["RevisionFileResponse"] = []
    changelog: List["ChangelogEntryResponse"] = []


# File Schemas
class RevisionFileResponse(BaseModel):
    """File attached to a revision."""
    id: int
    revision_id: int
    filename: str
    file_type: str  # picture, cad, drawing, document, test_result
    mime_type: str
    file_size: int
    file_path: str
    cad_format: Optional[str] = None
    file_hash: str
    encrypted: bool
    viewer_file_path: Optional[str] = None
    has_viewer: bool
    is_deleted: bool
    uploaded_at: datetime
    uploaded_by: int

    class Config:
        from_attributes = True


# Changelog Schemas
class ChangelogEntryResponse(BaseModel):
    """Changelog entry showing what changed."""
    id: int
    part_id: int
    revision_id: Optional[int] = None
    action: str  # created, status_changed, approved, rejected, frozen, cancelled, file_uploaded, metadata_updated
    action_description: str
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    file_id: Optional[int] = None
    performed_by: int
    performed_by_user: Optional[str] = None  # Username, populated from User table
    performed_at: datetime
    notes: Optional[str] = None
    ip_address: Optional[str] = None

    class Config:
        from_attributes = True


# Revision Tree Response
class RevisionTreeNode(BaseModel):
    """Node in revision tree hierarchy."""
    revision: PartRevisionResponse
    children: List["RevisionTreeNode"] = []


# Bulk Operation Schemas
class CreateRFQRequest(BaseModel):
    """Request to create RFQ revision (auto-increments to next major version)."""
    summary: Optional[str] = None
    reject_drafts: bool = Field(False, description="If true, reject existing draft proposals before creating new major version")


class CreateRFQProposalRequest(BaseModel):
    """Request to create RFQ proposal (minor iteration like RFQ1.1, RFQ1.2)."""
    parent_revision_id: int = Field(..., description="Parent RFQ revision ID (e.g., RFQ1)")
    summary: Optional[str] = None


class PromoteRevisionRequest(BaseModel):
    """Request to promote a revision to next major version."""
    notes: Optional[str] = Field(None, description="Notes about the promotion")


class RejectMajorRevisionRequest(BaseModel):
    """Request to reject a major revision."""
    reason: Optional[str] = Field(None, description="Reason for rejection")


class TransitionToEngineeringRequest(BaseModel):
    """Request to transition RFQ to Engineering."""
    pass


class CreateEngineeringProposalRequest(BaseModel):
    """Request to create engineering proposal."""
    major_version: int = Field(..., ge=1, description="Base version (1 for ENG1.x, 2 for ENG2.x)")
    proposal_number: int = Field(..., ge=1, description="Proposal number (1 for x.1, 2 for x.2)")
    summary: Optional[str] = None
    change_reason: Optional[str] = None


class ApproveProposalRequest(BaseModel):
    """Request to approve a proposal."""
    next_major_version: int = Field(..., ge=2, description="Next major version")
    approval_notes: Optional[str] = None


class RejectProposalRequest(BaseModel):
    """Request to reject a proposal."""
    reason: Optional[str] = None


class CreateDesignFreezeRequest(BaseModel):
    """Request to create design freeze."""
    pass


class CreateECRRequest(BaseModel):
    """Request to create ECR proposal."""
    freeze_major_version: int = Field(..., ge=1, description="Freeze version (1 for IND1.x, 2 for IND2.x)")
    proposal_number: int = Field(..., ge=1, description="Proposal number")
    summary: Optional[str] = None
    change_reason: Optional[str] = None


# Update forward references
PartDetailResponse.model_rebuild()
PartRevisionDetailResponse.model_rebuild()
RevisionTreeNode.model_rebuild()
