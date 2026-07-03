# ECM Phase E Implementation Plan — Engine Unification, Sales Deadline, Notifications, Reporting

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the two parallel change-execution engines into one (workflow engine drives the assessment phase; `ChangeAssessment` becomes a task payload), add a Sales deadline with at-risk tracking, wire in-app notification emission + deep links, and ship a KPI dashboard — then close the debt (org scoping, tsc baseline) and merge to main.

**Architecture:** `WfInstance` gains a nullable `change_id` (subject = change XOR part revision). Change submit spawns an "ECM Bewertung" instance; `ChangeAssessment` rows link 1:1 to `WfInstanceTask` and keep only D1 payload (verdict, costs, cost lines). All advancement/RASIC/due-date/escalation logic lives in `workflow_service`; `change_routing_service` keeps only standard resolution, deviation governance, and template promotion. API response shapes are preserved via read-through properties so the frontend barely changes. Deadline, notifications, and reports build on the unified model.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic (backend), React 18 + TS + TanStack Query 5 + Tailwind dark-slate + vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-07-03-ecm-phase-e-design.md`

## Global Constraints

- Backend tests: run from `backend/` with `python3 -m pytest` (baseline **190 tests pass**, 31 files). Test DB is built from models via `Base.metadata.create_all` (conftest), NOT from migrations — data-backfill logic must live in a service function so it is testable.
- Frontend tests: `cd frontend && npx vitest run` (baseline **55 tests pass**, 13 files). vitest has `globals: false` — always `import { describe, it, expect, vi } from 'vitest'`.
- Type-check: `cd frontend && npx tsc --noEmit` has **exactly 21 pre-existing errors** (enumerated in Task 16). Tasks 1–15 must add ZERO new errors; Task 16 takes the count to 0.
- SQLAlchemy 2.0 async style (`Mapped`/`mapped_column`). New models/columns registered where applicable in `backend/app/models/__init__.py`.
- Migrations: idempotent inspect-guard pattern (see `024_ownership_due_dates.py`). **SQLite cannot ADD COLUMN with FK** — new FK columns ship as plain `sa.Integer()` in the migration; the ORM model carries the `ForeignKey`. Column NOT NULL changes need `op.batch_alter_table`.
- Audit: change-level events go through `ChangeService.append_changelog(session, change, action, description, performed_by, *, field_name=, old_value=, new_value=, notes=)` (which calls `AuditService.record` with `correlation_id=change.change_number`). Workflow-instance events go through `WorkflowService._audit`.
- Frontend labels: DE/EN via `src/i18n/cmLabels.ts` (`cmLabels` map + `t(key, lang)`); status chips via `STATUS_PILL` from `src/lib/changeStatus.ts`; toasts via `sonner`.
- Query keys in use: `['change', id]`, `['change-routing', id]`, `['change-gates', id]`, `['change-my-tasks']`, `['workflow', ...]`, `['notifications']`, `['notifications-unread']` — reuse for invalidation.
- **Model tiering:** Tasks 1–6 opus (engine semantics, migration); Tasks 7–15 sonnet; Task 16 haiku; Task 17 opus (review/verification). Never trade correctness for cost.

## Stream order

Tasks 1–8 = Stream 1 (unification). Tasks 9–10 = Stream 2 (deadline). Tasks 11–12 = Stream 3 (notifications). Tasks 13–15 = Stream 4 + org scoping (reports). Task 16 = tsc debt. Task 17 = verification + merge.

---

### Task 1: Schema — change-scoped instances + assessment↔task link (migration 027 + models)

**Files:**
- Create: `backend/alembic/versions/027_change_scoped_instances.py`
- Modify: `backend/app/models/workflow.py` (WfInstance ~L148-173, WfInstanceTask ~L176-213)
- Modify: `backend/app/models/change.py` (ChangeAssessment ~L156-208)
- Test: `backend/tests/test_change_scoped_instances.py` (new)

**Interfaces:**
- Produces: `WfInstance.change_id: int|None` (FK change_requests), `WfInstance.part_revision_id` now nullable, `WfInstanceTask.step_id` now nullable, `ChangeAssessment.wf_instance_task_id: int|None` (unique FK wf_instance_tasks) + `ChangeAssessment.task` relationship + read-through properties `effective_status`, `effective_owner_id`, `effective_owner_name`, `effective_due_date`, `effective_accepted_at`, `effective_overdue`.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_change_scoped_instances.py
import pytest
from datetime import datetime, timedelta
from app.models.workflow import WfInstance, WfInstanceTask, WfTemplate, Department
from app.models.change import ChangeRequest, ChangeAssessment


async def _mk_template(session):
    t = WfTemplate(name="ECM Bewertung Test", flow_type="change", created_by=1)
    session.add(t)
    await session.flush()
    return t


@pytest.mark.asyncio
async def test_instance_can_be_change_scoped(session_factory, seed):
    async with session_factory() as session:
        t = await _mk_template(session)
        chg = ChangeRequest(change_number="C-E-001", title="x", reason="y",
                            change_type="physical_part", created_by=seed["admin"].id)
        session.add(chg)
        await session.flush()
        inst = WfInstance(template_id=t.id, change_id=chg.id, part_revision_id=None,
                          status="active", current_stage_order=1,
                          started_by=seed["admin"].id)
        session.add(inst)
        await session.flush()
        assert inst.change_id == chg.id and inst.part_revision_id is None


@pytest.mark.asyncio
async def test_assessment_links_to_task_and_reads_through(session_factory, seed):
    async with session_factory() as session:
        t = await _mk_template(session)
        chg = ChangeRequest(change_number="C-E-002", title="x", reason="y",
                            change_type="physical_part", created_by=seed["admin"].id)
        dept = Department(name="R&D-E", flow_type="change")
        session.add_all([chg, dept])
        await session.flush()
        inst = WfInstance(template_id=t.id, change_id=chg.id, status="active",
                          current_stage_order=1, started_by=seed["admin"].id)
        session.add(inst)
        await session.flush()
        task = WfInstanceTask(instance_id=inst.id, stage_order=1, step_id=None,
                              department_id=dept.id, rasic_letter="R",
                              status="approved", is_actionable=True,
                              owner_id=seed["admin"].id,
                              due_date=datetime.utcnow() + timedelta(days=7))
        session.add(task)
        await session.flush()
        a = ChangeAssessment(change_id=chg.id, department_id=dept.id,
                             stage_order=1, rasic_letter="R", status="pending",
                             wf_instance_task_id=task.id)
        session.add(a)
        await session.flush()
        await session.refresh(a)
        # R/A execution state reads through from the task
        assert a.effective_status == "submitted"        # approved -> submitted
        assert a.effective_owner_id == seed["admin"].id
        assert a.effective_due_date == task.due_date


@pytest.mark.asyncio
async def test_sc_assessment_derives_status_without_task_write(session_factory, seed):
    async with session_factory() as session:
        chg = ChangeRequest(change_number="C-E-003", title="x", reason="y",
                            change_type="physical_part", created_by=seed["admin"].id)
        dept = Department(name="Log-E", flow_type="change")
        session.add_all([chg, dept])
        await session.flush()
        a = ChangeAssessment(change_id=chg.id, department_id=dept.id,
                             stage_order=2, rasic_letter="S", status="pending")
        session.add(a)
        await session.flush()
        await session.refresh(a)
        assert a.effective_status == "pending"          # no task yet -> own column
        a.submitted_at = datetime.utcnow()
        assert a.effective_status == "submitted"        # payload submitted
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_change_scoped_instances.py -v`
Expected: FAIL — `TypeError: 'change_id' is an invalid keyword argument for WfInstance` (and/or NOT NULL violations for `part_revision_id`).

- [ ] **Step 3: Model changes**

In `backend/app/models/workflow.py`, `WfInstance`:

```python
    part_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("part_revisions.id"), nullable=True)
    change_id: Mapped[int | None] = mapped_column(
        ForeignKey("change_requests.id"), nullable=True, index=True)
```

and relax the relationship (`part_revision` may be None now):

```python
    part_revision: Mapped["PartRevision | None"] = relationship(
        foreign_keys="[WfInstance.part_revision_id]",
    )
```

In `WfInstanceTask`:

```python
    step_id: Mapped[int | None] = mapped_column(ForeignKey("wf_steps.id"), nullable=True)
    step: Mapped["WfStep | None"] = relationship()
```

In `backend/app/models/change.py`, `ChangeAssessment` — add column, relationship, and read-through properties (place after the `overdue` property; `BLOCKING_LETTERS` is already imported in this module):

```python
    wf_instance_task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("wf_instance_tasks.id"), nullable=True, unique=True, index=True)
    task: Mapped["WfInstanceTask | None"] = relationship(
        "WfInstanceTask", foreign_keys=[wf_instance_task_id], lazy="selectin")

_TASK_TO_ASSESSMENT_STATUS = {
    "pending": "pending", "active": "active", "approved": "submitted",
    "waived": "waived", "rejected": "submitted", "noted": "active",
}
```

Properties on `ChangeAssessment` (task is source of truth for R/A once linked; S/C/unlinked rows derive from their own columns):

