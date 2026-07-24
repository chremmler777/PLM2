# Änderungsmitteilung Digitization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing change-assessment-routing feature so PLM2 captures the full `GB-CM-0001` Änderungsmitteilung — per-department cost lines (intern/extern × plant), department×plant rates, a seeded activity catalog, D1 master fields, and the 3 gates — with the in-app forms as the primary entry path.

**Architecture:** New normalized tables (`department_rate`, `assessment_activity`, `assessment_cost_line`, `change_gate`) plus an association table `change_affected_plants` and additive columns on `change_requests` / `change_impacted_items` / `change_assessments`. A new `CostService` computes `internal_cost = demand_hours × rate` and the `Summierung` roll-up (computed, never stored). API endpoints extend the existing `/api/v1/changes` router. Frontend adds a cost-line grid, a D1 master panel, and a Summierung view, following the existing dark-slate Tailwind + react-query conventions.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 (async, `Mapped`/`mapped_column`), Alembic, Pydantic v2 (`from_attributes`), pytest + pytest-asyncio (`asyncio_mode=auto`); React + TypeScript, @tanstack/react-query, Tailwind, vitest + @testing-library/react.

## Global Constraints

- Backend tests build the schema with `Base.metadata.create_all` (see `backend/tests/conftest.py`), so **every new model MUST be imported in `backend/app/models/__init__.py`** or it will be invisible to tests.
- Every new/changed model also needs an **Alembic migration**; new migration id is `021`, `down_revision = '020'` (current head is `020`). Follow the idempotent `inspect(op.get_bind())` guard pattern from `020_change_assessment_routing.py` (check table/column existence before create) — never call `.create()` on enums; use `sa.String` for enum-like fields exactly as existing models do.
- All persisted audited actions append to the hash-chained changelog via `ChangeService.append_changelog(...)`.
- Pydantic response models use `class Config: from_attributes = True` (match `backend/app/schemas/change.py`).
- Run backend tests from `backend/` with `python3 -m pytest` (the bare `python` command is absent on this host).
- Enum-like value tuples live as module constants next to the model (mirror `CHANGE_STATUSES`, `TASK_LETTERS`).
- Gate→state-machine wiring is **additive and backward-compatible**: a gate only constrains a transition when a `change_gate` row exists for that change; changes without gate rows behave exactly as today (keeps existing `test_changes.py` green).
- Money/hours are stored as `Float`; do not round on storage, round only for display.

---

## File Structure

**Backend — create:**
- `backend/app/models/change_cost.py` — `DepartmentRate`, `AssessmentActivity`, `AssessmentCostLine`, `ChangeGate`, and the `COST_KINDS` / `GATE_KEYS` / `GATE_TARGET_STATUS` constants.
- `backend/app/services/cost_service.py` — `CostService` (rate lookup, cost-line replace, totals recompute, Summierung).
- `backend/tests/test_change_cost.py` — cost math, roll-up, cost-line API, reference endpoints.
- `backend/tests/test_change_gates.py` — gate decisions + state-machine wiring.
- `backend/alembic/versions/021_add_cm_cost_lines.py` — migration for all new tables/columns.

**Backend — modify:**
- `backend/app/models/change.py` — D1 fields on `ChangeRequest`, `affected_plants` relationship + `change_affected_plants` table, `is_lead` on `ChangeImpactedItem`, and `producibility` / `contact_person` / `approval_comment` + `lifecycle_cost` + `cost_lines` relationship on `ChangeAssessment`; `gates` relationship on `ChangeRequest`.
- `backend/app/models/__init__.py` — register the new models.
- `backend/app/services/change_service.py` — `decide_gate`, gate-aware `_guard`, D1 fields in `update_change`'s allow-list.
- `backend/app/schemas/change.py` — cost-line, summation, gate, reference, and extended D1 / assessment schemas.
- `backend/app/api/v1/changes/changes.py` — cost-line, summation, gate, and reference endpoints.

**Frontend — modify:**
- `frontend/src/types/change.ts` — cost-line, summation, gate, reference types; D1 fields.
- `frontend/src/api/changes.ts` — client wrappers for the new endpoints.
- `frontend/src/i18n/cmLabels.ts` *(create)* — DE/EN label key map.
- `frontend/src/components/changes/CostLineGrid.tsx` *(create)* — department cost-line editor.
- `frontend/src/components/changes/D1MasterPanel.tsx` *(create)* — header + approval matrix + gates.
- `frontend/src/components/changes/SummationView.tsx` *(create)* — read-only roll-up.
- `frontend/src/components/changes/CostLineGrid.test.tsx` *(create)* — vitest for live internal-cost calc.

---

## Task 1: Reference tables — `DepartmentRate` + `AssessmentActivity`

**Files:**
- Create: `backend/app/models/change_cost.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_change_cost.py`

**Interfaces:**
- Produces: `DepartmentRate(id, department_id, plant_id, hourly_rate: float, min_factor: float, effective_from: date)`; `AssessmentActivity(id, department_id, label: str, sort_order: int, is_active: bool)`; constants `COST_KINDS = ("one_time", "lifecycle")`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_change_cost.py
import pytest
pytestmark = pytest.mark.asyncio


async def test_reference_models_persist(session_factory):
    from app.models.change_cost import DepartmentRate, AssessmentActivity, COST_KINDS
    from app.models.workflow import Department
    from app.models.entities import Organization, Plant
    from datetime import date
    async with session_factory() as s:
        org = Organization(name="O", code="o"); s.add(org); await s.flush()
        plant = Plant(organization_id=org.id, name="Weissenburg", code="WUG"); s.add(plant)
        dep = Department(name="Sales", flow_type="action"); s.add(dep)
        await s.flush()
        s.add(DepartmentRate(department_id=dep.id, plant_id=plant.id,
                             hourly_rate=50.0, min_factor=0.6, effective_from=date(2026, 1, 1)))
        s.add(AssessmentActivity(department_id=dep.id, label="Angebotserstellung",
                                 sort_order=1, is_active=True))
        await s.commit()
        rate = (await s.execute(__import__("sqlalchemy").select(DepartmentRate))).scalar_one()
        assert rate.hourly_rate == 50.0 and rate.min_factor == 0.6
        assert COST_KINDS == ("one_time", "lifecycle")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_change_cost.py::test_reference_models_persist -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.change_cost'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/models/change_cost.py
"""Cost-assessment models digitizing the GB-CM-0001 department tabs:
per-department×plant rates, the seeded activity catalog, per-line costs, and
the three D1 gates."""
from datetime import date, datetime

from sqlalchemy import String, Text, DateTime, Date, Float, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

COST_KINDS = ("one_time", "lifecycle")
GATE_KEYS = ("feasibility", "budget", "release")
GATE_DECISIONS = ("yes", "no", "na")
# Which transition each gate guards (additive; see Global Constraints).
GATE_TARGET_STATUS = {"feasibility": "in_assessment", "budget": "costing", "release": "in_implementation"}


class DepartmentRate(Base):
    """Hourly rate for a department at a plant (from the Std.-Sätze sheet)."""
    __tablename__ = "department_rate"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"), index=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), index=True)
    hourly_rate: Mapped[float] = mapped_column(Float)
    min_factor: Mapped[float] = mapped_column(Float, default=1.0)
    effective_from: Mapped[date] = mapped_column(Date, default=date.today)


class AssessmentActivity(Base):
    """A predefined cost-line activity offered to a department (its selection list)."""
    __tablename__ = "assessment_activity"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
```

Then register in `backend/app/models/__init__.py` — add after the `from app.models.change import (...)` block:

```python
from app.models.change_cost import (
    DepartmentRate, AssessmentActivity, AssessmentCostLine, ChangeGate,
)
```

and append `"DepartmentRate", "AssessmentActivity", "AssessmentCostLine", "ChangeGate",` to `__all__`.

> Note: `AssessmentCostLine` and `ChangeGate` are added in Tasks 2 and 5; add all four names now so the import line is written once. If running Task 1 in isolation, temporarily import only the two defined classes and add the others in their tasks.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_change_cost.py::test_reference_models_persist -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/change_cost.py backend/app/models/__init__.py backend/tests/test_change_cost.py
git commit -m "feat(change): department rate + activity catalog models"
```

---

## Task 2: `AssessmentCostLine` model, assessment extensions, and cost math

**Files:**
- Modify: `backend/app/models/change_cost.py`, `backend/app/models/change.py`
- Create: `backend/app/services/cost_service.py`
- Test: `backend/tests/test_change_cost.py`

