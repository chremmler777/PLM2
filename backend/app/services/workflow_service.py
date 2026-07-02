"""Workflow instance execution service (Phase 3c)."""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import (
    WfInstance, WfInstanceTask, WfTemplate, WfStage, WfStep
)
from app.models.part import PartRevision

ACTIONABLE_LETTERS = {"R", "A"}


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

        # Load template with full structure
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
        for step in sorted(stage.steps, key=lambda s: s.position_in_stage):
            for rasic in step.rasic_assignments:
                is_actionable = rasic.rasic_letter in ACTIONABLE_LETTERS
                if is_actionable:
                    actionable_departments.add(rasic.department_id)
                task = WfInstanceTask(
                    instance_id=instance.id,
                    stage_order=stage.stage_order,
                    step_id=step.id,
                    department_id=rasic.department_id,
                    rasic_letter=rasic.rasic_letter,
                    status="active" if is_actionable else "noted",
                    is_actionable=is_actionable,
                )
                db.add(task)
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

    @staticmethod
    async def _instance_part_context(db: AsyncSession, instance: WfInstance):
        """Part and revision belonging to a workflow instance."""
        from app.models.part import Part

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
        if step is not None and step.requires_cad_evidence and decision == "approved":
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
            next_stages = [s for s in stages if s.stage_order > instance.current_stage_order]

            if not next_stages:
                instance.status = "completed"
                instance.completed_at = datetime.utcnow()

                await WorkflowService._audit(db, instance, "wf_completed",
                                             completed_by_id, None)

                from app.services.notification_service import NotificationService

                part, revision = await WorkflowService._instance_part_context(db, instance)
                await NotificationService.notify_users(
                    db,
                    [instance.started_by],
                    title=f"Workflow completed: {part.name} {revision.revision_name}",
                    body="All stages approved.",
                    link=f"/projects/{part.project_id}?part={part.id}",
                )
            else:
                next_stage = next_stages[0]
                instance.current_stage_order = next_stage.stage_order
                await WorkflowService._create_stage_tasks(db, instance, next_stage)

            await db.flush()

        return instance

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
    ) -> list[dict]:
        """Return active actionable tasks for the departments, with part/revision info."""
        if not department_ids:
            return []
        result = await db.execute(
            select(WfInstanceTask)
            .where(
                WfInstanceTask.department_id.in_(department_ids),
                WfInstanceTask.status == "active",
                WfInstanceTask.is_actionable == True,
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
            })
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
