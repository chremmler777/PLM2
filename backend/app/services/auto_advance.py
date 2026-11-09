"""Assessment & costing runs on its own (Christoph 2026-11-09).

"I think we closed scoping and it should run on its own; Sales should be
starting when all responsible departments finished costing; that is not
waiting necessarily for the PM to say we are done."

No "Close assessment" and no "Close costing" button on the main road any
more. After every department event that can complete the set (assessment
submit, costing finalize, "no cost", an override or routing decision) the
change is checked and moved as a system step, the actor being the user whose
act completed it:

1. in_assessment -> costing as soon as the existing hop is free (every
   first-stage R/A answer in, no "not feasible", no routing change waiting,
   no open check item, no HARD rule). Entering costing wakes the later
   routing stages (Summation & Budget), exactly as the manual close did.
2. costing -> quoting (customer changes only) once EVERY department with an
   assessment row on the change has submitted it (all stages, R/A/S/C, PM,
   Sales and consulted rows included; waived rows count as done) and every
   department that owes a costing input finalized it or said "no cost", and
   the hop is free of every guard (C5 costing not finalized, open index
   rechecks, supplier waits, gates, HARD rules). Rows of the quote stage
   itself ("Customer activities": Sales sends the quote) are not counted:
   that work starts with quote creation.

The 'costing' status stays (old changes, the internal approval of an
internal change, reports); the new flow passes through it. A department
that reopens its costing before quoting moves nothing back. A guard that
holds a hop is never bypassed: the change stays and the cockpit lists why
(transition_blocks, the same "Blocked by" list).
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeRequest

log = logging.getLogger(__name__)

# Switch: False brings back the PM's "Close assessment" / "Close costing".
ON = True

# The routing stage whose work IS the quote (Sales sends it): not owed
# before quote creation. Names as seeded (wf_seed_service ECM_BEWERTUNG).
QUOTE_STAGE_NAMES = ("Customer activities", "Quotation")
# Christoph 2026-11-09: the PM's "Review cost summary" row (Summation & Budget)
# does not hold the change: the PM's own finalized costing is enough.
PM_REVIEW_STAGE_NAMES = ("Summation & Budget",)
PM_DEPARTMENT = "Project Manager"

TEXT_COSTING = ("Automatically to costing: every first-stage assessment is in, "
                "the next routing stage is open")
TEXT_QUOTING = ("Automatically to Quote creation: all departments finished "
                "assessment and costing")

DONE_ROW = ("submitted", "waived")


def applies(change: ChangeRequest) -> bool:
    """The change runs this phase on its own (the cockpit hides the manual
    close and shows the progress instead)."""
    if not ON or change.status not in ("in_assessment", "costing"):
        return False
    from app.services import mother_plants as mp
    from app.services.engineering_review_service import is_review
    return not (mp.is_mother_plant(change) or is_review(change))


async def _stage_orders(session: AsyncSession, change: ChangeRequest, names) -> set[int]:
    from app.models.workflow import WfInstance, WfStage
    rows = (await session.execute(
        select(WfStage.stage_order)
        .join(WfInstance, WfInstance.template_id == WfStage.template_id)
        .where(WfInstance.change_id == change.id,
               WfInstance.status.in_(("active", "completed")),
               WfStage.name.in_(names)))).scalars().all()
    return set(rows)


async def counted_rows(session: AsyncSession, change: ChangeRequest) -> list:
    """The assessment rows that must be done before Quote creation: not the
    quote stage itself, not the PM's cost-summary review."""
    from app.models.workflow import Department
    skip = await _quote_stage_orders(session, change)
    pm_skip = await _stage_orders(session, change, PM_REVIEW_STAGE_NAMES)
    pm_id = (await session.execute(select(Department.id).where(
        Department.name == PM_DEPARTMENT))).scalar_one_or_none()
    return [a for a in change.assessments if a.stage_order not in skip
            and not (a.department_id == pm_id and a.stage_order in pm_skip)]


async def _quote_stage_orders(session: AsyncSession, change: ChangeRequest) -> set[int]:
    from app.models.workflow import WfInstance, WfStage
    rows = (await session.execute(
        select(WfStage.stage_order)
        .join(WfInstance, WfInstance.template_id == WfStage.template_id)
        .where(WfInstance.change_id == change.id,
               WfInstance.status.in_(("active", "completed")),
               WfStage.name.in_(QUOTE_STAGE_NAMES)))).scalars().all()
    return set(rows)


