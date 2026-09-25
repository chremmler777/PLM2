# backend/app/api/v1/changes/plan_offer.py
"""Costing to close: plan, offer, timing validation, deviations, release.

Mounted under the same /changes prefix as the lifecycle router. The services
own every rule; this module maps their three refusal kinds onto HTTP
(ChangeError -> 400, PlanForbidden -> 403, PlanConflict -> 409, or 404 when
the thing asked for is not on this change) and builds nothing itself.
"""
from datetime import date
from typing import Annotated, List, Optional, Union

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status,
)
from fastapi.responses import Response
from pydantic import AfterValidator, BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.services import plan_engine as eng
from app.services.change_plan_service import (
    ChangePlanService, PlanConflict, PlanForbidden,
)
from app.services.change_service import ChangeError, ChangeService
from app.services.offer_service import OfferService
from app.services.release_service import ReleaseService

router = APIRouter(prefix="/changes", tags=["changes"])


# ----------------------------------------------------------------------
# Request bodies
# ----------------------------------------------------------------------
def _plan_year(d: date) -> date:
    if not eng.MIN_YEAR <= d.year <= eng.MAX_YEAR:
        raise ValueError(f"dates lie between {eng.MIN_YEAR} and {eng.MAX_YEAR}")
    return d


# Plan dates, durations and lags within sane bounds (a year 9999 date or a
# million-day block only ever comes from a typo or a hostile client).
PlanDate = Annotated[date, AfterValidator(_plan_year)]
Days = Annotated[int, Field(le=eng.MAX_DURATION_DAYS)]
Lag = Annotated[int, Field(ge=-eng.MAX_LAG_DAYS, le=eng.MAX_LAG_DAYS)]


class PlanIn(BaseModel):
    plan: str = "quote"
    # after the baseline, scheduling moves dates: each move is a deviation
    reason: Optional[str] = None


class PlanSeedIn(BaseModel):
    plan: str = "quote"
    replace: bool = False


class TaskCreateIn(BaseModel):
    plan: str = "quote"
    name: str = Field(max_length=200)
    kind: str = "work"
    lane: Optional[str] = Field(default=None, max_length=80)
    department_id: Optional[int] = None
    start_date: PlanDate
    duration_days: Days = 0
    predecessors: List[int] = []
    is_idea: bool = False
    notes: Optional[str] = None
    parent_id: Optional[int] = None
    constraint_type: Optional[str] = None
    constraint_date: Optional[PlanDate] = None


class TaskPatchIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    kind: Optional[str] = None
    lane: Optional[str] = Field(default=None, max_length=80)
    department_id: Optional[int] = None
    start_date: Optional[PlanDate] = None
    duration_days: Optional[Days] = None
    predecessors: Optional[List[int]] = None
    is_idea: Optional[bool] = None
    sort_order: Optional[int] = None
    progress_pct: Optional[int] = None
    actual_start: Optional[PlanDate] = None
    actual_finish: Optional[PlanDate] = None
    notes: Optional[str] = None
    parent_id: Optional[int] = None
    constraint_type: Optional[str] = None
    constraint_date: Optional[PlanDate] = None
    reason: Optional[str] = None


class BulkItem(BaseModel):
    id: int
    start_date: Optional[PlanDate] = None
    duration_days: Optional[Days] = None


class BulkIn(BaseModel):
    plan: str = "quote"
    updates: List[BulkItem]
    reason: Optional[str] = None


class LinkIn(BaseModel):
    plan: str = "quote"
    from_task_id: int
    to_task_id: int
    type: str = "FS"
    lag_days: Lag = 0


class LinkPatchIn(BaseModel):
    type: Optional[str] = None
    lag_days: Optional[Lag] = None


class CalendarIn(BaseModel):
    mode: str = "calendar"
    workdays: List[int] = [1, 2, 3, 4, 5]
    holidays: List[PlanDate] = Field(default=[], max_length=eng.MAX_HOLIDAYS)
    # convert durations and lags when the mode changes (keeps real lengths)
    convert: bool = False
    # automatic scheduling: edits push the blocks their links drive; None
    # keeps the plan's current setting (default on)
    auto: Optional[bool] = None


