"""Pydantic schemas for parts and revisions."""
from datetime import date, datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field

from app.schemas.common import NaiveUtcDatetime


# Part Schemas
class PartBase(BaseModel):
    """Base part information."""
    part_number: str = Field(..., min_length=1, max_length=100)
    customer_part_number: Optional[str] = Field(
        None, max_length=100, description="Customer's own number, e.g. 3CR.919.491.A")
    tier1_part_number: Optional[str] = Field(
        None, max_length=100, description="Tier 1 number when we are Tier 2, e.g. S00H54-110")
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    part_type: str = Field(..., description="purchased, internal_mfg, sub_assembly")
    supplier: Optional[str] = None
    supplier_id: Optional[int] = None
    data_classification: str = "confidential"
    parent_part_id: Optional[int] = None
    item_category: str = Field("article", description="article, tool, assembly_equipment, gauge")
    calibration_interval_months: Optional[int] = Field(None, ge=1, le=120)
    last_calibrated_at: Optional[datetime] = None
    next_calibration_due: Optional[datetime] = None

    # Tool fields (item_category = tool only)
    tool_cavities: Optional[int] = Field(None, ge=1, le=256, description="Cavities in the tool, total")
    toolmaker_id: Optional[int] = Field(None, description="Supplier building the tool")
    tool_tonnage_class: Optional[int] = Field(None, ge=1, le=10000, description="Machine clamping force class, t")
    tool_cycle_time_s: Optional[float] = Field(None, gt=0, le=9999.9, description="Target cycle time, s")


class PartCreate(PartBase):
    """Create a new part."""
    project_id: int
    parent_part_id: Optional[int] = None  # Can be a child of a sub-assembly
    # Input-only normalization; PartResponse must keep plain datetime fields
    # so serialization never silently strips tzinfo.
    last_calibrated_at: Optional[NaiveUtcDatetime] = None
    next_calibration_due: Optional[NaiveUtcDatetime] = None


class PartUpdate(BaseModel):
    """Update part information. parent_part_id only applies when explicitly
    provided (send null to move the part to top level)."""
    name: Optional[str] = None
    customer_part_number: Optional[str] = Field(None, max_length=100)
    tier1_part_number: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    part_type: Optional[str] = None
    supplier: Optional[str] = None
    supplier_id: Optional[int] = None
    parent_part_id: Optional[int] = None
    item_category: Optional[str] = None
    calibration_interval_months: Optional[int] = Field(None, ge=1, le=120)
    last_calibrated_at: Optional[NaiveUtcDatetime] = None

    # Tool fields (item_category = tool only)
    tool_cavities: Optional[int] = Field(None, ge=1, le=256, description="Cavities in the tool, total")
    toolmaker_id: Optional[int] = Field(None, description="Supplier building the tool")
    tool_tonnage_class: Optional[int] = Field(None, ge=1, le=10000, description="Machine clamping force class, t")
    tool_cycle_time_s: Optional[float] = Field(None, gt=0, le=9999.9, description="Target cycle time, s")


class PartResponse(PartBase):
    """Part response with metadata."""
    id: int
    project_id: int
    active_revision_id: Optional[int] = None
    lifecycle_phase: str = "rfq"
    nominated_at: Optional[date] = None
    sop_at: Optional[date] = None
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
    revision_name: str = Field(..., description="E1, E1.1 (review) or 1, 1.1 (official)")
    phase: str = Field(..., description="review, official")
    status: str = Field(default="draft", description="draft, in_progress, in_review, approved, rejected, archived, frozen, cancelled")
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
    customer_index: Optional[str] = None
    customer_statement: Optional[str] = None
    customer_received_at: Optional[date] = None
    source: str = "internal"
    part_phase_at_receipt: str = "rfq"
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


# Revision action schemas
class CustomerDataReceivedRequest(BaseModel):
    """The customer sent data and stated whether it is review or official."""
    statement: Literal["review", "official"]
    received_at: date
    customer_index: Optional[str] = Field(None, max_length=20, description="Customer's own index, e.g. B")
    summary: Optional[str] = None
    major: Optional[int] = Field(None, ge=1, description="Chosen major number; must be above every existing major of this kind")


class CreateProposalRequest(BaseModel):
    """Our internal iteration under a customer major (E1 → E1.1, 1 → 1.1)."""
    parent_revision_id: int
    summary: Optional[str] = None


class PromoteRevisionRequest(BaseModel):
    """The customer adopted this proposal as their next data state."""
    statement: Literal["review", "official"]
    received_at: date
    customer_index: Optional[str] = Field(None, max_length=20)
    major: Optional[int] = Field(None, ge=1, description="Chosen major number; must be above every existing major of this kind")


class RejectMajorRevisionRequest(BaseModel):
    """Request to reject a revision."""
    reason: Optional[str] = Field(None, description="Reason for rejection")


class SetLifecyclePhaseRequest(BaseModel):
    phase: Literal["nominated", "series"]
    effective: date


# Update forward references
PartDetailResponse.model_rebuild()
PartRevisionDetailResponse.model_rebuild()
RevisionTreeNode.model_rebuild()


class PackageRowOut(BaseModel):
    filename: str
    part_id: Optional[int] = None
    part_number: Optional[str] = None
    customer_part_number: Optional[str] = None
    customer_index: Optional[str] = None
    current_revision: Optional[str] = None
    current_index: Optional[str] = None
    action: Literal["new_major", "unchanged", "unmatched", "error"]
    suggested_name: Optional[str] = None
    major: Optional[int] = None
    error: Optional[str] = None


class PackageRowIn(BaseModel):
    filename: str
    part_id: Optional[int] = None
    customer_index: Optional[str] = Field(None, max_length=20)
    action: Literal["new_major", "unchanged", "unmatched"]
    major: Optional[int] = Field(None, ge=1)


class PackagePreviewResponse(BaseModel):
    rows: List[PackageRowOut]
