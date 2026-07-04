# ECM Phase C — Named Ownership, Due Dates, Escalation, My Tasks — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every open assessment and check-workflow task carries a named owner (accept or assign), a due date stamped at activation, computed overdue flags, and lead-facing escalation surfacing — so "who is on the hook and since when" is answerable at a glance, with every ownership change audited.

**Architecture:** Three columns (`owner_id`, `accepted_at`, `due_date`) are added to both `wf_instance_tasks` and `change_assessments` (migration 024), with an `overdue` Python property on each model so Pydantic `from_attributes` serializes it for free. Due dates are stamped when a task/assessment becomes ACTIVE (stage activation), defaulting to `DEFAULT_TASK_DUE_DAYS = 7`, overridable by the accountable person via new endpoints. Accept/assign/due-date service methods live on `WorkflowService` and `ChangeService` respectively, each writing hash-chained `AuditLog` rows (correlation = change number) and notifying assignees. Both My-Tasks queries become owner-aware (`mine` flag, unclaimed = `owner_id IS NULL`), and a new `GET /changes/my-escalations` rolls up everything overdue across the changes the current user leads — consumed by a Dashboard card and a My Tasks section.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async (`Mapped`/`mapped_column`), Alembic, Pydantic v2, pytest + pytest-asyncio (`asyncio_mode=auto`); React + TypeScript, @tanstack/react-query, Tailwind dark-slate, vitest + @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-07-02-ecm-lifecycle-design.md` (Phase C row + scope area 4: "owner_id, due_date, accepted_at on assessments and WF instance tasks; overdue computation; escalation surfacing to the change lead (dashboard + My Tasks). Ownership changes are audited events.").

## Global Constraints

- Run backend tests from `backend/` with `python3 -m pytest` (bare `python` absent). Run Alembic via the `alembic` console script from `backend/` (NOT `python3 -m alembic` — a local package shadows the lib).
- New Alembic migration id is `024`, `down_revision = "023"`. Idempotent `inspect(op.get_bind())` guard pattern. **SQLite cannot ADD COLUMN with a FK constraint** (learned in Phase B): `owner_id` columns go in as plain `sa.Integer()` in the migration while the ORM model keeps `ForeignKey("users.id")`; document with the same comment style as migration 023.
- Every new model relationship uses `lazy="selectin"` ONLY where a serialized property depends on it (see `owner` below) — never rely on lazy loads inside async serialization (MissingGreenlet).
- Enum-like value tuples and defaults live as module constants next to their consumer (mirror `CHANGE_STATUSES`); `DEFAULT_TASK_DUE_DAYS = 7` goes at the top of `backend/app/services/workflow_service.py`, imported where needed.
- All audited actions: WF-task events via the existing `WorkflowService._audit(db, instance, action, user_id, new_values)` (writes hash-chained `AuditLog`, correlation = originating change number); assessment events via `ChangeService.append_changelog(session, change, action, description, performed_by, *, field_name=None, old_value=None, new_value=None, notes=None)` (dual-writes AuditLog).
- Notifications: `NotificationService.notify_users(db, user_ids: list[int], title: str, body: str | None = None, link: str | None = None) -> int` (function-local import in services, matching existing call sites).
- Authorization idiom: routers resolve `current_user`, services raise `ValueError` (workflow, → HTTP 400) / `ChangeError` (change, → HTTP 400); routers raise `HTTPException` 403/404 directly (mirror `put_gate` at `backend/app/api/v1/changes/changes.py`).
- User display name = `User.full_name` (`backend/app/models/entities.py:48`).
- Due-date fields are `DateTime` (dominant codebase convention — milestones, gauges, lessons all use DateTime; comparisons vs `datetime.utcnow()`).
- Route-ordering: any new literal `/changes/...` route (e.g. `/my-escalations`) MUST be registered before the `/{change_id}` routes (mirror `my-tasks`/`check-standards` placement).
- `GET /workflow-instances/my-tasks` and `GET /changes/my-tasks` return raw dicts (no response_model) — extend the dicts; do NOT touch the stale, unused `MyTaskResponse` schema (`backend/app/schemas/workflow.py:181` — its `article_*` fields prove it's dead; leave a one-line comment on it, nothing more).
- Existing tests stay green: ownership is accountability, NOT a lock — `complete_task`/`submit_assessment` remain completable by any authorized department member regardless of owner.
- Test import convention: `from tests.conftest import <helper>`; fixtures `seed` (`{org_id, project_id, admin_id, engineer_id, inactive_id}`), `part` (`{part_id, revision_id}`), `client`, `eng_auth`, `admin_auth`; helper `approve_gates`. The engineer user's id is `seed["engineer_id"]`; `login()` uses emails `eng@test.io` / `admin@test.io`.
- Frontend: tests `cd frontend && npx vitest run <file>`; type-check `npx tsc --noEmit` (≈30 PRE-EXISTING errors in files untouched by this phase — you must add ZERO new ones); labels in `frontend/src/i18n/cmLabels.ts` (DE/EN, `t()` defaults `'en'`); query keys `['workflow','my-tasks', deptId]` (in `useWorkflows.ts` `QUERY_KEYS`), `['change-my-tasks']`, `['open-task-count']`; mutations invalidate then-refetch.
- Agent tiering: each task carries a **Tier** hint (haiku mechanical / sonnet standard / opus design-critical: authorization, escalation query, UX-critical components). Never trade correctness for cost.

---

## File Structure

**Backend — create:**
- `backend/alembic/versions/024_ownership_due_dates.py` — six columns across two tables.
- `backend/tests/test_task_ownership.py` — WF task accept/assign/due-date + due-date stamping.
- `backend/tests/test_assessment_ownership.py` — assessment accept/assign/due-date.
- `backend/tests/test_escalations.py` — lead escalation roll-up + My Tasks owner-awareness.

**Backend — modify:**
- `backend/app/models/workflow.py` — `WfInstanceTask`: 3 columns + `owner` relationship + `owner_name`/`overdue` properties.
- `backend/app/models/change.py` — `ChangeAssessment`: 3 columns + `owner` relationship + `owner_name`/`overdue` properties.
- `backend/app/services/workflow_service.py` — `DEFAULT_TASK_DUE_DAYS`, due-date stamping in `_create_stage_tasks`, `accept_task`, `assign_task`, `set_task_due_date`, `_is_department_member`, owner fields in `get_my_tasks`.
- `backend/app/services/change_routing_service.py` — due-date stamping in `build_routing`/`activate_stage`.
- `backend/app/services/change_service.py` — `accept_assessment`, `assign_assessment`, `set_assessment_due_date`, `lead_escalations`.
- `backend/app/api/v1/workflows/workflow_instances.py` — accept/assign/due-date routes; owner fields in the task serializer.
- `backend/app/api/v1/changes/changes.py` — assessment accept/assign/due-date routes, `GET /my-escalations`, owner fields in `my_change_tasks`.
- `backend/app/schemas/workflow.py` — `WfInstanceTaskResponse` + owner/due fields; `AssignTaskRequest`, `DueDateRequest`.
- `backend/app/schemas/change.py` — `AssessmentResponse` + owner/due/overdue fields.

**Frontend — create:**
- `frontend/src/components/EscalationsCard.tsx` (+ `EscalationsCard.test.tsx`) — lead-facing overdue roll-up (Dashboard + My Tasks).

**Frontend — modify:**
- `frontend/src/types/workflow.ts` — `MyTask` + owner fields; `WfInstanceTask` + owner fields; `Escalation` type.
- `frontend/src/types/change.ts` — `ChangeTask` + owner fields.
- `frontend/src/api/changes.ts` — `myEscalations`, assessment accept/assign.
- `frontend/src/hooks/queries/useWorkflows.ts` — `useAcceptTask`, `useAssignTask` mutations.
- `frontend/src/pages/MyTasksPage.tsx` — owner/due/overdue columns, Accept buttons, mine-first sort, escalations section.
- `frontend/src/components/workflows/WorkflowProgress.tsx` — owner chip + Accept on task rows.
- `frontend/src/pages/Dashboard.tsx` — mount `EscalationsCard`.
- `frontend/src/i18n/cmLabels.ts` — new labels.

---

## Task 1: Model columns + migration 024

**Tier:** sonnet.

**Files:**
- Modify: `backend/app/models/workflow.py` (WfInstanceTask, ~L176-196), `backend/app/models/change.py` (ChangeAssessment, ~L150-184)
- Create: `backend/alembic/versions/024_ownership_due_dates.py`
- Test: `backend/tests/test_task_ownership.py` (model section)

**Interfaces:**
- Produces (both `WfInstanceTask` and `ChangeAssessment`): `owner_id: int | None` (ORM FK users.id, indexed), `accepted_at: datetime | None`, `due_date: datetime | None`; relationship `owner` (`lazy="selectin"`, `foreign_keys=[owner_id]`); properties `owner_name -> str | None` (reads `self.owner.full_name`, safe because selectin) and `overdue -> bool`.
- `WfInstanceTask.overdue` = `due_date is not None and status == "active" and due_date < datetime.utcnow()`.
- `ChangeAssessment.overdue` = `due_date is not None and status == "active" and due_date < datetime.utcnow()`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_task_ownership.py
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def test_ownership_columns_and_overdue_property(session_factory, seed):
    from app.models.workflow import (
        Department, WfTemplate, WfStage, WfStep, WfStepRasic, WfInstanceTask)
    from app.models.change import ChangeAssessment

    async with session_factory() as s:
        dept = Department(name="Own Dept", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        tmpl = WfTemplate(name="own-tpl", version=1, is_active=True,
                          created_by=seed["engineer_id"])
        s.add(tmpl)
        await s.flush()
        stage = WfStage(template_id=tmpl.id, stage_order=1, name="S1")
        s.add(stage)
        await s.flush()
        step = WfStep(stage_id=stage.id, step_name="do it", position_in_stage=1)
        s.add(step)
        await s.flush()
        s.add(WfStepRasic(step_id=step.id, department_id=dept.id, rasic_letter="R"))
        await s.commit()
        dept_id = dept.id

    async with session_factory() as s:
        task = WfInstanceTask(
            instance_id=None, stage_order=1, step_id=None, department_id=dept_id,
            rasic_letter="R", status="active", is_actionable=True,
            owner_id=seed["engineer_id"],
            accepted_at=datetime.utcnow(),
            due_date=datetime.utcnow() - timedelta(days=1),
        )
        assert task.overdue is True
        task.due_date = datetime.utcnow() + timedelta(days=1)
        assert task.overdue is False
        task.due_date = datetime.utcnow() - timedelta(days=1)
        task.status = "approved"
        assert task.overdue is False

        a = ChangeAssessment(change_id=None, department_id=dept_id,
                             status="active",
                             due_date=datetime.utcnow() - timedelta(hours=2))
        assert a.overdue is True
        assert hasattr(a, "owner_id") and hasattr(a, "accepted_at")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_task_ownership.py -v`
