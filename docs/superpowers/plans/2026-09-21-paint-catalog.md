# Paint Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Paint master data in PLM, an ordered paint setup per article, and a paint overview on the project page.

**Architecture:** Three new tables in one migration; a `PaintService` for catalog CRUD and the per-part setup with changelog; two routers (`/paints`, part paint under `/parts`); a Paints page, a Paint card on the part page, a Painted chip and a Paint section on the project page.

**Tech Stack:** FastAPI + SQLAlchemy async + alembic (backend, `cd backend && uv run --no-sync pytest ...`), React + TypeScript + vitest + testing-library (frontend, `cd frontend && npx vitest run ...`).

**Spec:** `docs/superpowers/specs/2026-09-21-paint-catalog-design.md`

## Global Constraints

- Paints are org-scoped: every query filters `organization_id == current_user.organization_id`; unique `(organization_id, name)` → 409 on duplicate.
- `PUT /parts/{id}/paint` replaces the whole setup; layers get `layer_order` 1..n from list order; one changelog line `paint_updated` per put.
- No delete on paints, `is_active=false` instead; inactive paints stay on existing layers.
- Paint types: `primer | basecoat | clearcoat | one_coat | other`.
- Migration is `073`, `down_revision = "072"`, follows the `op.create_table` style of 071.
- Backend tests always `uv run --no-sync pytest` (never sync; untracked `uv.lock`).
- Commit after each task; trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

### Task 1: Models and migration

**Files:**
- Create: `backend/app/models/paint.py`
- Modify: `backend/app/models/__init__.py` (export `Paint`, `PartPaint`, `PartPaintLayer`)
- Create: `backend/alembic/versions/073_paint_catalog.py`
- Test: `backend/tests/test_paint_models.py`

**Interfaces:**
- Produces: `Paint(organization_id, name, paint_type, colour_code, colour_name, colour_hex, supplier_id, supplier_text, spec_reference, notes, is_active, created_by, created_at, updated_at)`, `PartPaint(part_id unique, paint_required, process, notes, updated_by, updated_at)` with relationship `layers` (ordered by `layer_order`, cascade delete-orphan), `PartPaintLayer(part_paint_id, paint_id, layer_order, area, notes)` with relationship `paint`. `PAINT_TYPES = ("primer","basecoat","clearcoat","one_coat","other")` exported from `app.models.paint`.

- [ ] **Step 1: Failing test**

```python
"""Paint tables exist and cascade."""
from sqlalchemy import select
from app.models.paint import PAINT_TYPES, Paint, PartPaint, PartPaintLayer
from app.models.part import Part
from app.services.part_service import PartService


async def test_paint_setup_round_trip_and_cascade(session_factory, seed):
    async with session_factory() as s:
        p = await PartService.create_part(s, project_id=seed["project_id"], part_number="PT-1", name="Cover",
                                          part_type="internal_mfg", created_by=seed["admin_id"])
        base = Paint(organization_id=seed["org_id"], name="RAL 9005 base", paint_type="basecoat",
                     colour_code="RAL 9005", created_by=seed["admin_id"])
        s.add(base); await s.flush()
        setup = PartPaint(part_id=p.id, paint_required=True, process="spray", updated_by=seed["admin_id"])
        setup.layers.append(PartPaintLayer(paint_id=base.id, layer_order=1, area="A-side"))
        s.add(setup); await s.commit()
        pid, sid = p.id, setup.id
    async with session_factory() as s:
        got = (await s.execute(select(PartPaint).where(PartPaint.part_id == pid))).scalar_one()
        assert got.paint_required and got.layers[0].paint.colour_code == "RAL 9005"
        await s.delete(got); await s.commit()
    async with session_factory() as s:
        assert (await s.execute(select(PartPaintLayer).where(PartPaintLayer.part_paint_id == sid))).first() is None
    assert "basecoat" in PAINT_TYPES
```

Check `seed` in `tests/conftest.py` for the org id key (`org_id` or similar) and use the real key.

- [ ] **Step 2: Run** `cd backend && uv run --no-sync pytest tests/test_paint_models.py -q` → FAIL ModuleNotFoundError.

