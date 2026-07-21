# ECM Phase B — Impact Tree, ECN Check Workflows, Ready-to-Go — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the execution half of the change loop: leads pick impacted nodes on an interactive part tree (with BOM-based parent roll-up suggestions), kickoff spawns back-linked ECN revisions each driven by a real check-workflow instance seeded from the spec's "ECN Umsetzung" template (3D-evidence-gated, 4-eyes design check, waivable steps), and "ready to go" becomes a computed fact that guards release.

**Architecture:** `spawn_ecn_revisions` (runs at `approved → in_implementation`) gains two duties: stamp `PartRevision.originating_change_id` and start a `WfInstance` per ECN revision via a new `CheckWorkflowStandard` mapping (`item_category → WfTemplate`). `WorkflowService.complete_task` gains three compliance rules: a `waived` decision (reason required), a 3D-evidence gate on steps flagged `requires_cad_evidence` (CAD `RevisionFile` present OR owner-signed `no_geometry_change` on the revision), and a 4-eyes gate on steps flagged `four_eyes` (approver must differ from the previous stage's completers). `ChangeService.implementation_progress` rolls up per-revision instance status into `ready_to_go`, which `_guard` enforces for `→ released` (soft guard — bypassable only via Phase A's 4-eyes deviation). The impact tree is three new `ChangeService` methods + endpoints; the frontend replaces the read-only impacted tab with a checkbox tree and adds an Implementation tab with per-revision WF status, evidence actions, and a ready-to-go banner.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async (`Mapped`/`mapped_column`), Alembic, Pydantic v2, pytest + pytest-asyncio (`asyncio_mode=auto`); React + TypeScript, @tanstack/react-query, Tailwind (hardcoded dark-slate), vitest + @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-07-02-ecm-lifecycle-design.md` (Phase B row + scope areas 1, 2, the 3D-evidence decision, and workflow-definitions Template 2; Template 1 "ECM Bewertung" is seeded here too because the seeding infrastructure is shared and the spec declares both templates replace the ECR stub).

## Global Constraints

- Run backend tests from `backend/` with `python3 -m pytest` (bare `python` is absent on this host).
- Every new model MUST be imported in `backend/app/models/__init__.py` (tests build schema via `Base.metadata.create_all`).
- New Alembic migration id is `023`, `down_revision = "022"`. Use the idempotent `inspect(op.get_bind())` guard pattern; `sa.String` for enum-like columns; never `.create()` enums; data backfill via `bind.execute(sa.text(...))` (mirror migration 022).
- Enum-like value tuples live as module constants next to the model (mirror `CHANGE_STATUSES` in `app/models/change.py`).
- Audited actions append to the hash-chained changelog via `ChangeService.append_changelog(session, change, action, description, performed_by, *, field_name=None, old_value=None, new_value=None, notes=None)` (dual-writes `AuditLog`), or directly via `AuditService.record(session, *, entity_type, entity_id, action, user_id=None, old_values=None, new_values=None, correlation_id=None, log_level="info")` for non-change entities.
- The `quoted → approved` hard requirements (customer accepted + PM/Quality dual sign-off) remain absolute. All new guards added in this phase go into `_guard` (soft — bypassable only via an approved `ChangeTransitionDeviation`).
- `ChangeService.transition` signature: `transition(session, change, to_status, user_id, *, cancellation_reason=None)`. `ChangeError` maps to HTTP 400 in routers.
- `WorkflowService` signatures: `start_workflow(db, revision_id, template_id, started_by_id)` (raises `ValueError` on conflict/bad template), `complete_task(db, task_id, decision, notes, completed_by_id)`, `get_revision_workflow(db, revision_id)`. `ValueError` maps to HTTP 400 in the workflow router.
- Table names in raw SQL: `change_requests`, `change_impacted_items`, `part_revisions`, `revision_files`, `wf_templates`, `wf_stages`, `wf_steps`, `wf_step_rasic`, `wf_instances`, `wf_instance_tasks`, `wf_departments`, `check_workflow_standards`.
- Test import convention: `from tests.conftest import <helper>`; fixtures `seed` (`{org_id, project_id, admin_id, engineer_id, inactive_id}`), `part` (`{part_id, revision_id}`, `item_category="article"`), `client`, `eng_auth`, `admin_auth`, helper `approve_gates(client, auth, change_id, *keys)`.
- Frontend tests: `cd frontend && npx vitest run <file>`; type-check with `npx tsc --noEmit`. Tests import `describe/it/expect/vi` from `'vitest'` explicitly (`globals: false`); no `jest-dom` matchers. New user-facing strings go into `frontend/src/i18n/cmLabels.ts` (DE/EN).
- Frontend query-key conventions: `['change', changeId, '<sub>']`; mutations invalidate via `qc.invalidateQueries({ queryKey: [...] })`.
- Agent tiering (spec execution guidance): each task carries a **Tier** hint — haiku = mechanical, sonnet = standard feature work, opus = design-critical (state machine, tree algorithm, compliance rules, UX-critical components). Never trade correctness for cost; when in doubt, tier up.

---

## File Structure

**Backend — create:**
- `backend/alembic/versions/023_check_wf_impact_tree.py` — new columns + `check_workflow_standards` table + back-link backfill.
- `backend/app/services/wf_seed_service.py` — seeded "ECM Bewertung" + "ECN Umsetzung (Werkzeug/Artikel)" templates and standard mappings.
- `backend/tests/test_wf_seeds.py`, `backend/tests/test_check_workflow_rules.py`, `backend/tests/test_revision_evidence.py`, `backend/tests/test_impact_tree.py`, `backend/tests/test_change_kickoff.py`, `backend/tests/test_ready_to_go.py`.

**Backend — modify:**
- `backend/app/models/workflow.py` — `CheckWorkflowStandard`, `WfStep.requires_cad_evidence` / `WfStep.four_eyes`, `WF_TASK_DECISIONS` constant.
- `backend/app/models/part.py` — `PartRevision.originating_change_id` + no-geometry-change fields.
- `backend/app/models/__init__.py` — register `CheckWorkflowStandard`.
- `backend/app/services/workflow_service.py` — waive decision, evidence gate, 4-eyes gate, `has_3d_evidence`, audit writes.
- `backend/app/services/change_service.py` — impact-tree methods, kickoff wiring, `implementation_progress`, `_guard` additions.
- `backend/app/api/v1/changes/changes.py` — impact-tree, implementation, check-standards endpoints.
- `backend/app/api/v1/items/revision_files.py` — no-geometry-change sign endpoint.
- `backend/app/schemas/change.py` — `ImpactSuggestIn`, `ImpactSelectionIn`, `CheckStandardIn`, `CheckStandardResponse`.
- `backend/app/main.py` — call `seed_change_workflows` from `seed_test_data`.
- `backend/tests/conftest.py` — `check_wf_standards` fixture + `force_complete_check_workflows` helper.
- `backend/tests/test_changes.py` — adapt the two lifecycle tests to check workflows.

**Frontend — create:**
- `frontend/src/components/changes/ImpactTree.tsx` (+ `ImpactTree.test.tsx`) — checkbox tree with roll-up suggestions and bulk apply.
- `frontend/src/components/changes/ImplementationPanel.tsx` (+ `ImplementationPanel.test.tsx`) — per-revision WF status, evidence actions, ready-to-go banner.

**Frontend — modify:**
- `frontend/src/types/change.ts` — impact-tree + implementation types.
- `frontend/src/types/workflow.ts` — `waived` task status/decision.
- `frontend/src/api/changes.ts` — new endpoints.
- `frontend/src/components/workflows/WorkflowProgress.tsx` — waive-with-reason action.
- `frontend/src/pages/ChangeDetailPage.tsx` — ImpactTree in impacted tab, new implementation tab, ready badge.
- `frontend/src/i18n/cmLabels.ts` — new DE/EN labels.

---

## Task 1: Models + migration 023

**Tier:** sonnet (multi-file model work following established patterns).

**Files:**
- Modify: `backend/app/models/workflow.py`, `backend/app/models/part.py`, `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/023_check_wf_impact_tree.py`
- Test: `backend/tests/test_check_workflow_rules.py` (model section only)

**Interfaces:**
- Produces: `CheckWorkflowStandard` (table `check_workflow_standards`: `id, item_category (unique), template_id FK wf_templates.id, template_version, updated_by, updated_at`), module constants `WF_TASK_DECISIONS = ("approved", "rejected", "waived")` and `CHECK_WF_ITEM_CATEGORIES = ("article", "tool", "assembly_equipment", "eoat", "gauge")` in `app/models/workflow.py`; `WfStep.requires_cad_evidence: bool` and `WfStep.four_eyes: bool` (both default `False`); `PartRevision.originating_change_id: int | None`, `PartRevision.no_geometry_change: bool` (default `False`), `no_geometry_change_by: int | None`, `no_geometry_change_at: datetime | None`, `no_geometry_change_reason: str | None`.
- Consumes: existing `WfTemplate`/`WfStep` and `PartRevision` models.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_check_workflow_rules.py
import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def test_new_model_columns_exist(session_factory, seed):
    from app.models.workflow import (
        CheckWorkflowStandard, WfTemplate, WfStage, WfStep,
        WF_TASK_DECISIONS, CHECK_WF_ITEM_CATEGORIES,
    )
    from app.models.part import PartRevision

    assert "waived" in WF_TASK_DECISIONS
    assert "tool" in CHECK_WF_ITEM_CATEGORIES

    async with session_factory() as s:
        tmpl = WfTemplate(name="cols-check", version=1, is_active=True,
                          created_by=seed["engineer_id"])
        s.add(tmpl)
        await s.flush()
        stage = WfStage(template_id=tmpl.id, stage_order=1, name="S1")
        s.add(stage)
        await s.flush()
        step = WfStep(stage_id=stage.id, step_name="3D", position_in_stage=1)
        s.add(step)
        std = CheckWorkflowStandard(item_category="tool", template_id=tmpl.id)
        s.add(std)
        await s.commit()
        assert step.requires_cad_evidence is False
        assert step.four_eyes is False
        assert std.template_version == 1

    async with session_factory() as s:
        rev = PartRevision(part_id=None, revision_name="X1", phase="ecn",
                           status="draft")
        # column presence check only — no flush needed
        assert rev.no_geometry_change in (False, None)
        assert hasattr(rev, "originating_change_id")
        assert hasattr(rev, "no_geometry_change_by")
        assert hasattr(rev, "no_geometry_change_at")
        assert hasattr(rev, "no_geometry_change_reason")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_check_workflow_rules.py -v`
Expected: FAIL with `ImportError: cannot import name 'CheckWorkflowStandard'`

- [ ] **Step 3: Implement the models**

In `backend/app/models/workflow.py`:

Add near the top (next to `ACTIONABLE_LETTERS`-style constants; after imports):

```python
WF_TASK_STATUSES = ("pending", "active", "approved", "rejected", "noted", "waived")
WF_TASK_DECISIONS = ("approved", "rejected", "waived")
CHECK_WF_ITEM_CATEGORIES = ("article", "tool", "assembly_equipment", "eoat", "gauge")
```

On `WfStep` add (after `position_in_stage`):

```python
    requires_cad_evidence: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    four_eyes: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

(Import `Boolean` from sqlalchemy if not already imported.)

Add a new model after `WfTemplateHistory`:

```python
class CheckWorkflowStandard(Base):
    """Maps a part item_category to the check-workflow template instantiated
    per ECN revision at change kickoff (approved -> in_implementation)."""
    __tablename__ = "check_workflow_standards"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_category: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("wf_templates.id"))
    template_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    template: Mapped["WfTemplate"] = relationship()
```

(Match the import style already used in the file — `String`, `Integer`, `DateTime`, `ForeignKey` are already imported there; add any missing.)

In `backend/app/models/part.py`, on `PartRevision` (after `supersedes_revision_id`):

```python
    # Phase B: bidirectional change link + 3D-evidence sign-off
    originating_change_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("change_requests.id"), nullable=True, index=True)
    no_geometry_change: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    no_geometry_change_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    no_geometry_change_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    no_geometry_change_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