Expected: FAIL with `TypeError: 'owner_id' is an invalid keyword argument` (or AttributeError on `overdue`).

- [ ] **Step 3: Implement the model changes**

In `backend/app/models/workflow.py`, on `WfInstanceTask` after `notes`:

```python
    # Phase C: named ownership + due dates
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

and next to the existing relationships:

```python
    owner: Mapped["User | None"] = relationship(
        foreign_keys=[owner_id], lazy="selectin")
```

and after the relationships:

```python
    @property
    def owner_name(self) -> str | None:
        return self.owner.full_name if self.owner is not None else None

    @property
    def overdue(self) -> bool:
        return (self.due_date is not None and self.status == "active"
                and self.due_date < datetime.utcnow())
```

(`User` is referenced by string; check the file's existing imports — `datetime` is already imported; add `from app.models.entities import User` ONLY if other string-referenced relationships in this file require it — they don't, string form works because `completed_by_user: Mapped["User | None"]` already exists at ~L195.)

In `backend/app/models/change.py`, on `ChangeAssessment` after `responsible_id`/`submitted_*` (keep `responsible_id` untouched — it is a submitter-declared contact, distinct from Phase C ownership; consolidation is Phase D cleanup):

```python
    # Phase C: named ownership + due dates (owner = accountable person; distinct
    # from responsible_id, a free-form contact declared at submission)
    owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```

relationship + properties (same shape as WfInstanceTask, `Optional[...]` style to match this file):

```python
    owner: Mapped["User | None"] = relationship(
        foreign_keys=[owner_id], lazy="selectin")

    @property
    def owner_name(self) -> Optional[str]:
        return self.owner.full_name if self.owner is not None else None

    @property
    def overdue(self) -> bool:
        return (self.due_date is not None and self.status == "active"
                and self.due_date < datetime.utcnow())
```

(Check `change.py`'s existing relationship imports; `User` string-refs already appear in this file's neighborhood — mirror them.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_task_ownership.py -v`
Expected: PASS

- [ ] **Step 5: Write migration 024**

```python
# backend/alembic/versions/024_ownership_due_dates.py
"""Phase C: owner_id/accepted_at/due_date on wf_instance_tasks and
change_assessments.

Revision ID: 024
Revises: 023
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None

# SQLite cannot ADD COLUMN with a FK constraint (see migration 023's note):
# owner_id ships as a plain Integer here; the ORM model carries the ForeignKey.
_TABLES = ("wf_instance_tasks", "change_assessments")


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        insp = inspect(bind)
        cols = {c["name"] for c in insp.get_columns(table)}
        if "owner_id" not in cols:
            op.add_column(table, sa.Column("owner_id", sa.Integer(), nullable=True))
        if "accepted_at" not in cols:
            op.add_column(table, sa.Column("accepted_at", sa.DateTime(), nullable=True))
        if "due_date" not in cols:
            op.add_column(table, sa.Column("due_date", sa.DateTime(), nullable=True))
        indexes = {ix["name"] for ix in inspect(bind).get_indexes(table)}
        ix_name = f"ix_{table}_owner_id"
        if ix_name not in indexes:
            op.create_index(ix_name, table, ["owner_id"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        indexes = {ix["name"] for ix in inspect(bind).get_indexes(table)}
        ix_name = f"ix_{table}_owner_id"
        if ix_name in indexes:
            op.drop_index(ix_name, table_name=table)
        op.drop_column(table, "owner_id")
        op.drop_column(table, "accepted_at")
        op.drop_column(table, "due_date")
```

- [ ] **Step 6: Apply migration + full suite**

Run: `cd backend && alembic upgrade head && alembic upgrade head && python3 -m pytest`
Expected: both alembic runs exit 0 (second is a no-op); full suite passes (169+).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/workflow.py backend/app/models/change.py \
        backend/alembic/versions/024_ownership_due_dates.py \
        backend/tests/test_task_ownership.py
git commit -m "feat(ownership): owner/accepted_at/due_date columns on tasks and assessments"
```

---

## Task 2: Due-date stamping at activation

**Tier:** sonnet.

**Files:**
- Modify: `backend/app/services/workflow_service.py` (`_create_stage_tasks`), `backend/app/services/change_routing_service.py` (`build_routing`, `activate_stage`)
- Test: `backend/tests/test_task_ownership.py` (extend), `backend/tests/test_assessment_ownership.py` (create)

**Interfaces:**
- Produces: `DEFAULT_TASK_DUE_DAYS = 7` module constant at the top of `workflow_service.py` (next to `ACTIONABLE_LETTERS`). Every ACTIONABLE `WfInstanceTask` gets `due_date = utcnow + DEFAULT_TASK_DUE_DAYS days` at creation (stage activation); S/C/I tasks get none. Every `ChangeAssessment` row gets `due_date = utcnow + DEFAULT_TASK_DUE_DAYS days` at the moment its stage ACTIVATES (in `activate_stage`, when flipping `pending` → `active`; and in `build_routing` for the initially-activated stage via the existing `activate_stage` call — verify `build_routing` activates through `activate_stage` and stamp in ONE place only).
- Consumes: Task 1 columns.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_task_ownership.py`:

```python
@pytest_asyncio.fixture
async def two_stage_template(session_factory, seed):
    """Two-stage template, one R dept per stage; dept has the engineer as member."""
    from app.models.workflow import (
        Department, UserDepartment, WfTemplate, WfStage, WfStep, WfStepRasic)
    async with session_factory() as s:
        dept = Department(name="Stamp Dept", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept.id))
        tmpl = WfTemplate(name="stamp-tpl", version=1, is_active=True,
                          created_by=seed["engineer_id"])
        s.add(tmpl)
        await s.flush()
        for order in (1, 2):
            stage = WfStage(template_id=tmpl.id, stage_order=order, name=f"S{order}")
            s.add(stage)
            await s.flush()
            step = WfStep(stage_id=stage.id, step_name=f"step{order}",
                          position_in_stage=1)
            s.add(step)
            await s.flush()
            s.add(WfStepRasic(step_id=step.id, department_id=dept.id,
                              rasic_letter="R"))
            s.add(WfStepRasic(step_id=step.id, department_id=dept.id,
                              rasic_letter="I"))
        await s.commit()
        return {"template_id": tmpl.id, "dept_id": dept.id}


async def test_actionable_tasks_get_default_due_date(
        session_factory, seed, part, two_stage_template):
    from app.models.workflow import WfInstanceTask
    from app.services.workflow_service import WorkflowService, DEFAULT_TASK_DUE_DAYS

    async with session_factory() as s:
        inst = await WorkflowService.start_workflow(
            s, part["revision_id"], two_stage_template["template_id"],
            seed["engineer_id"])
        await s.commit()
        inst_id = inst.id

    async with session_factory() as s:
        tasks = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst_id))).scalars().all()
        actionable = [t for t in tasks if t.is_actionable]
        noted = [t for t in tasks if not t.is_actionable]
        assert actionable and noted
        for t in actionable:
            assert t.due_date is not None
            delta_days = (t.due_date - datetime.utcnow()).total_seconds() / 86400
            assert DEFAULT_TASK_DUE_DAYS - 1 < delta_days <= DEFAULT_TASK_DUE_DAYS
        assert all(t.due_date is None for t in noted)
```

