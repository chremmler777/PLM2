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
#: §10 (RELEASE_V2): a weight delta reaches Sales above this share of the
#: estimate (or on a FAIL).
WEIGHT_DELTA_SALES_SHARE = 0.02
#: D5 (Christoph 2026-10-19): the department that confirms the limits a
#: measurer set with the first measurement (A5-02); was Quality.
LIMITS_CONFIRMER_DEPARTMENT = "APQP"


class ValidationError(ValueError):
    """Invalid validation-check operation; mapped to HTTP 400."""


class ValidationService:

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------
    @staticmethod
    async def may_write(session: AsyncSession, change: ChangeRequest,
                        department_id: int, actor: User) -> bool:
        """A member of that department while the change is in validation.

        With RELEASE_V2 (C7, spec §10 "rows answered by their department")
        that is the whole rule: PM or the lead record a department's check
        only when that department has no real member here
        (change_people.staffed_department_ids), and only in validation; a
        real admin's own department rows do not count (HARD #3, it acts as
        the department). The same rule decides the retest of a failed
        check (failed_overwrite_refusal). Otherwise the run team could fix the limits and
        PASS another department's measurement with no evidence of its own,
        or fail a check on a released change. Off the switch: PM and admin
        at any time, as before."""
        return (await ValidationService.write_rights(
            session, change, [department_id], actor)).get(department_id, False)

    @staticmethod
    async def write_rights(session: AsyncSession, change: ChangeRequest,
                           department_ids, actor: User) -> dict[int, bool]:
        """may_write for several departments at once (a few queries)."""
        from app.services import cm_switches
        from app.services.meeting_service import MeetingService
        from app.services.workflow_service import WorkflowService
        ids = [d for d in dict.fromkeys(department_ids) if d is not None]
        if not cm_switches.on("RELEASE_V2"):
            if (actor.effective_role == "admin"
                    or await MeetingService.user_is_pm_member(session, actor)):
                return {d: True for d in ids}
            if change.status != VALIDATION_STATUS:
                return {d: False for d in ids}
            mine = set(await WorkflowService.effective_department_ids(session, actor))
            return {d: d in mine for d in ids}
        from app.services.change_people import (
            hard3_blind, holds_lead, staffed_department_ids,
        )
        from app.services.hub_departments import is_hub_account
        # retest N4 (the T5 rule): a hub admin's AdminPanel department roles
        # are real memberships and count; only a local admin account's
        # blanket rows stay blind (it acts as the department)
        if change.status != VALIDATION_STATUS or (
                hard3_blind(actor) and not is_hub_account(actor)):
            # HARD #3: a real admin's own department rows do not count (it
            # acts as the department to record for it)
            return {d: False for d in ids}
        mine = set(await WorkflowService.effective_department_ids(session, actor))
        out = {d: d in mine for d in ids}
        rest = [d for d in ids if not out[d]]
        if rest:
            pm = (await session.execute(
                select(Department.id).where(Department.name == "Project Manager")
                .limit(1))).scalar_one_or_none()
            if holds_lead(change, actor) or (pm is not None and pm in mine):
                # one rule for the first measurement and the retest: PM or
                # the lead for a department with no real member here
                staffed = await staffed_department_ids(session, change, rest)
                out.update({d: d not in staffed for d in rest})
        return out

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
        if not delta or change.weight_delta_ack_at is not None:
            return False
        from app.services import cm_switches
        if cm_switches.on("RELEASE_V2"):
            # §10: Sales hears of the weight only on a FAIL (a notice, see
            # ValidationIssueService.on_check_failed) or a delta > 2 % of
            # the estimate the quote was built on
            est = float(change.estimated_part_weight_g or 0)
            return est <= 0 or abs(delta) > WEIGHT_DELTA_SALES_SHARE * est
        return True

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
        planned_total_s = (round(sum(planned.values()), 3)
                           if planned else None)
        people = await ValidationService._names(
            session, [r.checked_by for r in rows] + [change.weight_delta_ack_by]
            + [x for r in rows for x in (r.limits_set_by, r.limits_confirmed_by)])
        estimate = (float(change.estimated_part_weight_g)
                    if change.estimated_part_weight_g is not None else None)
        delta = ValidationService.weight_delta(change)
        measured = await ValidationService.measurements_by_check(session, change)
        people.update(await ValidationService._names(
            session, [m.measured_by for ms in measured.values() for m in ms
                      if m.measured_by not in people]))

        by_dept: dict[int, list[ValidationCheck]] = {}
        for row in rows:
            by_dept.setdefault(row.department_id, []).append(row)

        departments = []
        for dept_id in sorted(by_dept):
            dept_name = names.get(dept_id)
            stored = {r.check_key: r for r in by_dept[dept_id]}
            checks = []
            # Catalog order, not insertion order: the list reads the way the
            # rule book states it. Keys an older catalog seeded still surface,
            # at the end and marked retired, when somebody answered them, so
            # an answer never silently vanishes; an unanswered retired row is
            # not owed any more and is left out. Retired rows never count.
            current = catalog.keys_for(dept_name)
            keys = current + [k for k in stored if k not in current
                              and stored[k].status != "open"]
            for key in keys:
                row = stored.get(key)
                item = (catalog.item_for(key, dept_name)
                        or catalog.any_item_for(key) or {
                            "key": key, "label_de": key, "label_en": key,
                            "expects_value": False, "unit": None,
                            "extra": True})
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
                    "retired": key not in current,
                    # A5-10 b: 'passed' names the measuring report
                    "pass_needs_report": ValidationService.pass_needs_report(
                        key, catalog.computed_unit(key, dept_name)),
                    # what that reference is (the field's words)
                    "pass_ref_prompt": (ValidationService.REPORT_PROMPTS[key][0]
                                        if ValidationService.pass_needs_report(
                                            key, catalog.computed_unit(key, dept_name))
                                        else None),
                }
                if key == catalog.CYCLE_TIME_KEY:
                    # The costing never stated an absolute cycle time, only
                    # the seconds this change adds per part. Named as what it
                    # is so nobody subtracts a measurement from it.
                    if dept_name == catalog.CYCLE_TIME_DEPARTMENT:
                        # The Tool Engineer measures the line for the whole
                        # change, so its row is held against the change-wide
                        # sum of every department's lifecycle minutes (it
                        # rarely prices lifecycle minutes itself).
                        entry["planned_delta_seconds"] = planned_total_s
                        entry["planned_delta_source"] = (
                            "change_lifecycle_total"
                            if planned_total_s is not None else None)
                    else:
                        entry["planned_delta_seconds"] = planned.get(dept_id)
                        entry["planned_delta_source"] = (
                            "department_lifecycle"
                            if planned.get(dept_id) is not None else None)
                if key == catalog.WEIGHT_KEY:
                    entry["estimated_part_weight_g"] = estimate
                    entry["delta_g"] = delta
                computed = catalog.computed_unit(key, dept_name)
                if computed and key in current:
                    lo = row.lower_limit if row else None
                    hi = row.upper_limit if row else None
                    entry.update({
                        "computed": True, "unit_short": computed[1],
                        "needs_lot": key in catalog.NEEDS_LOT_REF,
                        "lower_limit": lo, "upper_limit": hi,
                        "spec_source": row.spec_source if row else None,
                        "check_id": row.id if row else None,
                        "limits_set_by_name": (people.get(row.limits_set_by)
                                               if row else None),
                        "limits_confirmed_by_name": (
                            people.get(row.limits_confirmed_by) if row else None),
                        "limits_confirmed_at": (row.limits_confirmed_at
                                                if row else None),
                        "limits_pending": bool(
                            row and ValidationService.limits_pending(row)),
                        "measurements": [{
                            "id": m.id, "sample_size": m.sample_size,
                            "min_value": m.min_value, "max_value": m.max_value,
                            "measuring_ref": m.measuring_ref, "lot_ref": m.lot_ref,
                            "what_changed_kind": m.what_changed_kind,
                            "what_changed_ref": m.what_changed_ref,
                            "result": m.result, "measured_by": m.measured_by,
                            "measured_by_name": people.get(m.measured_by),
                            "measured_at": m.measured_at,
                            "line": ValidationService.measurement_line(
                                m, computed[1], lo, hi),
                        } for m in (measured.get(row.id, []) if row else [])],
                    })
                checks.append(entry)
            if not checks:
                continue
            owed = [c for c in checks if not c["retired"]]
            answered = [c for c in owed if c["status"] in VALIDATION_WRITE_STATUSES]
            departments.append({
                "department_id": dept_id,
                "department_name": dept_name,
                "checks": checks,
                "open_count": len(owed) - len(answered),
                "failed_count": sum(1 for c in owed if c["status"] == "failed"),
                "all_passed": bool(owed) and all(
                    c["status"] == "passed" for c in owed),
            })

        all_checks = [c for d in departments for c in d["checks"]
                      if not c["retired"]]
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
            # §10 (RELEASE_V2): "Not releasable: <check> vs <limits>; fix:
            # <who>, retest <day>; concession: <state>", and the concessions
            # in force ("Accepted under concession VI-n until <date>")
            **await ValidationService._release_words(session, change),
        }

    @staticmethod
    async def _release_words(session: AsyncSession, change: ChangeRequest) -> dict:
        from app.services.validation_issue_service import ValidationIssueService as VIS
        return {"release_line": await VIS.release_line(session, change),
                "active_concessions": (await VIS.active_concessions(session, change)
                                       if VIS.fix_rule_on() else [])}

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

        implementing = await ValidationService.implementing_department_ids(
            session, change)
        if department_id not in implementing:
            raise ValidationError(
                f"Department {department_id} is not implementing this change: "
                "only departments that costed work on it validate it")
        names = await ValidationService._department_names(session)
        dept_name = names.get(department_id)
        item = catalog.item_for(check_key, dept_name)
        if item is None:
            raise ValidationError(
                f"'{check_key}' is not a validation check for "
                f"{dept_name or f'department {department_id}'}")

        from app.services import cm_switches
        computed = catalog.computed_unit(check_key, dept_name)
        measurement = spec.get("measurement")
        if computed and (measurement is not None or cm_switches.on("RELEASE_V2")):
            return await ValidationService._record_measurement(
                session, change, department_id, check_key, item, computed,
                measurement, spec.get("note"), actor)
        if status not in VALIDATION_WRITE_STATUSES:
            raise ValidationError(
                f"Invalid validation status '{status}': "
                f"one of {', '.join(VALIDATION_WRITE_STATUSES)}")

        if status == "passed" and ValidationService.pass_needs_report(check_key, computed):
            # A5-10 b (RELEASE_V2, R4): a dimension check that is not
            # computed passes with the measuring report, not a plain tick
            from app.services.cm_rules import reference_refusal
            why = reference_refusal(spec.get("note"),
                                    *ValidationService.REPORT_PROMPTS[check_key])
            if why:
                raise ValidationError(why)
        value = spec.get("value")
        if value is not None:
            value = round(float(value), 3)
        if status == "passed" and item["expects_value"] and value is None:
            raise ValidationError(
                f"{item['label_en']} is a measurement: record the value "
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
        if old_status == "failed" and status != "failed":
            refusal = await ValidationService.failed_overwrite_refusal(
                session, change, department_id, spec.get("note"), actor)
            if refusal:
                raise ValidationError(refusal)
        row.status = status
        # A value is kept when the caller does not restate it: correcting a
        # 'passed' to 'failed' should not silently erase the measurement that
        # is the reason for the argument.
        if value is not None:
            row.value = value
        if spec.get("note") is not None:
            row.note = spec.get("note") or None
        elif status == "passed" and old_status != "passed":
            # the note said why it was not passing; a pass without a new
            # note leaves no stale explanation behind
            row.note = None
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
            notes=row.note, for_department_id=department_id)

        return await ValidationService._after_answer(
            session, change, row, old_status, actor)

    @staticmethod
    async def _after_answer(session: AsyncSession, change: ChangeRequest,
                            row: ValidationCheck, old_status: str,
                            actor: User) -> ValidationCheck:
        """What an answer sets off, the same for a tick and a measurement."""
        if row.check_key == catalog.WEIGHT_KEY and row.status == "passed":
            await ValidationService._stamp_validated_weight(
                session, change, row.value, actor)
        # Validation issues (spec §12): a passed re-answer closes the issue
        # linked to this check; a new failure sends one waiting for
        # re-validation back to fixing. A5-02: a PASS against limits only
        # the measurer stated closes nothing until APQP confirms them (D5).
        from app.services.validation_issue_service import ValidationIssueService
        if not ValidationService.limits_pending(row):
            await ValidationIssueService.on_check_answered(session, change, row, actor)
        if row.status == "failed" and old_status != "failed":
            # §10 (RELEASE_V2): a FAIL raises its issue with a Fix task for
            # Quality, tells the Sales contact of a failed weight, and an
            # urgent change's Management at once
            await ValidationIssueService.on_check_failed(session, change, row, actor)
        return row

    # ------------------------------------------------------------------
    # §10 computed checks (RELEASE_V2)
    # ------------------------------------------------------------------
    @staticmethod
    def measurement_line(m, unit: str, lower, upper) -> str:
        """'n=5, 503-516.2 g vs 495-515 g; scale WG-0042' (one line, §10)."""
        def f(v):
            return f"{float(v):g}"
        spec = (f" vs {f(lower)}-{f(upper)} {unit}"
                if lower is not None and upper is not None else "")
        lot = f", lot {m.lot_ref}" if m.lot_ref else ""
        return (f"n={m.sample_size}, {f(m.min_value)}-{f(m.max_value)} {unit}"
                f"{spec}; {m.measuring_ref}{lot}")

    @staticmethod
    async def measurements_by_check(session: AsyncSession,
                                    change: ChangeRequest) -> dict[int, list]:
        from app.models.change_validation import ValidationMeasurement
        out: dict[int, list] = {}
        for m in (await session.execute(
                select(ValidationMeasurement)
                .where(ValidationMeasurement.change_id == change.id)
                .order_by(ValidationMeasurement.id))).scalars().all():
            out.setdefault(m.check_id, []).append(m)
        return out

    @staticmethod
    async def _record_measurement(
        session: AsyncSession, change: ChangeRequest, department_id: int,
        check_key: str, item: dict, computed: tuple, m: dict | None,
        note, actor: User,
    ) -> ValidationCheck:
        """A computed check (§10): sample size n, min and max, the measuring
        report or device (cycle time: the lot). PASS only if both min and
        max lie inside the limits, which the first measurement fixes; a
        retest adds a row, keeps the failed one and names what changed."""
        from app.models.change_validation import (
            RETEST_CHANGE_KINDS, ValidationMeasurement,
        )
        from app.services.cm_rules import reference_refusal
        unit_label, unit = computed
        label = item["label_en"]
        if not isinstance(m, dict):
            raise ValidationError(
                f"{label} is computed from a measurement: enter the sample "
                f"size n, min and max ({unit}) and the measuring report or "
                "device id; the result follows from the limits")

        def num(key, what):
            v = m.get(key)
            if v is None or v == "":
                return None
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise ValidationError(f"{what} must be a number")
            if v != v or v in (float("inf"), float("-inf")):
                raise ValidationError(f"{what} must be a number")
            return round(v, 3)

        try:
            n = int(m.get("sample_size") or 0)
        except (TypeError, ValueError):
            n = 0
        if n < 1:
            raise ValidationError("The sample size n is at least 1 part (or cycle)")
        lo, hi = num("min_value", "Min"), num("max_value", "Max")
        if lo is None or hi is None:
            raise ValidationError(f"Enter both min and max ({unit})")
        if lo > hi:
            raise ValidationError("The min is larger than the max")
        why = reference_refusal(m.get("measuring_ref"),
                                "The measuring report or device id",
                                "report MR-2026-118 or scale WG-0042")
        if why:
            raise ValidationError(why)
        lot = (m.get("lot_ref") or "").strip() or None
        if check_key in catalog.NEEDS_LOT_REF:
            why = reference_refusal(lot, "The lot the cycles ran on",
                                    "lot 2026-41-117")
            if why:
                raise ValidationError(why)

        rows = await ValidationService.ensure_checks(session, change)
        row = next((r for r in rows if r.department_id == department_id
                    and r.check_key == check_key), None)
        if row is None:
            row = ValidationCheck(change_id=change.id, department_id=department_id,
                                  check_key=check_key, status="open")
            session.add(row)
            await session.flush()

        old_status, old_value = row.status, row.value
        kind = (m.get("what_changed_kind") or "").strip() or None
        changed_ref = (m.get("what_changed_ref") or "").strip() or None
        if old_status == "failed":
            # a retest: its own department in validation (HARD #3), and what
            # changed since the failure
            refusal = await ValidationService.failed_overwrite_refusal(
                session, change, department_id, None, actor, note_rule=False)
            if refusal:
                raise ValidationError(refusal)
            if kind not in RETEST_CHANGE_KINDS:
                raise ValidationError(
                    "What changed since the failure: pick parameter, tool, "
                    "material or method, and give its reference")
            why = reference_refusal(changed_ref, "What changed since the failure",
                                    "holding pressure -5 bar, PS-114 rev C")
            if why:
                raise ValidationError(why)
        else:
            kind = changed_ref = None

        new_lo, new_hi = num("lower_limit", "The lower limit"), num(
            "upper_limit", "The upper limit")
        source = (m.get("spec_source") or "").strip() or None
        if row.lower_limit is None or row.upper_limit is None:
            if new_lo is None or new_hi is None:
                raise ValidationError(
                    f"The first measurement sets the limits: enter the lower "
                    f"and upper limit ({unit}) and where they come from")
            if new_lo >= new_hi:
                raise ValidationError("The lower limit is below the upper limit")
            why = reference_refusal(source, "Where the limits come from",
                                    "drawing 886.197 D or process sheet PS-114")
            if why:
                raise ValidationError(why)
            row.lower_limit, row.upper_limit = new_lo, new_hi
            row.spec_source = source[:200]
            # A5-02: the measurer's own limits; a PASS against them counts
            # once APQP (D5; never the setter) confirms them
            row.limits_set_by = actor.id
            row.limits_confirmed_by = row.limits_confirmed_at = None
        elif ((new_lo is not None and new_lo != float(row.lower_limit))
              or (new_hi is not None and new_hi != float(row.upper_limit))):
            raise ValidationError(
                f"The limits are fixed by the first measurement "
                f"({float(row.lower_limit):g}-{float(row.upper_limit):g} {unit}): "
                "a different spec is a concession (Quality), not a retest")

        lower, upper = float(row.lower_limit), float(row.upper_limit)
        result = "passed" if lower <= lo and hi <= upper else "failed"
        meas = ValidationMeasurement(
            check_id=row.id, change_id=change.id, sample_size=n,
            min_value=lo, max_value=hi,
            measuring_ref=m["measuring_ref"].strip()[:200],
            lot_ref=lot[:120] if lot else None,
            what_changed_kind=kind,
            what_changed_ref=changed_ref[:200] if changed_ref else None,
            result=result, measured_by=actor.id, measured_at=datetime.utcnow())
        session.add(meas)
        row.status = result
        row.value = round((lo + hi) / 2, 3)
        row.note = (note or "").strip() or None
        row.checked_by = actor.id
        row.checked_at = datetime.utcnow()
        await session.flush()

        from app.services.change_service import ChangeService
        line = ValidationService.measurement_line(meas, unit, lower, upper)
        await ChangeService.append_changelog(
            session, change, "validation_check",
            f"{label} {result} for dept {department_id} ({line})", actor.id,
            field_name=f"validation_{check_key}",
            old_value={"status": old_status, "value": old_value},
            new_value={"department_id": department_id, "check_key": check_key,
                       "status": result, "value": row.value,
                       "measurement_id": meas.id, "sample_size": n,
                       "min": lo, "max": hi, "lower_limit": lower,
                       "upper_limit": upper,
                       **({"what_changed": kind} if kind else {})},
            notes=changed_ref or row.note, for_department_id=department_id)
        return await ValidationService._after_answer(
            session, change, row, old_status, actor)

    #: A5-10 b: the plain dimension check of Tool, Manufacturing and
    #: Process Engineer ('Part measured'), passed with the report
    #: Click-through R38 (R4): Development's 'Revision levels raised per
    #: customer statement and verified' passes with the index that shows it.
    #: key -> (what is asked, an example)
    REPORT_PROMPTS = {
        "measured": ("The measuring report (number or file name)",
                     "measuring report MR-2026-118"),
        "revision_bump": ("The raised index that shows it (drawing or PLM "
                          "revision, per the customer statement)",
                          "886.197 index D in drawing and PLM"),
    }
    REPORT_KEYS = frozenset(REPORT_PROMPTS)

    @staticmethod
    def pass_needs_report(check_key: str, computed) -> bool:
        from app.services import cm_switches
        return (cm_switches.on("RELEASE_V2") and not computed
                and check_key in ValidationService.REPORT_KEYS)

    @staticmethod
    def limits_pending(row) -> bool:
        """A5-02 (RELEASE_V2): a PASS held against limits nobody but their
        setter confirmed does not count yet."""
        from app.services import cm_switches
        return cm_switches.on("RELEASE_V2") and bool(row.limits_pending)

    @staticmethod
    async def _limits_department_id(session: AsyncSession) -> int | None:
        return (await session.execute(select(Department.id).where(
            Department.name == LIMITS_CONFIRMER_DEPARTMENT,
            Department.is_active.is_(True)).limit(1))).scalar_one_or_none()

    @staticmethod
    async def limits_confirmers(session: AsyncSession, change: ChangeRequest,
                                set_by: int | None = None
                                ) -> tuple[bool, set[int]]:
        """(apqp_confirms, ids): who confirms a check's limits, never
        `set_by` (whoever set them). D5 (Christoph 2026-10-19): APQP's real
        members, not Quality. With no APQP member here other than the setter
        (or APQP retired): the lead who can act (change_people.coordinator),
        then Project Management's real members, so a lead or the only APQP
        member who measured is never the only one left (A5-02: no deadlock
        on HARD #3)."""
        from app.services.change_people import (
            coordinator, department_members_of_change_org, staffed_department_ids,
        )
        apqp = await ValidationService._limits_department_id(session)
        if apqp is not None and await staffed_department_ids(session, change, [apqp]):
            ids = set(await department_members_of_change_org(
                session, change, [apqp], real_only=True))
            ids.discard(set_by)
            if ids:
                return True, ids
        lead_id, _ = await coordinator(session, change)
        pm = (await session.execute(select(Department.id).where(
            Department.name == "Project Manager", Department.is_active.is_(True))
            .limit(1))).scalar_one_or_none()
        ids = set(await department_members_of_change_org(
            session, change, [pm] if pm else [], real_only=True))
        if lead_id is not None:
            ids.add(lead_id)
        ids.discard(set_by)
        return False, ids

    @staticmethod
    async def _confirmers_words(session: AsyncSession, change: ChangeRequest,
                                set_by: int | None) -> str:
        """Who can confirm, in words, for a refusal (R5: name the unblocker)."""
        staffed, ids = await ValidationService.limits_confirmers(session, change, set_by)
        names = sorted(n for n in (await ValidationService._names(
            session, list(ids))).values() if n)
        d = LIMITS_CONFIRMER_DEPARTMENT
        if not names:
            return (f"nobody else here can confirm them: give {d} (or Project "
                    "Management) a member")
        who = ", ".join(names[:3]) + (f" (+{len(names) - 3})" if len(names) > 3 else "")
        return (f"{d} confirms them: {who}" if staffed else
                f"{d} has no other member here: {who} confirm them")

    @staticmethod
    async def limits_confirm_refusal(session: AsyncSession, change: ChangeRequest,
                                     row, actor: User) -> str | None:
        """None when `actor` may confirm (or correct) the row's limits: an
        APQP member (D5; acts-as aware) who did not set them, else (no other
        APQP member here) the lead who can act or a Project Management
        member; never the person who set them, never a real admin alone
        (HARD #3). A refusal names who can."""
        from app.services import cm_switches
        from app.services.change_people import hard3_blind, is_acting
        if not cm_switches.on("RELEASE_V2"):
            return "Limits are confirmed only with the release rules on"
        if row.lower_limit is None:
            return "The limits are set with the first measurement"
        if row.limits_set_by is not None and row.limits_set_by == actor.id:
            return ("You set these limits; the department being judged does not "
                    "set its own pass criterion alone. " + await
                    ValidationService._confirmers_words(session, change, row.limits_set_by))
        if hard3_blind(actor):
            return (f"An admin confirms limits only acting as "
                    f"{LIMITS_CONFIRMER_DEPARTMENT} (no admin shortcut: it holds the release)")
        from app.services.workflow_service import WorkflowService
        mine = set(await WorkflowService.effective_department_ids(session, actor))
        apqp = await ValidationService._limits_department_id(session)
        if apqp is not None and apqp in mine:
            return None
        staffed, ids = await ValidationService.limits_confirmers(
            session, change, row.limits_set_by)
        if not staffed and not is_acting(actor) and actor.id in ids:
            return None
        return await ValidationService._confirmers_words(session, change, row.limits_set_by)

    @staticmethod
    async def confirm_limits(session: AsyncSession, change: ChangeRequest,
                             check_id: int, spec: dict, actor: User):
        """A5-02 / D5: APQP confirms the limits the measurer set (one click),
        or corrects them; the latest measurement is held against the
        confirmed limits and the PASS (or a FAIL) counts from now on."""
        from app.models.change_validation import ValidationMeasurement
        from app.services.cm_rules import reference_refusal
        row = await session.get(ValidationCheck, check_id)
        if row is None or row.change_id != change.id:
            raise ValidationError("No such validation check on this change")
        why = await ValidationService.limits_confirm_refusal(session, change, row, actor)
        if why:
            raise PermissionError(why)
        if not ValidationService.limits_pending(row):
            # a FAIL counts at once; changing the limits after it would lift
            # HARD #3 without a concession
            raise ValidationError(
                f"Only a PASS against limits nobody confirmed waits on {LIMITS_CONFIRMER_DEPARTMENT} "
                "(a different spec after a FAIL is a concession)")
        lo, hi = spec.get("lower_limit"), spec.get("upper_limit")
        source = (spec.get("spec_source") or "").strip() or None
        corrected = lo is not None or hi is not None
        if corrected:
            try:
                lo, hi = round(float(lo), 3), round(float(hi), 3)
            except (TypeError, ValueError):
                raise ValidationError("Enter both limits as numbers")
            if lo >= hi:
                raise ValidationError("The lower limit is below the upper limit")
            refusal = reference_refusal(source, "Where the limits come from",
                                        "drawing 886.197 D or process sheet PS-114")
            if refusal:
                raise ValidationError(refusal)
            row.lower_limit, row.upper_limit = lo, hi
            row.spec_source = source[:200]
            row.limits_set_by = actor.id
        row.limits_confirmed_by = actor.id
        row.limits_confirmed_at = datetime.utcnow()
        old_status = row.status
        last = (await session.execute(
            select(ValidationMeasurement).where(ValidationMeasurement.check_id == row.id)
            .order_by(ValidationMeasurement.id.desc()).limit(1))).scalar_one_or_none()
        if last is not None:
            ok = float(row.lower_limit) <= float(last.min_value) \
                and float(last.max_value) <= float(row.upper_limit)
            row.status = "passed" if ok else "failed"
            last.result = row.status
        await session.flush()
        names = await ValidationService._department_names(session)
        label = catalog.label_for(row.check_key, names.get(row.department_id))
        from app.services.change_service import ChangeService
        await ChangeService.append_changelog(
            session, change, "validation_limits",
            f"{label}: limits {float(row.lower_limit):g}-{float(row.upper_limit):g} "
            f"{'corrected' if corrected else 'confirmed'} ({row.spec_source}); "
            f"{row.status}", actor.id,
            field_name=f"validation_{row.check_key}_limits",
            new_value={"lower_limit": float(row.lower_limit),
                       "upper_limit": float(row.upper_limit),
                       "status": row.status, "corrected": corrected},
            for_department_id=row.department_id)
        # the PASS waited on this confirm: what a pass (or a new FAIL) sets
        # off runs now; the weight was stamped at the measurement already
        if (row.check_key == catalog.WEIGHT_KEY and row.status == "passed"
                and old_status != "passed"):
            await ValidationService._stamp_validated_weight(
                session, change, row.value, actor)
        from app.services.validation_issue_service import ValidationIssueService
        await ValidationIssueService.on_check_answered(session, change, row, actor)
        if row.status == "failed" and old_status != "failed":
            await ValidationIssueService.on_check_failed(session, change, row, actor)
        return row

    @staticmethod
    async def failed_overwrite_refusal(
        session: AsyncSession, change: ChangeRequest, department_id: int,
        note, actor: User, *, note_rule: bool = True,
    ) -> str | None:
        """HARD #3 (C7, RELEASE_V2): a FAILED check is answered again only by
        a retest, in validation, by whoever records the first measurement
        (write_rights: a member of its department, acts-as aware; PM or the
        lead only for a department with no real member here; never a real
        admin), with what changed since the failure (spec §10). Otherwise
        the failure, and the issue linked to it, could be lifted without a
        fix or a concession. None = allowed."""
        from app.services import cm_switches
        if not cm_switches.on("RELEASE_V2"):
            return None
        if change.status != VALIDATION_STATUS:
            return ("A failed check is answered again only by a retest while "
                    "the change is in validation")
        if not (await ValidationService.write_rights(
                session, change, [department_id], actor)).get(department_id):
            return ("A failed check is retested by its own department (Project "
                    "Management or the lead only when it has no member here): "
                    "no admin shortcut (the other exit is a "
                    "concession, Quality's decision)")
        if not note_rule:       # a measurement names it in its own fields
            return None
        from app.services.cm_rules import reference_refusal
        return reference_refusal(
            note, "What changed since the failure (parameter, tool, material "
                  "or method + reference)")

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
                "No weight delta to acknowledge: the part weight has not been "
                "both estimated and validated")
        if not delta:
            raise ValidationError(
                "The validated weight matches the estimate: there is nothing "
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
    async def release_parts(
        session: AsyncSession, change: ChangeRequest,
    ) -> tuple[str | None, str | None]:
        """(failed, outstanding) in the words of release_blocker, split for
        C7: a FAILED check is HARD at release (only a concession lifts it),
        a check not answered yet stays a soft rule.

        A failed check is covered by a concession: a validation issue raised
        on that check (check_id) and closed 'accepted' (the customer accepted
        the deviation, route customer_concession) on a Quality member's
        decision. Vacuous with no rows."""
        rows = await ValidationService.list_checks(session, change)
        if not rows:
            return None, None
        names = await ValidationService._department_names(session)
        rows = [r for r in rows if r.check_key in catalog.keys_for(
            names.get(r.department_id))]

        def _name(row) -> str:
            dept = names.get(row.department_id) or f"dept {row.department_id}"
            return f"{dept}: {catalog.label_for(row.check_key, names.get(row.department_id))}"

        failed = [r for r in rows if r.status == "failed"]
        if failed:
            from app.models.change_validation_issue import ValidationIssue
            from app.services.validation_issue_service import ValidationIssueService
            # HARD #3: only a concession a Quality member decided counts (an
            # admin, PM or Sales alone cannot produce the exit)
            accepted = (await session.execute(
                select(ValidationIssue).where(
                    ValidationIssue.change_id == change.id,
                    ValidationIssue.check_id.in_([r.id for r in failed]),
                    ValidationIssue.status == "accepted",
                    ValidationIssue.route == "customer_concession"))).scalars().all()
            ok = await ValidationIssueService.quality_decided_ids(session, accepted)
            # a concession is for a quantity or until a date (§10): an
            # expired one no longer covers the failed check
            conceded = {i.check_id for i in accepted if i.id in ok
                        and ValidationIssueService.concession_in_force(i)}
            failed = [r for r in failed if r.id not in conceded]
        outstanding = [r for r in rows if r.status not in ("passed", "failed")]
        # A5-02: a PASS against the measurer's own limits is not yet a pass
        pending = [r for r in rows if ValidationService.limits_pending(r)]
        setters = await ValidationService._names(session, [r.limits_set_by for r in pending])
        words = sorted(map(_name, outstanding)) + sorted(
            f"{_name(r)} (limits set by {setters.get(r.limits_set_by) or 'the measurer'}: "
            f"{LIMITS_CONFIRMER_DEPARTMENT} confirms)" for r in pending)
        return (
            ("Validation failed: " + ", ".join(sorted(map(_name, failed)))
             + ". Fix it and retest (Quality's Fix task names who and when), or a "
             "concession (Quality)") if failed else None,
            ("Validation incomplete, still open: " + ", ".join(words)) if words else None,
        )

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
        from app.services import cm_switches
        if cm_switches.on("RELEASE_V2"):
            # C7: one wording with the HARD refusal; a failed check covered by
            # an accepted concession no longer holds.
            failed, outstanding = await ValidationService.release_parts(session, change)
            return failed or outstanding
        if rows is None:
            rows = await ValidationService.list_checks(session, change)
        if not rows:
            return None
        names = await ValidationService._department_names(session)
        # Only the checks the department owes under the current catalog: a
        # row an older catalog seeded (Development's 'sampled') is retired.
        rows = [r for r in rows if r.check_key in catalog.keys_for(
            names.get(r.department_id))]

        def _name(row) -> str:
            dept = names.get(row.department_id) or f"dept {row.department_id}"
            return f"{dept}: {catalog.label_for(row.check_key, names.get(row.department_id))}"

        failed = [r for r in rows if r.status == "failed"]
        if failed:
            return ("Validation failed: " + ", ".join(sorted(map(_name, failed)))
                    + ". Send the change back to implementation with a reason")
        outstanding = [r for r in rows if r.status != "passed"]
        if outstanding:
            return ("Validation incomplete, still open: "
                    + ", ".join(sorted(map(_name, outstanding))))
        return None
