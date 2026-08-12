"""Stage 9: validation — the checks that decide whether a change is released.

Implementation ends with a tool that runs and a part in somebody's hand. What
turns that into a RELEASE is a set of statements, each made by the department
that is in a position to make it:

  sampled / measured   the department did the physical work on its own scope.
  cycle_time           the measured cycle time, AS A NUMBER, so it can be held
                       against the lifecycle assumption the costing was built
                       on. A tick would prove only that somebody looked.
  weight               the Tool Engineer's: the sampled part on a scale
                       against the weight the QUOTE was built on. The delta is
                       Sales' errand, not the tool shop's.
  revision_bump        Development's: the revision levels were raised the way
                       the customer's statement said, and someone verified it.

Who owes checks is DERIVED, exactly as stage 8 derives it — the departments
that priced work on this change (ImplementationService.implementing_department
_ids). Rows are created lazily from the catalog the first time anyone reads or
writes the state, which makes the ABSENCE of rows meaningful: a change that
never entered stage 9 has none, and the released guard lets it through
vacuously. That is what keeps every change that predates this module — and
every legacy flow test — releasable.

The verdict is not a new status. 'in_validation' -> 'released' already exists
and already carries the ready-to-go guard; this module adds a second reason it
can refuse. The loop back is the existing 'in_validation' ->
'in_implementation' hop, given a mandatory reason so the changelog records WHY
the change went round again — replanned timing, renegotiated terms — instead
of a bare status hop nobody can account for six months later.
"""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import AssessmentCostLine
from app.models.change_validation import (
    VALIDATION_WRITE_STATUSES, ValidationCheck,
)
from app.models.entities import User
from app.models.workflow import Department
from app.services import validation_checklist as catalog

VALIDATION_STATUS = "in_validation"


class ValidationError(ValueError):
    """Invalid validation-check operation; mapped to HTTP 400."""