Create `backend/tests/test_assessment_ownership.py`:

```python
# backend/tests/test_assessment_ownership.py
from datetime import datetime

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def _routed_change(client, eng_auth, seed, session_factory, part_id):
    """Change routed into in_assessment via the standard flow."""
    from tests.conftest import approve_gates
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "own", "change_type": "tooling",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    change = res.json()
    res = await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                            json={"part_id": part_id, "is_lead": True},
                            headers=eng_auth)
    assert res.status_code == 200, res.text
    await approve_gates(client, eng_auth, change["id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "in_assessment"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    return change


async def test_assessments_get_due_date_on_activation(
        client, eng_auth, seed, session_factory, part):
    from app.models.change import ChangeAssessment
    change = await _routed_change(client, eng_auth, seed, session_factory,
                                  part["part_id"])
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"]))).scalars().all()
        assert rows
        active = [a for a in rows if a.status == "active"]
        assert active
        assert all(a.due_date is not None for a in active)
        pending = [a for a in rows if a.status == "pending"]
        assert all(a.due_date is None for a in pending)
```

(Note: with the fallback routing — no ChangeRoutingStandard seeded in this test DB — all rows may land in one stage, so `pending` may be empty; the `all(...)` over an empty list is fine. The active-stage assertion is the load-bearing one.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_task_ownership.py tests/test_assessment_ownership.py -v`
Expected: new tests FAIL (`due_date is None`, or ImportError on `DEFAULT_TASK_DUE_DAYS`).

- [ ] **Step 3: Implement**

`backend/app/services/workflow_service.py` — top of file, next to `ACTIONABLE_LETTERS`:

```python
DEFAULT_TASK_DUE_DAYS = 7
```

In `_create_stage_tasks`, the `WfInstanceTask(...)` constructor gains:

```python
                    due_date=(datetime.utcnow() + timedelta(days=DEFAULT_TASK_DUE_DAYS))
                    if is_actionable else None,
```

(add `timedelta` to the file's `datetime` import).

`backend/app/services/change_routing_service.py` — in `activate_stage` (the loop flipping `pending` → `active`, ~L125-145), when setting `status = "active"` also set:

```python
            row.due_date = datetime.utcnow() + timedelta(days=DEFAULT_TASK_DUE_DAYS)
```

with `from app.services.workflow_service import DEFAULT_TASK_DUE_DAYS` (import at top if no cycle — `change_routing_service` does not import `workflow_service` today and `workflow_service` does not import `change_routing_service`, so a top-level import is safe; verify with a quick grep, else function-local). Add `timedelta` to imports. READ `build_routing` first: if it activates the first stage exclusively through `activate_stage`, stamping there covers creation too — do not double-stamp. If `build_routing` sets any rows `active` directly, route them through the same stamping line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_task_ownership.py tests/test_assessment_ownership.py tests/test_change_routing.py tests/test_workflows.py -v`
Expected: PASS (routing/workflow suites unaffected — new fields are additive).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/workflow_service.py \
        backend/app/services/change_routing_service.py \
        backend/tests/test_task_ownership.py backend/tests/test_assessment_ownership.py
git commit -m "feat(ownership): stamp default due dates at stage activation"
```

---

## Task 3: WF task accept / assign / due-date — service + API + audit

**Tier:** opus (authorization rules).

**Files:**
- Modify: `backend/app/services/workflow_service.py`, `backend/app/api/v1/workflows/workflow_instances.py`, `backend/app/schemas/workflow.py`
- Test: `backend/tests/test_task_ownership.py` (extend)

**Interfaces:**
- Produces (all `@staticmethod` on `WorkflowService`; each raises `ValueError` on violation, mapped to 400 by the router; each writes `WorkflowService._audit`):
  - `_is_department_member(db, user_id: int, department_id: int) -> bool` (query `UserDepartment`).
  - `accept_task(db, task_id: int, user) -> WfInstanceTask` — task must exist, be `active` + actionable; user must be admin or member of the task's department; if `owner_id` set to someone else → ValueError "already owned"; idempotent self-accept OK. Sets `owner_id=user.id`, `accepted_at=utcnow`. Audit `task_accepted`.
  - `assign_task(db, task_id: int, assignee_id: int, actor) -> WfInstanceTask` — actor admin or member of the task's department; assignee must be an ACTIVE user AND member of the task's department; task `active` + actionable. Sets `owner_id=assignee_id`, `accepted_at=None` (assignee hasn't accepted). Audit `task_assigned`; notify the assignee via `NotificationService.notify_users(db, [assignee_id], title=f"Task assigned: {task.step.step_name}", link="/my-tasks")` (skip self-assign notification).
  - `set_task_due_date(db, task_id: int, due_date: datetime, actor) -> WfInstanceTask` — actor admin, OR the lead of the originating change (resolve `instance.part_revision → originating_change_id → ChangeRequest.lead_id`), OR `instance.started_by`. Task `active`. Audit `task_due_date_set` with old/new in `new_values`.
- Produces (API, all under the existing router; `ValueError` → 400, missing task → 404 handled in service or router consistently with existing complete-task route):
  - `POST /workflow-instances/{instance_id}/tasks/{task_id}/accept` → `WfInstanceTaskResponse`
  - `POST /workflow-instances/{instance_id}/tasks/{task_id}/assign` body `AssignTaskRequest {user_id: int}` → `WfInstanceTaskResponse`
  - `PUT /workflow-instances/{instance_id}/tasks/{task_id}/due-date` body `DueDateRequest {due_date: datetime}` → `WfInstanceTaskResponse`
- Produces (schema): `WfInstanceTaskResponse` gains `owner_id: int | None`, `owner_name: str | None`, `accepted_at: datetime | None`, `due_date: datetime | None`, `overdue: bool` — populated wherever the router serializes tasks (find the existing task→response mapping used by `GET /{instance_id}` / `GET /revisions/{revision_id}/current` and add the five fields; `owner_name`/`overdue` come from the model properties, safe because `owner` is selectin).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_task_ownership.py`:

```python
async def _active_task(session_factory, inst_id):
    from app.models.workflow import WfInstanceTask
    async with session_factory() as s:
        return (await s.execute(select(WfInstanceTask.id).where(
            WfInstanceTask.instance_id == inst_id,
            WfInstanceTask.status == "active",
            WfInstanceTask.is_actionable == True,  # noqa: E712
        ))).scalars().first()


async def test_accept_assign_task_api(client, eng_auth, admin_auth, seed,
                                      session_factory, part, two_stage_template):
    from app.services.workflow_service import WorkflowService
    async with session_factory() as s:
        inst = await WorkflowService.start_workflow(
            s, part["revision_id"], two_stage_template["template_id"],
            seed["engineer_id"])
        await s.commit()
        inst_id = inst.id
    task_id = await _active_task(session_factory, inst_id)

    # engineer is a member of "Stamp Dept" (fixture) -> can accept
    res = await client.post(
        f"/api/v1/workflow-instances/{inst_id}/tasks/{task_id}/accept",
        headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["owner_id"] == seed["engineer_id"]
    assert body["accepted_at"] is not None
    assert body["owner_name"]

    # admin (not a member, but admin) reassigns to the engineer -> allowed, resets accepted_at
    res = await client.post(
        f"/api/v1/workflow-instances/{inst_id}/tasks/{task_id}/assign",
        json={"user_id": seed["engineer_id"]}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["accepted_at"] is None

    # assigning a non-member is refused
    res = await client.post(
        f"/api/v1/workflow-instances/{inst_id}/tasks/{task_id}/assign",
        json={"user_id": seed["admin_id"]}, headers=admin_auth)
    assert res.status_code == 400
    assert "member" in res.json()["detail"].lower()


async def test_accept_conflict_and_audit(client, eng_auth, admin_auth, seed,
                                         session_factory, part, two_stage_template):
    from app.services.workflow_service import WorkflowService
    from app.models.workflow import UserDepartment
    from app.models.entities import AuditLog
    async with session_factory() as s:
        # make admin a dept member too, so the conflict path (not authz) is hit
        s.add(UserDepartment(user_id=seed["admin_id"],
                             department_id=two_stage_template["dept_id"]))
        inst = await WorkflowService.start_workflow(
            s, part["revision_id"], two_stage_template["template_id"],
            seed["engineer_id"])
        await s.commit()
        inst_id = inst.id
    task_id = await _active_task(session_factory, inst_id)

    r1 = await client.post(
        f"/api/v1/workflow-instances/{inst_id}/tasks/{task_id}/accept",
        headers=eng_auth)
    assert r1.status_code == 200, r1.text
    r2 = await client.post(
        f"/api/v1/workflow-instances/{inst_id}/tasks/{task_id}/accept",
        headers=admin_auth)
    assert r2.status_code == 400
    assert "owned" in r2.json()["detail"].lower()

    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "wf_instance",
            AuditLog.action == "task_accepted"))).scalars().all()
    assert len(rows) == 1


async def test_due_date_authz(client, eng_auth, admin_auth, seed,
                              session_factory, part, two_stage_template):
    from app.services.workflow_service import WorkflowService
    from datetime import timedelta
    async with session_factory() as s:
        inst = await WorkflowService.start_workflow(
            s, part["revision_id"], two_stage_template["template_id"],
            seed["engineer_id"])
        await s.commit()
        inst_id = inst.id
    task_id = await _active_task(session_factory, inst_id)
    new_due = (datetime.utcnow() + timedelta(days=14)).isoformat()

    # engineer started the instance -> allowed
    res = await client.put(
        f"/api/v1/workflow-instances/{inst_id}/tasks/{task_id}/due-date",
        json={"due_date": new_due}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["due_date"].startswith(new_due[:10])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_task_ownership.py -v`
Expected: new tests FAIL with 404/405 (routes missing).

- [ ] **Step 3: Implement the service methods**

In `backend/app/services/workflow_service.py` (imports: `UserDepartment` from app.models.workflow; `timedelta` already added in Task 2):

```python
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
        task = await WorkflowService._load_open_task(db, task_id)
        if actor.role != "admin" and not await WorkflowService._is_department_member(
                db, actor.id, task.department_id):
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
            await NotificationService.notify_users(
                db, [assignee_id], title=f"Task assigned: {step_name}",
                link="/my-tasks")
        return task

    @staticmethod
    async def set_task_due_date(db: AsyncSession, task_id: int,
                                due_date: datetime, actor) -> WfInstanceTask:
        from app.models.change import ChangeRequest
        task = await WorkflowService._load_open_task(db, task_id)
        allowed = actor.role == "admin" or task.instance.started_by == actor.id
        if not allowed:
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
```

- [ ] **Step 4: Implement schemas + routes**

`backend/app/schemas/workflow.py` — `WfInstanceTaskResponse` gains:

```python
    owner_id: int | None = None
    owner_name: str | None = None
    accepted_at: datetime | None = None
    due_date: datetime | None = None
    overdue: bool = False
```

and add near the other request models:

```python
class AssignTaskRequest(BaseModel):
    user_id: int


class DueDateRequest(BaseModel):
    due_date: datetime
```

`backend/app/api/v1/workflows/workflow_instances.py` — find how the existing complete-task route serializes its response and mirror it; add (after the complete route):

```python
@router.post("/{instance_id}/tasks/{task_id}/accept")
async def accept_task(
    instance_id: int, task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        task = await WorkflowService.accept_task(db, task_id, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return await _task_response(db, task)


@router.post("/{instance_id}/tasks/{task_id}/assign")
async def assign_task(
    instance_id: int, task_id: int, body: AssignTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        task = await WorkflowService.assign_task(db, task_id, body.user_id, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return await _task_response(db, task)


@router.put("/{instance_id}/tasks/{task_id}/due-date")
async def set_task_due_date(
    instance_id: int, task_id: int, body: DueDateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        task = await WorkflowService.set_task_due_date(
            db, task_id, body.due_date, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return await _task_response(db, task)
```

`_task_response(db, task)` is whatever helper the file needs to produce a `WfInstanceTaskResponse` dict with `step_name`/`department_name` — READ the existing `GET /{instance_id}` serializer first; if it builds task dicts inline, extract that into `_task_response` and reuse (do not duplicate the mapping). Extend the serializer (both the shared helper and any other task-serialization site) with the five new fields (`owner_id`, `owner_name`, `accepted_at`, `due_date`, `overdue` — the latter two from the model properties). Also update the task-not-found mapping: `ValueError("Task not found")` should surface as 404, not 400 — match how the complete-task route treats missing tasks today (if it 400s, keep 400 for consistency and note it).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_task_ownership.py tests/test_workflows.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/workflow_service.py \
        backend/app/api/v1/workflows/workflow_instances.py \
        backend/app/schemas/workflow.py backend/tests/test_task_ownership.py
git commit -m "feat(ownership): accept/assign/due-date for workflow tasks with audit + notification"
```

---

## Task 4: Assessment accept / assign / due-date — service + API

**Tier:** sonnet (mirror of Task 3 on the change side).

**Files:**
- Modify: `backend/app/services/change_service.py`, `backend/app/api/v1/changes/changes.py`, `backend/app/schemas/change.py`
- Test: `backend/tests/test_assessment_ownership.py` (extend)

**Interfaces:**
- Produces (`@staticmethod` on `ChangeService`, raising `ChangeError`):
  - `accept_assessment(session, change, assessment_id: int, user) -> ChangeAssessment` — row must belong to the change and have `status == "active"`; user admin or member of the row's department (reuse `WorkflowService._is_department_member` via function-local import); conflict rule identical to tasks. Changelog action `assessment_accepted`.
  - `assign_assessment(session, change, assessment_id: int, assignee_id: int, actor) -> ChangeAssessment` — actor admin, department member, or the change lead; assignee active member of the department. Sets owner, clears `accepted_at`. Changelog `assessment_assigned`; notify assignee (`link=f"/changes/{change.id}"`, skip self).
  - `set_assessment_due_date(session, change, assessment_id: int, due_date, actor) -> ChangeAssessment` — actor admin or change lead. Changelog `assessment_due_date_set` with old/new.
- Produces (API; lead/admin/member checks INSIDE the service, router only 404s the change):
  - `POST /changes/{change_id}/assessments/{assessment_id}/accept`
  - `POST /changes/{change_id}/assessments/{assessment_id}/assign` body `{user_id}`
  - `PUT /changes/{change_id}/assessments/{assessment_id}/due-date` body `{due_date}`
  All return the updated `AssessmentResponse`.
- Produces (schema): `AssessmentResponse` in `backend/app/schemas/change.py` gains `owner_id: Optional[int] = None`, `owner_name: Optional[str] = None`, `accepted_at: Optional[datetime] = None`, `due_date: Optional[datetime] = None`, `overdue: bool = False` (all served by `from_attributes` via the model's columns/properties).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_assessment_ownership.py`:

```python
async def _first_active_assessment(session_factory, change_id):
    from app.models.change import ChangeAssessment
    async with session_factory() as s:
        return (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change_id,
            ChangeAssessment.status == "active"))).scalars().first()


async def test_accept_and_assign_assessment(client, eng_auth, admin_auth, seed,
                                            session_factory, part):
    from app.models.workflow import UserDepartment
    change = await _routed_change(client, eng_auth, seed, session_factory,
                                  part["part_id"])
    a = await _first_active_assessment(session_factory, change["id"])
    async with session_factory() as s:
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=a.department_id))
        await s.commit()

    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments/{a.id}/accept",
        headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["owner_id"] == seed["engineer_id"]
    assert body["accepted_at"] is not None

    # admin assigns back to engineer -> accepted_at cleared
    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments/{a.id}/assign",
        json={"user_id": seed["engineer_id"]}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["accepted_at"] is None

    # non-member assignee refused
    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments/{a.id}/assign",
        json={"user_id": seed["admin_id"]}, headers=admin_auth)
    assert res.status_code == 400


async def test_assessment_due_date_lead_only(client, eng_auth, admin_auth, seed,
                                             session_factory, part):
    from datetime import datetime, timedelta
    change = await _routed_change(client, eng_auth, seed, session_factory,
                                  part["part_id"])
    a = await _first_active_assessment(session_factory, change["id"])
    new_due = (datetime.utcnow() + timedelta(days=3)).isoformat()

    # engineer IS the lead (fixture sets lead_id) -> allowed
    res = await client.put(
        f"/api/v1/changes/{change['id']}/assessments/{a.id}/due-date",
        json={"due_date": new_due}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["due_date"] is not None

    # ownership events are in the changelog/audit
    from app.models.entities import AuditLog
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).where(
            AuditLog.correlation_id == change["change_number"],
            AuditLog.action == "assessment_due_date_set"))).scalars().all()
    assert len(rows) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_assessment_ownership.py -v`
Expected: FAIL with 404/405.

- [ ] **Step 3: Implement service methods**

In `backend/app/services/change_service.py` (near `submit_assessment`):

```python
    @staticmethod
    async def _get_assessment(session: AsyncSession, change: ChangeRequest,
                              assessment_id: int) -> ChangeAssessment:
        a = await session.get(ChangeAssessment, assessment_id)
        if a is None or a.change_id != change.id:
            raise ChangeError("Assessment not found on this change")
        if a.status != "active":
            raise ChangeError("Assessment is not active")
        return a

    @staticmethod
    async def accept_assessment(session: AsyncSession, change: ChangeRequest,
                                assessment_id: int, user) -> ChangeAssessment:
        from app.services.workflow_service import WorkflowService
        a = await ChangeService._get_assessment(session, change, assessment_id)
        if user.role != "admin" and not await WorkflowService._is_department_member(
                session, user.id, a.department_id):
            raise ChangeError("Only members of the assessed department may accept")
        if a.owner_id is not None and a.owner_id != user.id:
            raise ChangeError("Assessment is already owned by another user")
        a.owner_id = user.id
        a.accepted_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "assessment_accepted",
            f"Assessment {a.id} accepted", user.id,
            new_value={"assessment_id": a.id, "owner_id": user.id})
        return a

    @staticmethod
    async def assign_assessment(session: AsyncSession, change: ChangeRequest,
                                assessment_id: int, assignee_id: int,
                                actor) -> ChangeAssessment:
        from app.models.entities import User
        from app.services.workflow_service import WorkflowService
        a = await ChangeService._get_assessment(session, change, assessment_id)
        allowed = (actor.role == "admin" or change.lead_id == actor.id
                   or await WorkflowService._is_department_member(
                       session, actor.id, a.department_id))
        if not allowed:
            raise ChangeError(
                "Only an admin, the change lead, or a department member may assign")
        assignee = await session.get(User, assignee_id)
        if assignee is None or not assignee.is_active:
            raise ChangeError("Assignee not found or inactive")
        if not await WorkflowService._is_department_member(
                session, assignee_id, a.department_id):
            raise ChangeError("Assignee must be a member of the assessed department")
        a.owner_id = assignee_id
        a.accepted_at = None
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "assessment_assigned",
            f"Assessment {a.id} assigned to user {assignee_id}", actor.id,
            new_value={"assessment_id": a.id, "owner_id": assignee_id})
        if assignee_id != actor.id:
            from app.services.notification_service import NotificationService
            await NotificationService.notify_users(
                session, [assignee_id],
                title=f"Assessment assigned: {change.change_number}",
                link=f"/changes/{change.id}")
        return a

    @staticmethod
    async def set_assessment_due_date(session: AsyncSession, change: ChangeRequest,
                                      assessment_id: int, due_date: datetime,
                                      actor) -> ChangeAssessment:
        a = await ChangeService._get_assessment(session, change, assessment_id)
        if actor.role != "admin" and change.lead_id != actor.id:
            raise ChangeError("Only the change lead or an admin may set due dates")
        old = a.due_date.isoformat() if a.due_date else None
        a.due_date = due_date
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "assessment_due_date_set",
            f"Assessment {a.id} due date set", actor.id,
            old_value={"due_date": old},
            new_value={"assessment_id": a.id, "due_date": due_date.isoformat()})
        return a
```

(`ChangeAssessment` is already imported in this file; check and mirror the `append_changelog` kwarg types used at existing call sites.)

- [ ] **Step 4: Implement schema + routes**

`backend/app/schemas/change.py` — `AssessmentResponse` gains:

```python
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    accepted_at: Optional[datetime] = None
    due_date: Optional[datetime] = None
    overdue: bool = False
```

Reuse `DueDateRequest`/`AssignTaskRequest`? They live in `schemas/workflow.py` — define change-side equivalents locally to avoid a cross-schema import (mirror the file's own style):

```python
class AssessmentAssignIn(BaseModel):
    user_id: int


class AssessmentDueDateIn(BaseModel):
    due_date: datetime
```

`backend/app/api/v1/changes/changes.py` — three routes following the file's idiom (404 change → `ChangeError` → 400 → explicit commit → return ORM object with `response_model=AssessmentResponse`):

```python
@router.post("/{change_id}/assessments/{assessment_id}/accept",
             response_model=AssessmentResponse)
async def accept_assessment(
    change_id: int, assessment_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        a = await ChangeService.accept_assessment(db, change, assessment_id, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(a)
    return a


@router.post("/{change_id}/assessments/{assessment_id}/assign",
             response_model=AssessmentResponse)
async def assign_assessment(
    change_id: int, assessment_id: int, body: AssessmentAssignIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        a = await ChangeService.assign_assessment(
            db, change, assessment_id, body.user_id, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(a)
    return a


@router.put("/{change_id}/assessments/{assessment_id}/due-date",
            response_model=AssessmentResponse)
async def set_assessment_due_date(
    change_id: int, assessment_id: int, body: AssessmentDueDateIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        a = await ChangeService.set_assessment_due_date(
            db, change, assessment_id, body.due_date, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(a)
    return a
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_assessment_ownership.py tests/test_changes.py tests/test_change_routing.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_service.py \
        backend/app/api/v1/changes/changes.py backend/app/schemas/change.py \
        backend/tests/test_assessment_ownership.py
git commit -m "feat(ownership): accept/assign/due-date for change assessments"
```

---

## Task 5: My Tasks backend rework — owner-aware queries

**Tier:** sonnet.

**Files:**
- Modify: `backend/app/services/workflow_service.py` (`get_my_tasks`), `backend/app/api/v1/workflows/workflow_instances.py` (my-tasks route), `backend/app/api/v1/changes/changes.py` (`my_change_tasks`)
- Test: `backend/tests/test_escalations.py` (create — My Tasks section)

**Interfaces:**
- Produces: `WorkflowService.get_my_tasks(db, department_ids: list[int], user_id: int) -> list[dict]` — signature gains `user_id`; each dict gains `owner_id: int | None`, `owner_name: str | None`, `accepted_at: iso | None`, `due_date: iso | None`, `overdue: bool`, `mine: bool` (`owner_id == user_id`). Sort: mine-first, then overdue-first, then `due_date` ascending (None last), then `task_id`. The route passes `current_user.id`.
- Produces: `GET /changes/my-tasks` dicts gain the same six keys (from the assessment row), same sort. Kind stays `"assessment"`.
- The datetime fields serialize the way the existing dict fields do (the current dicts already include `instance_started_at` — mirror its serialization style exactly).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_escalations.py
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update

from tests.test_assessment_ownership import _routed_change

pytestmark = pytest.mark.asyncio


async def test_my_tasks_are_owner_aware(client, eng_auth, seed, session_factory,
                                        part):
    from app.models.workflow import (
        Department, UserDepartment, WfTemplate, WfStage, WfStep, WfStepRasic,
        WfInstanceTask)
    from app.services.workflow_service import WorkflowService

    async with session_factory() as s:
        dept = Department(name="MT Dept", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept.id))
        tmpl = WfTemplate(name="mt-tpl", version=1, is_active=True,
                          created_by=seed["engineer_id"])
        s.add(tmpl)
        await s.flush()
        stage = WfStage(template_id=tmpl.id, stage_order=1, name="S1")
        s.add(stage)
        await s.flush()
        for i in (1, 2):
            step = WfStep(stage_id=stage.id, step_name=f"s{i}", position_in_stage=i)
            s.add(step)
            await s.flush()
            s.add(WfStepRasic(step_id=step.id, department_id=dept.id,
                              rasic_letter="R"))
        await s.commit()
        inst = await WorkflowService.start_workflow(
            s, part["revision_id"], tmpl.id, seed["engineer_id"])
        await s.commit()
        inst_id = inst.id

    # own one of the two tasks and make it overdue
    async with session_factory() as s:
        task_ids = [t for (t,) in await s.execute(
            select(WfInstanceTask.id).where(
                WfInstanceTask.instance_id == inst_id,
                WfInstanceTask.is_actionable == True))]  # noqa: E712
        await s.execute(update(WfInstanceTask).where(WfInstanceTask.id == task_ids[0])
                        .values(owner_id=seed["engineer_id"],
                                accepted_at=datetime.utcnow(),
                                due_date=datetime.utcnow() - timedelta(days=2)))
        await s.commit()

    res = await client.get("/api/v1/workflow-instances/my-tasks", headers=eng_auth)
    assert res.status_code == 200, res.text
    tasks = [t for t in res.json() if t["instance_id"] == inst_id]
    assert len(tasks) == 2
    first, second = tasks[0], tasks[1]
    assert first["mine"] is True and first["overdue"] is True
    assert first["owner_name"]
    assert second["mine"] is False and second["owner_id"] is None


async def test_change_my_tasks_owner_fields(client, eng_auth, seed,
                                            session_factory, part):
    from app.models.workflow import UserDepartment
    from app.models.change import ChangeAssessment
    change = await _routed_change(client, eng_auth, seed, session_factory,
                                  part["part_id"])
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"],
            ChangeAssessment.status == "active"))).scalars().first()
        s.add(UserDepartment(user_id=seed["engineer_id"],
                             department_id=a.department_id))
        a.owner_id = seed["engineer_id"]
        a.due_date = datetime.utcnow() - timedelta(hours=1)
        await s.commit()

    res = await client.get("/api/v1/changes/my-tasks", headers=eng_auth)
    assert res.status_code == 200, res.text
    mine = [t for t in res.json() if t["change_id"] == change["id"]]
    assert mine and mine[0]["mine"] is True and mine[0]["overdue"] is True
    assert mine[0]["due_date"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_escalations.py -v`
Expected: FAIL with KeyError `'mine'` (or TypeError on get_my_tasks signature once modified).

- [ ] **Step 3: Implement**

`get_my_tasks` — add the `user_id: int` parameter, add to each dict:

```python
            "owner_id": t.owner_id,
            "owner_name": t.owner_name,
            "accepted_at": t.accepted_at,
            "due_date": t.due_date,
            "overdue": t.overdue,
            "mine": t.owner_id == user_id,
```

and after building the list, sort:

```python
        results.sort(key=lambda d: (
            not d["mine"], not d["overdue"],
            d["due_date"] is None, d["due_date"] or datetime.max, d["task_id"]))
```

(the `owner` relationship is `lazy="selectin"` so `owner_name` is safe here; adapt the variable names to the function's actual loop). Update the two call sites (`my-tasks` route passes `current_user.id`; check `open-task-count` — it does NOT call get_my_tasks, leave it).

`my_change_tasks` in `changes.py` — extend the select to return the `ChangeAssessment` object (it already does), add the same six keys to the dict from the assessment row, and apply the same sort (key on `assessment_id` instead of `task_id`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_escalations.py tests/test_workflows.py tests/test_changes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/workflow_service.py \
        backend/app/api/v1/workflows/workflow_instances.py \
        backend/app/api/v1/changes/changes.py backend/tests/test_escalations.py
git commit -m "feat(ownership): owner-aware My Tasks with mine/overdue flags and deterministic sort"
```

---

## Task 6: Lead escalations endpoint

**Tier:** opus (cross-entity roll-up query).

**Files:**
- Modify: `backend/app/services/change_service.py`, `backend/app/api/v1/changes/changes.py`
- Test: `backend/tests/test_escalations.py` (extend)

**Interfaces:**
- Produces: `ChangeService.lead_escalations(session, user_id: int) -> list[dict]` — for every non-terminal change where `lead_id == user_id`, collect:
  - overdue assessments (`status == "active"`, `due_date < utcnow`) → `{"kind": "assessment", "change_id", "change_number", "change_title", "label": <department name>, "owner_id", "owner_name", "due_date": iso, "days_overdue": int}`
  - overdue check-WF tasks: revisions with `originating_change_id` in those change ids → active `WfInstance` → `WfInstanceTask` where `status == "active"`, `is_actionable`, `due_date < utcnow` → `{"kind": "wf_task", ... "label": <step name>, ...}` (same keys).
  - Sorted by `days_overdue` descending.
- Produces: `GET /api/v1/changes/my-escalations` → that list, any authenticated user (empty when leading nothing). REGISTER BEFORE `/{change_id}` routes (next to `my-tasks`).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_escalations.py`:

```python
async def test_lead_escalations_roll_up(client, eng_auth, seed, session_factory,
                                        part, check_wf_standards):
    """Engineer leads a change with an overdue assessment AND an overdue check-WF
    task -> both appear in /changes/my-escalations, worst first."""
    from app.models.change import ChangeAssessment, ChangeRequest
    from app.models.change_cost import ChangeGate
    from app.models.workflow import WfInstanceTask, WfInstance
    from app.models.part import PartRevision
    from app.services.change_service import ChangeService

    change = await _routed_change(client, eng_auth, seed, session_factory,
                                  part["part_id"])

    # overdue assessment (5 days)
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"],
            ChangeAssessment.status == "active"))).scalars().first()
        a.due_date = datetime.utcnow() - timedelta(days=5)
        # drive the change to in_implementation directly to spawn the check WF
        c = await s.get(ChangeRequest, change["id"])
        c.status = "approved"
        await s.execute(update(ChangeGate).where(ChangeGate.change_id == c.id)
                        .values(decision="yes"))
        await s.commit()

    async with session_factory() as s:
        c = await ChangeService.get_change(s, change["id"])
        await ChangeService.transition(s, c, "in_implementation",
                                       seed["engineer_id"])
        await s.commit()

    # make one spawned WF task overdue (2 days)
    async with session_factory() as s:
        rev_id = (await s.execute(select(PartRevision.id).where(
            PartRevision.originating_change_id == change["id"]))).scalars().first()
        task_id = (await s.execute(
            select(WfInstanceTask.id)
            .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
            .where(WfInstance.part_revision_id == rev_id,
                   WfInstanceTask.status == "active",
                   WfInstanceTask.is_actionable == True)  # noqa: E712
        )).scalars().first()
        await s.execute(update(WfInstanceTask).where(WfInstanceTask.id == task_id)
                        .values(due_date=datetime.utcnow() - timedelta(days=2)))
        await s.commit()

    res = await client.get("/api/v1/changes/my-escalations", headers=eng_auth)
    assert res.status_code == 200, res.text
    rows = res.json()
    kinds = [r["kind"] for r in rows]
    assert "assessment" in kinds and "wf_task" in kinds
    assert rows[0]["days_overdue"] >= rows[-1]["days_overdue"]
    assert rows[0]["days_overdue"] == 5
    assert all(r["change_number"] == change["change_number"] for r in rows
               if r["change_id"] == change["id"])


