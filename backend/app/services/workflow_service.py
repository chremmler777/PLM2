"""Workflow instance execution service (Phase 3c)."""
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import (
    WfInstance, WfInstanceTask, WfTemplate, WfStage, WfStep
)
from app.models.part import PartRevision

ACTIONABLE_LETTERS = {"R", "A"}
DEFAULT_TASK_DUE_DAYS = 7


class TaskAssignForbidden(ValueError):
    """The caller may not assign this task (a rights refusal: 403 where the
    router maps it; a ValueError, so older callers still answer 400)."""


class TaskAcceptForbidden(ValueError):
    """The caller may not accept this task: not a member of its department
    (403, not 400; review 2026-10-19)."""


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
        dropped = await WorkflowService._create_stage_tasks(db, instance, first_stage)

        await WorkflowService._audit(db, instance, "wf_started", started_by_id,
                                     {"template_id": template_id,
                                      "revision_id": revision_id})
        if dropped:
            # A revision signed 'no geometry change' starts past the stages
            # it does not need (Christoph 2026-10-19): cascade as for a stage
            # completed by its last task.
            await WorkflowService._maybe_advance_stage(
                db, instance, actor_id=started_by_id)

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
        # A change-scoped stage 1 can be born gateless (its only actionable rows
        # were already payload-submitted, or scoping left it with no R/A task):
        # cascade immediately so the instance advances instead of stalling on an
        # already-satisfied stage.
        await WorkflowService._maybe_advance_stage(db, instance, actor_id=started_by_id)

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
    async def no_geometry_drops(db: AsyncSession,
                                instance: WfInstance) -> tuple[dict, int | None]:
        """DECIDED BY CHRISTOPH 2026-10-19 (switch RELEASE_V2): the steps an
        ECN check workflow does not ask of a revision signed 'no geometry
        change': the Design and Design check stages, and the steps the
        release checklist (and validation) already ask, the one place.
        Returns ({step_id: waive note}, the signer) - empty for any other
        instance, an unsigned revision, another template or the switch off."""
        from app.services import cm_switches
        from app.services import wf_seed_service as seeds
        if instance.part_revision_id is None or not cm_switches.on("RELEASE_V2"):
            return {}, None
        rev = await db.get(PartRevision, instance.part_revision_id)
        if rev is None or not rev.no_geometry_change:
            return {}, None
        name = (await db.execute(select(WfTemplate.name).where(
            WfTemplate.id == instance.template_id))).scalar_one_or_none()
        if name not in seeds.ECN_TEMPLATE_NAMES:
            return {}, None
        rows = (await db.execute(
            select(WfStep.id, WfStep.step_name, WfStage.name)
            .join(WfStage, WfStage.id == WfStep.stage_id)
            .where(WfStage.template_id == instance.template_id))).all()
        out: dict[int, str] = {}
        for step_id, step_name, stage_name in rows:
            if stage_name in seeds.NO_GEOMETRY_DROPPED_STAGES:
                out[step_id] = ("Dropped: no geometry change signed (no design "
                                "work to update or check)")
            elif step_name in seeds.ASKED_ON_RELEASE:
                out[step_id] = ("Dropped: no geometry change signed; asked once "
                                f"in the {seeds.ASKED_ON_RELEASE[step_name]}")
        return out, rev.no_geometry_change_by

    @staticmethod
    async def no_geometry_signer_departments(db: AsyncSession,
                                             revision: PartRevision) -> tuple[str, ...]:
        """The departments that own the revision's 3D evidence: the R and A
        departments of the CAD-evidence step of its ECN check workflow
        template (the revision's running one, else the one for the part's
        category): Development for an article, Tool Engineer and Development
        for a tool."""
        from app.models.part import Part
        from app.services import wf_seed_service as seeds
        name = (await db.execute(
            select(WfTemplate.name)
            .join(WfInstance, WfInstance.template_id == WfTemplate.id)
            .where(WfInstance.part_revision_id == revision.id,
                   WfTemplate.name.in_(list(seeds.ECN_TEMPLATE_NAMES)))
            .order_by(WfInstance.id.desc()).limit(1))).scalar_one_or_none()
        if name is None:
            part = await db.get(Part, revision.part_id)
            name = seeds.CHECK_WF_CATEGORY_TEMPLATE.get(
                getattr(part, "item_category", None) or "article",
                seeds.ECN_UMSETZUNG_ARTIKEL["name"])
        spec = next(t for t in (seeds.ECN_UMSETZUNG_WERKZEUG, seeds.ECN_UMSETZUNG_ARTIKEL)
                    if t["name"] == name)
        out: list[str] = []
        for _stage, steps in spec["stages"]:
            for _step, rasic, flags in steps:
                if flags.get("requires_cad_evidence"):
                    out += [d for d, letter in rasic if letter in ("R", "A") and d not in out]
        return tuple(out)

    @staticmethod
    async def may_sign_no_geometry(db: AsyncSession, revision: PartRevision,
                                   user) -> bool:
        """Review fix 2026-10-19: 'no geometry change' is the 3D evidence
        and drops the Design stages and the release duplicates of the check
        workflow, so only its owner signs: a real member of the department
        that owns the 3D data (no_geometry_signer_departments), the lead of
        the change the revision belongs to, or a Project Management member.
        An admin's own department rows do not count (D7, real_member_of): an
        admin signs by acting as one of those departments."""
        if getattr(user, "effective_role", None) == "viewer":
            return False
        from app.models.change import ChangeImpactedItem, ChangeRequest
        from app.services.change_people import holds_lead
        from app.services.change_service import ChangeService
        change_ids = {revision.originating_change_id} - {None}
        change_ids |= set((await db.execute(
            select(ChangeImpactedItem.change_id).where(
                ChangeImpactedItem.resulting_revision_id == revision.id))).scalars().all())
        if change_ids:
            leads = (await db.execute(select(ChangeRequest).where(
                ChangeRequest.id.in_(change_ids)))).scalars().all()
            if any(holds_lead(c, user) for c in leads):
                return True
        names = await WorkflowService.no_geometry_signer_departments(db, revision)
        return await ChangeService.real_member_of(db, user, "Project Manager", *names)

    @staticmethod
    async def apply_no_geometry_change(db: AsyncSession, revision: PartRevision,
                                       user_id: int) -> int:
        """The revision was just signed 'no geometry change': its running ECN
        check workflow drops what it no longer asks (no_geometry_drops). Open
        R/A tasks of those steps are waived with the reason, signed by the
        signer; tasks already done stay as they are; the instance then moves
        on as after any completed stage (later stages are created without the
        dropped steps). Returns the number of tasks waived."""
        instances = (await db.execute(select(WfInstance).where(
            WfInstance.part_revision_id == revision.id,
            WfInstance.status == "active"))).scalars().all()
        waived = 0
        for inst in instances:
            drops, _ = await WorkflowService.no_geometry_drops(db, inst)
            if not drops:
                continue
            tasks = (await db.execute(select(WfInstanceTask).where(
                WfInstanceTask.instance_id == inst.id,
                WfInstanceTask.step_id.in_(list(drops)),
                WfInstanceTask.is_actionable.is_(True),
                WfInstanceTask.status.in_(("pending", "active"))))).scalars().all()
            now = datetime.utcnow()
            for t in tasks:
                t.status = "waived"
                t.decision = "waived"
                t.completed_by = user_id
                t.completed_at = now
                t.notes = drops[t.step_id]
            if tasks:
                waived += len(tasks)
                await db.flush()
                await WorkflowService._audit(
                    db, inst, "tasks_dropped_no_geometry", user_id,
                    {"task_ids": [t.id for t in tasks]})
            await WorkflowService._maybe_advance_stage(db, inst, actor_id=user_id)
        return waived

    @staticmethod
    async def _create_stage_tasks(
        db: AsyncSession,
        instance: WfInstance,
        stage: WfStage,
    ) -> int:
        """Create tasks for every RASIC assignment in a stage and notify
        members of the departments that have actionable tasks. A step an
        ECN check workflow does not ask of a 'no geometry change' revision
        (no_geometry_drops) gets its R/A tasks born waived with the reason
        and no C/S/I task; returns how many were born waived."""
        actionable_departments: set[int] = set()
        fyi_departments: set[int] = set()
        tasks_created: list[WfInstanceTask] = []
        # Departments owing a step-less (deviation-added) task: told with a
        # link to the change's assessments, where their row is listed.
        added_departments: set[int] = set()

        # Change-scoped instances execute the change's routing *snapshot*, which
        # may be scoped down from the template (scoping-meeting department
        # selection, deviations). Skip template assignments absent from the
        # snapshot so engine tasks never outnumber the governed routing.
        allowed_pairs: set | None = None
        snap_departments: list[dict] = []
        if instance.change_id is not None:
            from app.models.change import ChangeRouting
            routing = (await db.execute(
                select(ChangeRouting).where(
                    ChangeRouting.change_id == instance.change_id)
            )).scalar_one_or_none()
            if routing is not None:
                snap_stage = next(
                    (st for st in routing.standard_snapshot.get("stages", [])
                     if st["stage_order"] == stage.stage_order), None)
                if snap_stage is not None:
                    # An approved deviation add sits on the snapshot
                    # (added_by_deviation) but is still outside the
                    # template: its step-less task comes from its row below.
                    snap_departments = [d for d in snap_stage["departments"]
                                        if not d.get("added_by_deviation")]
                    allowed_pairs = {(d["department_id"], d["rasic_letter"])
                                     for d in snap_departments}

        drops, signer = await WorkflowService.no_geometry_drops(db, instance)
        born_waived: list[WfInstanceTask] = []

        def _add_task(step_id, department_id: int, letter: str) -> None:
            is_actionable = letter in ACTIONABLE_LETTERS
            if step_id in drops:
                # not asked here (Christoph 2026-10-19): on the record as
                # waived with where it is asked, nobody told, nothing noted
                if is_actionable:
                    task = WfInstanceTask(
                        instance_id=instance.id, stage_order=stage.stage_order,
                        step_id=step_id, department_id=department_id,
                        rasic_letter=letter, status="waived", decision="waived",
                        is_actionable=True, completed_by=signer,
                        completed_at=datetime.utcnow(), notes=drops[step_id])
                    db.add(task)
                    born_waived.append(task)
                return
            if is_actionable:
                actionable_departments.add(department_id)
            elif letter == "I":
                fyi_departments.add(department_id)
            task = WfInstanceTask(
                instance_id=instance.id,
                stage_order=stage.stage_order,
                step_id=step_id,
                department_id=department_id,
                rasic_letter=letter,
                status="active" if is_actionable else "noted",
                is_actionable=is_actionable,
                due_date=(datetime.utcnow() + timedelta(days=DEFAULT_TASK_DUE_DAYS))
                if is_actionable else None,
            )
            db.add(task)
            tasks_created.append(task)

        steps = sorted(stage.steps, key=lambda s: s.position_in_stage)
        produced: set = set()
        for step in steps:
            for rasic in step.rasic_assignments:
                if allowed_pairs is not None and \
                        (rasic.department_id, rasic.rasic_letter) not in allowed_pairs:
                    continue
                _add_task(step.id, rasic.department_id, rasic.rasic_letter)
                produced.add((rasic.department_id, rasic.rasic_letter))

        # The snapshot is authoritative for a change (the scoping room decides
        # who assesses, and with which letter): a department the room pulled
        # in that the template's stage does not carry, or carries with another
        # letter, still gets its task. Without this the row sat in the stage
        # with no task, owed an answer nobody could give, and held the gate
        # forever (final walk P1-1). Hung off the step that carries the
        # department, else the stage's first step.
        for d in snap_departments:
            pair = (d["department_id"], d["rasic_letter"])
            if pair in produced:
                continue
            produced.add(pair)
            step_id = next(
                (s.id for s in steps
                 if any(r.department_id == d["department_id"]
                        for r in s.rasic_assignments)),
                steps[0].id if steps else None)
            _add_task(step_id, d["department_id"], d["rasic_letter"])

        # A routing deviation that added an R/A/S/C department to this stage
        # before it started left an assessment row, but neither the template
        # nor the snapshot's standard entries carry it (an approved add sits
        # on the snapshot marked added_by_deviation, skipped above). Its
        # task is created here, with the stage's others, BEFORE the caller
        # decides whether the stage has a gate: otherwise a stage whose
        # template rows are all C/I cascades straight through and the added
        # Responsible department is never asked. Such a row is outside the
        # template and the snapshot: its task carries NO step (never the
        # stage's first step), the mark is_assessment_row, blocking_complete,
        # My Tasks and the cockpit read as "a department somebody added to
        # the assessment", whatever stage it landed on.
        if instance.change_id is not None:
            from app.models.change import ChangeAssessment, ASSESSMENT_LETTERS
            extra = (await db.execute(
                select(ChangeAssessment.department_id, ChangeAssessment.rasic_letter)
                .where(ChangeAssessment.change_id == instance.change_id,
                       ChangeAssessment.stage_order == stage.stage_order,
                       ChangeAssessment.wf_instance_task_id.is_(None),
                       ChangeAssessment.rasic_letter.in_(ASSESSMENT_LETTERS))
                .order_by(ChangeAssessment.id))).all()
            for department_id, letter in extra:
                pair = (department_id, letter)
                if pair in produced:
                    continue
                produced.add(pair)
                _add_task(None, department_id, letter)
                if letter in ACTIONABLE_LETTERS:
                    added_departments.add(department_id)
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
                        # Same rule as complete_task: the submitter owns what
                        # they answered, so the mirrored task carries the
                        # assessment's owner rather than reading "unassigned".
                        if t.owner_id is None:
                            t.owner_id = a.owner_id or a.submitted_by
                            if t.accepted_at is None:
                                t.accepted_at = a.accepted_at or a.submitted_at
            await db.flush()

        standard_departments = actionable_departments - added_departments
        if standard_departments:
            from app.services.notification_service import NotificationService

            part, revision = await WorkflowService._instance_part_context(db, instance)
            stage_label = stage.name or f"stage {stage.stage_order}"
            # Project team (spec §18): the responsible first, backups as info.
            await NotificationService.notify_team(
                db, part.project_id,
                list(standard_departments),
                title=f"Workflow task: {part.name} {revision.revision_name}",
                body=f"Your department has a new task in '{stage_label}'.",
                link="/my-tasks", kind="task_new",
            )
        if added_departments:
            from app.services.notification_service import NotificationService

            part, revision = await WorkflowService._instance_part_context(db, instance)
            await NotificationService.notify_team(
                db, part.project_id,
                sorted(added_departments),
                title=f"Assessment task: {revision.revision_name}",
                body=(f"Your department was added to the assessment of "
                      f"'{part.name}' and has an assessment to give."),
                link=f"/changes/{instance.change_id}?tab=assessments",
                kind="task_new",
            )

        if fyi_departments:
            from app.services.notification_service import NotificationService

            part, revision = await WorkflowService._instance_part_context(db, instance)
            stage_label = stage.name or f"stage {stage.stage_order}"
            link = (f"/changes/{instance.change_id}?tab=assessments"
                    if instance.change_id is not None else "/my-tasks")
            await NotificationService.notify_team(
                db, part.project_id,
                list(fyi_departments),
                kind="fyi_stage",
                subject_key=f"inst:{instance.id}:stage:{stage.stage_order}",
                title=f"FYI: {part.name} {revision.revision_name}",
                body=f"'{stage_label}' has started — informational only.",
                link=link,
            )
        return len(born_waived)

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

        # Department-membership guard: only a member of the task's department
        # (or an admin) may record a decision on it. Placed after the
        # active/actionable checks (those are structural — "can this task be
        # acted on at all") and before any decision writes, so a rejected
        # actor never mutates state. Mirrors accept_task/assign_task's
        # existing admin-exempt membership check.
        from app.models.entities import User
        actor = await db.get(User, completed_by_id)
        if actor is None:
            raise ValueError("Actor not found")
        fallback = None
        in_department = await WorkflowService.actor_in_department(
            db, actor, task.department_id)
        if not in_department and decision == "approved":
            # DECIDED BY CLAUDE 2026-10-26 (Christoph confirms): a 4-eyes
            # review whose department has nobody but the previous stage's
            # doer goes to the project's Tool Engineer (four_eyes_fallback)
            fallback = await WorkflowService.four_eyes_fallback(db, task)
            if fallback is not None and fallback["user_id"] != actor.id:
                fallback = None
        if actor.effective_role != "admin" and not in_department and fallback is None \
                and not await WorkflowService.coordinates_task(db, task, actor):
            raise ValueError(
                "Only members of the task's department (or an admin) may complete it; "
                "for a department with no member here the change's coordinator does")

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
        # Doing the work IS taking it. There is no accept step in front of a
        # task any more — accept_task still works, but no flow requires it —
        # so whoever records the decision becomes the owner of record if
        # nobody had put their name on it. Without this a finished task reads
        # "unassigned", which is the one thing it certainly is not. A
        # deliberate assignment (or an actual accept) is never overwritten.
        #
        # Assigned through the relationship, not the id column, so the name
        # the response serializes is right in this same session — the
        # already-loaded `owner` would otherwise stay the None it was loaded
        # as. Same call as ChangeService.submit_assessment.
        if task.owner_id is None:
            task.owner = actor
            if task.accepted_at is None:
                task.accepted_at = task.completed_at
        await db.flush()

        await WorkflowService._audit(
            db, instance, f"task_{decision}", completed_by_id,
            {"task_id": task.id, "step": step.step_name if step else None,
             "notes": notes})
        if fallback is not None:
            change = await WorkflowService._task_change(db, instance)
            line = (f"4-eyes fallback: {fallback['name']} reviews, "
                    f"{fallback['department_name']} has no second member")
            await WorkflowService._audit(
                db, instance, "four_eyes_fallback", completed_by_id,
                {"task_id": task.id, "line": line})
            if change is not None:
                from app.services.change_service import ChangeService
                await ChangeService.append_changelog(
                    db, change, "four_eyes_fallback", line, completed_by_id,
                    new_value={"task_id": task.id,
                               "step": step.step_name if step else None})

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

        # Spec §16 P1-2: a change's later routing stages (PM's summation,
        # Sales' customer activities) stay dormant while the change is in
        # assessment. Stage 1 completing there only earns the hop to costing;
        # the hop itself wakes the next stage (ChangeService.transition).
        # Otherwise PM and Sales get assessment tasks nobody owes, and a
        # department's bucket rebinds from its submitted row to a later one.
        if instance.change_id is not None:
            from app.models.change import ChangeRequest
            change_status = (await db.execute(
                select(ChangeRequest.status).where(
                    ChangeRequest.id == instance.change_id))).scalar_one_or_none()
            if change_status == "in_assessment":
                return instance

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
    async def effective_department_ids(db: AsyncSession, actor) -> list[int]:
        """The departments a permission check must see. While a real admin is
        acting as a department (X-Acts-As-Department), that is the ONLY one —
        the whole point of the switch is that their real memberships and the
        admin bypass step aside (spec D2)."""
        if getattr(actor, "acts_as_department_id", None) is not None:
            return [actor.acts_as_department_id]
        return await WorkflowService.get_user_department_ids(db, actor.id)

    @staticmethod
    async def actor_in_department(db: AsyncSession, actor,
                                  department_id: int) -> bool:
        """Membership check that honours acts-as. Use this wherever an actor
        object is in hand; _is_department_member stays for id-only call
        sites."""
        return department_id in await WorkflowService.effective_department_ids(db, actor)

    @staticmethod
    async def _is_department_member(db: AsyncSession, user_id: int,
                                    department_id: int) -> bool:
        from app.models.workflow import Department, UserDepartment
        row = (await db.execute(
            select(UserDepartment)
            .join(Department, Department.id == UserDepartment.department_id)
            .where(
                UserDepartment.user_id == user_id,
                UserDepartment.department_id == department_id,
                Department.is_active.is_(True)).limit(1)
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
        if user.effective_role != "admin" and not await WorkflowService.actor_in_department(
                db, user, task.department_id):
            raise TaskAcceptForbidden("Only members of the task's department may accept it")
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
        from app.services.change_people import holds_lead
        task = await WorkflowService._load_open_task(db, task_id)
        allowed = actor.effective_role == "admin" or await WorkflowService.actor_in_department(
                db, actor, task.department_id)
        if not allowed:
            if task.instance.change_id is not None:
                # Change-scoped: authorize against the change lead directly;
                # D2b: Project Management can always reassign a change's task.
                change = await db.get(ChangeRequest, task.instance.change_id)
                from app.services.meeting_service import MeetingService
                allowed = change is not None and (
                    holds_lead(change, actor)
                    or await MeetingService.user_is_pm_member(db, actor))
            elif task.instance.part_revision_id is not None:
                rev = await db.get(PartRevision, task.instance.part_revision_id)
                if rev is not None and rev.originating_change_id is not None:
                    change = await db.get(ChangeRequest, rev.originating_change_id)
                    allowed = change is not None and holds_lead(change, actor)
        if not allowed:
            raise TaskAssignForbidden(
                "Only an admin, the change lead, Project Management or a member "
                "of the task's department may assign it")
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
        from app.services.change_people import holds_lead
        task = await WorkflowService._load_open_task(db, task_id)
        allowed = actor.effective_role == "admin" or task.instance.started_by == actor.id
        if not allowed:
            if task.instance.change_id is not None:
                # Change-scoped: authorize against the change lead directly;
                # D2b: Project Management can always reassign a change's task.
                change = await db.get(ChangeRequest, task.instance.change_id)
                from app.services.meeting_service import MeetingService
                allowed = change is not None and (
                    holds_lead(change, actor)
                    or await MeetingService.user_is_pm_member(db, actor))
            elif task.instance.part_revision_id is not None:
                rev = await db.get(PartRevision, task.instance.part_revision_id)
                if rev is not None and rev.originating_change_id is not None:
                    change = await db.get(ChangeRequest, rev.originating_change_id)
                    allowed = change is not None and holds_lead(change, actor)
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
        """Active department ids the user belongs to. A deactivated
        department grants nothing: every permission check reads this."""
        from app.models.workflow import Department, UserDepartment

        result = await db.execute(
            select(UserDepartment.department_id)
            .join(Department, Department.id == UserDepartment.department_id)
            .where(UserDepartment.user_id == user_id, Department.is_active.is_(True))
        )
        return [d for (d,) in result.all()]

    # ------------------------------------------------------------------
    # Click-through R38 (R5, R18): a revision check workflow step owed by a
    # department with no real member on the change is no dead end. The
    # change's coordinator (change_people.coordinator: the lead who can
    # act, else a Project Management member) acts for it, as on the release
    # checklist (C7 fallback).
    # ------------------------------------------------------------------
    @staticmethod
    async def coordinated_change(db: AsyncSession, task: WfInstanceTask):
        """The open change whose coordinator acts for this task, or None: a
        revision-scoped instance whose revision an open change created, and
        a task department nobody real belongs to on that change."""
        from app.models.change import ChangeRequest, TERMINAL_STATUSES
        from app.services.change_people import staffed_department_ids
        inst = await db.get(WfInstance, task.instance_id)
        if inst is None or inst.change_id is not None or inst.part_revision_id is None:
            return None
        rev = await db.get(PartRevision, inst.part_revision_id)
        if rev is None or rev.originating_change_id is None:
            return None
        change = await db.get(ChangeRequest, rev.originating_change_id)
        if change is None or change.status in TERMINAL_STATUSES:
            return None
        if task.department_id in await staffed_department_ids(db, change, [task.department_id]):
            return None
        return change

    @staticmethod
    async def coordinates_task(db: AsyncSession, task: WfInstanceTask, user) -> bool:
        change = await WorkflowService.coordinated_change(db, task)
        if change is None:
            return False
        from app.services.change_people import coordinates
        return await coordinates(db, change, user)

    # ------------------------------------------------------------------
    # F1 2026-10-26, DECIDED BY CLAUDE (Christoph confirms): a 4-eyes step
    # (Design review) whose department has no second active member (prod:
    # Development = Christoph alone) is no dead end. The fallback reviewer
    # is the project team's Tool Engineer responsible, else its named
    # backup, else the change lead; never whoever did the previous stage.
    # ------------------------------------------------------------------
    FOUR_EYES_FALLBACK_DEPARTMENT = "Tool Engineer"

    @staticmethod
    async def _task_change(db: AsyncSession, instance: WfInstance):
        """The change that runs this instance: its engine change, or the
        change that created the instance's revision; None otherwise."""
        from app.models.change import ChangeRequest
        if instance.change_id is not None:
            return await db.get(ChangeRequest, instance.change_id)
        if instance.part_revision_id is not None:
            rev = await db.get(PartRevision, instance.part_revision_id)
            if rev is not None and rev.originating_change_id is not None:
                return await db.get(ChangeRequest, rev.originating_change_id)
        return None

    @staticmethod
    async def four_eyes_fallback(db: AsyncSession, task: WfInstanceTask) -> dict | None:
        """{user_id, name, department_name} of who reviews this open 4-eyes
        task for its department, or None (no 4-eyes step, or the department
        has a member besides the previous stage's doers)."""
        from app.models.entities import User
        from app.models.workflow import Department, UserDepartment
        from app.services.hub_departments import member_clause
        from app.services.project_team_service import _pair
        if task.status != "active" or not task.is_actionable:
            return None
        step = task.step if "step" in task.__dict__ else (
            await db.get(WfStep, task.step_id) if task.step_id else None)
        if step is None or not step.four_eyes:
            return None
        prev = {u for u in (await db.execute(
            select(WfInstanceTask.completed_by).where(
                WfInstanceTask.instance_id == task.instance_id,
                WfInstanceTask.stage_order == task.stage_order - 1,
                WfInstanceTask.status.in_(("approved", "waived")))
        )).scalars().all() if u is not None}
        members = set((await db.execute(
            select(UserDepartment.user_id)
            .join(User, User.id == UserDepartment.user_id)
            .join(Department, Department.id == UserDepartment.department_id)
            .where(UserDepartment.department_id == task.department_id,
                   User.is_active.is_(True), Department.is_active.is_(True),
                   member_clause()))).scalars().all())
        if members - prev:
            return None
        instance = await db.get(WfInstance, task.instance_id)
        change = await WorkflowService._task_change(db, instance)
        project_id = change.project_id if change is not None else None
        if project_id is None and instance.part_revision_id is not None:
            part, _ = await WorkflowService._instance_part_context(db, instance)
            project_id = part.project_id
        dept = await db.get(Department, task.department_id)
        te_id = (await db.execute(select(Department.id).where(
            Department.name == WorkflowService.FOUR_EYES_FALLBACK_DEPARTMENT,
            Department.is_active.is_(True)))).scalar_one_or_none()
        resp, backup = await _pair(db, project_id, te_id)
        candidates = [resp, backup]
        if change is not None and change.lead_id is not None:
            lead = await db.get(User, change.lead_id)
            if lead is not None and lead.is_active:
                candidates.append((lead.id, lead.full_name or lead.username))
        for c in candidates:
            if c is not None and c[0] not in prev:
                return {"user_id": c[0], "name": c[1],
                        "department_name": dept.name if dept else "The department"}
        return None

    @staticmethod
    async def get_four_eyes_fallback_tasks(db: AsyncSession, user) -> list[dict]:
        """The open 4-eyes revision steps this user reviews as the fallback
        (four_eyes_fallback), shaped like get_my_tasks rows."""
        from app.services.change_people import is_acting
        if user is None or is_acting(user):
            return []
        q = (select(WfInstanceTask)
             .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
             .join(WfStep, WfStep.id == WfInstanceTask.step_id)
             .where(WfInstanceTask.status == "active",
                    WfInstanceTask.is_actionable.is_(True),
                    WfStep.four_eyes.is_(True),
                    WfInstance.change_id.is_(None),
                    WfInstance.part_revision_id.is_not(None),
                    WfInstance.status == "active")
             .options(selectinload(WfInstanceTask.instance)
                      .selectinload(WfInstance.part_revision)
                      .selectinload(PartRevision.part),
                      selectinload(WfInstanceTask.step).selectinload(WfStep.stage),
                      selectinload(WfInstanceTask.department)))
        from app.services.project_team_service import TeamRoles
        roles = TeamRoles(db, user.id)
        out = []
        for t in (await db.execute(q)).scalars().all():
            fb = await WorkflowService.four_eyes_fallback(db, t)
            if fb is None or fb["user_id"] != user.id:
                continue
            row = await WorkflowService._my_task_row(t, roles, user.id)
            row.update({"coordinated": True, "role": "main", "main_name": None,
                        "hint": (f"4-eyes fallback: you review, "
                                 f"{fb['department_name']} has no second member")})
            out.append(row)
        return out

    @staticmethod
    async def task_rights(db: AsyncSession, instance: WfInstance, user) -> dict:
        """task id -> {can_act, coordinator_hint} for the open actionable
        tasks of this instance (the backend rule of complete_task)."""
        from app.models.workflow import Department
        open_tasks = [t for t in instance.tasks
                      if t.status == "active" and t.is_actionable]
        if not open_tasks or user is None:
            return {}
        admin = user.effective_role == "admin"
        mine = set(await WorkflowService.effective_department_ids(db, user))
        out = {}
        for t in open_tasks:
            change = await WorkflowService.coordinated_change(db, t)
            hint = None
            if change is not None:
                from app.services.change_people import coordinator_name, no_member_words
                dept = await db.get(Department, t.department_id)
                hint = no_member_words(dept.name if dept else None,
                                       await coordinator_name(db, change))
            can = admin or t.department_id in mine or (
                change is not None and await WorkflowService.coordinates_task(db, t, user))
            fb = await WorkflowService.four_eyes_fallback(db, t)
            if fb is not None:
                hint = (f"4-eyes fallback: {fb['name']} reviews, "
                        f"{fb['department_name']} has no second member")
                if t.department_id not in mine:
                    # the fallback reviewer acts; a department member who
                    # did the previous stage never does (the 4-eyes rule)
                    can = can or fb["user_id"] == user.id
            out[t.id] = {"can_act": bool(can), "coordinator_hint": hint}
        return out

    @staticmethod
    async def get_coordinated_tasks(db: AsyncSession, user) -> list[dict]:
        """The open check workflow steps this user coordinates (a member-less
        department on a change they lead, or as Project Management where no
        lead can act), shaped like get_my_tasks rows."""
        from app.models.change import ChangeRequest, TERMINAL_STATUSES
        from app.models.workflow import Department
        from app.services.change_people import (
            coordinates, coordinator_name, is_acting, no_member_words,
            staffed_department_ids)
        from app.services.meeting_service import MeetingService
        if user is None or is_acting(user) or user.effective_role == "admin":
            return []
        is_pm = await MeetingService.user_is_pm_member(db, user)
        mine = set(await WorkflowService.effective_department_ids(db, user))
        q = (select(WfInstanceTask, ChangeRequest)
             .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
             .join(PartRevision, PartRevision.id == WfInstance.part_revision_id)
             .join(ChangeRequest, ChangeRequest.id == PartRevision.originating_change_id)
             .where(WfInstanceTask.status == "active",
                    WfInstanceTask.is_actionable.is_(True),
                    WfInstance.change_id.is_(None),
                    WfInstance.status == "active",
                    ChangeRequest.status.not_in(TERMINAL_STATUSES))
             .options(selectinload(WfInstanceTask.instance)
                      .selectinload(WfInstance.part_revision)
                      .selectinload(PartRevision.part),
                      selectinload(WfInstanceTask.step).selectinload(WfStep.stage),
                      selectinload(WfInstanceTask.department)))
        if mine:
            q = q.where(WfInstanceTask.department_id.not_in(mine))
        if not is_pm:
            q = q.where(ChangeRequest.lead_id == user.id)
        rows = (await db.execute(q)).all()
        if not rows:
            return []
        by_change: dict = {}
        for t, change in rows:
            by_change.setdefault(change.id, (change, []))[1].append(t)
        from app.services.project_team_service import TeamRoles
        roles = TeamRoles(db, user.id)
        out = []
        for change, tasks in by_change.values():
            if not await coordinates(db, change, user, is_pm_member=is_pm):
                continue
            staffed = await staffed_department_ids(
                db, change, [t.department_id for t in tasks])
            who = None
            for t in tasks:
                if t.department_id in staffed:
                    continue
                who = who or await coordinator_name(db, change)
                row = await WorkflowService._my_task_row(t, roles, user.id)
                row.update({"coordinated": True, "role": "main", "main_name": None,
                            "change_id": change.id, "change_number": change.change_number,
                            "hint": no_member_words(
                                t.department.name if t.department else None, who)})
                out.append(row)
        return out

    @staticmethod
    async def _my_task_row(t: WfInstanceTask, roles, user_id: int) -> dict:
        instance = t.instance
        revision = instance.part_revision
        part = revision.part
        stage = t.step.stage if t.step else None
        # A task the viewer took is theirs, backup or not.
        role, main_name = await roles.role(part.project_id, t.department_id,
                                           owned=t.owner_id == user_id)
        # D2b: an overdue task goes to the project's named backup too
        covering = (await roles.covering(part.project_id, t.department_id)
                    if role == "backup" and t.overdue else None)
        if covering is not None:
            role, main_name = "main", None
        return {
            **({"covering_for": covering} if covering is not None else {}),
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
            # Project team (spec 2026-09-25): "main" (counts) or "backup"
            # (visible, actionable, not counted); main_name only set when
            # this task's role is "backup".
            "role": role,
            "main_name": main_name if role == "backup" else None,
        }

    @staticmethod
    async def add_change_refs(db: AsyncSession, rows: list[dict]) -> list[dict]:
        """F4 (R18): a check workflow step of a revision an open change
        created names that change (change_id, change_number, change_title),
        so My Tasks reads "CR-2026-0013 Design review", not a bare part."""
        from app.models.change import ChangeRequest
        rev_ids = {r["revision_id"] for r in rows
                   if r.get("revision_id") is not None and not r.get("change_number")}
        if not rev_ids:
            return rows
        found = {rid: (cid, num, title) for rid, cid, num, title in (await db.execute(
            select(PartRevision.id, ChangeRequest.id, ChangeRequest.change_number,
                   ChangeRequest.title)
            .join(ChangeRequest, ChangeRequest.id == PartRevision.originating_change_id)
            .where(PartRevision.id.in_(rev_ids)))).all()}
        for r in rows:
            hit = found.get(r.get("revision_id"))
            if hit is not None and not r.get("change_number"):
                r["change_id"], r["change_number"], r["change_title"] = hit
        return rows

    @staticmethod
    def sort_my_tasks(results: list[dict]) -> list[dict]:
        results.sort(key=lambda d: (
            not d["mine"], not d["overdue"],
            d["due_date"] is None, d["due_date"] or datetime.max, d["task_id"]))
        return results

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
                # A dead instance owes nobody anything: without this, tasks of
                # a canceled workflow (e.g. its change was cancelled) sit in
                # the list forever — the reference never gets killed.
                WfInstance.status == "active",
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

        # Project team (spec 2026-09-25): a task's department may have a
        # responsible on the task's project -- everyone else active in the
        # department is a backup there. TeamRoles caches the responsible per
        # (project, department), the same resolver every task list uses.
        from app.services.project_team_service import TeamRoles
        roles = TeamRoles(db, user_id)

        results = [await WorkflowService._my_task_row(t, roles, user_id) for t in tasks]
        return WorkflowService.sort_my_tasks(results)

    @staticmethod
    async def owning_open_change(db: AsyncSession, instance_id: int) -> str | None:
        """The change number when this instance is run by a change: its
        engine workflow, or the approval of a revision the change created
        while that change is still open. None otherwise (or not found)."""
        from app.models.change import ChangeRequest, TERMINAL_STATUSES
        instance = await db.get(WfInstance, instance_id)
        if instance is None:
            return None
        if instance.change_id is not None:
            change = await db.get(ChangeRequest, instance.change_id)
            return change.change_number if change is not None else str(instance.change_id)
        if instance.part_revision_id is not None:
            rev = await db.get(PartRevision, instance.part_revision_id)
            if rev is not None and rev.originating_change_id is not None:
                change = await db.get(ChangeRequest, rev.originating_change_id)
                if change is not None and change.status not in TERMINAL_STATUSES:
                    return change.change_number
        return None

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
        # The instance's open tasks die with it — waived, not deleted, so the
        # record shows they existed and were never done. Leaving them 'active'
        # kept dead work on task lists indefinitely.
        for task in (await db.execute(
                select(WfInstanceTask).where(
                    WfInstanceTask.instance_id == instance.id,
                    WfInstanceTask.status.in_(("pending", "active", "noted"))
                ))).scalars():
            task.status = "waived"
        await db.flush()
        return instance