```python
    @property
    def effective_status(self) -> str:
        if self.rasic_letter in BLOCKING_LETTERS and self.task is not None:
            return _TASK_TO_ASSESSMENT_STATUS.get(self.task.status, self.status)
        if self.rasic_letter not in BLOCKING_LETTERS:
            if self.submitted_at is not None:
                return "submitted"
            if self.task is not None:      # its stage has started
                return "active"
        return self.status

    @property
    def effective_owner_id(self):
        if self.rasic_letter in BLOCKING_LETTERS and self.task is not None:
            return self.task.owner_id
        return self.owner_id

    @property
    def effective_owner_name(self):
        if self.rasic_letter in BLOCKING_LETTERS and self.task is not None:
            return self.task.owner_name
        return self.owner.full_name if getattr(self, "owner", None) else None

    @property
    def effective_due_date(self):
        if self.rasic_letter in BLOCKING_LETTERS and self.task is not None:
            return self.task.due_date
        return self.due_date

    @property
    def effective_accepted_at(self):
        if self.rasic_letter in BLOCKING_LETTERS and self.task is not None:
            return self.task.accepted_at
        return self.accepted_at

    @property
    def effective_overdue(self) -> bool:
        if self.rasic_letter in BLOCKING_LETTERS and self.task is not None:
            return self.task.overdue
        return self.overdue
```

Note: if `ChangeAssessment` has no `owner` relationship, source `effective_owner_name` the way the existing `AssessmentResponse` does today (check how `owner_name` is currently populated and mirror it for the fallback branch).

- [ ] **Step 4: Migration 027**

```python
# backend/alembic/versions/027_change_scoped_instances.py
"""027: change-scoped wf instances + assessment->task link"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    cols = {c["name"] for c in insp.get_columns("wf_instances")}
    if "change_id" not in cols:
        # FK lives in the ORM only (SQLite cannot ADD COLUMN with FK)
        op.add_column("wf_instances", sa.Column("change_id", sa.Integer(), nullable=True))
        op.create_index("ix_wf_instances_change_id", "wf_instances", ["change_id"])

    prev = next(c for c in inspect(bind).get_columns("wf_instances")
                if c["name"] == "part_revision_id")
    if not prev["nullable"]:
        with op.batch_alter_table("wf_instances") as batch:
            batch.alter_column("part_revision_id", existing_type=sa.Integer(),
                               nullable=True)

    step = next(c for c in inspect(bind).get_columns("wf_instance_tasks")
                if c["name"] == "step_id")
    if not step["nullable"]:
        with op.batch_alter_table("wf_instance_tasks") as batch:
            batch.alter_column("step_id", existing_type=sa.Integer(), nullable=True)

    cols = {c["name"] for c in inspect(bind).get_columns("change_assessments")}
    if "wf_instance_task_id" not in cols:
        op.add_column("change_assessments",
                      sa.Column("wf_instance_task_id", sa.Integer(), nullable=True))
        idx = {ix["name"] for ix in inspect(bind).get_indexes("change_assessments")}
        if "ix_change_assessments_wf_instance_task_id" not in idx:
            op.create_index("ix_change_assessments_wf_instance_task_id",
                            "change_assessments", ["wf_instance_task_id"], unique=True)


def downgrade() -> None:
    pass  # forward-only, consistent with 023-026
```

- [ ] **Step 5: Run tests, verify migration on the dev DB, commit**

Run: `cd backend && python3 -m pytest tests/test_change_scoped_instances.py -v` → 3 PASS.
Run: `cd backend && python3 -m pytest` → full suite still green (190 + 3).
Run: `cd backend && cp plm.db /tmp/plm.db.bak && python3 -m alembic upgrade head && python3 -m alembic current` → `027 (head)`; run it twice to prove idempotence.

```bash
git add backend/alembic/versions/027_change_scoped_instances.py backend/app/models/workflow.py backend/app/models/change.py backend/tests/test_change_scoped_instances.py
git commit -m "feat(unification): change-scoped WfInstance + assessment-task link (migration 027)"
```

---

### Task 2: Change-aware plumbing in the workflow engine

Every place that assumes `instance.part_revision_id` is non-null must handle change-scoped instances. Sites (from exploration): `workflow_service.py` L100 (`_audit`), L157 (`_instance_part_context`), L193-197 (CAD-evidence gate in `complete_task`), L369-372 (`set_task_due_date` authz); `change_service.py` L286-306 (`lead_escalations` wf_task branch); `app/api/v1/workflows/workflow_instances.py` serializers (`_serialize_instance`); `get_my_tasks` L413-474.

**Files:**
- Modify: `backend/app/services/workflow_service.py`
- Modify: `backend/app/services/change_service.py:286-306`
- Modify: `backend/app/api/v1/workflows/workflow_instances.py:40-84`
- Test: `backend/tests/test_change_scoped_instances.py` (extend)

**Interfaces:**
- Produces: `WorkflowService.start_change_workflow(db, change_id: int, template_id: int, started_by_id: int) -> WfInstance`; `WorkflowService.get_my_tasks` excludes change-scoped instances (`WfInstance.change_id.is_(None)`) — change-scoped tasks surface only via `/changes/my-tasks` (Task 7).
- Consumes: Task 1 columns.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_change_scoped_instances.py`:

```python
from app.services.workflow_service import WorkflowService
from app.services.wf_seed_service import seed_change_workflows


@pytest.mark.asyncio
async def test_start_change_workflow_creates_stage1_tasks(session_factory, seed):
    async with session_factory() as session:
        await seed_change_workflows(session)   # seeds "ECM Bewertung" + departments
        from app.models.workflow import WfTemplate
        from sqlalchemy import select
        tmpl = (await session.execute(select(WfTemplate).where(
            WfTemplate.name == "ECM Bewertung"))).scalar_one()
        chg = ChangeRequest(change_number="C-E-010", title="x", reason="y",
                            change_type="physical_part", created_by=seed["admin"].id)
        session.add(chg)
        await session.flush()
        inst = await WorkflowService.start_change_workflow(
            session, chg.id, tmpl.id, seed["admin"].id)
        assert inst.change_id == chg.id and inst.part_revision_id is None
        assert inst.status == "active" and inst.current_stage_order == 1
        assert any(t.stage_order == 1 for t in inst.tasks)


@pytest.mark.asyncio
async def test_change_scoped_instance_skips_cad_evidence_gate(session_factory, seed):
    # completing the last stage-1 R task on a change-scoped instance must not
    # raise the 3D-evidence error (that rule applies to ECN revisions only)
    async with session_factory() as session:
        await seed_change_workflows(session)
        # ... start instance as above, grant admin membership in a stage-1 dept,
        # then WorkflowService.complete_task on that dept's R task:
        # expect no "3D evidence" ValueError; stage advances or instance completes.
```

(Write the second test fully: create the instance, insert a `UserDepartment` row for `seed["admin"]` in the first task's department, call `complete_task(session, task.id, "approved", "ok", seed["admin"].id)`, assert no exception and `task.status == "approved"`.)

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_change_scoped_instances.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'start_change_workflow'`.

- [ ] **Step 3: Implement**

`start_change_workflow` mirrors `start_workflow` (L18-74) with the change-scoped guard:

```python
    @staticmethod
    async def start_change_workflow(db: AsyncSession, change_id: int,
                                    template_id: int, started_by_id: int) -> WfInstance:
        existing = (await db.execute(
            select(WfInstance).where(
                WfInstance.change_id == change_id,
                WfInstance.status == "active"))).scalar_one_or_none()
        if existing is not None:
            return existing
        template = await db.get(WfTemplate, template_id)   # same load pattern as start_workflow
        # ... identical stage loading as start_workflow ...
        instance = WfInstance(template_id=template_id, change_id=change_id,
                              part_revision_id=None, status="active",
                              current_stage_order=1, started_by=started_by_id,
                              started_at=datetime.utcnow())
        db.add(instance)
        await db.flush()
        await WorkflowService._create_stage_tasks(db, instance, first_stage)
        await WorkflowService._audit(db, instance, "wf_started", started_by_id)
        return instance
```

Reuse `start_workflow`'s exact template/stage loading; factor shared lines into a private helper if the duplication exceeds ~15 lines (DRY), otherwise inline.

Then make the four read sites change-aware:

`_audit` (L95-106) — resolve correlation from the change directly when change-scoped:

```python
        correlation = None
        if instance.change_id is not None:
            chg = await db.get(ChangeRequest, instance.change_id)
            correlation = chg.change_number if chg else None
        elif instance.part_revision_id is not None:
            # existing revision -> originating change path unchanged
```

`_instance_part_context` (L150-160) — return a change context when `part_revision_id is None`: load the change and return its `change_number`/`title` in the same tuple/dict shape callers expect.

`complete_task` CAD gate (L193-197) — wrap in `if task.instance.part_revision_id is not None:` so change-scoped instances skip the 3D-evidence rule.

`set_task_due_date` authz (L369-372) — when `instance.change_id` is set, load the change and authorize against `change.lead_id` directly (same rule, shorter path).

`get_my_tasks` (L413-474) — add `.where(WfInstance.change_id.is_(None))` to the task query so change-scoped tasks don't double-appear (they surface via `/changes/my-tasks`).

`lead_escalations` wf_task branch (`change_service.py` L286-306) — extend the join so change-scoped tasks roll up too: the current path joins `WfInstance -> PartRevision.originating_change_id`; add a second query (or OR-condition) for `WfInstance.change_id == ChangeRequest.id` with the same overdue/active filters, and dedupe on task id.

`_serialize_instance` / `_serialize_task` (`workflow_instances.py` L40-84) — tolerate `part_revision_id is None` and `step_id is None` (emit `part_revision_id: None`, derive names defensively).

- [ ] **Step 4: Run tests**

