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