- [ ] **Step 3: Implement models**

`backend/app/models/paint.py`:

```python
"""Paint master data and the per-article paint setup.

A paint is org-scoped master data (like catalog_parts). An article's paint
setup hangs off the part, not the revision, and lists paints in layer order.
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.database import Base  # match the import the other models use

PAINT_TYPES = ("primer", "basecoat", "clearcoat", "one_coat", "other")


class Paint(Base):
    __tablename__ = "paints"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    paint_type: Mapped[str] = mapped_column(String(20), default="basecoat")
    colour_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    colour_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    colour_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    supplier_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    spec_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_paint_org_name"),)


class PartPaint(Base):
    __tablename__ = "part_paints"
    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"), unique=True)
    paint_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    process: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    layers: Mapped[list["PartPaintLayer"]] = relationship(
        back_populates="setup", cascade="all, delete-orphan", order_by="PartPaintLayer.layer_order", lazy="selectin")


class PartPaintLayer(Base):
    __tablename__ = "part_paint_layers"
    id: Mapped[int] = mapped_column(primary_key=True)
    part_paint_id: Mapped[int] = mapped_column(ForeignKey("part_paints.id", ondelete="CASCADE"), index=True)
    paint_id: Mapped[int] = mapped_column(ForeignKey("paints.id"), index=True)
    layer_order: Mapped[int] = mapped_column(Integer)
    area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    setup: Mapped[PartPaint] = relationship(back_populates="layers")
    paint: Mapped[Paint] = relationship(lazy="selectin")
    __table_args__ = (UniqueConstraint("part_paint_id", "layer_order", name="uq_part_paint_layer_order"),)
```

Find the `Base` import the other model files use (`grep -n "^from.*Base" backend/app/models/part.py`) and use the same. Export the three classes from `backend/app/models/__init__.py` next to `CatalogPart`.

- [ ] **Step 4: Migration** `backend/alembic/versions/073_paint_catalog.py`: `revision = "073"`, `down_revision = "072"`, `upgrade` creates the three tables with `op.create_table` matching the columns above (constraints included), `downgrade` drops them in reverse order. Mirror the style of `071_offer_is_partial.py`.

- [ ] **Step 5: Run** the test → PASS. Then `cd backend && uv run --no-sync alembic upgrade head` against the local dev DB is NOT needed here (the docker backend applies migrations on restart); do not run alembic.

- [ ] **Step 6: Commit** `feat(paint): paint catalog and part paint tables`.

---

### Task 2: PaintService

**Files:**
- Create: `backend/app/services/paint_service.py`
- Test: `backend/tests/test_paint_service.py`

**Interfaces:**
- Produces:

```python
class PaintService:
    @staticmethod
    async def list_paints(session, org_id, active_only=True, q=None) -> list[Paint]
    @staticmethod
    async def create_paint(session, org_id, created_by, **fields) -> Paint   # raises DuplicatePaint(ValueError) on same name in org
    @staticmethod
    async def update_paint(session, org_id, paint_id, **fields) -> Paint     # ValueError if not in org; DuplicatePaint on rename clash
    @staticmethod
    async def used_in(session, org_id, paint_id) -> list[dict]  # {part_id, part_number, name, project_id, project_code, layer_order}
    @staticmethod
    async def get_setup(session, part_id) -> dict   # {"paint_required": False, "process": None, "notes": None, "layers": []} when none
    @staticmethod
    async def put_setup(session, part_id, org_id, paint_required, process, notes, layers: list[dict], updated_by) -> dict
        # layers: [{paint_id, area, notes}] in order; validates every paint_id belongs to org (ValueError); renumbers 1..n; replaces existing layers; logs changelog "paint_updated"
    @staticmethod
    async def project_overview(session, project_id) -> list[dict]  # parts with paint_required, each {part_id, part_number, name, process, layers:[{layer_order, area, paint:{id,name,paint_type,colour_code,colour_name,colour_hex,is_active}}]}
```
  `get_setup`/`put_setup` return the same dict shape (`layers[].paint` embedded).