Run: `cd backend && python3 -m pytest tests/test_change_scoped_instances.py tests/test_workflows.py tests/test_escalations.py tests/test_task_ownership.py -v`
Expected: all PASS. Then full suite: `python3 -m pytest` → green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/workflow_service.py backend/app/services/change_service.py backend/app/api/v1/workflows/workflow_instances.py backend/tests/test_change_scoped_instances.py
git commit -m "feat(unification): change-aware workflow engine + start_change_workflow"
```

---

### Task 3: Submit spawns the assessment instance; payload rows link lazily

`build_routing` (routing service L71-116) keeps resolving + snapshotting the standard and creating `ChangeAssessment` payload rows, but now also spawns the change-scoped instance. Tasks are created stage-by-stage by the engine, so assessments link lazily: when `_create_stage_tasks` creates tasks for a change-scoped instance, it links matching unlinked assessments.

**Files:**
- Modify: `backend/app/services/change_routing_service.py:71-147`
- Modify: `backend/app/services/workflow_service.py` (`_create_stage_tasks`)
- Test: `backend/tests/test_change_routing.py` (adjust), `backend/tests/test_change_scoped_instances.py` (extend)

**Interfaces:**
- Consumes: `WorkflowService.start_change_workflow` (Task 2).
- Produces: after `captured -> in_assessment`, the change has one active "ECM Bewertung" `WfInstance` whose stage-1 tasks are linked to stage-1 assessments; assessments for not-yet-started stages exist unlinked with `status="pending"`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_submit_spawns_assessment_instance_with_linked_stage1(client, admin_auth, seed):
    # create a change via API, transition captured -> in_assessment,
    # then assert via a fresh session:
    #   - one WfInstance with change_id == change.id, status active, stage 1
    #   - every stage-1 assessment has wf_instance_task_id set
    #   - stage-2+ assessments exist with wf_instance_task_id None, status pending
```

Write it concretely using the existing API test pattern from `tests/test_change_routing.py` (create change `POST /v1/changes`, transition `POST /v1/changes/{id}/transition {"to_status": "in_assessment"}`).

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_change_scoped_instances.py -k spawns -v`
Expected: FAIL — no instance with `change_id` exists.

- [ ] **Step 3: Implement**

In `build_routing`, after the existing snapshot/assessment-row creation (keep both), replace the trailing `activate_stage(...)` call with:

```python
        if routing.template_id is not None:
            await WorkflowService.start_change_workflow(
                session, change.id, routing.template_id, user_id)
```

When `routing.template_id is None` (legacy `TYPE_DISCIPLINES` fallback), resolve the seeded default instead:

```python
        else:
            tmpl_id = (await session.execute(
                select(WfTemplate.id).where(WfTemplate.name == "ECM Bewertung")
            )).scalar_one_or_none()
            if tmpl_id is not None:
                await WorkflowService.start_change_workflow(session, change.id, tmpl_id, user_id)
```

Assessment rows keep being created for all snapshot stages/letters as today, but drop the per-row `status="active"`/`due_date` writes for stage 1 — leave every new row `status="pending"` (execution state now lives on tasks; `effective_status` handles display).

In `WorkflowService._create_stage_tasks`, after tasks are flushed, link change-scoped payload rows:

```python
        if instance.change_id is not None:
            rows = (await db.execute(select(ChangeAssessment).where(
                ChangeAssessment.change_id == instance.change_id,
                ChangeAssessment.stage_order == stage.stage_order,
                ChangeAssessment.wf_instance_task_id.is_(None)))).scalars().all()
            by_key = {(t.department_id, t.rasic_letter): t for t in tasks_created}
            for a in rows:
                t = by_key.get((a.department_id, a.rasic_letter))
                if t is not None:
                    a.wf_instance_task_id = t.id
```

(`tasks_created` = the list this method already builds; import `ChangeAssessment` locally inside the method to avoid an import cycle.)

- [ ] **Step 4: Run tests**

Run: `cd backend && python3 -m pytest tests/test_change_scoped_instances.py tests/test_change_routing.py -v`
Expected: new test PASS. Some `test_change_routing.py` tests may fail on assumptions about `status="active"` on stage-1 assessment ROWS — update those assertions to `effective_status` semantics (the row is `pending`, the linked task is `active`, `effective_status == "active"`). Do not weaken tests: assert the task state explicitly.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/change_routing_service.py backend/app/services/workflow_service.py backend/tests/
git commit -m "feat(unification): submit spawns ECM Bewertung instance, lazy assessment-task linking"
```

---

### Task 4: Assessment submission through the engine; delete the parallel advancement machinery

**Files:**
- Modify: `backend/app/services/change_service.py:762-807` (`submit_assessment`)
- Modify: `backend/app/services/change_routing_service.py` — DELETE `activate_stage` (L126-147) and `maybe_advance` (L149-187); rewrite `blocking_complete` (L189-195)
- Test: `backend/tests/test_change_routing.py`, `backend/tests/test_changes.py` (adjust), extend `backend/tests/test_change_scoped_instances.py`

**Interfaces:**
- Consumes: `WorkflowService.complete_task(db, task_id, decision, notes, completed_by_id)` (existing, L162-292), `effective_status` (Task 1).
- Produces: `ChangeRoutingService.blocking_complete(session, change) -> bool` — same signature, now: all blocking-letter assessments have `effective_status in ("submitted", "waived")` and at least one exists. `maybe_advance` and `activate_stage` NO LONGER EXIST — nothing may import them.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_ra_submission_completes_task_and_engine_advances(client, admin_auth, seed):
    # change -> in_assessment; submit all stage-1 R/A assessments via
    # POST /v1/changes/{id}/assessments (grant the submitting user membership
    # in each department first — engine authz applies now).
    # Assert: linked tasks are 'approved'; instance.current_stage_order == 2;
    # stage-2 assessments now have wf_instance_task_id set.


@pytest.mark.asyncio
async def test_sc_submission_is_payload_only(client, admin_auth, seed):
    # submit an S-letter assessment: assessment.submitted_at set,
    # effective_status == "submitted", its task (if any) stays "noted",
    # stage does NOT advance because of it.


@pytest.mark.asyncio
async def test_blocking_complete_over_effective_status(session_factory, seed):
    # build change with 2 blocking assessments: one linked task 'approved',
    # one linked task 'waived' -> blocking_complete True;
    # flip one task to 'active' -> False.
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_change_scoped_instances.py -k "ra_submission or sc_submission or blocking" -v`
Expected: FAIL (tasks stay active; blocking_complete still reads `status`).

- [ ] **Step 3: Implement `submit_assessment` rework**

Keep the existing row-targeting logic (lowest-stage active/pending row for the department, bare-submit tolerance) but replace the tail. After writing the payload fields (`verdict`, `cost_impact`, `lead_time_impact_days`, `conditions`, `notes`, `responsible_id`, `submitted_at`, `submitted_by`):

```python
        if a.rasic_letter in BLOCKING_LETTERS and a.wf_instance_task_id is not None:
            from app.services.workflow_service import WorkflowService
            await WorkflowService.complete_task(
                session, a.wf_instance_task_id, "approved",
                notes or f"Assessment: {verdict}", user_id)
        else:
            a.status = "submitted"   # S/C payload-only; unlinked legacy rows too
        await session.flush()
```

Delete the `maybe_advance` import and call (old L800-801). Keep the `append_changelog(..., "assessment_submitted", ...)` exactly as is.

**Authz note:** `complete_task` enforces department membership/4-eyes where the old path did not. This is intended (uniform engine semantics — the Phase B deferred ticket wanted exactly this). Update affected tests to grant the submitting user a `UserDepartment` row; if `complete_task` exempts admins today, preserve that behavior — check `_is_department_member` (L295-303) first and mirror what workflow-task tests do.

- [ ] **Step 4: Rewrite `blocking_complete`, delete dead machinery**

```python
    @staticmethod
    async def blocking_complete(session: AsyncSession, change: ChangeRequest) -> bool:
        rows = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
        )).scalars().all()
        blocking = [a for a in rows if a.rasic_letter in BLOCKING_LETTERS]
        return bool(blocking) and all(
            a.effective_status in ("submitted", "waived") for a in blocking)
```

Delete `activate_stage` and `maybe_advance` entirely. Grep for stragglers:

Run: `cd backend && grep -rn "maybe_advance\|activate_stage" app/ tests/ --include="*.py"`
Expected: zero hits in `app/`; fix any test that still calls them (rewrite to drive the engine via `complete_task`).

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && python3 -m pytest`
Expected: green. `test_change_routing.py` (16 tests) is the churn hotspot — stage-advancement assertions must now observe `WfInstance.current_stage_order` and task statuses instead of assessment `status` flips. Preserve each test's *intent*; do not delete coverage.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ backend/tests/
git commit -m "feat(unification): submissions drive the engine; parallel advancement machinery deleted"
```

---

### Task 5: Routing deviations re-target tasks

`apply_deviation` (routing service L206-256) mutates assessment rows (`add`/`remove`/`reletter`). Each op must now also mutate the linked task so engine state stays consistent.

**Files:**
- Modify: `backend/app/services/change_routing_service.py:206-256`
- Test: `backend/tests/test_change_deviations.py` (extend; 5 existing tests)

**Interfaces:**
- Consumes: change-scoped instance (Task 3), `_TASK_TO_ASSESSMENT_STATUS` semantics.
- Produces: deviation ops keep their API contract (`POST /v1/changes/{id}/routing/deviation`, ops `add|remove|reletter`) — behavior extended to tasks.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_deviation_add_creates_task_in_running_instance(client, admin_auth, seed):
    # change in_assessment; POST deviation op=add, department X, letter R, stage 1
    # -> new ChangeAssessment linked to a NEW WfInstanceTask (status active,
    #    is_actionable True) in the change-scoped instance.

@pytest.mark.asyncio
async def test_deviation_remove_deletes_task(client, admin_auth, seed):
    # op=remove on an unsubmitted stage-1 R row -> assessment gone AND its task gone;
    # stage can then complete without it.

@pytest.mark.asyncio
async def test_deviation_reletter_updates_task(client, admin_auth, seed):
    # op=reletter R->S -> task.rasic_letter=="S", task.is_actionable False,
    # task.status=="noted"; effective_status derives S/C semantics.
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_change_deviations.py -v`
Expected: new tests FAIL (no task mutations yet).

