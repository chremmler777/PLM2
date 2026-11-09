"""Book hours on a change (ECR-solid C15, spec §0 "Hours"; no switch).

One "Book hours" dialog for the whole life of a change: department, hours,
the day worked (back 21 days), optionally for a colleague (Belk books for
the toolmakers, who have no account), on any change still open and until
7 days after it closed or was cancelled. The lead has a "Coordination" row.
One prefilled confirm at the department's last action names its source
("your estimate: 6 h"); skipped is "not booked", never a 0.

Bookings are the implementation bookings (one table, one P&L): each stores
its source ('estimate' = a confirmed estimate, 'typed'), the day worked and
the change's status at booking.

The effort report (GET /reports/ecr-effort) sums booked against estimated
hours per change and department, and names the departments with work and no
booking ("not booked"). Its split by origin and Sales contact is cut 2.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import AssessmentCostLine, CostingPosition
from app.models.change_impl import ImplementationBooking
from app.models.entities import User
from app.models.workflow import Department

#: how far back a work date may lie
BACKDATE_DAYS = 21
#: how long after close / cancel hours may still be booked
AFTER_CLOSE_DAYS = 7
#: one booking is at most one day's work
MAX_HOURS = 24.0
#: the lead's own row
COORDINATION = "coordination"
#: where a booking's number came from
SOURCES = ("estimate", "typed")
#: a department's own labour (CostingPosition kinds whose hours it works)
OWN_HOUR_KINDS = ("internal_effort", "support_effort", "own_time")


class HoursError(ValueError):
    """Refused booking; HTTP 400."""


class HoursForbidden(PermissionError):
    """Not yours to book; HTTP 403."""


def window_until(change: ChangeRequest) -> Optional[datetime]:
    """When booking ends: 7 days after close or cancel; None while open."""
    end = change.closed_at if change.status == "closed" else (
        change.cancelled_at if change.status == "cancelled" else None)
    if change.status in ("closed", "cancelled") and end is None:
        end = change.updated_at
    return end + timedelta(days=AFTER_CLOSE_DAYS) if end is not None else None


def window_open(change: ChangeRequest, now: Optional[datetime] = None) -> bool:
    until = window_until(change)
    return until is None or (now or datetime.utcnow()) <= until


async def estimate_by_department(session: AsyncSession, change_ids: list[int]
                                 ) -> dict[tuple[int, int], float]:
    """(change, department) -> hours the department costed for its own work:
    its own-labour positions plus its cost lines' demand hours."""
    out: dict[tuple[int, int], float] = {}
    absorbed: set = set()
    if not change_ids:
        return out
    for cid, did, h in (await session.execute(
            select(CostingPosition.change_id, CostingPosition.department_id,
                   func.sum(CostingPosition.hours))
            .where(CostingPosition.change_id.in_(change_ids),
                   CostingPosition.kind.in_(OWN_HOUR_KINDS),
                   CostingPosition.hours.isnot(None))
            .group_by(CostingPosition.change_id, CostingPosition.department_id))).all():
        out[(cid, did)] = out.get((cid, did), 0.0) + float(h or 0)
    for cid, did, h in (await session.execute(
            select(ChangeAssessment.change_id, ChangeAssessment.department_id,
                   func.sum(AssessmentCostLine.demand_hours))
            .join(ChangeAssessment, ChangeAssessment.id == AssessmentCostLine.assessment_id)
            .where(ChangeAssessment.change_id.in_(change_ids))
            .group_by(ChangeAssessment.change_id, ChangeAssessment.department_id))).all():
        if h:
            out[(cid, did)] = out.get((cid, did), 0.0) + float(h)
    # F13 / T14: "<Dept> has no cost: absorbed" carries the hours it works
    # for free; they are its estimate too (one per department)
    for cid, did, raw in (await session.execute(
            select(ChangeAssessment.change_id, ChangeAssessment.department_id,
                   ChangeAssessment.details)
            .where(ChangeAssessment.change_id.in_(change_ids),
                   ChangeAssessment.details.like('%costing_no_cost%')))).all():
        try:
            nc = (json.loads(raw) or {}).get("costing_no_cost") or {}
        except (TypeError, ValueError):
            continue
        if nc.get("reason") == "absorbed" and nc.get("hours") and (cid, did) not in absorbed:
            absorbed.add((cid, did))
            out[(cid, did)] = out.get((cid, did), 0.0) + float(nc["hours"])
    return {k: round(v, 2) for k, v in out.items() if v}


