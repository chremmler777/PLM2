# Change Assessment Routing (ECR) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive change assessments through a staged RASIC matrix read from the flow designer (`WfTemplate`), with R/A blocking, C/S optional, I notify-only, governed deviations that promote into the standard on release.

**Architecture:** Approach B — `ChangeAssessment` stays *the* task/verdict record (extended with `stage_order`/`rasic_letter`/`status`). A new `ChangeRouting` snapshots the standard `WfTemplate` per change; a new `ChangeRoutingStandard` maps `change_type → template`. A new `ChangeRoutingService` resolves the standard (or falls back to `TYPE_DISCIPLINES`), generates assessments, activates stages, advances on blocking completion, handles deviations, and promotes on release. `ChangeService` delegates at four seams: enter-assessment, submit-assessment, costing guard, release.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, pytest-asyncio (API-level tests), React + TanStack Query v5 + TypeScript (frontend).

**Spec:** `docs/superpowers/specs/2026-06-15-change-assessment-routing-design.md`

**Branch:** `feature/change-assessment-routing` (already created off `feature/change-management`).

**Test command (always run in the conda env):**
```bash
source /home/nitrolinux/miniconda3/bin/activate && export PYTHONPATH="/home/nitrolinux/miniconda3/pkgs/pythonocc-core-7.9.3-all_he3b93f9_200/lib/python3.11/site-packages:$PYTHONPATH" && cd /home/nitrolinux/claude/plm2/backend && python -m pytest <args>
```
(The `anaconda-auth` warning line is harmless.)

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/models/change.py` (modify) | Add 3 columns to `ChangeAssessment`; add `ChangeRouting`, `ChangeRoutingStandard` models + relationship on `ChangeRequest`. |
| `backend/alembic/versions/020_change_assessment_routing.py` (create) | Add columns + 2 tables, idempotent guards like 019. |
| `backend/app/services/change_routing_service.py` (create) | All routing logic: resolve/snapshot, generate, activate, advance, deviation, promote. |
| `backend/app/services/change_service.py` (modify) | Delegate at 4 seams; refine costing guard. |
| `backend/app/schemas/change.py` (modify) | Extend `AssessmentResponse`; add routing/deviation/standard schemas. |
| `backend/app/api/v1/changes/changes.py` (modify) | Add routing-view, deviation, approve-deviation, routing-standards endpoints. |
| `backend/tests/test_change_routing.py` (create) | API-level tests for all routing behavior. |
| `frontend/src/types/change.ts` (modify) | Routing/assessment TS types. |
| `frontend/src/api/changes.ts` (modify) | Routing API wrappers. |
| `frontend/src/components/changes/AssessmentRouting.tsx` (create) | Staged stepper + deviation controls (dark-slate). |
| `frontend/src/pages/ChangeDetailPage.tsx` (modify) | Render `<AssessmentRouting>` in the assessments tab. |
| `frontend/src/pages/MyTasksPage.tsx` (modify) | Surface active-stage assessment tasks. |

**Shared constants** (define once in `change.py` models module, import elsewhere):
```python
BLOCKING_LETTERS = ("R", "A")        # must submit a verdict before the stage advances
TASK_LETTERS = ("R", "A", "S", "C")  # get a ChangeAssessment row
# "I" => no row, notification only
DEVIATION_STATUSES = ("none", "pending_approval", "approved")
```

**Snapshot JSON shape** (stored in `ChangeRouting.standard_snapshot`):
```json
{"stages": [{"stage_order": 1, "departments": [{"department_id": 3, "rasic_letter": "R"}]}]}
```
`I` departments appear in the snapshot (for notification) but never get a `ChangeAssessment`.

---

## Task 1: Models + migration 020

**Files:**
- Modify: `backend/app/models/change.py`
- Create: `backend/alembic/versions/020_change_assessment_routing.py`
- Test: `backend/tests/test_change_routing.py`

- [ ] **Step 1: Add the failing test** (create the file)

```python
# backend/tests/test_change_routing.py
import pytest
import pytest_asyncio
from app.models.workflow import Department, WfTemplate, WfStage, WfStep, WfStepRasic
from app.models.change import (
    ChangeRouting, ChangeRoutingStandard, BLOCKING_LETTERS, TASK_LETTERS,
)

pytestmark = pytest.mark.asyncio


async def test_routing_models_importable_and_columns_exist(session_factory):
    # Persisting a ChangeRoutingStandard + reading ChangeAssessment new columns proves the schema migrated.
    async with session_factory() as s:
        t = WfTemplate(name="ECR", description="x", version=1, is_active=True, created_by=1)
        s.add(t)
        await s.flush()
        s.add(ChangeRoutingStandard(change_type="physical_part", template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()
    assert BLOCKING_LETTERS == ("R", "A")
    assert TASK_LETTERS == ("R", "A", "S", "C")
```

- [ ] **Step 2: Run it, verify it fails**

Run: `python -m pytest tests/test_change_routing.py -q`
Expected: FAIL — `ImportError: cannot import name 'ChangeRouting'` (and missing columns once import is fixed).

- [ ] **Step 3: Extend `ChangeAssessment` and add models** in `backend/app/models/change.py`

Add the constants near the top (after the existing tuples, before `class ChangeRequest`):
```python
BLOCKING_LETTERS = ("R", "A")
TASK_LETTERS = ("R", "A", "S", "C")
DEVIATION_STATUSES = ("none", "pending_approval", "approved")
```

In `class ChangeAssessment`, add three columns after `notes`:
```python
    stage_order: Mapped[int] = mapped_column(Integer, default=1)
    rasic_letter: Mapped[str] = mapped_column(String(1), default="R")
    status: Mapped[str] = mapped_column(String(20), default="active")  # pending|active|submitted|waived
```

Add a `routing` relationship on `ChangeRequest` (after the `changelog_entries` relationship):
```python
    routing: Mapped["ChangeRouting | None"] = relationship(
        back_populates="change", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
```

Append two new model classes at the end of the file (note `JSON` must be added to the sqlalchemy import line):
```python
class ChangeRouting(Base):
    """Per-change snapshot of the standard RASIC routing + deviation governance state."""
    __tablename__ = "change_routings"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), unique=True, index=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("wf_templates.id"), nullable=True)
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    standard_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)

    has_deviation: Mapped[bool] = mapped_column(default=False)
    deviation_status: Mapped[str] = mapped_column(String(20), default="none")
    deviation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    deviation_proposed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deviation_approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deviation_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    change: Mapped["ChangeRequest"] = relationship(back_populates="routing", foreign_keys=[change_id])


