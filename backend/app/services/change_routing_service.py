"""Change assessment routing: resolve the standard RASIC matrix, snapshot it per
change, generate staged assessments, advance stages, govern deviations, promote on
release. Standard is read from the flow designer (WfTemplate); falls back to the
legacy TYPE_DISCIPLINES dict when no ChangeRoutingStandard mapping exists.
"""
from __future__ import annotations
import copy
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.models.change import (
    ChangeRequest, ChangeAssessment, ChangeMeeting, ChangeRouting, ChangeRoutingStandard,
    ASSESSMENT_LETTERS, BLOCKING_LETTERS, TASK_LETTERS,
)
from app.models.workflow import (
    Department, WfTemplate, WfStage, WfStep, WfStepRasic, WfTemplateHistory,
    WfInstance, WfInstanceTask,
)
from app.services.notification_service import NotificationService
from app.services.workflow_service import DEFAULT_TASK_DUE_DAYS, WorkflowService


async def _match_step_id(session: AsyncSession, template_id: Optional[int],
                         stage_order: int, department_id: int,
                         rasic_letter: str) -> Optional[int]:
    """Resolve the step a deviation task should hang off inside ``template_id``'s
    stage ``stage_order``: prefer the step carrying a WfStepRasic for
    (department_id, rasic_letter), else the stage's first step, else ``None`` when
    the stage has no steps (tasks tolerate a null step_id since Task 1)."""
    if template_id is None:
        return None
    stage = (await session.execute(
        select(WfStage)
        .where(WfStage.template_id == template_id,
               WfStage.stage_order == stage_order)
        .options(selectinload(WfStage.steps).selectinload(WfStep.rasic_assignments))
    )).scalar_one_or_none()
    if stage is None or not stage.steps:
        return None
    steps = sorted(stage.steps, key=lambda s: s.position_in_stage)
    for step in steps:
        for r in step.rasic_assignments:
            if r.department_id == department_id and r.rasic_letter == rasic_letter:
                return step.id
    return steps[0].id


async def _template_stage_departments(session: AsyncSession,
                                      template_id: Optional[int],
                                      stage_order: int) -> list[dict]:
    """The (department, letter) entries the template gives one stage."""
    if template_id is None:
        return []
    stage = (await session.execute(
        select(WfStage)
        .where(WfStage.template_id == template_id,
               WfStage.stage_order == stage_order)
        .options(selectinload(WfStage.steps).selectinload(WfStep.rasic_assignments))
    )).scalar_one_or_none()
    if stage is None:
        return []
    return [{"department_id": r.department_id, "rasic_letter": r.rasic_letter}
            for step in sorted(stage.steps, key=lambda s: s.position_in_stage)
            for r in step.rasic_assignments]


async def _standard_pairs(session: AsyncSession, routing: Optional[ChangeRouting],
                          template_id: Optional[int], stage_order: int) -> set:
    """The (department_id, letter) pairs the change's standard gives a stage,
    by the engine's own rule (WorkflowService._create_stage_tasks): the
    routing snapshot's stage when it carries one, else the template's. A
    row outside this set is a deviation add: its task carries no step. An
    approved deviation add sits on the snapshot (added_by_deviation) so a
    later rejection keeps it, but it is still a deviation add here."""
    snap_stage = None
    if routing is not None:
        snap_stage = next(
            (st for st in (routing.standard_snapshot or {}).get("stages", [])
             if st["stage_order"] == stage_order), None)
    if snap_stage is not None:
        return {(d["department_id"], d["rasic_letter"])
                for d in snap_stage["departments"]
                if not d.get("pending_deviation") and not d.get("added_by_deviation")}
    return {(d["department_id"], d["rasic_letter"])
            for d in await _template_stage_departments(session, template_id, stage_order)}


async def _snapshot_stage(session: AsyncSession, routing: ChangeRouting, snap: dict,
                          stage_order: int) -> dict:
    """The snapshot's entry for a stage, created when missing. A missing
    stage is seeded from the template first: the engine filters a stage's
    template tasks by the snapshot stage once one exists, so a stage created
    with only the deviation's department would drop every other department
    the template gives it."""
    st = next((x for x in snap.setdefault("stages", [])
               if x["stage_order"] == stage_order), None)
    if st is None:
        st = {"stage_order": stage_order,
              "departments": await _template_stage_departments(
                  session, routing.template_id, stage_order)}
        snap["stages"].append(st)
        snap["stages"].sort(key=lambda x: x["stage_order"])
    return st


def _retarget_task(task: WfInstanceTask, rasic_letter: str,
                   stage_order: Optional[int] = None) -> None:
    """Apply a re-letter (and optional re-stage) to a linked engine task so it
    stays consistent with its assessment row. Blocking (R/A) => an active,
    actionable task with a default due date; non-blocking (S/C) => a noted,
    non-actionable task with no due date. Shared by the approved reletter and
    the rejected-deviation restore so both mutate the task identically."""
    is_blocking = rasic_letter in BLOCKING_LETTERS
    task.rasic_letter = rasic_letter
    task.is_actionable = is_blocking
    if stage_order is not None:
        task.stage_order = stage_order
    if is_blocking:
        # non-blocking -> blocking: (re)open with a default due date.
        task.status = "active"
        task.due_date = datetime.utcnow() + timedelta(days=DEFAULT_TASK_DUE_DAYS)
    else:
        # blocking -> non-blocking: drop to a noted task, no due date.
        task.status = "noted"
        task.due_date = None