async def booked_by_department(session: AsyncSession, change_ids: list[int]
                               ) -> dict[tuple[int, int], float]:
    if not change_ids:
        return {}
    return {(cid, did): round(float(h or 0), 2) for cid, did, h in (await session.execute(
        select(ImplementationBooking.change_id, ImplementationBooking.department_id,
               func.sum(ImplementationBooking.hours))
        .where(ImplementationBooking.change_id.in_(change_ids))
        .group_by(ImplementationBooking.change_id,
                  ImplementationBooking.department_id))).all()}


class HoursService:

    @staticmethod
    async def books_for_memberless(session: AsyncSession, change: ChangeRequest,
                                   actor: User, dept_id: int) -> bool:
        """A5-04 b (R20, R37): the lead or a Project Management member books
        for a department with no real member here, so its estimate does not
        stay 'not booked'; the booker's name stays on the row."""
        from app.services.change_people import holds_lead, staffed_department_ids
        from app.services.meeting_service import MeetingService
        if not (holds_lead(change, actor)
                or await MeetingService.user_is_pm_member(session, actor)):
            return False
        return dept_id not in await staffed_department_ids(session, change, [dept_id])

    @staticmethod
    async def book(session: AsyncSession, change: ChangeRequest, spec: dict,
                   actor: User) -> ImplementationBooking:
        """Book hours (C15). The actor books for a department they are a
        member of (acts-as aware; an admin for any), for themselves or a
        named colleague; the lead's Coordination row is the lead's."""
        from app.services.change_people import holds_lead
        from app.services.workflow_service import WorkflowService
        if not window_open(change):
            raise HoursError(
                f"Hours are booked until {AFTER_CLOSE_DAYS} days after the change "
                "closed or was cancelled")
        dept_id = spec.get("department_id")
        from app.services.change_people import department_is_active
        if dept_id is None or not await department_is_active(session, dept_id):
            raise HoursError("Pick the department the hours are for (an active "
                             "department)")
        admin = actor.effective_role == "admin"
        if not admin and not await WorkflowService.actor_in_department(
                session, actor, dept_id) and not await HoursService.books_for_memberless(
                    session, change, actor, dept_id):
            raise HoursForbidden(
                "You book hours for a department you belong to (the lead or "
                "Project Management also for a department with no member here)")
        coordination = bool(spec.get("coordination"))
        if coordination and not (holds_lead(change, actor) or admin):
            raise HoursForbidden("Coordination is the change lead's row")
        try:
            hours = float(spec.get("hours"))
        except (TypeError, ValueError):
            raise HoursError("Hours are a number")
        if not hours > 0:
            raise HoursError("Hours above zero: a day you did not work on it is "
                             "simply not booked")
        if hours > MAX_HOURS:
            raise HoursError(f"At most {MAX_HOURS:g} h per booking (one day's work)")
        from app.utils.clock import business_today
        today = business_today()
        raw = spec.get("work_date")
        if raw in (None, ""):
            work_date = today
        elif isinstance(raw, date):
            work_date = raw
        else:
            try:
                work_date = date.fromisoformat(str(raw)[:10])
            except ValueError:
                raise HoursError("The work date is a date (YYYY-MM-DD)")
        if work_date > today:
            raise HoursError("The work date is today or earlier")
        if work_date < today - timedelta(days=BACKDATE_DAYS):
            raise HoursError(f"Hours are booked within {BACKDATE_DAYS} days of the work")
        source = spec.get("source") or "typed"
        if source not in SOURCES:
            raise HoursError("Source: 'estimate' (confirmed) or 'typed'")
        if source == "estimate" and not coordination:
            # 'a confirmed estimate' is the server's word, not the client's:
            # only the prefill itself (estimate less booked) counts as one
            e = (await estimate_by_department(session, [change.id])).get(
                (change.id, dept_id))
            b = (await booked_by_department(session, [change.id])).get(
                (change.id, dept_id), 0.0)
            left = round(max((e or 0) - b, 0), 2)
            if not e or round(hours, 2) != left:
                source = "typed"
        booked_for = (spec.get("booked_for") or "").strip() or None
        if booked_for and len(booked_for) > 120:
            raise HoursError("The colleague's name has at most 120 characters")
        note = (spec.get("note") or "").strip() or None
        b = ImplementationBooking(
            change_id=change.id, department_id=dept_id, hours=round(hours, 2),
            note=note, booked_by=actor.id, booked_at=datetime.utcnow(),
            work_date=work_date, source=source, booked_for=booked_for,
            activity=COORDINATION if coordination else None,
            status_at_booking=change.status)
        session.add(b)
        await session.flush()
        from app.services.change_service import ChangeService
        dept = await session.get(Department, dept_id)
        await ChangeService.append_changelog(
            session, change, "hours_booked",
            f"{b.hours:g} h booked for {dept.name if dept else dept_id}"
            + (" (coordination)" if coordination else "")
            + (f" for {booked_for}" if booked_for else "")
            + (" (your estimate confirmed)" if source == "estimate" else ""),
            actor.id,
            new_value={"booking_id": b.id, "department_id": dept_id, "hours": b.hours,
                       "work_date": work_date.isoformat(), "source": source,
                       "booked_for": booked_for, "activity": b.activity,
                       "status": change.status},
            for_department_id=dept_id)
        if change.status in HoursService.PRE_OFFER:
            await HoursService.sync_assessment_effort(session, change, dept_id, actor.id)
        return b

    # Christoph 2026-11-08: the costing row "Assessment effort" is the sum of
    # the department's bookings made before the offer, never typed
    PRE_OFFER = ("draft", "captured", "scoping", "in_assessment", "costing")

    @staticmethod
    async def sync_assessment_effort(session: AsyncSession, change: ChangeRequest,
                                     department_id: int, actor_id: int) -> None:
        from sqlalchemy import func as _f
        total = float((await session.execute(
            select(_f.coalesce(_f.sum(ImplementationBooking.hours), 0)).where(
                ImplementationBooking.change_id == change.id,
                ImplementationBooking.department_id == department_id,
                ImplementationBooking.status_at_booking.in_(HoursService.PRE_OFFER)))
        ).scalar() or 0)
        row = (await session.execute(select(CostingPosition).where(
            CostingPosition.change_id == change.id,
            CostingPosition.department_id == department_id,
            CostingPosition.kind == "internal_effort"))).scalars().first()
        if row is None:
            if total <= 0:
                return
            routed = (await session.execute(select(ChangeAssessment.id).where(
                ChangeAssessment.change_id == change.id,
                ChangeAssessment.department_id == department_id).limit(1))).scalar_one_or_none()
            if routed is None:
                return
            row = CostingPosition(
                change_id=change.id, department_id=department_id,
                label="Internal effort: time spent on assessment (h)",
                kind="internal_effort", pricing="estimate", created_by=actor_id,
                lead_time_unit="calendar_days")
            session.add(row)
        row.hours = round(total, 2) if total > 0 else None
        await session.flush()
        from app.services import costing_rates
        await costing_rates.snapshot_position(session, change, row)
        await session.flush()

    @staticmethod
    async def state(session: AsyncSession, change: ChangeRequest, actor: User) -> dict:
        """Booked vs estimated per department (the ones the viewer may read),
        the viewer's own bookings, and the prefill of the confirm: per the
        viewer's departments, its estimate, what is booked and what is left
        ("your estimate: 6 h")."""
        from app.services.change_people import holds_lead
        from app.services.implementation_service import ImplementationService
        from app.services.workflow_service import WorkflowService
        visible = await ImplementationService.readable_department_ids(session, change, actor)
        mine = set(await WorkflowService.effective_department_ids(session, actor))
        est = await estimate_by_department(session, [change.id])
        booked = await booked_by_department(session, [change.id])
        dept_ids = {d for (_, d) in est} | {d for (_, d) in booked}
        names = dict((await session.execute(
            select(Department.id, Department.name))).all())
        rows = []
        for did in sorted(dept_ids, key=lambda i: (names.get(i) or "", i)):
            if visible is not None and did not in visible:
                continue
            e, b = est.get((change.id, did)), booked.get((change.id, did), 0.0)
            rows.append({"department_id": did, "department_name": names.get(did),
                         "estimate_hours": e, "booked_hours": b,
                         "not_booked": bool(e) and not b})
        q = select(ImplementationBooking).where(
            ImplementationBooking.change_id == change.id)
        if visible is not None:
            q = q.where(ImplementationBooking.department_id.in_(visible or {-1}))
        bookings = (await session.execute(
            q.order_by(ImplementationBooking.work_date.desc(),
                       ImplementationBooking.id.desc()))).scalars().all()
        from app.services.change_plan_service import ChangePlanService
        users = await ChangePlanService._user_names(session, [x.booked_by for x in bookings])
        prefill = []
        for did in sorted(mine, key=lambda i: (names.get(i) or "", i)):
            e = est.get((change.id, did))
            b = booked.get((change.id, did), 0.0)
            left = round(max((e or 0) - b, 0), 2)
            prefill.append({
                "department_id": did, "department_name": names.get(did),
                "estimate_hours": e, "booked_hours": b,
                "prefill_hours": left or None,
                "source_label": (f"your estimate: {e:g} h"
                                 + (f", {b:g} h booked" if b else "")) if e else None})
        # A5-04 b: the departments with no member here this viewer books for
        coordinated = []
        if actor.effective_role != "admin":
            from app.services.change_people import (
                coordinator_name, no_member_words, staffed_department_ids,
            )
            from app.services.meeting_service import MeetingService
            rest = {d for d in dept_ids if d not in mine}
            if rest and (holds_lead(change, actor)
                         or await MeetingService.user_is_pm_member(session, actor)):
                coordinated = sorted(rest - await staffed_department_ids(
                    session, change, rest), key=lambda i: (names.get(i) or "", i))
            if coordinated:
                who = await coordinator_name(session, change)
            for did in coordinated:
                e = est.get((change.id, did))
                b = booked.get((change.id, did), 0.0)
                left = round(max((e or 0) - b, 0), 2)
                prefill.append({
                    "department_id": did, "department_name": names.get(did),
                    "estimate_hours": e, "booked_hours": b,
                    "prefill_hours": left or None, "no_member": True,
                    "source_label": (
                        no_member_words(names.get(did), who)
                        + (f"; its estimate: {e:g} h" if e else "")
                        + (f", {b:g} h booked" if b else ""))})
        until = window_until(change)
        return {
            "change_id": change.id, "window_open": window_open(change),
            "window_until": until, "backdate_days": BACKDATE_DAYS,
            "can_coordinate": holds_lead(change, actor),
            "departments": rows,
            "total_booked": round(sum(r["booked_hours"] for r in rows), 2),
            "total_estimate": round(sum(r["estimate_hours"] or 0 for r in rows), 2),
            "mine": prefill,
            "bookings": [{
                "id": x.id, "department_id": x.department_id,
                "department_name": names.get(x.department_id), "hours": x.hours,
                "work_date": x.work_date, "source": x.source or "typed",
                "booked_for": x.booked_for, "activity": x.activity,
                "note": x.note, "booked_by": x.booked_by,
                "booked_by_name": users.get(x.booked_by),
                "status_at_booking": x.status_at_booking,
                "can_delete": x.booked_by == actor.id or actor.effective_role == "admin",
            } for x in bookings],
        }

    @staticmethod
    async def effort_report(session: AsyncSession, actor: User, *,
                            since: Optional[date] = None,
                            until: Optional[date] = None) -> dict:
        """Hours per change (C15 report 'ecr-effort'): booked vs estimated,
        per department, and the departments with an estimate and no booking
        ("not booked", never 0). Changes the viewer may see. With a date
        window (work date): only the changes with hours booked in it, their
        bookings in it, and "not booked" still means never booked. Split by
        origin and Sales contact: cut 2."""
        from app.services.change_service import ChangeService, _org_scope
        if not (actor.effective_role == "admin"
                or await ChangeService._user_in_department(session, actor, "Project Manager")
                or await ChangeService._user_in_department(session, actor, "Management")):
            raise HoursForbidden("The effort report is for Project Management, "
                                 "Management and admins")
        q = _org_scope(select(ChangeRequest), actor)
        changes = (await session.execute(q.order_by(ChangeRequest.id))).scalars().all()
        ids = [c.id for c in changes]
        est = await estimate_by_department(session, ids)
        bq = (select(ImplementationBooking.change_id, ImplementationBooking.department_id,
                     ImplementationBooking.source, func.sum(ImplementationBooking.hours))
              .where(ImplementationBooking.change_id.in_(ids or [-1])))
        if since is not None:
            bq = bq.where(ImplementationBooking.work_date >= since)
        if until is not None:
            bq = bq.where(ImplementationBooking.work_date <= until)
        windowed = since is not None or until is not None
        # grouped by change once (R34), not scanned per change
        booked: dict = {}
        confirmed: dict = {}
        for cid, did, src, h in (await session.execute(bq.group_by(
                ImplementationBooking.change_id, ImplementationBooking.department_id,
                ImplementationBooking.source))).all():
            per_c = booked.setdefault(cid, {})
            per_c[did] = per_c.get(did, 0.0) + float(h or 0)
            if src == "estimate":
                confirmed[cid] = confirmed.get(cid, 0.0) + float(h or 0)
        ever: set = set()
        if windowed:
            # "not booked" means never booked, not "nothing in this window"
            ever = set((await session.execute(
                select(ImplementationBooking.change_id,
                       ImplementationBooking.department_id)
                .where(ImplementationBooking.change_id.in_(ids or [-1]))
                .distinct())).all())
        est_by: dict = {}
        for (cid, did), h in est.items():
            est_by.setdefault(cid, {})[did] = h
        names = dict((await session.execute(select(Department.id, Department.name))).all())
        rows = []
        for c in changes:
            b_c = booked.get(c.id, {})
            if windowed and not b_c:
                # a date window reports the changes with hours in it; the
                # estimates of changes with no activity there do not count
                continue
            e_c = est_by.get(c.id, {})
            depts = sorted(set(e_c) | set(b_c), key=lambda i: (names.get(i) or "", i))
            if not depts:
                continue
            per = [{"department_id": d, "department_name": names.get(d),
                    "estimate_hours": e_c.get(d),
                    "booked_hours": round(b_c.get(d, 0.0), 2)}
                   for d in depts]
            not_booked = [p["department_name"] for p in per if p["estimate_hours"]
                          and not ((c.id, p["department_id"]) in ever if windowed
                                   else p["booked_hours"])]
            rows.append({
                "change_id": c.id, "change_number": c.change_number, "title": c.title,
                "status": c.status, "customer_relevant": bool(c.customer_relevant),
                "booked_hours": round(sum(p["booked_hours"] for p in per), 2),
                "estimate_hours": round(sum(p["estimate_hours"] or 0 for p in per), 2),
                "confirmed_estimate_hours": round(confirmed.get(c.id, 0.0), 2),
                "not_booked": not_booked,
                "departments": per,
            })
        return {"since": since, "until": until, "changes": rows,
                "booked_hours": round(sum(r["booked_hours"] for r in rows), 2),
                "estimate_hours": round(sum(r["estimate_hours"] for r in rows), 2)}
