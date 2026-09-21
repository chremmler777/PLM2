"""Pydantic schemas for the paint catalog and per-part paint setup."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Mirrors app.models.paint.PAINT_TYPES; kept as a literal here so FastAPI/pydantic
# can validate and document it directly.
PaintType = Literal["primer", "basecoat", "clearcoat", "one_coat", "other"]


class PaintIn(BaseModel):
    """Create a paint."""
    name: str = Field(..., min_length=1, max_length=255)
    paint_type: PaintType = "basecoat"
    colour_code: Optional[str] = Field(None, max_length=50)
    colour_name: Optional[str] = Field(None, max_length=100)
    colour_hex: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    supplier_id: Optional[int] = None
    supplier_text: Optional[str] = Field(None, max_length=255)
    spec_reference: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class PaintUpdate(BaseModel):
    """Update a paint; all fields optional."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    paint_type: Optional[PaintType] = None
    colour_code: Optional[str] = Field(None, max_length=50)
    colour_name: Optional[str] = Field(None, max_length=100)
    colour_hex: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    supplier_id: Optional[int] = None
    supplier_text: Optional[str] = Field(None, max_length=255)
    spec_reference: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class PaintOut(BaseModel):
    """A paint as returned by the catalog and embedded in layers."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    paint_type: str
    colour_code: Optional[str] = None
    colour_name: Optional[str] = None
    colour_hex: Optional[str] = None
    supplier_id: Optional[int] = None
    supplier_text: Optional[str] = None
    spec_reference: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool


class UsedInOut(BaseModel):
    """One article using a paint, across projects."""
    model_config = ConfigDict(from_attributes=True)

    part_id: int
    part_number: str
    name: str
    project_id: int
    project_code: str
    layer_order: int


class PartPaintLayerIn(BaseModel):
    """One layer of a part's paint setup, as submitted."""
    paint_id: int
    area: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = Field(None, max_length=500)


class PartPaintLayerOut(BaseModel):
    """One layer of a part's paint setup, with the paint embedded."""
    model_config = ConfigDict(from_attributes=True)

    layer_order: int
    area: Optional[str] = None
    notes: Optional[str] = None
    paint: PaintOut


class PartPaintIn(BaseModel):
    """Replace a part's whole paint setup."""
    paint_required: bool = False
    process: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    layers: list[PartPaintLayerIn] = Field(default_factory=list)


class PartPaintOut(BaseModel):
    """A part's paint setup with layers."""
    model_config = ConfigDict(from_attributes=True)

    paint_required: bool
    process: Optional[str] = None
    notes: Optional[str] = None
    layers: list[PartPaintLayerOut] = Field(default_factory=list)


class PaintOverviewPartOut(BaseModel):
    """One painted part in a project's paint overview."""
    model_config = ConfigDict(from_attributes=True)

    part_id: int
    part_number: str
    name: str
    process: Optional[str] = None
    layers: list[PartPaintLayerOut] = Field(default_factory=list)
