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
    ChangePlanService, PlanConflict, PlanForbidden, PlanRuleError,
)
from app.services.change_service import ChangeError, ChangeService
from app.services import plan_quote, plan_rules
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
    # Spec §6 [R3]: an open high risk the offer does not price goes out only
    # with a reason pick (offer_service.HIGH_RISK_SEND_REASONS) + a sentence.
    risk_reason_code: Optional[str] = None
    risk_reason: Optional[str] = None
    # F3 (SOFT): hours without a labour rate go out only with a reason pick
    # (offer_service.NO_RATE_SEND_REASONS) + a sentence
    rate_reason_code: Optional[str] = None
    rate_reason: Optional[str] = None


class OfferReceivedIn(BaseModel):
    received_at: date


class ReleaseCheckIn(BaseModel):
    status: str
    note: Optional[str] = None
    # Only on 'done' of an item that carries a value: the cycle time
    # (outcome changed | unchanged, value = new seconds when changed) and the
    # process-stable row (value = measured Cm, optional).
    outcome: Optional[str] = None
    value: Optional[float] = None


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
    if isinstance(e, PlanRuleError):          # a plan rule with a code
        return HTTPException(status_code=400,
                             detail={"message": str(e), "code": e.code})
    return HTTPException(status_code=400, detail=str(e))


_ERRORS = (ChangeError, PlanForbidden, PlanConflict)


