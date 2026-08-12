"""Stage 8: the implementation stage as something the system can see.

Three facts, one derived view.

  Bookings are hours, per department, against the change. They are the raw
  material of the actuals P&L at validation, which is why the per-department
  totals are part of the state payload rather than something a caller has to
  sum client-side out of a list it may only partly be allowed to read.

  Reports are the cadence. The rule book says at least twice a week, so a
  department that has not reported inside REPORT_CADENCE_HOURS owes one, and
  that debt becomes a my-tasks row rather than an email nobody sends.

  Escalations are the answer to a flagged report, and they are Sales' to make
  because Sales owns the customer. Everything about the direction ('customer'
  vs 'internal') is a commercial call, not a technical one.

Who implements is DERIVED: a department that put a costing position or a cost
line on this change priced work, and whoever priced the work does it. Storing
a separate membership list would give us two lists to disagree with each other
the first time somebody edits the costing.

Write permission mirrors the costing module exactly (CostingPositionService.
may_write) with one substitution — the status window is 'in_implementation'
instead of 'costing'. Read permission mirrors it without change: a department
sees its own rows, and the people accountable for the change as a whole (PM,
Sales, the change lead, admins) see everything, because a progress picture
with a hole in it is not a progress picture.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import AssessmentCostLine, CostingPosition
from app.models.change_impl import (
    ESCALATION_DIRECTIONS, REPORT_CADENCE_HOURS,
    ImplementationBooking, ImplementationEscalation, ImplementationReport,
)
from app.models.entities import User
from app.models.workflow import Department

IMPLEMENTATION_STATUS = "in_implementation"


class ImplementationError(ValueError):
    """Invalid booking/report/escalation operation; mapped to HTTP 400."""


class ImplementationService:

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------
    @staticmethod
    async def may_write(session: AsyncSession, change: ChangeRequest,
                        department_id: int, actor: User) -> bool:
        """A member of that department while the change is in implementation,
        or the people who run the programme (PM, admin) at any time.

        The status window is the same argument costing makes: bookings and
        reports are the working record of a stage, and letting them appear
        after the stage closed would make the actuals P&L drawn at validation
        a moving target."""
        from app.services.meeting_service import MeetingService
        from app.services.workflow_service import WorkflowService
        if (actor.effective_role == "admin"
                or await MeetingService.user_is_pm_member(session, actor)):
            return True
        if change.status != IMPLEMENTATION_STATUS:
            return False
        return await WorkflowService.actor_in_department(
            session, actor, department_id)

    @staticmethod
    async def readable_department_ids(
        session: AsyncSession, change: ChangeRequest, actor: User,
    ) -> set | None:
        """Which departments' implementation rows this caller may see. None
        means all — PM, Sales, the change lead and admins run the change as a
        whole. Identical to the costing rule on purpose: a user who can see a
        department's costing and not its progress would be able to compare a
        budget against nothing."""
        from app.services.change_service import ChangeService
        from app.services.meeting_service import MeetingService
        from app.services.workflow_service import WorkflowService
        if (actor.effective_role == "admin" or change.lead_id == actor.id
                or await MeetingService.user_is_pm_member(session, actor)
                or await ChangeService._user_in_department(
                    session, actor, "Sales")):
            return None
        return set(await WorkflowService.effective_department_ids(session, actor))

    @staticmethod
    async def may_escalate(session: AsyncSession, change: ChangeRequest,
                           actor: User) -> bool:
        """Sales, the change lead, or an admin. Same set that may put a price
        in front of the customer (ChangeService.user_can_set_quoted_price) —
        deciding that a delay leaves the building is the same kind of act."""
        from app.services.change_service import ChangeService
        return await ChangeService.user_can_set_quoted_price(
            session, actor, change)

    # ------------------------------------------------------------------
    # Who implements
    # ------------------------------------------------------------------
    @staticmethod
    async def implementing_department_ids(
        session: AsyncSession, change: ChangeRequest,
    ) -> list[int]:
        """Departments that priced work on this change, and therefore do it.

        A costing position OR a cost line counts: a supplier quote filed as a
        position is a commitment to work exactly as much as an hours line is.
        Sorted so every payload built off this list has a stable order.
        """
        dept_ids: set[int] = set()
        rows = (await session.execute(
            select(CostingPosition.department_id).where(
                CostingPosition.change_id == change.id).distinct())).scalars()
        dept_ids.update(rows.all())
        rows = (await session.execute(
            select(ChangeAssessment.department_id)
            .join(AssessmentCostLine,
                  AssessmentCostLine.assessment_id == ChangeAssessment.id)
            .where(ChangeAssessment.change_id == change.id)
            .distinct())).scalars()
        dept_ids.update(rows.all())
        return sorted(dept_ids)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    async def list_bookings(
        session: AsyncSession, change: ChangeRequest,
        department_ids: set | None = None,
    ) -> list[ImplementationBooking]:
        q = (select(ImplementationBooking)
             .where(ImplementationBooking.change_id == change.id)
             .order_by(ImplementationBooking.department_id,
                       ImplementationBooking.id))
        if department_ids is not None:
            if not department_ids:
                return []
            q = q.where(ImplementationBooking.department_id.in_(department_ids))
        return list((await session.execute(q)).scalars().all())

    @staticmethod
    async def list_reports(
        session: AsyncSession, change: ChangeRequest,
        department_ids: set | None = None,
    ) -> list[ImplementationReport]:
        q = (select(ImplementationReport)
             .where(ImplementationReport.change_id == change.id)
             .order_by(ImplementationReport.id))
        if department_ids is not None:
            if not department_ids:
                return []
            q = q.where(ImplementationReport.department_id.in_(department_ids))
        return list((await session.execute(q)).scalars().all())

    @staticmethod
    async def list_escalations(
        session: AsyncSession, change: ChangeRequest,
    ) -> list[ImplementationEscalation]:
        """Not department-scoped, on purpose: an escalation is a statement
        about the CHANGE (its date moved, or it did not), and hiding it from
        the department whose work caused it would be absurd."""
        return list((await session.execute(
            select(ImplementationEscalation)
            .where(ImplementationEscalation.change_id == change.id)
            .order_by(ImplementationEscalation.id))).scalars().all())

    @staticmethod
    async def booked_hours_by_department(
        session: AsyncSession, change: ChangeRequest,
    ) -> dict[int, float]:
        rows = (await session.execute(
            select(ImplementationBooking.department_id,
                   func.sum(ImplementationBooking.hours))
            .where(ImplementationBooking.change_id == change.id)
            .group_by(ImplementationBooking.department_id))).all()
        return {dept_id: round(float(total or 0.0), 2) for dept_id, total in rows}

    @staticmethod
    async def get_booking(session: AsyncSession, change: ChangeRequest,
                          booking_id: int) -> ImplementationBooking:
        row = await session.get(ImplementationBooking, booking_id)
        if row is None or row.change_id != change.id:
            raise ImplementationError(
                f"Booking {booking_id} not found on this change")
        return row

    @staticmethod
    async def get_escalation(session: AsyncSession, change: ChangeRequest,
                             escalation_id: int) -> ImplementationEscalation:
        row = await session.get(ImplementationEscalation, escalation_id)
        if row is None or row.change_id != change.id:
            raise ImplementationError(
                f"Escalation {escalation_id} not found on this change")
        return row

    # ------------------------------------------------------------------
    # The derived state — one row per implementing department
    # ------------------------------------------------------------------
    @staticmethod
    def _answered_at(
        escalations: list[ImplementationEscalation],
        department_report_ids: set[int],
    ) -> datetime | None:
        """The moment this department's risk was last ANSWERED.

        An escalation answers a department when it points at one of that
        department's reports, or when it points at no report at all — a
        change-wide escalation ("the whole programme slips") is an answer to
        everyone's flag, and treating it otherwise would leave Sales staring
        at tasks for a risk they already took to the customer.

        Resolving counts as answering too, and is later than the raise, so the
        latest of created_at/resolved_at wins.
        """
        stamps: list[datetime] = []
        for e in escalations:
            if e.report_id is not None and e.report_id not in department_report_ids:
                continue
            stamps.append(e.created_at)
            if e.resolved_at is not None:
                stamps.append(e.resolved_at)
        return max(stamps) if stamps else None

    @staticmethod
    async def state(
        session: AsyncSession, change: ChangeRequest, actor: User,
        *, now: datetime | None = None,
    ) -> dict:
        """Per-department implementation state, scoped to what actor may read.

        booked_hours is here rather than behind a separate roll-up endpoint
        because the actuals P&L at validation needs exactly this number, and a
        second way of computing it is a second way of getting it wrong.
        """
        now = now or datetime.utcnow()
        visible = await ImplementationService.readable_department_ids(
            session, change, actor)
        implementing = await ImplementationService.implementing_department_ids(
            session, change)
        hours = await ImplementationService.booked_hours_by_department(
            session, change)
        reports = await ImplementationService.list_reports(session, change)
        escalations = await ImplementationService.list_escalations(
            session, change)

        names = dict((await session.execute(
            select(Department.id, Department.name))).all())
        cutoff = now - timedelta(hours=REPORT_CADENCE_HOURS)
        in_implementation = change.status == IMPLEMENTATION_STATUS

        departments = []
        for dept_id in implementing:
            if visible is not None and dept_id not in visible:
                continue
            mine = sorted((r for r in reports if r.department_id == dept_id),
                          key=lambda r: (r.reported_at, r.id))
            latest = mine[-1] if mine else None
            last_at = latest.reported_at if latest else None
            answered = ImplementationService._answered_at(
                escalations, {r.id for r in mine})
            # Two ways a flag stops being open, and the department owns one of
            # them: Sales escalated (or closed an escalation) AFTER it was
            # raised, or the department's own next report no longer says
            # at_risk — "we're back on track" is an answer, and the LATEST
            # report is the department's current position, not a historical
            # one that stays raised forever.
            at_risk_open = bool(
                latest is not None and latest.at_risk
                and (answered is None or latest.reported_at > answered))
            departments.append({
                "department_id": dept_id,
                "department_name": names.get(dept_id),
                "booked_hours": hours.get(dept_id, 0.0),
                "report_count": len(mine),
                "last_report_at": last_at,
                "at_risk_open": at_risk_open,
                # Silence is the debt, not lateness: a department that has
                # never reported owes one from the moment the stage starts.
                "owes_report": bool(
                    in_implementation
                    and (last_at is None or last_at < cutoff)),
            })
        return {
            "change_id": change.id,
            "status": change.status,
            "cadence_hours": REPORT_CADENCE_HOURS,
            "departments": departments,
            "total_booked_hours": round(
                sum(d["booked_hours"] for d in departments), 2),
            "open_escalations": sum(1 for e in escalations if e.is_open),
        }

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    @staticmethod
    async def _require_implementing(
        session: AsyncSession, change: ChangeRequest, department_id: int,
    ) -> None:
        """Only a department that priced work books time or reports on it.

        Same guard costing uses against untargeted departments, one step
        further along the flow: there, the department needed an assessment;
        here it needs a number on the change.
        """
        implementing = await ImplementationService.implementing_department_ids(
            session, change)
        if department_id not in implementing:
            raise ImplementationError(
                f"Department {department_id} is not implementing this change — "
                "only departments that costed work on it book time or report "
                "progress")

    @staticmethod
    async def create_booking(
        session: AsyncSession, change: ChangeRequest, spec: dict, actor: User,
    ) -> ImplementationBooking:
        department_id = spec["department_id"]
        await ImplementationService._require_implementing(
            session, change, department_id)
        hours = spec.get("hours")
        if hours is None or float(hours) <= 0:
            raise ImplementationError(
                "A time booking needs hours greater than zero")
        booking = ImplementationBooking(
            change_id=change.id, department_id=department_id,
            hours=round(float(hours), 2),
            note=(spec.get("note") or None), booked_by=actor.id,
            booked_at=datetime.utcnow(),
        )
        session.add(booking)
        await session.flush()
        from app.services.change_service import ChangeService
        await ChangeService.append_changelog(
            session, change, "implementation_time_booked",
            f"{booking.hours} h booked for dept {department_id}", actor.id,
            new_value={"booking_id": booking.id,
                       "department_id": department_id,
                       "hours": booking.hours})
        return booking

    @staticmethod
    async def delete_booking(
        session: AsyncSession, change: ChangeRequest,
        booking: ImplementationBooking, actor: User,
    ) -> None:
        booking_id, department_id, hours = (
            booking.id, booking.department_id, booking.hours)
        await session.delete(booking)
        await session.flush()
        from app.services.change_service import ChangeService
        await ChangeService.append_changelog(
            session, change, "implementation_time_removed",
            f"{hours} h booking removed from dept {department_id}", actor.id,
            old_value={"booking_id": booking_id,
                       "department_id": department_id, "hours": hours})

    @staticmethod
    async def create_report(
        session: AsyncSession, change: ChangeRequest, spec: dict, actor: User,
    ) -> ImplementationReport:
        department_id = spec["department_id"]
        await ImplementationService._require_implementing(
            session, change, department_id)
        note = (spec.get("note") or "").strip()
        if not note:
            raise ImplementationError("A progress report needs a note")
        at_risk = bool(spec.get("at_risk") or False)
        risk_note = (spec.get("risk_note") or None)
        report = ImplementationReport(
            change_id=change.id, department_id=department_id, note=note,
            at_risk=at_risk, risk_note=risk_note if at_risk else None,
            reported_by=actor.id, reported_at=datetime.utcnow(),
        )
        session.add(report)
        await session.flush()
        from app.services.change_service import ChangeService
        if at_risk:
            # The flag is the escalation trigger, so it gets its own action:
            # "somebody said this change is in trouble" has to be findable in
            # the changelog without reading every progress note.
            await ChangeService.append_changelog(
                session, change, "implementation_risk_flagged",
                f"Dept {department_id} flagged implementation at risk",
                actor.id,
                new_value={"report_id": report.id,
                           "department_id": department_id,
                           "risk_note": risk_note})
        else:
            await ChangeService.append_changelog(
                session, change, "implementation_reported",
                f"Progress report from dept {department_id}", actor.id,
                new_value={"report_id": report.id,
                           "department_id": department_id})
        return report

    @staticmethod
    async def create_escalation(
        session: AsyncSession, change: ChangeRequest, spec: dict, actor: User,
    ) -> ImplementationEscalation:
        direction = spec.get("direction")
        if direction not in ESCALATION_DIRECTIONS:
            raise ImplementationError(
                f"Invalid escalation direction '{direction}' — "
                f"one of {', '.join(ESCALATION_DIRECTIONS)}")
        note = (spec.get("note") or "").strip()
        if not note:
            raise ImplementationError("An escalation needs a note")
        report_id = spec.get("report_id")
        if report_id is not None:
            report = await session.get(ImplementationReport, report_id)
            if report is None or report.change_id != change.id:
                raise ImplementationError(
                    f"Report {report_id} not found on this change")
        escalation = ImplementationEscalation(
            change_id=change.id, report_id=report_id, direction=direction,
            note=note, created_by=actor.id, created_at=datetime.utcnow(),
        )
        session.add(escalation)
        await session.flush()
        from app.services.change_service import ChangeService
        await ChangeService.append_changelog(
            session, change, "implementation_escalated",
            f"Implementation risk escalated {direction}", actor.id,
            new_value={"escalation_id": escalation.id,
                       "direction": direction, "report_id": report_id})
        return escalation

    @staticmethod
    async def resolve_escalation(
        session: AsyncSession, change: ChangeRequest,
        escalation: ImplementationEscalation, note: str, actor: User,
    ) -> ImplementationEscalation:
        if escalation.resolved_at is not None:
            raise ImplementationError("That escalation is already resolved")
        note = (note or "").strip()
        if not note:
            # Closing without saying what happened turns the escalation into a
            # dropped ball with a tick next to it.
            raise ImplementationError(
                "Resolving an escalation needs a resolution note")
        escalation.resolution_note = note
        escalation.resolved_by = actor.id
        escalation.resolved_at = datetime.utcnow()
        await session.flush()
        from app.services.change_service import ChangeService
        await ChangeService.append_changelog(
            session, change, "escalation_resolved",
            f"Implementation escalation {escalation.id} resolved", actor.id,
            new_value={"escalation_id": escalation.id,
                       "resolution_note": note})
        return escalation

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    # Every row carries the author's NAME as well as their id: a progress
    # report attributed to "user 41" is a report nobody can act on, and making
    # the frontend fetch the user directory to render a list is the kind of
    # round trip that turns into a stale cache.
    @staticmethod
    async def _names(session: AsyncSession, ids) -> dict[int, str]:
        wanted = {i for i in ids if i is not None}
        if not wanted:
            return {}
        rows = (await session.execute(
            select(User.id, User.full_name).where(User.id.in_(wanted)))).all()
        return dict(rows)

    @staticmethod
    async def serialize_bookings(
        session: AsyncSession, rows: list[ImplementationBooking],
    ) -> list[dict]:
        """The stored columns are booked_by/booked_at — the fact recorded is
        "this time was booked". The payload ALSO carries them under the
        created_by/created_at names every other change child uses, so a client
        rendering mixed lists does not need a per-kind field mapping."""
        names = await ImplementationService._names(
            session, (b.booked_by for b in rows))
        return [{
            "id": b.id, "change_id": b.change_id,
            "department_id": b.department_id, "hours": b.hours, "note": b.note,
            "booked_by": b.booked_by, "booked_at": b.booked_at,
            "created_by": b.booked_by, "created_at": b.booked_at,
            "created_by_name": names.get(b.booked_by),
        } for b in rows]

    @staticmethod
    async def serialize_reports(
        session: AsyncSession, rows: list[ImplementationReport],
    ) -> list[dict]:
        names = await ImplementationService._names(
            session, (r.reported_by for r in rows))
        return [{
            "id": r.id, "change_id": r.change_id,
            "department_id": r.department_id, "note": r.note,
            "at_risk": r.at_risk, "risk_note": r.risk_note,
            "reported_by": r.reported_by,
            "reported_by_name": names.get(r.reported_by),
            "reported_at": r.reported_at,
        } for r in rows]

    @staticmethod
    async def serialize_escalations(
        session: AsyncSession, rows: list[ImplementationEscalation],
    ) -> list[dict]:
        names = await ImplementationService._names(
            session, [e.created_by for e in rows] + [e.resolved_by for e in rows])
        return [{
            "id": e.id, "change_id": e.change_id, "report_id": e.report_id,
            "direction": e.direction, "note": e.note,
            "created_by": e.created_by,
            "created_by_name": names.get(e.created_by),
            "created_at": e.created_at,
            "resolved_at": e.resolved_at, "resolved_by": e.resolved_by,
            "resolved_by_name": names.get(e.resolved_by),
            "resolution_note": e.resolution_note, "is_open": e.is_open,
        } for e in rows]