**Interfaces:**
- Consumes: `DepartmentRate`, `COST_KINDS` (Task 1).
- Produces:
  - `AssessmentCostLine(id, assessment_id, plant_id, activity_id: int|None, activity_label: str|None, cost_kind: str, demand_hours: float, rate_snapshot: float, internal_cost: float, external_cost: float, note: str|None)`
  - `ChangeAssessment.cost_lines` relationship; new columns `producibility: str`, `contact_person: str|None`, `approval_comment: str|None`, `lifecycle_cost: float|None`.
  - `CostService.rate_for(session, department_id, plant_id) -> float | None`
  - `CostService.replace_cost_lines(session, change, assessment, lines: list[dict], user_id) -> list[AssessmentCostLine]` where each `line` dict has keys `plant_id, cost_kind, demand_hours, external_cost` and optional `activity_id, activity_label, note`.
  - `CostService.recompute_assessment_totals(assessment) -> None` (sets `cost_impact` = sum one_time internal+external; `lifecycle_cost` = sum lifecycle internal+external).

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_change_cost.py
async def test_replace_cost_lines_computes_internal_cost(session_factory, seed):
    from sqlalchemy import select
    from datetime import date
    from app.models.change import ChangeRequest, ChangeAssessment
    from app.models.change_cost import DepartmentRate, AssessmentCostLine
    from app.models.workflow import Department
    from app.models.entities import Plant
    from app.services.cost_service import CostService
    async with session_factory() as s:
        plant = (await s.execute(select(Plant))).scalars().first()
        dep = Department(name="R&D", flow_type="action"); s.add(dep); await s.flush()
        s.add(DepartmentRate(department_id=dep.id, plant_id=plant.id,
                             hourly_rate=65.0, min_factor=0.6, effective_from=date(2026, 1, 1)))
        change = ChangeRequest(change_number="CR-T-2", project_id=seed["project_id"],
                               title="t", change_type="physical_part", status="in_assessment",
                               raised_by=seed["engineer_id"], lead_id=seed["engineer_id"])
        s.add(change); await s.flush()
        a = ChangeAssessment(change_id=change.id, department_id=dep.id, verdict="pending")
        s.add(a); await s.flush()
        await CostService.replace_cost_lines(s, change, a, [
            {"plant_id": plant.id, "cost_kind": "one_time", "demand_hours": 5.0,
             "external_cost": 100.0, "activity_label": "3D-Konstruktion"},
        ], seed["engineer_id"])
        await s.commit()
        line = (await s.execute(select(AssessmentCostLine))).scalar_one()
        assert line.rate_snapshot == 65.0
        assert line.internal_cost == 325.0          # 5h × 65
        assert a.cost_impact == 425.0               # 325 internal + 100 external (one_time)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_change_cost.py::test_replace_cost_lines_computes_internal_cost -v`
Expected: FAIL with `ImportError`/`AttributeError` (no `AssessmentCostLine` / `cost_service`).

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/models/change_cost.py`:

```python
class AssessmentCostLine(Base):
    """One cost line on a department's assessment tab (per plant, one-time or lifecycle)."""
    __tablename__ = "assessment_cost_line"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("change_assessments.id"), index=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), index=True)
    activity_id: Mapped[int | None] = mapped_column(ForeignKey("assessment_activity.id"), nullable=True)
    activity_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cost_kind: Mapped[str] = mapped_column(String(20), default="one_time")
    demand_hours: Mapped[float] = mapped_column(Float, default=0.0)
    rate_snapshot: Mapped[float] = mapped_column(Float, default=0.0)
    internal_cost: Mapped[float] = mapped_column(Float, default=0.0)
    external_cost: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessment: Mapped["ChangeAssessment"] = relationship(back_populates="cost_lines")
```

In `backend/app/models/change.py`, add to `ChangeAssessment` (after `notes`):

```python
    producibility: Mapped[str] = mapped_column(String(10), default="na", server_default="na")  # yes|no|na
    contact_person: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approval_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
```

and add the relationship (after `department = relationship(...)`):

```python
    cost_lines: Mapped[list["AssessmentCostLine"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", lazy="selectin",
    )
```

and at the bottom import block of `change.py` add:

```python
from app.models.change_cost import AssessmentCostLine  # noqa: E402
```

Create `backend/app/services/cost_service.py`:

```python
"""Cost-line math + Summierung roll-up for the digitized Änderungsmitteilung."""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeRequest, ChangeAssessment
from app.models.change_cost import AssessmentCostLine, DepartmentRate, COST_KINDS


class CostError(ValueError):
    """Invalid cost-line operation; mapped to HTTP 400 in the router."""


class CostService:

    @staticmethod
    async def rate_for(session: AsyncSession, department_id: int, plant_id: int) -> Optional[float]:
        row = (await session.execute(
            select(DepartmentRate).where(
                (DepartmentRate.department_id == department_id)
                & (DepartmentRate.plant_id == plant_id)
            ).order_by(DepartmentRate.effective_from.desc())
        )).scalars().first()
        return row.hourly_rate if row else None

    @staticmethod
    def recompute_assessment_totals(assessment: ChangeAssessment) -> None:
        one_time = sum(l.internal_cost + l.external_cost
                       for l in assessment.cost_lines if l.cost_kind == "one_time")
        lifecycle = sum(l.internal_cost + l.external_cost
                        for l in assessment.cost_lines if l.cost_kind == "lifecycle")
        assessment.cost_impact = one_time
        assessment.lifecycle_cost = lifecycle

    @staticmethod
    async def replace_cost_lines(session: AsyncSession, change: ChangeRequest,
                                 assessment: ChangeAssessment, lines: list[dict],
                                 user_id: int) -> list[AssessmentCostLine]:
        from app.services.change_service import ChangeService  # local import avoids cycle
        for old in list(assessment.cost_lines):
            await session.delete(old)
        await session.flush()
        new_lines: list[AssessmentCostLine] = []
        for spec in lines:
            cost_kind = spec.get("cost_kind", "one_time")
            if cost_kind not in COST_KINDS:
                raise CostError(f"Invalid cost_kind '{cost_kind}'")
            if spec.get("activity_id") is None and not spec.get("activity_label"):
                raise CostError("Free-input line requires an activity_label")
            plant_id = spec["plant_id"]
            demand_hours = float(spec.get("demand_hours") or 0.0)
            rate = await CostService.rate_for(session, assessment.department_id, plant_id)
            if rate is None and demand_hours > 0:
                raise CostError(
                    f"No rate for department {assessment.department_id} at plant {plant_id}")
            rate = rate or 0.0
            line = AssessmentCostLine(
                assessment_id=assessment.id, plant_id=plant_id,
                activity_id=spec.get("activity_id"), activity_label=spec.get("activity_label"),
                cost_kind=cost_kind, demand_hours=demand_hours, rate_snapshot=rate,
                internal_cost=demand_hours * rate,
                external_cost=float(spec.get("external_cost") or 0.0),
                note=spec.get("note"),
            )
            session.add(line)
            new_lines.append(line)
        await session.flush()
        await session.refresh(assessment, ["cost_lines"])
        CostService.recompute_assessment_totals(assessment)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "cost_lines_updated",
            f"Cost lines updated for dept {assessment.department_id} "
            f"({len(new_lines)} lines)", user_id,
            field_name="cost_impact", new_value=assessment.cost_impact,
        )
        return new_lines
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_change_cost.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/change_cost.py backend/app/models/change.py backend/app/services/cost_service.py backend/tests/test_change_cost.py
git commit -m "feat(change): cost-line model + internal-cost computation"
```

---

## Task 3: Summierung roll-up

**Files:**
- Modify: `backend/app/services/cost_service.py`
- Test: `backend/tests/test_change_cost.py`

**Interfaces:**
- Consumes: `CostService.replace_cost_lines` (Task 2).
- Produces: `CostService.summation(session, change) -> dict` returning
  `{"by_plant": [{"plant_id", "one_time_internal", "one_time_external", "lifecycle_internal", "lifecycle_external"}], "by_department": [{"department_id", ...same four...}], "totals": {"one_time_internal", "one_time_external", "lifecycle_internal", "lifecycle_external", "grand_total"}}`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_change_cost.py
async def test_summation_rolls_up_by_plant_and_department(session_factory, seed):
    from sqlalchemy import select
    from datetime import date
    from app.models.change import ChangeRequest, ChangeAssessment
    from app.models.change_cost import DepartmentRate
    from app.models.workflow import Department
    from app.models.entities import Plant
    from app.services.cost_service import CostService
    async with session_factory() as s:
        plant = (await s.execute(select(Plant))).scalars().first()
        dep = Department(name="Sales", flow_type="action"); s.add(dep); await s.flush()
        s.add(DepartmentRate(department_id=dep.id, plant_id=plant.id,
                             hourly_rate=50.0, min_factor=0.6, effective_from=date(2026, 1, 1)))
        change = ChangeRequest(change_number="CR-T-3", project_id=seed["project_id"],
                               title="t", change_type="physical_part", status="in_assessment",
                               raised_by=seed["engineer_id"], lead_id=seed["engineer_id"])
        s.add(change); await s.flush()
        a = ChangeAssessment(change_id=change.id, department_id=dep.id, verdict="pending")
        s.add(a); await s.flush()
        await CostService.replace_cost_lines(s, change, a, [
            {"plant_id": plant.id, "cost_kind": "one_time", "demand_hours": 2.0,
             "external_cost": 50.0, "activity_label": "Angebotserstellung"},
            {"plant_id": plant.id, "cost_kind": "lifecycle", "demand_hours": 1.0,
             "external_cost": 0.0, "activity_label": "Betreuung"},
        ], seed["engineer_id"])
        await s.commit()
        summ = await CostService.summation(s, change)
        assert summ["totals"]["one_time_internal"] == 100.0   # 2h × 50
        assert summ["totals"]["one_time_external"] == 50.0
        assert summ["totals"]["lifecycle_internal"] == 50.0   # 1h × 50
        assert summ["totals"]["grand_total"] == 200.0
        assert summ["by_plant"][0]["plant_id"] == plant.id
        assert summ["by_department"][0]["department_id"] == dep.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_change_cost.py::test_summation_rolls_up_by_plant_and_department -v`