In `backend/app/models/__init__.py`, add `CheckWorkflowStandard` to the workflow import line and `__all__` (mirror how `WfTemplate` is registered).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_check_workflow_rules.py -v`
Expected: PASS

- [ ] **Step 5: Write migration 023**

```python
# backend/alembic/versions/023_check_wf_impact_tree.py
"""Phase B: check_workflow_standards, WfStep evidence/4-eyes flags,
PartRevision change back-link + no-geometry-change sign-off.

Revision ID: 023
Revises: 022
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    if "check_workflow_standards" not in tables:
        op.create_table(
            "check_workflow_standards",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("item_category", sa.String(30), nullable=False, unique=True),
            sa.Column("template_id", sa.Integer(),
                      sa.ForeignKey("wf_templates.id"), nullable=False),
            sa.Column("template_version", sa.Integer(), nullable=False,
                      server_default="1"),
            sa.Column("updated_by", sa.Integer(),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    step_cols = {c["name"] for c in insp.get_columns("wf_steps")}
    if "requires_cad_evidence" not in step_cols:
        op.add_column("wf_steps", sa.Column(
            "requires_cad_evidence", sa.Boolean(), nullable=False,
            server_default=sa.text("0")))
    if "four_eyes" not in step_cols:
        op.add_column("wf_steps", sa.Column(
            "four_eyes", sa.Boolean(), nullable=False, server_default=sa.text("0")))

    rev_cols = {c["name"] for c in insp.get_columns("part_revisions")}
    if "originating_change_id" not in rev_cols:
        op.add_column("part_revisions", sa.Column(
            "originating_change_id", sa.Integer(),
            sa.ForeignKey("change_requests.id"), nullable=True))
    if "no_geometry_change" not in rev_cols:
        op.add_column("part_revisions", sa.Column(
            "no_geometry_change", sa.Boolean(), nullable=False,
            server_default=sa.text("0")))
    if "no_geometry_change_by" not in rev_cols:
        op.add_column("part_revisions", sa.Column(
            "no_geometry_change_by", sa.Integer(),
            sa.ForeignKey("users.id"), nullable=True))
    if "no_geometry_change_at" not in rev_cols:
        op.add_column("part_revisions", sa.Column(
            "no_geometry_change_at", sa.DateTime(), nullable=True))
    if "no_geometry_change_reason" not in rev_cols:
        op.add_column("part_revisions", sa.Column(
            "no_geometry_change_reason", sa.Text(), nullable=True))

    # Backfill back-links for revisions already spawned by in-flight changes.
    bind.execute(sa.text("""
        UPDATE part_revisions
           SET originating_change_id = (
               SELECT cii.change_id FROM change_impacted_items cii
                WHERE cii.resulting_revision_id = part_revisions.id
                LIMIT 1)
         WHERE originating_change_id IS NULL
           AND id IN (SELECT resulting_revision_id FROM change_impacted_items
                       WHERE resulting_revision_id IS NOT NULL)
    """))


def downgrade() -> None:
    op.drop_table("check_workflow_standards")
    op.drop_column("wf_steps", "requires_cad_evidence")
    op.drop_column("wf_steps", "four_eyes")
    op.drop_column("part_revisions", "originating_change_id")
    op.drop_column("part_revisions", "no_geometry_change")
    op.drop_column("part_revisions", "no_geometry_change_by")
    op.drop_column("part_revisions", "no_geometry_change_at")
    op.drop_column("part_revisions", "no_geometry_change_reason")
```

- [ ] **Step 6: Apply the migration to the dev DB and run the full suite**

Run: `cd backend && python3 -m alembic upgrade head && python3 -m pytest`
Expected: migration applies cleanly (idempotent guards make a re-run safe); full suite PASSES (nothing behavioral changed yet).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/workflow.py backend/app/models/part.py \
        backend/app/models/__init__.py \
        backend/alembic/versions/023_check_wf_impact_tree.py \
        backend/tests/test_check_workflow_rules.py
git commit -m "feat(change): check-workflow standard mapping + revision change back-link + evidence/4-eyes step flags"
```

---

## Task 2: Seeded workflow templates + standards + check-standards API

**Tier:** sonnet (data-heavy but pattern-following; the RASIC data is copied verbatim from the spec).

**Files:**
- Create: `backend/app/services/wf_seed_service.py`
- Modify: `backend/app/main.py` (end of `seed_test_data`), `backend/app/api/v1/changes/changes.py`, `backend/app/schemas/change.py`
- Test: `backend/tests/test_wf_seeds.py`

**Interfaces:**
- Produces: `seed_assessment_standard(session) -> None` (Template 1 + `ChangeRoutingStandard` rows for all `CHANGE_TYPES`, create-if-absent), `seed_check_standards(session) -> None` (Templates 2×2 + `CheckWorkflowStandard` rows for all `CHECK_WF_ITEM_CATEGORIES`), `seed_change_workflows(session) -> None` (both). All idempotent (matched by template name / mapping key; never overwrite existing mappings).
- Produces: `GET /api/v1/changes/check-standards` → `list[CheckStandardResponse]`, `PUT /api/v1/changes/check-standards` (admin only, body `CheckStandardIn {item_category, template_id}`).
- Consumes: Task 1's `CheckWorkflowStandard`, `WfStep.requires_cad_evidence`, `WfStep.four_eyes`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_wf_seeds.py
import pytest
from sqlalchemy import select, func

pytestmark = pytest.mark.asyncio


async def test_seed_check_standards_creates_templates_and_mappings(session_factory, seed):
    from app.models.workflow import (
        CheckWorkflowStandard, WfTemplate, WfStage, WfStep,
        CHECK_WF_ITEM_CATEGORIES,
    )
    from app.services.wf_seed_service import seed_check_standards

    async with session_factory() as s:
        await seed_check_standards(s)
        await s.commit()

    async with session_factory() as s:
        cats = {c for (c,) in await s.execute(
            select(CheckWorkflowStandard.item_category))}
        assert cats == set(CHECK_WF_ITEM_CATEGORIES)

        tmpl = (await s.execute(select(WfTemplate).where(
            WfTemplate.name == "ECN Umsetzung (Werkzeug)"))).scalar_one()
        stages = (await s.execute(select(WfStage).where(
            WfStage.template_id == tmpl.id))).scalars().all()
        assert len(stages) == 4

        steps = (await s.execute(
            select(WfStep).join(WfStage, WfStep.stage_id == WfStage.id)
            .where(WfStage.template_id == tmpl.id))).scalars().all()
        evidence = [st for st in steps if st.requires_cad_evidence]
        assert [st.step_name for st in evidence] == ["3D-Daten aktualisieren"]
        four_eyes = [st for st in steps if st.four_eyes]
        assert [st.step_name for st in four_eyes] == ["Konstruktionsprüfung"]


async def test_seed_is_idempotent(session_factory, seed):
    from app.models.workflow import WfTemplate
    from app.services.wf_seed_service import seed_change_workflows

    async with session_factory() as s:
        await seed_change_workflows(s)
        await s.commit()
    async with session_factory() as s:
        n1 = (await s.execute(select(func.count()).select_from(WfTemplate))).scalar()
        await seed_change_workflows(s)
        await s.commit()
        n2 = (await s.execute(select(func.count()).select_from(WfTemplate))).scalar()
    assert n1 == n2


async def test_seed_assessment_standard_maps_all_change_types(session_factory, seed):
    from app.models.change import ChangeRoutingStandard, CHANGE_TYPES
    from app.models.workflow import WfTemplate, WfStage
    from app.services.wf_seed_service import seed_assessment_standard

    async with session_factory() as s:
        await seed_assessment_standard(s)
        await s.commit()

    async with session_factory() as s:
        rows = (await s.execute(select(ChangeRoutingStandard))).scalars().all()
        assert {r.change_type for r in rows} == set(CHANGE_TYPES)
        tmpl = (await s.execute(select(WfTemplate).where(
            WfTemplate.name == "ECM Bewertung"))).scalar_one()
        assert all(r.template_id == tmpl.id for r in rows)
        stages = (await s.execute(select(WfStage).where(
            WfStage.template_id == tmpl.id))).scalars().all()
        assert len(stages) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_wf_seeds.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.wf_seed_service'`

- [ ] **Step 3: Implement the seed service**

```python
# backend/app/services/wf_seed_service.py
"""Seeded change-management workflow templates (spec: workflow definitions,
2026-07-02). Idempotent by template name / mapping key: existing templates and
mappings are never overwritten, so designer edits survive restarts.

Department names must match the names seeded in app.main.seed_test_data;
_get_or_create_department covers fresh test databases.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeRoutingStandard, CHANGE_TYPES
from app.models.entities import User
from app.models.workflow import (
    CheckWorkflowStandard, Department, WfStage, WfStep, WfStepRasic, WfTemplate,
    CHECK_WF_ITEM_CATEGORIES,
)

# RASIC data copied from the spec tables (Template 1 / Template 2).
# Step tuple: (step_name, rasic list[(department, letter)], flags dict)

ECM_BEWERTUNG = {
    "name": "ECM Bewertung",
    "description": "Change-level assessment routing (captured -> approved), D1 matrix",
    "stages": [
        ("Machbarkeit & Bewertung", [
            ("Fachbereichsbewertung", [
                ("Sales", "R"), ("R&D", "R"), ("Tool design", "R"), ("IE", "R"),
                ("Quality", "R"), ("Logistics", "R"), ("Production", "R"),
                ("Purchasing", "R"), ("Production control", "R"),
                ("Project Manager", "A"), ("Planner-Scheduler", "I"),
            ], {}),
        ]),
        ("Summierung & Budget", [
            ("Kostenzusammenfassung prüfen & Budget freigeben", [
                ("Project Manager", "R"), ("Sales", "A"),
                ("R&D", "C"), ("Tool design", "C"),
                ("IE", "I"), ("Quality", "I"), ("Logistics", "I"),
                ("Production", "I"), ("Purchasing", "I"), ("Production control", "I"),
            ], {}),
        ]),
        ("Kundenaktivitäten", [
            ("Angebot an Kunde / Kundenantwort erfassen", [
                ("Sales", "R"), ("Project Manager", "A"),
                ("Quality", "I"), ("R&D", "I"),
            ], {}),
        ]),
    ],
}


def _ecn_umsetzung(name: str, konstruktion_r: str) -> dict:
    return {
        "name": name,
        "description": "Check workflow per impacted ECN revision (kickoff -> ready-to-go)",
        "stages": [
            ("Konstruktion", [
                ("3D-Daten aktualisieren", [
                    (konstruktion_r, "R"), ("R&D", "A"), ("Project Manager", "I"),
                ], {"requires_cad_evidence": True}),
                ("Zeichnungen & Doku aktualisieren", [
                    (konstruktion_r, "R"), ("R&D", "A"), ("Quality", "S"),
                ], {}),
            ]),
            ("Design-Check", [
                ("Konstruktionsprüfung", [
                    ("R&D", "R"), ("Quality", "A"), ("IE", "C"),
                ], {"four_eyes": True}),
            ]),
            ("Industrialisierung", [
                ("Werkzeugänderung umsetzen", [
                    ("Production", "R"), ("Tool design", "A"), ("Production control", "I"),
                ], {}),
                ("Prozess/Arbeitspläne anpassen", [
                    ("IE", "R"), ("Project Manager", "A"), ("Production", "C"),
                ], {}),
                ("Prüfplan / PPAP-Bedarf klären", [
                    ("Quality", "R"), ("Project Manager", "A"), ("Sales", "C"),
                ], {}),
                ("Stammdaten & Logistik aktualisieren", [
                    ("Logistics", "R"), ("Project Manager", "A"),
                    ("Purchasing", "C"), ("Production control", "I"),
                ], {}),
            ]),
            ("Ready to go", [
                ("Bemusterung / Trial", [
                    ("Quality", "R"), ("Project Manager", "A"), ("Production", "S"),
                ], {}),
                ("Finale Freigabe", [
                    ("Project Manager", "R"), ("Quality", "A"),
                    ("Sales", "I"), ("Logistics", "I"), ("Production control", "I"),
                ], {}),
            ]),
        ],
    }


ECN_UMSETZUNG_WERKZEUG = _ecn_umsetzung("ECN Umsetzung (Werkzeug)", "Tool design")
ECN_UMSETZUNG_ARTIKEL = _ecn_umsetzung("ECN Umsetzung (Artikel)", "R&D")

CHECK_WF_CATEGORY_TEMPLATE = {
    "article": "ECN Umsetzung (Artikel)",
    "tool": "ECN Umsetzung (Werkzeug)",
    "assembly_equipment": "ECN Umsetzung (Werkzeug)",
    "eoat": "ECN Umsetzung (Werkzeug)",
    "gauge": "ECN Umsetzung (Werkzeug)",
}


async def _get_or_create_department(session: AsyncSession, name: str) -> Department:
    dept = (await session.execute(
        select(Department).where(Department.name == name))).scalar_one_or_none()
    if dept is None:
        dept = Department(name=name, flow_type="action", is_active=True)
        session.add(dept)
        await session.flush()
    return dept


async def _seed_user_id(session: AsyncSession) -> int:
    uid = (await session.execute(
        select(User.id).where(User.role == "admin").order_by(User.id).limit(1)
    )).scalar_one_or_none()
    if uid is None:
        uid = (await session.execute(
            select(User.id).order_by(User.id).limit(1))).scalar_one()
    return uid