- [ ] **Step 3: Implement**

Inside `apply_deviation`, after each existing assessment mutation, load the change-scoped instance (`select(WfInstance).where(WfInstance.change_id == change.id, WfInstance.status == "active")`). If none (legacy pre-migration change), skip task ops — assessment-only behavior remains valid for them.

- `add`: create the task when the target stage has started (`stage_order <= instance.current_stage_order`):

```python
            task = WfInstanceTask(
                instance_id=inst.id, stage_order=stage_order or inst.current_stage_order,
                step_id=await _match_step_id(session, inst.template_id, stage_order, department_id, rasic_letter),
                department_id=department_id, rasic_letter=rasic_letter,
                status="active" if rasic_letter in BLOCKING_LETTERS else "noted",
                is_actionable=rasic_letter in BLOCKING_LETTERS,
                due_date=datetime.utcnow() + timedelta(days=DEFAULT_TASK_DUE_DAYS)
                    if rasic_letter in BLOCKING_LETTERS else None)
            session.add(task)
            await session.flush()
            assessment.wf_instance_task_id = task.id
```

  For a future stage, leave the assessment unlinked — lazy linking (Task 3) picks it up when the stage starts.
- `remove`: if `existing.wf_instance_task_id`, delete that task row first, then the assessment (as today). Then re-check stage completion: removing the last open blocking task must let the stage advance — call the same stage-completion check `complete_task` uses (factor it into a small `WorkflowService._maybe_advance_stage(db, instance)` helper reused by both; this helper is extracted from `complete_task` L243-290, not new logic).
- `reletter`: update `task.rasic_letter`, recompute `is_actionable`; letter → non-blocking flips `status` to `"noted"` and clears `due_date`; non-blocking → blocking flips to `"active"` + default due date. Re-run `_maybe_advance_stage` afterwards.

`_match_step_id` helper: find the step in the instance's template whose stage matches and which has a `WfStepRasic` for (department_id, rasic_letter); fall back to the stage's first step; return `None` if the template has no steps (tasks tolerate null `step_id` since Task 1).

- [ ] **Step 4: Run tests**

Run: `cd backend && python3 -m pytest tests/test_change_deviations.py tests/test_change_routing.py -v` → PASS.
Then: `python3 -m pytest` → green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ backend/tests/test_change_deviations.py
git commit -m "feat(unification): routing deviations mutate engine tasks (add/remove/reletter)"
```

### Task 6: Backfill repair for in-flight changes (startup + testable service)

The pytest DB is built from models, so the backfill lives in a service function (like Phase B's `repair_inflight_check_workflows`) called at startup — NOT as Alembic data-migration code.

**Files:**
- Create: `backend/app/services/assessment_instance_repair.py`
- Modify: `backend/app/main.py` (~L347-351, next to `repair_inflight_check_workflows`)
- Test: `backend/tests/test_assessment_instance_repair.py` (new)

**Interfaces:**
- Produces: `repair_change_assessment_instances(session) -> int` (count of instances synthesized). Idempotent — second call returns 0.
- Consumes: Task 1-3 schema + linking.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_assessment_instance_repair.py
# Build LEGACY state by hand (assessments + ChangeRouting, no instance), covering:
# 1. in-flight change (in_assessment): stage-1 rows active/submitted, stage-2 pending
#    -> active instance, current_stage_order=1, tasks mirror statuses
#       (active->active, submitted->approved), assessments linked, S/C rows -> 'noted' tasks
# 2. terminal change (released): all rows submitted -> instance status 'completed'
# 3. deviation-added row not in the template snapshot -> task synthesized from the
#    assessment itself (step_id None). Nothing dropped.
# 4. idempotence: run twice, second run returns 0, no duplicate instances/tasks
# 5. owner/due/accepted mirrored onto synthesized tasks
```

Write all five concretely; use `seed_change_workflows` for the template and build assessments with explicit `status`/`stage_order`/`rasic_letter`/`owner_id`/`due_date`.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_assessment_instance_repair.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

```python
# backend/app/services/assessment_instance_repair.py
"""Synthesize change-scoped assessment instances for changes created before
Phase E (one engine). Mirrors current assessment state exactly; nothing dropped."""
from datetime import datetime
from sqlalchemy import select
from app.models.change import ChangeRequest, ChangeAssessment, ChangeRouting, TERMINAL_STATUSES, BLOCKING_LETTERS
from app.models.workflow import WfInstance, WfInstanceTask, WfTemplate, WfStage, WfStep, WfStepRasic

_STATUS_MAP = {"pending": "pending", "active": "active",
               "submitted": "approved", "waived": "waived"}


async def repair_change_assessment_instances(session) -> int:
    created = 0
    routed = (await session.execute(select(ChangeRouting))).scalars().all()
    for routing in routed:
        existing = (await session.execute(select(WfInstance.id).where(
            WfInstance.change_id == routing.change_id))).first()
        if existing is not None:
            continue
        change = await session.get(ChangeRequest, routing.change_id)
        rows = (await session.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change.id))).scalars().all()
        if not rows:
            continue
        template_id = routing.template_id or (await session.execute(
            select(WfTemplate.id).where(WfTemplate.name == "ECM Bewertung")
        )).scalar_one_or_none()
        if template_id is None:
            continue  # cannot synthesize without any template; log and move on
        open_stages = [a.stage_order for a in rows if a.status in ("active", "pending")
                       and a.rasic_letter in BLOCKING_LETTERS]
        done = not open_stages or change.status in TERMINAL_STATUSES
        instance = WfInstance(
            template_id=template_id, change_id=change.id, part_revision_id=None,
            status="completed" if done else "active",
            current_stage_order=min(open_stages) if open_stages else
                max((a.stage_order for a in rows), default=1),
            started_by=change.created_by, started_at=change.created_at,
            completed_at=datetime.utcnow() if done else None)
        session.add(instance)
        await session.flush()
        # tasks synthesized only for stages that have started (<= current), or all
        # stages when done — matches the engine's lazy stage creation
        limit = instance.current_stage_order if not done else max(
            a.stage_order for a in rows)
        for a in rows:
            if a.stage_order > limit:
                continue
            blocking = a.rasic_letter in BLOCKING_LETTERS
            task = WfInstanceTask(
                instance_id=instance.id, stage_order=a.stage_order,
                step_id=await _match_step_id(session, template_id, a.stage_order,
                                             a.department_id, a.rasic_letter),
                department_id=a.department_id, rasic_letter=a.rasic_letter,
                status=_STATUS_MAP.get(a.status, "pending") if blocking else "noted",
                is_actionable=blocking,
                completed_by=a.submitted_by, completed_at=a.submitted_at,
                owner_id=a.owner_id, accepted_at=a.accepted_at, due_date=a.due_date)
            session.add(task)
            await session.flush()
            a.wf_instance_task_id = task.id
        created += 1
    await session.flush()
    return created
```

`_match_step_id` — same helper contract as Task 5; import it from where Task 5 put it (module-level function in `change_routing_service.py`) rather than duplicating.

Wire into startup in `backend/app/main.py`, directly after the existing call at ~L351:

```python
            from app.services.assessment_instance_repair import repair_change_assessment_instances
            n = await repair_change_assessment_instances(session)
            if n:
                logger.info(f"Synthesized {n} change-scoped assessment instances")
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python3 -m pytest tests/test_assessment_instance_repair.py -v` → 5 PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/assessment_instance_repair.py backend/app/main.py backend/tests/test_assessment_instance_repair.py
git commit -m "feat(unification): startup repair synthesizes assessment instances for in-flight changes"
```

---

### Task 7: API read-through — preserved response shapes over the new engine

Response shapes stay byte-compatible so the frontend keeps working: `AssessmentResponse` and the routing/my-tasks endpoints source execution state from `effective_*`.

**Files:**
- Modify: `backend/app/schemas/change.py:82-102` (`AssessmentResponse`)
- Modify: `backend/app/api/v1/changes/changes.py:84-120` (my-tasks), `:254-284` (routing endpoint)
- Modify: `backend/app/services/change_service.py:819-886` (ownership delegation)
- Test: `backend/tests/test_assessment_ownership.py`, `backend/tests/test_changes.py` (extend)

**Interfaces:**
- Consumes: `effective_*` properties (Task 1), `WorkflowService.accept_task/assign_task/set_task_due_date` (existing).
- Produces: UNCHANGED JSON shapes for `GET /v1/changes/{id}` (assessments array), `GET /v1/changes/{id}/routing`, `GET /v1/changes/my-tasks`; ownership endpoints keep their paths but write to the task when linked.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_assessment_response_reads_execution_from_task(client, admin_auth, seed):
    # change in_assessment; accept a stage-1 assessment via
    # POST /v1/changes/{cid}/assessments/{aid}/accept
    # -> GET /v1/changes/{cid}: that assessment shows owner_id/accepted_at,
    #    AND the linked WfInstanceTask has owner_id set (task is source of truth).

@pytest.mark.asyncio
async def test_routing_view_shows_task_backed_status(client, admin_auth, seed):
    # after one R submission: GET /routing shows that department 'submitted'
    # while an unsubmitted one shows 'active' (from the task, row is 'pending').

@pytest.mark.asyncio
async def test_change_my_tasks_lists_active_task_backed_rows(client, eng_auth, seed):
    # engineer owns an active stage-1 task -> GET /v1/changes/my-tasks contains it
    # with kind=="assessment" and mine==True; shape keys unchanged.
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_changes.py -k "reads_execution or task_backed" tests/test_assessment_ownership.py -v`
Expected: FAIL (responses still read raw columns).

