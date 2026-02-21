"""API endpoints for plants."""
import logging
from typing import List
from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_current_user
from app.models import Plant, User, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plants", tags=["plants"])


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
