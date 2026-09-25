"""The project team: one responsible (main owner) per department per
project (spec 2026-09-25). GET/PUT /v1/projects/{project_id}/team."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import Plant, Project, User, get_db
from app.services.project_team_service import ProjectTeamError, ProjectTeamService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


class TeamMemberSet(BaseModel):
    """PUT body: set (user_id given) or clear (user_id null) one role."""
    department_id: int
    user_id: Optional[int] = None


async def _get_project(db: AsyncSession, project_id: int, current_user: User) -> Project:
    result = await db.execute(
        select(Project).join(Plant).where(
            (Project.id == project_id) & (Plant.organization_id == current_user.organization_id)
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.get("/{project_id}/team", response_model=list[dict])
async def get_team(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project(db, project_id, current_user)
    return await ProjectTeamService.list_team(db, project_id)


@router.put("/{project_id}/team", response_model=list[dict])
async def set_team_member(
    project_id: int,
    body: TeamMemberSet,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set or clear the responsible for one department on this project.
    Rights: PM members or admin."""
    await _get_project(db, project_id, current_user)
    if not await ProjectTeamService.user_can_manage(db, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Project Management or an admin may set the project team")
    try:
        if body.user_id is None:
            await ProjectTeamService.clear_responsible(db, project_id, body.department_id)
        else:
            await ProjectTeamService.set_responsible(
                db, project_id, body.department_id, body.user_id, current_user)
    except ProjectTeamError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await db.commit()
    return await ProjectTeamService.list_team(db, project_id)