async def test_escalations_empty_for_non_lead(client, admin_auth):
    res = await client.get("/api/v1/changes/my-escalations", headers=admin_auth)
    assert res.status_code == 200
    assert res.json() == []
```

(Note: the assessment stays `active` while the change moves on — its stage was never completed, which is exactly the escalation scenario. The `check_wf_standards` fixture exists in conftest since Phase B.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_escalations.py -v`
Expected: FAIL with 404 (route missing).

- [ ] **Step 3: Implement the service method**

In `backend/app/services/change_service.py`:

```python
    @staticmethod
    async def lead_escalations(session: AsyncSession, user_id: int) -> list[dict]:
        from app.models.workflow import Department, WfInstance, WfInstanceTask, WfStep

        now = datetime.utcnow()
        changes = (await session.execute(
            select(ChangeRequest).where(
                ChangeRequest.lead_id == user_id,
                ChangeRequest.status.not_in(TERMINAL_STATUSES)))).scalars().all()
        if not changes:
            return []
        by_id = {c.id: c for c in changes}
        out: list[dict] = []

        assessment_rows = (await session.execute(
            select(ChangeAssessment, Department.name)
            .join(Department, Department.id == ChangeAssessment.department_id)
            .where(ChangeAssessment.change_id.in_(by_id.keys()),
                   ChangeAssessment.status == "active",
                   ChangeAssessment.due_date.is_not(None),
                   ChangeAssessment.due_date < now))).all()
        for a, dept_name in assessment_rows:
            c = by_id[a.change_id]
            out.append({
                "kind": "assessment", "change_id": c.id,
                "change_number": c.change_number, "change_title": c.title,
                "label": dept_name, "owner_id": a.owner_id,
                "owner_name": a.owner_name,
                "due_date": a.due_date.isoformat(),
                "days_overdue": (now - a.due_date).days,
            })

        task_rows = (await session.execute(
            select(WfInstanceTask, WfStep.step_name, PartRevision.originating_change_id)
            .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
            .join(PartRevision, PartRevision.id == WfInstance.part_revision_id)
            .join(WfStep, WfStep.id == WfInstanceTask.step_id)
            .where(PartRevision.originating_change_id.in_(by_id.keys()),
                   WfInstance.status == "active",
                   WfInstanceTask.status == "active",
                   WfInstanceTask.is_actionable == True,  # noqa: E712
                   WfInstanceTask.due_date.is_not(None),
                   WfInstanceTask.due_date < now))).all()
        for t, step_name, change_id in task_rows:
            c = by_id[change_id]
            out.append({
                "kind": "wf_task", "change_id": c.id,
                "change_number": c.change_number, "change_title": c.title,
                "label": step_name, "owner_id": t.owner_id,
                "owner_name": t.owner_name,
                "due_date": t.due_date.isoformat(),
                "days_overdue": (now - t.due_date).days,
            })

        out.sort(key=lambda r: r["days_overdue"], reverse=True)
        return out
```

