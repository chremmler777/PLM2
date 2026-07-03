"""Change assessment routing: resolve the standard RASIC matrix, snapshot it per
change, generate staged assessments, advance stages, govern deviations, promote on
release. Standard is read from the flow designer (WfTemplate); falls back to the
legacy TYPE_DISCIPLINES dict when no ChangeRoutingStandard mapping exists.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.change import (
    ChangeRequest, ChangeAssessment, ChangeRouting, ChangeRoutingStandard,
    BLOCKING_LETTERS, TASK_LETTERS,
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


def _retarget_task(task: WfInstanceTask, rasic_letter: str,
                   stage_order: Optional[int] = None) -> None:
    """Apply a re-letter (and optional re-stage) to a linked engine task so it
    stays consistent with its assessment row. Blocking (R/A) => an active,
    actionable task with a default due date; non-blocking (S/C) => a noted,
    non-actionable task with no due date. Shared by the reletter op and the
    add-on-existing-row path so both mutate the task identically."""
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

        routing = ChangeRouting(
            change_id=change.id, template_id=template_id, template_version=template_version,
            standard_snapshot={"stages": stages},
        )
        session.add(routing)

        for stage in stages:
            for dep in stage["departments"]:
                if dep["rasic_letter"] not in TASK_LETTERS:
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

        # Broadcast "started" to everyone involved (incl. I).
        involved = ChangeRoutingService._involved_department_ids(stages)
        if involved:
            await NotificationService.notify_departments(
                session, involved,
                title=f"Change {change.change_number} entered assessment",
                body=f"'{change.title}' has started cross-functional assessment.",
                link=f"/changes/{change.id}",
            )
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
        return routing

    @staticmethod
    def _involved_department_ids(stages) -> list[int]:
        ids = []
        for stage in stages:
            for dep in stage["departments"]:
                ids.append(dep["department_id"])
        return list(dict.fromkeys(ids))

    @staticmethod
    async def blocking_complete(session: AsyncSession, change: ChangeRequest) -> bool:
        rows = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
        )).scalars().all()
        blocking = [a for a in rows if a.rasic_letter in BLOCKING_LETTERS]
        return bool(blocking) and all(
            a.effective_status in ("submitted", "waived") for a in blocking)

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
                              stage_order: Optional[int] = None) -> ChangeRouting:
        from app.services.change_service import ChangeService  # local import avoids cycle
        routing = await ChangeRoutingService._routing(session, change)
        existing = (await session.execute(
            select(ChangeAssessment).where(
                (ChangeAssessment.change_id == change.id)
                & (ChangeAssessment.department_id == department_id))
        )).scalar_one_or_none()
        # Change-scoped engine instance (Task 3). When present, deviation ops must
        # mutate its tasks alongside the assessment rows so engine state stays
        # consistent. Legacy pre-migration changes have none -> assessment-only.
        inst = (await session.execute(
            select(WfInstance).where(
                WfInstance.change_id == change.id,
                WfInstance.status == "active")
        )).scalar_one_or_none()

        if op == "add":
            if rasic_letter not in TASK_LETTERS:
                raise ValueError("add requires a task letter (R/A/S/C)")
            order = stage_order or 1
            if existing is None:
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
                # Engine: if the change has a running instance and the target stage
                # has already started (current or passed), create + link the task so
                # the assignment gets an actionable surface. A future stage is left
                # unlinked — lazy linking (Task 3) picks it up when the stage starts.
                if inst is not None and order <= inst.current_stage_order:
                    is_blocking = rasic_letter in BLOCKING_LETTERS
                    task = WfInstanceTask(
                        instance_id=inst.id, stage_order=order,
                        step_id=await _match_step_id(
                            session, inst.template_id, order, department_id, rasic_letter),
                        department_id=department_id, rasic_letter=rasic_letter,
                        status="active" if is_blocking else "noted",
                        is_actionable=is_blocking,
                        due_date=(datetime.utcnow() + timedelta(days=DEFAULT_TASK_DUE_DAYS)
                                  if is_blocking else None),
                    )
                    session.add(task)
                    await session.flush()
                    new_row.wf_instance_task_id = task.id
            else:
                existing.rasic_letter = rasic_letter
                existing.stage_order = order
                # Re-lettering/re-staging an existing row must carry the same
                # transitions onto its linked engine task so it doesn't go stale
                # (e.g. a C-noted task re-added as R must become active/actionable).
                if existing.wf_instance_task_id is not None:
                    task = await session.get(WfInstanceTask, existing.wf_instance_task_id)
                    if task is not None:
                        _retarget_task(task, rasic_letter, stage_order=order)
                        task.step_id = await _match_step_id(
                            session, inst.template_id if inst else None,
                            order, department_id, rasic_letter)
                        await session.flush()
                        if inst is not None:
                            await WorkflowService._maybe_advance_stage(session, inst)
            desc = f"added dept {department_id} as {rasic_letter} in stage {order}"
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
        elif op == "reletter":
            if rasic_letter not in TASK_LETTERS:
                raise ValueError("reletter requires a task letter (R/A/S/C)")
            if existing is None:
                raise ValueError("no assessment to reletter")
            existing.rasic_letter = rasic_letter
            if existing.wf_instance_task_id is not None:
                task = await session.get(WfInstanceTask, existing.wf_instance_task_id)
                if task is not None:
                    _retarget_task(task, rasic_letter)
                    await session.flush()
            # A reletter can add or remove a stage gate; re-check advancement.
            if inst is not None:
                await WorkflowService._maybe_advance_stage(session, inst)
            desc = f"re-lettered dept {department_id} to {rasic_letter}"
        else:
            raise ValueError(f"unknown op '{op}'")

        routing.has_deviation = True
        routing.deviation_status = "pending_approval"
        routing.deviation_proposed_by = user_id
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "routing_deviation", f"Routing deviation: {desc}", user_id)
        return routing

    @staticmethod
    async def _max_active_order(session: AsyncSession, change: ChangeRequest) -> int:
        rows = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
        )).scalars().all()
        active = [a.stage_order for a in rows if a.status == "active"]
        return max(active) if active else 1

    @staticmethod
    async def approve_deviation(session: AsyncSession, change: ChangeRequest, user_id: int) -> ChangeRouting:
        from app.services.change_service import ChangeService
        routing = await ChangeRoutingService._routing(session, change)
        if routing.deviation_status != "pending_approval":
            raise ValueError("No deviation pending approval")
        # No self-approval. If a non-lead proposed it, only the lead may approve. If the
        # lead proposed it, anyone-but-the-proposer (i.e. the PM) may approve.
        if routing.deviation_proposed_by == user_id:
            raise ValueError("Cannot approve your own routing deviation")
        if (change.lead_id is not None
                and routing.deviation_proposed_by != change.lead_id
                and user_id != change.lead_id):
            raise ValueError("Only the change lead may approve this deviation")
        routing.deviation_status = "approved"
        routing.deviation_approved_by = user_id
        routing.deviation_approved_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "routing_deviation_approved", "Routing deviation approved", user_id)
        return routing

    @staticmethod
    async def promote_to_standard(session: AsyncSession, change: ChangeRequest, user_id: int) -> None:
        """If the change carries an approved deviation against a mapped template, bump
        that template to v+1 (one step per stage), snapshot history, repoint standard."""
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
        for order, st in snapshot_stages.items():
            for dep in st["departments"]:
                if dep["rasic_letter"] == "I":
                    by_stage.setdefault(order, []).append(dep)

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