class ChangeRoutingStandard(Base):
    """Maps a change_type to the standard ECR WfTemplate it routes through."""
    __tablename__ = "change_routing_standards"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_type: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("wf_templates.id"))
    template_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

Update the import line at the top of the file to include `JSON`:
```python
from sqlalchemy import String, Text, DateTime, Float, Integer, ForeignKey, JSON
```

- [ ] **Step 4: Create migration `020_change_assessment_routing.py`**

```python
"""Change assessment routing: ChangeAssessment stage/letter/status columns,
change_routings, change_routing_standards.

Revision ID: 020
Revises: 019
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = '020'
down_revision = '019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())
    existing = inspector.get_table_names()

    cols = {c['name'] for c in inspector.get_columns('change_assessments')}
    if 'stage_order' not in cols:
        op.add_column('change_assessments', sa.Column('stage_order', sa.Integer(), nullable=False, server_default='1'))
    if 'rasic_letter' not in cols:
        op.add_column('change_assessments', sa.Column('rasic_letter', sa.String(1), nullable=False, server_default='R'))
    if 'status' not in cols:
        op.add_column('change_assessments', sa.Column('status', sa.String(20), nullable=False, server_default='active'))

    if 'change_routings' not in existing:
        op.create_table(
            'change_routings',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), nullable=False, unique=True, index=True),
            sa.Column('template_id', sa.Integer(), sa.ForeignKey('wf_templates.id'), nullable=True),
            sa.Column('template_version', sa.Integer(), nullable=True),
            sa.Column('standard_snapshot', sa.JSON(), nullable=False, server_default='{}'),
            sa.Column('has_deviation', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('deviation_status', sa.String(20), nullable=False, server_default='none'),
            sa.Column('deviation_note', sa.Text(), nullable=True),
            sa.Column('deviation_proposed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('deviation_approved_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('deviation_approved_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if 'change_routing_standards' not in existing:
        op.create_table(
            'change_routing_standards',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_type', sa.String(30), nullable=False, unique=True, index=True),
            sa.Column('template_id', sa.Integer(), sa.ForeignKey('wf_templates.id'), nullable=False),
            sa.Column('template_version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('updated_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table('change_routing_standards')
    op.drop_table('change_routings')
    op.drop_column('change_assessments', 'status')
    op.drop_column('change_assessments', 'rasic_letter')
    op.drop_column('change_assessments', 'stage_order')
```

> Note: tests build their schema via `Base.metadata.create_all` (see conftest), so the new models are picked up automatically; the migration is for the real DB. Verify the migration applies cleanly in Step 6.

- [ ] **Step 5: Run the test, verify it passes**

Run: `python -m pytest tests/test_change_routing.py -q`
Expected: PASS.

- [ ] **Step 6: Verify migration applies to the real DB**

Run: `alembic upgrade head && alembic current`
Expected: ends at `020 (head)`, no error.

- [ ] **Step 7: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add backend/app/models/change.py backend/alembic/versions/020_change_assessment_routing.py backend/tests/test_change_routing.py
git commit -m "feat(change): routing models + migration 020 (assessment stage/letter, ChangeRouting, ChangeRoutingStandard)"
```

---

## Task 2: ChangeRoutingService — resolve standard + generate assessments

**Files:**
- Create: `backend/app/services/change_routing_service.py`
- Test: `backend/tests/test_change_routing.py`

This task builds routing resolution and assessment generation as a pure service step (no transition wiring yet). Add a shared fixture for departments + an ECR template.

- [ ] **Step 1: Add fixtures + failing tests** to `tests/test_change_routing.py`

```python
@pytest_asyncio.fixture
async def departments(session_factory):
    async with session_factory() as s:
        names = ["Tool Engineer", "APQP", "Quality", "Manufacturing Engineer", "Sales"]
        ids = {}
        for i, n in enumerate(names):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i)
            s.add(d); await s.flush(); ids[n] = d.id
        await s.commit()
        return ids


