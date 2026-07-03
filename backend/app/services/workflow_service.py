"""Workflow instance execution service (Phase 3c)."""
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import (
    WfInstance, WfInstanceTask, WfTemplate, WfStage, WfStep
)
from app.models.part import PartRevision

ACTIONABLE_LETTERS = {"R", "A"}
DEFAULT_TASK_DUE_DAYS = 7


class WorkflowService:

    @staticmethod
    async def start_workflow(
        db: AsyncSession,
        revision_id: int,
        template_id: int,
        started_by_id: int,
    ) -> WfInstance:
        """Start a workflow instance for a revision. Raises ValueError on conflict."""
        # Guard: active instance already exists
        existing = await db.execute(
            select(WfInstance).where(
                WfInstance.part_revision_id == revision_id,
                WfInstance.status == "active",
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("An active workflow already exists for this revision")

        template = await WorkflowService._load_template_for_start(db, template_id)

        # Create instance
        instance = WfInstance(
            template_id=template_id,
            part_revision_id=revision_id,
            status="active",
            current_stage_order=1,
            started_by=started_by_id,
            started_at=datetime.utcnow(),
        )
        db.add(instance)
        await db.flush()  # generate instance.id

        # Activate first stage tasks
        first_stage = sorted(template.stages, key=lambda s: s.stage_order)[0]
        await WorkflowService._create_stage_tasks(db, instance, first_stage)

        await WorkflowService._audit(db, instance, "wf_started", started_by_id,
                                     {"template_id": template_id,
                                      "revision_id": revision_id})

        return instance

    @staticmethod
    async def _load_template_for_start(
        db: AsyncSession, template_id: int
    ) -> WfTemplate:
        """Load a template with its stage/step/RASIC tree and validate that it
        is startable. Shared by revision- and change-scoped starts."""
        tmpl_result = await db.execute(
            select(WfTemplate)
            .where(WfTemplate.id == template_id)
            .options(
                selectinload(WfTemplate.stages)
                .selectinload(WfStage.steps)
                .selectinload(WfStep.rasic_assignments)
            )
        )
        template = tmpl_result.scalar_one_or_none()
        if not template:
            raise ValueError("Template not found")
        if not template.is_active:
            raise ValueError("Template is not active")
        if not template.stages:
            raise ValueError("Template has no stages")
        return template

    @staticmethod
    async def start_change_workflow(
        db: AsyncSession,
        change_id: int,
        template_id: int,
        started_by_id: int,
    ) -> WfInstance:
        """Start a change-scoped workflow instance (no part revision).

        Idempotent: if an active instance already exists for the change it is
        returned unchanged rather than raising."""
        existing = (await db.execute(
            select(WfInstance).where(
                WfInstance.change_id == change_id,
                WfInstance.status == "active",
            )
        )).scalar_one_or_none()
        if existing is not None:
            return existing

        template = await WorkflowService._load_template_for_start(db, template_id)

        instance = WfInstance(
            template_id=template_id,
            change_id=change_id,
            part_revision_id=None,
            status="active",
            current_stage_order=1,
            started_by=started_by_id,
            started_at=datetime.utcnow(),
        )
        db.add(instance)
        await db.flush()  # generate instance.id

        first_stage = sorted(template.stages, key=lambda s: s.stage_order)[0]
        await WorkflowService._create_stage_tasks(db, instance, first_stage)

        await WorkflowService._audit(db, instance, "wf_started", started_by_id,
                                     {"template_id": template_id,
                                      "change_id": change_id})

        return instance

    @staticmethod
    async def has_3d_evidence(db: AsyncSession, revision_id: int) -> bool:
        """CAD evidence rule: a live CAD file on the revision OR an
        owner-signed no-geometry-change flag. File presence only — conversion
        success is deliberately not required (spec risk note)."""
        from app.models.part import RevisionFile
        rev = await db.get(PartRevision, revision_id)
        if rev is not None and rev.no_geometry_change:
            return True
        row = (await db.execute(
            select(RevisionFile.id).where(
                RevisionFile.revision_id == revision_id,
                RevisionFile.file_type == "cad",
                RevisionFile.is_deleted == False,  # noqa: E712
            ).limit(1)
        )).scalar_one_or_none()
        return row is not None

    @staticmethod
    async def _audit(db: AsyncSession, instance: WfInstance, action: str,
                     user_id: int | None, new_values: dict | None = None) -> None:
        from app.models.change import ChangeRequest
        from app.services.audit_service import AuditService
        correlation = None
        if instance.change_id is not None:
            # Change-scoped instance: correlate to the change directly.
            change = await db.get(ChangeRequest, instance.change_id)
            correlation = change.change_number if change else None
        elif instance.part_revision_id is not None:
            rev = await db.get(PartRevision, instance.part_revision_id)
            if rev is not None and rev.originating_change_id is not None:
                change = await db.get(ChangeRequest, rev.originating_change_id)
                correlation = change.change_number if change else None
        await AuditService.record(
            db, entity_type="wf_instance", entity_id=instance.id, action=action,
            user_id=user_id, new_values=new_values, correlation_id=correlation)

    @staticmethod
    async def _create_stage_tasks(
        db: AsyncSession,
        instance: WfInstance,
        stage: WfStage,
    ) -> None:
        """Create tasks for every RASIC assignment in a stage and notify
        members of the departments that have actionable tasks."""
        actionable_departments: set[int] = set()
        fyi_departments: set[int] = set()
        tasks_created: list[WfInstanceTask] = []
        for step in sorted(stage.steps, key=lambda s: s.position_in_stage):
            for rasic in step.rasic_assignments:
                is_actionable = rasic.rasic_letter in ACTIONABLE_LETTERS
                if is_actionable:
                    actionable_departments.add(rasic.department_id)
                elif rasic.rasic_letter == "I":
                    fyi_departments.add(rasic.department_id)
                task = WfInstanceTask(
                    instance_id=instance.id,
                    stage_order=stage.stage_order,
                    step_id=step.id,
                    department_id=rasic.department_id,
                    rasic_letter=rasic.rasic_letter,
                    status="active" if is_actionable else "noted",
                    is_actionable=is_actionable,
                    due_date=(datetime.utcnow() + timedelta(days=DEFAULT_TASK_DUE_DAYS))
                    if is_actionable else None,
                )
                db.add(task)
                tasks_created.append(task)
        await db.flush()

        # Change-scoped instances: link this stage's assessment payload rows to the
        # freshly-created tasks (lazy linking — each stage links as its tasks appear).
        if instance.change_id is not None:
            from app.models.change import ChangeAssessment
            rows = (await db.execute(select(ChangeAssessment).where(
                ChangeAssessment.change_id == instance.change_id,
                ChangeAssessment.stage_order == stage.stage_order,
                ChangeAssessment.wf_instance_task_id.is_(None)))).scalars().all()
            by_key = {(t.department_id, t.rasic_letter): t for t in tasks_created}
            for a in rows:
                t = by_key.get((a.department_id, a.rasic_letter))
                if t is not None:
                    a.wf_instance_task_id = t.id
                    # A blocking row the user already submitted while its stage was
                    # still pending (a payload-only submit) must not be re-opened
                    # when its task finally materializes — mirror the submission
                    # onto the freshly-created task so effective_status stays
                    # 'submitted' and the engine treats the gate as satisfied.
                    if a.submitted_at is not None and t.is_actionable:
                        t.status = "approved"
                        t.decision = "approved"
                        t.completed_by = a.submitted_by
                        t.completed_at = a.submitted_at
            await db.flush()

        if actionable_departments:
            from app.services.notification_service import NotificationService

            part, revision = await WorkflowService._instance_part_context(db, instance)
            stage_label = stage.name or f"stage {stage.stage_order}"
            await NotificationService.notify_departments(
                db,
                list(actionable_departments),
                title=f"Workflow task: {part.name} {revision.revision_name}",
                body=f"Your department has a new task in '{stage_label}'.",
                link="/my-tasks",
            )

        if fyi_departments:
            from app.services.notification_service import NotificationService

            part, revision = await WorkflowService._instance_part_context(db, instance)
            stage_label = stage.name or f"stage {stage.stage_order}"
            link = (f"/changes/{instance.change_id}?tab=assessments"
                    if instance.change_id is not None else "/my-tasks")
            await NotificationService.notify_departments_once(
                db,
                list(fyi_departments),
                kind="fyi_stage",
                subject_key=f"inst:{instance.id}:stage:{stage.stage_order}",
                title=f"FYI: {part.name} {revision.revision_name}",
                body=f"'{stage_label}' has started — informational only.",
                link=link,
            )

    @staticmethod
    async def _instance_part_context(db: AsyncSession, instance: WfInstance):
        """Part and revision belonging to a workflow instance.

        For change-scoped instances (no part revision) this returns lightweight
        stand-ins whose ``name``/``revision_name`` carry the change title and
        number, so callers building notification text keep working unchanged."""
        from app.models.part import Part

        if instance.part_revision_id is None:
            from types import SimpleNamespace
            from app.models.change import ChangeRequest

            change = await db.get(ChangeRequest, instance.change_id) \
                if instance.change_id is not None else None
            part = SimpleNamespace(
                id=None,
                name=change.title if change else "",
                project_id=change.project_id if change else None,
            )
            revision = SimpleNamespace(
                revision_name=change.change_number if change else "")
            return part, revision

        result = await db.execute(
            select(PartRevision, Part)
            .join(Part, Part.id == PartRevision.part_id)
            .where(PartRevision.id == instance.part_revision_id)
        )
        revision, part = result.one()
        return part, revision

    @staticmethod
    async def complete_task(
        db: AsyncSession,
        task_id: int,
        decision: str,
        notes: str | None,
        completed_by_id: int,
    ) -> WfInstance:
        """Complete an actionable task and advance the workflow if stage is done."""
        # Validate decision value first
        if decision not in ("approved", "rejected", "waived"):
            raise ValueError("Decision must be 'approved', 'rejected' or 'waived'")
        if decision == "waived" and not (notes and notes.strip()):
            raise ValueError("Waiving a step requires a reason (notes)")

        # Load task with instance eager-loaded
        task_result = await db.execute(
            select(WfInstanceTask)
            .where(WfInstanceTask.id == task_id)
            .options(selectinload(WfInstanceTask.instance),
                     selectinload(WfInstanceTask.step))
        )
        task = task_result.scalar_one_or_none()
        if not task:
            raise ValueError("Task not found")
        if task.status != "active":
            raise ValueError("Task is not active")
        if not task.is_actionable:
            raise ValueError("Task is not actionable (S/I/C roles cannot complete tasks)")

        step = task.step
        # CAD-evidence gate applies to revision-scoped (ECN) instances only;
        # change-scoped instances have no part revision to attach a CAD file to.
        if (step is not None and step.requires_cad_evidence
                and decision == "approved"
                and task.instance.part_revision_id is not None):
            if not await WorkflowService.has_3d_evidence(db, task.instance.part_revision_id):
                raise ValueError(
                    "3D evidence required: upload a CAD file to this revision "
                    "or sign 'no geometry change' before approving this step")
        if step is not None and step.four_eyes and decision == "approved":
            prev = (await db.execute(
                select(WfInstanceTask.completed_by).where(
                    WfInstanceTask.instance_id == task.instance_id,
                    WfInstanceTask.stage_order == task.stage_order - 1,
                    WfInstanceTask.status.in_(("approved", "waived")),
                ))).scalars().all()
            if completed_by_id in {u for u in prev if u is not None}:
                raise ValueError(
                    "4-eyes check: this step must be decided by a different "
                    "user than the previous stage")

        instance = task.instance

        # Update task
        task.status = decision
        task.completed_by = completed_by_id
        task.completed_at = datetime.utcnow()
        task.decision = decision
        task.notes = notes
        await db.flush()

        await WorkflowService._audit(
            db, instance, f"task_{decision}", completed_by_id,
            {"task_id": task.id, "step": step.step_name if step else None,
             "notes": notes})

        # Rejection propagates to instance immediately
        if decision == "rejected":
            instance.status = "rejected"
            instance.completed_at = datetime.utcnow()
            await db.flush()

            from app.services.notification_service import NotificationService

            part, revision = await WorkflowService._instance_part_context(db, instance)
            await NotificationService.notify_users(
                db,
                [instance.started_by],
                title=f"Workflow rejected: {part.name} {revision.revision_name}",
                body=notes or None,
                link=f"/projects/{part.project_id}?part={part.id}",
            )
            return instance

        return await WorkflowService._maybe_advance_stage(
            db, instance, actor_id=completed_by_id)

    @staticmethod
    async def _maybe_advance_stage(
        db: AsyncSession,
        instance: WfInstance,
        actor_id: int | None = None,
    ) -> WfInstance:
        """Advance the instance if every actionable task in its current stage is
        resolved (approved/waived), cascading through optional-only stages and
        completing the instance when no gated stage remains.

        Extracted from ``complete_task`` (unchanged logic) so routing-deviation
        remove/reletter can re-run the same gate after mutating tasks. ``actor_id``
        attributes the completion audit; it is ``None`` for engine-internal
        re-checks (e.g. a deviation removing the last blocking task)."""
        # A non-active instance (already completed/rejected/canceled) must never
        # advance again — completing a stray task in a passed stage of a finished
        # instance would otherwise re-enter the completion branch and emit a
        # duplicate wf_completed audit + notification.
        if instance.status != "active":
            return instance
        # Check if all actionable tasks in the current stage are approved
        stage_tasks_result = await db.execute(
            select(WfInstanceTask).where(
                WfInstanceTask.instance_id == instance.id,
                WfInstanceTask.stage_order == instance.current_stage_order,
                WfInstanceTask.is_actionable == True,
            )
        )
        all_actionable = stage_tasks_result.scalars().all()

        if all(t.status in ("approved", "waived") for t in all_actionable):
            # Advance: load template stages to find next
            tmpl_result = await db.execute(
                select(WfTemplate)
                .where(WfTemplate.id == instance.template_id)
                .options(
                    selectinload(WfTemplate.stages)
                    .selectinload(WfStage.steps)
                    .selectinload(WfStep.rasic_assignments)
                )
            )
            template = tmpl_result.scalar_one()
            stages = sorted(template.stages, key=lambda s: s.stage_order)

            # Advance stage by stage, cascading through any stage that carries no
            # actionable (R/A) task. An optional-only stage (all C/S/I) has no gate
            # to wait on, so it must not stall the instance — its tasks are still
            # created (noted) so consulted parties see them, but we keep advancing
            # until we reach a stage with a real gate or run out of stages.
            while True:
                next_stages = [s for s in stages
                               if s.stage_order > instance.current_stage_order]
                if not next_stages:
                    instance.status = "completed"
                    instance.completed_at = datetime.utcnow()

                    await WorkflowService._audit(db, instance, "wf_completed",
                                                 actor_id, None)

                    from app.services.notification_service import NotificationService

                    part, revision = await WorkflowService._instance_part_context(db, instance)
                    await NotificationService.notify_users(
                        db,
                        [instance.started_by],
                        title=f"Workflow completed: {part.name} {revision.revision_name}",
                        body="All stages approved.",
                        link=f"/projects/{part.project_id}?part={part.id}",
                    )
                    break

                next_stage = next_stages[0]
                instance.current_stage_order = next_stage.stage_order
                await WorkflowService._create_stage_tasks(db, instance, next_stage)
                # Continuation is decided from the OPEN actionable tasks actually
                # created for this stage, not the template's RASIC letters. A stage
                # can be born already complete: _create_stage_tasks mirrors early
                # payload-submitted assessments onto its fresh tasks, so a stage
                # whose only actionable tasks are all approved/waived (or which has
                # none) has no gate left to wait on and must keep cascading —
                # relying on template letters here would stall the instance forever.
                stage_actionable = (await db.execute(
                    select(WfInstanceTask).where(
                        WfInstanceTask.instance_id == instance.id,
                        WfInstanceTask.stage_order == next_stage.stage_order,
                        WfInstanceTask.is_actionable == True,  # noqa: E712
                    ))).scalars().all()
                if any(t.status not in ("approved", "waived")
                       for t in stage_actionable):
                    break
                # No open gate in this stage -> cascade on to the next one.

            await db.flush()

        return instance

    @staticmethod
    async def _is_department_member(db: AsyncSession, user_id: int,
                                    department_id: int) -> bool:
        from app.models.workflow import UserDepartment
        row = (await db.execute(
            select(UserDepartment).where(
                UserDepartment.user_id == user_id,
                UserDepartment.department_id == department_id).limit(1)
        )).scalar_one_or_none()
        return row is not None

    @staticmethod
    async def _load_open_task(db: AsyncSession, task_id: int) -> WfInstanceTask:
        task = (await db.execute(
            select(WfInstanceTask).where(WfInstanceTask.id == task_id)
            .options(selectinload(WfInstanceTask.instance),
                     selectinload(WfInstanceTask.step))
        )).scalar_one_or_none()
        if task is None:
            raise ValueError("Task not found")
        if task.status != "active" or not task.is_actionable:
            raise ValueError("Task is not open (active and actionable)")
        return task

    @staticmethod
    async def accept_task(db: AsyncSession, task_id: int, user) -> WfInstanceTask:
        task = await WorkflowService._load_open_task(db, task_id)
        if user.role != "admin" and not await WorkflowService._is_department_member(
                db, user.id, task.department_id):
            raise ValueError("Only members of the task's department may accept it")
        if task.owner_id is not None and task.owner_id != user.id:
            raise ValueError("Task is already owned by another user")
        task.owner_id = user.id
        task.accepted_at = datetime.utcnow()
        await db.flush()
        await WorkflowService._audit(
            db, task.instance, "task_accepted", user.id,
            {"task_id": task.id, "owner_id": user.id})
        return task

    @staticmethod
    async def assign_task(db: AsyncSession, task_id: int, assignee_id: int,
                          actor) -> WfInstanceTask:
        from app.models.entities import User
        from app.models.change import ChangeRequest
        task = await WorkflowService._load_open_task(db, task_id)
        allowed = actor.role == "admin" or await WorkflowService._is_department_member(
                db, actor.id, task.department_id)
        if not allowed:
            if task.instance.change_id is not None:
                # Change-scoped: authorize against the change lead directly.
                change = await db.get(ChangeRequest, task.instance.change_id)
                allowed = change is not None and change.lead_id == actor.id
            elif task.instance.part_revision_id is not None:
                rev = await db.get(PartRevision, task.instance.part_revision_id)
                if rev is not None and rev.originating_change_id is not None:
                    change = await db.get(ChangeRequest, rev.originating_change_id)
                    allowed = change is not None and change.lead_id == actor.id
        if not allowed:
            raise ValueError("Only members of the task's department (or an admin) may assign it")
        assignee = await db.get(User, assignee_id)
        if assignee is None or not assignee.is_active:
            raise ValueError("Assignee not found or inactive")
        if not await WorkflowService._is_department_member(
                db, assignee_id, task.department_id):
            raise ValueError("Assignee must be a member of the task's department")
        task.owner_id = assignee_id
        task.accepted_at = None
        await db.flush()
        await WorkflowService._audit(
            db, task.instance, "task_assigned", actor.id,
            {"task_id": task.id, "owner_id": assignee_id})
        if assignee_id != actor.id:
            from app.services.notification_service import NotificationService
            step_name = task.step.step_name if task.step else "workflow task"
            link = (f"/changes/{task.instance.change_id}?tab=assessments"
                    if task.instance.change_id is not None else "/my-tasks")
            await NotificationService.notify_once(
                db, [assignee_id], kind="task_assigned",
                subject_key=f"task:{task.id}",
                title=f"Task assigned: {step_name}", link=link)
        return task

    @staticmethod
    async def set_task_due_date(db: AsyncSession, task_id: int,
                                due_date: datetime, actor) -> WfInstanceTask:
        from app.models.change import ChangeRequest
        task = await WorkflowService._load_open_task(db, task_id)
        allowed = actor.role == "admin" or task.instance.started_by == actor.id
        if not allowed:
            if task.instance.change_id is not None:
                # Change-scoped: authorize against the change lead directly.
                change = await db.get(ChangeRequest, task.instance.change_id)
                allowed = change is not None and change.lead_id == actor.id
            elif task.instance.part_revision_id is not None:
                rev = await db.get(PartRevision, task.instance.part_revision_id)
                if rev is not None and rev.originating_change_id is not None:
                    change = await db.get(ChangeRequest, rev.originating_change_id)
                    allowed = change is not None and change.lead_id == actor.id
        if not allowed:
            raise ValueError(
                "Only an admin, the workflow starter, or the change lead may set due dates")
        old = task.due_date.isoformat() if task.due_date else None
        task.due_date = due_date
        await db.flush()
        await WorkflowService._audit(
            db, task.instance, "task_due_date_set", actor.id,
            {"task_id": task.id, "old": old, "new": due_date.isoformat()})
        return task

    @staticmethod
    async def get_revision_workflow(
        db: AsyncSession,
        revision_id: int,
    ) -> WfInstance | None:
        """Return the latest workflow instance for a revision, or None."""
        result = await db.execute(
            select(WfInstance)
            .where(WfInstance.part_revision_id == revision_id)
            .options(
                selectinload(WfInstance.tasks).selectinload(WfInstanceTask.step),
                selectinload(WfInstance.tasks).selectinload(WfInstanceTask.department),
                selectinload(WfInstance.template),
            )
            .order_by(WfInstance.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_department_ids(db: AsyncSession, user_id: int) -> list[int]:
        """Department ids the user belongs to."""
        from app.models.workflow import UserDepartment

        result = await db.execute(
            select(UserDepartment.department_id).where(UserDepartment.user_id == user_id)
        )
        return [d for (d,) in result.all()]

    @staticmethod
    async def get_my_tasks(
        db: AsyncSession,
        department_ids: list[int],
        user_id: int,
    ) -> list[dict]:
        """Return active actionable tasks for the departments, with part/revision info."""
        if not department_ids:
            return []
        result = await db.execute(
            select(WfInstanceTask)
            .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
            .where(
                WfInstanceTask.department_id.in_(department_ids),
                WfInstanceTask.status == "active",
                WfInstanceTask.is_actionable == True,
                # Change-scoped tasks surface via /changes/my-tasks (Task 7),
                # not here — exclude them to avoid double-appearing.
                WfInstance.change_id.is_(None),
            )
            .options(
                selectinload(WfInstanceTask.instance)
                .selectinload(WfInstance.part_revision)
                .selectinload(PartRevision.part),
                selectinload(WfInstanceTask.step)
                .selectinload(WfStep.stage),
                selectinload(WfInstanceTask.department),
            )
        )
        tasks = result.scalars().all()

        results = []
        for t in tasks:
            instance = t.instance
            revision = instance.part_revision
            part = revision.part
            stage = t.step.stage
            results.append({
                "task_id": t.id,
                "instance_id": t.instance_id,
                "status": t.status,
                "is_actionable": t.is_actionable,
                "rasic_letter": t.rasic_letter,
                "department_name": t.department.name if t.department else "",
                "step_name": t.step.step_name if t.step else "",
                "stage_order": t.stage_order,
                "stage_name": stage.name if stage else None,
                "part_id": part.id,
                "part_number": part.part_number,
                "part_name": part.name,
                "project_id": part.project_id,
                "revision_id": revision.id,
                "revision_name": revision.revision_name,
                "instance_started_at": instance.started_at,
                "owner_id": t.owner_id,
                "owner_name": t.owner_name,
                "accepted_at": t.accepted_at,
                "due_date": t.due_date,
                "overdue": t.overdue,
                "mine": t.owner_id == user_id,
            })

        results.sort(key=lambda d: (
            not d["mine"], not d["overdue"],
            d["due_date"] is None, d["due_date"] or datetime.max, d["task_id"]))
        return results

    @staticmethod
    async def cancel_workflow(
        db: AsyncSession,
        instance_id: int,
        canceled_by_id: int,
        reason: str | None,
    ) -> WfInstance:
        """Cancel an active workflow instance."""
        result = await db.execute(
            select(WfInstance).where(WfInstance.id == instance_id)
        )
        instance = result.scalar_one_or_none()
        if not instance:
            raise ValueError("Workflow instance not found")
        if instance.status != "active":
            raise ValueError("Only active workflows can be canceled")

        instance.status = "canceled"
        instance.canceled_at = datetime.utcnow()
        instance.canceled_by = canceled_by_id
        instance.cancel_reason = reason
        await db.flush()
        return instance