async def _change(db: AsyncSession, change_id: int, user: User):
    change = await ChangeService.get_change(db, change_id, viewer=user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


async def _plan_out(db, change, plan, user):
    try:
        out = await ChangePlanService.get_plan(db, change, plan, user)
    except _ERRORS as e:
        raise _http(e)
    # Christoph 2026-11-09: the planning rules (plan_rules) in the issues
    # list, each block's rule role, and whether the plan may be reset
    ev = await plan_rules.evaluate(db, change, plan)
    rule_issues = plan_rules.as_issues(ev["violations"])
    out["validation"]["errors"] = rule_issues["errors"] + out["validation"]["errors"]
    out["validation"]["warnings"] = rule_issues["warnings"] + out["validation"]["warnings"]
    for t in out["tasks"]:
        t["rule_role"] = ev["roles"].get(t["id"])
        t["source_tag"] = ev["tags"].get(t.get("source_position_id"))
    editor = await ChangePlanService.is_editor(db, change, user)
    out["plan_editor"] = editor
    # real time vs the Sales buffer (Sales/PM see both, the customer the total)
    out["timing"] = plan_quote.timing_summary(
        await ChangePlanService.tasks(db, change, plan),
        ChangePlanService.calendar(change, plan))
    plan_quote.mark_estimates(out)
    out["reset_blocked_reason"] = plan_rules.reset_blocked_reason(change, plan, editor)
    return out


async def _rules_before(db, change, plan) -> set:
    """The rule violations before a write (see _rules_after)."""
    return await plan_rules.snapshot(db, change, plan)


async def _rules_after(db, change, plan, before: set) -> None:
    """Refuse (400, code) a write that created a new planning-rule
    violation between committed blocks; nothing of it is kept."""
    try:
        await plan_rules.refuse_new(db, change, plan, before)
    except PlanRuleError as e:
        await db.rollback()
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


@router.post("/{change_id}/plan/reset")
async def reset_plan(
    change_id: int, body: PlanIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Christoph 2026-11-09: delete every block of the plan and seed it
    again (quote: from the costing, detailed: from the quote plan). Refused
    once the customer accepted the quote plan or timing was validated."""
    change = await _change(db, change_id, current_user)
    try:
        await plan_rules.reset_plan(db, change, body.plan, current_user,
                                    reseed=True)
    except _ERRORS as e:
        await db.rollback()
        raise _http(e)
    out = await _plan_out(db, change, body.plan, current_user)
    await db.commit()
    return out


class SalesBufferIn(BaseModel):
    plan: str = "quote"
    weeks: float = Field(ge=0, le=plan_quote.MAX_BUFFER_WEEKS)


@router.put("/{change_id}/plan/sales-buffer")
async def set_sales_buffer(
    change_id: int, body: SalesBufferIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Christoph 2026-11-09: the ONE buffer at the end of the plan, in weeks
    (resizes the end buffer block, or adds one after the real work)."""
    change = await _change(db, change_id, current_user)
    before = await _rules_before(db, change, body.plan)
    try:
        await plan_quote.set_sales_buffer(db, change, body.plan, body.weeks, current_user)
    except _ERRORS as e:
        await db.rollback()
        raise _http(e)
    await _rules_after(db, change, body.plan, before)
    moved = ChangePlanService.take_moved(change)
    out = await _plan_out(db, change, body.plan, current_user)
    await db.commit()
    return {**out, "moved_ids": moved}


@router.delete("/{change_id}/plan")
async def delete_plan(
    change_id: int, plan: str = Query("quote"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Christoph 2026-11-09: delete every block (the plan stays, empty; the
    seed button is offered again). Same refusals as the reset."""
    change = await _change(db, change_id, current_user)
    try:
        await plan_rules.reset_plan(db, change, plan, current_user,
                                    reseed=False)
    except _ERRORS as e:
        await db.rollback()
        raise _http(e)
    out = await _plan_out(db, change, plan, current_user)
    await db.commit()
    return out


@router.post("/{change_id}/plan/tasks")
async def add_plan_task(
    change_id: int, body: TaskCreateIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    spec = body.model_dump(exclude={"plan"})
    before = await _rules_before(db, change, body.plan)
    try:
        await ChangePlanService.add_task(db, change, body.plan, spec, current_user)
    except _ERRORS as e:
        raise _http(e)
    await _rules_after(db, change, body.plan, before)
    out = await _plan_out(db, change, body.plan, current_user)
    await db.commit()
    return out


@router.patch("/{change_id}/plan/tasks")
async def bulk_update_plan_tasks(
    change_id: int, body: BulkIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    before = await _rules_before(db, change, body.plan)
    try:
        await ChangePlanService.bulk_update(
            db, change, body.plan,
            [u.model_dump(exclude_unset=True) for u in body.updates],
            current_user, reason=body.reason)
    except _ERRORS as e:
        raise _http(e)
    await _rules_after(db, change, body.plan, before)
    # moved_ids: what the server moved by itself, not the blocks sent
    moved = ChangePlanService.take_moved(change, [u.id for u in body.updates])
    out = await _plan_out(db, change, body.plan, current_user)
    await db.commit()
    return {**out, "moved_ids": moved}


@router.patch("/{change_id}/plan/tasks/{task_id}")
async def update_plan_task(
    change_id: int, task_id: int, body: TaskPatchIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    spec = body.model_dump(exclude_unset=True)
    reason = spec.pop("reason", None)
    try:
        plan = (await ChangePlanService._get_task(db, change, task_id)).plan
        before = await _rules_before(db, change, plan)
        task = await ChangePlanService.update_task(
            db, change, task_id, spec, current_user, reason=reason)
    except _ERRORS as e:
        raise _http(e)
    await _rules_after(db, change, plan, before)
    moved = ChangePlanService.take_moved(change, [task_id])
    out = await _plan_out(db, change, task.plan, current_user)
    await db.commit()
    return {**out, "moved_ids": moved}


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
    before = await _rules_before(db, change, body.plan)
    try:
        await ChangePlanService.schedule(db, change, body.plan, current_user,
                                         reason=body.reason)
    except _ERRORS as e:
        raise _http(e)
    await _rules_after(db, change, body.plan, before)
    moved = ChangePlanService.take_moved(change)
    out = await _plan_out(db, change, body.plan, current_user)
    await db.commit()
    return {**out, "moved_ids": moved}


@router.post("/{change_id}/plan/links")
async def add_plan_link(
    change_id: int, body: LinkIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    before = await _rules_before(db, change, body.plan)
    try:
        await ChangePlanService.add_link(
            db, change, body.plan, body.model_dump(exclude={"plan"}), current_user)
    except _ERRORS as e:
        raise _http(e)
    await _rules_after(db, change, body.plan, before)
    moved = ChangePlanService.take_moved(change)
    out = await _plan_out(db, change, body.plan, current_user)
    await db.commit()
    return {**out, "moved_ids": moved}


@router.patch("/{change_id}/plan/links/{link_id}")
async def update_plan_link(
    change_id: int, link_id: int, body: LinkPatchIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        link_plan = (await ChangePlanService._get_link(db, change, link_id)).plan
        before = await _rules_before(db, change, link_plan)
        link = await ChangePlanService.update_link(
            db, change, link_id, body.model_dump(exclude_unset=True), current_user)
    except _ERRORS as e:
        raise _http(e)
    await _rules_after(db, change, link_plan, before)
    moved = ChangePlanService.take_moved(change)
    out = await _plan_out(db, change, link.plan, current_user)
    await db.commit()
    return {**out, "moved_ids": moved}


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
    before = await _rules_before(db, change, plan) if plan in ("quote", "detailed") else set()
    try:
        # only what the client sent: {"auto": false} alone keeps the calendar
        await ChangePlanService.set_calendar(
            db, change, body.model_dump(exclude_unset=True), current_user, plan=plan)
    except _ERRORS as e:
        raise _http(e)
    await _rules_after(db, change, plan, before)
    moved = ChangePlanService.take_moved(change)
    out = await _plan_out(db, change, plan, current_user)
    await db.commit()
    return {**out, "moved_ids": moved}


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
    before = await _rules_before(db, change, body.plan)
    try:
        maps = await ChangePlanService.apply_changes(
            db, change, body.plan, changes, current_user, reason=body.reason)
    except _ERRORS as e:
        await db.rollback()
        raise _http(e)
    await _rules_after(db, change, body.plan, before)
    # moved_ids: what the server moved by itself, not the blocks sent
    sent = [u["id"] for u in changes["tasks_upsert"]
            if isinstance(u.get("id"), int) and not isinstance(u.get("id"), bool)]
    moved = ChangePlanService.take_moved(change, sent + list(maps["id_map"].values()))
    out = await _plan_out(db, change, body.plan, current_user)
    await db.commit()
    return {**out, **maps, "moved_ids": moved}


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
    return await ChangePlanService.feedback_state(db, change, current_user)


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
    out = await ChangePlanService.feedback_state(db, change, current_user)
    await db.commit()
    return out


@router.post("/{change_id}/plan/validate-timing")
async def validate_timing(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Sets the baseline; returns the detailed PlanOut."""
    change = await _change(db, change_id, current_user)
    broken = [v for v in (await plan_rules.evaluate(db, change, "detailed"))["violations"]
              if not v["idea"]]
    if broken:
        raise HTTPException(status_code=400, detail={
            "message": "The detailed plan breaks a planning rule: "
                       + "; ".join(v["message"] for v in broken),
            "code": broken[0]["code"]})
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


async def _group_out(db, change, gid):
    """The group's rows as list_deviations shows them."""
    return [d for d in await ChangePlanService.list_deviations(db, change)
            if d["group_id"] == gid]


@router.post("/{change_id}/plan/deviations/groups/{group_id}/lock")
async def lock_plan_deviation_group(
    change_id: int, group_id: int, body: DeviationLockIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Lock every open deviation of one move in one transaction."""
    change = await _change(db, change_id, current_user)
    try:
        await ChangePlanService.lock_group(
            db, change, group_id, body.note, current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await _group_out(db, change, group_id)
    await db.commit()
    return out


@router.post("/{change_id}/plan/deviations/groups/{group_id}/escalate")
async def escalate_plan_deviation_group(
    change_id: int, group_id: int, body: DeviationEscalateIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Escalate every open deviation of one move under one escalation."""
    change = await _change(db, change_id, current_user)
    try:
        await ChangePlanService.escalate_group(
            db, change, group_id, body.note, current_user)
    except _ERRORS as e:
        raise _http(e)
    out = await _group_out(db, change, group_id)
    await db.commit()
    return out


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
                                change_note=body.change_note,
                                risk_reason_code=body.risk_reason_code,
                                risk_reason=body.risk_reason,
                                rate_reason_code=body.rate_reason_code,
                                rate_reason=body.rate_reason)
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
    # The data is read here; reportlab (CPU-bound, ~100 ms and more) runs in
    # the thread pool so it never blocks the event loop. A version that went
    # out is served from the in-process cache after its first render.
    try:
        ctx, key = await OfferService.pdf_context(db, change, offer, current_user)
    except _ERRORS as e:
        raise _http(e)
    pdf = OfferService.pdf_cache_get(key)
    if pdf is None:
        from starlette.concurrency import run_in_threadpool
        from app.services.offer_pdf import render_offer_pdf
        pdf = await run_in_threadpool(render_offer_pdf, ctx)
        OfferService.pdf_cache_put(key, pdf)
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition":
            f'inline; filename="{change.change_number}-offer-v{offer.version}.pdf"'})


@router.get("/{change_id}/offers/{offer_id}/package")
async def offer_package(
    change_id: int, offer_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Christoph 2026-11-09: everything Sales hands over as one ZIP: the
    customer offer PDF, the internal breakdown (CSV: who is doing what,
    markup, margin) and every supplier quote file of the chosen / favourite
    quotes, named "<department> - <vendor> - <line>.<ext>". Price readers only."""
    import csv
    import io
    import zipfile
    change = await _change(db, change_id, current_user)
    await _require_offer_read(db, change, current_user)
    try:
        offer = await OfferService.get_offer(db, change, offer_id)
        ctx, key = await OfferService.pdf_context(db, change, offer, current_user)
        pkg = await OfferService.package_files(db, change, offer)
    except _ERRORS as e:
        raise _http(e)
    from starlette.concurrency import run_in_threadpool
    pdf = OfferService.pdf_cache_get(key)
    if pdf is None:
        from app.services.offer_pdf import render_offer_pdf
        pdf = await run_in_threadpool(render_offer_pdf, ctx)
        OfferService.pdf_cache_put(key, pdf)
    stem = f"{change.change_number}-offer-v{offer.version}"

    def build() -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{stem}.pdf", pdf)
            text = io.StringIO()
            csv.writer(text).writerows(pkg["breakdown_rows"])
            # utf-8-sig: Excel reads the umlauts
            z.writestr(f"{stem}-internal-breakdown.csv", text.getvalue().encode("utf-8-sig"))
            for name, path in pkg["files"]:
                z.write(path, name)
            if pkg["missing"]:
                z.writestr("supplier-quotes/MISSING.txt",
                           "Listed on the costing, file not found on the server:\n"
                           + "\n".join(pkg["missing"]) + "\n")
        return buf.getvalue()

    data = await run_in_threadpool(build)
    return Response(content=data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{stem}-package.zip"'})


# ----------------------------------------------------------------------
# Release
# ----------------------------------------------------------------------
@router.get("/{change_id}/release")
async def get_release(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    return await ReleaseService.state(db, change, current_user)   # read-only


@router.post("/{change_id}/release/checks/{check_key}")
async def set_release_check(
    change_id: int, check_key: str, body: ReleaseCheckIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await ReleaseService.set_check(db, change, check_key, body.status,
                                       body.note, current_user,
                                       outcome=body.outcome, value=body.value)
    except _ERRORS as e:
        raise _http(e)
    out = await ReleaseService.state(db, change, current_user)
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


# ----------------------------------------------------------------------
# §6 [R3] scope change cards (COMMERCIAL_V2)
# ----------------------------------------------------------------------
class ScopeChangeIn(BaseModel):
    what: str = Field(max_length=2000)
    part_number: Optional[str] = Field(default=None, max_length=100)
    expects_by: Optional[date] = None
    attachment_id: Optional[int] = None
    ref: Optional[str] = Field(default=None, max_length=255)
    # an internal upload picked as the customer's (re-tagged, logged)
    from_customer: bool = False


class ScopeDecideIn(BaseModel):
    decision: str                     # accept | refuse | new_change
    department_ids: Optional[list[int]] = None
    note: Optional[str] = Field(default=None, max_length=2000)


class ScopeRecostedIn(BaseModel):
    department_id: int
    # R4: the costing moved, or "no cost impact" and why
    no_cost_note: Optional[str] = Field(default=None, max_length=500)


class ScopeToldIn(BaseModel):
    ref: str = Field(max_length=255)


class ScopeAskIn(BaseModel):
    text: str = Field(max_length=1000)


class ScopeAnswerIn(BaseModel):
    answer: str = Field(max_length=1000)
    attachment_id: Optional[int] = None
    ref: Optional[str] = Field(default=None, max_length=255)
    from_customer: bool = False


def _scope_http(e: Exception) -> HTTPException:
    from app.services.scope_change_service import ScopeChangeForbidden
    if isinstance(e, ScopeChangeForbidden):
        return HTTPException(status_code=403, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


async def _scope_out(db, change):
    from app.services.scope_change_service import ScopeChangeService
    return await ScopeChangeService.serialize(db, change)


@router.get("/{change_id}/scope-changes")
async def list_scope_changes(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Every scope change card of the change (no prices in it)."""
    change = await _change(db, change_id, current_user)
    return await _scope_out(db, change)


@router.post("/{change_id}/scope-changes")
async def request_scope_change(
    change_id: int, body: ScopeChangeIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Sales: "Customer wants to add or change something" (from quoted on)."""
    from app.services.scope_change_service import ScopeChangeService
    change = await _change(db, change_id, current_user)
    try:
        await ScopeChangeService.request(
            db, change, current_user, what=body.what, part_number=body.part_number,
            expects_by=body.expects_by, attachment_id=body.attachment_id, ref=body.ref,
            from_customer=body.from_customer)
    except ChangeError as e:
        raise _scope_http(e)
    await db.commit()
    return await _scope_out(db, change)


@router.post("/{change_id}/scope-changes/{card_id}/decide")
async def decide_scope_change(
    change_id: int, card_id: int, body: ScopeDecideIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """The lead: accept (departments re-cost), refuse, or (after approval,
    an added part) its own linked change."""
    from app.services.scope_change_service import ScopeChangeService
    change = await _change(db, change_id, current_user)
    try:
        await ScopeChangeService.decide(
            db, change, card_id, current_user, body.decision,
            department_ids=body.department_ids, note=body.note)
    except ChangeError as e:
        raise _scope_http(e)
    await db.commit()
    return await _scope_out(db, change)


@router.post("/{change_id}/scope-changes/{card_id}/recosted")
async def scope_change_recosted(
    change_id: int, card_id: int, body: ScopeRecostedIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """A department's re-costing of the card is done."""
    from app.services.scope_change_service import ScopeChangeService
    change = await _change(db, change_id, current_user)
    try:
        await ScopeChangeService.recosted(db, change, card_id, current_user,
                                          body.department_id, no_cost_note=body.no_cost_note)
    except ChangeError as e:
        raise _scope_http(e)
    await db.commit()
    return await _scope_out(db, change)


@router.post("/{change_id}/scope-changes/{card_id}/question")
async def scope_change_question(
    change_id: int, card_id: int, body: ScopeAskIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Missing info on a requested card: a question to the customer (Sales
    asks; it holds the accept)."""
    from app.services.scope_change_service import ScopeChangeService
    change = await _change(db, change_id, current_user)
    try:
        await ScopeChangeService.ask(db, change, card_id, current_user, body.text)
    except ChangeError as e:
        raise _scope_http(e)
    await db.commit()
    return await _scope_out(db, change)


@router.post("/{change_id}/scope-changes/{card_id}/answer")
async def scope_change_answer(
    change_id: int, card_id: int, body: ScopeAnswerIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Sales files the customer's answer to the card's question."""
    from app.services.scope_change_service import ScopeChangeService
    change = await _change(db, change_id, current_user)
    try:
        await ScopeChangeService.answer(
            db, change, card_id, current_user, body.answer,
            attachment_id=body.attachment_id, ref=body.ref,
            from_customer=body.from_customer)
    except ChangeError as e:
        raise _scope_http(e)
    await db.commit()
    return await _scope_out(db, change)


@router.post("/{change_id}/scope-changes/{card_id}/told")
async def scope_change_told(
    change_id: int, card_id: int, body: ScopeToldIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Sales told the customer: the scope change is refused, or (re-costed
    at no cost everywhere) it comes at no price change."""
    from app.services.scope_change_service import ScopeChangeService
    change = await _change(db, change_id, current_user)
    try:
        await ScopeChangeService.told(db, change, card_id, current_user, body.ref)
    except ChangeError as e:
        raise _scope_http(e)
    await db.commit()
    return await _scope_out(db, change)


# ----------------------------------------------------------------------
# §7a start at risk (START_AT_RISK)
# ----------------------------------------------------------------------
class StartAtRiskIn(BaseModel):
    attachment_id: Optional[int] = None
    ref: Optional[str] = Field(default=None, max_length=255)
    from_customer: bool = False


class StartAtRiskQualityIn(BaseModel):
    note: str = Field(max_length=500)


def _sar_http(e: Exception) -> HTTPException:
    from app.services.start_at_risk_service import StartAtRiskForbidden
    if isinstance(e, StartAtRiskForbidden):
        return HTTPException(status_code=403, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


@router.get("/{change_id}/start-at-risk")
async def start_at_risk_state(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.start_at_risk_service import StartAtRiskService
    change = await _change(db, change_id, current_user)
    return await StartAtRiskService.state(db, change)


@router.post("/{change_id}/start-at-risk")
async def request_start_at_risk(
    change_id: int, body: StartAtRiskIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Sales or the run team: the customer's go-ahead before the PO."""
    from app.services.start_at_risk_service import StartAtRiskService
    change = await _change(db, change_id, current_user)
    try:
        await StartAtRiskService.request(db, change, current_user,
                                         attachment_id=body.attachment_id, ref=body.ref,
                                         from_customer=body.from_customer)
    except ChangeError as e:
        raise _sar_http(e)
    await db.commit()
    return await StartAtRiskService.state(db, change)


@router.post("/{change_id}/start-at-risk/quality")
async def start_at_risk_quality(
    change_id: int, body: StartAtRiskQualityIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Quality: one line of quality risks."""
    from app.services.start_at_risk_service import StartAtRiskService
    change = await _change(db, change_id, current_user)
    try:
        await StartAtRiskService.quality_line(db, change, current_user, body.note)
    except ChangeError as e:
        raise _sar_http(e)
    await db.commit()
    return await StartAtRiskService.state(db, change)


class StartAtRiskRefuseIn(BaseModel):
    note: str = Field(max_length=500)


@router.post("/{change_id}/start-at-risk/refuse")
async def refuse_start_at_risk(
    change_id: int, body: StartAtRiskRefuseIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """A Project Management member (or an admin) says no, with why."""
    from app.services.start_at_risk_service import StartAtRiskService
    change = await _change(db, change_id, current_user)
    try:
        await StartAtRiskService.refuse(db, change, current_user, body.note)
    except ChangeError as e:
        raise _sar_http(e)
    await db.commit()
    return await StartAtRiskService.state(db, change)


@router.post("/{change_id}/start-at-risk/approve")
async def approve_start_at_risk(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """A Project Management member (second: an admin), never the asker."""
    from app.services.start_at_risk_service import StartAtRiskService
    change = await _change(db, change_id, current_user)
    try:
        await StartAtRiskService.approve(db, change, current_user)
    except ChangeError as e:
        raise _sar_http(e)
    await db.commit()
    return await StartAtRiskService.state(db, change)
