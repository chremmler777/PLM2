# backend/app/api/v1/items/intakes.py
"""Revision intake (spec 2026-09-25 §17): every new customer index is
captured and triaged by Development.

    GET  /intakes                 list (part_id, project_id, status, change_id, waiting)
    GET  /intakes/my              My Tasks: triage (Development) + review answers
    GET  /intakes/{id}            one intake
    POST /intakes/{id}/decide     route + reason (+ change_id for attach_ecr)

IntakeError -> 400, IntakeForbidden -> 403, IntakeNotFound -> 404.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.services.change_service import ChangeError
from app.services.revision_intake_service import (
    IntakeError, IntakeForbidden, IntakeNotFound, RevisionIntakeService,
)

router = APIRouter(prefix="/intakes", tags=["intakes"])


class DecideIn(BaseModel):
    route: str = Field(..., pattern="^(full_ecr|attach_ecr|engineering_review|administrative)$")
    reason: Optional[str] = Field(None, max_length=4000)
    change_id: Optional[int] = None


def _http(e: Exception) -> HTTPException:
    if isinstance(e, IntakeForbidden):
        return HTTPException(status_code=403, detail=str(e))
    if isinstance(e, IntakeNotFound):
        return HTTPException(status_code=404, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


_ERRORS = (IntakeError, IntakeForbidden, IntakeNotFound, ChangeError)


@router.get("")
async def list_intakes(
    part_id: Optional[int] = Query(None), project_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None), change_id: Optional[int] = Query(None),
    waiting: Optional[bool] = Query(None),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    can = await RevisionIntakeService.may_triage(db, current_user)
    rows = await RevisionIntakeService.list(
        db, current_user, part_id=part_id, project_id=project_id, status=status,
        change_id=change_id, waiting=waiting)
    return {"can_triage": can,
            "intakes": [await RevisionIntakeService.out(db, i, can) for i in rows]}


@router.get("/my")
async def my_intakes(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await RevisionIntakeService.my(db, current_user)


@router.get("/{intake_id}")
async def get_intake(
    intake_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    try:
        intake = await RevisionIntakeService.get(db, intake_id, current_user)
    except _ERRORS as e:
        raise _http(e)
    can = await RevisionIntakeService.may_triage(db, current_user)
    return await RevisionIntakeService.out(db, intake, can)


@router.post("/{intake_id}/decide")
async def decide_intake(
    intake_id: int, body: DecideIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    try:
        intake = await RevisionIntakeService.get(db, intake_id, current_user)
        await RevisionIntakeService.decide(
            db, intake, body.route, current_user, reason=body.reason,
            change_id=body.change_id)
        await db.commit()
    except _ERRORS as e:
        await db.rollback()
        raise _http(e)
    await db.refresh(intake)
    return await RevisionIntakeService.out(db, intake, True)