- [ ] **Step 1: Failing tests** covering: create + duplicate name → `DuplicatePaint`; list with `q` matches name or colour_code, `active_only` hides inactive; update rename clash; put_setup round trip with two layers reordered on second put (renumbering), changelog row with action `paint_updated`; put with a paint from another org → ValueError; deactivated paint stays in setup with `is_active False`; project_overview lists only required parts; used_in returns the part with project code. Use `PartService.create_part` and `seed` from conftest; find the org id key and a second org if the seed has one (else create `Organization` directly; check `backend/app/models` for its class).

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** the service (`select(...).where(Paint.organization_id == org_id)`, `ilike` for `q`, `ChangelogService.log_action(session, part_id=..., action="paint_updated", action_description=..., performed_by=updated_by)` from `app.services.part_service`; description like `"Paint required · spray · RAL 9005 base (basecoat) → 2K clear (clearcoat)"` or `"Paint not required"`). **Step 4: Run** → PASS. **Step 5: Commit** `feat(paint): PaintService`.

---

### Task 3: API routers and schemas

**Files:**
- Create: `backend/app/schemas/paint.py`, `backend/app/api/v1/paints.py`, `backend/app/api/v1/items/part_paint.py`
- Modify: `backend/app/api/v1/__init__.py` (register both routers the way `catalog_parts_router` and `revision_files_router` are)
- Test: `backend/tests/test_paint_api.py`

**Interfaces (produces):**
- `GET /api/v1/paints?active_only=&q=` → `list[PaintOut]`; `POST /api/v1/paints` (`PaintIn`: name required, paint_type Literal of PAINT_TYPES default basecoat, colour_code, colour_name, colour_hex (regex `^#[0-9a-fA-F]{6}$` optional), supplier_id, supplier_text, spec_reference, notes, is_active) → 201 `PaintOut`, 409 on duplicate; `GET /api/v1/paints/{id}`; `PUT /api/v1/paints/{id}` (all optional) ; `GET /api/v1/paints/{id}/used-in` → list of `UsedInOut`.
- `GET /api/v1/parts/{part_id}/paint` → `PartPaintOut {paint_required, process, notes, layers:[{layer_order, area, notes, paint: PaintOut}]}`; `PUT /api/v1/parts/{part_id}/paint` (`PartPaintIn {paint_required, process, notes, layers:[{paint_id, area, notes}]}`) → `PartPaintOut`, 400 on foreign paint, 404 unknown part.
- `GET /api/v1/parts/project/{project_id}/paint-overview` → `list[PaintOverviewPartOut]`.
- Auth: `Depends(get_current_user)` on every route; org from `current_user.organization_id`.

- [ ] Tests: create/list/duplicate 409/update/used-in over HTTP with `client` + `eng_auth` fixtures (see `tests/test_customer_data_index.py` for the pattern); part paint put/get round trip; overview after put; 400 for a foreign paint id (create a paint directly in the DB under another org).
- [ ] Implement, run `tests/test_paint_api.py tests/test_paint_service.py`, commit `feat(api): paints and part paint endpoints`.

---

### Task 4: Paints page

**Files:**
- Create: `frontend/src/pages/PaintsPage.tsx`, `frontend/src/pages/PaintsPage.test.tsx`, `frontend/src/types/paint.ts`, `frontend/src/api/paints.ts`
- Modify: `frontend/src/App.tsx` (route `/paints`), `frontend/src/components/layout/Sidebar.tsx` (entry `{ path: '/paints', label: 'Paints', icon: '🎨' }` right after Purchased Parts)

**Interfaces:**
- Produces `types/paint.ts`: `PaintType`, `Paint`, `PartPaintLayer`, `PartPaintSetup`, `PaintOverviewPart`, `PAINT_TYPE_LABEL`. `api/paints.ts`: `listPaints({activeOnly, q})`, `createPaint`, `updatePaint`, `paintUsedIn(id)`, `getPartPaint(partId)`, `putPartPaint(partId, setup)`, `projectPaintOverview(projectId)` wrapping `client`.
- Produces a shared `ColourSwatch({ hex, code })` component in `frontend/src/components/paint/ColourSwatch.tsx` (small rounded square with the hex as background, grey hatch when no hex, title = code).