Expected: FAIL with `AttributeError: type object 'CostService' has no attribute 'summation'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/services/cost_service.py`:

```python
    @staticmethod
    async def summation(session: AsyncSession, change: ChangeRequest) -> dict:
        rows = (await session.execute(
            select(AssessmentCostLine, ChangeAssessment.department_id)
            .join(ChangeAssessment, ChangeAssessment.id == AssessmentCostLine.assessment_id)
            .where(ChangeAssessment.change_id == change.id)
        )).all()

        def _blank() -> dict:
            return {"one_time_internal": 0.0, "one_time_external": 0.0,
                    "lifecycle_internal": 0.0, "lifecycle_external": 0.0}

        by_plant: dict[int, dict] = {}
        by_dep: dict[int, dict] = {}
        totals = _blank()
        for line, department_id in rows:
            pk = "one_time" if line.cost_kind == "one_time" else "lifecycle"
            for bucket, key in ((by_plant.setdefault(line.plant_id, _blank()), None),
                                (by_dep.setdefault(department_id, _blank()), None),
                                (totals, None)):
                bucket[f"{pk}_internal"] += line.internal_cost
                bucket[f"{pk}_external"] += line.external_cost
        totals["grand_total"] = (totals["one_time_internal"] + totals["one_time_external"]
                                 + totals["lifecycle_internal"] + totals["lifecycle_external"])
        return {
            "by_plant": [{"plant_id": pid, **vals} for pid, vals in sorted(by_plant.items())],
            "by_department": [{"department_id": did, **vals} for did, vals in sorted(by_dep.items())],
            "totals": totals,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_change_cost.py::test_summation_rolls_up_by_plant_and_department -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cost_service.py backend/tests/test_change_cost.py
git commit -m "feat(change): Summierung roll-up by plant and department"
```

---

## Task 4: Cost-line + summation API and schemas

**Files:**
- Modify: `backend/app/schemas/change.py`, `backend/app/api/v1/changes/changes.py`
- Test: `backend/tests/test_change_cost.py`

**Interfaces:**
- Consumes: `CostService.replace_cost_lines`, `CostService.summation` (Tasks 2–3).
- Produces endpoints:
  - `GET /api/v1/changes/{change_id}/assessments/{aid}/cost-lines` → `list[CostLineResponse]`
  - `PUT /api/v1/changes/{change_id}/assessments/{aid}/cost-lines` body `CostLineReplace{lines: list[CostLineIn]}` → `list[CostLineResponse]`
  - `GET /api/v1/changes/{change_id}/summation` → `SummationResponse`
- Schemas: `CostLineIn{plant_id:int, cost_kind:str="one_time", demand_hours:float=0, external_cost:float=0, activity_id:int|None, activity_label:str|None, note:str|None}`, `CostLineReplace{lines:list[CostLineIn]}`, `CostLineResponse{id, plant_id, activity_id, activity_label, cost_kind, demand_hours, rate_snapshot, internal_cost, external_cost, note}`, `PlantRollup{plant_id, one_time_internal, one_time_external, lifecycle_internal, lifecycle_external}`, `DeptRollup{department_id, ...four...}`, `SummationTotals{...four..., grand_total}`, `SummationResponse{by_plant, by_department, totals}`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_change_cost.py
async def _captured_change_with_assessment(client, eng_auth, seed, session_factory):
    from datetime import date
    from sqlalchemy import select
    from app.models.workflow import Department
    from app.models.change_cost import DepartmentRate
    from app.models.entities import Plant
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "c", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    async with session_factory() as s:
        plant = (await s.execute(select(Plant))).scalars().first()
        dep = Department(name="Sales", flow_type="action"); s.add(dep); await s.flush()
        s.add(DepartmentRate(department_id=dep.id, plant_id=plant.id, hourly_rate=50.0,
                             min_factor=0.6, effective_from=date(2026, 1, 1)))
        from app.models.change import ChangeAssessment
        a = ChangeAssessment(change_id=cid, department_id=dep.id, verdict="pending")
        s.add(a); await s.commit()
        return cid, a.id, dep.id, plant.id


async def test_put_and_get_cost_lines_and_summation(client, eng_auth, seed, session_factory):
    cid, aid, dep_id, plant_id = await _captured_change_with_assessment(
        client, eng_auth, seed, session_factory)
    put = await client.put(
        f"/api/v1/changes/{cid}/assessments/{aid}/cost-lines",
        json={"lines": [{"plant_id": plant_id, "cost_kind": "one_time",
                         "demand_hours": 3.0, "external_cost": 10.0,
                         "activity_label": "Angebot"}]},
        headers=eng_auth)
    assert put.status_code == 200, put.text
    assert put.json()[0]["internal_cost"] == 150.0
    got = await client.get(f"/api/v1/changes/{cid}/assessments/{aid}/cost-lines", headers=eng_auth)
    assert len(got.json()) == 1
    summ = await client.get(f"/api/v1/changes/{cid}/summation", headers=eng_auth)
    assert summ.json()["totals"]["grand_total"] == 160.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_change_cost.py::test_put_and_get_cost_lines_and_summation -v`
Expected: FAIL with 404 (routes not defined yet).

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/schemas/change.py`:

```python
class CostLineIn(BaseModel):
    plant_id: int
    cost_kind: str = "one_time"
    demand_hours: float = 0.0
    external_cost: float = 0.0
    activity_id: Optional[int] = None
    activity_label: Optional[str] = None
    note: Optional[str] = None


class CostLineReplace(BaseModel):
    lines: List[CostLineIn] = []


class CostLineResponse(BaseModel):
    id: int
    plant_id: int
    activity_id: Optional[int] = None
    activity_label: Optional[str] = None
    cost_kind: str
    demand_hours: float
    rate_snapshot: float
    internal_cost: float
    external_cost: float
    note: Optional[str] = None

    class Config:
        from_attributes = True


class PlantRollup(BaseModel):
    plant_id: int
    one_time_internal: float
    one_time_external: float
    lifecycle_internal: float
    lifecycle_external: float


class DeptRollup(BaseModel):
    department_id: int
    one_time_internal: float
    one_time_external: float
    lifecycle_internal: float
    lifecycle_external: float


class SummationTotals(BaseModel):
    one_time_internal: float
    one_time_external: float
    lifecycle_internal: float
    lifecycle_external: float
    grand_total: float


class SummationResponse(BaseModel):
    by_plant: List[PlantRollup] = []
    by_department: List[DeptRollup] = []
    totals: SummationTotals
```