(`TERMINAL_STATUSES` is a module constant in this file; `PartRevision` already imported.)

- [ ] **Step 4: Implement the route**

In `backend/app/api/v1/changes/changes.py`, next to `my-tasks` (BEFORE `/{change_id}` routes):

```python
@router.get("/my-escalations")
async def my_escalations(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await ChangeService.lead_escalations(db, current_user.id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_escalations.py -v && python3 -m pytest`
Expected: escalation tests PASS; full suite PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_service.py \
        backend/app/api/v1/changes/changes.py backend/tests/test_escalations.py
git commit -m "feat(ownership): lead escalation roll-up across overdue assessments and WF tasks"
```

---

## Task 7: Frontend — My Tasks rework (owner/due/overdue, accept, mine-first)

**Tier:** opus (UX-critical).

**Files:**
- Modify: `frontend/src/types/workflow.ts`, `frontend/src/types/change.ts`, `frontend/src/api/changes.ts`, `frontend/src/hooks/queries/useWorkflows.ts`, `frontend/src/pages/MyTasksPage.tsx`, `frontend/src/i18n/cmLabels.ts`
- Test: `frontend/src/pages/MyTasksPage.test.tsx` (create)

**Interfaces:**
- Consumes: Task 5's my-tasks dicts, Task 3's accept endpoint, Task 4's assessment accept endpoint.
- Produces:
  - `MyTask` type += `owner_id: number | null`, `owner_name: string | null`, `accepted_at: string | null`, `due_date: string | null`, `overdue: boolean`, `mine: boolean`.
  - `ChangeTask` type += the same six fields.
  - `useAcceptTask()` mutation in `useWorkflows.ts`: `POST /v1/workflow-instances/{instanceId}/tasks/{taskId}/accept`, invalidates `['workflow','my-tasks']` (prefix) and `['open-task-count']`.
  - `changesApi.acceptAssessment(changeId, assessmentId)` → `POST /v1/changes/{changeId}/assessments/{assessmentId}/accept`; invalidation of `['change-my-tasks']` handled by the caller.
  - MyTasksPage workflow table: new columns Owner (name, or an Accept button when `owner_id === null`) and Due (date, red `⚠` + `overdue` styling when `overdue` — mirror the existing `LessonActionsSection` pattern in the same file); rows already arrive mine-first from the backend — render a subtle left border (`border-l-2 border-sky-500`) on `mine` rows.
  - `ChangeTasksSection`: adds due date + overdue flag + Accept button (when unowned) per row.

- [ ] **Step 1: Types, api, labels**

`frontend/src/types/workflow.ts` — extend `MyTask` (L125-142) with:

```ts
  owner_id: number | null
  owner_name: string | null
  accepted_at: string | null
  due_date: string | null
  overdue: boolean
  mine: boolean