- [ ] **Step 3: Implement**

`AssessmentResponse` — add a before-validator that maps ORM objects through the effective properties (same pattern as `ChangeResponse`'s plant mapping at L165-184):

```python
    @model_validator(mode="before")
    @classmethod
    def _read_through(cls, data):
        if hasattr(data, "effective_status"):
            return {
                **{f: getattr(data, f) for f in (
                    "id", "change_id", "department_id", "verdict", "cost_impact",
                    "lead_time_impact_days", "conditions", "notes", "producibility",
                    "contact_person", "approval_comment", "lifecycle_cost",
                    "stage_order", "rasic_letter", "submitted_at", "submitted_by",
                    "responsible_id", "created_at", "updated_at")},
                "status": data.effective_status,
                "owner_id": data.effective_owner_id,
                "owner_name": data.effective_owner_name,
                "accepted_at": data.effective_accepted_at,
                "due_date": data.effective_due_date,
                "overdue": data.effective_overdue,
            }
        return data
```

(Match the exact current field list of `AssessmentResponse` — copy it, don't guess.)

Routing endpoint (`changes.py` L254-284): change `status=(a.status if a else None)` to `status=(a.effective_status if a else None)`.

`/changes/my-tasks` (L84-120): the inline query currently selects active `ChangeAssessment` rows. Rework: select assessments joined (outer) to their task, active = `effective_status == "active"` — since that's a Python property, query task-linked rows by `WfInstanceTask.status == "active"` UNION unlinked rows by `ChangeAssessment.status == "active"`, then build the same dict shape using `effective_*` values. Keep the sort (mine, overdue, due).

Ownership delegation (`accept_assessment` / `assign_assessment` / `set_assessment_due_date`, change_service L819-886): when `a.wf_instance_task_id` is set and the letter is blocking, delegate:

```python
        if a.wf_instance_task_id is not None and a.rasic_letter in BLOCKING_LETTERS:
            from app.services.workflow_service import WorkflowService
            await WorkflowService.accept_task(session, a.wf_instance_task_id, user)
        else:
            a.owner_id = user.id           # legacy/unlinked fallback (existing body)
            a.accepted_at = datetime.utcnow()
```

(analogous for assign → `assign_task`, due-date → `set_task_due_date`; keep the existing changelog calls). Check `accept_task`'s parameter type — it takes the `user` object, `assign_task` takes `assignee_id` + `actor` (see workflow_service L318-360); pass exactly what each expects.

- [ ] **Step 4: Run tests**

Run: `cd backend && python3 -m pytest tests/test_assessment_ownership.py tests/test_changes.py tests/test_change_routing.py -v` → PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/change.py backend/app/api/v1/changes/changes.py backend/app/services/change_service.py backend/tests/
git commit -m "feat(unification): API read-through — shapes preserved, task is source of truth"
```

---

### Task 8: Frontend regression pass for Stream 1

API shapes were preserved, so this is a verification + small-fix task, not a rebuild.

**Files:**
- Verify/adjust: `frontend/src/components/changes/AssessmentRouting.tsx`, `D1MasterPanel.tsx`, `frontend/src/pages/MyTasksPage.tsx`, their `.test.tsx` fixtures
- Test: existing vitest suites

**Interfaces:** consumes the preserved shapes from Task 7. No new interfaces.

- [ ] **Step 1: Run the frontend suite and type-check**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: 55 tests pass, tsc unchanged at 21 pre-existing errors. If a test fails on fixture data (e.g. an assessment fixture missing a field the validator now emits), fix the fixture, not the component.

- [ ] **Step 2: Manual smoke via the running app**

Start backend (`./run_backend.sh`) + frontend (`cd frontend && npm run dev`). Walk one change captured → in_assessment → submit stage-1 assessments (as a department member) → verify: routing cards advance stages, D1 cost lines still editable, My Tasks shows/clears the rows, cockpit blockers resolve, audit timeline shows both `wf_instance` and `change` events under one correlation id.

- [ ] **Step 3: Commit any fixture/UI fixes**

```bash
git add frontend/src
git commit -m "test(unification): frontend fixtures aligned with task-backed assessment state"
```

(Skip the commit if nothing changed — say so in the task report.)

---

### Task 9: Sales deadline — backend (migration 028, audited set, computed state)

**Files:**
- Create: `backend/alembic/versions/028_change_required_by.py`
- Modify: `backend/app/models/change.py` (ChangeRequest), `backend/app/schemas/change.py` (`ChangeUpdate`, `ChangeResponse`), `backend/app/services/change_service.py` (`update_change` L888-937, `lead_escalations` L254-309, `get_change`/`list_changes`)
- Test: `backend/tests/test_change_deadline.py` (new)

**Interfaces:**
- Produces: `ChangeRequest.required_by_date/required_by_reason/required_by_set_by/required_by_set_at`; `ChangeService.deadline_state(session, change) -> str|None` returning `"on_track"|"at_risk"|"overdue"|None`; `ChangeResponse` gains `required_by_date: Optional[datetime]`, `required_by_reason: Optional[str]`, `deadline_state: Optional[str]`. `PATCH /v1/changes/{id}` accepts the two writable fields.
- Consumes: `DEFAULT_TASK_DUE_DAYS` (workflow_service), change-scoped + ECN instances.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_change_deadline.py
# 1. PATCH required_by_date + reason -> persisted, set_by/set_at stamped,
#    changelog row action=="deadline_set" with old/new values, AuditLog entry present.
# 2. deadline_state None when no date.
# 3. overdue: date in the past, change not terminal -> "overdue".
# 4. at_risk: active instance with 3 remaining stages (incl. current), date in
#    2 days, DEFAULT_TASK_DUE_DAYS=7 -> needed 21d > 2d -> "at_risk".
# 5. on_track: same instance, date in 60 days -> "on_track".
# 6. terminal change (released before date) -> None (no state on done changes).
# 7. lead_escalations contains kind=="deadline" row for an at_risk/overdue change.
# 8. GET /v1/changes/{id} and GET /v1/changes expose the three new fields.
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_change_deadline.py -v` → FAIL (no columns).

- [ ] **Step 3: Migration 028 + model + schema**

Migration follows the 027 inspect-guard pattern exactly — four adds on `change_requests`: `required_by_date sa.DateTime()`, `required_by_reason sa.Text()`, `required_by_set_by sa.Integer()`, `required_by_set_at sa.DateTime()` (all nullable; FK in ORM only). Model columns accordingly. Schema:

```python
# ChangeUpdate — add:
    required_by_date: Optional[datetime] = None
    required_by_reason: Optional[str] = None
# ChangeResponse — add:
    required_by_date: Optional[datetime] = None
    required_by_reason: Optional[str] = None
    deadline_state: Optional[str] = None
```

- [ ] **Step 4: Service logic**

In `update_change`, handle the pair specially (before the generic `allowed` loop; do NOT add them to `allowed`):

```python
        if "required_by_date" in fields:
            new_date = fields.pop("required_by_date")
            reason = fields.pop("required_by_reason", None)
            old = change.required_by_date
            change.required_by_date = new_date
            change.required_by_reason = reason
            change.required_by_set_by = user_id
            change.required_by_set_at = datetime.utcnow()
            await ChangeService.append_changelog(
                session, change, "deadline_set",
                f"Required-by {old} -> {new_date}", user_id,
                field_name="required_by_date",
                old_value=str(old) if old else None,
                new_value=str(new_date) if new_date else None, notes=reason)
```

`deadline_state`:

```python
    @staticmethod
    async def deadline_state(session: AsyncSession, change: ChangeRequest) -> str | None:
        if change.required_by_date is None or change.status in TERMINAL_STATUSES:
            return None
        now = datetime.utcnow()
        if change.required_by_date < now:
            return "overdue"
        insts = (await session.execute(
            select(WfInstance).where(WfInstance.status == "active").where(
                (WfInstance.change_id == change.id)
                | WfInstance.part_revision_id.in_(
                    select(PartRevision.id).where(
                        PartRevision.originating_change_id == change.id))
            ).options(selectinload(WfInstance.template).selectinload(WfTemplate.stages))
        )).scalars().all()
        needed = 0
        for inst in insts:
            max_stage = max((s.stage_order for s in inst.template.stages), default=inst.current_stage_order)
            needed = max(needed, (max_stage - inst.current_stage_order + 1) * DEFAULT_TASK_DUE_DAYS)
        days_left = (change.required_by_date - now).days
        return "at_risk" if needed > days_left else "on_track"
```

Populate on read: in the endpoints for `GET /changes/{id}` and `GET /changes` (changes.py), after loading, set `change.deadline_state = await ChangeService.deadline_state(db, change)` (transient attribute; `ChangeResponse.from_attributes` picks it up). For the list endpoint compute it per row — acceptable at current volume; batch later if it shows.

`lead_escalations`: append `kind="deadline"` rows for the lead's non-terminal changes whose state is `at_risk`/`overdue` (id, change_number, title, required_by_date, state).

- [ ] **Step 5: Run, then commit**

Run: `cd backend && python3 -m pytest tests/test_change_deadline.py -v` → 8 PASS; full suite green. Run `python3 -m alembic upgrade head` twice (idempotence).

```bash
git add backend/alembic/versions/028_change_required_by.py backend/app/models/change.py backend/app/schemas/change.py backend/app/services/change_service.py backend/app/api/v1/changes/changes.py backend/tests/test_change_deadline.py
git commit -m "feat(deadline): required-by date with audited set + computed on_track/at_risk/overdue"
```

---

### Task 10: Sales deadline — frontend (chip, cockpit editor, list column)

**Files:**
- Create: `frontend/src/components/changes/DeadlineChip.tsx`, `frontend/src/components/changes/DeadlineChip.test.tsx`
- Modify: `frontend/src/types/change.ts` (ChangeRequest/ChangeDetail types), `frontend/src/components/changes/CockpitSummary.tsx` (status card, L54-65), `frontend/src/pages/ChangeDetailPage.tsx` (overview tab: deadline editor), `frontend/src/pages/ChangesPage.tsx` (new column + STATUS_PILL upgrade), `frontend/src/i18n/cmLabels.ts`

**Interfaces:**
- Consumes: `required_by_date`, `required_by_reason`, `deadline_state` from Task 9; `changesApi.update` (PATCH).
- Produces: `<DeadlineChip date={string|null} state={'on_track'|'at_risk'|'overdue'|null} lang={Lang} />` — renders nothing when date is null.

- [ ] **Step 1: Write the failing component test**

```tsx
// frontend/src/components/changes/DeadlineChip.test.tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DeadlineChip } from './DeadlineChip'

describe('DeadlineChip', () => {
  it('renders nothing without a date', () => {
    const { container } = render(<DeadlineChip date={null} state={null} />)
    expect(container).toBeEmptyDOMElement()
  })
  it('shows days left and at-risk styling', () => {
    const inTen = new Date(Date.now() + 10 * 864e5).toISOString()
    render(<DeadlineChip date={inTen} state="at_risk" />)
    expect(screen.getByText(/10\s?d/i)).toBeTruthy()
    expect(screen.getByTestId('deadline-chip').className).toContain('amber')
  })
  it('shows overdue in red', () => {
    const past = new Date(Date.now() - 3 * 864e5).toISOString()
    render(<DeadlineChip date={past} state="overdue" />)
    expect(screen.getByTestId('deadline-chip').className).toContain('red')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/changes/DeadlineChip.test.tsx` → FAIL (module missing).

- [ ] **Step 3: Implement the chip**

```tsx
// frontend/src/components/changes/DeadlineChip.tsx
const STATE_CLASS: Record<string, string> = {
  on_track: 'bg-sky-500/10 text-sky-300 border-sky-500/30',
  at_risk: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  overdue: 'bg-red-500/10 text-red-300 border-red-500/30',
}

export function DeadlineChip({ date, state }: { date: string | null; state: string | null }) {
  if (!date) return null
  const days = Math.ceil((new Date(date).getTime() - Date.now()) / 864e5)
  const label = days >= 0 ? `${days}d` : `${Math.abs(days)}d over`
  return (
    <span data-testid="deadline-chip"
      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs ${STATE_CLASS[state ?? 'on_track']}`}
      title={new Date(date).toLocaleDateString()}>
      ⏱ {label}
    </span>
  )
}
```

- [ ] **Step 4: Wire in**

- `src/types/change.ts`: add `required_by_date: string | null`, `required_by_reason: string | null`, `deadline_state: 'on_track' | 'at_risk' | 'overdue' | null` to the change types.
- `CockpitSummary.tsx` status card (L54-65): render `<DeadlineChip date={change.required_by_date} state={change.deadline_state} />` next to the status pill.
- `ChangeDetailPage.tsx` overview tab: small "Deadline" block — date input + reason input + save via the existing `changesApi.update` mutation (`{ required_by_date, required_by_reason }`), invalidate `['change', changeId]`, `toast.success` on save. Any authenticated user may set it (Sales or lead per spec; no role gate exists client-side today — keep consistent).
- `ChangesPage.tsx`: new "Deadline" column rendering the chip; upgrade the plain-text Status cell to `<span className={STATUS_PILL[c.status]}>{STATUS_LABELS[c.status]}</span>` for visual consistency.
- `cmLabels.ts`: add keys `deadline.title {de: 'Termin', en: 'Deadline'}`, `deadline.reason {de: 'Begründung', en: 'Reason'}`, `deadline.set {de: 'Termin setzen', en: 'Set deadline'}`, `deadline.overdue {de: 'überfällig', en: 'overdue'}`.

- [ ] **Step 5: Run, then commit**

Run: `cd frontend && npx vitest run && npx tsc --noEmit` → all pass, still 21 tsc errors (zero new).

```bash
git add frontend/src
git commit -m "feat(deadline): countdown chip on cockpit + changes list, deadline editor"
```

---

### Task 11: Notifications — backend emission, dedup, sweep (migration 029)

The inbox UI + REST endpoints already exist (`/v1/notifications*`, `NotificationBell.tsx`). This task makes the events actually fire, deduplicated.

**Files:**
- Create: `backend/alembic/versions/029_notification_dedup.py`, `backend/app/services/notification_sweep.py`
- Modify: `backend/app/models/notification.py`, `backend/app/services/notification_service.py`, emission sites: `backend/app/services/workflow_service.py` (`assign_task`, `_create_stage_tasks`), `backend/app/services/change_service.py` (deviation propose, deadline set), `backend/app/main.py` (loop)
- Test: `backend/tests/test_notifications.py` (new)

**Interfaces:**
- Produces: `Notification.kind: str|None`, `Notification.subject_key: str|None`; `NotificationService.notify_once(db, user_ids, *, kind, subject_key, title, body=None, link=None) -> int` (skips users who already have an UNREAD notification with the same kind+subject_key); `run_notification_sweep(session) -> dict` (counts per category).
- Consumes: deadline_state (Task 9), unified engine (Stream 1).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_notifications.py
# 1. notify_once creates one row; second call same (user, kind, subject_key) -> 0 new.
# 2. read notification does NOT block a new one (dedup is per unread).
# 3. assign_task emits kind="task_assigned" to the assignee with link
#    "/changes/{number}?tab=assessments" for change-scoped instances
#    (and "/my-tasks" for revision-scoped ones).
# 4. stage activation notifies I-letter departments (kind="fyi_stage").
# 5. propose deviation -> change lead gets kind="deviation_pending".
# 6. run_notification_sweep: task due in <=2 days -> owner gets "due_soon";
#    overdue task -> owner gets "overdue"; at_risk change -> lead gets
#    "deadline_at_risk". Second sweep run adds nothing (dedup).
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_notifications.py -v` → FAIL.