async def _seed_template(session: AsyncSession, spec: dict) -> WfTemplate:
    existing = (await session.execute(
        select(WfTemplate).where(WfTemplate.name == spec["name"]))).scalars().first()
    if existing is not None:
        return existing
    tmpl = WfTemplate(
        name=spec["name"], description=spec["description"], version=1,
        is_active=True, created_by=await _seed_user_id(session),
    )
    session.add(tmpl)
    await session.flush()
    for stage_order, (stage_name, steps) in enumerate(spec["stages"], start=1):
        stage = WfStage(template_id=tmpl.id, stage_order=stage_order, name=stage_name)
        session.add(stage)
        await session.flush()
        for pos, (step_name, rasic, flags) in enumerate(steps, start=1):
            step = WfStep(
                stage_id=stage.id, step_name=step_name, position_in_stage=pos,
                requires_cad_evidence=flags.get("requires_cad_evidence", False),
                four_eyes=flags.get("four_eyes", False),
            )
            session.add(step)
            await session.flush()
            for dept_name, letter in rasic:
                dept = await _get_or_create_department(session, dept_name)
                session.add(WfStepRasic(
                    step_id=step.id, department_id=dept.id, rasic_letter=letter))
    await session.flush()
    return tmpl


async def seed_check_standards(session: AsyncSession) -> None:
    templates = {}
    for spec in (ECN_UMSETZUNG_WERKZEUG, ECN_UMSETZUNG_ARTIKEL):
        templates[spec["name"]] = await _seed_template(session, spec)
    uid = await _seed_user_id(session)
    for category in CHECK_WF_ITEM_CATEGORIES:
        existing = (await session.execute(
            select(CheckWorkflowStandard).where(
                CheckWorkflowStandard.item_category == category)
        )).scalar_one_or_none()
        if existing is None:
            tmpl = templates[CHECK_WF_CATEGORY_TEMPLATE[category]]
            session.add(CheckWorkflowStandard(
                item_category=category, template_id=tmpl.id,
                template_version=tmpl.version, updated_by=uid,
                updated_at=datetime.utcnow(),
            ))
    await session.flush()


async def seed_assessment_standard(session: AsyncSession) -> None:
    tmpl = await _seed_template(session, ECM_BEWERTUNG)
    uid = await _seed_user_id(session)
    for change_type in CHANGE_TYPES:
        existing = (await session.execute(
            select(ChangeRoutingStandard).where(
                ChangeRoutingStandard.change_type == change_type)
        )).scalar_one_or_none()
        if existing is None:
            session.add(ChangeRoutingStandard(
                change_type=change_type, template_id=tmpl.id,
                template_version=tmpl.version, updated_by=uid,
                updated_at=datetime.utcnow(),
            ))
    await session.flush()


async def seed_change_workflows(session: AsyncSession) -> None:
    await seed_assessment_standard(session)
    await seed_check_standards(session)
```

Check `ChangeRoutingStandard` column names before finalizing (`updated_by`, `updated_at` exist per `app/models/change.py:253-262`); drop any kwarg that doesn't exist.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_wf_seeds.py -v`
Expected: PASS

- [ ] **Step 5: Wire startup seeding + check-standards API**

In `backend/app/main.py`, at the end of `seed_test_data()` (inside its session block, after the existing department/rate/activity seeding):

```python
        from app.services.wf_seed_service import seed_change_workflows
        await seed_change_workflows(session)
        await session.commit()
```

(Adapt the session variable name to what `seed_test_data` actually uses.)

In `backend/app/schemas/change.py` add:

```python
class CheckStandardIn(BaseModel):
    item_category: str
    template_id: int


class CheckStandardResponse(BaseModel):
    id: int
    item_category: str
    template_id: int
    template_version: int

    class Config:
        from_attributes = True
```

In `backend/app/api/v1/changes/changes.py`, next to the existing `routing-standards` endpoints (must be declared BEFORE the `/{change_id}` routes, as the routing-standards routes already are):

```python
@router.get("/check-standards", response_model=List[CheckStandardResponse])
async def list_check_standards(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.models.workflow import CheckWorkflowStandard
    rows = (await db.execute(select(CheckWorkflowStandard))).scalars().all()
    return rows


@router.put("/check-standards", response_model=CheckStandardResponse)
async def put_check_standard(
    body: CheckStandardIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.models.workflow import CheckWorkflowStandard, CHECK_WF_ITEM_CATEGORIES, WfTemplate
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    if body.item_category not in CHECK_WF_ITEM_CATEGORIES:
        raise HTTPException(status_code=400, detail="Unknown item_category")
    tmpl = await db.get(WfTemplate, body.template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    row = (await db.execute(select(CheckWorkflowStandard).where(
        CheckWorkflowStandard.item_category == body.item_category))).scalar_one_or_none()
    if row is None:
        row = CheckWorkflowStandard(item_category=body.item_category,
                                    template_id=tmpl.id)
        db.add(row)
    row.template_id = tmpl.id
    row.template_version = tmpl.version
    row.updated_by = current_user.id
    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return row
```

