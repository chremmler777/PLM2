# backend/app/api/v1/changes/validation_issues.py
"""Validation issues: the failure branch of stage 9 (spec §12, §12a).

Mounted under /api/v1/changes. The service owns every rule; this module maps
its refusals onto HTTP (ChangeError -> 400, IssueForbidden / PlanForbidden ->
403, IssueNotFound -> 404, PlanConflict -> 409) and commits on success.
Every write answers the issue's IssueOut (the list item shape).
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.services.change_plan_service import PlanConflict, PlanForbidden
from app.services.change_service import ChangeError, ChangeService
from app.services.validation_issue_service import (
    IssueForbidden, IssueNotFound, ValidationIssueService as Svc,
)

router = APIRouter(prefix="/changes", tags=["changes"])


# ----------------------------------------------------------------------
# Bodies
# ----------------------------------------------------------------------
class ActionIn(BaseModel):
    description: str = Field(max_length=2000)
    owner_id: Optional[int] = None
    department_id: Optional[int] = None
    due_date: Optional[date] = None


class IssueCreateIn(BaseModel):
    title: str = Field(max_length=200)
    description: str
    category: Optional[str] = None
    severity: Optional[int] = None
    department_id: Optional[int] = None
    check_id: Optional[int] = None
    # the failed check by key and department (the frontend has no check id)
    check_key: Optional[str] = Field(default=None, max_length=40)
    check_department_id: Optional[int] = None
    affected_part_id: Optional[int] = None
    affected_tool_ref: Optional[str] = Field(default=None, max_length=120)


class IssuePatchIn(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[int] = None
    department_id: Optional[int] = None
    affected_part_id: Optional[int] = None
    affected_tool_ref: Optional[str] = Field(default=None, max_length=120)
    customer_inform: Optional[bool] = None


class TextIn(BaseModel):
    text: Optional[str] = None
    containment: Optional[str] = None
    root_cause: Optional[str] = None


class RouteIn(BaseModel):
    route: str
    reason: str
    supplier_name: Optional[str] = Field(default=None, max_length=120)
    chargeback: Optional[bool] = None
    customer_inform: Optional[bool] = None
    actions: List[ActionIn] = []


class CustomerIn(BaseModel):
    decision: str
    note: str
    concession_until: Optional[date] = None
    # new_timing: the customer's new release date (updates release_due_date)
    new_release_due_date: Optional[date] = None
    new_date: Optional[date] = None          # alias


class CostIn(BaseModel):
    extra_cost: Optional[float] = Field(default=None, ge=0, le=1e10)
    cost_bearer: Optional[str] = None


class NoteIn(BaseModel):
    note: Optional[str] = None


class EscalateIn(BaseModel):
    reason: str
    level: Optional[int] = None


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
_ERRORS = (ChangeError, IssueForbidden, IssueNotFound, PlanForbidden, PlanConflict)


def _http(e: Exception) -> HTTPException:
    if isinstance(e, (IssueForbidden, PlanForbidden)):
        return HTTPException(status_code=403, detail=str(e))
    if isinstance(e, IssueNotFound):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, PlanConflict):
        if e.extra.get("not_found"):
            return HTTPException(status_code=404, detail=str(e))
        return HTTPException(status_code=409, detail={"message": str(e), **e.extra})
    return HTTPException(status_code=400, detail=str(e))


async def _change(db: AsyncSession, change_id: int, user: User):
    change = await ChangeService.get_change(db, change_id, viewer=user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


async def _run(db, change, user, coro):
    try:
        issue = await coro
    except _ERRORS as e:
        await db.rollback()
        raise _http(e)
    out = await Svc.out_one(db, change, issue, user)
    await db.commit()
    return out


BASE = "/{change_id}/validation/issues"


# ----------------------------------------------------------------------
# Reads
# ----------------------------------------------------------------------
@router.get(BASE)
async def list_issues(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await Svc.out_many(db, change, await Svc.list_issues(db, change),
                              current_user)


@router.get(BASE + "/summary")
async def issues_summary(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await Svc.summary(db, change)


@router.get(BASE + "/prefill")
async def issue_prefill(
    change_id: int, check_id: int = Query(...),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        return await Svc.prefill(db, change, check_id, current_user)
    except _ERRORS as e:
        raise _http(e)


@router.get(BASE + "/{iid}")
async def get_issue(
    change_id: int, iid: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        issue = await Svc.get_issue(db, change, iid)
    except _ERRORS as e:
        raise _http(e)
    return (await Svc.out_many(db, change, [issue], current_user))[0]


# ----------------------------------------------------------------------
# Writes
# ----------------------------------------------------------------------
@router.post(BASE, status_code=status.HTTP_201_CREATED)
async def create_issue(
    change_id: int, body: IssueCreateIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await _run(db, change, current_user,
                      Svc.create(db, change, body.model_dump(), current_user))


@router.patch(BASE + "/{iid}")
async def patch_issue(
    change_id: int, iid: int, body: IssuePatchIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await _run(db, change, current_user, Svc.update(
        db, change, iid, body.model_dump(exclude_unset=True), current_user))


@router.post(BASE + "/{iid}/contain")
async def contain_issue(
    change_id: int, iid: int, body: TextIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await _run(db, change, current_user, Svc.contain(
        db, change, iid, body.containment or body.text, current_user))


@router.post(BASE + "/{iid}/root-cause")
async def root_cause_issue(
    change_id: int, iid: int, body: TextIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await _run(db, change, current_user, Svc.set_root_cause(
        db, change, iid, body.root_cause or body.text, current_user))


@router.post(BASE + "/{iid}/route")
async def route_issue(
    change_id: int, iid: int, body: RouteIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    spec = body.model_dump()
    spec["actions"] = [a.model_dump() for a in body.actions]
    return await _run(db, change, current_user,
                      Svc.decide_route(db, change, iid, spec, current_user))


@router.post(BASE + "/{iid}/customer")
async def customer_issue(
    change_id: int, iid: int, body: CustomerIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await _run(db, change, current_user, Svc.customer_decision(
        db, change, iid, body.model_dump(), current_user))


@router.post(BASE + "/{iid}/cost")
async def cost_issue(
    change_id: int, iid: int, body: CostIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await _run(db, change, current_user, Svc.set_cost(
        db, change, iid, body.model_dump(), current_user))


@router.post(BASE + "/{iid}/fix-quoted")
async def fix_quoted_issue(
    change_id: int, iid: int, body: NoteIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await _run(db, change, current_user, Svc.mark_fix_quoted(
        db, change, iid, body.note, current_user))


@router.post(BASE + "/{iid}/actions", status_code=status.HTTP_201_CREATED)
async def add_issue_action(
    change_id: int, iid: int, body: ActionIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await _run(db, change, current_user, Svc.add_action(
        db, change, iid, body.model_dump(), current_user))


@router.post(BASE + "/{iid}/actions/{aid}/done")
async def issue_action_done(
    change_id: int, iid: int, aid: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await _run(db, change, current_user, Svc.action_done(
        db, change, iid, aid, current_user))


@router.post(BASE + "/{iid}/close")
async def close_issue(
    change_id: int, iid: int, body: NoteIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await _run(db, change, current_user, Svc.close(
        db, change, iid, body.note, current_user))


@router.post(BASE + "/{iid}/escalate")
async def escalate_issue(
    change_id: int, iid: int, body: EscalateIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await _run(db, change, current_user, Svc.escalate(
        db, change, iid, body.model_dump(), current_user))


@router.post(BASE + "/{iid}/deescalate")
async def deescalate_issue(
    change_id: int, iid: int, body: EscalateIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await _run(db, change, current_user, Svc.deescalate(
        db, change, iid, body.model_dump(), current_user))


@router.post(BASE + "/{iid}/escalations/{eid}/acknowledge")
async def acknowledge_issue_escalation(
    change_id: int, iid: int, eid: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await _run(db, change, current_user, Svc.acknowledge(
        db, change, iid, eid, current_user))
