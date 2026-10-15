"""Waiting on a supplier (ECR-solid spec §4 "one state everywhere", §5,
§8; switch ASSESSMENT_V2).

A department records that it waits on a supplier: vendor, asked on,
expected by. Costing phase (in_assessment, costing): a supplier quote;
implementation phase (approved, in_implementation): the supplier's
delivery (a tool change). While open:
- it is the one wait besides the customer's that pauses the late clock
  (spec §0): the department's costing task is due at expected-by;
- its costing does not finalize ("Waiting on FZ until 3 Nov"), nor may it
  say "<Dept> has no cost";
- close costing (C5) lists it, and the lead picks "Wait for FZ (3 Nov)"
  (nothing to do) or "Price on estimate" (closes it; the department is told
  to finalize on its estimate);
- the header reads "Waiting on FZ since 21 Oct" with "day 9 of 21";
- in implementation it pauses the department's progress-report cadence
  (C23).
A wait ends when the quote or delivery is in, when the lead prices on an
estimate, or when it is not needed."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.display import fmt_date
from app.models.change import ChangeRequest
from app.models.change_cost import (
    SUPPLIER_WAIT_ENDS, CostingPosition, SupplierWait)
from app.models.entities import User
from app.models.workflow import Department
from app.services import cm_switches
from app.utils.clock import business_today

COSTING_STATUSES = ("in_assessment", "costing")
IMPLEMENTATION_STATUSES = ("approved", "in_implementation")


class SupplierWaitError(ValueError):
    """Refused; 400 (403 for SupplierWaitForbidden)."""


class SupplierWaitForbidden(SupplierWaitError):
    pass


def phase_of(change: ChangeRequest) -> Optional[str]:
    if change.status in COSTING_STATUSES:
        return "costing"
    if change.status in IMPLEMENTATION_STATUSES:
        return "implementation"
    return None


async def open_waits(session: AsyncSession, change_ids: list[int],
                     phase: Optional[str] = None) -> list[SupplierWait]:
    """Every open wait of these changes (one query), oldest first."""
    if not change_ids:
        return []
    q = select(SupplierWait).where(SupplierWait.change_id.in_(change_ids),
                                   SupplierWait.closed_at.is_(None))
    if phase is not None:
        q = q.where(SupplierWait.phase == phase)
    return list((await session.execute(
        q.order_by(SupplierWait.asked_on, SupplierWait.id))).scalars().all())


async def current_waits(session: AsyncSession,
                        changes: list[ChangeRequest]) -> list[SupplierWait]:
    """The open waits of the phase each change is in now (one query): what
    the header and the digest say. A costing wait outlives costing in the
    table but not on screen; a change back in costing shows it again."""
    phase = {c.id: phase_of(c) for c in changes}
    ids = [cid for cid, ph in phase.items() if ph is not None]
    return [w for w in await open_waits(session, ids) if w.phase == phase[w.change_id]]


async def open_by_department(session: AsyncSession, change_ids: list[int],
                             phase: str) -> dict[tuple[int, int], SupplierWait]:
    """{(change id, department id): its latest-expected open wait}."""
    out: dict[tuple[int, int], SupplierWait] = {}
    for w in await open_waits(session, change_ids, phase):
        key = (w.change_id, w.department_id)
        if key not in out or w.expected_by > out[key].expected_by:
            out[key] = w
    return out


def line(w: SupplierWait, dept_name: Optional[str] = None) -> str:
    """'Waiting on FZ until 3 Nov (Toolshop)'."""
    return (f"Waiting on {w.vendor_name} until {fmt_date(w.expected_by)}"
            + (f" ({dept_name})" if dept_name else ""))


async def _may_act(session: AsyncSession, change: ChangeRequest,
                   department_id: int, actor: User) -> bool:
    from app.services.early_costing import _may_act as costing_may_act
    return await costing_may_act(session, change, department_id, actor)


async def _may_decide(session: AsyncSession, change: ChangeRequest, actor: User) -> bool:
    """The run team (lead, PM member, admin): §5 "Price on estimate"."""
    from app.services.change_people import holds_lead
    from app.services.meeting_service import MeetingService
    return (actor.effective_role == "admin" or holds_lead(change, actor)
            or await MeetingService.user_is_pm_member(session, actor))


async def create(session: AsyncSession, change: ChangeRequest, actor: User, *,
                 department_id: int, vendor_name: str, asked_on: date,
                 expected_by: date, position_id: Optional[int] = None,
                 note: Optional[str] = None) -> SupplierWait:
    from app.services.change_service import ChangeService
    if not cm_switches.on("ASSESSMENT_V2"):
        raise SupplierWaitError("Supplier waits are switched off (ASSESSMENT_V2)")
    phase = phase_of(change)
    if phase is None:
        raise SupplierWaitError(
            "A supplier wait is recorded while costing (assessment, costing) "
            "or implementing (approved, in implementation)")
    if not await _may_act(session, change, department_id, actor):
        raise SupplierWaitForbidden(
            "Only a member of that department, Project Management or an admin "
            "records its supplier wait")
    # R25: an inactive or unknown department grants nothing, and a wait
    # belongs to a department that works on this change: routed for the
    # assessment and its costing, implementing it afterwards
    dept = await session.get(Department, department_id)
    if dept is None or not dept.is_active:
        raise SupplierWaitError("Pick an active department of this change")
    if phase == "costing":
        works = any(a.department_id == department_id
                    and a.effective_status != "waived"
                    for a in change.assessments)
    else:
        from app.services.implementation_service import ImplementationService
        works = department_id in await ImplementationService.implementing_department_ids(
            session, change)
    if not works:
        raise SupplierWaitError(
            f"{dept.name} has no part in this change's "
            + ("assessment and costing" if phase == "costing" else "implementation")
            + ": its supplier wait would hold nothing")
    vendor = (vendor_name or "").strip()
    if len(vendor) < 2:
        raise SupplierWaitError("Name the supplier you wait on")
    if asked_on > business_today():
        raise SupplierWaitError("Asked on: today or earlier")
    if expected_by < asked_on:
        raise SupplierWaitError("Expected by: on or after the day you asked")
    if expected_by < business_today():
        raise SupplierWaitError(
            "Expected by is in the past: chase the supplier and give the new date")
    if position_id is not None:
        pos = await session.get(CostingPosition, position_id)
        if pos is None or pos.change_id != change.id or pos.department_id != department_id:
            raise SupplierWaitError("Pick one of the department's costing positions")
    twin = next((w for w in await open_waits(session, [change.id], phase)
                 if w.department_id == department_id
                 and w.vendor_name.lower() == vendor.lower()), None)
    if twin is not None:
        raise SupplierWaitError(
            f"Already waiting on {twin.vendor_name} until "
            f"{fmt_date(twin.expected_by)}: close it or change that one")
    w = SupplierWait(change_id=change.id, department_id=department_id, phase=phase,
                     vendor_name=vendor[:120], asked_on=asked_on,
                     expected_by=expected_by, position_id=position_id,
                     note=(note or "").strip() or None, created_by=actor.id)
    session.add(w)
    await session.flush()
    await ChangeService.append_changelog(
        session, change, "supplier_wait_started",
        f"Waiting on {vendor} (asked {fmt_date(asked_on)}, expected "
        f"{fmt_date(expected_by)})", actor.id,
        new_value={"wait_id": w.id, "department_id": department_id, "phase": phase},
        for_department_id=department_id)
    return w


async def close(session: AsyncSession, change: ChangeRequest, wait_id: int,
                actor: User, reason: str, note: Optional[str] = None) -> SupplierWait:
    """End a wait. 'received' / 'not_needed': the department (or PM, admin);
    'price_on_estimate': the run team at close costing, and the department
    is told to finalize on its estimate."""
    from app.services.change_service import ChangeService
    w = await session.get(SupplierWait, wait_id)
    if w is None or w.change_id != change.id:
        raise SupplierWaitError("Supplier wait not found on this change")
    if not w.is_open:
        raise SupplierWaitError("This wait is already closed")
    if reason not in SUPPLIER_WAIT_ENDS:
        raise SupplierWaitError("Say how it ended: received, price_on_estimate or not_needed")
    if reason == "price_on_estimate":
        if w.phase != "costing":
            raise SupplierWaitError("Price on estimate is a costing decision")
        if not await _may_decide(session, change, actor):
            raise SupplierWaitForbidden(
                "Only the lead, Project Management or an admin decides to "
                "price on the estimate")
    elif not await _may_act(session, change, w.department_id, actor):
        raise SupplierWaitForbidden(
            "Only a member of that department, Project Management or an admin "
            "closes its supplier wait")
    w.closed_at = datetime.utcnow()
    w.closed_by = actor.id
    w.close_reason = reason
    text = (note or "").strip()
    await session.flush()
    words = {"received": "in", "price_on_estimate": "priced on the estimate instead",
             "not_needed": "not needed"}[reason]
    await ChangeService.append_changelog(
        session, change, "supplier_wait_closed",
        f"Wait on {w.vendor_name}: {words}" + (f" ({text})" if text else ""),
        actor.id, new_value={"wait_id": w.id, "reason": reason},
        notes=text or None, for_department_id=w.department_id)
    if reason == "price_on_estimate":
        from app.services.notification_service import NotificationService
        await NotificationService.notify_departments_once(
            session, [w.department_id], change=change, kind="task_new",
            subject_key=f"wait:{w.id}:estimate",
            title=f"Price on your estimate: {change.change_number}"[:255],
            body=(f"The lead does not wait for {w.vendor_name}: finalize your "
                  "costing on your estimate (it shows as 'estimated')."),
            link=f"/changes/{change.id}?tab=costing")
    return w


async def serialize(session: AsyncSession, waits: list[SupplierWait]) -> list[dict]:
    if not waits:
        return []
    dept_ids = {w.department_id for w in waits}
    names = dict((await session.execute(
        select(Department.id, Department.name).where(Department.id.in_(dept_ids)))).all())
    today = business_today()
    return [{
        "id": w.id, "change_id": w.change_id, "department_id": w.department_id,
        "department_name": names.get(w.department_id), "phase": w.phase,
        "vendor_name": w.vendor_name, "asked_on": w.asked_on,
        "expected_by": w.expected_by, "position_id": w.position_id, "note": w.note,
        "is_open": w.is_open, "overdue": w.is_open and w.expected_by < today,
        "chip": w.chip(today), "closed_at": w.closed_at,
        "close_reason": w.close_reason,
    } for w in waits]
