"""Article and revision schemas."""
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class ArticleTypeEnum(str, Enum):
    """Article type enumeration."""
    INJECTION_TOOL = "injection_tool"
    ASSEMBLY_EQUIPMENT = "assembly_equipment"
    PURCHASED_PART = "purchased_part"


class SourcingTypeEnum(str, Enum):
    """Sourcing type enumeration."""
    INTERNAL = "internal"
    EXTERNAL = "external"


class RevisionTypeEnum(str, Enum):
    """Revision type enumeration."""
    ENGINEERING = "engineering"
    RELEASED = "released"
    CHANGE = "change"


class RevisionStatusEnum(str, Enum):
    """Revision status enumeration."""
    DRAFT = "draft"
    RFQ = "rfq"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    IN_IMPLEMENTATION = "in_implementation"
    RELEASED = "released"
    REJECTED = "rejected"
    CANCELED = "canceled"
    SUPERSEDED = "superseded"


class ArticleCreateRequest(BaseModel):
    """Request to create a new article."""
    article_number: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    article_type: ArticleTypeEnum
    sourcing_type: SourcingTypeEnum = SourcingTypeEnum.INTERNAL


class ArticleUpdateRequest(BaseModel):
    """Request to update article metadata."""
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    sourcing_type: SourcingTypeEnum | None = None


class ArticleResponse(BaseModel):
    """Article response model."""
    id: int
    article_number: str
    name: str
    description: str | None
    article_type: ArticleTypeEnum
    sourcing_type: SourcingTypeEnum
    data_classification: str
    active_revision_id: int | None
    created_at: datetime
    created_by: int

    class Config:
        from_attributes = True


class RevisionCreateRequest(BaseModel):
    """Request to create a new engineering revision."""
    pass  # No parameters - auto-numbered


class ReleaseRevisionRequest(BaseModel):
    """Request to release a revision."""
    notes: str | None = None


class ChangeProposalRequest(BaseModel):
    """Request to create a change proposal."""
    change_summary: str | None = None


class RevisionStatusTransitionRequest(BaseModel):
    """Request to transition revision status."""
    new_status: RevisionStatusEnum
    notes: str | None = None


class RevisionResponse(BaseModel):
    """Revision response model."""
    id: int
    article_id: int
    revision: str
    version: int
    status: RevisionStatusEnum
    revision_type: RevisionTypeEnum
    rfq_number: str | None
    is_official: bool
    change_summary: str | None
    comments: str | None
    created_at: datetime
    created_by: int
    released_at: datetime | None
    released_by: int | None
    parent_revision_id: int | None
    supersedes_id: int | None
    parent_index_id: int | None

    class Config:
        from_attributes = True


class RevisionTreeNodeResponse(BaseModel):
    """Single node in revision tree."""
    id: int
    revision: str
    status: RevisionStatusEnum
    revision_type: RevisionTypeEnum


class RevisionChangeResponse(BaseModel):
    """Change proposal response in tree."""
    id: int
    revision: str
    status: RevisionStatusEnum


class RevisionIndexResponse(BaseModel):
    """Released index response in tree."""
    id: int
    revision: str
    status: RevisionStatusEnum
    changes: list[RevisionChangeResponse]


class RevisionTreeResponse(BaseModel):
    """Hierarchical revision tree response."""
    engineering: list[RevisionTreeNodeResponse]
    released_indexes: list[RevisionIndexResponse]


class ArticleDetailResponse(BaseModel):
    """Article with all revisions and details."""
    article: ArticleResponse
    revisions: list[RevisionResponse]
    revision_tree: RevisionTreeResponse