# Batch ChangeSet. Ids of new blocks / links may be client temp ids
# (strings such as "tmp-3") referenced elsewhere in the same set.
TempId = Union[int, str]


class TaskUpsert(BaseModel):
    id: Optional[TempId] = None
    name: Optional[str] = Field(default=None, max_length=200)
    kind: Optional[str] = None
    lane: Optional[str] = Field(default=None, max_length=80)
    department_id: Optional[int] = None
    start_date: Optional[PlanDate] = None
    duration_days: Optional[Days] = None
    predecessors: Optional[List[TempId]] = None
    is_idea: Optional[bool] = None
    sort_order: Optional[int] = None
    progress_pct: Optional[int] = None
    actual_start: Optional[PlanDate] = None
    actual_finish: Optional[PlanDate] = None
    notes: Optional[str] = None
    parent_id: Optional[TempId] = None
    constraint_type: Optional[str] = None
    constraint_date: Optional[PlanDate] = None


class LinkUpsert(BaseModel):
    id: Optional[TempId] = None
    from_task_id: Optional[TempId] = None
    to_task_id: Optional[TempId] = None
    type: Optional[str] = None
    lag_days: Optional[Lag] = None


class ChangeSetIn(BaseModel):
    tasks_upsert: List[TaskUpsert] = []
    tasks_delete: List[int] = []
    links_upsert: List[LinkUpsert] = []
    links_delete: List[int] = []


class PlanChangesIn(BaseModel):
    plan: str = "quote"
    changes: ChangeSetIn
    reason: Optional[str] = None


class FeedbackIn(BaseModel):
    department_id: int
    verdict: str
    note: Optional[str] = None


class DeviationLockIn(BaseModel):
    note: Optional[str] = None


class DeviationEscalateIn(BaseModel):
    note: str


class OfferPatchIn(BaseModel):
    data: Optional[dict] = None
    currency: Optional[str] = None


class OfferSendIn(BaseModel):
    received_at: Optional[date] = None
    change_note: Optional[str] = None


class OfferReceivedIn(BaseModel):
    received_at: date


class ReleaseCheckIn(BaseModel):
    status: str
    note: Optional[str] = None


class LessonIn(BaseModel):
    title: str
    description: str
    category: str = "other"
    lesson_type: str = "improvement"
    severity: str = "medium"
    recommendation: Optional[str] = None


class LessonsCompleteIn(BaseModel):
    none_reason: Optional[str] = None


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _http(e: Exception) -> HTTPException:
    if isinstance(e, PlanForbidden):
        return HTTPException(status_code=403, detail=str(e))
    if isinstance(e, PlanConflict):
        if e.extra.get("not_found"):
            return HTTPException(status_code=404, detail=str(e))
        return HTTPException(status_code=409,
                             detail={"message": str(e), **e.extra})
    return HTTPException(status_code=400, detail=str(e))


_ERRORS = (ChangeError, PlanForbidden, PlanConflict)