In `backend/app/api/v1/changes/changes.py`, extend the schema import to add `CostLineReplace, CostLineResponse, SummationResponse`, then add these routes (place **after** the `submit_assessment` route, i.e. among the `/{change_id}/...` routes):

```python
@router.get("/{change_id}/assessments/{aid}/cost-lines", response_model=List[CostLineResponse])
async def get_cost_lines(
    change_id: int, aid: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    a = await db.get(ChangeAssessment, aid)
    if not a or a.change_id != change_id:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return a.cost_lines


@router.put("/{change_id}/assessments/{aid}/cost-lines", response_model=List[CostLineResponse])
async def put_cost_lines(
    change_id: int, aid: int, body: CostLineReplace,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.cost_service import CostService, CostError
    change = await ChangeService.get_change(db, change_id)
    a = await db.get(ChangeAssessment, aid)
    if not change or not a or a.change_id != change_id:
        raise HTTPException(status_code=404, detail="Assessment not found")
    try:
        lines = await CostService.replace_cost_lines(
            db, change, a, [l.model_dump() for l in body.lines], current_user.id)
    except CostError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return lines


@router.get("/{change_id}/summation", response_model=SummationResponse)
async def get_summation(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.cost_service import CostService
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return await CostService.summation(db, change)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_change_cost.py::test_put_and_get_cost_lines_and_summation -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/change.py backend/app/api/v1/changes/changes.py backend/tests/test_change_cost.py
git commit -m "feat(change): cost-line + summation API"
```

---

## Task 5: `ChangeGate` model, decisions, and state-machine wiring

**Files:**
- Modify: `backend/app/models/change_cost.py`, `backend/app/models/change.py`, `backend/app/services/change_service.py`, `backend/app/schemas/change.py`, `backend/app/api/v1/changes/changes.py`
- Test: `backend/tests/test_change_gates.py`

**Interfaces:**
- Consumes: `GATE_KEYS`, `GATE_DECISIONS`, `GATE_TARGET_STATUS` (Task 1).
- Produces:
  - `ChangeGate(id, change_id, gate_key:str, decision:str="na", decided_by:int|None, decided_at:datetime|None, remark:str|None)`; `ChangeRequest.gates` relationship.
  - `ChangeService.decide_gate(session, change, gate_key, decision, user_id, remark=None) -> ChangeGate`
  - Endpoints `GET /api/v1/changes/{change_id}/gates` → `list[GateResponse]`; `PUT /api/v1/changes/{change_id}/gates/{gate_key}` body `GateDecisionIn{decision, remark?}` → `GateResponse`.
  - `_guard` returns a soft reason when a gate row exists for the target status and its `decision != "yes"`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_change_gates.py
import pytest
pytestmark = pytest.mark.asyncio