```

`frontend/src/types/change.ts` — extend `ChangeTask` (~L121) with the same six fields.

`frontend/src/api/changes.ts`:

```ts
  acceptAssessment: (changeId: number, assessmentId: number) =>
    client.post(`/v1/changes/${changeId}/assessments/${assessmentId}/accept`)
      .then(r => r.data),
```

`frontend/src/hooks/queries/useWorkflows.ts`:

```ts
export function useAcceptTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ instanceId, taskId }: { instanceId: number; taskId: number }) =>
      client.post(`/v1/workflow-instances/${instanceId}/tasks/${taskId}/accept`)
        .then(r => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflow', 'my-tasks'] })
      queryClient.invalidateQueries({ queryKey: ['open-task-count'] })
    },
  })
}
```

(match the file's existing import of the axios client and mutation idioms).

`frontend/src/i18n/cmLabels.ts`:

```ts
  'tasks.owner': { de: 'Verantwortlich', en: 'Owner' },
  'tasks.due': { de: 'Fällig', en: 'Due' },
  'tasks.overdue': { de: 'überfällig', en: 'overdue' },
  'tasks.accept': { de: 'Übernehmen', en: 'Accept' },
  'tasks.unclaimed': { de: 'Nicht übernommen', en: 'Unclaimed' },
  'tasks.mine': { de: 'Meine', en: 'Mine' },