async def _change(db: AsyncSession, change_id: int, user: User):
    change = await ChangeService.get_change(db, change_id, viewer=user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


async def _plan_out(db, change, plan, user):
    try:
        return await ChangePlanService.get_plan(db, change, plan, user)
    except _ERRORS as e:
        raise _http(e)


async def _require_offer_read(db, change, user):
    if not await OfferService.may_read(db, change, user):
        raise HTTPException(
            status_code=403,
            detail="Only Sales, Project Management, the change lead or an "
                   "admin may see the offer")


# ----------------------------------------------------------------------
# Plan
# ----------------------------------------------------------------------
@router.get("/{change_id}/plan")
async def get_plan(
    change_id: int, plan: str = Query("quote"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await _plan_out(db, change, plan, current_user)


@router.post("/{change_id}/plan/seed")
async def seed_plan(
    change_id: int, body: PlanSeedIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await ChangePlanService.seed(db, change, body.plan, current_user,
                                     replace=body.replace)
    except _ERRORS as e:
        raise _http(e)
    out = await _plan_out(db, change, body.plan, current_user)
    await db.commit()
    return out


@router.post("/{change_id}/plan/tasks")
async def add_plan_task(
    change_id: int, body: TaskCreateIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    spec = body.model_dump(exclude={"plan"})
    try:
        await ChangePlanService.add_task(db, change, body.plan, spec, current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await _plan_out(db, change, body.plan, current_user)
    await db.commit()
    return out


@router.patch("/{change_id}/plan/tasks")
async def bulk_update_plan_tasks(
    change_id: int, body: BulkIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await ChangePlanService.bulk_update(
            db, change, body.plan,
            [u.model_dump(exclude_unset=True) for u in body.updates],
            current_user, reason=body.reason)
    except _ERRORS as e:
        raise _http(e)
    out = await _plan_out(db, change, body.plan, current_user)
    await db.commit()
    return out


@router.patch("/{change_id}/plan/tasks/{task_id}")
async def update_plan_task(
    change_id: int, task_id: int, body: TaskPatchIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    spec = body.model_dump(exclude_unset=True)
    reason = spec.pop("reason", None)
    try:
        task = await ChangePlanService.update_task(
            db, change, task_id, spec, current_user, reason=reason)
    except _ERRORS as e:
        raise _http(e)
    out = await _plan_out(db, change, task.plan, current_user)
    await db.commit()
    return out


@router.delete("/{change_id}/plan/tasks/{task_id}")
async def delete_plan_task(
    change_id: int, task_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        task = await ChangePlanService._get_task(db, change, task_id)
        plan = task.plan
        await ChangePlanService.delete_task(db, change, task_id, current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await _plan_out(db, change, plan, current_user)
    await db.commit()
    return out


@router.post("/{change_id}/plan/schedule")
async def schedule_plan(
    change_id: int, body: PlanIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await ChangePlanService.schedule(db, change, body.plan, current_user,
                                         reason=body.reason)
    except _ERRORS as e:
        raise _http(e)
    out = await _plan_out(db, change, body.plan, current_user)
    await db.commit()
    return out


@router.post("/{change_id}/plan/links")
async def add_plan_link(
    change_id: int, body: LinkIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await ChangePlanService.add_link(
            db, change, body.plan, body.model_dump(exclude={"plan"}), current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await _plan_out(db, change, body.plan, current_user)
    await db.commit()
    return out


@router.patch("/{change_id}/plan/links/{link_id}")
async def update_plan_link(
    change_id: int, link_id: int, body: LinkPatchIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        link = await ChangePlanService.update_link(
            db, change, link_id, body.model_dump(exclude_unset=True), current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await _plan_out(db, change, link.plan, current_user)
    await db.commit()
    return out


@router.delete("/{change_id}/plan/links/{link_id}")
async def delete_plan_link(
    change_id: int, link_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        plan = await ChangePlanService.delete_link(db, change, link_id, current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await _plan_out(db, change, plan, current_user)
    await db.commit()
    return out


@router.put("/{change_id}/plan/calendar")
async def set_plan_calendar(
    change_id: int, body: CalendarIn, plan: str = Query("quote"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """The calendar of the plan `?plan=` (each plan has its own); answers
    that plan's PlanOut."""
    change = await _change(db, change_id, current_user)
    try:
        # only what the client sent: {"auto": false} alone keeps the calendar
        await ChangePlanService.set_calendar(
            db, change, body.model_dump(exclude_unset=True), current_user, plan=plan)
    except _ERRORS as e:
        raise _http(e)
    out = await _plan_out(db, change, plan, current_user)
    await db.commit()
    return out


@router.post("/{change_id}/plan/changes")
async def apply_plan_changes(
    change_id: int, body: PlanChangesIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """One ChangeSet, applied atomically: PlanOut plus `id_map` (temp task
    id -> real id) and `link_id_map` (temp link id -> real id)."""
    change = await _change(db, change_id, current_user)
    ch = body.changes
    changes = {
        "tasks_upsert": [u.model_dump(exclude_unset=True) for u in ch.tasks_upsert],
        "tasks_delete": list(ch.tasks_delete),
        "links_upsert": [u.model_dump(exclude_unset=True) for u in ch.links_upsert],
        "links_delete": list(ch.links_delete),
    }
    try:
        maps = await ChangePlanService.apply_changes(
            db, change, body.plan, changes, current_user, reason=body.reason)
    except _ERRORS as e:
        await db.rollback()
        raise _http(e)
    out = await _plan_out(db, change, body.plan, current_user)
    await db.commit()
    return {**out, **maps}


MAX_IMPORT_BYTES = 10 * 1024 * 1024


@router.post("/{change_id}/plan/import")
async def import_plan(
    change_id: int, file: UploadFile = File(...), plan: str = Form("quote"),
    replace: bool = Form(False),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """MS Project XML (MSPDI) into a plan; refused after the baseline.
    Answers the PlanOut plus `import_warnings` (what was skipped, and why)."""
    change = await _change(db, change_id, current_user)
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=400, detail="The file is larger than 10 MB")
    try:
        result = await ChangePlanService.import_mspdi(
            db, change, plan, content, current_user, replace=replace)
    except _ERRORS as e:
        await db.rollback()
        raise _http(e)
    out = await _plan_out(db, change, plan, current_user)
    await db.commit()
    return {**out, "import_warnings": result["warnings"]}


@router.get("/{change_id}/plan/export.xml")
async def export_plan_xml(
    change_id: int, plan: str = Query("quote"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    if plan not in ("quote", "detailed"):
        raise HTTPException(status_code=400, detail=f"Unknown plan '{plan}'")
    tasks = await ChangePlanService.tasks(db, change, plan)
    links = await ChangePlanService.links(db, change, plan)
    body = ChangePlanService.mspdi_xml(change, plan, tasks, links)
    return Response(content=body, media_type="application/xml", headers={
        "Content-Disposition":
            f'attachment; filename="{change.change_number}-{plan}.xml"'})


@router.get("/{change_id}/plan/export.csv")
async def export_plan_csv(
    change_id: int, plan: str = Query("quote"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    if plan not in ("quote", "detailed"):
        raise HTTPException(status_code=400, detail=f"Unknown plan '{plan}'")
    tasks = await ChangePlanService.tasks(db, change, plan)
    links = await ChangePlanService.links(db, change, plan)
    return Response(content=ChangePlanService.csv_export(tasks, links),
                    media_type="text/csv", headers={
                        "Content-Disposition":
                            f'attachment; filename="{change.change_number}-{plan}.csv"'})


@router.get("/{change_id}/plan/feedback")
async def get_plan_feedback(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await ChangePlanService.feedback_state(db, change)


@router.post("/{change_id}/plan/feedback")
async def post_plan_feedback(
    change_id: int, body: FeedbackIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await ChangePlanService.post_feedback(
            db, change, body.department_id, body.verdict, body.note, current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await ChangePlanService.feedback_state(db, change)
    await db.commit()
    return out


@router.post("/{change_id}/plan/validate-timing")
async def validate_timing(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Sets the baseline; returns the detailed PlanOut."""
    change = await _change(db, change_id, current_user)
    try:
        await ChangePlanService.validate_timing(db, change, current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await _plan_out(db, change, "detailed", current_user)
    await db.commit()
    return out


@router.get("/{change_id}/plan/deviations")
async def list_plan_deviations(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await ChangePlanService.list_deviations(db, change)


async def _deviation_out(db, change, did):
    return next((d for d in await ChangePlanService.list_deviations(db, change)
                 if d["id"] == did), None)


@router.post("/{change_id}/plan/deviations/{deviation_id}/lock")
async def lock_plan_deviation(
    change_id: int, deviation_id: int, body: DeviationLockIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await ChangePlanService.lock_deviation(
            db, change, deviation_id, body.note, current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await _deviation_out(db, change, deviation_id)
    await db.commit()
    return out


@router.post("/{change_id}/plan/deviations/{deviation_id}/escalate")
async def escalate_plan_deviation(
    change_id: int, deviation_id: int, body: DeviationEscalateIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await ChangePlanService.escalate_deviation(
            db, change, deviation_id, body.note, current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await _deviation_out(db, change, deviation_id)
    await db.commit()
    return out


# ----------------------------------------------------------------------
# Offers
# ----------------------------------------------------------------------
@router.get("/{change_id}/offers")
async def list_offers(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    await _require_offer_read(db, change, current_user)
    return await OfferService.serialize(
        db, change, await OfferService.list_offers(db, change))


async def _offer_out(db, change, offer):
    return (await OfferService.serialize(db, change, [offer]))[0]


@router.post("/{change_id}/offers", status_code=status.HTTP_201_CREATED)
async def create_offer(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        offer = await OfferService.create(db, change, current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await _offer_out(db, change, offer)
    await db.commit()
    return out


@router.patch("/{change_id}/offers/{offer_id}")
async def patch_offer(
    change_id: int, offer_id: int, body: OfferPatchIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        offer = await OfferService.get_offer(db, change, offer_id)
        await OfferService.patch(db, change, offer, current_user,
                                 data=body.data, currency=body.currency)
    except _ERRORS as e:
        raise _http(e)
    out = await _offer_out(db, change, offer)
    await db.commit()
    return out


@router.post("/{change_id}/offers/{offer_id}/refresh")
async def refresh_offer(
    change_id: int, offer_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        offer = await OfferService.get_offer(db, change, offer_id)
        await OfferService.refresh(db, change, offer, current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await _offer_out(db, change, offer)
    await db.commit()
    return out


@router.delete("/{change_id}/offers/{offer_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def discard_offer(
    change_id: int, offer_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Discard a draft offer (Sales, the change lead, admin)."""
    change = await _change(db, change_id, current_user)
    # Rights first: a non-writer learns nothing about which offer ids exist.
    if not await OfferService.may_write(db, change, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only Sales, the change lead or an admin may discard a draft offer")
    try:
        offer = await OfferService.get_offer(db, change, offer_id)
        await OfferService.discard(db, change, offer, current_user)
    except _ERRORS as e:
        raise _http(e)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{change_id}/offers/{offer_id}/send")
async def send_offer(
    change_id: int, offer_id: int, body: OfferSendIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        offer = await OfferService.get_offer(db, change, offer_id)
        await OfferService.send(db, change, offer, current_user,
                                received_at=body.received_at,
                                change_note=body.change_note)
    except _ERRORS as e:
        raise _http(e)
    out = await _offer_out(db, change, offer)
    await db.commit()
    return out


@router.post("/{change_id}/offers/{offer_id}/received")
async def offer_received(
    change_id: int, offer_id: int, body: OfferReceivedIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        offer = await OfferService.get_offer(db, change, offer_id)
        await OfferService.mark_received(db, change, offer, body.received_at,
                                         current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await _offer_out(db, change, offer)
    await db.commit()
    return out


@router.get("/{change_id}/offers/{offer_id}/pdf")
async def offer_pdf(
    change_id: int, offer_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    await _require_offer_read(db, change, current_user)
    try:
        offer = await OfferService.get_offer(db, change, offer_id)
    except _ERRORS as e:
        raise _http(e)
    pdf = await OfferService.pdf_bytes(db, change, offer)
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition":
            f'inline; filename="{change.change_number}-offer-v{offer.version}.pdf"'})


# ----------------------------------------------------------------------
# Release
# ----------------------------------------------------------------------
@router.get("/{change_id}/release")
async def get_release(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await ReleaseService.state(db, change)   # read-only


@router.post("/{change_id}/release/checks/{check_key}")
async def set_release_check(
    change_id: int, check_key: str, body: ReleaseCheckIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await ReleaseService.set_check(db, change, check_key, body.status,
                                       body.note, current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await ReleaseService.state(db, change)
    await db.commit()
    return out


@router.post("/{change_id}/lessons", status_code=status.HTTP_201_CREATED)
async def add_change_lesson(
    change_id: int, body: LessonIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        lesson = await ReleaseService.add_lesson(db, change, body.model_dump(),
                                                 current_user)
    except _ERRORS as e:
        raise _http(e)
    users = await ChangePlanService._user_names(db, [lesson.created_by])
    out = ReleaseService.lesson_out(lesson, users)
    await db.commit()
    return out


@router.post("/{change_id}/lessons/complete")
async def complete_change_lessons(
    change_id: int, body: LessonsCompleteIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await ReleaseService.complete_lessons(db, change, body.none_reason,
                                              current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await ReleaseService.state(db, change)
    await db.commit()
    return out
