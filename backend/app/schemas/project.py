"""Project schemas."""
from datetime import datetime
from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    """Request to create a project."""
    name: str = Field(..., min_length=1, max_length=255)
    code: str = Field(..., min_length=1, max_length=100)
    description: str | None = None


class ProjectUpdateRequest(BaseModel):
    """Request to update a project."""
    name: str | None = Field(None, max_length=255)
    code: str | None = Field(None, max_length=100)
    description: str | None = None
    status: str | None = None


class ProjectResponse(BaseModel):
    """Project response model."""
    id: int
    plant_id: int
    name: str
    code: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