```

- [ ] **Step 2: Write the failing test**

```tsx
// frontend/src/pages/MyTasksPage.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import MyTasksPage from './MyTasksPage'

const clientMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('../api/changes', () => ({
  changesApi: { myTasks: vi.fn().mockResolvedValue([]), acceptAssessment: vi.fn() },
}))

const myTask = (over: Record<string, unknown>) => ({
  task_id: 1, instance_id: 9, status: 'active', is_actionable: true,
  rasic_letter: 'R', department_name: 'IE', step_name: 'do it',
  stage_order: 1, stage_name: 'S1', part_id: 4, part_number: 'P-1',
  part_name: 'Housing', project_id: 2, revision_id: 7, revision_name: 'ECR1.1',
  instance_started_at: '2026-07-01T00:00:00',
  owner_id: null, owner_name: null, accepted_at: null,
  due_date: '2026-06-30T00:00:00', overdue: true, mine: false,
  ...over,
})

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
}

describe('MyTasksPage ownership', () => {
  beforeEach(() => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('/workflow-instances/my-tasks'))
        return Promise.resolve({ data: [
          myTask({ task_id: 1, mine: true, owner_id: 5, owner_name: 'Eva Eng' }),
          myTask({ task_id: 2, step_name: 'unclaimed step', overdue: false,
                   due_date: '2026-07-30T00:00:00' }),
        ] })
      return Promise.resolve({ data: [] })
    })
    clientMocks.post.mockResolvedValue({ data: {} })
  })
  afterEach(cleanup)

  it('shows owner, overdue flag, and Accept on unclaimed rows', async () => {
    wrap(<MyTasksPage />)
    expect(await screen.findByText('Eva Eng')).toBeDefined()
    expect(screen.getByText(/overdue/)).toBeDefined()
    const accept = screen.getByRole('button', { name: /Accept/ })
    fireEvent.click(accept)
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith(
      '/v1/workflow-instances/9/tasks/2/accept'))
  })
})
```

(Adapt the two `vi.mock` targets to MyTasksPage's REAL imports before finalizing — read the file first: if sections fetch via inline `client.get`, the client mock above is the one that matters; if `useMyTasks` imports the client differently, mirror it. The page also renders SEP/lesson sections that hit other URLs — the catch-all `{ data: [] }` covers them.)

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/MyTasksPage.test.tsx`
Expected: FAIL (no owner column / Accept button yet).

- [ ] **Step 4: Implement the page changes**

In `frontend/src/pages/MyTasksPage.tsx`:

1. Import `useAcceptTask` and `t`; import `changesApi` is already there.
2. Workflow table (main section, ~L241+): add `<th>` for `{t('tasks.owner')}` and `{t('tasks.due')}` after the Stage column. Per row:

```tsx
<td className="px-3 py-2">
  {task.owner_id !== null ? (
    <span className="text-slate-200">{task.owner_name}</span>
  ) : (
    <button
      onClick={() => acceptTask.mutate({ instanceId: task.instance_id, taskId: task.task_id })}
      className="px-2 py-0.5 rounded bg-sky-700 hover:bg-sky-600 text-sky-100 text-xs"
    >
      {t('tasks.accept')}
    </button>
  )}
</td>
<td className="px-3 py-2 text-sm">
  {task.due_date ? (
    <span className={task.overdue ? 'text-red-400 font-semibold' : 'text-slate-300'}>
      {new Date(task.due_date).toLocaleDateString()}
      {task.overdue && <span className="ml-1">⚠ {t('tasks.overdue')}</span>}
    </span>
  ) : (
    <span className="text-slate-500">—</span>
  )}
</td>
```

with `const acceptTask = useAcceptTask()` in the component; add `className={task.mine ? 'border-l-2 border-sky-500' : ''}` to the row (merge with any existing row classes).
3. `ChangeTasksSection` (~L189): add due-date display (same pattern) and an Accept button when `t.owner_id === null` calling `changesApi.acceptAssessment(t.change_id, t.assessment_id)` in a `useMutation` that invalidates `['change-my-tasks']`.

- [ ] **Step 5: Run tests + full frontend verification**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all tests PASS (39+); zero NEW tsc errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/types/change.ts \
        frontend/src/api/changes.ts frontend/src/hooks/queries/useWorkflows.ts \
        frontend/src/pages/MyTasksPage.tsx frontend/src/pages/MyTasksPage.test.tsx \
        frontend/src/i18n/cmLabels.ts
