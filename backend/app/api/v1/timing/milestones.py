"""Project milestone (timing gate) endpoints."""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.entities import Project
from app.models.timing import ProjectMilestone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/timing", tags=["timing"])


class MilestoneCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    due_date: datetime
    notes: Optional[str] = None


class MilestoneUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    due_date: Optional[datetime] = None
    status: Optional[str] = Field(None, description="open or done")
    notes: Optional[str] = None


def _dict(m: ProjectMilestone) -> dict:
    now = datetime.utcnow()
    return {
        "id": m.id,
        "project_id": m.project_id,
        "name": m.name,
        "due_date": m.due_date.isoformat(),
        "status": m.status,
        "completed_at": m.completed_at.isoformat() if m.completed_at else None,
        "notes": m.notes,
        "overdue": m.status == "open" and m.due_date < now,
    }


@router.get("/projects/{project_id}/milestones", response_model=List[dict])
async def list_milestones(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ProjectMilestone)
        .where(ProjectMilestone.project_id == project_id)
        .order_by(ProjectMilestone.due_date, ProjectMilestone.id)
    )
    return [_dict(m) for m in result.scalars().all()]


@router.post("/projects/{project_id}/milestones", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_milestone(
    project_id: int,
    body: MilestoneCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    milestone = ProjectMilestone(
        project_id=project_id,
        name=body.name.strip(),
        due_date=body.due_date,
        notes=body.notes,
        created_by=current_user.id,
    )
    db.add(milestone)
    await db.commit()
    return _dict(milestone)


@router.patch("/milestones/{milestone_id}", response_model=dict)
async def update_milestone(
    milestone_id: int,
    body: MilestoneUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ProjectMilestone).where(ProjectMilestone.id == milestone_id))
    milestone = result.scalar_one_or_none()
    if not milestone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Milestone not found")

    if body.status is not None:
        if body.status not in ("open", "done"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status must be open or done")
        milestone.status = body.status
        milestone.completed_at = datetime.utcnow() if body.status == "done" else None
    if body.name is not None:
        milestone.name = body.name.strip()
    if body.due_date is not None:
        milestone.due_date = body.due_date
    if body.notes is not None:
        milestone.notes = body.notes

    await db.commit()
    return _dict(milestone)


@router.delete("/milestones/{milestone_id}")
async def delete_milestone(
    milestone_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ProjectMilestone).where(ProjectMilestone.id == milestone_id))
    milestone = result.scalar_one_or_none()
    if not milestone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Milestone not found")
    await db.delete(milestone)
    await db.commit()
    return {"status": "success"}