(Reuse the file's existing imports — `select`, `datetime`, `HTTPException` are already there; import the schemas.)

Add an API test to `backend/tests/test_wf_seeds.py`:

```python
async def test_check_standards_api_roundtrip(client, admin_auth, eng_auth, session_factory, seed):
    from app.services.wf_seed_service import seed_check_standards
    from app.models.workflow import WfTemplate
    from sqlalchemy import select
    async with session_factory() as s:
        await seed_check_standards(s)
        await s.commit()
        artikel = (await s.execute(select(WfTemplate).where(
            WfTemplate.name == "ECN Umsetzung (Artikel)"))).scalar_one()

    res = await client.get("/api/v1/changes/check-standards", headers=eng_auth)
    assert res.status_code == 200, res.text
    assert len(res.json()) == 5

    res = await client.put("/api/v1/changes/check-standards",
                           json={"item_category": "tool", "template_id": artikel.id},
                           headers=eng_auth)
    assert res.status_code == 403
    res = await client.put("/api/v1/changes/check-standards",
                           json={"item_category": "tool", "template_id": artikel.id},
                           headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["template_id"] == artikel.id
```

- [ ] **Step 6: Run tests + full suite**

Run: `cd backend && python3 -m pytest tests/test_wf_seeds.py -v && python3 -m pytest`
Expected: new tests PASS; full suite PASS (routing tests create their own standards per-test DB, so the seed does not interfere).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/wf_seed_service.py backend/app/main.py \
        backend/app/api/v1/changes/changes.py backend/app/schemas/change.py \
        backend/tests/test_wf_seeds.py
git commit -m "feat(change): seed ECM Bewertung + ECN Umsetzung templates with RASIC per spec"
```

---

## Task 3: Workflow engine — waive decision + 4-eyes rule + audit writes

**Tier:** opus (state-machine/compliance rules).

**Files:**
- Modify: `backend/app/services/workflow_service.py`
- Test: `backend/tests/test_check_workflow_rules.py` (extend)

**Interfaces:**
- Produces: `complete_task` accepts `decision="waived"` (notes mandatory; task gets `status="waived"`, `decision="waived"`; counts as satisfied for stage advancement). Steps with `four_eyes=True` cannot be approved by a user who completed (approved/waived) any task in the immediately previous stage of the same instance. `start_workflow` and `complete_task` write `AuditLog` rows (`entity_type="wf_instance"`, actions `wf_started` / `task_approved` / `task_rejected` / `task_waived` / `wf_completed`, `correlation_id` = originating change number when the revision belongs to a change).
- Consumes: Task 1's `WfStep.four_eyes`, `PartRevision.originating_change_id`; `AuditService.record`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_check_workflow_rules.py`:

```python
import pytest_asyncio


@pytest_asyncio.fixture
async def rules_template(session_factory, seed):
    """2-stage template: stage 1 evidence-gated step, stage 2 four-eyes step.
    One department carries R in both stages so the same user could act twice."""
    from app.models.workflow import (
        Department, WfTemplate, WfStage, WfStep, WfStepRasic)
    async with session_factory() as s:
        dept = Department(name="Rules Dept", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        tmpl = WfTemplate(name="rules-tpl", version=1, is_active=True,
                          created_by=seed["engineer_id"])
        s.add(tmpl)
        await s.flush()
        st1 = WfStage(template_id=tmpl.id, stage_order=1, name="Konstruktion")
        s.add(st1)
        await s.flush()
        step1 = WfStep(stage_id=st1.id, step_name="3D-Daten aktualisieren",
                       position_in_stage=1, requires_cad_evidence=True)
        s.add(step1)
        await s.flush()
        s.add(WfStepRasic(step_id=step1.id, department_id=dept.id, rasic_letter="R"))
        st2 = WfStage(template_id=tmpl.id, stage_order=2, name="Design-Check")
        s.add(st2)
        await s.flush()
        step2 = WfStep(stage_id=st2.id, step_name="Konstruktionsprüfung",
                       position_in_stage=1, four_eyes=True)
        s.add(step2)
        await s.flush()
        s.add(WfStepRasic(step_id=step2.id, department_id=dept.id, rasic_letter="R"))
        await s.commit()
        return {"template_id": tmpl.id, "dept_id": dept.id}


async def _start_instance(session_factory, seed, part, rules_template):
    from app.services.workflow_service import WorkflowService
    async with session_factory() as s:
        inst = await WorkflowService.start_workflow(
            s, part["revision_id"], rules_template["template_id"],
            seed["engineer_id"])
        await s.commit()
        return inst.id


async def _active_task_id(session_factory, instance_id, stage_order):
    from app.models.workflow import WfInstanceTask
    async with session_factory() as s:
        return (await s.execute(
            select(WfInstanceTask.id).where(
                WfInstanceTask.instance_id == instance_id,
                WfInstanceTask.stage_order == stage_order,
                WfInstanceTask.status == "active"))).scalars().first()


async def test_waive_requires_notes_and_advances_stage(
        session_factory, seed, part, rules_template):
    from app.services.workflow_service import WorkflowService
    inst_id = await _start_instance(session_factory, seed, part, rules_template)
    task_id = await _active_task_id(session_factory, inst_id, 1)

    async with session_factory() as s:
        with pytest.raises(ValueError):
            await WorkflowService.complete_task(s, task_id, "waived", None,
                                                seed["engineer_id"])

    async with session_factory() as s:
        inst = await WorkflowService.complete_task(
            s, task_id, "waived", "document-only change", seed["engineer_id"])
        await s.commit()
        assert inst.current_stage_order == 2


async def test_evidence_gate_blocks_approval_without_evidence(
        session_factory, seed, part, rules_template):
    from app.services.workflow_service import WorkflowService
    from app.models.part import PartRevision
    inst_id = await _start_instance(session_factory, seed, part, rules_template)
    task_id = await _active_task_id(session_factory, inst_id, 1)

    async with session_factory() as s:
        with pytest.raises(ValueError, match="evidence"):
            await WorkflowService.complete_task(s, task_id, "approved", None,
                                                seed["engineer_id"])

    async with session_factory() as s:
        rev = await s.get(PartRevision, part["revision_id"])
        rev.no_geometry_change = True
        await s.commit()

    async with session_factory() as s:
        inst = await WorkflowService.complete_task(
            s, task_id, "approved", None, seed["engineer_id"])
        await s.commit()
        assert inst.current_stage_order == 2


async def test_four_eyes_blocks_previous_stage_completer(
        session_factory, seed, part, rules_template):
    from app.services.workflow_service import WorkflowService
    inst_id = await _start_instance(session_factory, seed, part, rules_template)
    t1 = await _active_task_id(session_factory, inst_id, 1)
    async with session_factory() as s:
        await WorkflowService.complete_task(s, t1, "waived", "n/a",
                                            seed["engineer_id"])
        await s.commit()
    t2 = await _active_task_id(session_factory, inst_id, 2)

    async with session_factory() as s:
        with pytest.raises(ValueError, match="4-eyes"):
            await WorkflowService.complete_task(s, t2, "approved", None,
                                                seed["engineer_id"])

    async with session_factory() as s:
        inst = await WorkflowService.complete_task(s, t2, "approved", None,
                                                   seed["admin_id"])
        await s.commit()
        assert inst.status == "completed"


async def test_wf_events_write_audit_log(session_factory, seed, part, rules_template):
    from app.models.entities import AuditLog
    inst_id = await _start_instance(session_factory, seed, part, rules_template)
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "wf_instance",
            AuditLog.entity_id == inst_id))).scalars().all()
    assert any(r.action == "wf_started" for r in rows)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_check_workflow_rules.py -v`
Expected: model test PASSES; the four new tests FAIL (waive raises "Decision must be 'approved' or 'rejected'", evidence/4-eyes not enforced, no audit rows).

- [ ] **Step 3: Implement in `workflow_service.py`**

Add helpers to `WorkflowService`:

```python
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
```

In `start_workflow`, after `_create_stage_tasks(db, instance, first_stage)` and before `return instance`:

```python
        await WorkflowService._audit(db, instance, "wf_started", started_by_id,
                                     {"template_id": template_id,
                                      "revision_id": revision_id})
```

In `complete_task`:

1. Replace the decision validation:

```python
        if decision not in ("approved", "rejected", "waived"):
            raise ValueError("Decision must be 'approved', 'rejected' or 'waived'")
        if decision == "waived" and not (notes and notes.strip()):
            raise ValueError("Waiving a step requires a reason (notes)")
```

2. Extend the task query's options to eager-load the step:

```python
            .options(selectinload(WfInstanceTask.instance),
                     selectinload(WfInstanceTask.step))
```

3. After the `is_actionable` check and before mutating the task, insert the two gates:

```python
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
```

4. The stage-advancement check must treat waived as satisfied — change:

```python
        if all(t.status in ("approved", "waived") for t in all_actionable):
```

(and the early `if decision == "rejected"` branch stays as-is; `task.status = decision` already stores `"waived"`.)

5. Audit writes: after the task mutation flush add

```python
        await WorkflowService._audit(
            db, instance, f"task_{decision}", completed_by_id,
            {"task_id": task.id, "step": step.step_name if step else None,
             "notes": notes})
```

and inside the completion branch (where `instance.status = "completed"` is set) add

```python
                await WorkflowService._audit(db, instance, "wf_completed",
                                             completed_by_id, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_check_workflow_rules.py tests/test_workflows.py -v`
Expected: PASS (existing `test_workflows.py` must stay green — the new rules only trigger on flagged steps, and all pre-existing steps have both flags `False`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/workflow_service.py backend/tests/test_check_workflow_rules.py
git commit -m "feat(workflow): waivable steps, 3D-evidence gate, 4-eyes rule + audit writes"
```

---

## Task 4: No-geometry-change sign-off endpoint

**Tier:** opus (compliance sign-off; authorization + audit).

**Files:**
- Modify: `backend/app/api/v1/items/revision_files.py`
- Test: `backend/tests/test_revision_evidence.py`

**Interfaces:**
- Produces: `POST /api/v1/parts/{part_id}/revisions/{revision_id}/no-geometry-change` body `{"reason": str}` → 200 with `{"revision_id", "no_geometry_change", "no_geometry_change_by", "no_geometry_change_at"}`. 404 unknown revision/part mismatch, 409 on locked revisions (same `LOCKED_STATUSES` as upload), 400 if already signed or reason blank. Writes `RevisionChangelog` via `ChangelogService.log_action` and `AuditLog` via `AuditService.record` (`entity_type="part_revision"`, action `no_geometry_change_signed`, `correlation_id` = originating change number when set).
- Consumes: Task 1's `PartRevision.no_geometry_change*` fields.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_revision_evidence.py
import pytest
from sqlalchemy import select

from tests.conftest import freeze_revision

pytestmark = pytest.mark.asyncio


async def test_sign_no_geometry_change(client, eng_auth, part, session_factory):
    res = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/no-geometry-change",
        json={"reason": "label text change only"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["no_geometry_change"] is True
    assert body["no_geometry_change_by"] is not None

    from app.models.entities import AuditLog
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "part_revision",
            AuditLog.entity_id == part["revision_id"],
            AuditLog.action == "no_geometry_change_signed"))).scalars().all()
    assert len(rows) == 1

    # double-sign is rejected
    res = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/no-geometry-change",
        json={"reason": "again"}, headers=eng_auth)
    assert res.status_code == 400


async def test_sign_requires_reason(client, eng_auth, part):
    res = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/no-geometry-change",
        json={"reason": "  "}, headers=eng_auth)
    assert res.status_code == 400


async def test_sign_blocked_on_locked_revision(client, eng_auth, part, session_factory):
    await freeze_revision(session_factory, part["revision_id"])
    res = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/no-geometry-change",
        json={"reason": "doc change"}, headers=eng_auth)
    assert res.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_revision_evidence.py -v`
Expected: FAIL with 404/405 (route does not exist).

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/v1/items/revision_files.py` (reuse the file's existing revision-loading + `LOCKED_STATUSES` idiom from the upload endpoint; define the request model inline next to any existing ones):

```python
from pydantic import BaseModel


class NoGeometryChangeIn(BaseModel):
    reason: str


@router.post("/{part_id}/revisions/{revision_id}/no-geometry-change")
async def sign_no_geometry_change(
    part_id: int, revision_id: int, body: NoGeometryChangeIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner-signed statement that this ECN revision has no geometry change —
    the alternative 3D evidence to a CAD upload (spec: 3D-evidence decision)."""
    revision = await _load_revision(db, part_id, revision_id)  # reuse/extract the
    # same lookup+404 used by the upload endpoint; keep its 409 LOCKED_STATUSES check
    if revision.status in LOCKED_STATUSES:
        raise HTTPException(status_code=409,
                            detail=f"Revision is {revision.status}; evidence is locked")
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Reason is required")
    if revision.no_geometry_change:
        raise HTTPException(status_code=400, detail="Already signed")

    revision.no_geometry_change = True
    revision.no_geometry_change_by = current_user.id
    revision.no_geometry_change_at = datetime.utcnow()
    revision.no_geometry_change_reason = reason

    await ChangelogService.log_action(
        db, part_id=part_id, action="no_geometry_change_signed",
        action_description=f"No-geometry-change signed: {reason}",
        performed_by=current_user.id, revision_id=revision_id)

    from app.services.audit_service import AuditService
    correlation = None
    if revision.originating_change_id is not None:
        from app.models.change import ChangeRequest
        change = await db.get(ChangeRequest, revision.originating_change_id)
        correlation = change.change_number if change else None
    await AuditService.record(
        db, entity_type="part_revision", entity_id=revision_id,
        action="no_geometry_change_signed", user_id=current_user.id,
        new_values={"reason": reason}, correlation_id=correlation)

    await db.commit()
    return {
        "revision_id": revision_id,
        "no_geometry_change": True,
        "no_geometry_change_by": current_user.id,
        "no_geometry_change_at": revision.no_geometry_change_at.isoformat(),
    }
```

If the upload endpoint inlines its revision lookup instead of a `_load_revision` helper, extract that lookup into `_load_revision(db, part_id, revision_id)` (404 on missing or part mismatch) and use it from both places. Match `ChangelogService.log_action`'s real signature (`app/services/part_service.py:1419`) — it is sync or async as defined there; call accordingly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_revision_evidence.py tests/test_revision_files.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/items/revision_files.py backend/tests/test_revision_evidence.py
git commit -m "feat(parts): owner-signed no-geometry-change as auditable 3D evidence"
```

---

## Task 5: Impact tree backend — tree, roll-up suggestion, bulk selection

**Tier:** opus (the roll-up algorithm and selection invariants are design-critical).

**Files:**
- Modify: `backend/app/services/change_service.py`, `backend/app/api/v1/changes/changes.py`, `backend/app/schemas/change.py`
- Test: `backend/tests/test_impact_tree.py`

**Interfaces:**
- Produces (service):
  - `ChangeService.get_impact_tree(session, change) -> dict` — `{"tree": [node...], "impacted_part_ids": [int], "lead_part_id": int | None}` where node = `{part_id, part_number, name, part_type, item_category, is_impacted, is_lead, resulting_revision_id, children: [node...]}` over the change's project part hierarchy.
  - `ChangeService.suggest_rollups(session, project_id, part_ids: set[int]) -> set[int]` — transitive BOM parents (display revision = `part.active_revision_id` or latest revision) of the selection, excluding the selection itself.
  - `ChangeService.apply_impact_selection(session, change, part_ids, user_id) -> None` — diff-apply; refuses when `change.status` in `IMPACT_LOCKED_STATUSES = ("in_implementation", "in_validation", "released", "closed", "rejected", "cancelled")`, refuses removing the lead item or any item with `resulting_revision_id`, validates parts belong to the change's project; changelog per add/remove.
- Produces (API): `GET /api/v1/changes/{change_id}/impact-tree`; `POST /api/v1/changes/{change_id}/impact-tree/suggest` body `{"part_ids": [int]}` → `{"suggested_part_ids": [int]}`; `PUT /api/v1/changes/{change_id}/impacted-items` body `{"part_ids": [int]}` (lead or admin only, mirroring the gate-decide rule) → 200 `{"impacted_part_ids": [int]}`.
- Consumes: `Part`, `PartRevision`, `PartBOMItem`, `ChangeImpactedItem`, `append_changelog`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_impact_tree.py
import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def _make_part(client, eng_auth, seed, number, name, parent_id=None,
                     part_type="internal_mfg"):
    body = {"project_id": seed["project_id"], "part_number": number,
            "name": name, "part_type": part_type,
            "data_classification": "confidential"}
    if parent_id is not None:
        body["parent_part_id"] = parent_id
    res = await client.post("/api/v1/parts", json=body, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    pid = res.json()["id"]
    res = await client.post(f"/api/v1/parts/{pid}/revisions/rfq",
                            json={"summary": "init"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    return {"part_id": pid, "revision_id": res.json()["id"]}


async def _make_change_with_lead(client, eng_auth, seed, lead_part_id):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "tree", "change_type": "tooling",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    change = res.json()
    res = await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                            json={"part_id": lead_part_id, "is_lead": True},
                            headers=eng_auth)
    assert res.status_code == 200, res.text
    return change


async def test_impact_tree_marks_impacted_and_lead(client, eng_auth, seed):
    asm = await _make_part(client, eng_auth, seed, "ASM-1", "Assembly",
                           part_type="sub_assembly")
    child = await _make_part(client, eng_auth, seed, "CHD-1", "Child",
                             parent_id=asm["part_id"])
    change = await _make_change_with_lead(client, eng_auth, seed, child["part_id"])

    res = await client.get(f"/api/v1/changes/{change['id']}/impact-tree",
                           headers=eng_auth)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["lead_part_id"] == child["part_id"]
    roots = {n["part_id"]: n for n in data["tree"]}
    assert asm["part_id"] in roots
    child_node = next(c for c in roots[asm["part_id"]]["children"]
                      if c["part_id"] == child["part_id"])
    assert child_node["is_impacted"] is True and child_node["is_lead"] is True
    assert roots[asm["part_id"]]["is_impacted"] is False


async def test_suggest_rollups_walks_bom_parents_transitively(
        client, eng_auth, seed, session_factory):
    top = await _make_part(client, eng_auth, seed, "TOP-1", "Top",
                           part_type="sub_assembly")
    mid = await _make_part(client, eng_auth, seed, "MID-1", "Mid",
                           part_type="sub_assembly")
    leaf = await _make_part(client, eng_auth, seed, "LEAF-1", "Leaf")
    change = await _make_change_with_lead(client, eng_auth, seed, leaf["part_id"])

    from app.models.part import PartBOMItem
    async with session_factory() as s:
        s.add(PartBOMItem(revision_id=mid["revision_id"],
                          child_part_id=leaf["part_id"], name="leaf", quantity=1))
        s.add(PartBOMItem(revision_id=top["revision_id"],
                          child_part_id=mid["part_id"], name="mid", quantity=1))
        await s.commit()

    res = await client.post(
        f"/api/v1/changes/{change['id']}/impact-tree/suggest",
        json={"part_ids": [leaf["part_id"]]}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert set(res.json()["suggested_part_ids"]) == {top["part_id"], mid["part_id"]}


async def test_apply_selection_adds_and_removes(client, eng_auth, seed):
    lead = await _make_part(client, eng_auth, seed, "L-1", "Lead")
    extra = await _make_part(client, eng_auth, seed, "X-1", "Extra")
    change = await _make_change_with_lead(client, eng_auth, seed, lead["part_id"])

    res = await client.put(f"/api/v1/changes/{change['id']}/impacted-items",
                           json={"part_ids": [lead["part_id"], extra["part_id"]]},
                           headers=eng_auth)
    assert res.status_code == 200, res.text
    assert set(res.json()["impacted_part_ids"]) == {lead["part_id"], extra["part_id"]}

    # dropping the lead is refused
    res = await client.put(f"/api/v1/changes/{change['id']}/impacted-items",
                           json={"part_ids": [extra["part_id"]]}, headers=eng_auth)
    assert res.status_code == 400
    assert "lead" in res.json()["detail"].lower()

    # removing the extra is fine
    res = await client.put(f"/api/v1/changes/{change['id']}/impacted-items",
                           json={"part_ids": [lead["part_id"]]}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["impacted_part_ids"] == [lead["part_id"]]


async def test_apply_selection_locked_after_kickoff(client, eng_auth, seed,
                                                    session_factory):
    lead = await _make_part(client, eng_auth, seed, "L-2", "Lead2")
    extra = await _make_part(client, eng_auth, seed, "X-2", "Extra2")
    change = await _make_change_with_lead(client, eng_auth, seed, lead["part_id"])

    from app.models.change import ChangeRequest
    async with session_factory() as s:
        c = await s.get(ChangeRequest, change["id"])
        c.status = "in_implementation"
        await s.commit()

    res = await client.put(f"/api/v1/changes/{change['id']}/impacted-items",
                           json={"part_ids": [lead["part_id"], extra["part_id"]]},
                           headers=eng_auth)
    assert res.status_code == 400
    assert "locked" in res.json()["detail"].lower()
```

Note: `_make_part` sends `parent_part_id` on create — if the parts POST schema doesn't accept it, set `parent_part_id` directly via the session instead (check `app/schemas/part.py` `PartCreate`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_impact_tree.py -v`
Expected: FAIL with 404/405 (routes missing).

- [ ] **Step 3: Implement the service methods**

In `backend/app/services/change_service.py` add module constant next to the others:

```python
IMPACT_LOCKED_STATUSES = ("in_implementation", "in_validation", "released",
                          "closed", "rejected", "cancelled")
```

Add methods to `ChangeService` (near `add_impacted_item`); `Part`, `PartRevision`, `select`, `func` are already imported — add `PartBOMItem` to the part-model import and `from collections import defaultdict` at the top:

```python
    @staticmethod
    async def get_impact_tree(session: AsyncSession, change: ChangeRequest) -> dict:
        parts = (await session.execute(
            select(Part).where(Part.project_id == change.project_id)
        )).scalars().all()
        impacted = {i.part_id: i for i in change.impacted_items}
        ids = {p.id for p in parts}
        children_map: dict = defaultdict(list)
        roots = []
        for p in parts:
            if p.parent_part_id in ids:
                children_map[p.parent_part_id].append(p)
            else:
                roots.append(p)

        def node(p: Part) -> dict:
            item = impacted.get(p.id)
            return {
                "part_id": p.id,
                "part_number": p.part_number,
                "name": p.name,
                "part_type": p.part_type,
                "item_category": p.item_category,
                "is_impacted": item is not None,
                "is_lead": bool(item and item.is_lead),
                "resulting_revision_id": item.resulting_revision_id if item else None,
                "children": [node(c) for c in
                             sorted(children_map.get(p.id, []), key=lambda x: x.id)],
            }

        return {
            "tree": [node(p) for p in sorted(roots, key=lambda x: x.id)],
            "impacted_part_ids": sorted(impacted),
            "lead_part_id": next(
                (pid for pid, it in impacted.items() if it.is_lead), None),
        }

    @staticmethod
    async def suggest_rollups(session: AsyncSession, project_id: int,
                              part_ids: set[int]) -> set[int]:
        """Transitive BOM roll-up: parents whose display revision's BOM
        references a selected (or already-suggested) part structurally must
        revise too. Display revision = active revision, else latest."""
        rows = (await session.execute(
            select(Part.id, Part.active_revision_id)
            .where(Part.project_id == project_id))).all()
        display_rev_to_part: dict[int, int] = {}
        missing = []
        for pid, active in rows:
            if active is not None:
                display_rev_to_part[active] = pid
            else:
                missing.append(pid)
        if missing:
            latest = (await session.execute(
                select(PartRevision.part_id, func.max(PartRevision.id))
                .where(PartRevision.part_id.in_(missing))
                .group_by(PartRevision.part_id))).all()
            for pid, rid in latest:
                display_rev_to_part[rid] = pid
        if not display_rev_to_part:
            return set()
        edges = (await session.execute(
            select(PartBOMItem.child_part_id, PartBOMItem.revision_id).where(
                PartBOMItem.revision_id.in_(display_rev_to_part.keys()),
                PartBOMItem.child_part_id.is_not(None)))).all()
        parents_of: dict[int, set[int]] = defaultdict(set)
        for child_id, rev_id in edges:
            parents_of[child_id].add(display_rev_to_part[rev_id])

        suggested: set[int] = set()
        frontier = set(part_ids)
        while frontier:
            nxt: set[int] = set()
            for pid in frontier:
                for parent in parents_of.get(pid, ()):
                    if parent not in part_ids and parent not in suggested:
                        suggested.add(parent)
                        nxt.add(parent)
            frontier = nxt
        return suggested

    @staticmethod
    async def apply_impact_selection(session: AsyncSession, change: ChangeRequest,
                                     part_ids: list[int], user_id: int) -> None:
        if change.status in IMPACT_LOCKED_STATUSES:
            raise ChangeError(
                "Impact selection is locked once implementation has started")
        wanted = set(part_ids)
        valid = {pid for (pid,) in (await session.execute(
            select(Part.id).where(Part.project_id == change.project_id,
                                  Part.id.in_(wanted))))}
        unknown = sorted(wanted - valid)
        if unknown:
            raise ChangeError(f"Parts not in this project: {unknown}")
        current = {i.part_id: i for i in change.impacted_items}
        for pid, item in list(current.items()):
            if pid in wanted:
                continue
            if item.is_lead:
                raise ChangeError("The lead item cannot be removed")
            if item.resulting_revision_id is not None:
                raise ChangeError(
                    f"Part {pid} already has a spawned revision and cannot be removed")
            await session.delete(item)
            await ChangeService.append_changelog(
                session, change, "impacted_removed",
                f"Impacted part {pid} removed via impact tree", user_id,
                old_value={"part_id": pid})
        for pid in sorted(wanted - set(current)):
            session.add(ChangeImpactedItem(change_id=change.id, part_id=pid,
                                           created_by=user_id))
            await ChangeService.append_changelog(
                session, change, "impacted_added",
                f"Impacted part {pid} added via impact tree", user_id,
                new_value={"part_id": pid})
        await session.flush()
```

(Match `append_changelog`'s real kwarg names — `old_value`/`new_value` — against the file; adjust if they take strings rather than dicts, mirroring existing call sites like `revision_spawned`.)

- [ ] **Step 4: Implement schemas + endpoints**

In `backend/app/schemas/change.py`:

```python
class ImpactSuggestIn(BaseModel):
    part_ids: List[int]


class ImpactSelectionIn(BaseModel):
    part_ids: List[int]
```

In `backend/app/api/v1/changes/changes.py` (follow the file's 404 + `ChangeError`→400 + explicit-commit idiom; the PUT mirrors the gate-decide lead/admin rule):

```python
@router.get("/{change_id}/impact-tree")
async def get_impact_tree(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return await ChangeService.get_impact_tree(db, change)


@router.post("/{change_id}/impact-tree/suggest")
async def suggest_impact_rollups(
    change_id: int, body: ImpactSuggestIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    suggested = await ChangeService.suggest_rollups(
        db, change.project_id, set(body.part_ids))
    return {"suggested_part_ids": sorted(suggested)}


@router.put("/{change_id}/impacted-items")
async def apply_impact_selection(
    change_id: int, body: ImpactSelectionIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if current_user.role != "admin" and change.lead_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the change lead or an admin may edit the impact selection")
    try:
        await ChangeService.apply_impact_selection(
            db, change, body.part_ids, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    change = await ChangeService.get_change(db, change_id)
    return {"impacted_part_ids": sorted(i.part_id for i in change.impacted_items)}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_impact_tree.py tests/test_changes.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_service.py \
        backend/app/api/v1/changes/changes.py backend/app/schemas/change.py \
        backend/tests/test_impact_tree.py
git commit -m "feat(change): impact tree with transitive BOM roll-up suggestion and bulk selection"
```

---

## Task 6: Kickoff wiring — back-links + check-WF instances + mapping guard

**Tier:** opus (state-machine side effects).

**Files:**
- Modify: `backend/app/services/change_service.py`, `backend/tests/conftest.py`, `backend/tests/test_changes.py`
- Test: `backend/tests/test_change_kickoff.py`

**Interfaces:**
- Produces: `spawn_ecn_revisions` now (a) stamps `originating_change_id=change.id` on spawned revisions, (b) for EVERY impacted item ensures a check-WF instance exists on its resulting revision (template resolved from `CheckWorkflowStandard` by the part's `item_category`; skipped with no instance when unmapped — the transition guard normally prevents that, deviation-bypassed kickoffs stay not-ready). Changelog action `check_wf_started`. `_guard` returns a reason for `→ in_implementation` when any impacted item's category lacks a mapping.
- Produces (conftest): fixture `check_wf_standards` (seeds Template-2 mappings) and helper `force_complete_check_workflows(session_factory, change_id)`.
- Consumes: Task 1 models, Task 2 `seed_check_standards`, `WorkflowService.start_workflow`.

- [ ] **Step 1: Add conftest fixture + helper**

In `backend/tests/conftest.py`:

```python
@pytest_asyncio.fixture
async def check_wf_standards(session_factory, seed):
    """Seed the ECN Umsetzung check-workflow templates + category mappings."""
    from app.services.wf_seed_service import seed_check_standards
    async with session_factory() as s:
        await seed_check_standards(s)
        await s.commit()


async def force_complete_check_workflows(session_factory, change_id: int):
    """Mark every check-WF instance of a change's ECN revisions completed —
    for tests that need to pass the ready-to-go guard without driving tasks."""
    from datetime import datetime
    from sqlalchemy import select, update
    from app.models.change import ChangeImpactedItem
    from app.models.workflow import WfInstance
    async with session_factory() as s:
        rev_ids = [r for (r,) in await s.execute(
            select(ChangeImpactedItem.resulting_revision_id).where(
                ChangeImpactedItem.change_id == change_id,
                ChangeImpactedItem.resulting_revision_id.is_not(None)))]
        if rev_ids:
            await s.execute(update(WfInstance)
                            .where(WfInstance.part_revision_id.in_(rev_ids))
                            .values(status="completed",
                                    completed_at=datetime.utcnow()))
        await s.commit()
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_change_kickoff.py
import pytest
from sqlalchemy import select, update

pytestmark = pytest.mark.asyncio


async def _approved_change(session_factory, seed, part_id):
    """Change with one lead impacted item, forced to approved with gates yes."""
    from app.services.change_service import ChangeService
    from app.models.change import ChangeImpactedItem
    from app.models.change_cost import ChangeGate
    async with session_factory() as s:
        change = await ChangeService.create_change(
            s, project_id=seed["project_id"], title="kickoff",
            change_type="tooling", raised_by=seed["engineer_id"],
            lead_id=seed["engineer_id"])
        s.add(ChangeImpactedItem(change_id=change.id, part_id=part_id,
                                 is_lead=True, created_by=seed["engineer_id"]))
        change.status = "approved"
        await s.execute(update(ChangeGate).where(ChangeGate.change_id == change.id)
                        .values(decision="yes"))
        await s.commit()
        return change.id


async def test_kickoff_spawns_backlinked_revision_and_check_wf(
        session_factory, seed, part, check_wf_standards):
    from app.services.change_service import ChangeService
    from app.models.change import ChangeImpactedItem
    from app.models.part import PartRevision
    from app.models.workflow import WfInstance, WfTemplate

    cid = await _approved_change(session_factory, seed, part["part_id"])
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        await ChangeService.transition(s, change, "in_implementation",
                                       seed["engineer_id"])
        await s.commit()

    async with session_factory() as s:
        item = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == cid))).scalar_one()
        assert item.resulting_revision_id is not None
        rev = await s.get(PartRevision, item.resulting_revision_id)
        assert rev.originating_change_id == cid
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.part_revision_id == rev.id))).scalar_one()
        assert inst.status == "active"
        tmpl = await s.get(WfTemplate, inst.template_id)
        # part fixture is item_category 'article'
        assert tmpl.name == "ECN Umsetzung (Artikel)"


async def test_kickoff_blocked_without_check_mapping(session_factory, seed, part):
    from app.services.change_service import ChangeService, ChangeError

    cid = await _approved_change(session_factory, seed, part["part_id"])
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        with pytest.raises(ChangeError, match="check-workflow"):
            await ChangeService.transition(s, change, "in_implementation",
                                           seed["engineer_id"])


async def test_kickoff_idempotent_no_duplicate_instances(
        session_factory, seed, part, check_wf_standards):
    from app.services.change_service import ChangeService
    from app.models.change import ChangeImpactedItem
    from app.models.workflow import WfInstance
    from sqlalchemy import func

    cid = await _approved_change(session_factory, seed, part["part_id"])
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        await ChangeService.transition(s, change, "in_implementation",
                                       seed["engineer_id"])
        # calling spawn again (e.g. resume from on_hold) must not duplicate
        await ChangeService.spawn_ecn_revisions(s, change, seed["engineer_id"])
        await s.commit()

    async with session_factory() as s:
        item = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == cid))).scalar_one()
        n = (await s.execute(select(func.count()).select_from(WfInstance).where(
            WfInstance.part_revision_id == item.resulting_revision_id))).scalar()
        assert n == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_change_kickoff.py -v`
Expected: FAIL (`originating_change_id` is None, no `WfInstance`, no guard message).

- [ ] **Step 4: Implement in `change_service.py`**

In `spawn_ecn_revisions`, add `originating_change_id=change.id` to the `PartRevision(...)` constructor, and restructure the loop so every item (not only newly-spawned ones) gets its check workflow ensured:

```python
    @staticmethod
    async def spawn_ecn_revisions(session: AsyncSession, change: ChangeRequest, user_id: int):
        for item in change.impacted_items:
            if item.resulting_revision_id is None:
                result = await session.execute(
                    select(func.count()).select_from(PartRevision).where(
                        (PartRevision.part_id == item.part_id)
                        & (PartRevision.phase == "ecn")
                    )
                )
                n = (result.scalar() or 0) + 1
                rev = PartRevision(
                    part_id=item.part_id,
                    revision_name=f"ECR{n}.1",
                    phase="ecn",
                    status="draft",
                    change_reason=f"{change.change_number}: {change.title}",
                    created_by=user_id,
                    originating_change_id=change.id,
                )
                session.add(rev)
                await session.flush()
                item.resulting_revision_id = rev.id
                await ChangeService.append_changelog(
                    session, change, "revision_spawned",
                    f"Spawned ECN revision {rev.revision_name} on part {item.part_id}",
                    user_id, new_value={"revision_id": rev.id, "part_id": item.part_id},
                )
            await ChangeService._ensure_check_workflow(session, change, item, user_id)

    @staticmethod
    async def _ensure_check_workflow(session: AsyncSession, change: ChangeRequest,
                                     item: "ChangeImpactedItem", user_id: int) -> None:
        """Start the mapped check-WF instance for an impacted item's ECN
        revision. No-op if one already runs/ran, or (deviation-bypassed
        kickoff) no mapping exists — the change then stays not-ready-to-go."""
        from app.models.workflow import CheckWorkflowStandard, WfInstance
        from app.services.workflow_service import WorkflowService

        existing = (await session.execute(
            select(WfInstance).where(
                WfInstance.part_revision_id == item.resulting_revision_id,
                WfInstance.status.in_(("active", "completed")))
        )).scalars().first()
        if existing is not None:
            return
        part = await session.get(Part, item.part_id)
        standard = (await session.execute(
            select(CheckWorkflowStandard).where(
                CheckWorkflowStandard.item_category == part.item_category)
        )).scalar_one_or_none()
        if standard is None:
            return
        instance = await WorkflowService.start_workflow(
            session, item.resulting_revision_id, standard.template_id, user_id)
        await ChangeService.append_changelog(
            session, change, "check_wf_started",
            f"Check workflow started for revision {item.resulting_revision_id} "
            f"(part {item.part_id})",
            user_id, new_value={"instance_id": instance.id,
                                "revision_id": item.resulting_revision_id},
        )
```

In `_guard`, add before the gate-row loop:

```python
        if to_status == "in_implementation":
            from app.models.workflow import CheckWorkflowStandard
            part_ids = [i.part_id for i in change.impacted_items]
            if part_ids:
                cats = {c for (c,) in await session.execute(
                    select(Part.item_category).where(Part.id.in_(part_ids)))}
                mapped = {c for (c,) in await session.execute(
                    select(CheckWorkflowStandard.item_category).where(
                        CheckWorkflowStandard.item_category.in_(cats)))}
                missing = sorted(cats - mapped)
                if missing:
                    return ("no check-workflow template mapped for item "
                            f"category: {', '.join(missing)}")
```

- [ ] **Step 5: Adapt the two lifecycle tests in `test_changes.py`**

`test_implementation_spawns_ecn_revision_per_item` and `test_release_activates_revisions_and_stamps_eng_level` both reach `in_implementation`: add `check_wf_standards` to each test's fixture parameters (after `departments`). No other change for the first test. (The release test gains its ready-to-go adaptation in Task 7 — here it still passes because the release guard doesn't exist yet.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_change_kickoff.py tests/test_changes.py tests/test_change_deviations.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/change_service.py backend/tests/conftest.py \
        backend/tests/test_changes.py backend/tests/test_change_kickoff.py
git commit -m "feat(change): kickoff spawns back-linked ECN revisions with check-WF instances"
```

---

## Task 7: Computed ready-to-go — progress roll-up + release guard

**Tier:** sonnet (aggregation over well-defined inputs; the guard slot is established).

**Files:**
- Modify: `backend/app/services/change_service.py`, `backend/app/api/v1/changes/changes.py`, `backend/tests/test_changes.py`
- Test: `backend/tests/test_ready_to_go.py`

**Interfaces:**
- Produces: `ChangeService.implementation_progress(session, change) -> dict`:
  `{"ready_to_go": bool, "items": [{"item_id", "part_id", "part_number", "part_name", "item_category", "is_lead", "revision_id", "revision_name", "instance_id", "instance_status", "current_stage_order", "total_stages", "has_cad_file", "no_geometry_change", "ready"}]}` — `ready` = instance status `completed`; `ready_to_go` = non-empty items and all ready.
- Produces: `GET /api/v1/changes/{change_id}/implementation` → that dict. `_guard` returns a reason for `→ released` when not ready (soft, deviation-bypassable).
- Consumes: Task 6's instances, `WfInstance`, `WfStage`, `RevisionFile`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_ready_to_go.py
import pytest
from sqlalchemy import select, update

from tests.conftest import force_complete_check_workflows
from tests.test_change_kickoff import _approved_change

pytestmark = pytest.mark.asyncio


async def _kickoff(session_factory, seed, part_id):
    from app.services.change_service import ChangeService
    cid = await _approved_change(session_factory, seed, part_id)
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        await ChangeService.transition(s, change, "in_implementation",
                                       seed["engineer_id"])
        await s.commit()
    return cid


async def test_progress_not_ready_until_instances_complete(
        session_factory, seed, part, check_wf_standards, client, eng_auth):
    from app.services.change_service import ChangeService

    cid = await _kickoff(session_factory, seed, part["part_id"])

    res = await client.get(f"/api/v1/changes/{cid}/implementation",
                           headers=eng_auth)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ready_to_go"] is False
    assert len(data["items"]) == 1
    entry = data["items"][0]
    assert entry["instance_status"] == "active"
    assert entry["total_stages"] == 4
    assert entry["ready"] is False

    await force_complete_check_workflows(session_factory, cid)
    data = (await client.get(f"/api/v1/changes/{cid}/implementation",
                             headers=eng_auth)).json()
    assert data["ready_to_go"] is True
    assert data["items"][0]["ready"] is True


async def test_release_guarded_by_ready_to_go(
        session_factory, seed, part, check_wf_standards):
    from app.services.change_service import ChangeService, ChangeError

    cid = await _kickoff(session_factory, seed, part["part_id"])
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        await ChangeService.transition(s, change, "in_validation",
                                       seed["engineer_id"])
        with pytest.raises(ChangeError, match="ready"):
            await ChangeService.transition(s, change, "released",
                                           seed["engineer_id"])
        await s.commit()

    await force_complete_check_workflows(session_factory, cid)
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        await ChangeService.transition(s, change, "released",
                                       seed["engineer_id"])
        await s.commit()
        assert change.status == "released"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_ready_to_go.py -v`
Expected: FAIL (endpoint 404; release succeeds without guard).

- [ ] **Step 3: Implement**

In `change_service.py` add to `ChangeService`:

```python
    @staticmethod
    async def implementation_progress(session: AsyncSession,
                                      change: ChangeRequest) -> dict:
        from app.models.part import RevisionFile
        from app.models.workflow import WfInstance, WfStage

        items = []
        for item in change.impacted_items:
            part = await session.get(Part, item.part_id)
            entry = {
                "item_id": item.id,
                "part_id": item.part_id,
                "part_number": part.part_number if part else None,
                "part_name": part.name if part else None,
                "item_category": part.item_category if part else None,
                "is_lead": item.is_lead,
                "revision_id": item.resulting_revision_id,
                "revision_name": None,
                "instance_id": None,
                "instance_status": None,
                "current_stage_order": None,
                "total_stages": None,
                "has_cad_file": False,
                "no_geometry_change": False,
                "ready": False,
            }
            if item.resulting_revision_id is not None:
                rev = await session.get(PartRevision, item.resulting_revision_id)
                if rev is not None:
                    entry["revision_name"] = rev.revision_name
                    entry["no_geometry_change"] = bool(rev.no_geometry_change)
                n_files = (await session.execute(
                    select(func.count()).select_from(RevisionFile).where(
                        RevisionFile.revision_id == item.resulting_revision_id,
                        RevisionFile.file_type == "cad",
                        RevisionFile.is_deleted == False,  # noqa: E712
                    ))).scalar()
                entry["has_cad_file"] = bool(n_files)
                inst = (await session.execute(
                    select(WfInstance)
                    .where(WfInstance.part_revision_id == item.resulting_revision_id)
                    .order_by(WfInstance.id.desc()).limit(1)
                )).scalar_one_or_none()
                if inst is not None:
                    entry["instance_id"] = inst.id
                    entry["instance_status"] = inst.status
                    entry["current_stage_order"] = inst.current_stage_order
                    entry["total_stages"] = (await session.execute(
                        select(func.count()).select_from(WfStage).where(
                            WfStage.template_id == inst.template_id))).scalar()
                    entry["ready"] = inst.status == "completed"
            items.append(entry)
        return {
            "ready_to_go": bool(items) and all(e["ready"] for e in items),
            "items": items,
        }
```

In `_guard`, add (before the gate-row loop, next to the Task 6 block):

```python
        if to_status == "released":
            progress = await ChangeService.implementation_progress(session, change)
            if not progress["ready_to_go"]:
                pending = sum(1 for e in progress["items"] if not e["ready"])
                return (f"not ready to go: {pending} of {len(progress['items'])} "
                        "impacted revisions have not completed their check workflow")
```

In `changes.py` add the endpoint (any authenticated user):

```python
@router.get("/{change_id}/implementation")
async def get_implementation_progress(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return await ChangeService.implementation_progress(db, change)
```

- [ ] **Step 4: Adapt `test_release_activates_revisions_and_stamps_eng_level`**

In `backend/tests/test_changes.py`, that test now needs the workflows completed before `released`: add the import `from tests.conftest import force_complete_check_workflows` (extend the existing conftest import line) and, between the `in_validation` and `released` transitions, insert:

```python
    await force_complete_check_workflows(session_factory, cid)
```

(add `session_factory` to the test's fixture parameters).

- [ ] **Step 5: Run tests + full backend suite**

Run: `cd backend && python3 -m pytest tests/test_ready_to_go.py -v && python3 -m pytest`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_service.py \
        backend/app/api/v1/changes/changes.py \
        backend/tests/test_ready_to_go.py backend/tests/test_changes.py
git commit -m "feat(change): computed ready-to-go from check-WF roll-up guards release"
```

---

## Task 8: Frontend — interactive impact tree

**Tier:** opus (UX-critical component per spec tiering).

**Files:**
- Create: `frontend/src/components/changes/ImpactTree.tsx`, `frontend/src/components/changes/ImpactTree.test.tsx`
- Modify: `frontend/src/types/change.ts`, `frontend/src/api/changes.ts`, `frontend/src/pages/ChangeDetailPage.tsx`, `frontend/src/i18n/cmLabels.ts`

**Interfaces:**
- Consumes: `GET /v1/changes/{id}/impact-tree`, `POST /v1/changes/{id}/impact-tree/suggest`, `PUT /v1/changes/{id}/impacted-items` (Task 5 shapes).
- Produces: `<ImpactTree changeId={number} status={ChangeStatus} />` rendered in the ChangeDetailPage "impacted" tab; types `ImpactTreeNode`, `ImpactTreeResponse`; api methods `getImpactTree`, `suggestImpact`, `applyImpactSelection`.

- [ ] **Step 1: Add types + api methods**

In `frontend/src/types/change.ts`:

```ts
export interface ImpactTreeNode {
  part_id: number
  part_number: string
  name: string
  part_type: string
  item_category: string
  is_impacted: boolean
  is_lead: boolean
  resulting_revision_id: number | null
  children: ImpactTreeNode[]
}

export interface ImpactTreeResponse {
  tree: ImpactTreeNode[]
  impacted_part_ids: number[]
  lead_part_id: number | null
}
```

In `frontend/src/api/changes.ts` (inside `changesApi`, matching the file's `client.<verb>(...).then(r => r.data)` style):

```ts
  getImpactTree: (changeId: number): Promise<ImpactTreeResponse> =>
    client.get(`/v1/changes/${changeId}/impact-tree`).then(r => r.data),
  suggestImpact: (changeId: number, partIds: number[]): Promise<{ suggested_part_ids: number[] }> =>
    client.post(`/v1/changes/${changeId}/impact-tree/suggest`, { part_ids: partIds }).then(r => r.data),
  applyImpactSelection: (changeId: number, partIds: number[]): Promise<{ impacted_part_ids: number[] }> =>
    client.put(`/v1/changes/${changeId}/impacted-items`, { part_ids: partIds }).then(r => r.data),
```

In `frontend/src/i18n/cmLabels.ts` add keys:

```ts
  'impact.title': { de: 'Betroffene Struktur', en: 'Impact tree' },
  'impact.hint': { de: 'Betroffene Knoten wählen — Vorschläge zeigen strukturell betroffene Baugruppen.', en: 'Pick impacted nodes — suggestions mark structurally affected parent assemblies.' },
  'impact.suggested': { de: 'Vorschlag', en: 'Suggested' },
  'impact.lead': { de: 'Leit-Teil', en: 'Lead item' },
  'impact.apply': { de: 'Auswahl übernehmen', en: 'Apply selection' },
  'impact.locked': { de: 'Auswahl gesperrt — Umsetzung gestartet', en: 'Selection locked — implementation started' },
  'impact.empty': { de: 'Keine Teile im Projekt. Teile zuerst im Projekt anlegen.', en: 'No parts in this project. Create parts on the project page first.' },
```

- [ ] **Step 2: Write the failing component test**

```tsx
// frontend/src/components/changes/ImpactTree.test.tsx
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ImpactTree from './ImpactTree'
import { changesApi } from '../../api/changes'

vi.mock('../../api/changes', () => ({
  changesApi: {
    getImpactTree: vi.fn(),
    suggestImpact: vi.fn(),
    applyImpactSelection: vi.fn(),
  },
}))

const tree = {
  tree: [
    {
      part_id: 1, part_number: 'ASM-1', name: 'Assembly', part_type: 'sub_assembly',
      item_category: 'article', is_impacted: false, is_lead: false,
      resulting_revision_id: null,
      children: [
        { part_id: 2, part_number: 'CHD-1', name: 'Child', part_type: 'internal_mfg',
          item_category: 'article', is_impacted: true, is_lead: true,
          resulting_revision_id: null, children: [] },
        { part_id: 3, part_number: 'CHD-2', name: 'Sibling', part_type: 'internal_mfg',
          item_category: 'article', is_impacted: false, is_lead: false,
          resulting_revision_id: null, children: [] },
      ],
    },
  ],
  impacted_part_ids: [2],
  lead_part_id: 2,
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ImpactTree', () => {
  beforeEach(() => {
    vi.mocked(changesApi.getImpactTree).mockResolvedValue(tree)
    vi.mocked(changesApi.suggestImpact).mockResolvedValue({ suggested_part_ids: [1] })
    vi.mocked(changesApi.applyImpactSelection).mockResolvedValue({ impacted_part_ids: [2, 3] })
  })
  afterEach(cleanup)

  it('renders nodes and marks suggested parents when selection changes', async () => {
    wrap(<ImpactTree changeId={7} status="captured" />)
    expect(await screen.findByText('Child')).toBeDefined()
    fireEvent.click(screen.getByRole('checkbox', { name: /Sibling/ }))
    await waitFor(() =>
      expect(changesApi.suggestImpact).toHaveBeenCalledWith(7, [2, 3]))
    expect(await screen.findByText(/Suggested/)).toBeDefined()
  })

  it('lead checkbox is disabled and apply sends the selection', async () => {
    wrap(<ImpactTree changeId={7} status="captured" />)
    await screen.findByText('Child')
    const lead = screen.getByRole('checkbox', { name: /Child/ }) as HTMLInputElement
    expect(lead.disabled).toBe(true)
    fireEvent.click(screen.getByRole('checkbox', { name: /Sibling/ }))
    fireEvent.click(screen.getByRole('button', { name: /Apply selection/ }))
    await waitFor(() =>
      expect(changesApi.applyImpactSelection).toHaveBeenCalledWith(7, [2, 3]))
  })

  it('locks editing once implementation started', async () => {
    wrap(<ImpactTree changeId={7} status="in_implementation" />)
    await screen.findByText('Child')
    expect(screen.queryByRole('button', { name: /Apply selection/ })).toBeNull()
    expect(screen.getByText(/Selection locked/)).toBeDefined()
  })
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/changes/ImpactTree.test.tsx`
Expected: FAIL (module `./ImpactTree` not found).

- [ ] **Step 4: Implement the component**

```tsx
// frontend/src/components/changes/ImpactTree.tsx
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { changesApi } from '../../api/changes'
import type { ChangeStatus, ImpactTreeNode } from '../../types/change'
import { t } from '../../i18n/cmLabels'

const LOCKED: ChangeStatus[] = [
  'in_implementation', 'in_validation', 'released', 'closed', 'rejected', 'cancelled',
]

interface Props {
  changeId: number
  status: ChangeStatus
}

export default function ImpactTree({ changeId, status }: Props) {
  const qc = useQueryClient()
  const editable = !LOCKED.includes(status)
  const [selected, setSelected] = useState<Set<number>>(new Set())

  const { data, isLoading } = useQuery({
    queryKey: ['change', changeId, 'impact-tree'],
    queryFn: () => changesApi.getImpactTree(changeId),
  })

  useEffect(() => {
    if (data) setSelected(new Set(data.impacted_part_ids))
  }, [data])

  const selectedKey = useMemo(() => [...selected].sort((a, b) => a - b), [selected])

  const { data: suggestion } = useQuery({
    queryKey: ['change', changeId, 'impact-suggest', selectedKey.join(',')],
    queryFn: () => changesApi.suggestImpact(changeId, selectedKey),
    enabled: editable && selectedKey.length > 0,
  })
  const suggested = useMemo(
    () => new Set(suggestion?.suggested_part_ids ?? []), [suggestion])

  const apply = useMutation({
    mutationFn: () => changesApi.applyImpactSelection(changeId, selectedKey),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId, 'impact-tree'] })
    },
    onError: (e: any) => alert(e?.response?.data?.detail ?? 'Apply failed'),
  })

  const toggle = (partId: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(partId)) next.delete(partId)
      else next.add(partId)
      return next
    })
  }

  if (isLoading) return <div className="text-slate-400 text-sm">…</div>
  if (!data || data.tree.length === 0)
    return <div className="text-slate-400 text-sm">{t('impact.empty')}</div>

  const dirty =
    selectedKey.join(',') !== [...data.impacted_part_ids].sort((a, b) => a - b).join(',')

  const renderNode = (node: ImpactTreeNode, depth: number) => (
    <div key={node.part_id}>
      <div
        className="flex items-center gap-2 py-1 rounded hover:bg-slate-700/40"
        style={{ paddingLeft: `${depth * 20}px` }}
      >
        <input
          type="checkbox"
          className="accent-sky-500"
          aria-label={`${node.name} (${node.part_number})`}
          checked={selected.has(node.part_id)}
          disabled={!editable || node.is_lead || node.resulting_revision_id !== null}
          onChange={() => toggle(node.part_id)}
        />
        <span className="text-slate-100 text-sm">{node.name}</span>
        <span className="text-slate-500 text-xs">{node.part_number}</span>
        {node.is_lead && (
          <span className="px-2 py-0.5 rounded-full text-xs bg-sky-900 text-sky-100">
            {t('impact.lead')}
          </span>
        )}
        {node.resulting_revision_id !== null && (
          <span className="px-2 py-0.5 rounded-full text-xs bg-purple-900 text-purple-100">
            ECN #{node.resulting_revision_id}
          </span>
        )}
        {!selected.has(node.part_id) && suggested.has(node.part_id) && (
          <button
            onClick={() => editable && toggle(node.part_id)}
            className="px-2 py-0.5 rounded-full text-xs bg-amber-900 text-amber-100 hover:bg-amber-800"
            title={t('impact.hint')}
          >
            {t('impact.suggested')} +
          </button>
        )}
      </div>
      {node.children.map(c => renderNode(c, depth + 1))}
    </div>
  )

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-slate-100 font-semibold">{t('impact.title')}</h3>
          <p className="text-slate-400 text-xs">{t('impact.hint')}</p>
        </div>
        {editable ? (
          <button
            onClick={() => apply.mutate()}
            disabled={!dirty || apply.isPending}
            className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm disabled:opacity-50"
          >
            {t('impact.apply')}
          </button>
        ) : (
          <span className="text-amber-300 text-xs">{t('impact.locked')}</span>
        )}
      </div>
      {data.tree.map(n => renderNode(n, 0))}
    </div>
  )
}
```

Check `t`'s default language behavior in `cmLabels.ts` (defaults to `'en'`), so tests assert the English strings.

- [ ] **Step 5: Wire into `ChangeDetailPage.tsx`**

Replace the read-only impacted tab body (lines ~155-168) with:

```tsx
        {tab === 'impacted' && change && (
          <ImpactTree changeId={change.id} status={change.status} />
        )}
```

and add the import `import ImpactTree from '../components/changes/ImpactTree'`.

- [ ] **Step 6: Run tests + type-check**

Run: `cd frontend && npx vitest run src/components/changes/ImpactTree.test.tsx && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/changes/ImpactTree.tsx \
        frontend/src/components/changes/ImpactTree.test.tsx \
        frontend/src/types/change.ts frontend/src/api/changes.ts \
        frontend/src/pages/ChangeDetailPage.tsx frontend/src/i18n/cmLabels.ts
git commit -m "feat(frontend): interactive impact tree with roll-up suggestions replaces read-only list"
```

---

## Task 9: Frontend — implementation panel, evidence actions, waive, ready badge

**Tier:** opus (UX-critical; "the UI drives the task" hard requirement).

**Files:**
- Create: `frontend/src/components/changes/ImplementationPanel.tsx`, `frontend/src/components/changes/ImplementationPanel.test.tsx`
- Modify: `frontend/src/types/change.ts`, `frontend/src/types/workflow.ts`, `frontend/src/api/changes.ts`, `frontend/src/components/workflows/WorkflowProgress.tsx`, `frontend/src/pages/ChangeDetailPage.tsx`, `frontend/src/i18n/cmLabels.ts`

**Interfaces:**
- Consumes: `GET /v1/changes/{id}/implementation` (Task 7 shape), `POST /v1/parts/{partId}/revisions/{revId}/no-geometry-change` (Task 4), existing `CADUploader` (props: partId + revisionId multipart upload), existing `useRevisionWorkflow(revisionId)` + task-complete mutation, `ReasonDialog`.
- Produces: `<ImplementationPanel changeId={number} />`; types `ImplementationItem`, `ImplementationProgress`; api methods `getImplementation`, `signNoGeometryChange`; `WfTaskStatus`/`WfDecision` extended with `'waived'`; a Waive action on actionable workflow tasks.

- [ ] **Step 1: Types + api + labels**

`frontend/src/types/change.ts`:

```ts
export interface ImplementationItem {
  item_id: number
  part_id: number
  part_number: string | null
  part_name: string | null
  item_category: string | null
  is_lead: boolean
  revision_id: number | null
  revision_name: string | null
  instance_id: number | null
  instance_status: string | null
  current_stage_order: number | null
  total_stages: number | null
  has_cad_file: boolean
  no_geometry_change: boolean
  ready: boolean
}

export interface ImplementationProgress {
  ready_to_go: boolean
  items: ImplementationItem[]
}
```

`frontend/src/api/changes.ts`:

```ts
  getImplementation: (changeId: number): Promise<ImplementationProgress> =>
    client.get(`/v1/changes/${changeId}/implementation`).then(r => r.data),
  signNoGeometryChange: (partId: number, revisionId: number, reason: string) =>
    client.post(`/v1/parts/${partId}/revisions/${revisionId}/no-geometry-change`,
      { reason }).then(r => r.data),
```

`frontend/src/types/workflow.ts`: extend the task-status and decision unions with `'waived'` (`WfTaskStatus`, `WfDecision` at lines ~89-91).

`frontend/src/i18n/cmLabels.ts`:

```ts
  'impl.title': { de: 'Umsetzung', en: 'Implementation' },
  'impl.readyToGo': { de: 'Ready to go — alle Prüf-Workflows abgeschlossen', en: 'Ready to go — all check workflows completed' },
  'impl.notReady': { de: 'Noch nicht ready to go', en: 'Not ready to go yet' },
  'impl.evidenceOk': { de: '3D-Nachweis vorhanden', en: '3D evidence present' },
  'impl.evidenceMissing': { de: '3D-Nachweis fehlt', en: '3D evidence missing' },
  'impl.noGeometry': { de: 'Keine Geometrieänderung', en: 'No geometry change' },
  'impl.signNoGeometry': { de: 'Keine Geometrieänderung bestätigen', en: 'Sign no geometry change' },
  'impl.stage': { de: 'Stufe', en: 'Stage' },
  'impl.noRevision': { de: 'Noch keine ECN-Revision (Kickoff ausstehend)', en: 'No ECN revision yet (kickoff pending)' },
  'wf.waive': { de: 'Erlassen', en: 'Waive' },
  'wf.waiveReason': { de: 'Begründung für das Erlassen', en: 'Reason for waiving' },
```

- [ ] **Step 2: Write the failing component test**

```tsx
// frontend/src/components/changes/ImplementationPanel.test.tsx
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ImplementationPanel from './ImplementationPanel'
import { changesApi } from '../../api/changes'

vi.mock('../../api/changes', () => ({
  changesApi: {
    getImplementation: vi.fn(),
    signNoGeometryChange: vi.fn(),
  },
}))
vi.mock('../CADUploader', () => ({
  default: () => <div data-testid="cad-uploader" />,
}))
vi.mock('../workflows/RevisionWorkflowSection', () => ({
  default: () => <div data-testid="wf-section" />,
}))

const progress = {
  ready_to_go: false,
  items: [
    {
      item_id: 1, part_id: 10, part_number: 'P-100', part_name: 'Housing',
      item_category: 'article', is_lead: true,
      revision_id: 55, revision_name: 'ECR1.1',
      instance_id: 9, instance_status: 'active',
      current_stage_order: 1, total_stages: 4,
      has_cad_file: false, no_geometry_change: false, ready: false,
    },
  ],
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ImplementationPanel', () => {
  beforeEach(() => {
    vi.mocked(changesApi.getImplementation).mockResolvedValue(progress)
    vi.mocked(changesApi.signNoGeometryChange).mockResolvedValue({})
  })
  afterEach(cleanup)

  it('shows per-revision status and missing evidence with resolving actions', async () => {
    wrap(<ImplementationPanel changeId={7} />)
    expect(await screen.findByText(/ECR1\.1/)).toBeDefined()
    expect(screen.getByText(/3D evidence missing/)).toBeDefined()
    expect(screen.getByText(/Not ready to go/)).toBeDefined()
    expect(screen.getByRole('button', { name: /Sign no geometry change/ })).toBeDefined()
  })

  it('signs no-geometry-change with a reason', async () => {
    wrap(<ImplementationPanel changeId={7} />)
    await screen.findByText(/ECR1\.1/)
    fireEvent.click(screen.getByRole('button', { name: /Sign no geometry change/ }))
    const textarea = await screen.findByRole('textbox')
    fireEvent.change(textarea, { target: { value: 'label only' } })
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))
    await waitFor(() =>
      expect(changesApi.signNoGeometryChange).toHaveBeenCalledWith(10, 55, 'label only'))
  })

  it('shows the ready banner when all revisions are ready', async () => {
    vi.mocked(changesApi.getImplementation).mockResolvedValue({
      ready_to_go: true,
      items: [{ ...progress.items[0], instance_status: 'completed',
                has_cad_file: true, ready: true }],
    })
    wrap(<ImplementationPanel changeId={7} />)
    expect(await screen.findByText(/Ready to go/)).toBeDefined()
  })
})
```

(Adjust the two `vi.mock` module paths to the real relative paths once the component's imports are written; the confirm-button name must match `ReasonDialog`'s actual confirm label — check the component and align the test.)

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/changes/ImplementationPanel.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 4: Implement the panel**

```tsx
// frontend/src/components/changes/ImplementationPanel.tsx
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { changesApi } from '../../api/changes'
import type { ImplementationItem } from '../../types/change'
import { t } from '../../i18n/cmLabels'
import ReasonDialog from './ReasonDialog'
import CADUploader from '../CADUploader'
import RevisionWorkflowSection from '../workflows/RevisionWorkflowSection'

interface Props {
  changeId: number
}

export default function ImplementationPanel({ changeId }: Props) {
  const qc = useQueryClient()
  const [signTarget, setSignTarget] = useState<ImplementationItem | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [uploadFor, setUploadFor] = useState<number | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['change', changeId, 'implementation'],
    queryFn: () => changesApi.getImplementation(changeId),
  })

  const sign = useMutation({
    mutationFn: ({ item, reason }: { item: ImplementationItem; reason: string }) =>
      changesApi.signNoGeometryChange(item.part_id, item.revision_id!, reason),
    onSuccess: () => {
      setSignTarget(null)
      qc.invalidateQueries({ queryKey: ['change', changeId, 'implementation'] })
    },
    onError: (e: any) => alert(e?.response?.data?.detail ?? 'Sign-off failed'),
  })

  if (isLoading || !data) return <div className="text-slate-400 text-sm">…</div>

  return (
    <div className="space-y-4">
      <div
        data-testid="ready-banner"
        className={`rounded-lg border p-3 text-sm font-semibold ${
          data.ready_to_go
            ? 'bg-green-900/40 border-green-700 text-green-200'
            : 'bg-slate-800 border-slate-700 text-slate-300'
        }`}
      >
        {data.ready_to_go ? `✓ ${t('impl.readyToGo')}` : t('impl.notReady')}
      </div>

      {data.items.map(item => {
        const evidenceOk = item.has_cad_file || item.no_geometry_change
        return (
          <div key={item.item_id}
               className="bg-slate-800 rounded-lg border border-slate-700 p-4">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-slate-100 font-medium">
                {item.part_name} <span className="text-slate-500 text-xs">{item.part_number}</span>
              </span>
              {item.revision_name ? (
                <span className="px-2 py-0.5 rounded-full text-xs bg-purple-900 text-purple-100">
                  {item.revision_name}
                </span>
              ) : (
                <span className="text-slate-400 text-xs">{t('impl.noRevision')}</span>
              )}
              {item.instance_status && (
                <span className={`px-2 py-0.5 rounded-full text-xs ${
                  item.ready ? 'bg-green-900 text-green-100' : 'bg-blue-900 text-blue-100'
                }`}>
                  {item.ready
                    ? '✓'
                    : `${t('impl.stage')} ${item.current_stage_order}/${item.total_stages}`}{' '}
                  {item.instance_status}
                </span>
              )}
              <span className={`px-2 py-0.5 rounded-full text-xs ${
                evidenceOk ? 'bg-green-900 text-green-100' : 'bg-amber-900 text-amber-100'
              }`}>
                {evidenceOk
                  ? item.no_geometry_change ? t('impl.noGeometry') : t('impl.evidenceOk')
                  : t('impl.evidenceMissing')}
              </span>
            </div>

            {!evidenceOk && item.revision_id !== null && (
              <div className="mt-3 flex items-center gap-2">
                <button
                  onClick={() =>
                    setUploadFor(uploadFor === item.item_id ? null : item.item_id)}
                  className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs"
                >
                  Upload CAD
                </button>
                <button
                  onClick={() => setSignTarget(item)}
                  className="px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-100 text-xs"
                >
                  {t('impl.signNoGeometry')}
                </button>
              </div>
            )}
            {uploadFor === item.item_id && item.revision_id !== null && (
              <div className="mt-3">
                <CADUploader partId={item.part_id} revisionId={item.revision_id} />
              </div>
            )}

            {item.revision_id !== null && item.instance_id !== null && (
              <div className="mt-3">
                <button
                  onClick={() =>
                    setExpanded(expanded === item.item_id ? null : item.item_id)}
                  className="text-sky-400 hover:text-sky-300 text-xs"
                >
                  {expanded === item.item_id ? '▾ Workflow' : '▸ Workflow'}
                </button>
                {expanded === item.item_id && (
                  <RevisionWorkflowSection revisionId={item.revision_id} />
                )}
              </div>
            )}
          </div>
        )
      })}

      <ReasonDialog
        open={signTarget !== null}
        title={t('impl.signNoGeometry')}
        onCancel={() => setSignTarget(null)}
        onConfirm={(reason: string) =>
          signTarget && sign.mutate({ item: signTarget, reason })}
      />
    </div>
  )
}
```

Align `ReasonDialog` and `CADUploader`/`RevisionWorkflowSection` prop names with their actual definitions before finalizing (e.g. `ReasonDialog` may use `isOpen`/`onSubmit` — mirror how `ChangeDetailPage` and `DeviationBanner` invoke it; `CADUploader` may need extra props for its invalidation keys).

- [ ] **Step 5: Waive action in `WorkflowProgress.tsx` + tab & badge wiring**

In `frontend/src/components/workflows/WorkflowProgress.tsx`: in the `TaskRow` actions (where Approve/Reject render for actionable active tasks), add a Waive action that reuses the existing reject-notes modal flow. Concretely, generalize the modal state from a reject-only shape to a moded one and add the button:

```tsx
// state: replace the reject-modal task state with a moded variant
const [notesModal, setNotesModal] = useState<{ taskId: number; mode: 'rejected' | 'waived' } | null>(null)
```

```tsx
// in TaskRow actions, next to the existing Reject button:
<button
  onClick={() => setNotesModal({ taskId: task.id, mode: 'waived' })}
  className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100 text-xs"
>
  {t('wf.waive')}
</button>
```

```tsx
// modal confirm handler: decision comes from the mode; notes required in both modes
completeTask.mutate({ taskId: notesModal.taskId, decision: notesModal.mode, notes })
```

Adapt names to the file's actual state/mutation variables (the reject modal and complete-task mutation already exist — extend them, don't duplicate). Set the modal title to `t('wf.waiveReason')` in waive mode. Render waived tasks with a slate pill (`bg-slate-700 text-slate-200`, same pill classes as the approved/rejected ones, label `waived`).

In `frontend/src/pages/ChangeDetailPage.tsx`:
1. Extend the `Tab` union with `'implementation'` and add a tab button (label `t('impl.title')`) after `impacted`.
2. Render `{tab === 'implementation' && change && <ImplementationPanel changeId={change.id} />}`.
3. Header ready badge: add alongside the status pill —

```tsx
const { data: impl } = useQuery({
  queryKey: ['change', changeId, 'implementation'],
  queryFn: () => changesApi.getImplementation(changeId),
  enabled: !!change && ['in_implementation', 'in_validation', 'released']
    .includes(change.status),
})
```

```tsx
{impl?.ready_to_go && (
  <span className="px-3 py-1 rounded-full text-xs font-semibold bg-green-900 text-green-100">
    ✓ {t('impl.readyToGo')}
  </span>
)}
```

(match the page's existing variable names for `changeId`/`change`).

- [ ] **Step 6: Run tests + type-check + full frontend suite**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all tests PASS (including the pre-existing 4 test files), no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/changes/ImplementationPanel.tsx \
        frontend/src/components/changes/ImplementationPanel.test.tsx \
        frontend/src/components/workflows/WorkflowProgress.tsx \
        frontend/src/types/change.ts frontend/src/types/workflow.ts \
        frontend/src/api/changes.ts frontend/src/pages/ChangeDetailPage.tsx \
        frontend/src/i18n/cmLabels.ts
git commit -m "feat(frontend): implementation panel with evidence actions, waive, ready-to-go badge"
```

---

## Task 10: Final verification

**Tier:** sonnet.

**Files:** none (verification only; fix regressions where they surface).

- [ ] **Step 1: Full backend suite**

Run: `cd backend && python3 -m pytest`
Expected: all PASS.

- [ ] **Step 2: Migration idempotency on the dev DB**

Run: `cd backend && python3 -m alembic upgrade head && python3 -m alembic upgrade head`
Expected: both invocations exit 0 (inspect guards make the second a no-op).

- [ ] **Step 3: Full frontend suite + types + lint**

Run: `cd frontend && npx vitest run && npx tsc --noEmit && npm run lint`
Expected: all PASS, zero warnings (lint runs with `--max-warnings 0`).

- [ ] **Step 4: Spec cross-check (manual)**

Confirm each Phase B spec item maps to shipped behavior:
- Impact tree explicit pick + suggested roll-up, nothing revises silently → Tasks 5/8.
- ECN revisions with bidirectional links (`originating_change_id` + `resulting_revision_id`) → Tasks 1/6.
- Check-WF instance per ECN revision from mapped, designer-editable seeded template → Tasks 2/6.
- 3D evidence (CAD file or owner-signed no-geometry-change) gates the 3D step → Tasks 3/4.
- Waivable steps with audited reason; 4-eyes design check → Task 3.
- Computed ready-to-go exposed on the change and guarding release (deviation-bypassable only) → Tasks 7/9.
- All new events land in the hash-chained `AuditLog` with change correlation → Tasks 3/4/5/6 (via `append_changelog` / `AuditService.record`).

- [ ] **Step 5: Commit any verification fixes**

```bash
git add -A backend frontend
git commit -m "test: Phase B verification fixes"
```

(Skip the commit if nothing changed.)