- [ ] Test (mock `../api/client` like `CatalogPage` tests do; check `frontend/src/pages/CatalogPage.test.tsx` if present): renders the list from the mock, search filters via the `q` param, "show inactive" toggles `active_only`, new form posts the payload, edit form puts, expanding a row loads used-in and shows part numbers.
- [ ] Implement page in the style of `CatalogPage.tsx` (dark slate classes). Commit `feat(ui): paints page`.

---

### Task 5: Paint card on the part page

**Files:**
- Create: `frontend/src/components/paint/PartPaintCard.tsx`, `frontend/src/components/paint/PartPaintCard.test.tsx`
- Modify: `frontend/src/pages/PartDetail.tsx` (render `<PartPaintCard partId={part.id} />` right after the Part Information card)

**Interfaces:**
- Consumes `getPartPaint`, `putPartPaint`, `listPaints`, `ColourSwatch`, `PAINT_TYPE_LABEL` (Task 4).

- [ ] Test (mock `../../api/client`): loads setup; toggling "Paint required" on reveals process/layers; adding a layer from the picker (mock listPaints returns two paints) appends it; move up/down reorders; remove deletes; Save puts `{paint_required, process, notes, layers:[{paint_id, area, notes}]}` in the shown order; "paint spec missing" shows when required with no layers; an inactive paint layer shows "inactive".
- [ ] Implement with react-query (`['part-paint', partId]`), local draft state, single Save, toast on success. Commit `feat(ui): paint card on the part page`.

---

### Task 6: Painted chip and Paint section on the project page

**Files:**
- Create: `frontend/src/components/paint/ProjectPaintSection.tsx`, `frontend/src/components/paint/ProjectPaintSection.test.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`: (a) query `['project-paint-overview', id]` → `projectPaintOverview`; (b) category chips gain a `painted` entry `🎨 Painted (n)` after Assemblies, filtering `visibleNodes` to parts whose id is in the overview set, sorted with `comparePartNodes`; (c) tree rows show `<ColourSwatch>` of the top layer when the part is in the overview (pass a `paintByPartId` map into `TreeNodeComponent` like `projectCode`); (d) render `<ProjectPaintSection projectId={id} />` after `ProjectChangesSection`.
- Test: extend `frontend/src/pages/ProjectDetailPage.files.test.tsx` with a case: overview mock returns one painted part → chip reads `Painted (1)`, clicking it shows only that part, the row shows the swatch (`data-testid="paint-swatch-<partId>"`).

**Interfaces:** `ProjectPaintSection` groups overview parts by paint (a part with several layers appears under each paint with its layer position), header per paint (swatch, name, type label, colour code), collapsible like `ProjectSepSection`, empty state "No painted articles yet".

- [ ] Tests first, implement, run `npx tsc --noEmit -p tsconfig.json && npx vitest run`, commit `feat(ui): painted filter and paint overview on the project page`.

---

### Task 7: Docs

- Modify `MODULES.md`: add a **Paint** row (files: `models/paint.py`, `services/paint_service.py`, `api/v1/paints.py`, `api/v1/items/part_paint.py`; pages: PaintsPage, PartPaintCard, ProjectPaintSection; state: complete, engineering data only, part-level).
- Create `docs/PAINT.md` (short guide: what a paint is, how to set up an article, where the overview is, API table, out of scope list) linking the spec.
- Commit `docs: paint catalog guide`.

## Self-review notes
Spec §1 → T1; §2 → T2, T3; §3 Paints page → T4, part card → T5, project chip + section → T6; §5 tests spread per task; docs → T7. Names: `PaintService.put_setup/get_setup/project_overview/used_in` (T2) used by T3; `types/paint.ts` + `api/paints.ts` + `ColourSwatch` (T4) used by T5, T6; `comparePartNodes`, `visibleNodes`, `projectCode` prop already exist on ProjectDetailPage.
