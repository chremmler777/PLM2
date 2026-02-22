"""Workflow instance execution service (Phase 3c)."""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import (
    WfInstance, WfInstanceTask, WfTemplate, WfStage, WfStep
)
from app.models.article import ArticleRevision

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
                WfInstance.revision_id == revision_id,
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
            revision_id=revision_id,
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

        return instance

    @staticmethod
    async def _create_stage_tasks(
        db: AsyncSession,
        instance: WfInstance,
        stage: WfStage,
    ) -> None:
        """Create tasks for every RASIC assignment in a stage."""
        for step in sorted(stage.steps, key=lambda s: s.position_in_stage):
            for rasic in step.rasic_assignments:
                is_actionable = rasic.rasic_letter in ACTIONABLE_LETTERS
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
        if decision not in ("approved", "rejected"):
            raise ValueError("Decision must be 'approved' or 'rejected'")

        # Load task with instance eager-loaded
        task_result = await db.execute(
            select(WfInstanceTask)
            .where(WfInstanceTask.id == task_id)
            .options(selectinload(WfInstanceTask.instance))
        )
        task = task_result.scalar_one_or_none()
        if not task:
            raise ValueError("Task not found")
        if task.status != "active":
            raise ValueError("Task is not active")
        if not task.is_actionable:
            raise ValueError("Task is not actionable (S/I/C roles cannot complete tasks)")

        instance = task.instance

        # Update task
        task.status = decision
        task.completed_by = completed_by_id
        task.completed_at = datetime.utcnow()
        task.decision = decision
        task.notes = notes
        await db.flush()

        # Rejection propagates to instance immediately
        if decision == "rejected":
            instance.status = "rejected"
            instance.completed_at = datetime.utcnow()
            await db.flush()
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

        if all(t.status == "approved" for t in all_actionable):
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
            .where(WfInstance.revision_id == revision_id)
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
    async def get_my_tasks(
        db: AsyncSession,
        department_id: int,
    ) -> list[dict]:
        """Return active actionable tasks for a department, with article/revision info."""
        result = await db.execute(
            select(WfInstanceTask)
            .where(
                WfInstanceTask.department_id == department_id,
                WfInstanceTask.status == "active",
                WfInstanceTask.is_actionable == True,
            )
            .options(
                selectinload(WfInstanceTask.instance)
                .selectinload(WfInstance.revision)
                .selectinload(ArticleRevision.article),
                selectinload(WfInstanceTask.step)
                .selectinload(WfStep.stage),
                selectinload(WfInstanceTask.department),
            )
        )
        tasks = result.scalars().all()

        results = []
        for t in tasks:
            instance = t.instance
            revision = instance.revision
            article = revision.article
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
                "article_id": article.id,
                "article_number": article.article_number,
                "article_name": article.name,
                "revision_id": revision.id,
                "revision_label": revision.revision,
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
