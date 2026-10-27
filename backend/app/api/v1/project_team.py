"""The project team: one responsible (main owner) per department per
project (spec 2026-09-25) and, D2b (2026-10-19), a named backup.
GET/PUT /v1/projects/{project_id}/team."""
import logging
from typing import Literal, Optional

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
    """PUT body: set (user_id given) or clear (user_id null) one role's
    responsible, or (slot "backup", D2b) its named backup."""
    department_id: int
    user_id: Optional[int] = None
    slot: Literal["responsible", "backup"] = "responsible"


class TeamSlotsIn(BaseModel):
    department_id: int
    responsible_id: Optional[int] = None
    backup_id: Optional[int] = None


class TeamSave(BaseModel):
    """PUT /projects/{id}/team/batch: the dialog's draft, per touched
    department its wanted Responsible and Backup (null clears)."""
    slots: list[TeamSlotsIn]


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


@router.get("/team-gaps")
async def team_gaps(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """{project_id: open Responsible slots} for the caller's organization's
    projects: the projects list's red "Team incomplete" marker."""
    ids = list((await db.execute(select(Project.id).join(Plant).where(
        Plant.organization_id == current_user.organization_id))).scalars().all())
    return {str(k): v for k, v in (await ProjectTeamService.team_gaps(db, ids)).items()}


@router.get("/pm-responsibles")
async def pm_responsibles(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """{project_id: {id, name, mine}} of each project's Project Manager responsible,
    for the Start change project picker (Christoph 2026-10-27: the caller's
    own projects first, then the other PMs', undefined last). Projects with
    no PM responsible are left out. mine = the caller (under Act as person:
    that person) is the PM responsible."""
    from app.models.workflow import Department, ProjectResponsible
    rows = (await db.execute(
        select(ProjectResponsible.project_id, User.id, User.full_name, User.username)
        .join(Department, Department.id == ProjectResponsible.department_id)
        .join(User, User.id == ProjectResponsible.user_id)
        .join(Project, Project.id == ProjectResponsible.project_id)
        .join(Plant, Plant.id == Project.plant_id)
        .where(Department.name == "Project Manager",
               Plant.organization_id == current_user.organization_id))).all()
    return {str(pid): {"id": uid, "name": full or uname,
                      "mine": uid == current_user.id} for pid, uid, full, uname in rows}


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
    """Set or clear the responsible (or the named backup) for one
    department on this project. Rights: PM members or admin."""
    await _get_project(db, project_id, current_user)
    if not await ProjectTeamService.user_can_manage(db, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Project Management or an admin may set the project team")
    try:
        if body.user_id is None:
            await ProjectTeamService.clear_responsible(
                db, project_id, body.department_id, slot=body.slot, actor=current_user)
        else:
            await ProjectTeamService.set_responsible(
                db, project_id, body.department_id, body.user_id, current_user,
                slot=body.slot)
    except ProjectTeamError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await db.commit()
    return await ProjectTeamService.list_team(db, project_id)


@router.put("/{project_id}/team/batch", response_model=list[dict])
async def save_team(
    project_id: int,
    body: TeamSave,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The Team dialog's Save: the draft's slots in one step, all or
    nothing, then one notice (and mail) per newly named person. Rights: PM
    members or admin."""
    await _get_project(db, project_id, current_user)
    if not await ProjectTeamService.user_can_manage(db, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Project Management or an admin may set the project team")
    try:
        await ProjectTeamService.save_team(
            db, project_id, [x.model_dump() for x in body.slots], current_user)
    except ProjectTeamError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await db.commit()
    return await ProjectTeamService.list_team(db, project_id)