git commit -m "feat(frontend): owner-aware My Tasks with accept, due dates, overdue flags"
```

---

## Task 8: Frontend — WorkflowProgress ownership + Escalations card

**Tier:** opus (UX-critical).

**Files:**
- Create: `frontend/src/components/EscalationsCard.tsx`, `frontend/src/components/EscalationsCard.test.tsx`
- Modify: `frontend/src/components/workflows/WorkflowProgress.tsx`, `frontend/src/types/workflow.ts`, `frontend/src/api/changes.ts`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/MyTasksPage.tsx`, `frontend/src/i18n/cmLabels.ts`
- Test: `frontend/src/components/EscalationsCard.test.tsx`

**Interfaces:**
- Consumes: Task 3's extended `WfInstanceTaskResponse` (owner fields now in the instance payload), Task 6's `GET /v1/changes/my-escalations`, Task 7's `useAcceptTask`.
- Produces:
  - `WfInstanceTask` type (`frontend/src/types/workflow.ts` ~L93-108) += `owner_id: number | null`, `owner_name: string | null`, `accepted_at: string | null`, `due_date: string | null`, `overdue: boolean`.
  - `Escalation` type in `frontend/src/types/workflow.ts`:

```ts
export interface Escalation {
  kind: 'assessment' | 'wf_task'
  change_id: number
  change_number: string
  change_title: string
  label: string
  owner_id: number | null
  owner_name: string | null
  due_date: string
  days_overdue: number
}
```

  - `changesApi.myEscalations(): Promise<Escalation[]>` → `client.get('/v1/changes/my-escalations').then(r => r.data)`.
  - `<EscalationsCard />` — self-fetching (`useQuery({ queryKey: ['my-escalations'], queryFn: changesApi.myEscalations, refetchInterval: 60_000 })`), renders NOTHING when empty (`return null`), else a red-accented panel (`bg-slate-800 border border-red-900/60`) titled `t('esc.title')`, one row per escalation: `⚠ {change_number} — {label}`, owner name or `t('tasks.unclaimed')`, `{days_overdue}d {t('tasks.overdue')}` in `text-red-400`, and a link to `/changes/{change_id}` (`react-router-dom` `Link`).
  - Mounted on `Dashboard.tsx` (top of the content area) and on `MyTasksPage.tsx` (above the sections).
  - `WorkflowProgress.tsx` `TaskRow`: for active actionable tasks show owner chip (`owner_name` in a slate pill) or an Accept button (via `useAcceptTask`, additionally invalidating the revision-workflow key — pass `onAccepted` or invalidate `['workflow']` prefix); show due date with red overdue styling next to the step name (same pattern as Task 7).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/EscalationsCard.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import EscalationsCard from './EscalationsCard'
import { changesApi } from '../api/changes'

vi.mock('../api/changes', () => ({
  changesApi: { myEscalations: vi.fn() },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
}

describe('EscalationsCard', () => {
  afterEach(cleanup)

  it('renders nothing when there are no escalations', async () => {
    vi.mocked(changesApi.myEscalations).mockResolvedValue([])
    const { container } = wrap(<EscalationsCard />)
    await new Promise(r => setTimeout(r, 0))
    expect(container.textContent).toBe('')
  })

  it('lists overdue items with change link and owner', async () => {
    vi.mocked(changesApi.myEscalations).mockResolvedValue([
      { kind: 'wf_task', change_id: 3, change_number: 'CR-2026-0009',
        change_title: 'Tool fix', label: 'Werkzeugänderung umsetzen',
        owner_id: 5, owner_name: 'Eva Eng', due_date: '2026-06-28T00:00:00',
        days_overdue: 4 },
      { kind: 'assessment', change_id: 3, change_number: 'CR-2026-0009',
        change_title: 'Tool fix', label: 'Quality', owner_id: null,
        owner_name: null, due_date: '2026-06-30T00:00:00', days_overdue: 2 },
    ])
    wrap(<EscalationsCard />)
    expect(await screen.findByText(/CR-2026-0009/)).toBeDefined()
    expect(screen.getByText('Eva Eng')).toBeDefined()
    expect(screen.getByText(/Unclaimed/)).toBeDefined()
    expect(screen.getByText(/4d overdue/)).toBeDefined()
    const links = screen.getAllByRole('link')
    expect(links.some(l => l.getAttribute('href') === '/changes/3')).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/EscalationsCard.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

`frontend/src/i18n/cmLabels.ts`:

```ts
  'esc.title': { de: 'Eskalationen — überfällig in meinen Changes', en: 'Escalations — overdue in my changes' },
```

```tsx
// frontend/src/components/EscalationsCard.tsx
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { changesApi } from '../api/changes'
import { t } from '../i18n/cmLabels'

export default function EscalationsCard() {
  const { data } = useQuery({
    queryKey: ['my-escalations'],
    queryFn: changesApi.myEscalations,
    refetchInterval: 60_000,
  })
  if (!data || data.length === 0) return null
  return (
    <div className="bg-slate-800 rounded-lg border border-red-900/60 p-4">
      <h3 className="text-red-300 font-semibold mb-2">⚠ {t('esc.title')}</h3>
      <ul className="space-y-1">
        {data.map((e, i) => (
          <li key={`${e.kind}-${i}`} className="flex items-center gap-2 text-sm flex-wrap">
            <Link to={`/changes/${e.change_id}`}
                  className="text-sky-400 hover:text-sky-300 font-medium">
              {e.change_number}
            </Link>
            <span className="text-slate-300">{e.label}</span>
            <span className="text-slate-400">
              {e.owner_name ?? t('tasks.unclaimed')}
            </span>
            <span className="text-red-400 font-semibold">
              {e.days_overdue}d {t('tasks.overdue')}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
```

Add `myEscalations` to `changesApi`, the `Escalation` type, and the `WfInstanceTask` type fields. Mount `<EscalationsCard />` at the top of `Dashboard.tsx`'s content and above the sections in `MyTasksPage.tsx`. Extend `WorkflowProgress.tsx` `TaskRow` per the Interfaces block (owner pill / Accept button / due+overdue text — reuse the exact class patterns from Task 7's snippets; read the component's actual row layout first and place the chip group after the step name).

- [ ] **Step 4: Run tests + full frontend verification**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS, zero new tsc errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EscalationsCard.tsx \
        frontend/src/components/EscalationsCard.test.tsx \
        frontend/src/components/workflows/WorkflowProgress.tsx \
        frontend/src/types/workflow.ts frontend/src/api/changes.ts \
        frontend/src/pages/Dashboard.tsx frontend/src/pages/MyTasksPage.tsx \
        frontend/src/i18n/cmLabels.ts
git commit -m "feat(frontend): escalations card + task ownership in workflow progress"
```

---

## Task 9: Final verification

**Tier:** sonnet (verification), opus (whole-branch review — dispatched by the controller per SDD).

**Files:** none (fix regressions where they surface).

- [ ] **Step 1: Full backend suite**

Run: `cd backend && python3 -m pytest`
Expected: all PASS (180+).

- [ ] **Step 2: Migration idempotency**

Run: `cd backend && alembic upgrade head && alembic upgrade head`
Expected: both exit 0.

- [ ] **Step 3: Frontend suite + types + scoped lint**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS; zero NEW tsc errors (≈30 pre-existing in untouched files).
Run: `npm run lint 2>&1 | grep -E "MyTasksPage|EscalationsCard|WorkflowProgress|useWorkflows"`
Expected: zero errors in Phase C-touched files (repo-wide lint has known pre-existing failures — out of scope).

- [ ] **Step 4: Spec cross-check (manual)**

- `owner_id`, `due_date`, `accepted_at` on assessments AND WF instance tasks → Task 1.
- Due dates on every step at activation → Task 2.
- Accept or assign, audited → Tasks 3/4.
- Overdue computation → model properties (Task 1) surfaced in My Tasks (5/7), instance payloads (3/8), escalations (6/8).
- Escalation surfacing to the change lead (dashboard + My Tasks) → Tasks 6/8.
- My Tasks reflects ownership, not just department membership → Tasks 5/7.

- [ ] **Step 5: Live smoke (controller dispatches, mirroring Phase B)**

Boot the real backend, then over HTTP: accept a task, assign it (check the assignee notification row), set a due date in the past directly in the DB, confirm `my-tasks` shows `overdue: true` and mine-first sort, and `/changes/my-escalations` lists it for the lead. Kill the server after.

- [ ] **Step 6: Commit any verification fixes**

```bash
git add <explicit paths only>
git commit -m "test: Phase C verification fixes"
```

(Skip if nothing changed. NEVER `git add -A`.)