class ChangeRoutingService:

    @staticmethod
    async def resolve_standard(session: AsyncSession, change_type: str):
        """Return (template_id|None, template_version|None, stages).

        stages = [{"stage_order": int, "departments": [{"department_id", "rasic_letter"}]}]
        """
        std = (await session.execute(
            select(ChangeRoutingStandard).where(ChangeRoutingStandard.change_type == change_type)
        )).scalar_one_or_none()

        if std is not None:
            template = (await session.execute(
                select(WfTemplate)
                .where(WfTemplate.id == std.template_id)
                .options(
                    selectinload(WfTemplate.stages)
                    .selectinload(WfStage.steps)
                    .selectinload(WfStep.rasic_assignments)
                )
            )).scalar_one_or_none()
            if template is not None and template.stages:
                stages = []
                for stage in sorted(template.stages, key=lambda s: s.stage_order):
                    deps = []
                    for step in sorted(stage.steps, key=lambda s: s.position_in_stage):
                        for r in step.rasic_assignments:
                            deps.append({"department_id": r.department_id, "rasic_letter": r.rasic_letter})
                    stages.append({"stage_order": stage.stage_order, "departments": deps})
                return template.id, template.version, stages

        # Fallback: single implicit stage, all blocking R, from discipline names.
        from app.services.change_service import TYPE_DISCIPLINES  # local import avoids circular-import at module load
        names = TYPE_DISCIPLINES.get(change_type, [])
        rows = (await session.execute(
            select(Department).where(Department.name.in_(names))
        )).scalars().all() if names else []
        deps = [{"department_id": d.id, "rasic_letter": "R"} for d in rows]
        return None, None, [{"stage_order": 1, "departments": deps}]

    @staticmethod
    async def build_routing(session: AsyncSession, change: ChangeRequest, user_id: int) -> ChangeRouting:
        """Idempotent: if routing already exists, do nothing. Otherwise snapshot the
        standard, create assessment rows (pending), broadcast start, activate stage 1.

        ``user_id`` is the actor initiating routing; reserved for future audit-log
        attribution and intentionally unused here.
        """
        existing = (await session.execute(
            select(ChangeRouting).where(ChangeRouting.change_id == change.id)
        )).scalar_one_or_none()
        if existing is not None:
            return existing

        template_id, template_version, stages = await ChangeRoutingService.resolve_standard(
            session, change.change_type)

        # Scoped fan-out: the latest 'proceed' scoping meeting restricts which
        # departments take part in stage 1 (the impact-assessment stage).
        # Later stages are process roles (summation, quote) and stay as the
        # template defines them.
        proceed = (await session.execute(
            select(ChangeMeeting)
            .where(ChangeMeeting.change_id == change.id,
                   ChangeMeeting.decision == "proceed")
            .order_by(ChangeMeeting.decided_at.desc(), ChangeMeeting.id.desc())
            .limit(1))).scalar_one_or_none()
        if proceed is not None and proceed.selected_department_ids:
            # The meeting's selection is AUTHORITATIVE for stage 1, not a filter
            # applied to the template's opinion. The template is the default the
            # meeting starts from; the people in the room decide who actually
            # assesses. So:
            #   in template, selected      -> kept, with its template letter
            #   in template, NOT selected  -> dropped, however standard it is
            #   selected, NOT in template  -> added as Responsible at stage 1
            # The last case is the one that used to be silently swallowed: a
            # department the room deliberately pulled in got no task at all.
            # Later stages are process roles (summation, quote) and stay as the
            # template defines them.
            # With letters on the meeting, the room's letter wins over the
            # template's for every stage-1 department; without them the
            # template letter stands and an extra department is Responsible.
            room = proceed.rasic_map
            allowed = set(proceed.selected_department_ids) | set(room)
            for stage in stages:
                if stage["stage_order"] == 1:
                    kept = [{**d, "rasic_letter": room.get(d["department_id"], d["rasic_letter"])}
                            for d in stage["departments"]
                            if d["department_id"] in allowed]
                    known = {d["department_id"] for d in stage["departments"]}
                    for dept_id in sorted(allowed - known):
                        kept.append({"department_id": dept_id,
                                     "rasic_letter": room.get(dept_id, "R")})
                    # An all-informational selection (only S/C/I letters) leaves
                    # stage 1 with no gate — the engine would stall forever. Require
                    # at least one responsible/accountable (R/A) department so the
                    # stage can actually complete and advance.
                    if not any(d["rasic_letter"] in BLOCKING_LETTERS for d in kept):
                        raise ValueError(
                            "Scoping selection contains no responsible/accountable "
                            "department in stage 1")
                    stage["departments"] = kept

        routing = ChangeRouting(
            change_id=change.id, template_id=template_id, template_version=template_version,
            standard_snapshot={"stages": stages},
        )
        session.add(routing)

        for stage in stages:
            for dep in stage["departments"]:
                if dep["rasic_letter"] not in ASSESSMENT_LETTERS:
                    continue  # I => notification only, no row
                # Every new row is created pending; execution state now lives on the
                # engine task (linked lazily by _create_stage_tasks), and
                # ``effective_status`` handles the read-through for display.
                session.add(ChangeAssessment(
                    change_id=change.id, department_id=dep["department_id"],
                    verdict="pending", stage_order=stage["stage_order"],
                    rasic_letter=dep["rasic_letter"], status="pending",
                ))
        await session.flush()

        # Spawn the change-scoped "ECM Assessment" instance. The engine creates
        # stage-1 tasks (and links stage-1 assessments) on start; later stages
        # link lazily as their tasks are created. Execution state lives entirely
        # on engine tasks now — assessment submission drives that engine.
        if routing.template_id is not None:
            await WorkflowService.start_change_workflow(
                session, change.id, routing.template_id, user_id)
        else:
            # Legacy TYPE_DISCIPLINES fallback carries no template — resolve the
            # seeded default by name.
            tmpl_id = (await session.execute(
                select(WfTemplate.id).where(WfTemplate.name == "ECM Assessment")
            )).scalar_one_or_none()
            if tmpl_id is not None:
                await WorkflowService.start_change_workflow(
                    session, change.id, tmpl_id, user_id)
        # Broadcast "started" to everyone involved (incl. I), once: a
        # department Informed in stage 1 already got its FYI from the engine
        # starting that stage, so it is not told a second time here.
        started = (await session.execute(
            select(WfInstance.id).where(
                WfInstance.change_id == change.id,
                WfInstance.status == "active"))).scalar_one_or_none()
        fyi_told: set[int] = set()
        if started is not None and stages:
            first = min(stages, key=lambda st: st["stage_order"])
            letters: dict[int, set] = {}
            for d in first["departments"]:
                letters.setdefault(d["department_id"], set()).add(d["rasic_letter"])
            fyi_told = {dep for dep, ls in letters.items() if ls == {"I"}}
        involved = [d for d in ChangeRoutingService._involved_department_ids(stages)
                    if d not in fyi_told]
        if involved:
            await NotificationService.notify_team(
                session, change.project_id, involved,
                title=f"Change {change.change_number} entered assessment",
                body=f"'{change.title}' has started cross-functional assessment.",
                link=f"/changes/{change.id}",
            )
        # Belt and braces: any stage-1 row the engine did not give a task.
        await ChangeRoutingService.repair_stage_tasks(session, change, None)
        return routing

    @staticmethod
    async def lock_instance(session: AsyncSession,
                            change_id: int) -> Optional[WfInstance]:
        """Lock the change's active engine instance (SELECT ... FOR UPDATE on
        Postgres; a no-op on SQLite) and return it freshly read.

        Every write path that re-letters, adds or removes rows and then runs
        the repair takes this lock FIRST, before any row write, so all of
        them (and the engine advance behind them) lock in one order: the
        instance, then its tasks and rows. Re-entrant inside a transaction.
        populate_existing: the stage order read after the lock is the
        committed one, not a stale identity-map copy."""
        return (await session.execute(
            select(WfInstance).where(
                WfInstance.change_id == change_id,
                WfInstance.status == "active")
            .with_for_update()
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()

    @staticmethod
    async def lock_task_instance(session: AsyncSession,
                                 change_id: int) -> Optional[WfInstance]:
        """The instance a task for this change hangs off, locked: the active
        one (lock_instance), else the latest COMPLETED one. A department added
        after the instance finished (every stage passed, the change still
        live, e.g. in costing) still owes its answer; its task goes onto the
        completed instance, step-less, so every view recognises it."""
        inst = await ChangeRoutingService.lock_instance(session, change_id)
        if inst is not None:
            return inst
        return (await session.execute(
            select(WfInstance).where(
                WfInstance.change_id == change_id,
                WfInstance.status == "completed")
            .order_by(WfInstance.id.desc()).limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()

    @staticmethod
    def _instances_by_id(instances) -> dict:
        if instances is None:
            return {}
        if isinstance(instances, WfInstance):
            instances = [instances]
        return {i.id: i for i in instances if i is not None}

    @staticmethod
    def owed_stepless_rows(change: ChangeRequest, instances) -> list:
        """R/A rows owed outside the assessment phase: an active actionable
        task without a step (a deviation add outside the template and the
        snapshot, or a row added after its stage passed) on an ACTIVE or
        COMPLETED instance. The department answers them whatever the change
        status; costing -> quoting waits on them (blocking_complete)."""
        by_id = ChangeRoutingService._instances_by_id(instances)
        out = []
        for a in change.assessments:
            t = a.task
            if (a.rasic_letter not in BLOCKING_LETTERS or t is None
                    or not t.is_actionable or t.status != "active"
                    or t.step_id is not None):
                continue
            inst = by_id.get(t.instance_id)
            if inst is not None and inst.status in ("active", "completed"):
                out.append(a)
        return out

    @staticmethod
    def late_rows(change: ChangeRequest, instances) -> list:
        """R/A rows added to a stage after it had passed whose answer is
        still owed: judged on the row's task, not on the instance still
        being live. The task is active, step-less, and either behind its
        active instance's stage or on an instance that has completed (every
        stage passed). The lead is flagged about them (cockpit action,
        notification). ``instances``: the change's instances (one or many)."""
        by_id = ChangeRoutingService._instances_by_id(instances)
        out = []
        for a in ChangeRoutingService.owed_stepless_rows(change, instances):
            inst = by_id[a.task.instance_id]
            if inst.status == "completed" or a.task.stage_order < inst.current_stage_order:
                out.append(a)
        return out

    @staticmethod
    async def repair_stage_tasks(session: AsyncSession, change: ChangeRequest,
                                 user_id: Optional[int] = None,
                                 report: Optional[dict] = None) -> list[int]:
        """Give every assessment row of a started stage its engine task.

        Before the snapshot-driven task creation (final walk P1-1), a
        department the scoping room added to stage 1 (or re-lettered away
        from the template's letter) got an assessment row but no task: the
        UI showed "Later stage / nothing to submit" while the gate kept
        waiting on it. A deviation-added row of a later stage still starts
        without one (the engine creates tasks from the template and the
        snapshot only). This links or creates the missing task, idempotently.

        Run from the write paths that open the gap (meeting proceed /
        routing build, routing deviations, stage wake-up, assessment submit)
        and from the admin POST /routing/repair; never from a read. The
        change's instance row is locked (SELECT ... FOR UPDATE on Postgres)
        and the unlinked rows and existing tasks are read inside the lock, so
        two concurrent repairs cannot both insert a task for the same row.
        With no active instance the latest COMPLETED one is used: a row
        added after every stage passed still gets its task there.

        What the created task looks like:
          * an answered row: approved, mirroring the answer
          * a row in neither the snapshot nor the template (a deviation
            add): no step, so every view counts it as an assessment row
          * an unanswered R/A deviation add of a live change: active
            (department notified), also when its stage has already passed.
            A department added to a passed stage is never waived on its
            behalf: its task is flagged instead (no step, a note), counts as
            an assessment row still waited on, and the change lead is told
            and gets a cockpit action to chase it or take the department off
          * an unanswered R/A row the snapshot or template gave a stage that
            has passed (history: it never got its task): waived, noted. The
            standard routing moved on without it; nothing is owed any more
          * an S/C row: noted (nothing owed)
          * an unanswered R/A row of a finished change: waived; the change
            is dead, so nothing is owed any more
        The stage advance is re-checked afterwards (an approved or waived
        task can complete it). ``user_id`` None logs a system action.
        ``report``, when given, is filled with the ids of the rows flagged
        late ("late") and waived for a passed stage ("waived_passed").
        Returns the repaired assessment ids."""
        inst = await ChangeRoutingService.lock_task_instance(session, change.id)
        if inst is None:
            return []
        completed = inst.status == "completed"
        q = (select(ChangeAssessment).where(
                ChangeAssessment.change_id == change.id,
                ChangeAssessment.wf_instance_task_id.is_(None),
                ChangeAssessment.rasic_letter.in_(ASSESSMENT_LETTERS))
             .order_by(ChangeAssessment.id)
             .execution_options(populate_existing=True))
        if not completed:
            q = q.where(ChangeAssessment.stage_order <= inst.current_stage_order)
        rows = (await session.execute(q)).scalars().all()
        if not rows:
            return []
        linked = set((await session.execute(
            select(ChangeAssessment.wf_instance_task_id).where(
                ChangeAssessment.change_id == change.id,
                ChangeAssessment.wf_instance_task_id.isnot(None))
        )).scalars().all())
        tasks = (await session.execute(
            select(WfInstanceTask).where(WfInstanceTask.instance_id == inst.id)
        )).scalars().all()
        routing = (await session.execute(
            select(ChangeRouting).where(ChangeRouting.change_id == change.id)
        )).scalar_one_or_none()
        standard: dict[int, set] = {}
        finished = change.status in ("released", "closed", "rejected", "cancelled")
        repaired: list[int] = []
        late: list[ChangeAssessment] = []
        waived_passed: list[ChangeAssessment] = []
        created_any = False
        notify_depts: set[int] = set()
        for a in rows:
            # Idempotent: an unlinked task of this instance for the same
            # stage + department + letter is this row's task; link it.
            task = next((t for t in tasks
                         if t.id not in linked and t.stage_order == a.stage_order
                         and t.department_id == a.department_id
                         and t.rasic_letter == a.rasic_letter), None)
            if task is None:
                if a.stage_order not in standard:
                    standard[a.stage_order] = await _standard_pairs(
                        session, routing, inst.template_id, a.stage_order)
                in_standard = (a.department_id, a.rasic_letter) in standard[a.stage_order]
                is_blocking = a.rasic_letter in BLOCKING_LETTERS
                passed = completed or a.stage_order < inst.current_stage_order
                answered = a.submitted_at is not None
                owed = is_blocking and not answered and not finished
                # A standard row of a passed stage that never got its task:
                # the routing ran that stage without it; nothing owed now.
                lapsed = owed and passed and in_standard
                is_late = owed and passed and not in_standard
                live = owed and not lapsed
                task = WfInstanceTask(
                    instance_id=inst.id, stage_order=a.stage_order,
                    # A row outside the snapshot and the template is a
                    # deviation add: no step, the mark the assessment views
                    # (is_assessment_row, blocking_complete, My Tasks, the
                    # cockpit) recognise and keep waiting on.
                    step_id=await _match_step_id(
                        session, inst.template_id, a.stage_order,
                        a.department_id, a.rasic_letter) if in_standard else None,
                    department_id=a.department_id, rasic_letter=a.rasic_letter,
                    status="active" if live else "noted",
                    is_actionable=is_blocking,
                    due_date=(a.due_date or datetime.utcnow()
                              + timedelta(days=DEFAULT_TASK_DUE_DAYS))
                    if live else None,
                )
                if is_blocking and answered:
                    task.status = "approved"
                    task.decision = "approved"
                    task.completed_by = a.submitted_by
                    task.completed_at = a.submitted_at
                    task.owner_id = a.owner_id or a.submitted_by
                    task.accepted_at = a.accepted_at or a.submitted_at
                elif is_blocking and not live:
                    task.status = "waived"
                    task.notes = (
                        f"Created by the routing repair after the change was "
                        f"{change.status}; nothing owed" if finished else
                        f"Created by the routing repair after stage "
                        f"{a.stage_order} had passed; nothing owed")
                    if lapsed:
                        waived_passed.append(a)
                elif is_late:
                    task.notes = (
                        f"Added to stage {a.stage_order} after it had passed: "
                        "the answer is still owed (flagged for the change lead)")
                    notify_depts.add(a.department_id)
                    late.append(a)
                elif live:
                    notify_depts.add(a.department_id)
                session.add(task)
                await session.flush()
                tasks = list(tasks) + [task]
                created_any = True
            a.wf_instance_task_id = task.id
            linked.add(task.id)
            repaired.append(a.id)
        await session.flush()
        if report is not None:
            report["late"] = [a.id for a in late]
            report["waived_passed"] = [a.id for a in waived_passed]
        if notify_depts:
            await NotificationService.notify_team(
                session, change.project_id, sorted(notify_depts),
                title=f"Assessment task: {change.change_number}",
                body=f"Your department has an assessment to give on '{change.title}'.",
                link=f"/changes/{change.id}?tab=assessments",
            )
        if late and change.lead_id is not None:
            names = await ChangeRoutingService._department_names(
                session, [a.department_id for a in late])
            await NotificationService.notify_once(
                session, [change.lead_id], kind="routing_late_assessment",
                subject_key=(f"routing-late:{change.id}:"
                             + ",".join(str(a.id) for a in late)),
                title=f"Assessment owed after its stage passed: {change.change_number}",
                body=(f"{', '.join(names)}: added to a routing stage that had "
                      "already passed and still owe their answer. Chase them, "
                      "or take them off the routing."),
                link=f"/changes/{change.id}?tab=assessments",
            )
        if created_any:
            await WorkflowService._maybe_advance_stage(session, inst)
        from app.services.change_service import ChangeService
        actor = user_id or change.lead_id or change.raised_by
        text = (f"Routing repair: {len(repaired)} assessment row(s) got their "
                "missing workflow task")
        extra: dict = {"assessment_ids": repaired}
        if late:
            extra["late_assessment_ids"] = [a.id for a in late]
            text += (f"; {len(late)} added after their stage had passed, "
                     "flagged for the lead")
        if waived_passed:
            extra["waived_passed_assessment_ids"] = [a.id for a in waived_passed]
            text += (f"; {len(waived_passed)} of a passed stage waived "
                     "(the standard routing ran it without them)")
        if user_id is None:
            text += " (automatic)"
            extra["system"] = True
        await ChangeService.append_changelog(
            session, change, "routing_repaired", text, actor, new_value=extra)
        return repaired

    @staticmethod
    async def _department_names(session: AsyncSession, ids) -> list[str]:
        ids = list(dict.fromkeys(i for i in ids if i is not None))
        if not ids:
            return []
        names = dict((await session.execute(
            select(Department.id, Department.name).where(Department.id.in_(ids)))).all())
        return [names.get(i, f"department {i}") for i in ids]

    @staticmethod
    async def teardown_routing(session: AsyncSession, change: ChangeRequest,
                               user_id: int) -> None:
        """Remove all assessment scaffolding built on entry to assessment, so a
        corrected impacted set rebuilds cleanly on re-submit. Caller must ensure
        no assessment work has started.

        ``user_id`` is the actor initiating the recall; reserved for future audit-log
        attribution and intentionally unused here.
        """
        assessments = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
        )).scalars().all()
        for a in assessments:
            a.wf_instance_task_id = None      # break FK before task rows go
        await session.flush()
        for a in assessments:
            await session.delete(a)
        instances = (await session.execute(
            select(WfInstance).where(WfInstance.change_id == change.id)
        )).scalars().all()
        for inst in instances:
            await session.delete(inst)        # cascade deletes its WfInstanceTasks
        routing = (await session.execute(
            select(ChangeRouting).where(ChangeRouting.change_id == change.id)
        )).scalar_one_or_none()
        if routing is not None:
            await session.delete(routing)
        await session.flush()

    @staticmethod
    def _involved_department_ids(stages) -> list[int]:
        ids = []
        for stage in stages:
            for dep in stage["departments"]:
                ids.append(dep["department_id"])
        return list(dict.fromkeys(ids))

    @staticmethod
    async def blocking_rows(session: AsyncSession,
                            change: ChangeRequest) -> list[ChangeAssessment]:
        """The R/A rows the costing hops wait on.

        ONLY assessment work gates this transition (rule book: Sales is
        exempt and relies on the departments; PM's summation happens in the
        costing/quoting phases of the change, not as an assessment row).
        That is: the FIRST stage — the engine advances its instance to
        stage 2 once stage 1 completes and activates those phase tasks, and
        precisely then they must not re-block the hop the completion just
        earned — PLUS any deviation-added row outside the template (its
        task carries step_id None): someone deliberately added that
        department to the assessment, whatever stage number it landed on."""
        rows = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
        )).scalars().all()
        first = min((a.stage_order for a in rows), default=None)
        return [a for a in rows
                if a.rasic_letter in BLOCKING_LETTERS
                and (a.stage_order == first
                     # linked deviation row outside the template
                     or (a.task is not None and a.task.step_id is None)
                     # the same row before the repair links its task: an
                     # unlinked later-stage row carrying its own "active"
                     # (template phase rows sit unlinked as "pending")
                     or (a.task is None and a.status == "active"))]

    @staticmethod
    async def blocking_waiting(session: AsyncSession,
                               change: ChangeRequest) -> Optional[list[str]]:
        """Names of the departments the costing hops still wait on; None
        when there is no blocking row at all (nothing was ever asked)."""
        blocking = await ChangeRoutingService.blocking_rows(session, change)
        if not blocking:
            return None
        waiting = [a for a in blocking
                   if a.effective_status not in ("submitted", "waived")]
        return await ChangeRoutingService._department_names(
            session, [a.department_id for a in waiting])

    @staticmethod
    async def blocking_complete(session: AsyncSession, change: ChangeRequest) -> bool:
        waiting = await ChangeRoutingService.blocking_waiting(session, change)
        return waiting is not None and not waiting

    @staticmethod
    async def _routing(session: AsyncSession, change: ChangeRequest) -> ChangeRouting:
        r = (await session.execute(
            select(ChangeRouting).where(ChangeRouting.change_id == change.id)
        )).scalar_one_or_none()
        if r is None:
            raise ValueError("Change has no routing yet")
        return r

    @staticmethod
    async def apply_deviation(session: AsyncSession, change: ChangeRequest, user_id: int, *,
                              op: str, department_id: int, rasic_letter: Optional[str] = None,
                              stage_order: Optional[int] = None,
                              reason: Optional[str] = None) -> ChangeRouting:
        from app.services.change_service import ChangeService  # local import avoids cycle
        # One lock order with the engine: the instance first, then rows.
        inst = await ChangeRoutingService.lock_instance(session, change.id)
        # No active instance: the completed one (every stage passed) still
        # takes the task of a department added now.
        task_inst = inst or await ChangeRoutingService.lock_task_instance(
            session, change.id)
        routing = await ChangeRoutingService._routing(session, change)
        # Adding a department mid-assessment is an audit event: somebody was
        # forgotten, or something turned out to be impacted after all. The
        # reason is the record of which, and the lead reads it to decide.
        if not (reason and reason.strip()):
            raise ValueError("A reason is required to change the routing")
        # A department can hold rows in several routing stages (R at stage 1,
        # C at the summation stage...). The deviation acts on the row of the
        # stage it targets: the given stage, else the assessment stage (the
        # change's first); remove/reletter fall back to the lowest row.
        dept_rows = (await session.execute(
            select(ChangeAssessment).where(
                (ChangeAssessment.change_id == change.id)
                & (ChangeAssessment.department_id == department_id))
            .order_by(ChangeAssessment.stage_order, ChangeAssessment.id)
        )).scalars().all()
        target_stage = stage_order
        if target_stage is None:
            target_stage = (await session.execute(
                select(func.min(ChangeAssessment.stage_order)).where(
                    ChangeAssessment.change_id == change.id))).scalar() or 1
        existing = next((r for r in dept_rows if r.stage_order == target_stage), None)
        if existing is None and op != "add" and dept_rows:
            existing = dept_rows[0]
        # Change-scoped engine instance (Task 3, locked above). When present,
        # deviation ops must mutate its tasks alongside the assessment rows so
        # engine state stays consistent. Legacy pre-migration changes have
        # none -> assessment-only.

        if op == "add":
            if rasic_letter not in TASK_LETTERS:
                raise ValueError("add requires a RASIC letter (R/A/S/C/I)")
            order = stage_order or target_stage
            if existing is not None:
                # An add never re-letters: that would change a department's
                # role (R -> I drops its duty) before anybody decided it.
                # A different letter is a reletter request, which waits for
                # the lead (pending_rasic_letter).
                raise ValueError(
                    f"The department is already {existing.rasic_letter} in "
                    f"stage {existing.stage_order}: request a different "
                    "letter with a reletter instead")
            if rasic_letter == "I":
                # Informed: told, nothing owed. No assessment row and no task
                # (nothing for a gate to wait on); the department sits on the
                # routing snapshot, flagged until the lead decides, so a
                # rejection can take it off again.
                snap = copy.deepcopy(routing.standard_snapshot or {"stages": []})
                st = await _snapshot_stage(session, routing, snap, order)
                if any(d["department_id"] == department_id and d["rasic_letter"] == "I"
                       for d in st["departments"]):
                    raise ValueError("The department is already I")
                st["departments"].append({"department_id": department_id,
                                          "rasic_letter": "I",
                                          "pending_deviation": True})
                routing.standard_snapshot = snap
                flag_modified(routing, "standard_snapshot")
                await session.flush()
                await NotificationService.notify_team(
                    session, change.project_id, [department_id],
                    title=f"For your information: {change.change_number}",
                    body=(f"Your department is informed about '{change.title}'. "
                          "Nothing to answer."),
                    link=f"/changes/{change.id}",
                )
            else:
                new_status = "active" if order <= await ChangeRoutingService._max_active_order(session, change) else "pending"
                new_row = ChangeAssessment(
                    change_id=change.id, department_id=department_id, verdict="pending",
                    stage_order=order, rasic_letter=rasic_letter,
                    status=new_status,
                    due_date=(datetime.utcnow() + timedelta(days=DEFAULT_TASK_DUE_DAYS)
                              if new_status == "active" else None),
                )
                session.add(new_row)
                await session.flush()
                # Engine: if the change has an instance and the target stage
                # has already started (current or passed, or the instance has
                # completed), create + link the task so the assignment gets an
                # actionable surface. A future stage is left unlinked — lazy
                # linking (Task 3) picks it up when the stage starts.
                if task_inst is not None and (
                        task_inst.status == "completed"
                        or order <= task_inst.current_stage_order):
                    is_blocking = rasic_letter in BLOCKING_LETTERS
                    # Added to a stage that already passed: owed all the same,
                    # flagged like the repair flags it (no step, a note).
                    passed = (task_inst.status == "completed"
                              or order < task_inst.current_stage_order)
                    is_late = is_blocking and passed
                    in_standard = (department_id, rasic_letter) in await _standard_pairs(
                        session, routing, task_inst.template_id, order)
                    task = WfInstanceTask(
                        instance_id=task_inst.id, stage_order=order,
                        # Outside the snapshot and the template (a deviation
                        # add) or late: no step, the mark every assessment
                        # view recognises.
                        step_id=None if (is_late or not in_standard) else await _match_step_id(
                            session, task_inst.template_id, order, department_id,
                            rasic_letter),
                        department_id=department_id, rasic_letter=rasic_letter,
                        status="active" if is_blocking else "noted",
                        is_actionable=is_blocking,
                        due_date=(datetime.utcnow() + timedelta(days=DEFAULT_TASK_DUE_DAYS)
                                  if is_blocking else None),
                        notes=(f"Added to stage {order} after it had passed: the "
                               "answer is still owed (flagged for the change lead)"
                               if is_late else None),
                    )
                    session.add(task)
                    await session.flush()
                    new_row.wf_instance_task_id = task.id
            desc = f"added dept {department_id} as {rasic_letter} in stage {order}"
            record = {"op": "add", "department_id": department_id,
                      "rasic_letter": rasic_letter, "stage_order": order}
        elif op == "remove":
            if existing is not None:
                # Drop the linked engine task first (null the FK so the row can be
                # deleted), then the assessment row itself.
                if existing.wf_instance_task_id is not None:
                    task = await session.get(WfInstanceTask, existing.wf_instance_task_id)
                    existing.wf_instance_task_id = None
                    await session.flush()
                    if task is not None:
                        await session.delete(task)
                await session.delete(existing)
                await session.flush()
                # Removing the last open blocking task can unblock the stage.
                if inst is not None:
                    await WorkflowService._maybe_advance_stage(session, inst)
            desc = f"removed dept {department_id}"
            record = {"op": "remove", "department_id": department_id,
                      "stage_order": existing.stage_order if existing else None}
        elif op == "reletter":
            if rasic_letter not in TASK_LETTERS:
                raise ValueError("reletter requires a RASIC letter (R/A/S/C/I)")
            if existing is None:
                raise ValueError("no assessment to reletter")
            # "Not our responsibility" (spec §16 P1-3): a department that has
            # answered cannot decline any more, and the decline is only a
            # request. The row keeps its letter (and owes its answer) until
            # the lead approves; the workflow does not move on it.
            if existing.submitted_at is not None or (
                    existing.verdict and existing.verdict != "pending"):
                raise ValueError(
                    "The department has already submitted its assessment; it "
                    "can no longer decline it")
            if existing.rasic_letter == rasic_letter:
                raise ValueError(f"The department is already {rasic_letter}")
            existing.pending_rasic_letter = rasic_letter
            await session.flush()
            desc = (f"dept {department_id} declined: {existing.rasic_letter} to "
                    f"{rasic_letter}, awaiting decision")
            record = {"op": "reletter", "department_id": department_id,
                      "rasic_letter": rasic_letter, "stage_order": existing.stage_order}
        else:
            raise ValueError(f"unknown op '{op}'")

        routing.has_deviation = True
        routing.deviation_status = "pending_approval"
        routing.deviation_proposed_by = user_id
        if reason and reason.strip():
            routing.deviation_note = reason.strip()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "routing_deviation", f"Routing deviation: {desc}", user_id,
            notes=(reason.strip() if reason else None), new_value=record)
        # The decision sits with the lead (4-eyes: the proposer cannot take
        # it). Tell them, once per pending deviation.
        if change.lead_id is not None and change.lead_id != user_id:
            await NotificationService.notify_once(
                session, [change.lead_id], kind="routing_deviation_pending",
                subject_key=f"routing-dev:{change.id}:{routing.deviation_proposed_by}:{desc}",
                title=f"Routing change pending: {change.change_number}",
                body=f"{desc.capitalize()}: needs your approval.",
                link=f"/changes/{change.id}?tab=assessments",
            )
        # A row the op added to a started stage without a task gets one now.
        await ChangeRoutingService.repair_stage_tasks(session, change, None)
        return routing

    @staticmethod
    async def _max_active_order(session: AsyncSession, change: ChangeRequest) -> int:
        rows = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
        )).scalars().all()
        active = [a.stage_order for a in rows if a.status == "active"]
        return max(active) if active else 1

    @staticmethod
    def user_can_decide_deviation(change: ChangeRequest, routing: ChangeRouting,
                                  user_id: int, *, acting: bool = False) -> bool:
        """Who may approve or reject a pending routing deviation. No
        self-decision. If a non-lead proposed it, only the lead decides. If the
        lead proposed it, anyone-but-the-proposer (i.e. the PM) decides. Shared
        by the endpoints and my_actions so the plate and the gate agree.
        acting: the caller acts as a department, which drops the personal
        lead privilege (change_people.holds_lead)."""
        if routing.deviation_status != "pending_approval":
            return False
        if routing.deviation_proposed_by == user_id:
            return False
        if (change.lead_id is not None
                and routing.deviation_proposed_by != change.lead_id
                and (acting or user_id != change.lead_id)):
            return False
        return True

    @staticmethod
    def _check_decide(change: ChangeRequest, routing: ChangeRouting, user_id: int,
                      verb: str, acting: bool = False) -> None:
        if routing.deviation_status != "pending_approval":
            raise ValueError("No deviation pending approval")
        if routing.deviation_proposed_by == user_id:
            raise ValueError(f"Cannot {verb} your own routing deviation")
        if not ChangeRoutingService.user_can_decide_deviation(
                change, routing, user_id, acting=acting):
            raise ValueError(f"Only the change lead may {verb} this deviation")

    @staticmethod
    def _settle_pending_informed(routing: ChangeRouting, *, keep: bool) -> list[int]:
        """Decide the Informed departments a pending deviation put on the
        snapshot: approved (keep) drops the pending flag, rejected removes the
        entries. Returns the department ids touched."""
        snap = copy.deepcopy(routing.standard_snapshot or {"stages": []})
        touched: list[int] = []
        for st in snap.get("stages", []):
            deps = []
            for d in st["departments"]:
                if d.get("pending_deviation"):
                    touched.append(d["department_id"])
                    if not keep:
                        continue
                    d = {k: v for k, v in d.items() if k != "pending_deviation"}
                deps.append(d)
            st["departments"] = deps
        if touched:
            routing.standard_snapshot = snap
            flag_modified(routing, "standard_snapshot")
        return touched

    @staticmethod
    async def reject_deviation(session: AsyncSession, change: ChangeRequest, user_id: int,
                               reason: str, *, acting: bool = False) -> ChangeRouting:
        """Reject the pending deviation and undo what it added.

        Undo covers the 'add' op, the only one the UI offers: every assessment
        row outside the routing snapshot that has not been answered is dropped
        together with its engine task, so the department is off the hook again.
        Adds of earlier, APPROVED deviations are on the snapshot
        (added_by_deviation, written by approve_deviation) and stay: a
        rejection undoes only what is still pending.
        A row that was already answered is NOT erased — the rejection is refused
        instead; by then the department's work is a fact of the record."""
        from app.services.change_service import ChangeService
        inst = await ChangeRoutingService.lock_instance(session, change.id)
        routing = await ChangeRoutingService._routing(session, change)
        ChangeRoutingService._check_decide(change, routing, user_id, "reject", acting)
        if not (reason and reason.strip()):
            raise ValueError("A reason is required to reject a routing deviation")
        # What the routing stands at: the snapshot, with the adds and
        # re-letters approved so far. One letter per department and stage;
        # an assessment letter wins over an Informed entry of the same
        # department (a row is never "re-lettered back" to I).
        standard: dict[tuple[int, int], str] = {}
        for st in routing.standard_snapshot.get("stages", []):
            for d in st["departments"]:
                if d.get("pending_deviation"):
                    continue
                key = (d["department_id"], st["stage_order"])
                if key in standard and d["rasic_letter"] not in ASSESSMENT_LETTERS:
                    continue
                standard[key] = d["rasic_letter"]
        # An Informed department the deviation put on the routing comes off
        # again (it never had a row or a task).
        uninformed = ChangeRoutingService._settle_pending_informed(routing, keep=False)
        rows = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
        )).scalars().all()
        # A pending decline simply lapses: the row never changed its letter.
        declined = [a for a in rows if a.pending_rasic_letter]
        for a in declined:
            a.pending_rasic_letter = None
        added = [a for a in rows if (a.department_id, a.stage_order) not in standard]
        # A re-lettered standard row ("not our responsibility" -> C) goes back
        # to the letter the routing gave it.
        relettered = [a for a in rows
                      if (a.department_id, a.stage_order) in standard
                      and a.rasic_letter != standard[(a.department_id, a.stage_order)]]
        answered = [a for a in added + relettered
                    if a.submitted_at is not None or (a.verdict and a.verdict != "pending")]
        if answered:
            raise ValueError(
                "The department has already submitted its assessment; "
                "its answer stays on the record and cannot be rejected away")
        for a in relettered:
            a.rasic_letter = standard[(a.department_id, a.stage_order)]
            if a.wf_instance_task_id is not None:
                task = await session.get(WfInstanceTask, a.wf_instance_task_id)
                if task is not None:
                    _retarget_task(task, a.rasic_letter)
        removed = []
        for a in added:
            if a.wf_instance_task_id is not None:
                task = await session.get(WfInstanceTask, a.wf_instance_task_id)
                a.wf_instance_task_id = None
                await session.flush()
                if task is not None:
                    await session.delete(task)
            removed.append(a.department_id)
            await session.delete(a)
        await session.flush()
        if inst is not None and (removed or relettered):
            await WorkflowService._maybe_advance_stage(session, inst)
        routing.deviation_status = "rejected"
        routing.has_deviation = False
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "routing_deviation_rejected",
            f"Routing deviation rejected: {reason.strip()}", user_id,
            notes=reason.strip(),
            new_value={"removed_department_ids": removed + uninformed,
                       "restored_department_ids": [a.department_id for a in relettered],
                       "declines_refused_department_ids": [a.department_id for a in declined]})
        if routing.deviation_proposed_by is not None and routing.deviation_proposed_by != user_id:
            await NotificationService.notify_once(
                session, [routing.deviation_proposed_by], kind="routing_deviation_rejected",
                subject_key=f"routing-dev-rejected:{change.id}:{datetime.utcnow().isoformat()}",
                title=f"Routing change rejected: {change.change_number}",
                body=reason.strip(),
                link=f"/changes/{change.id}?tab=assessments",
            )
        # A restored letter or a removed row can start the next stage: its
        # rows get their tasks now.
        await ChangeRoutingService.repair_stage_tasks(session, change, None)
        return routing

    @staticmethod
    async def approve_deviation(session: AsyncSession, change: ChangeRequest, user_id: int,
                                *, acting: bool = False) -> ChangeRouting:
        from app.services.change_service import ChangeService
        inst = await ChangeRoutingService.lock_instance(session, change.id)
        routing = await ChangeRoutingService._routing(session, change)
        ChangeRoutingService._check_decide(change, routing, user_id, "approve", acting)
        # A pending "not our responsibility" re-letters only now (§16 P1-3),
        # and only if the department has not answered in the meantime (then
        # its answer stands and the decline is moot).
        rows = (await session.execute(
            select(ChangeAssessment).where(
                ChangeAssessment.change_id == change.id,
                ChangeAssessment.pending_rasic_letter.isnot(None))
        )).scalars().all()
        relettered = []
        informed: list[tuple[int, int]] = []
        # (department, stage, old letter, new letter): the snapshot follows
        # every approved re-letter, so a later stage start creates the task
        # for the row's letter and not an orphan one for the template's.
        moved: list[tuple[int, int, str, str]] = []
        for a in rows:
            letter = a.pending_rasic_letter
            a.pending_rasic_letter = None
            if a.submitted_at is not None or (a.verdict and a.verdict != "pending"):
                continue
            relettered.append(a.department_id)
            if letter == "I":
                # Informed has no row and no task (nothing is owed): the row
                # and its task go, the department stays on the routing as I.
                # Documents filed with the row stay on the change (as the
                # supersede does): the link to the row is cut first.
                from app.models.change import ChangeAttachment
                for att in (await session.execute(
                        select(ChangeAttachment).where(
                            ChangeAttachment.assessment_id == a.id))).scalars().all():
                    att.assessment_id = None
                if a.wf_instance_task_id is not None:
                    task = await session.get(WfInstanceTask, a.wf_instance_task_id)
                    a.wf_instance_task_id = None
                    await session.flush()
                    if task is not None:
                        await session.delete(task)
                informed.append((a.department_id, a.stage_order))
                await session.flush()
                await session.delete(a)
                continue
            moved.append((a.department_id, a.stage_order, a.rasic_letter, letter))
            a.rasic_letter = letter
            if a.wf_instance_task_id is not None:
                task = await session.get(WfInstanceTask, a.wf_instance_task_id)
                if task is not None:
                    _retarget_task(task, letter)
        await session.flush()
        # The routing rows as they stand after the re-letters: the approved
        # adds and removes are written into the snapshot below.
        current = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
            .order_by(ChangeAssessment.stage_order, ChangeAssessment.id)
        )).scalars().all()
        row_keys = {(a.department_id, a.stage_order) for a in current}
        on_snap = {(d["department_id"], st["stage_order"])
                   for st in (routing.standard_snapshot or {}).get("stages", [])
                   for d in st["departments"]
                   if not d.get("pending_deviation")
                   and d["rasic_letter"] in ASSESSMENT_LETTERS}
        # An R/A/S/C row outside the snapshot is an add of this deviation.
        added = [a for a in current
                 if a.rasic_letter in ASSESSMENT_LETTERS
                 and (a.department_id, a.stage_order) not in on_snap]
        # An R/A/S/C snapshot entry without its row: the row was removed.
        removed_entries = bool(on_snap - row_keys)
        if informed or moved or added or removed_entries:
            snap = copy.deepcopy(routing.standard_snapshot or {"stages": []})
            # Approved adds join the snapshot, so a later rejection of
            # another deviation (which undoes every row outside the
            # snapshot) keeps them. Marked added_by_deviation: for the
            # engine and the repair they stay deviation adds (task without
            # a step, never waived as a standard row of a passed stage).
            for a in added:
                st = await _snapshot_stage(session, routing, snap, a.stage_order)
                st["departments"] = [
                    d for d in st["departments"]
                    if not (d["department_id"] == a.department_id
                            and d["rasic_letter"] in ASSESSMENT_LETTERS)]
                st["departments"].append({"department_id": a.department_id,
                                          "rasic_letter": a.rasic_letter,
                                          "added_by_deviation": True})
            # Approved removes leave the snapshot: a later stage start must
            # not create a task for a department taken off the routing.
            if removed_entries:
                for st in snap.get("stages", []):
                    st["departments"] = [
                        d for d in st["departments"]
                        if d.get("pending_deviation")
                        or d["rasic_letter"] not in ASSESSMENT_LETTERS
                        or (d["department_id"], st["stage_order"]) in row_keys]
            for dept_id, order in informed:
                st = await _snapshot_stage(session, routing, snap, order)
                st["departments"] = [d for d in st["departments"]
                                     if d["department_id"] != dept_id]
                st["departments"].append({"department_id": dept_id,
                                          "rasic_letter": "I"})
            for dept_id, order, old, new in moved:
                st = await _snapshot_stage(session, routing, snap, order)
                # The department's entry follows its row's letter (a
                # standard entry, or an add approved earlier).
                for d in st["departments"]:
                    if (d["department_id"] == dept_id and d["rasic_letter"] == old
                            and not d.get("pending_deviation")):
                        d["rasic_letter"] = new
            routing.standard_snapshot = snap
            flag_modified(routing, "standard_snapshot")
            await session.flush()
        if relettered and inst is not None:
            await WorkflowService._maybe_advance_stage(session, inst)
        ChangeRoutingService._settle_pending_informed(routing, keep=True)
        routing.deviation_status = "approved"
        routing.deviation_approved_by = user_id
        routing.deviation_approved_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "routing_deviation_approved", "Routing deviation approved", user_id,
            new_value={"relettered_department_ids": relettered} if relettered else None)
        await ChangeRoutingService.repair_stage_tasks(session, change, None)
        return routing

    @staticmethod
    async def promote_to_standard(session: AsyncSession, change: ChangeRequest, user_id: int) -> None:
        """If the change carries an approved deviation against a mapped template, bump
        that template to v+1 (one step per stage), snapshot history, repoint standard."""
        # Scoped changes must never promote: a meeting-scoped change carries only the
        # selected departments in its stage-1 assessment rows, so rebuilding the shared
        # standard from those rows would silently delete every unselected department
        # from the org-wide template. Promoting a genuinely scoped-down routing needs
        # dedicated semantics (merge into, not replace, the standard) — deferred. Skip
        # promotion entirely whenever any 'proceed' meeting restricted the fan-out.
        proceed_meetings = (await session.execute(
            select(ChangeMeeting).where(
                ChangeMeeting.change_id == change.id,
                ChangeMeeting.decision == "proceed")
        )).scalars().all()
        if any(m.selected_department_ids for m in proceed_meetings):
            return  # scoped-change promotion semantics deferred (see comment above)

        routing = (await session.execute(
            select(ChangeRouting).where(ChangeRouting.change_id == change.id)
        )).scalar_one_or_none()
        if routing is None or routing.deviation_status != "approved" or routing.template_id is None:
            return  # nothing to promote (no deviation, or fallback routing had no template)

        template = (await session.execute(
            select(WfTemplate)
            .where(WfTemplate.id == routing.template_id)
            .options(selectinload(WfTemplate.stages).selectinload(WfStage.steps))
        )).scalar_one_or_none()
        if template is None:
            return

        # Build the new structure from the change's final assessments grouped by stage.
        rows = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
        )).scalars().all()
        # carry over I departments from the snapshot
        snapshot_stages = {st["stage_order"]: st for st in routing.standard_snapshot.get("stages", [])}
        by_stage: dict[int, list[dict]] = {}
        for a in rows:
            by_stage.setdefault(a.stage_order, []).append(
                {"department_id": a.department_id, "rasic_letter": a.rasic_letter})
        # One role per department and stage: an Informed entry is carried
        # only where the department holds no assessment row in that stage (a
        # department re-lettered R -> I lost its row; one re-added as R keeps
        # its row and must not ALSO come back as I).
        for order, st in snapshot_stages.items():
            present = {d["department_id"] for d in by_stage.get(order, [])}
            for dep in st["departments"]:
                if (dep["rasic_letter"] == "I" and not dep.get("pending_deviation")
                        and dep["department_id"] not in present):
                    present.add(dep["department_id"])
                    by_stage.setdefault(order, []).append(
                        {"department_id": dep["department_id"], "rasic_letter": "I"})

        # Drop old stages (cascade removes steps + rasic), then recreate.
        for stage in list(template.stages):
            await session.delete(stage)
        await session.flush()

        for order in sorted(by_stage):
            stage = WfStage(template_id=template.id, stage_order=order, name=f"Stage {order}")
            session.add(stage); await session.flush()
            step = WfStep(stage_id=stage.id, step_name=f"Stage {order}", position_in_stage=1)
            session.add(step); await session.flush()
            seen = set()
            for dep in by_stage[order]:
                key = (dep["department_id"], dep["rasic_letter"])
                if key in seen:
                    continue
                seen.add(key)
                session.add(WfStepRasic(step_id=step.id, department_id=dep["department_id"],
                                        rasic_letter=dep["rasic_letter"]))

        template.version = (template.version or 1) + 1
        template.updated_by = user_id
        session.add(WfTemplateHistory(
            template_id=template.id, version=template.version,
            snapshot={"stages": [{"stage_order": o,
                                  "departments": by_stage[o]} for o in sorted(by_stage)]},
            changed_by=user_id,
            change_note=f"Promoted from change {change.change_number} deviation",
        ))
        std = (await session.execute(
            select(ChangeRoutingStandard).where(
                ChangeRoutingStandard.change_type == change.change_type)
        )).scalar_one_or_none()
        if std is not None:
            std.template_version = template.version
            std.updated_by = user_id
        await session.flush()