async def progress(session: AsyncSession, change: ChangeRequest) -> dict:
    """X of Y departments finished, and who is still open with what.

    {total, done, open: [{department_id, department_name, owner_name,
    open: 'assessment' | 'costing'}], ready}. A department is done when all
    its counted rows are submitted (or waived) and it owes no costing input,
    or finalized it / said no cost."""
    from app.services import early_costing
    from app.services.early_stage_service import EarlyStageService
    rows = await counted_rows(session, change)
    pending_costing = set(early_costing.state(change)["pending"])
    # 2026-11-09 night: a department that owes costing without a counted row
    # (the PM: its rows are the excluded review and the quote stage) is one
    # of the X of Y too; before, "8 of 8" showed while the PM's costing held
    # the hop.
    dept_ids = sorted({a.department_id for a in rows} | pending_costing)
    names = await EarlyStageService._dept_names(session, dept_ids)
    open_: list[dict] = []
    for d in dept_ids:
        mine = sorted((a for a in rows if a.department_id == d),
                      key=lambda a: (a.stage_order, a.id or 0))
        unanswered = [a for a in mine if a.effective_status not in DONE_ROW]
        if unanswered:
            what, row = "assessment", unanswered[0]
        elif d in pending_costing:
            what, row = "costing", (mine[0] if mine else None)
        else:
            continue
        open_.append({"department_id": d, "department_name": names.get(d),
                      "owner_name": row.effective_owner_name if row else None,
                      "open": what, "stage_order": row.stage_order if row else None})
    total = len(dept_ids)
    return {"total": total, "done": total - len(open_), "open": open_,
            "ready": total > 0 and not open_}


async def _hop_free(session: AsyncSession, change: ChangeRequest, to: str) -> Optional[str]:
    """None when the hop would go through today, else why not (the HARD
    rule, or the first soft rule no approved override covers)."""
    from app.services.change_service import ALLOWED_TRANSITIONS
    from app.services.early_stage_service import EarlyStageService
    if to not in ALLOWED_TRANSITIONS.get(change.status, set()):
        return f"'{change.status}' does not go to '{to}'"
    hard = await EarlyStageService.hard_refusal(session, change, to)
    if hard is not None:
        return str(hard)
    block = (await EarlyStageService.transition_blocks(session, change)).get(to)
    return str(block["reason"]) if block else None


def target(change: ChangeRequest) -> Optional[str]:
    """The hop the automation would take next."""
    if change.status == "in_assessment":
        return "costing"
    if change.status == "costing" and change.customer_relevant:
        return "quoting"
    return None


async def state(session: AsyncSession, change: ChangeRequest) -> Optional[dict]:
    """The cockpit's line: progress plus what holds the move once everybody
    is done. None when the change does not run on its own now."""
    if not applies(change):
        return None
    p = await progress(session, change)
    to = target(change)
    held = None
    if to == "costing":
        held = await _hop_free(session, change, "costing")
    elif to == "quoting" and p["ready"]:
        held = await _hop_free(session, change, "quoting")
    return {**p, "to": to, "held_by": held,
            # the end of the road: quote creation, or (internal) the approval
            "final": "quoting" if change.customer_relevant else "approved"}


async def _hop(session: AsyncSession, change: ChangeRequest, to: str,
               actor_id: int, text: str) -> bool:
    from app.services.change_service import ChangeError, ChangeService
    try:
        async with session.begin_nested():
            await ChangeService.transition(session, change, to, actor_id)
            await ChangeService.append_changelog(
                session, change, "auto_advanced", text, actor_id,
                field_name="status", new_value=to)
    except ChangeError as e:        # a rule the precheck did not see
        log.info("auto advance of change %s to %s held: %s", change.id, to, e)
        return False
    return True


async def maybe_advance(session: AsyncSession, change: ChangeRequest,
                        actor_id: int) -> Optional[str]:
    """Take the next automatic hop if it is due and free; the status moved
    to, else None. One hop per call (the caller reloads and asks again)."""
    if not applies(change):
        return None
    to = target(change)
    if to is None:
        return None
    if to == "quoting" and not (await progress(session, change))["ready"]:
        return None
    if await _hop_free(session, change, to) is not None:
        return None
    ok = await _hop(session, change, to, actor_id,
                    TEXT_COSTING if to == "costing" else TEXT_QUOTING)
    return to if ok else None


async def run_after(session: AsyncSession, change_id: int, actor) -> list[str]:
    """After a committed department event: move the change on as far as it
    goes (at most both hops), each hop its own commit. Never fails the
    caller's request: a refusal or error leaves the change where it was."""
    moved: list[str] = []
    actor_id = getattr(actor, "id", actor)
    try:
        for _ in range(2):
            # fresh rows (tasks the last hop woke), without expiring the
            # caller's objects (its user is still read after this)
            change = (await session.execute(
                select(ChangeRequest).where(ChangeRequest.id == change_id)
                .execution_options(populate_existing=True))).scalar_one_or_none()
            if change is None:
                break
            to = await maybe_advance(session, change, actor_id)
            if to is None:
                break
            await session.commit()
            moved.append(to)
    except Exception:               # pragma: no cover - logged, never raised
        log.exception("auto advance of change %s failed", change_id)
        await session.rollback()
    return moved
