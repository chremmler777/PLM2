# backend/app/api/v1/changes/engineering_review.py
"""Engineering review (spec 2026-09-25 §17): the Review tab of a change with
origin "engineering_review".

    GET  /changes/{id}/review            tab state + caller rights
    POST /changes/{id}/review/answers    a department answers impact / no impact
    POST /changes/{id}/review/escalate   Development: escalate to a full ECR

ChangeError -> 400, ReviewForbidden -> 403, ReviewNotFound -> 404.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.services.change_service import ChangeError, ChangeService
from app.services.engineering_review_service import (
    EngineeringReviewService, ReviewForbidden, ReviewNotFound,
)

router = APIRouter(prefix="/changes", tags=["changes"])


class AnswerIn(BaseModel):
    department_id: int
    answer: str = Field(..., pattern="^(no_impact|impact)$")
    note: Optional[str] = Field(None, max_length=4000)


class EscalateIn(BaseModel):
    note: Optional[str] = Field(None, max_length=4000)


def _http(e: Exception) -> HTTPException:
    if isinstance(e, ReviewForbidden):
        return HTTPException(status_code=403, detail=str(e))
    if isinstance(e, ReviewNotFound):
        return HTTPException(status_code=404, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


_ERRORS = (ChangeError, ReviewForbidden, ReviewNotFound)


async def _change(db: AsyncSession, change_id: int, user: User):
    change = await ChangeService.get_change(db, change_id, viewer=user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


@router.get("/{change_id}/review")
async def get_review(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await EngineeringReviewService.state(db, change, current_user)


@router.post("/{change_id}/review/answers")
async def answer_review(
    change_id: int, body: AnswerIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await EngineeringReviewService.answer(
            db, change, body.department_id, body.answer, current_user, body.note)
        await db.commit()
    except _ERRORS as e:
        await db.rollback()
        raise _http(e)
    await db.refresh(change)
    return await EngineeringReviewService.state(db, change, current_user)


@router.post("/{change_id}/review/escalate")
async def escalate_review(
    change_id: int, body: EscalateIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await EngineeringReviewService.escalate(db, change, current_user, body.note)
        await db.commit()
    except _ERRORS as e:
        await db.rollback()
        raise _http(e)
    await db.refresh(change)
    return await EngineeringReviewService.state(db, change, current_user)