async def test_decide_gate_records_and_lists(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "g", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    put = await client.put(f"/api/v1/changes/{cid}/gates/feasibility",
                           json={"decision": "yes", "remark": "ok"}, headers=eng_auth)
    assert put.status_code == 200, put.text
    assert put.json()["decision"] == "yes"
    lst = await client.get(f"/api/v1/changes/{cid}/gates", headers=eng_auth)
    keys = {g["gate_key"]: g["decision"] for g in lst.json()}
    assert keys["feasibility"] == "yes"


async def test_gate_blocks_transition_until_yes(client, eng_auth, seed, session_factory):
    from sqlalchemy import select
    from app.models.part import Part
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "g2", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    # add an impacted item so the existing in_assessment guard passes
    pres = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": "PG-1", "name": "x",
        "part_type": "sub_assembly", "data_classification": "confidential"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": pres.json()["id"]}, headers=eng_auth)
    # set the feasibility gate to "no" -> transition must be blocked without justification
    await client.put(f"/api/v1/changes/{cid}/gates/feasibility",
                     json={"decision": "no"}, headers=eng_auth)
    blocked = await client.post(f"/api/v1/changes/{cid}/transition",
                                json={"to_status": "in_assessment"}, headers=eng_auth)
    assert blocked.status_code == 400
    assert "gate" in blocked.json()["detail"].lower()
    # flip to yes -> allowed
    await client.put(f"/api/v1/changes/{cid}/gates/feasibility",
                     json={"decision": "yes"}, headers=eng_auth)
    ok = await client.post(f"/api/v1/changes/{cid}/transition",
                           json={"to_status": "in_assessment"}, headers=eng_auth)
    assert ok.status_code == 200, ok.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_change_gates.py -v`
Expected: FAIL with 404 / 405 (gate routes missing).

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/models/change_cost.py`:

```python
class ChangeGate(Base):
    """One of the three D1 'Final assessment' gates on a change."""
    __tablename__ = "change_gate"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)
    gate_key: Mapped[str] = mapped_column(String(20))  # feasibility|budget|release
    decision: Mapped[str] = mapped_column(String(10), default="na")  # yes|no|na
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    change: Mapped["ChangeRequest"] = relationship(back_populates="gates")
```

In `backend/app/models/change.py`, add to `ChangeRequest` relationships:

```python
    gates: Mapped[list["ChangeGate"]] = relationship(
        back_populates="change", cascade="all, delete-orphan", lazy="selectin",
    )
```

and to the bottom import block of `change.py`:

```python
from app.models.change_cost import ChangeGate  # noqa: E402
```

In `backend/app/services/change_service.py`, import the gate constants near the top:

```python
from app.models.change_cost import ChangeGate
from app.models.change_cost import GATE_KEYS, GATE_DECISIONS, GATE_TARGET_STATUS
```

Add a method to `ChangeService`:

```python
    @staticmethod
    async def decide_gate(
        session: AsyncSession, change: ChangeRequest, gate_key: str,
        decision: str, user_id: int, *, remark: Optional[str] = None,
    ) -> ChangeGate:
        if gate_key not in GATE_KEYS:
            raise ChangeError(f"Unknown gate '{gate_key}'")
        if decision not in GATE_DECISIONS:
            raise ChangeError(f"Invalid gate decision '{decision}'")
        row = (await session.execute(
            select(ChangeGate).where(
                (ChangeGate.change_id == change.id) & (ChangeGate.gate_key == gate_key))
        )).scalar_one_or_none()
        if row is None:
            row = ChangeGate(change_id=change.id, gate_key=gate_key)
            session.add(row)
        row.decision = decision
        row.decided_by = user_id
        row.decided_at = datetime.utcnow()
        row.remark = remark
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "gate_decided", f"Gate {gate_key}: {decision}", user_id,
            field_name=f"gate_{gate_key}", new_value=decision, notes=remark,
        )
        return row
```

Extend `_guard` — add this block before the final `return None`:

```python
        # Gate wiring (additive): a gate constrains its target transition only when a
        # row exists. Changes with no gate rows behave exactly as before.
        for gate in change.gates:
            if GATE_TARGET_STATUS.get(gate.gate_key) == to_status and gate.decision != "yes":
                return f"Gate '{gate.gate_key}' is not approved ('{gate.decision}')"
```

Append to `backend/app/schemas/change.py`:

```python
class GateDecisionIn(BaseModel):
    decision: str  # yes | no | na
    remark: Optional[str] = None


class GateResponse(BaseModel):
    gate_key: str
    decision: str
    decided_by: Optional[int] = None
    decided_at: Optional[datetime] = None
    remark: Optional[str] = None

    class Config:
        from_attributes = True
```

In `backend/app/api/v1/changes/changes.py`, add `GateDecisionIn, GateResponse` to the schema import and add routes (among the `/{change_id}/...` routes):

```python
@router.get("/{change_id}/gates", response_model=List[GateResponse])
async def get_gates(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change.gates


@router.put("/{change_id}/gates/{gate_key}", response_model=GateResponse)
async def put_gate(
    change_id: int, gate_key: str, body: GateDecisionIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        gate = await ChangeService.decide_gate(
            db, change, gate_key, body.decision, current_user.id, remark=body.remark)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return gate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_change_gates.py -v`
Expected: PASS (both)

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/change_cost.py backend/app/models/change.py backend/app/services/change_service.py backend/app/schemas/change.py backend/app/api/v1/changes/changes.py backend/tests/test_change_gates.py
git commit -m "feat(change): D1 gates with additive state-machine wiring"
```

---

## Task 6: D1 master fields, affected plants, lead impacted item

**Files:**
- Modify: `backend/app/models/change.py`, `backend/app/services/change_service.py`, `backend/app/schemas/change.py`, `backend/app/api/v1/changes/changes.py`
- Test: `backend/tests/test_change_cost.py`

**Interfaces:**
- Produces on `ChangeRequest`: `issuer:str|None`, `is_series:bool`, `cm_internal:bool`, `cm_external:bool`, `implementation_mode:str|None`, `customer_relevant:bool`, `car_line:str|None`, and `affected_plants` (list[Plant] via `change_affected_plants`). On `ChangeImpactedItem`: `is_lead:bool`.
- `ChangeUpdate` gains the D1 fields; `update_change` allow-list includes them. `ImpactedItemCreate` gains `is_lead:bool=False`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_change_cost.py
async def test_d1_master_fields_patch(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "d1", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    patch = await client.patch(f"/api/v1/changes/{cid}", json={
        "issuer": "Customer X", "is_series": True, "cm_external": True,
        "implementation_mode": "integrated", "customer_relevant": True,
        "car_line": "VW426"}, headers=eng_auth)
    assert patch.status_code == 200, patch.text
    got = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    body = got.json()
    assert body["issuer"] == "Customer X"
    assert body["is_series"] is True
    assert body["car_line"] == "VW426"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_change_cost.py::test_d1_master_fields_patch -v`
Expected: FAIL (`issuer` not accepted / not returned).

- [ ] **Step 3: Write minimal implementation**

In `backend/app/models/change.py`, add the association table near the top (after the imports, before `class ChangeRequest`):

```python
from sqlalchemy import Table, Column, Boolean

change_affected_plants = Table(
    "change_affected_plants", Base.metadata,
    Column("change_id", ForeignKey("change_requests.id"), primary_key=True),
    Column("plant_id", ForeignKey("plants.id"), primary_key=True),
)
```

Add D1 columns to `ChangeRequest` (after `car_line` group; place after `data_classification`):

```python
    issuer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_series: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    cm_internal: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    cm_external: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    implementation_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_relevant: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    car_line: Mapped[str | None] = mapped_column(String(120), nullable=True)
```

> Import the boolean false helper at the top of `change.py`: `from sqlalchemy import false as sa_false`. (Existing migration 020 uses `sa.false()`; this is the ORM equivalent.)

Add the relationship to `ChangeRequest`:

```python
    affected_plants: Mapped[list["Plant"]] = relationship(
        secondary=change_affected_plants, lazy="selectin",
    )
```

Add `is_lead` to `ChangeImpactedItem` (after `eng_level_after`):

```python
    is_lead: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
```

Ensure `Plant` is importable for the relationship — extend the bottom import block of `change.py`:

```python
from app.models.entities import Project, User, Plant  # noqa: E402,F811
```

In `backend/app/services/change_service.py`, extend the `update_change` allow-list set to add:

```python
            "issuer", "is_series", "cm_internal", "cm_external",
            "implementation_mode", "customer_relevant", "car_line",
```

> Note the existing allow-list skips falsy values via `if k in allowed and v is not None`. Boolean `False` is not `None`, so it is applied correctly.

In `backend/app/schemas/change.py`, add to `ChangeUpdate`:

```python
    issuer: Optional[str] = None
    is_series: Optional[bool] = None
    cm_internal: Optional[bool] = None
    cm_external: Optional[bool] = None
    implementation_mode: Optional[str] = None
    customer_relevant: Optional[bool] = None
    car_line: Optional[str] = None
```

and to `ChangeResponse` (so the values round-trip in `GET`):

```python
    issuer: Optional[str] = None
    is_series: bool = False
    cm_internal: bool = False
    cm_external: bool = False
    implementation_mode: Optional[str] = None
    customer_relevant: bool = False
    car_line: Optional[str] = None
```

and add `is_lead: bool = False` to `ImpactedItemCreate`, `ImpactedItemResponse`. Then in `ChangeService.add_impacted_item` accept `is_lead: bool = False` and set it on the `ChangeImpactedItem(...)`, and pass `body.is_lead` from the `add_impacted_item` route.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_change_cost.py::test_d1_master_fields_patch -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/change.py backend/app/services/change_service.py backend/app/schemas/change.py backend/app/api/v1/changes/changes.py backend/tests/test_change_cost.py
git commit -m "feat(change): D1 master fields, affected plants, lead impacted item"
```

---

## Task 7: Reference endpoints (rates + activities) and seed data

**Files:**
- Modify: `backend/app/api/v1/changes/changes.py`, `backend/app/main.py`
- Test: `backend/tests/test_change_cost.py`

**Interfaces:**
- Produces:
  - `GET /api/v1/changes/reference/rates` → `list[{department_id, plant_id, hourly_rate, min_factor}]`
  - `GET /api/v1/changes/reference/activities?department_id=` → `list[{id, department_id, label, sort_order}]`
- `seed_test_data` ensures the Weissenburg/USA plants, department rates (Std.-Sätze), and per-department activities exist (idempotent).

> **Routing order matters:** register both `reference/*` routes **before** the `/{change_id}` routes (next to `routing-standards`), so `reference` is not parsed as an int `change_id`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_change_cost.py
async def test_reference_endpoints(client, eng_auth, seed, session_factory):
    from datetime import date
    from sqlalchemy import select
    from app.models.workflow import Department
    from app.models.change_cost import DepartmentRate, AssessmentActivity
    from app.models.entities import Plant
    async with session_factory() as s:
        plant = (await s.execute(select(Plant))).scalars().first()
        dep = Department(name="Sales", flow_type="action"); s.add(dep); await s.flush()
        s.add(DepartmentRate(department_id=dep.id, plant_id=plant.id, hourly_rate=50.0,
                             min_factor=0.6, effective_from=date(2026, 1, 1)))
        s.add(AssessmentActivity(department_id=dep.id, label="Angebot", sort_order=1, is_active=True))
        await s.commit()
        dep_id = dep.id
    rates = await client.get("/api/v1/changes/reference/rates", headers=eng_auth)
    assert any(r["hourly_rate"] == 50.0 for r in rates.json())
    acts = await client.get(f"/api/v1/changes/reference/activities?department_id={dep_id}",
                            headers=eng_auth)
    assert acts.json()[0]["label"] == "Angebot"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_change_cost.py::test_reference_endpoints -v`
Expected: FAIL (routes missing).

- [ ] **Step 3: Write minimal implementation**

In `backend/app/api/v1/changes/changes.py`, add (immediately after the `upsert_routing_standard` route, before `get_change`):

```python
@router.get("/reference/rates")
async def reference_rates(db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    from app.models.change_cost import DepartmentRate
    rows = (await db.execute(select(DepartmentRate))).scalars().all()
    return [{"department_id": r.department_id, "plant_id": r.plant_id,
             "hourly_rate": r.hourly_rate, "min_factor": r.min_factor} for r in rows]


@router.get("/reference/activities")
async def reference_activities(department_id: Optional[int] = Query(None),
                               db: AsyncSession = Depends(get_db),
                               current_user: User = Depends(get_current_user)):
    from app.models.change_cost import AssessmentActivity
    q = select(AssessmentActivity).where(AssessmentActivity.is_active == True)  # noqa: E712
    if department_id is not None:
        q = q.where(AssessmentActivity.department_id == department_id)
    q = q.order_by(AssessmentActivity.sort_order)
    rows = (await db.execute(q)).scalars().all()
    return [{"id": r.id, "department_id": r.department_id, "label": r.label,
             "sort_order": r.sort_order} for r in rows]
```

In `backend/app/main.py` `seed_test_data`, add an idempotent seed block (rates from `Std.-Sätze`; create Weissenburg + USA plants under the first org if missing). Use `get-or-create` guarded by existence checks so re-runs are safe. Reference rate values (Weissenburg / USA): Sales 50/—; R&D 65/21.5; Tool design 65/21.5; IE 65/21.5; Quality 45/21.5; Logistics 50/21.5; Production 55/21.5; Purchasing 50/21.5; Production control 50/21.5; min_factor DEU 0.6 / USA 0.36.

```python
    # --- Change-management cost reference data (idempotent) ---
    from app.models.change_cost import DepartmentRate, AssessmentActivity
    from app.models.entities import Plant, Organization
    from app.models.workflow import Department
    org = (await session.execute(select(Organization))).scalars().first()
    if org is not None:
        plants = {p.name: p for p in (await session.execute(
            select(Plant).where(Plant.organization_id == org.id))).scalars().all()}
        for name, code, loc, factor in [("Weissenburg", "WUG", "DE", 0.6), ("USA", "USA", "US", 0.36)]:
            if name not in plants:
                p = Plant(organization_id=org.id, name=name, code=code, location=loc)
                session.add(p); await session.flush(); plants[name] = p
        rate_table = {
            "Sales": (50.0, None), "R&D": (65.0, 21.5), "Tool design": (65.0, 21.5),
            "IE": (65.0, 21.5), "Quality": (45.0, 21.5), "Logistics": (50.0, 21.5),
            "Production": (55.0, 21.5), "Purchasing": (50.0, 21.5),
            "Production control": (50.0, 21.5),
        }
        existing_rates = {(r.department_id, r.plant_id) for r in (await session.execute(
            select(DepartmentRate))).scalars().all()}
        for dep_name, (wug, usa) in rate_table.items():
            dep = (await session.execute(
                select(Department).where(Department.name == dep_name))).scalar_one_or_none()
            if dep is None:
                continue
            for plant_name, rate, factor in [("Weissenburg", wug, 0.6), ("USA", usa, 0.36)]:
                if rate is None:
                    continue
                pid = plants[plant_name].id
                if (dep.id, pid) not in existing_rates:
                    session.add(DepartmentRate(department_id=dep.id, plant_id=pid,
                                               hourly_rate=rate, min_factor=factor))
    await session.commit()
```

> The activity-catalog seed (per-department selection lists from the workbook tabs) follows the same get-or-create pattern; transcribe the labels per department from the `D2`–`D10` tabs. Keep it idempotent (skip if any `AssessmentActivity` exists for that department).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_change_cost.py::test_reference_endpoints -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/changes/changes.py backend/app/main.py backend/tests/test_change_cost.py
git commit -m "feat(change): rate/activity reference endpoints + seed"
```

---

## Task 8: Alembic migration `021`

**Files:**
- Create: `backend/alembic/versions/021_add_cm_cost_lines.py`
- Test: `backend/tests/test_change_cost.py`

**Interfaces:**
- Consumes: all models from Tasks 1–6.
- Produces: idempotent `upgrade()`/`downgrade()` for `department_rate`, `assessment_activity`, `assessment_cost_line`, `change_gate`, `change_affected_plants`, the new `change_assessments` columns, the new `change_requests` columns, and `change_impacted_items.is_lead`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_change_cost.py
def test_migration_021_is_head_with_expected_tables():
    import re, pathlib
    p = pathlib.Path("alembic/versions/021_add_cm_cost_lines.py")
    assert p.exists(), "migration 021 missing"
    src = p.read_text()
    assert re.search(r"down_revision\s*=\s*'020'", src)
    for t in ("department_rate", "assessment_activity", "assessment_cost_line",
              "change_gate", "change_affected_plants"):
        assert t in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_change_cost.py::test_migration_021_is_head_with_expected_tables -v`
Expected: FAIL with "migration 021 missing".

- [ ] **Step 3: Write minimal implementation**

```python
# backend/alembic/versions/021_add_cm_cost_lines.py
"""CM cost digitization: department_rate, assessment_activity, assessment_cost_line,
change_gate, change_affected_plants; D1 columns on change_requests; cost columns on
change_assessments; is_lead on change_impacted_items.

Revision ID: 021
Revises: 020
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = '021'
down_revision = '020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    insp = inspect(op.get_bind())
    existing = set(insp.get_table_names())

    if 'department_rate' not in existing:
        op.create_table(
            'department_rate',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('department_id', sa.Integer(), sa.ForeignKey('wf_departments.id'), nullable=False, index=True),
            sa.Column('plant_id', sa.Integer(), sa.ForeignKey('plants.id'), nullable=False, index=True),
            sa.Column('hourly_rate', sa.Float(), nullable=False),
            sa.Column('min_factor', sa.Float(), nullable=False, server_default='1.0'),
            sa.Column('effective_from', sa.Date(), nullable=True),
        )
    if 'assessment_activity' not in existing:
        op.create_table(
            'assessment_activity',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('department_id', sa.Integer(), sa.ForeignKey('wf_departments.id'), nullable=False, index=True),
            sa.Column('label', sa.String(200), nullable=False),
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if 'assessment_cost_line' not in existing:
        op.create_table(
            'assessment_cost_line',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('assessment_id', sa.Integer(), sa.ForeignKey('change_assessments.id'), nullable=False, index=True),
            sa.Column('plant_id', sa.Integer(), sa.ForeignKey('plants.id'), nullable=False, index=True),
            sa.Column('activity_id', sa.Integer(), sa.ForeignKey('assessment_activity.id'), nullable=True),
            sa.Column('activity_label', sa.String(200), nullable=True),
            sa.Column('cost_kind', sa.String(20), nullable=False, server_default='one_time'),
            sa.Column('demand_hours', sa.Float(), nullable=False, server_default='0'),
            sa.Column('rate_snapshot', sa.Float(), nullable=False, server_default='0'),
            sa.Column('internal_cost', sa.Float(), nullable=False, server_default='0'),
            sa.Column('external_cost', sa.Float(), nullable=False, server_default='0'),
            sa.Column('note', sa.Text(), nullable=True),
        )
    if 'change_gate' not in existing:
        op.create_table(
            'change_gate',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), nullable=False, index=True),
            sa.Column('gate_key', sa.String(20), nullable=False),
            sa.Column('decision', sa.String(10), nullable=False, server_default='na'),
            sa.Column('decided_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('decided_at', sa.DateTime(), nullable=True),
            sa.Column('remark', sa.Text(), nullable=True),
        )
    if 'change_affected_plants' not in existing:
        op.create_table(
            'change_affected_plants',
            sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), primary_key=True),
            sa.Column('plant_id', sa.Integer(), sa.ForeignKey('plants.id'), primary_key=True),
        )

    a_cols = {c['name'] for c in insp.get_columns('change_assessments')}
    for name, col in [
        ('producibility', sa.Column('producibility', sa.String(10), nullable=False, server_default='na')),
        ('contact_person', sa.Column('contact_person', sa.String(120), nullable=True)),
        ('approval_comment', sa.Column('approval_comment', sa.Text(), nullable=True)),
        ('lifecycle_cost', sa.Column('lifecycle_cost', sa.Float(), nullable=True)),
    ]:
        if name not in a_cols:
            op.add_column('change_assessments', col)

    r_cols = {c['name'] for c in insp.get_columns('change_requests')}
    for name, col in [
        ('issuer', sa.Column('issuer', sa.String(120), nullable=True)),
        ('is_series', sa.Column('is_series', sa.Boolean(), nullable=False, server_default=sa.false())),
        ('cm_internal', sa.Column('cm_internal', sa.Boolean(), nullable=False, server_default=sa.false())),
        ('cm_external', sa.Column('cm_external', sa.Boolean(), nullable=False, server_default=sa.false())),
        ('implementation_mode', sa.Column('implementation_mode', sa.String(20), nullable=True)),
        ('customer_relevant', sa.Column('customer_relevant', sa.Boolean(), nullable=False, server_default=sa.false())),
        ('car_line', sa.Column('car_line', sa.String(120), nullable=True)),
    ]:
        if name not in r_cols:
            op.add_column('change_requests', col)

    i_cols = {c['name'] for c in insp.get_columns('change_impacted_items')}
    if 'is_lead' not in i_cols:
        op.add_column('change_impacted_items',
                      sa.Column('is_lead', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    from sqlalchemy import inspect
    insp = inspect(op.get_bind())
    existing = set(insp.get_table_names())
    for t in ('change_affected_plants', 'assessment_cost_line', 'change_gate',
              'assessment_activity', 'department_rate'):
        if t in existing:
            op.drop_table(t)
    i_cols = {c['name'] for c in insp.get_columns('change_impacted_items')}
    if 'is_lead' in i_cols:
        op.drop_column('change_impacted_items', 'is_lead')
    r_cols = {c['name'] for c in insp.get_columns('change_requests')}
    for name in ('car_line', 'customer_relevant', 'implementation_mode',
                 'cm_external', 'cm_internal', 'is_series', 'issuer'):
        if name in r_cols:
            op.drop_column('change_requests', name)
    a_cols = {c['name'] for c in insp.get_columns('change_assessments')}
    for name in ('lifecycle_cost', 'approval_comment', 'contact_person', 'producibility'):
        if name in a_cols:
            op.drop_column('change_assessments', name)
```

- [ ] **Step 4: Run test + full backend suite**

Run: `cd backend && python3 -m pytest tests/test_change_cost.py tests/test_change_gates.py tests/test_change_routing.py tests/test_changes.py -v`
Expected: PASS (all — including the unchanged routing/lifecycle tests, proving backward compatibility).

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/021_add_cm_cost_lines.py backend/tests/test_change_cost.py
git commit -m "feat(change): migration 021 for CM cost digitization"
```

---

## Task 9: Frontend types + API client + label map

**Files:**
- Modify: `frontend/src/types/change.ts`, `frontend/src/api/changes.ts`
- Create: `frontend/src/i18n/cmLabels.ts`

**Interfaces:**
- Produces TS types `CostLine`, `CostLineIn`, `Summation`, `Gate`, `DepartmentRateRef`, `ActivityRef`; `changesApi` methods `getCostLines`, `putCostLines`, `getSummation`, `getGates`, `putGate`, `referenceRates`, `referenceActivities`.

- [ ] **Step 1: Add types** to `frontend/src/types/change.ts`

```ts
export type CostKind = 'one_time' | 'lifecycle';

export interface CostLine {
  id: number;
  plant_id: number;
  activity_id?: number | null;
  activity_label?: string | null;
  cost_kind: CostKind;
  demand_hours: number;
  rate_snapshot: number;
  internal_cost: number;
  external_cost: number;
  note?: string | null;
}

export interface CostLineIn {
  plant_id: number;
  cost_kind: CostKind;
  demand_hours: number;
  external_cost: number;
  activity_id?: number | null;
  activity_label?: string | null;
  note?: string | null;
}

export interface PlantRollup {
  plant_id: number;
  one_time_internal: number; one_time_external: number;
  lifecycle_internal: number; lifecycle_external: number;
}
export interface DeptRollup extends Omit<PlantRollup, 'plant_id'> { department_id: number; }
export interface Summation {
  by_plant: PlantRollup[];
  by_department: DeptRollup[];
  totals: { one_time_internal: number; one_time_external: number;
            lifecycle_internal: number; lifecycle_external: number; grand_total: number };
}

export type GateKey = 'feasibility' | 'budget' | 'release';
export interface Gate {
  gate_key: GateKey;
  decision: 'yes' | 'no' | 'na';
  decided_by?: number | null;
  decided_at?: string | null;
  remark?: string | null;
}

export interface DepartmentRateRef { department_id: number; plant_id: number; hourly_rate: number; min_factor: number; }
export interface ActivityRef { id: number; department_id: number; label: string; sort_order: number; }
```

- [ ] **Step 2: Add API wrappers** to `frontend/src/api/changes.ts` (import the new types, add inside `changesApi`)

```ts
  getCostLines: (id: number, aid: number) =>
    client.get<CostLine[]>(`/v1/changes/${id}/assessments/${aid}/cost-lines`).then((r) => r.data),
  putCostLines: (id: number, aid: number, lines: CostLineIn[]) =>
    client.put<CostLine[]>(`/v1/changes/${id}/assessments/${aid}/cost-lines`, { lines }).then((r) => r.data),
  getSummation: (id: number) =>
    client.get<Summation>(`/v1/changes/${id}/summation`).then((r) => r.data),
  getGates: (id: number) =>
    client.get<Gate[]>(`/v1/changes/${id}/gates`).then((r) => r.data),
  putGate: (id: number, gateKey: string, body: { decision: string; remark?: string }) =>
    client.put<Gate>(`/v1/changes/${id}/gates/${gateKey}`, body).then((r) => r.data),
  referenceRates: () =>
    client.get<DepartmentRateRef[]>('/v1/changes/reference/rates').then((r) => r.data),
  referenceActivities: (departmentId: number) =>
    client.get<ActivityRef[]>('/v1/changes/reference/activities', { params: { department_id: departmentId } }).then((r) => r.data),
```

- [ ] **Step 3: Create the label map** `frontend/src/i18n/cmLabels.ts`

```ts
// Label keys for the Änderungsmitteilung UI. DE/EN now; sub-project C swaps the
// runtime locale. Components import t(key) instead of hard-coding strings.
export type Lang = 'de' | 'en';
export const cmLabels: Record<string, Record<Lang, string>> = {
  one_time: { de: 'Einmal-Aufwand', en: 'One-time cost' },
  lifecycle: { de: 'Lifecycle', en: 'Lifecycle' },
  internal: { de: 'interner Aufwand', en: 'Internal cost' },
  external: { de: 'externer Aufwand', en: 'External cost' },
  hours: { de: 'Stunden', en: 'Hours' },
  activity: { de: 'Tätigkeit', en: 'Activity' },
  total: { de: 'Summe', en: 'Total' },
  producibility: { de: 'Herstellbarkeit', en: 'Producibility' },
  feasibility: { de: 'Realisierbar?', en: 'Feasible?' },
  budget: { de: 'Budget geprüft?', en: 'Budget checked?' },
  release: { de: 'Techn. Freigabe?', en: 'Technical release?' },
};
export const t = (key: string, lang: Lang = 'en'): string => cmLabels[key]?.[lang] ?? key;
```

- [ ] **Step 4: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/change.ts frontend/src/api/changes.ts frontend/src/i18n/cmLabels.ts
git commit -m "feat(change): frontend types, API client, CM label map"
```

---

## Task 10: Cost-line grid component (+ vitest)

**Files:**
- Create: `frontend/src/components/changes/CostLineGrid.tsx`, `frontend/src/components/changes/CostLineGrid.test.tsx`

**Interfaces:**
- Consumes: `changesApi.getCostLines/putCostLines/referenceRates/referenceActivities` (Task 9).
- Produces: `CostLineGrid({ changeId, assessmentId, departmentId, plants })` where `plants: {id:number; name:string}[]`. Renders editable rows; internal cost = `demand_hours × rate(department,plant)` shown live; "Save" calls `putCostLines`.

- [ ] **Step 1: Write the failing test** (pure calc helper, no network)

```tsx
// frontend/src/components/changes/CostLineGrid.test.tsx
import { describe, it, expect } from 'vitest';
import { internalCost } from './CostLineGrid';

describe('internalCost', () => {
  it('multiplies hours by the matching rate', () => {
    const rates = [{ department_id: 1, plant_id: 10, hourly_rate: 65, min_factor: 0.6 }];
    expect(internalCost(rates, 1, 10, 5)).toBe(325);
  });
  it('returns 0 when no rate matches', () => {
    expect(internalCost([], 1, 10, 5)).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/changes/CostLineGrid.test.tsx`
Expected: FAIL (module/export missing).

- [ ] **Step 3: Write minimal implementation** `frontend/src/components/changes/CostLineGrid.tsx`

```tsx
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import type { CostLine, CostLineIn, DepartmentRateRef } from '../../types/change';
import { t } from '../../i18n/cmLabels';

export function internalCost(rates: DepartmentRateRef[], departmentId: number,
                             plantId: number, hours: number): number {
  const r = rates.find((x) => x.department_id === departmentId && x.plant_id === plantId);
  return r ? hours * r.hourly_rate : 0;
}

type Row = CostLineIn & { _internal: number };

export default function CostLineGrid({ changeId, assessmentId, departmentId, plants }:
  { changeId: number; assessmentId: number; departmentId: number; plants: { id: number; name: string }[] }) {
  const qc = useQueryClient();
  const { data: rates = [] } = useQuery({ queryKey: ['cm-rates'], queryFn: changesApi.referenceRates });
  const { data: activities = [] } = useQuery({
    queryKey: ['cm-activities', departmentId], queryFn: () => changesApi.referenceActivities(departmentId) });
  const { data: existing = [] } = useQuery({
    queryKey: ['cost-lines', changeId, assessmentId],
    queryFn: () => changesApi.getCostLines(changeId, assessmentId) });

  const [rows, setRows] = useState<Row[]>([]);
  const seeded = rows.length === 0 && existing.length > 0;
  if (seeded) {
    setRows(existing.map((l: CostLine) => ({
      plant_id: l.plant_id, cost_kind: l.cost_kind, demand_hours: l.demand_hours,
      external_cost: l.external_cost, activity_id: l.activity_id, activity_label: l.activity_label,
      note: l.note, _internal: l.internal_cost })));
  }

  const save = useMutation({
    mutationFn: () => changesApi.putCostLines(changeId, assessmentId,
      rows.map(({ _internal, ...l }) => l as CostLineIn)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cost-lines', changeId, assessmentId] });
      qc.invalidateQueries({ queryKey: ['change-summation', changeId] });
    },
  });

  const addRow = () => setRows((r) => [...r, {
    plant_id: plants[0]?.id ?? 0, cost_kind: 'one_time', demand_hours: 0,
    external_cost: 0, activity_label: '', _internal: 0 }]);

  const update = (i: number, patch: Partial<Row>) => setRows((r) => r.map((row, j) => {
    if (j !== i) return row;
    const merged = { ...row, ...patch };
    merged._internal = internalCost(rates, departmentId, merged.plant_id, merged.demand_hours);
    return merged;
  }));

  const total = rows.reduce((s, r) => s + r._internal + (r.external_cost || 0), 0);

  return (
    <div className="rounded border border-slate-700 bg-slate-800/40 p-3 space-y-2">
      <table className="w-full text-sm text-slate-200">
        <thead className="text-xs text-slate-400">
          <tr>
            <th className="text-left">{t('activity')}</th><th>Plant</th><th>{t('hours')}</th>
            <th>{t('internal')}</th><th>{t('external')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              <td>
                <input list={`acts-${i}`} className="bg-slate-900 border border-slate-600 rounded px-1 w-full"
                  value={row.activity_label ?? ''} onChange={(e) => update(i, { activity_label: e.target.value })} />
                <datalist id={`acts-${i}`}>{activities.map((a) => <option key={a.id} value={a.label} />)}</datalist>
              </td>
              <td>
                <select className="bg-slate-900 border border-slate-600 rounded"
                  value={row.plant_id} onChange={(e) => update(i, { plant_id: Number(e.target.value) })}>
                  {plants.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </td>
              <td><input type="number" className="bg-slate-900 border border-slate-600 rounded w-16 text-right"
                value={row.demand_hours} onChange={(e) => update(i, { demand_hours: Number(e.target.value) })} /></td>
              <td className="text-right text-slate-400">{row._internal.toFixed(2)}</td>
              <td><input type="number" className="bg-slate-900 border border-slate-600 rounded w-20 text-right"
                value={row.external_cost} onChange={(e) => update(i, { external_cost: Number(e.target.value) })} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex items-center justify-between">
        <button onClick={addRow} className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 text-slate-100">+ row</button>
        <span className="text-sm text-slate-300">{t('total')}: {total.toFixed(2)}</span>
        <button onClick={() => save.mutate()} disabled={save.isPending}
          className="px-2.5 py-1 text-xs rounded bg-sky-600 hover:bg-sky-500 text-white">Save</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/changes/CostLineGrid.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/changes/CostLineGrid.tsx frontend/src/components/changes/CostLineGrid.test.tsx
git commit -m "feat(change): department cost-line grid component"
```

---

## Task 11: D1 master panel + Summierung view

**Files:**
- Create: `frontend/src/components/changes/D1MasterPanel.tsx`, `frontend/src/components/changes/SummationView.tsx`

**Interfaces:**
- Consumes: `changesApi.getGates/putGate/getSummation` and `update` (Task 9).
- Produces: `D1MasterPanel({ changeId })` rendering the 3 gates with decide buttons; `SummationView({ changeId })` rendering the read-only roll-up.

- [ ] **Step 1: Write `SummationView.tsx`**

```tsx
import { useQuery } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import { t } from '../../i18n/cmLabels';

export default function SummationView({ changeId }: { changeId: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ['change-summation', changeId], queryFn: () => changesApi.getSummation(changeId) });
  if (isLoading) return <div className="text-slate-400 text-sm p-4">Loading…</div>;
  if (!data) return null;
  const tot = data.totals;
  return (
    <div className="rounded border border-slate-700 bg-slate-800/40 p-3 text-sm text-slate-200">
      <div className="font-semibold text-slate-100 mb-2">Summierung</div>
      <table className="w-full">
        <tbody>
          <tr><td>{t('one_time')} ({t('internal')})</td><td className="text-right">{tot.one_time_internal.toFixed(2)}</td></tr>
          <tr><td>{t('one_time')} ({t('external')})</td><td className="text-right">{tot.one_time_external.toFixed(2)}</td></tr>
          <tr><td>{t('lifecycle')} ({t('internal')})</td><td className="text-right">{tot.lifecycle_internal.toFixed(2)}</td></tr>
          <tr><td>{t('lifecycle')} ({t('external')})</td><td className="text-right">{tot.lifecycle_external.toFixed(2)}</td></tr>
          <tr className="border-t border-slate-600 font-semibold"><td>{t('total')}</td><td className="text-right">{tot.grand_total.toFixed(2)}</td></tr>
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Write `D1MasterPanel.tsx`**

```tsx
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import type { Gate, GateKey } from '../../types/change';
import { t } from '../../i18n/cmLabels';

const GATES: GateKey[] = ['feasibility', 'budget', 'release'];

export default function D1MasterPanel({ changeId }: { changeId: number }) {
  const qc = useQueryClient();
  const { data: gates = [] } = useQuery({
    queryKey: ['change-gates', changeId], queryFn: () => changesApi.getGates(changeId) });
  const decide = useMutation({
    mutationFn: ({ key, decision }: { key: GateKey; decision: string }) =>
      changesApi.putGate(changeId, key, { decision }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change-gates', changeId] }),
  });
  const byKey: Record<string, Gate> = Object.fromEntries(gates.map((g) => [g.gate_key, g]));

  return (
    <div className="rounded border border-slate-700 bg-slate-800/40 p-3 space-y-2">
      <div className="font-semibold text-slate-100">Final assessment</div>
      {GATES.map((key) => {
        const g = byKey[key];
        return (
          <div key={key} className="flex items-center justify-between text-sm">
            <span className="text-slate-200">{t(key)}</span>
            <span className="flex gap-1">
              {(['yes', 'no', 'na'] as const).map((d) => (
                <button key={d} onClick={() => decide.mutate({ key, decision: d })}
                  className={`px-2 py-0.5 rounded text-xs border ${g?.decision === d
                    ? 'bg-sky-600 text-white border-sky-500'
                    : 'bg-slate-900 text-slate-300 border-slate-600'}`}>{d}</button>
              ))}
            </span>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Wire into the change detail UI**

Import and render `D1MasterPanel`, `SummationView`, and (per assessment) `CostLineGrid` in the existing change detail location alongside `AssessmentRouting` (e.g. the change tab in `frontend/src/pages/ProjectDetailPage.tsx`). Follow the existing tab/section layout; pass `changeId`, and for the grid the `assessmentId`/`departmentId` from the routing/assessments data and the project's plants.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/changes/D1MasterPanel.tsx frontend/src/components/changes/SummationView.tsx frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(change): D1 master panel + Summierung view wired into change UI"
```

---

## Self-Review

**Spec coverage:**
- New tables `assessment_cost_line` / `department_rate` / `assessment_activity` / `change_gate` → Tasks 1, 2, 5, 8. ✓
- Extended `change_assessments` (producibility, contact_person, approval_comment, computed cost_impact + lifecycle_cost) → Task 2. ✓
- Extended `change_requests` D1 fields + `affected_plants` M2M + `is_lead` → Task 6. ✓
- Cost computation (`hours × rate`, rate_snapshot) → Task 2. ✓
- Summierung computed roll-up + endpoint → Tasks 3, 4. ✓
- Cost-line API (GET + PUT whole-collection replace) + changelog → Task 4 (changelog appended in Task 2's `replace_cost_lines`). ✓
- Gates + state-machine wiring → Task 5. ✓
- Reference endpoints + seed → Task 7. ✓
- Frontend forms (cost grid, D1 panel, Summierung), localization-ready labels → Tasks 9–11. ✓
- Error handling: missing rate (Task 2 raises `CostError`), free-input requires label (Task 2), single-plant toggle (grid plant dropdown, Task 10). ✓
- Out of scope respected: no Excel import/export, no localization runtime/Spanish, no email/translation. ✓

**Placeholder scan:** No "TBD"/"implement later". Two intentional, explicitly-bounded transcription steps remain (lifecycle per-department formula; activity-catalog labels) — these are data transcribed from the workbook, not code placeholders, and the one-time cost path they sit beside is fully specified.

**Type consistency:** `replace_cost_lines`, `summation`, `rate_for`, `recompute_assessment_totals`, `decide_gate` signatures match between definition and call sites; endpoint paths match the frontend client; schema field names (`cost_impact`, `lifecycle_cost`, `grand_total`, `gate_key`) consistent across model/schema/TS.
