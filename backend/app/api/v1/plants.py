"""API endpoints for plants."""
import logging
from typing import List
from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.dependencies import get_current_user
from app.models import Plant, User, get_db
from app.models.entities import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plants", tags=["plants"])


class ProjectCreate(BaseModel):
    """Create a new project."""
    name: str
    code: str
    description: str | None = None
    plant_id: int


@router.get("", response_model=List[dict])
async def get_plants(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all plants for the current organization."""
    result = await db.execute(
        select(Plant).where(Plant.organization_id == current_user.organization_id)
    )
    plants = result.scalars().all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "code": p.code,
            "location": p.location,
            "is_active": p.is_active,
        }
        for p in plants
    ]


@router.get("/projects", response_model=List[dict])
async def get_all_projects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all projects for the current organization (across all plants)."""
    result = await db.execute(
        select(Project).join(Plant).where(Plant.organization_id == current_user.organization_id)
        .order_by(Project.name)
    )
    projects = result.scalars().all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "code": p.code,
            "description": p.description,
            "status": p.status,
            "plant_id": p.plant_id,
        }
        for p in projects
    ]


@router.get("/{plant_id}/projects", response_model=List[dict])
async def get_plant_projects(
    plant_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all projects in a plant."""
    # Verify plant belongs to user's organization
    result = await db.execute(
        select(Plant).where(
            (Plant.id == plant_id) & (Plant.organization_id == current_user.organization_id)
        )
    )
    plant = result.scalar_one_or_none()
    if not plant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")

    # Get projects for this plant
    from app.models import Project
    result = await db.execute(select(Project).where(Project.plant_id == plant_id))
    projects = result.scalars().all()

    return [
        {
            "id": p.id,
            "name": p.name,
            "code": p.code,
            "description": p.description,
            "status": p.status,
            "plant_id": p.plant_id,
        }
        for p in projects
    ]


@router.post("/projects", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new project."""
    # Verify plant exists and belongs to user's organization
    result = await db.execute(
        select(Plant).where(
            (Plant.id == body.plant_id) & (Plant.organization_id == current_user.organization_id)
        )
    )
    plant = result.scalar_one_or_none()
    if not plant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")

    # Create project
    project = Project(
        plant_id=body.plant_id,
        name=body.name,
        code=body.code,
        description=body.description,
        status="active",
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    return {
        "id": project.id,
        "name": project.name,
        "code": project.code,
        "description": project.description,
        "status": project.status,
        "plant_id": project.plant_id,
    }