class ValidationService:

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------
    @staticmethod
    async def may_write(session: AsyncSession, change: ChangeRequest,
                        department_id: int, actor: User) -> bool:
        """A member of that department while the change is in validation, or
        the people who run the programme (PM, admin) at any time.

        Same shape as ImplementationService.may_write with the window moved
        one stage along. The window matters more here than it did there: a
        check ticked after the change was released is a signature on a
        decision that had already been made.
        """
        from app.services.meeting_service import MeetingService
        from app.services.workflow_service import WorkflowService
        if (actor.effective_role == "admin"
                or await MeetingService.user_is_pm_member(session, actor)):
            return True
        if change.status != VALIDATION_STATUS:
            return False
        return await WorkflowService.actor_in_department(
            session, actor, department_id)

    @staticmethod
    async def may_acknowledge_weight_delta(
        session: AsyncSession, change: ChangeRequest, actor: User,
    ) -> bool:
        """Whoever may put a price in front of the customer. Acknowledging the
        delta IS the commercial decision — re-quote it or absorb it — so it
        belongs to exactly the set that owns the quoted price."""
        from app.services.change_service import ChangeService
        return await ChangeService.user_can_set_quoted_price(
            session, actor, change)

    @staticmethod
    async def may_escalate(session: AsyncSession, change: ChangeRequest,
                           actor: User) -> bool:
        """Sending a change back from validation to implementation is a
        re-plan: the timing moves and the commercial terms may have to be
        renegotiated. PM (the timing) and Sales/lead/admin (the terms) are the
        two sides of that conversation, and nobody else should be able to
        start it on their own."""
        from app.services.change_service import ChangeService
        from app.services.meeting_service import MeetingService
        if await MeetingService.user_is_pm(session, actor):
            return True
        return await ChangeService.user_can_set_quoted_price(
            session, actor, change)

    # ------------------------------------------------------------------
    # The rows
    # ------------------------------------------------------------------
    @staticmethod
    async def _department_names(session: AsyncSession) -> dict[int, str]:
        return dict((await session.execute(
            select(Department.id, Department.name))).all())

    @staticmethod
    async def implementing_department_ids(
        session: AsyncSession, change: ChangeRequest,
    ) -> list[int]:
        """One derivation of "who is on the hook", shared with stage 8."""
        from app.services.implementation_service import ImplementationService
        return await ImplementationService.implementing_department_ids(
            session, change)

    @staticmethod
    async def list_checks(session: AsyncSession,
                          change: ChangeRequest) -> list[ValidationCheck]:
        return list((await session.execute(
            select(ValidationCheck)
            .where(ValidationCheck.change_id == change.id)
            .order_by(ValidationCheck.department_id, ValidationCheck.id)
        )).scalars().all())

    @staticmethod
    async def ensure_checks(session: AsyncSession,
                            change: ChangeRequest) -> list[ValidationCheck]:
        """Seed the catalog's rows for every implementing department.

        Idempotent by construction: only the (department, key) pairs that are
        missing are inserted, and the unique constraint is the backstop. A
        department that later prices work on the change picks up its rows the
        next time this runs, so the checklist follows the costing rather than
        freezing at whatever the first read saw.

        NOT a write anybody has to authorize: seeding says "these checks are
        owed", which is a restatement of the catalog and the costing, not a
        claim about the work.
        """
        existing = await ValidationService.list_checks(session, change)
        have = {(row.department_id, row.check_key) for row in existing}
        names = await ValidationService._department_names(session)
        created = []
        for dept_id in await ValidationService.implementing_department_ids(
                session, change):
            for item in catalog.items_for(names.get(dept_id)):
                if (dept_id, item["key"]) in have:
                    continue
                row = ValidationCheck(
                    change_id=change.id, department_id=dept_id,
                    check_key=item["key"], status="open")
                session.add(row)
                created.append(row)
        if created:
            await session.flush()
            existing = await ValidationService.list_checks(session, change)
        return existing

    # ------------------------------------------------------------------
    # The costing assumptions the measurements are held against
    # ------------------------------------------------------------------
    @staticmethod
    async def planned_cycle_seconds_by_department(
        session: AsyncSession, change: ChangeRequest,
    ) -> dict[int, float]:
        """The costing's LIFECYCLE assumption per department, in seconds.

        A lifecycle cost line prices the change per part: minutes_per_part is
        the time the department said each part would gain (or, negative, save)
        for the life of the programme. That is the only cycle-time number the
        costing ever states, so it is the only thing a measured cycle time can
        be held against, and it is a DELTA — the payload says so rather than
        pretending the costing knew the absolute cycle time of the line.

        Departments with no minutes on any line are absent from the map, which
        the payload renders as null: "no assumption to compare against" is a
        different answer from "zero seconds".
        """
        rows = (await session.execute(
            select(ChangeAssessment.department_id,
                   func.sum(AssessmentCostLine.minutes_per_part))
            .select_from(AssessmentCostLine)
            .join(ChangeAssessment,
                  ChangeAssessment.id == AssessmentCostLine.assessment_id)
            .where(ChangeAssessment.change_id == change.id,
                   AssessmentCostLine.minutes_per_part.is_not(None))
            .group_by(ChangeAssessment.department_id))).all()
        return {dept_id: round(float(minutes) * 60.0, 3)
                for dept_id, minutes in rows if minutes is not None}

    @staticmethod
    def weight_delta(change: ChangeRequest) -> float | None:
        """Validated minus estimated, in grams. None while either half is
        missing — a delta against an absent estimate is not zero, it is
        unanswerable."""
        if (change.validated_part_weight_g is None
                or change.estimated_part_weight_g is None):
            return None
        return round(float(change.validated_part_weight_g)
                     - float(change.estimated_part_weight_g), 2)

    @staticmethod
    def weight_delta_open(change: ChangeRequest) -> bool:
        """Is there a commercial loose end from the weight validation?

        Deliberately simple: a nonzero delta that nobody has acknowledged.
        Watching quoted_price for a subsequent edit was the alternative and it
        lies in both directions — a quote changed for an unrelated reason would
        clear the flag, and a quote deliberately left alone could never clear
        it. An explicit acknowledgement is one click and says what happened.
        """
        delta = ValidationService.weight_delta(change)
        return bool(delta) and change.weight_delta_ack_at is None

    # ------------------------------------------------------------------
    # The state payload
    # ------------------------------------------------------------------
    @staticmethod
    async def state(session: AsyncSession, change: ChangeRequest,
                    *, ensure: bool = True) -> dict:
        """Per implementing department, its checks and their answers.

        NOT department-scoped for reading, unlike bookings: a validation
        verdict is a statement about the CHANGE, and a department that can see
        it is about to be released ought to see what is still open. The write
        side is scoped; the read side is the shared picture everyone argues
        over in the release meeting.
        """
        rows = (await ValidationService.ensure_checks(session, change)
                if ensure else await ValidationService.list_checks(
                    session, change))
        names = await ValidationService._department_names(session)
        planned = await ValidationService.planned_cycle_seconds_by_department(
            session, change)
        people = await ValidationService._names(
            session, [r.checked_by for r in rows] + [change.weight_delta_ack_by])
        estimate = (float(change.estimated_part_weight_g)
                    if change.estimated_part_weight_g is not None else None)
        delta = ValidationService.weight_delta(change)

        by_dept: dict[int, list[ValidationCheck]] = {}
        for row in rows:
            by_dept.setdefault(row.department_id, []).append(row)

        departments = []
        for dept_id in sorted(by_dept):
            dept_name = names.get(dept_id)
            stored = {r.check_key: r for r in by_dept[dept_id]}
            checks = []
            # Catalog order, not insertion order: the list reads the way the
            # rule book states it. Keys stored before a catalog change still
            # surface, at the end, so a retired check never silently vanishes
            # from a change that already answered it.
            keys = catalog.keys_for(dept_name)
            keys += [k for k in stored if k not in keys]
            for key in keys:
                row = stored.get(key)
                item = catalog.item_for(key, dept_name) or {
                    "key": key, "label_de": key, "label_en": key,
                    "expects_value": False, "unit": None, "extra": True}
                entry = {
                    "check_key": key,
                    "label_de": item["label_de"], "label_en": item["label_en"],
                    "expects_value": item["expects_value"],
                    "unit": item["unit"],
                    "status": row.status if row else "open",
                    "value": row.value if row else None,
                    "note": row.note if row else None,
                    "checked_by": row.checked_by if row else None,
                    "checked_by_name": (people.get(row.checked_by)
                                        if row else None),
                    "checked_at": row.checked_at if row else None,
                }
                if key == catalog.CYCLE_TIME_KEY:
                    # The costing never stated an absolute cycle time, only
                    # the seconds this change adds per part. Named as what it
                    # is so nobody subtracts a measurement from it.
                    entry["planned_delta_seconds"] = planned.get(dept_id)
                if key == catalog.WEIGHT_KEY:
                    entry["estimated_part_weight_g"] = estimate
                    entry["delta_g"] = delta
                checks.append(entry)
            answered = [c for c in checks if c["status"] in VALIDATION_WRITE_STATUSES]
            departments.append({
                "department_id": dept_id,
                "department_name": dept_name,
                "checks": checks,
                "open_count": len(checks) - len(answered),
                "failed_count": sum(1 for c in checks if c["status"] == "failed"),
                "all_passed": bool(checks) and all(
                    c["status"] == "passed" for c in checks),
            })

        all_checks = [c for d in departments for c in d["checks"]]
        # The costing's lifecycle assumption for the change as a whole, in the
        # unit the costing states it (minutes per part). The measured cycle
        # times come in SECONDS, which is how a line measures; converting one
        # of them is the caller's job and the payload names both units so
        # nobody has to guess which one a bare number is in.
        planned_minutes = round(sum(planned.values()) / 60.0, 4) if planned else None
        return {
            "change_id": change.id,
            "status": change.status,
            "departments": departments,
            "planned_cycle_time_min_per_part": planned_minutes,
            # The weight triple, flat, because the card that renders it is not
            # per-department: the estimate Sales quoted, the number that came
            # off the scale, and the gap between them — computed HERE and
            # never in the client, so two screens cannot disagree about it.
            "weight_estimate_g": estimate,
            "validated_weight_g": (
                float(change.validated_part_weight_g)
                if change.validated_part_weight_g is not None else None),
            "weight_delta_g": delta,
            "weight_ack_at": change.weight_delta_ack_at,
            "weight_ack_by": change.weight_delta_ack_by,
            "weight_ack_by_name": people.get(change.weight_delta_ack_by),
            "weight_ack_note": change.weight_delta_ack_note,
            "check_count": len(all_checks),
            "open_count": sum(1 for c in all_checks if c["status"] == "open"),
            "failed_count": sum(1 for c in all_checks if c["status"] == "failed"),
            "all_passed": bool(all_checks) and all(
                c["status"] == "passed" for c in all_checks),
            # Is Sales still carrying the quote-update errand? Same predicate
            # the my-tasks row is built from, so the badge and the task agree.
            "weight_quote_update_open": ValidationService.weight_delta_open(
                change),
            "release_blocker": await ValidationService.release_blocker(
                session, change, rows=rows),
        }

    @staticmethod
    async def _names(session: AsyncSession, ids) -> dict[int, str]:
        wanted = {i for i in ids if i is not None}
        if not wanted:
            return {}
        return dict((await session.execute(
            select(User.id, User.full_name).where(User.id.in_(wanted)))).all())

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    @staticmethod
    async def record_check(
        session: AsyncSession, change: ChangeRequest, spec: dict, actor: User,
    ) -> ValidationCheck:
        department_id = spec["department_id"]
        check_key = spec["check_key"]
        status = spec.get("status")
        if status not in VALIDATION_WRITE_STATUSES:
            raise ValidationError(
                f"Invalid validation status '{status}' — "
                f"one of {', '.join(VALIDATION_WRITE_STATUSES)}")

        implementing = await ValidationService.implementing_department_ids(
            session, change)
        if department_id not in implementing:
            raise ValidationError(
                f"Department {department_id} is not implementing this change — "
                "only departments that costed work on it validate it")
        names = await ValidationService._department_names(session)
        dept_name = names.get(department_id)
        item = catalog.item_for(check_key, dept_name)
        if item is None:
            raise ValidationError(
                f"'{check_key}' is not a validation check for "
                f"{dept_name or f'department {department_id}'}")

        value = spec.get("value")
        if value is not None:
            value = round(float(value), 3)
        if status == "passed" and item["expects_value"] and value is None:
            raise ValidationError(
                f"{item['label_en']} is a measurement — record the value "
                f"({item['unit']}) to pass it")

        rows = await ValidationService.ensure_checks(session, change)
        row = next((r for r in rows if r.department_id == department_id
                    and r.check_key == check_key), None)
        if row is None:      # catalog changed under a live change
            row = ValidationCheck(change_id=change.id,
                                  department_id=department_id,
                                  check_key=check_key, status="open")
            session.add(row)
        old_status, old_value = row.status, row.value
        row.status = status
        # A value is kept when the caller does not restate it: correcting a
        # 'passed' to 'failed' should not silently erase the measurement that
        # is the reason for the argument.
        if value is not None:
            row.value = value
        if spec.get("note") is not None:
            row.note = spec.get("note") or None
        row.checked_by = actor.id
        row.checked_at = datetime.utcnow()
        await session.flush()

        from app.services.change_service import ChangeService
        unit = f" {item['unit']}" if item["unit"] else ""
        shown = "" if row.value is None else f" ({row.value:g}{unit})"
        await ChangeService.append_changelog(
            session, change, "validation_check",
            f"{item['label_en']} {status} for dept {department_id}{shown}",
            actor.id,
            field_name=f"validation_{check_key}",
            old_value={"status": old_status, "value": old_value},
            new_value={"department_id": department_id, "check_key": check_key,
                       "status": status, "value": row.value},
            notes=row.note)

        if check_key == catalog.WEIGHT_KEY and status == "passed":
            await ValidationService._stamp_validated_weight(
                session, change, row.value, actor)
        return row

    @staticmethod
    async def _stamp_validated_weight(
        session: AsyncSession, change: ChangeRequest, weight_g: float,
        actor: User,
    ) -> None:
        """The weighed part becomes the change's validated weight.

        Re-validating overwrites and re-opens the commercial question: the ack
        is cleared, because an acknowledgement of an old delta says nothing
        about a new one. Every previous value survives in the changelog.
        """
        old = (float(change.validated_part_weight_g)
               if change.validated_part_weight_g is not None else None)
        new = round(float(weight_g), 2)
        change.validated_part_weight_g = new
        change.validated_weight_by = actor.id
        change.validated_weight_at = datetime.utcnow()
        if old is not None and old != new:
            change.weight_delta_ack_at = None
            change.weight_delta_ack_by = None
            change.weight_delta_ack_note = None
        delta = ValidationService.weight_delta(change)
        await session.flush()
        from app.services.change_service import ChangeService
        await ChangeService.append_changelog(
            session, change, "weight_validated",
            f"Part weight validated at {new:g} g"
            + ("" if delta is None else f" ({delta:+g} g vs estimate)"),
            actor.id, field_name="validated_part_weight_g",
            old_value={"weight_g": old} if old is not None else None,
            new_value={"weight_g": new, "delta_g": delta})

    @staticmethod
    async def acknowledge_weight_delta(
        session: AsyncSession, change: ChangeRequest, note: str | None,
        actor: User,
    ) -> ChangeRequest:
        """Sales closes the commercial loop the weight delta opened."""
        delta = ValidationService.weight_delta(change)
        if delta is None:
            raise ValidationError(
                "No weight delta to acknowledge — the part weight has not been "
                "both estimated and validated")
        if not delta:
            raise ValidationError(
                "The validated weight matches the estimate — there is nothing "
                "to update the quote for")
        if change.weight_delta_ack_at is not None:
            raise ValidationError("That weight delta is already acknowledged")
        change.weight_delta_ack_at = datetime.utcnow()
        change.weight_delta_ack_by = actor.id
        change.weight_delta_ack_note = (note or "").strip() or None
        await session.flush()
        from app.services.change_service import ChangeService
        await ChangeService.append_changelog(
            session, change, "weight_delta_acknowledged",
            f"Weight delta of {delta:+g} g acknowledged for the quote",
            actor.id, field_name="weight_delta_ack_at",
            new_value={"delta_g": delta, "quoted_price": change.quoted_price},
            notes=change.weight_delta_ack_note)
        return change

    # ------------------------------------------------------------------
    # The verdict
    # ------------------------------------------------------------------
    @staticmethod
    async def release_blocker(
        session: AsyncSession, change: ChangeRequest,
        *, rows: list[ValidationCheck] | None = None,
    ) -> str | None:
        """Why this change may not be released yet, in the words of the checks.

        Vacuous when NO rows exist: a change that never had a validation
        checklist — everything created before this module, and every flow that
        drives a change through without opening stage 9 — releases exactly as
        it did before. The rows are what turn the guard on, and they appear the
        first time anybody looks at the validation state.

        Reads rows only; never seeds. A guard that created the very rows it
        then refuses on would fail a release nobody had been asked about.
        """
        if rows is None:
            rows = await ValidationService.list_checks(session, change)
        if not rows:
            return None
        names = await ValidationService._department_names(session)

        def _name(row) -> str:
            dept = names.get(row.department_id) or f"dept {row.department_id}"
            return f"{dept}: {catalog.label_for(row.check_key, names.get(row.department_id))}"

        failed = [r for r in rows if r.status == "failed"]
        if failed:
            return ("validation failed — " + ", ".join(sorted(map(_name, failed)))
                    + ". Send the change back to implementation with a reason")
        outstanding = [r for r in rows if r.status != "passed"]
        if outstanding:
            return ("validation incomplete — still open: "
                    + ", ".join(sorted(map(_name, outstanding))))
        return None
