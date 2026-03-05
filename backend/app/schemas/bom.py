"""BOM and catalog part schemas."""
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class PartTypeEnum(str, Enum):
    PURCHASED = "purchased"
    MANUFACTURED = "manufactured"


class CatalogPartCreateRequest(BaseModel):
    part_number: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    part_type: PartTypeEnum
    supplier: str | None = Field(None, max_length=255)
    unit: str = Field(..., min_length=1, max_length=20)


class CatalogPartUpdateRequest(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    part_type: PartTypeEnum | None = None
    supplier: str | None = None
    unit: str | None = Field(None, max_length=20)


class CatalogPartResponse(BaseModel):
    id: int
    organization_id: int
    part_number: str
    name: str
    description: str | None
    part_type: PartTypeEnum
    supplier: str | None
    unit: str
    is_active: bool
    created_at: datetime
    created_by: int
    updated_at: datetime

    class Config:
        from_attributes = True


class DuplicateCheckResponse(BaseModel):
    exact_match: bool
    similar_parts: list[CatalogPartResponse]


class BOMItemCreateRequest(BaseModel):
    catalog_part_id: int
    quantity: float = Field(..., gt=0)
    notes: str | None = None
    position: int | None = None


class BOMItemUpdateRequest(BaseModel):
    quantity: float | None = Field(None, gt=0)
    notes: str | None = None
    position: int | None = None


class BOMItemResponse(BaseModel):
    id: int
    bom_id: int
    catalog_part_id: int | None
    part_number: str | None
    name: str
    part_type: str | None
    quantity: float
    unit: str
    supplier: str | None
    notes: str | None
    position: int

    class Config:
        from_attributes = True


class BOMResponse(BaseModel):
    id: int
    article_id: int
    revision_id: int | None
    status: str
    items: list[BOMItemResponse]

    class Config:
        from_attributes = True


class ProjectBOMSourceResponse(BaseModel):
    article_id: int
    article_number: str
    article_name: str
    revision_id: int
    revision: str
    quantity: float


class ProjectBOMLineResponse(BaseModel):
    catalog_part_id: int
    part_number: str
    name: str
    part_type: str
    unit: str
    supplier: str | None
    total_quantity: float
    sources: list[ProjectBOMSourceResponse]


class ProjectBOMResponse(BaseModel):
    project_id: int
    lines: list[ProjectBOMLineResponse]