- [ ] **Step 3: Migration 029 + model + notify_once**

Migration (inspect-guard as before): add `kind sa.String(40)` and `subject_key sa.String(120)` to `notifications`, plus index `ix_notifications_dedup` on `(user_id, kind, subject_key)`. Model columns accordingly.

```python
    @staticmethod
    async def notify_once(db, user_ids, *, kind: str, subject_key: str,
                          title: str, body=None, link=None) -> int:
        if not user_ids:
            return 0
        existing = set((await db.execute(
            select(Notification.user_id).where(
                Notification.user_id.in_(list(set(user_ids))),
                Notification.kind == kind,
                Notification.subject_key == subject_key,
                Notification.is_read.is_(False)))).scalars().all())
        n = 0
        for uid in set(user_ids) - existing:
            db.add(Notification(user_id=uid, kind=kind, subject_key=subject_key,
                                title=title, body=body, link=link))
            n += 1
        await db.flush()
        return n
```

- [ ] **Step 4: Emission sites + sweep**

- `assign_task`: after assignment, `notify_once(db, [assignee_id], kind="task_assigned", subject_key=f"task:{task.id}", title=..., link=...)` — link `/changes/{change_number}?tab=assessments` when `instance.change_id` else `/my-tasks`.
- `_create_stage_tasks`: existing notify covers actionable departments; add `notify_departments` for I-letter assignments (title "FYI: …"); route through `notify_once` per user with `kind="fyi_stage"`, `subject_key=f"inst:{instance.id}:stage:{stage.stage_order}"` (add a `notify_departments_once` wrapper that expands membership then calls `notify_once`).
- Deviation propose (find the propose path in change_service / changes.py — `ChangeTransitionDeviation` creation): notify `change.lead_id`, `kind="deviation_pending"`, `subject_key=f"dev:{deviation.id}"`, link `/changes/{number}`.
- Deadline set/flip: on `deadline_set` in `update_change`, no notification (actor did it); flips are the sweep's job.

```python
# backend/app/services/notification_sweep.py
async def run_notification_sweep(session) -> dict:
    """due_soon (<=2 days), overdue tasks -> owner; at_risk/overdue changes -> lead."""
```