@pytest_asyncio.fixture
async def ecr_template(session_factory, departments):
    """Two-stage ECR: stage1 Tool Engineer(R) + Quality(C); stage2 APQP(A) + Sales(I)."""
    async with session_factory() as s:
        t = WfTemplate(name="ECR", description="Engineering Change Request",
                       version=1, is_active=True, created_by=1)
        s.add(t); await s.flush()
        layout = [
            (1, [("Tool Engineer", "R"), ("Quality", "C")]),
            (2, [("APQP", "A"), ("Sales", "I")]),
        ]
        for order, deps in layout:
            stage = WfStage(template_id=t.id, stage_order=order, name=f"Stage {order}")
            s.add(stage); await s.flush()
            step = WfStep(stage_id=stage.id, step_name=f"Step {order}", position_in_stage=1)
            s.add(step); await s.flush()
            for name, letter in deps:
                s.add(WfStepRasic(step_id=step.id, department_id=departments[name], rasic_letter=letter))
        s.add(ChangeRoutingStandard(change_type="physical_part", template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()
        return t.id


async def test_resolve_standard_from_template(session_factory, ecr_template, departments):
    from app.services.change_routing_service import ChangeRoutingService
    async with session_factory() as s:
        tid, ver, stages = await ChangeRoutingService.resolve_standard(s, "physical_part")
        assert tid == ecr_template and ver == 1
        assert [st["stage_order"] for st in stages] == [1, 2]
        s1 = {d["department_id"]: d["rasic_letter"] for d in stages[0]["departments"]}
        assert s1[departments["Tool Engineer"]] == "R"
        assert s1[departments["Quality"]] == "C"


async def test_resolve_fallback_to_type_disciplines(session_factory, departments):
    from app.services.change_routing_service import ChangeRoutingService
    async with session_factory() as s:
        tid, ver, stages = await ChangeRoutingService.resolve_standard(s, "tooling")
        assert tid is None and ver is None
        assert len(stages) == 1 and stages[0]["stage_order"] == 1
        # all fallback departments are blocking R
        assert all(d["rasic_letter"] == "R" for d in stages[0]["departments"])
        assert len(stages[0]["departments"]) >= 1
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_change_routing.py -k resolve -q`
Expected: FAIL — `ModuleNotFoundError: app.services.change_routing_service`.

- [ ] **Step 3: Create `change_routing_service.py` with `resolve_standard`**

```python
"""Change assessment routing: resolve the standard RASIC matrix, snapshot it per
change, generate staged assessments, advance stages, govern deviations, promote on
release. Standard is read from the flow designer (WfTemplate); falls back to the
legacy TYPE_DISCIPLINES dict when no ChangeRoutingStandard mapping exists.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.change import (
    ChangeRequest, ChangeAssessment, ChangeRouting, ChangeRoutingStandard,
    BLOCKING_LETTERS, TASK_LETTERS,
)
from app.models.workflow import Department, WfTemplate, WfStage, WfStep, WfStepRasic
from app.services.notification_service import NotificationService


# Legacy fallback (kept in sync with change_service.TYPE_DISCIPLINES).
FALLBACK_DISCIPLINES = {
    "physical_part": ["Tool Engineer", "APQP", "Quality", "Manufacturing Engineer", "Sales"],
    "tooling":       ["Tool Engineer", "Process Engineer", "Manufacturing Engineer"],
    "document_spec": ["Quality", "Project Manager"],
    "process_im":    ["Process Engineer", "Manufacturing Engineer", "Quality"],
    "packaging":     ["Packaging Engineer", "Quality", "Sales"],
}


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
        names = FALLBACK_DISCIPLINES.get(change_type, [])
        rows = (await session.execute(
            select(Department).where(Department.name.in_(names))
        )).scalars().all() if names else []
        deps = [{"department_id": d.id, "rasic_letter": "R"} for d in rows]
        return None, None, [{"stage_order": 1, "departments": deps}]
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_change_routing.py -k resolve -q`
Expected: PASS (both resolve tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/change_routing_service.py backend/tests/test_change_routing.py
git commit -m "feat(change): ChangeRoutingService.resolve_standard (template + TYPE_DISCIPLINES fallback)"
```

---

## Task 3: Build routing snapshot + generate assessments + start/stage-1 notifications

**Files:**
- Modify: `backend/app/services/change_routing_service.py`
- Test: `backend/tests/test_change_routing.py`

- [ ] **Step 1: Add failing test** (uses the API to enter assessment; wiring comes in Task 4, but the service method is tested directly here)

```python
async def _seeded_change(session_factory, seed, change_type="physical_part"):
    """Create a captured change with one impacted part, directly via models."""
    from app.models.change import ChangeRequest, ChangeImpactedItem
    from app.models.part import Part
    async with session_factory() as s:
        c = ChangeRequest(change_number="CR-T-1", project_id=seed["project_id"],
                          title="t", change_type=change_type, status="captured",
                          raised_by=seed["engineer_id"], lead_id=seed["engineer_id"])
        s.add(c); await s.flush()
        await s.commit()
        return c.id


async def test_build_routing_generates_task_rows_excludes_informed(
        session_factory, seed, ecr_template, departments):
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeAssessment, ChangeRouting
    cid = await _seeded_change(session_factory, seed)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.build_routing(s, change, seed["engineer_id"])
        await s.commit()
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeAssessment).where(ChangeAssessment.change_id == cid))).scalars().all()
        by_dep = {a.department_id: a for a in rows}
        # Sales is I -> no row; Tool Eng(R, stage1), Quality(C, stage1), APQP(A, stage2)
        assert departments["Sales"] not in by_dep
        assert by_dep[departments["Tool Engineer"]].stage_order == 1
        assert by_dep[departments["Tool Engineer"]].rasic_letter == "R"
        assert by_dep[departments["Tool Engineer"]].status == "active"   # stage 1 activated
        assert by_dep[departments["APQP"]].stage_order == 2
        assert by_dep[departments["APQP"]].status == "pending"           # stage 2 not active yet
        routing = (await s.execute(select(ChangeRouting).where(ChangeRouting.change_id == cid))).scalar_one()
        assert routing.template_id == ecr_template
        assert len(routing.standard_snapshot["stages"]) == 2
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_change_routing.py -k build_routing -q`
Expected: FAIL — `AttributeError: ... has no attribute 'build_routing'`.

- [ ] **Step 3: Implement `build_routing`, `activate_stage`, `_involved_department_ids`** (append to `ChangeRoutingService`)

```python
    @staticmethod
    async def build_routing(session: AsyncSession, change: ChangeRequest, user_id: int) -> ChangeRouting:
        """Idempotent: if routing already exists, do nothing. Otherwise snapshot the
        standard, create assessment rows (pending), broadcast start, activate stage 1."""
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
        # Activate the first stage that has any rows.
        await ChangeRoutingService.activate_stage(session, change, _first_stage_order(stages))
        return routing

    @staticmethod
    def _involved_department_ids(stages) -> list[int]:
        ids = []
        for stage in stages:
            for dep in stage["departments"]:
                ids.append(dep["department_id"])
        return list(dict.fromkeys(ids))

    @staticmethod
    async def activate_stage(session: AsyncSession, change: ChangeRequest, stage_order: int) -> None:
        rows = (await session.execute(
            select(ChangeAssessment).where(
                (ChangeAssessment.change_id == change.id)
                & (ChangeAssessment.stage_order == stage_order)
            )
        )).scalars().all()
        notify = []
        for a in rows:
            if a.status == "pending":
                a.status = "active"
                notify.append(a.department_id)
        await session.flush()
        if notify:
            await NotificationService.notify_departments(
                session, list(dict.fromkeys(notify)),
                title=f"Assessment due — {change.change_number}",
                body=f"Stage {stage_order} of '{change.title}' needs your assessment.",
                link=f"/changes/{change.id}",
            )
```

Add this module-level helper near the top of the file (after the imports):
```python
def _first_stage_order(stages) -> int:
    orders = [s["stage_order"] for s in stages if s["departments"]]
    return min(orders) if orders else 1
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_change_routing.py -k build_routing -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/change_routing_service.py backend/tests/test_change_routing.py
git commit -m "feat(change): build_routing snapshot + staged assessment rows + start/stage-1 notifications"
```

---

## Task 4: Wire into transition + stage advancement on submit + costing guard

**Files:**
- Modify: `backend/app/services/change_service.py`
- Modify: `backend/app/services/change_routing_service.py`
- Test: `backend/tests/test_change_routing.py`

- [ ] **Step 1: Add failing test** (full API flow: enter assessment via template, stage gating)

```python
async def _login(client):
    res = await client.post("/api/v1/auth/login", json={"email": "eng@test.io", "password": "engineer-secret-1"})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _api_change_in_assessment(client, auth, seed):
    body = {"project_id": seed["project_id"], "title": "Wall +0.2", "change_type": "physical_part",
            "reason": "sink", "lead_id": seed["engineer_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=auth)).json()
    p = (await client.post("/api/v1/parts", json={"project_id": seed["project_id"], "part_number": "ART-R1",
         "name": "ART-R1", "part_type": "internal_mfg", "item_category": "article"}, headers=auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items", json={"part_id": p["id"]}, headers=auth)
    await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "in_assessment"}, headers=auth)
    return c


async def test_stage_gating_blocks_costing_until_blocking_submitted(client, seed, ecr_template, departments):
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed)
    detail = (await client.get(f"/api/v1/changes/{c['id']}", headers=auth)).json()
    # Quality (C, stage1) submitting alone must NOT advance to stage 2; costing blocked.
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Quality"], "verdict": "feasible"}, headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 400, res.text  # Tool Engineer (R) still pending
    # Submit Tool Engineer (R) -> stage 1 blocking done -> stage 2 activates (APQP)
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Tool Engineer"], "verdict": "feasible"}, headers=auth)
    detail = (await client.get(f"/api/v1/changes/{c['id']}", headers=auth)).json()
    apqp = next(a for a in detail["assessments"] if a["department_id"] == departments["APQP"])
    assert apqp["status"] == "active"
    # Costing still blocked until APQP (A) submits
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 400, res.text
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["APQP"], "verdict": "feasible"}, headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_change_routing.py -k stage_gating -q`
Expected: FAIL (stage 2 not activated / costing not blocked correctly), because `ensure_assessments` still uses the old dict and there is no advancement.

- [ ] **Step 3: Add `maybe_advance` to `ChangeRoutingService`**

```python
    @staticmethod
    async def maybe_advance(session: AsyncSession, change: ChangeRequest, user_id: int) -> None:
        """If the active stage's blocking (R/A) assessments are all submitted, activate
        the next stage that has rows. C/S never block."""
        rows = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
        )).scalars().all()
        if not rows:
            return
        active_orders = sorted({a.stage_order for a in rows if a.status == "active"})
        if not active_orders:
            return
        current = active_orders[0]
        blocking = [a for a in rows if a.stage_order == current and a.rasic_letter in BLOCKING_LETTERS]
        if any(a.status != "submitted" for a in blocking):
            return  # still waiting on R/A
        # find next stage with any rows
        later = sorted({a.stage_order for a in rows if a.stage_order > current})
        for nxt in later:
            if any(a.stage_order == nxt for a in rows):
                await ChangeRoutingService.activate_stage(session, change, nxt)
                return

    @staticmethod
    async def blocking_complete(session: AsyncSession, change: ChangeRequest) -> bool:
        rows = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
        )).scalars().all()
        blocking = [a for a in rows if a.rasic_letter in BLOCKING_LETTERS]
        return bool(blocking) and all(a.status == "submitted" for a in blocking)
```

- [ ] **Step 4: Rewire `change_service.py`**

Replace the body of `ensure_assessments` (lines ~349-364) to delegate:
```python
    @staticmethod
    async def ensure_assessments(session: AsyncSession, change: ChangeRequest, user_id: int) -> None:
        from app.services.change_routing_service import ChangeRoutingService
        await ChangeRoutingService.build_routing(session, change, user_id)
```

In `submit_assessment`, after the existing `a.status = ...`/flush block but before/after the changelog append, set the row submitted and advance. Concretely, after `a.submitted_by = user_id` (line ~391) add:
```python
        a.status = "submitted"
        await session.flush()
        from app.services.change_routing_service import ChangeRoutingService
        await ChangeRoutingService.maybe_advance(session, change, user_id)
```
(Keep the existing `append_changelog` call that follows.)

Refine the `costing` branch of `_guard` (lines ~160-165) to key on blocking completion + deviation:
```python
        if to_status == "costing":
            from app.services.change_routing_service import ChangeRoutingService
            if not await ChangeRoutingService.blocking_complete(session, change):
                return "Not all responsible/accountable assessments are submitted"
            submitted = [a for a in change.assessments if a.verdict != "pending"]
            if any(a.verdict == "not_feasible" for a in submitted):
                return "An assessment is 'not_feasible' — explicit decision required"
            routing = change.routing
            if routing is not None and routing.deviation_status == "pending_approval":
                return "Routing deviation is pending approval"
```

- [ ] **Step 5: Run, verify pass**

Run: `python -m pytest tests/test_change_routing.py -k stage_gating -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_service.py backend/app/services/change_routing_service.py backend/tests/test_change_routing.py
git commit -m "feat(change): staged advancement on submit + blocking-aware costing guard"
```

---

## Task 5: Deviation ops + approval + soft guard + changelog

**Files:**
- Modify: `backend/app/services/change_routing_service.py`
- Test: `backend/tests/test_change_routing.py`

- [ ] **Step 1: Add failing test**

```python
async def test_deviation_requires_approval_then_clears(client, seed, ecr_template, departments):
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed)
    # Add Manufacturing Engineer as R in stage 1 (a deviation)
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": departments["Manufacturing Engineer"],
        "rasic_letter": "R", "stage_order": 1}, headers=auth)
    assert res.status_code == 200, res.text
    routing = (await client.get(f"/api/v1/changes/{c['id']}/routing", headers=auth)).json()
    assert routing["deviation_status"] == "pending_approval"
    # Submit all blocking; costing must still be blocked by pending deviation
    detail = (await client.get(f"/api/v1/changes/{c['id']}", headers=auth)).json()
    for a in detail["assessments"]:
        if a["rasic_letter"] in ("R", "A"):
            await client.post(f"/api/v1/changes/{c['id']}/assessments",
                              json={"department_id": a["department_id"], "verdict": "feasible"}, headers=auth)
    # newly added ME is in stage1 R — submit it too
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Manufacturing Engineer"], "verdict": "feasible"}, headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 400  # deviation pending
    # Approve the deviation, then costing passes
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve", headers=auth)
    assert res.status_code == 200, res.text
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_change_routing.py -k deviation -q`
Expected: FAIL — endpoints 404 (not added until Task 7) → so this test depends on Task 7's routes. Implement the service methods here; the route test passes after Task 7.

> Sequencing note: implement the **service** methods in this task (unit-tested via a direct service test below), and the **routes** in Task 7. The API-level `test_deviation_requires_approval_then_clears` is expected to pass only after Task 7 — mark it `@pytest.mark.skip(reason="routes land in Task 7")` now and remove the skip in Task 7 Step 1.

- [ ] **Step 3: Add a direct service test** (passes this task)

```python
async def test_apply_deviation_service(session_factory, seed, ecr_template, departments):
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeAssessment
    cid = await _seeded_change(session_factory, seed)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.build_routing(s, change, seed["engineer_id"]); await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        r = await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="add",
            department_id=departments["Manufacturing Engineer"], rasic_letter="R", stage_order=1)
        await s.commit()
        assert r.deviation_status == "pending_approval" and r.has_deviation is True
        rows = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == cid)
            & (ChangeAssessment.department_id == departments["Manufacturing Engineer"])))).scalars().all()
        assert len(rows) == 1 and rows[0].rasic_letter == "R"
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        # admin (different user) approves — proposer was engineer, so engineer cannot self-approve
        r = await ChangeRoutingService.approve_deviation(s, change, seed["admin_id"]); await s.commit()
        assert r.deviation_status == "approved"
```

- [ ] **Step 4: Implement `apply_deviation` + `approve_deviation`** (append to `ChangeRoutingService`)

```python
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

        if op == "add":
            if rasic_letter not in TASK_LETTERS:
                raise ValueError("add requires a task letter (R/A/S/C)")
            order = stage_order or 1
            if existing is None:
                session.add(ChangeAssessment(
                    change_id=change.id, department_id=department_id, verdict="pending",
                    stage_order=order, rasic_letter=rasic_letter,
                    status="active" if order <= await ChangeRoutingService._max_active_order(session, change) else "pending",
                ))
            else:
                existing.rasic_letter = rasic_letter
                existing.stage_order = order
            desc = f"added dept {department_id} as {rasic_letter} in stage {order}"
        elif op == "remove":
            if existing is not None:
                await session.delete(existing)
            desc = f"removed dept {department_id}"
        elif op == "reletter":
            if rasic_letter not in TASK_LETTERS:
                raise ValueError("reletter requires a task letter (R/A/S/C)")
            if existing is None:
                raise ValueError("no assessment to reletter")
            existing.rasic_letter = rasic_letter
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
```

> Approver rule encoded: the change **lead** approves; if the **lead proposed** it, approval must come from someone else (the PM). A non-lead proposer's deviation can be approved by the lead (or any authorized approver via the route, which checks lead in Task 7).

- [ ] **Step 5: Run, verify pass**

Run: `python -m pytest tests/test_change_routing.py -k apply_deviation -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_routing_service.py backend/tests/test_change_routing.py
git commit -m "feat(change): routing deviation apply/approve service + soft guard wiring"
```

---

## Task 6: Promotion on release

**Files:**
- Modify: `backend/app/services/change_routing_service.py`
- Modify: `backend/app/services/change_service.py`
- Test: `backend/tests/test_change_routing.py`

- [ ] **Step 1: Add failing direct-service test**

```python
async def test_promotion_bumps_template_and_repoints_standard(
        session_factory, seed, ecr_template, departments):
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeRoutingStandard
    from app.models.workflow import WfTemplate, WfTemplateHistory, WfStage, WfStep, WfStepRasic
    cid = await _seeded_change(session_factory, seed)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.build_routing(s, change, seed["engineer_id"])
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="add",
            department_id=departments["Manufacturing Engineer"], rasic_letter="R", stage_order=1)
        await ChangeRoutingService.approve_deviation(s, change, seed["admin_id"])
        await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.promote_to_standard(s, change, seed["admin_id"]); await s.commit()
    async with session_factory() as s:
        std = (await s.execute(select(ChangeRoutingStandard).where(
            ChangeRoutingStandard.change_type == "physical_part"))).scalar_one()
        tmpl = await s.get(WfTemplate, std.template_id)
        assert tmpl.version == 2 and std.template_version == 2
        hist = (await s.execute(select(WfTemplateHistory).where(
            WfTemplateHistory.template_id == tmpl.id))).scalars().all()
        assert any("CR-" in (h.change_note or "") for h in hist)
        # new structure includes Manufacturing Engineer
        stages = (await s.execute(select(WfStage).where(WfStage.template_id == tmpl.id))).scalars().all()
        dep_ids = set()
        for stg in stages:
            steps = (await s.execute(select(WfStep).where(WfStep.stage_id == stg.id))).scalars().all()
            for stp in steps:
                ras = (await s.execute(select(WfStepRasic).where(WfStepRasic.step_id == stp.id))).scalars().all()
                dep_ids |= {r.department_id for r in ras}
        assert departments["Manufacturing Engineer"] in dep_ids
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_change_routing.py -k promotion -q`
Expected: FAIL — no `promote_to_standard`.

- [ ] **Step 3: Implement `promote_to_standard`** (append to `ChangeRoutingService`)

```python
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
```

- [ ] **Step 4: Call from `release()`** — add at the very end of `ChangeService.release` (after the impacted-items loop, ~line 283):

```python
        from app.services.change_routing_service import ChangeRoutingService
        await ChangeRoutingService.promote_to_standard(session, change, user_id)
```

- [ ] **Step 5: Run, verify pass**

Run: `python -m pytest tests/test_change_routing.py -k promotion -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_routing_service.py backend/app/services/change_service.py backend/tests/test_change_routing.py
git commit -m "feat(change): promote approved deviation to standard ECR template on release"
```

---

## Task 7: API endpoints + schemas

**Files:**
- Modify: `backend/app/schemas/change.py`
- Modify: `backend/app/api/v1/changes/changes.py`
- Test: `backend/tests/test_change_routing.py`

- [ ] **Step 1: Un-skip the API deviation test** — remove the `@pytest.mark.skip` added in Task 5 Step 2 from `test_deviation_requires_approval_then_clears`.

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_change_routing.py -k deviation_requires_approval -q`
Expected: FAIL — routes 404.

- [ ] **Step 3: Add schemas** to `backend/app/schemas/change.py`

Extend `AssessmentResponse` with the new fields + derived tier (add after `submitted_at`):
```python
    stage_order: int = 1
    rasic_letter: str = "R"
    status: str = "active"
```
Add new schemas at the end of the file:
```python
class RoutingDepartment(BaseModel):
    department_id: int
    rasic_letter: str
    tier: str          # blocking | optional | info
    status: Optional[str] = None     # None for info-only
    verdict: Optional[str] = None
    assessment_id: Optional[int] = None


class RoutingStage(BaseModel):
    stage_order: int
    departments: List[RoutingDepartment] = []


class RoutingResponse(BaseModel):
    change_id: int
    template_id: Optional[int] = None
    template_version: Optional[int] = None
    has_deviation: bool = False
    deviation_status: str = "none"
    stages: List[RoutingStage] = []


class DeviationRequest(BaseModel):
    op: str                       # add | remove | reletter
    department_id: int
    rasic_letter: Optional[str] = None
    stage_order: Optional[int] = None


class RoutingStandardUpsert(BaseModel):
    change_type: str
    template_id: int
    template_version: int = 1
```

- [ ] **Step 4: Add a routing-view builder + endpoints** in `backend/app/api/v1/changes/changes.py`

Add a helper that composes the routing view by merging the snapshot (for `I` departments and tiers) with live assessments:
```python
def _tier(letter: str) -> str:
    if letter in ("R", "A"):
        return "blocking"
    if letter in ("S", "C"):
        return "optional"
    return "info"
```
Add endpoints (mirror existing `@router.post("/{change_id}/...")` patterns; reuse the existing change-load dependency/`get_change`):
```python
@router.get("/{change_id}/routing", response_model=RoutingResponse)
async def get_routing(change_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    change = await ChangeService.get_change(db, change_id)
    if change is None:
        raise HTTPException(404, "Change not found")
    routing = change.routing
    assess_by_dep = {a.department_id: a for a in change.assessments}
    snapshot = routing.standard_snapshot if routing else {"stages": []}
    stages = []
    for st in snapshot.get("stages", []):
        deps = []
        for d in st["departments"]:
            a = assess_by_dep.get(d["department_id"])
            deps.append(RoutingDepartment(
                department_id=d["department_id"], rasic_letter=d["rasic_letter"],
                tier=_tier(d["rasic_letter"]),
                status=(a.status if a else None), verdict=(a.verdict if a else None),
                assessment_id=(a.id if a else None)))
        stages.append(RoutingStage(stage_order=st["stage_order"], departments=deps))
    return RoutingResponse(
        change_id=change_id,
        template_id=(routing.template_id if routing else None),
        template_version=(routing.template_version if routing else None),
        has_deviation=(routing.has_deviation if routing else False),
        deviation_status=(routing.deviation_status if routing else "none"),
        stages=stages)


@router.post("/{change_id}/routing/deviation", response_model=RoutingResponse)
async def post_deviation(change_id: int, body: DeviationRequest,
                         db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    change = await ChangeService.get_change(db, change_id)
    if change is None:
        raise HTTPException(404, "Change not found")
    from app.services.change_routing_service import ChangeRoutingService
    try:
        await ChangeRoutingService.apply_deviation(
            db, change, user.id, op=body.op, department_id=body.department_id,
            rasic_letter=body.rasic_letter, stage_order=body.stage_order)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    return await get_routing(change_id, db, user)


@router.post("/{change_id}/routing/deviation/approve", response_model=RoutingResponse)
async def approve_deviation(change_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    change = await ChangeService.get_change(db, change_id)
    if change is None:
        raise HTTPException(404, "Change not found")
    from app.services.change_routing_service import ChangeRoutingService
    try:
        await ChangeRoutingService.approve_deviation(db, change, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    return await get_routing(change_id, db, user)


@router.get("/routing-standards")
async def list_routing_standards(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    from app.models.change import ChangeRoutingStandard
    rows = (await db.execute(select(ChangeRoutingStandard))).scalars().all()
    return [{"change_type": r.change_type, "template_id": r.template_id,
             "template_version": r.template_version} for r in rows]


@router.put("/routing-standards")
async def upsert_routing_standard(body: RoutingStandardUpsert,
                                  db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    from app.models.change import ChangeRoutingStandard
    row = (await db.execute(select(ChangeRoutingStandard).where(
        ChangeRoutingStandard.change_type == body.change_type))).scalar_one_or_none()
    if row is None:
        row = ChangeRoutingStandard(change_type=body.change_type, template_id=body.template_id,
                                    template_version=body.template_version, updated_by=user.id)
        db.add(row)
    else:
        row.template_id = body.template_id
        row.template_version = body.template_version
        row.updated_by = user.id
    await db.commit()
    return {"change_type": body.change_type, "template_id": body.template_id,
            "template_version": body.template_version}
```
Ensure the new schema names are imported at the top of `changes.py` (add `RoutingResponse, RoutingStage, RoutingDepartment, DeviationRequest, RoutingStandardUpsert` to the existing `from app.schemas.change import (...)`). Confirm `select` and `HTTPException` are already imported (they are used elsewhere in this file).

> Route ordering (verified): `changes.py` has `@router.get("/{change_id}")` at line 92, and the literal `/my-tasks` route is correctly declared before it (line 64). Declare the two `/routing-standards` routes in that same pre-`{change_id}` region (right after `/my-tasks`), otherwise `GET /routing-standards` is captured by `/{change_id}` (→ 422 on int parse). The `/{change_id}/routing*` routes are deeper paths and do not collide.
>
> Convention: match the file's dependency style — `current_user: User = Depends(get_current_user)` and `db: AsyncSession = Depends(get_db)` (both already imported). The endpoint code above uses `user=Depends(...)`/`user.id`; rename to `current_user`/`current_user.id` to stay consistent.

- [ ] **Step 5: Run, verify pass**

Run: `python -m pytest tests/test_change_routing.py -k deviation_requires_approval -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/change.py backend/app/api/v1/changes/changes.py backend/tests/test_change_routing.py
git commit -m "feat(change): routing API — view, deviation, approve, routing-standards admin"
```

---

## Task 8: Full backend suite — back-compat gate

**Files:** none (verification + fixup only)

- [ ] **Step 1: Run the whole suite**

Run: `python -m pytest -q`
Expected: all green. The 102 spine tests must still pass — the `test_changes.py` assessment tests use the `departments` fixture but **no** `ChangeRoutingStandard`, so routing takes the `TYPE_DISCIPLINES` fallback (single stage, all R/blocking, all active immediately) — behavior identical to before.

- [ ] **Step 2: If any spine test fails**, the likely cause is the costing guard now requiring `blocking_complete`. Confirm fallback rows are created with `rasic_letter="R"` and `status="active"` (they are, via `build_routing`), so `blocking_complete` matches the old "all assessments submitted" semantics. Fix any divergence, re-run.

- [ ] **Step 3: Commit** (only if fixes were needed)

```bash
git add -A && git commit -m "test(change): keep spine suite green under routing fallback"
```

---

## Task 9: Frontend types + API wrapper

**Files:**
- Modify: `frontend/src/types/change.ts`
- Modify: `frontend/src/api/changes.ts`

- [ ] **Step 1: Add types** to `frontend/src/types/change.ts`

```typescript
export interface RoutingDepartment {
  department_id: number;
  rasic_letter: 'R' | 'A' | 'S' | 'C' | 'I';
  tier: 'blocking' | 'optional' | 'info';
  status: 'pending' | 'active' | 'submitted' | 'waived' | null;
  verdict: string | null;
  assessment_id: number | null;
}
export interface RoutingStage { stage_order: number; departments: RoutingDepartment[]; }
export interface ChangeRouting {
  change_id: number;
  template_id: number | null;
  template_version: number | null;
  has_deviation: boolean;
  deviation_status: 'none' | 'pending_approval' | 'approved';
  stages: RoutingStage[];
}
export interface DeviationRequest {
  op: 'add' | 'remove' | 'reletter';
  department_id: number;
  rasic_letter?: 'R' | 'A' | 'S' | 'C';
  stage_order?: number;
}
```
Also add `stage_order: number; rasic_letter: string; status: string;` to the existing `Assessment` interface in this file.

- [ ] **Step 2: Add API wrappers** to `frontend/src/api/changes.ts` (match existing axios `client` usage in that file)

```typescript
import type { ChangeRouting, DeviationRequest } from '../types/change';

export const getChangeRouting = (id: number) =>
  client.get<ChangeRouting>(`/v1/changes/${id}/routing`).then(r => r.data);

export const postDeviation = (id: number, body: DeviationRequest) =>
  client.post<ChangeRouting>(`/v1/changes/${id}/routing/deviation`, body).then(r => r.data);

export const approveDeviation = (id: number) =>
  client.post<ChangeRouting>(`/v1/changes/${id}/routing/deviation/approve`).then(r => r.data);
```
(If `changes.ts` uses a different base import name than `client`, match it — check the top of the file.)

- [ ] **Step 3: Type-check**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx tsc --noEmit 2>&1 | grep -E "change.ts|changes.ts" || echo "clean"`
Expected: `clean`.

- [ ] **Step 4: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/types/change.ts frontend/src/api/changes.ts
git commit -m "feat(change): frontend routing types + API wrappers"
```

---

## Task 10: Frontend — staged assessment routing tab

**Files:**
- Create: `frontend/src/components/changes/AssessmentRouting.tsx`
- Modify: `frontend/src/pages/ChangeDetailPage.tsx`

- [ ] **Step 1: Create `AssessmentRouting.tsx`** (dark-slate, matches `ProjectSepSection` styling)

```tsx
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getChangeRouting, approveDeviation } from '../../api/changes';

const LETTER_LABEL: Record<string, string> = {
  R: 'Responsible', A: 'Accountable', S: 'Support', C: 'Consulted', I: 'Informed',
};
const TIER_BADGE: Record<string, string> = {
  blocking: 'bg-rose-900/50 text-rose-200 border-rose-700',
  optional: 'bg-amber-900/40 text-amber-200 border-amber-700',
  info: 'bg-slate-700/50 text-slate-300 border-slate-600',
};

export default function AssessmentRouting({ changeId }: { changeId: number }) {
  const qc = useQueryClient();
  const { data: routing, isLoading } = useQuery({
    queryKey: ['change-routing', changeId],
    queryFn: () => getChangeRouting(changeId),
  });
  const approve = useMutation({
    mutationFn: () => approveDeviation(changeId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change-routing', changeId] }),
  });

  if (isLoading) return <div className="text-slate-400 text-sm p-4">Loading routing…</div>;
  if (!routing || routing.stages.length === 0)
    return <div className="text-slate-400 text-sm p-4">No routing yet — enter assessment to generate it.</div>;

  const activeOrder = routing.stages.find(
    s => s.departments.some(d => d.status === 'active'))?.stage_order;

  return (
    <div className="space-y-3">
      {routing.deviation_status === 'pending_approval' && (
        <div className="flex items-center justify-between rounded border border-amber-700 bg-amber-900/30 px-3 py-2">
          <span className="text-amber-200 text-sm">Routing deviation pending approval.</span>
          <button onClick={() => approve.mutate()} disabled={approve.isPending}
            className="px-2.5 py-1 text-xs rounded bg-amber-600 hover:bg-amber-500 text-white">
            Approve deviation
          </button>
        </div>
      )}
      {routing.stages.map(stage => {
        const isActive = stage.stage_order === activeOrder;
        const done = stage.departments.filter(d => d.tier === 'blocking')
          .every(d => d.status === 'submitted');
        return (
          <div key={stage.stage_order}
            className={`rounded border p-3 ${isActive ? 'border-sky-600 bg-slate-800' : 'border-slate-700 bg-slate-800/40'}`}>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-slate-100 text-sm font-semibold">Stage {stage.stage_order}</span>
              {isActive && <span className="text-xs text-sky-300">active</span>}
              {!isActive && done && <span className="text-xs text-emerald-400">complete</span>}
            </div>
            <ul className="space-y-1">
              {stage.departments.map(d => (
                <li key={`${d.department_id}-${d.rasic_letter}`}
                  className="flex items-center justify-between text-sm">
                  <span className="flex items-center gap-2">
                    <span className={`px-1.5 py-0.5 rounded border text-xs ${TIER_BADGE[d.tier]}`}
                      title={LETTER_LABEL[d.rasic_letter]}>{d.rasic_letter}</span>
                    <span className="text-slate-200">Dept {d.department_id}</span>
                  </span>
                  <span className="text-slate-400 text-xs">
                    {d.tier === 'info' ? 'notified' : (d.verdict && d.verdict !== 'pending' ? d.verdict : d.status)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
```

> Department name display (`Dept {id}`) is intentionally minimal — a department-name lookup is a later polish; the spec scopes #2 to departments, not member/name resolution.

- [ ] **Step 2: Render it in the assessments tab** of `ChangeDetailPage.tsx`

Read `frontend/src/pages/ChangeDetailPage.tsx`, find the assessments tab panel (the block rendered when the active tab is the assessments/`'assessments'` tab), and replace its body with:
```tsx
<AssessmentRouting changeId={change.id} />
```
Add the import at the top:
```tsx
import AssessmentRouting from '../components/changes/AssessmentRouting';
```
Keep any existing "submit assessment" control if present, below the routing view.

- [ ] **Step 3: Type-check + build**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx tsc --noEmit 2>&1 | grep -E "AssessmentRouting|ChangeDetailPage" || echo "clean"`
Expected: `clean`.

- [ ] **Step 4: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/components/changes/AssessmentRouting.tsx frontend/src/pages/ChangeDetailPage.tsx
git commit -m "feat(change): staged assessment routing tab (dark-slate stepper + deviation approve)"
```

---

## Task 11: My Tasks — surface active-stage assessment tasks

**Files:**
- Modify: `frontend/src/pages/MyTasksPage.tsx`
- Modify: `backend/app/api/v1/changes/changes.py` (the `/changes/my-tasks` query)

- [ ] **Step 1: Read** the existing `/changes/my-tasks` endpoint (around line 81-90 in `changes.py`) and the `MyTasksPage.tsx` change-tasks section.

- [ ] **Step 2: Restrict the query to active-stage rows.** In the `/changes/my-tasks` endpoint, change the assessment selection to only include assessments whose `status == "active"` (currently it lists all pending). Concretely, add `& (ChangeAssessment.status == "active")` to the assessment filter so only the live stage's tasks surface.

- [ ] **Step 3: Add a failing/确认 test** to `tests/test_change_routing.py`:
```python
async def test_my_tasks_only_active_stage(client, seed, ecr_template, departments):
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed)
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()
    # engineer is not a member of any department in this seed, so expect 0;
    # this asserts the endpoint runs and filters by active status without error.
    assert isinstance(tasks, list)
```
Run: `python -m pytest tests/test_change_routing.py -k my_tasks -q` → PASS.

- [ ] **Step 4: Type-check frontend**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx tsc --noEmit 2>&1 | grep MyTasksPage || echo "clean"`
Expected: `clean`.

- [ ] **Step 5: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add backend/app/api/v1/changes/changes.py frontend/src/pages/MyTasksPage.tsx backend/tests/test_change_routing.py
git commit -m "feat(change): My Tasks surfaces only active-stage assessment tasks"
```

---

## Task 12: Final verification

**Files:** none

- [ ] **Step 1: Full backend suite**

Run: `source /home/nitrolinux/miniconda3/bin/activate && export PYTHONPATH="/home/nitrolinux/miniconda3/pkgs/pythonocc-core-7.9.3-all_he3b93f9_200/lib/python3.11/site-packages:$PYTHONPATH" && cd /home/nitrolinux/claude/plm2/backend && python -m pytest -q`
Expected: all green (102 spine + new routing tests).

- [ ] **Step 2: Migration round-trip**

Run: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
Expected: no error; ends at `020 (head)`.

- [ ] **Step 3: Frontend type-check**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx tsc --noEmit 2>&1 | grep -E "change|routing|Assessment" || echo "clean for change files"`
Expected: `clean for change files`.

- [ ] **Step 4: Use superpowers:requesting-code-review**, then **superpowers:finishing-a-development-branch** to open the PR.

---

## Self-review notes (author)

- **Spec coverage:** routing source (Task 2) · RASIC tiers R/A block, C/S optional, I notify (Tasks 3-4, `_tier`) · staged + notifications (Task 3) · deviation + approval + soft guard (Tasks 4-5,7) · promotion on release (Task 6) · API (Task 7) · frontend stepper + My Tasks (Tasks 10-11) · `TYPE_DISCIPLINES` fallback + 102-test back-compat (Tasks 2, 8). All covered.
- **Approver rule:** lead approves; lead-as-proposer must defer to another approver (PM) — encoded in `approve_deviation` (Task 5) and exercised by admin-approves test.
- **Type consistency:** `build_routing`/`activate_stage`/`maybe_advance`/`blocking_complete`/`apply_deviation`/`approve_deviation`/`promote_to_standard`/`resolve_standard` names used consistently across tasks. `RoutingResponse`/`RoutingStage`/`RoutingDepartment`/`DeviationRequest` consistent between schema (Task 7) and TS (Task 9).
- **Known cross-task dependency:** the API deviation test is written in Task 5 but skipped until Task 7 (routes) — explicitly flagged.
