"""Per-part paint setup endpoints and the project paint overview.

`PaintService.get_setup` / `put_setup` / `project_overview` take a part or
project id with no organization id of their own, so the org check happens
here: a part belongs to the org through `Part.project_id -> Project.plant_id
-> Plant.organization_id`, and a project the same way minus the first hop.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.models.entities import Plant, Project
from app.models.part import Part
from app.schemas.paint import PartPaintIn, PartPaintOut, PaintOverviewPartOut
from app.services.paint_service import PaintService

router = APIRouter(prefix="/parts", tags=["paints"])


async def _part_in_org(db: AsyncSession, part_id: int, org_id: int) -> int:
    """Return part_id if it belongs to the org, else raise 404."""
    row = (await db.execute(
        select(Part.id)
        .join(Project, Part.project_id == Project.id)
        .join(Plant, Project.plant_id == Plant.id)
        .where(Part.id == part_id, Plant.organization_id == org_id)
    )).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
    return part_id


async def _project_in_org(db: AsyncSession, project_id: int, org_id: int) -> int:
    """Return project_id if it belongs to the org, else raise 404."""
    row = (await db.execute(
        select(Project.id)
        .join(Plant, Project.plant_id == Plant.id)
        .where(Project.id == project_id, Plant.organization_id == org_id)
    )).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project_id


@router.get("/{part_id}/paint", response_model=PartPaintOut)
async def get_part_paint(
    part_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A part's paint setup with layers; empty setup if none stored yet."""
    await _part_in_org(db, part_id, current_user.organization_id)
    return await PaintService.get_setup(db, part_id=part_id)


@router.put("/{part_id}/paint", response_model=PartPaintOut)
async def put_part_paint(
    part_id: int,
    body: PartPaintIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Replace a part's whole paint setup; layers renumbered from list order."""
    await _part_in_org(db, part_id, current_user.organization_id)
    try:
        result = await PaintService.put_setup(
            db, part_id=part_id, org_id=current_user.organization_id,
            paint_required=body.paint_required, process=body.process, notes=body.notes,
            layers=[layer.model_dump() for layer in body.layers],
            updated_by=current_user.id,
        )
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await db.commit()
    return result


@router.get("/project/{project_id}/paint-overview", response_model=list[PaintOverviewPartOut])
async def get_project_paint_overview(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every part in the project with paint required, with its layers."""
    await _project_in_org(db, project_id, current_user.organization_id)
    return await PaintService.project_overview(db, project_id=project_id)