Implement: query active `WfInstanceTask` with `owner_id` and `due_date <= now+2d` → `due_soon` (subject_key `task:{id}:due_soon`); `due_date < now` → `overdue`; non-terminal changes with `required_by_date` → compute `deadline_state`, notify lead on at_risk/overdue (`subject_key f"chg:{id}:{state}"`). Links as above. Return counts.

Wire into the existing `_reminder_loop` in `main.py` (L410-424) — add a third block calling `run_notification_sweep(session)` in its own `async with AsyncSessionLocal() as session:`.

- [ ] **Step 5: Run, then commit**

Run: `cd backend && python3 -m pytest tests/test_notifications.py -v` → 6 PASS; full suite green; alembic upgrade idempotent.

```bash
git add backend/alembic/versions/029_notification_dedup.py backend/app/models/notification.py backend/app/services/ backend/app/main.py backend/tests/test_notifications.py
git commit -m "feat(notifications): deduped emission (assign/FYI/deviation) + due-soon/overdue/at-risk sweep"
```

---

### Task 12: Notifications — frontend deep links (URL-driven tabs) + inbox grouping

`ChangeDetailPage` tab state is local `useState` — notifications can't target a tab. Make the tab URL-driven (`?tab=`), keep `onResolveGate` working, group the bell inbox by change.

**Files:**
- Modify: `frontend/src/pages/ChangeDetailPage.tsx` (L25-31 tab state, L140 onResolveGate), `frontend/src/components/NotificationBell.tsx`
- Test: `frontend/src/pages/ChangeDetailPage.test.tsx` (new), extend NotificationBell coverage if a test exists (none today — add `frontend/src/components/NotificationBell.test.tsx`)

**Interfaces:**
- Consumes: notification `link` values like `/changes/GB-CM-0001?tab=assessments` (Task 11 — note backend links use the change NUMBER; verify what the changes route expects: it is `/changes/:id` with numeric id. **Fix the backend links in Task 11 to use `change.id`, not `change_number`** — cross-check this while implementing, and add a test asserting the link format matches the route).
- Produces: `/changes/:id?tab=<overview|impacted|implementation|assessments|commercial|d1|audit>` renders with that tab active; invalid/missing param falls back to `overview`.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/pages/ChangeDetailPage.test.tsx
// Render inside MemoryRouter at "/changes/1?tab=d1" with QueryClientProvider and
// mocked changesApi (vi.mock('../api/changes')) returning a minimal ChangeDetail.
// Assert the D1 tab button has the active class / D1 content is visible.
// Second test: "?tab=bogus" falls back to overview.
```

```tsx
// frontend/src/components/NotificationBell.test.tsx
// Mock client.get for /v1/notifications with 3 items across 2 links
// ("/changes/1?tab=d1" x2, "/changes/2" x1); open the bell; assert items are
// grouped under 2 headers (group key = link path before '?').
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/pages/ChangeDetailPage.test.tsx src/components/NotificationBell.test.tsx` → FAIL.

- [ ] **Step 3: Implement**

`ChangeDetailPage.tsx`:

```tsx
const [searchParams, setSearchParams] = useSearchParams()
const TABS: Tab[] = ['overview', 'impacted', 'implementation', 'assessments', 'commercial', 'd1', 'audit']
const raw = searchParams.get('tab')
const tab: Tab = TABS.includes(raw as Tab) ? (raw as Tab) : 'overview'
const setTab = (t: Tab) => setSearchParams(t === 'overview' ? {} : { tab: t }, { replace: true })
```

Remove the `useState` tab; every existing `setTab(...)` call (including `onResolveGate`) keeps working unchanged.

`NotificationBell.tsx`: group items by `n.link?.split('?')[0] ?? '_other'`, render a small slate header per group (the first item's title prefix or the path), items inside unchanged (click → navigate + mark read, as today).

- [ ] **Step 4: Run, then commit**

Run: `cd frontend && npx vitest run && npx tsc --noEmit` → green, no new tsc errors.

```bash
git add frontend/src
git commit -m "feat(notifications): URL-driven cockpit tabs enable deep links; inbox grouped by change"
```

### Task 13: Org scoping on change queries (known-gap debt)

Scoping path: `ChangeRequest.project_id → Project.plant_id → Plant.organization_id`; actor org = `User.organization_id` (NOT NULL). Changes without a project stay visible to everyone (no silent data loss).

**Files:**
- Modify: `backend/app/services/change_service.py` (`get_change` L228-233, `list_changes` L235-252), `backend/app/api/v1/changes/changes.py` (pass `current_user` into both)
- Test: `backend/tests/test_change_org_scoping.py` (new)

**Interfaces:**
- Produces: `ChangeService.list_changes(session, *, viewer: User | None = None, project_id=None, status=None, change_type=None, lead_id=None)` and `get_change(session, change_id, viewer: User | None = None)` — `viewer=None` keeps old behavior (internal callers unchanged); endpoints always pass the current user.
- Consumes: `Project.plant_id`, `Plant.organization_id` (entities.py).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_change_org_scoping.py
# Seed a second org + plant + project + user (org B). Create change A (org A
# project, via admin) and change B (org B project, via the org-B user).
# 1. GET /v1/changes as admin (org A) -> contains A, not B.
# 2. GET /v1/changes/{B.id} as admin -> 404.
# 3. Change with project_id=None visible to both orgs.
# 4. list_changes(viewer=None) returns everything (internal callers unaffected).
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_change_org_scoping.py -v` → FAIL (B visible).

- [ ] **Step 3: Implement**

```python
def _org_scope(stmt, viewer):
    if viewer is None:
        return stmt
    org_projects = select(Project.id).join(Plant, Project.plant_id == Plant.id).where(
        Plant.organization_id == viewer.organization_id)
    return stmt.where(
        ChangeRequest.project_id.is_(None) | ChangeRequest.project_id.in_(org_projects))
```

Apply in `list_changes` and `get_change` (after load: return `None` when out of scope so the endpoint 404s). Update the two endpoints to pass `current_user`. Grep other `list_changes`/`get_change` callers (`grep -rn "list_changes\|get_change(" app/`) — leave internal/service callers viewer-less.

- [ ] **Step 4: Run, then commit**

Run: `cd backend && python3 -m pytest tests/test_change_org_scoping.py -v && python3 -m pytest` → green.

```bash
git add backend/app/services/change_service.py backend/app/api/v1/changes/changes.py backend/tests/test_change_org_scoping.py
git commit -m "feat(scoping): change queries scoped to the viewer's organization"
```

---

### Task 14: Reports backend — ReportService + /reports API

**Files:**
- Create: `backend/app/services/report_service.py`, `backend/app/api/v1/reports.py`
- Modify: `backend/app/api/v1/__init__.py` (register router)
- Test: `backend/tests/test_reports.py` (new)

**Interfaces:**
- Produces three endpoints (all scoped via Task 13's `_org_scope` logic, viewer = current user):
  - `GET /v1/reports/pipeline` → `{"funnel": [{"status": str, "count": int}, ...] (all 12 CHANGE_STATUSES, zero-filled), "throughput": [{"month": "YYYY-MM", "released": int}] (last 12), "avg_stage_days": [{"from_status": str, "to_status": str, "avg_days": float}], "on_time_rate": float|None}`
  - `GET /v1/reports/workload` → `{"departments": [{"department_id": int, "name": str, "open": int, "overdue": int}], "owners": [{"owner_id": int, "owner_name": str, "open": int, "overdue": int}], "at_risk_changes": [{"id", "change_number", "title", "required_by_date", "deadline_state"}], "escalation_count": int}`
  - `GET /v1/reports/cost` → `{"projects": [{"project_id", "name", "budget": float, "actual": float}], "plants": [{"plant_id", "name", "actual": float}]}` — budget = `estimated_cost`, actual = Σ cost-line `internal_cost + external_cost` (reuse `CostService.summation` per change or aggregate `AssessmentCostLine` directly; direct aggregate is fine).
- Consumes: `AuditLog` transitions (`action in ("status_changed", "deviated_transition")`, `field_name`-equivalent old/new in `old_values`/`new_values`, `correlation_id` = change number), `deadline_state` (Task 9), `WfInstanceTask`/`ChangeAssessment` open/overdue (Stream 1 semantics).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_reports.py
# Fixture: 2 changes in org A (one released on time vs required_by_date, one
# in_assessment with an overdue owned task), 1 change in org B.
# 1. /reports/pipeline: funnel has all statuses zero-filled; in_assessment==1
#    (org B change invisible); on_time_rate == 1.0; throughput has the release month.
# 2. avg_stage_days: seed two AuditLog transition entries 3 days apart for one
#    change -> pair (captured, in_assessment) avg_days ≈ 3.0.
# 3. /reports/workload: the owner appears with open==1, overdue==1; department
#    row aggregates; at_risk_changes empty (no deadline) or as seeded.
# 4. /reports/cost: cost lines (internal 100, external 50) -> project actual 150,
#    plant breakdown matches the line's plant_id.
# 5. Empty DB (fresh org with no changes) -> all endpoints return zero-filled
#    shapes, HTTP 200, no division-by-zero (on_time_rate None).
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_reports.py -v` → 404s.

- [ ] **Step 3: Implement `ReportService`**

`pipeline(session, viewer)`: funnel via `select(ChangeRequest.status, func.count()).group_by(...)` on the org-scoped statement, zero-fill from `CHANGE_STATUSES`; throughput via `released_at` grouped by month (compute the month key in Python after selecting `released_at` — portable across SQLite/Postgres, volumes are small); `avg_stage_days`: load org-scoped changes' numbers, then `select(AuditLog).where(AuditLog.correlation_id.in_(numbers), AuditLog.action.in_(("status_changed", "deviated_transition"))).order_by(AuditLog.correlation_id, AuditLog.created_at)` and average deltas per (old→new) pair in Python (inspect `AuditLog`'s actual timestamp/values column names before writing — use what `audit_service.py` writes); `on_time_rate`: among org-scoped released/closed changes with `required_by_date`: fraction where `released_at or closed_at <= required_by_date`; `None` when no such changes.

`workload(session, viewer)`: open = active `WfInstanceTask` rows (join instance → change via `change_id` OR revision-origin path, org-scoped) grouped by department / by owner; overdue = same with `due_date < now`; `at_risk_changes` via `deadline_state` over org-scoped non-terminal changes with a date; `escalation_count` = total overdue rows.

`cost(session, viewer)`: aggregate `AssessmentCostLine` joined `ChangeAssessment → ChangeRequest` (org-scoped) grouped by `ChangeRequest.project_id` (join `Project` for names, sum `internal_cost + external_cost`) and by `AssessmentCostLine.plant_id` (join `Plant`).

Router `app/api/v1/reports.py` — three thin GET endpoints, `current_user` dependency, register in `app/api/v1/__init__.py` following the existing pattern (import + `api_router.include_router`).

- [ ] **Step 4: Run, then commit**

Run: `cd backend && python3 -m pytest tests/test_reports.py -v && python3 -m pytest` → green.

```bash
git add backend/app/services/report_service.py backend/app/api/v1/reports.py backend/app/api/v1/__init__.py backend/tests/test_reports.py
git commit -m "feat(reports): pipeline/workload/cost aggregates with org scoping"
```

---

### Task 15: Reports frontend — dashboard page

Hand-rolled Tailwind viz following `src/pages/LessonsKpiBoardPage.tsx` (`Tile`, horizontal `BarChart` via width-%, trend via height-%). No chart library. Every number links to the filtered list behind it.

**Files:**
- Create: `frontend/src/pages/ReportsPage.tsx`, `frontend/src/pages/ReportsPage.test.tsx`, `frontend/src/api/reports.ts`
- Modify: `frontend/src/App.tsx` (route `/reports`), `frontend/src/components/layout/Sidebar.tsx` (navItems L28-38), `frontend/src/pages/ChangesPage.tsx` (read `?status=` initial filter), `frontend/src/i18n/cmLabels.ts`

**Interfaces:**
- Consumes: the three Task 14 endpoints via `reportsApi = { pipeline: () => client.get('/v1/reports/pipeline')..., workload: ..., cost: ... }` (mirror `src/api/changes.ts` style). Query keys `['reports', 'pipeline'|'workload'|'cost']`.
- Produces: route `/reports`; funnel bars link to `/changes?status=<status>`; ChangesPage initializes its status filter from `?status=`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/ReportsPage.test.tsx
// vi.mock('../api/reports'); resolve pipeline/workload/cost with small fixtures.
// Render in MemoryRouter + QueryClientProvider.
// 1. funnel renders a row per non-zero status with its count and an anchor
//    href="/changes?status=in_assessment".
// 2. workload section lists the seeded department with open/overdue counts.
// 3. cost section shows the project with formatted actual.
```

- [ ] **Step 2: Run to verify failure** — `npx vitest run src/pages/ReportsPage.test.tsx` → FAIL.

- [ ] **Step 3: Implement**

`ReportsPage.tsx`: three sections ("Pipeline", "Workload", "Kosten") of `Tile`s + bars, copied structurally from LessonsKpiBoardPage; statuses labeled via `STATUS_LABELS`, funnel bar per status (width % of max, `STATUS_PILL`-consistent colors), `on_time_rate` as a headline Tile (`—` when null), throughput as a 12-column mini bar row, workload as two tables (departments, owners) with overdue in red, at-risk changes as linked rows (`/changes/${c.id}`), cost as budget-vs-actual bars per project. `useQuery` per endpoint, loading skeletons, empty states that teach ("Noch keine Änderungen — starte eine vom Teil aus.").

Wire route in `App.tsx` (`<ProtectedRoute><ReportsPage/></ProtectedRoute>` at `/reports`), Sidebar navItem `{ label: 'Reports', path: '/reports', icon: <existing icon pattern> }` after Changes. `ChangesPage`: `useSearchParams` → initialize/sync `statusFilter` with `?status=`. cmLabels keys `reports.*` (title, pipeline, workload, cost, onTime, throughput, atRisk, empty).

- [ ] **Step 4: Run, then commit**

Run: `cd frontend && npx vitest run && npx tsc --noEmit` → green, no new tsc errors.

```bash
git add frontend/src
git commit -m "feat(reports): KPI dashboard — pipeline, workload, cost with drill-through"
```

---

### Task 16: tsc baseline burn-down (21 → 0)

The exact 21 errors (from `npx tsc --noEmit`, verified 2026-07-03). 17 are mechanical (unused vars TS6133, implicit any TS7006, missing return TS7030); 4 in `WorkflowDesignerPage.tsx` are typed-state mismatches.

**Files:**
- Modify: `frontend/src/components/CutPlane.tsx` (L10: drop unused `axis`, `position` props or prefix `_`), `MeasurementReadout.tsx` (L72: add explicit `return undefined` on the fall-through path), `Viewer3D.tsx` (L51-54, L282: remove unused destructured props/param), `components/workflows/StepEditorModal.tsx` (L125 `dept` unused), `pages/LoginPage.tsx` (L5 `useEffect`, L13 `isAuthenticated` unused), `pages/PartDetail.tsx` (L128 unused function — delete it), `pages/WorkflowDesignerPage.tsx` (L137, L166, L364, L371, L376, L378, L430, L442, L492)
- Test: type-check + existing suites

**Interfaces:** none — behavior-preserving cleanup only.

- [ ] **Step 1: Fix the 17 mechanical errors**

Delete unused imports/params/functions (never `// @ts-ignore`); for intentionally-unused destructured props use a leading underscore only if the prop must stay for API compatibility, otherwise remove it from the destructuring AND the interface if nothing else uses it.

- [ ] **Step 2: Fix the WorkflowDesignerPage cluster**

The 4 hard errors (L137/L166 TS2345, L430 TS2322) stem from local partial-object state not matching `WfStage`/`WfStep` from `src/types/workflow.ts`. Introduce local draft types instead of widening the real ones:

```ts
type DraftStage = Omit<WfStage, 'id' | 'template_id'> & { id?: number; template_id?: number }
type DraftStep = Omit<WfStep, 'id' | 'stage_id'> & { id?: number; stage_id?: number }
```

and type the setState/handlers (L371/L376/L378 implicit-any params) against these. Do NOT cast to `any`; do NOT change `src/types/workflow.ts` (real API objects always have ids).

- [ ] **Step 3: Verify zero and run everything**

Run: `cd frontend && npx tsc --noEmit` → **0 errors** (also means `npm run build` = `tsc && vite build` now passes — run it once to confirm).
Run: `npx vitest run` → all pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "chore(tsc): burn baseline 21 -> 0; typed drafts in WorkflowDesignerPage"
```

---

### Task 17: Final verification, review, merge to main

**Files:** none new — verification + integration.

- [ ] **Step 1: Full verification (superpowers:verification-before-completion)**

Run and record actual output:
- `cd backend && python3 -m pytest` → expect ~220+ pass, 0 fail
- `cd backend && python3 -m alembic upgrade head` (twice — idempotent, exits clean)
- `cd frontend && npx vitest run` → expect ~65+ pass
- `cd frontend && npx tsc --noEmit` → 0 errors; `npm run build` succeeds
- Manual smoke (dev servers): one change end-to-end — create from part → submit → assessments through the engine → deviation add/remove → costing/quoted/approved with gates → kickoff → deadline set + chip states → bell shows deduped notifications with working deep links → /reports numbers match the walked change → audit timeline verifies (hash chain OK).

- [ ] **Step 2: Whole-phase code review**

Use superpowers:requesting-code-review on the Phase E commit range (opus tier). Fix Important+ findings; re-run suites.

- [ ] **Step 3: Merge (superpowers:finishing-a-development-branch)**

**STOP — ask the user before pushing** (outward-facing action): confirm pushing `feature/change-assessment-routing` (now ~100 commits ahead) and the merge target/mechanics (direct merge to `main` vs PR). Then execute what the user picks and verify `main` is green afterwards.

---

## Plan self-review notes (written 2026-07-03)

- **Spec coverage:** unification (Tasks 1–8), deadline (9–10), notifications (11–12), reporting (14–15), org scoping (13), tsc + merge (16–17). Spec's "execution columns no longer written" honored via read-through (Task 7); columns dropped in a later phase as spec states.
- **Deliberate deviations from spec text:** none functional. Compliance-KPI view excluded per user decision (recorded in spec).
- **Known churn hotspots flagged inline:** `test_change_routing.py` (Task 4), department-membership authz on submit (Task 4 note), backend notification links must use change **id** not number (Task 12 cross-check).
- **Type consistency check:** `start_change_workflow(db, change_id, template_id, started_by_id)` used in Tasks 2/3/6; `notify_once(db, user_ids, *, kind, subject_key, title, body, link)` in Task 11 tests+sites; `effective_*` property names consistent across Tasks 1/4/7; `_match_step_id` defined in Task 5, imported in Task 6.
