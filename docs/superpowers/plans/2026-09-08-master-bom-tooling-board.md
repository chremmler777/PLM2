# Master BOM and Tooling Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the project page's flat parts tree with a master BOM grouped by sub-assembly (engineering basics editable inline, mirrors, completeness counts), and add a tooling board that assigns articles to tools, gauges and assembly equipment.

**Architecture:** Six engineering attributes move onto `part_revisions` (a frozen revision keeps what it was approved with), volumes onto `parts`, `cavities` onto `part_relations`, and `mirror_of` becomes a relation type. One rule decides a part's "current revision" — `RevisionService.pick_active_revision` / `active_revision` — and both composed reads use it. `app/services/master_bom_service.py` builds the whole project view in a fixed number of queries; `app/api/v1/items/project_bom.py` exposes it as `GET /v1/projects/{id}/master-bom` and `GET /v1/projects/{id}/tooling-board`. On the frontend, `src/components/bom/` holds types, API hooks, `MasterBomSection` and `ToolingBoard`, shown as a two-tab header on the project detail page.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (backend, tests with pytest + aiosqlite), React 18 + TanStack Query + Tailwind (frontend, tests with vitest + testing-library).

**Spec:** `docs/superpowers/specs/2026-09-08-master-bom-tooling-board-design.md`

## Global Constraints

- Backend tests: `cd backend && python3 -m pytest tests/<file> -q` (system `python3`; backend/.venv lacks pytest). Never run the full backend suite in a task (22+ minutes); the controller does.
- Frontend tests: `cd frontend && npx vitest run <path>`; `npx tsc --noEmit -p .` must report 0 errors after every frontend task (the project is currently clean).
- Commit after every task with the trailers:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Bts9vcERghAQ2cVvRSsFaY
  ```
- Never push. English only. Memory lives in `<project-root>/memory/`. Do not commit the unrelated uncommitted files `backend/app/services/change_service.py` and `workflow_service.py`.
- Current Alembic head is `"065"` (`backend/alembic/versions/065_sep_forms.py`); the new migration is `"066"`.
- Styling follows the PLM2 system used in `frontend/src/forms/FormRenderer.tsx` and `FormPanel.tsx` (slate-800 cards, `border-slate-700/70`, rounded-lg inputs `bg-slate-900 border border-slate-700 px-3 py-2 text-sm`, sky-600 primary buttons, `shadow-panel`, tabular numerals, inline SVG icons instead of emoji).
- The API is mounted under `/api`, so tests call `/api/v1/...` while the frontend axios client (baseURL `/plm2/api`) calls `/v1/...`.
- `tsconfig.json` has `noUnusedLocals` and `noUnusedParameters`: every symbol left behind after the tree removal must actually be used.

## File map

Backend (all under `backend/`):

| file | responsibility |
|---|---|
| `alembic/versions/066_master_bom.py` | additive columns on `part_revisions`, `parts`, `part_relations` |
| `app/models/part.py` | the new columns on `Part`, `PartRevision`, `PartRelation` |
| `app/schemas/part.py` | attributes/volumes in responses, `RevisionAttributesUpdate`, `PartVolumesUpdate` |
| `app/services/part_service.py` | `_enum_value`, `_revision_number`, `ACTIVE_PHASE_PRIORITY`, `RevisionService.pick_active_revision` / `active_revision` |
| `app/services/master_bom_service.py` | `build_master_bom`, `build_tooling_board`, `RELATION_KINDS` |
| `app/api/v1/items/parts.py` | `PATCH /parts/revisions/{id}/attributes`, `PATCH /parts/{id}/volumes` |
| `app/api/v1/items/part_relations.py` | `mirror_of`, `cavities`, `PATCH /parts/relations/{id}` |
| `app/api/v1/items/project_bom.py` | `GET /projects/{id}/master-bom`, `GET /projects/{id}/tooling-board` |
| `app/api/v1/__init__.py` | register the new router |
| `tests/test_master_bom.py` | every backend test of this feature |

Frontend (all under `frontend/src/`):

| file | responsibility |
|---|---|
| `components/bom/types.ts` | master BOM and board response types |
| `components/bom/api.ts` | query + mutation hooks, shared query keys |
| `components/bom/MasterBomSection.tsx` | grouped BOM table with inline attribute editing |
| `components/bom/MasterBomSection.test.tsx` | rows, missing cells, completeness, inline save, frozen |
| `components/bom/ToolingBoard.tsx` | article rail + item cards, assign/remove, cavities |
| `components/bom/ToolingBoard.test.tsx` | rail, cards, assign, remove, progress |
| `pages/ProjectDetailPage.tsx` | tree removed, two-tab header, detail panel kept |
| `components/PartRelationsSection.tsx` | "Mirror of" option, cavities on `produces` |

---

### Task 1: Migration 066, model columns, schema shapes

**Files:**
- Create: `backend/alembic/versions/066_master_bom.py`
- Modify: `backend/app/models/part.py` (`Part` after line 66 `data_classification`, `PartRevision` after line 152 `impact_analysis`, `PartRelation` after its `notes` column)
- Modify: `backend/app/schemas/part.py` (`PartResponse`, `PartRevisionResponse`, two new update models)
- Modify: `backend/app/api/v1/items/part_relations.py` (lines 19-38 constants, `RelationCreate`, `_relation_dict`, the `PartRelation(...)` construction)
- Test: `backend/tests/test_master_bom.py` (new file)

**Interfaces:**
- Produces: `PartRevision.material: str | None`, `.weight_g: float | None`, `.box_x_mm/.box_y_mm/.box_z_mm: float | None`, `.finish: str | None`; `Part.peak_annual_volume: int | None`, `.lifetime_volume: int | None`; `PartRelation.cavities: int | None`.
- Produces: `RevisionAttributesUpdate(material, weight_g, box_x_mm, box_y_mm, box_z_mm, finish)` and `PartVolumesUpdate(peak_annual_volume, lifetime_volume)` in `app/schemas/part.py`, all fields optional.
- Produces: relation type `"mirror_of"` accepted by `POST /v1/parts/{id}/relations`, labelled `("mirror of", "mirror of")`; `RelationCreate.cavities: int | None`; `_relation_dict` returns `cavities`.
- Consumes: `backend/tests/conftest.py` fixtures `session_factory`, `seed`, `client`, `eng_auth`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_master_bom.py`:
```python
"""Master BOM and tooling board: attributes, volumes, mirrors, cavities."""
from sqlalchemy import select

from app.models.part import Part, PartRelation, PartRevision


async def _create_part(client, auth, seed, part_number, name, *, part_type="internal_mfg",
                       item_category="article", customer_part_number=None):
    res = await client.post(
        "/api/v1/parts",
        json={
            "project_id": seed["project_id"],
            "part_number": part_number,
            "name": name,
            "part_type": part_type,
            "item_category": item_category,
            "customer_part_number": customer_part_number,
            "data_classification": "confidential",
        },
        headers=auth,
    )
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def test_attribute_columns_roundtrip(session_factory, seed):
    async with session_factory() as s:
        part = Part(project_id=seed["project_id"], part_number="A-1", name="Cover LH",
                    part_type="internal_mfg", item_category="article",
                    peak_annual_volume=41000, lifetime_volume=159000,
                    created_by=seed["admin_id"])
        mirror = Part(project_id=seed["project_id"], part_number="A-2", name="Cover RH",
                      part_type="internal_mfg", item_category="article",
                      created_by=seed["admin_id"])
        tool = Part(project_id=seed["project_id"], part_number="T-1", name="T-0412",
                    part_type="purchased", item_category="tool",
                    created_by=seed["admin_id"])
        s.add_all([part, mirror, tool])
        await s.flush()
        s.add(PartRevision(part_id=part.id, revision_name="ENG1", phase="engineering",
                           status="in_progress", material="PC/ABS", weight_g=203.6,
                           box_x_mm=401.8, box_y_mm=338.0, box_z_mm=27.64,
                           finish="EDM grain Feinnarbe L", created_by=seed["admin_id"]))
        s.add(PartRelation(from_part_id=part.id, to_part_id=mirror.id,
                           relation_type="mirror_of", created_by=seed["admin_id"]))
        s.add(PartRelation(from_part_id=tool.id, to_part_id=part.id,
                           relation_type="produces", cavities=2,
                           created_by=seed["admin_id"]))
        await s.commit()

    async with session_factory() as s:
        rev = (await s.execute(select(PartRevision))).scalar_one()
        assert rev.material == "PC/ABS"
        assert rev.weight_g == 203.6
        assert (rev.box_x_mm, rev.box_y_mm, rev.box_z_mm) == (401.8, 338.0, 27.64)
        assert rev.finish == "EDM grain Feinnarbe L"

        left = (await s.execute(select(Part).where(Part.part_number == "A-1"))).scalar_one()
        assert (left.peak_annual_volume, left.lifetime_volume) == (41000, 159000)

        mirror_rel = (await s.execute(
            select(PartRelation).where(PartRelation.relation_type == "mirror_of"))).scalar_one()
        assert mirror_rel.cavities is None
        produces_rel = (await s.execute(
            select(PartRelation).where(PartRelation.relation_type == "produces"))).scalar_one()
        assert produces_rel.cavities == 2


async def test_relation_api_accepts_mirror_and_cavities(client, eng_auth, seed):
    left = await _create_part(client, eng_auth, seed, "A-10", "Cover LH")
    right = await _create_part(client, eng_auth, seed, "A-11", "Cover RH")
    tool = await _create_part(client, eng_auth, seed, "T-10", "T-0412",
                              part_type="purchased", item_category="tool")

    res = await client.post(f"/api/v1/parts/{left}/relations",
                            json={"to_part_id": right, "relation_type": "mirror_of"},
                            headers=eng_auth)
    assert res.status_code == 201, res.text
    assert res.json()["label"] == "mirror of"
    assert res.json()["cavities"] is None

    res = await client.post(f"/api/v1/parts/{tool}/relations",
                            json={"to_part_id": left, "relation_type": "produces", "cavities": 4},
                            headers=eng_auth)
    assert res.status_code == 201, res.text
    assert res.json()["cavities"] == 4

    res = await client.get(f"/api/v1/parts/{left}/relations", headers=eng_auth)
    kinds = {r["relation_type"]: r["cavities"] for r in res.json()}
    assert kinds == {"mirror_of": None, "produces": 4}
```

- [ ] **Step 2: Run to see it fail**

Run: `cd backend && python3 -m pytest tests/test_master_bom.py -q`
Expected: `TypeError: 'peak_annual_volume' is an invalid keyword argument for Part` in the first test, and `400 Invalid relation_type` in the second.

- [ ] **Step 3: Add the model columns**

In `backend/app/models/part.py`, class `Part`, immediately after the `data_classification` column:
```python
    # Master BOM volumes. Used for sub-assemblies, allowed on any part: the
    # numbers are quoted per assembly but nobody gains from a column that
    # refuses to hold a figure somebody has.
    peak_annual_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lifetime_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

In class `PartRevision`, immediately after the `impact_analysis` column:
```python
    # Master BOM engineering basics. They live on the revision, not the part,
    # so a frozen revision keeps the values it was approved with.
    material: Mapped[str | None] = mapped_column(String(120), nullable=True)
    weight_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    box_x_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    box_y_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    box_z_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    finish: Mapped[str | None] = mapped_column(String(255), nullable=True)
```

In class `PartRelation`, immediately after the `notes` column:
```python
    # Cavities of the tool that produces the article. Meaningful for
    # 'produces' only; every other relation type stores None.
    cavities: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

Also extend the `relation_type` comment above that column to list the new value:
```python
    # produces, checks, assembles, related, serves, feeds, mirror_of
    # (serves/feeds link equipment and tools — see app/services/equipment_numbering.py)
    # (mirror_of pairs a left-hand and a right-hand part; stored once, read symmetrically)
```

- [ ] **Step 4: Write the migration**

`backend/alembic/versions/066_master_bom.py`:
```python
"""066: master BOM — engineering basics on the revision, volumes on the part,
cavities on the relation.

Additive and nullable throughout, so nothing needs a backfill: a revision
without values simply shows empty cells, which is exactly the "missing" state
the master BOM highlights. The six engineering attributes sit on
part_revisions rather than parts because a frozen revision has to keep the
values it was approved with — moving them to the part would rewrite history
every time somebody corrects a weight.

FKs are ORM-level only and there are none to add here anyway; SQLite cannot
ADD COLUMN with a constraint, the same call 059/064 made.

Revision ID: 066
Revises: 065
Create Date: 2026-09-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None

_REVISION_COLUMNS = (
    ("material", lambda: sa.Column("material", sa.String(120), nullable=True)),
    ("weight_g", lambda: sa.Column("weight_g", sa.Float(), nullable=True)),
    ("box_x_mm", lambda: sa.Column("box_x_mm", sa.Float(), nullable=True)),
    ("box_y_mm", lambda: sa.Column("box_y_mm", sa.Float(), nullable=True)),
    ("box_z_mm", lambda: sa.Column("box_z_mm", sa.Float(), nullable=True)),
    ("finish", lambda: sa.Column("finish", sa.String(255), nullable=True)),
)

_PART_COLUMNS = (
    ("peak_annual_volume", lambda: sa.Column("peak_annual_volume", sa.Integer(), nullable=True)),
    ("lifetime_volume", lambda: sa.Column("lifetime_volume", sa.Integer(), nullable=True)),
)

_RELATION_COLUMNS = (
    ("cavities", lambda: sa.Column("cavities", sa.Integer(), nullable=True)),
)


def _add_columns(insp, table: str, columns) -> None:
    if table not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns(table)}
    for name, make in columns:
        if name not in existing:
            op.add_column(table, make())


def upgrade() -> None:
    insp = inspect(op.get_bind())
    _add_columns(insp, "part_revisions", _REVISION_COLUMNS)
    _add_columns(insp, "parts", _PART_COLUMNS)
    _add_columns(insp, "part_relations", _RELATION_COLUMNS)


def downgrade() -> None:
    pass  # forward-only
```

- [ ] **Step 5: Extend the pydantic shapes**

In `backend/app/schemas/part.py`, add the volume fields to `PartResponse` (after `active_revision_id`):
```python
    peak_annual_volume: Optional[int] = None
    lifetime_volume: Optional[int] = None
```

Add the attributes to `PartRevisionResponse` (after `test_data_status`):
```python
    material: Optional[str] = None
    weight_g: Optional[float] = None
    box_x_mm: Optional[float] = None
    box_y_mm: Optional[float] = None
    box_z_mm: Optional[float] = None
    finish: Optional[str] = None
```

Add the two update models directly above the `# Update forward references` block at the end of the file:
```python
class RevisionAttributesUpdate(BaseModel):
    """The master BOM's engineering basics; any subset may be sent.

    Every field is optional and `exclude_unset` decides what is written, so
    clearing one cell (sending null) is distinguishable from not touching it.
    """
    material: Optional[str] = Field(None, max_length=120)
    weight_g: Optional[float] = Field(None, ge=0)
    box_x_mm: Optional[float] = Field(None, ge=0)
    box_y_mm: Optional[float] = Field(None, ge=0)
    box_z_mm: Optional[float] = Field(None, ge=0)
    finish: Optional[str] = Field(None, max_length=255)


class PartVolumesUpdate(BaseModel):
    """Peak annual and lifetime volumes; either may be sent alone."""
    peak_annual_volume: Optional[int] = Field(None, ge=0)
    lifetime_volume: Optional[int] = Field(None, ge=0)
```

- [ ] **Step 6: Accept `mirror_of` and `cavities` in the relations API**

In `backend/app/api/v1/items/part_relations.py`, replace the constants block (lines 19-38) with:
```python
VALID_RELATION_TYPES = {"produces", "checks", "assembles", "related",
                        "serves", "feeds", "mirror_of"}

# Human-readable labels per direction
RELATION_LABELS = {
    "produces": ("produces", "produced by"),
    "checks": ("checks", "checked by"),
    "assembles": ("assembles", "assembled by"),
    "related": ("related to", "related to"),
    # serves: equipment -> every tool it covers (see equipment_numbering.py).
    # feeds: tool -> downstream tool whose station consumes its parts.
    "serves": ("serves", "served by"),
    "feeds": ("feeds", "fed by"),
    # mirror_of is symmetric: the left-hand part mirrors the right-hand one
    # and the other way round, so both directions read the same.
    "mirror_of": ("mirror of", "mirror of"),
}

# Cavities describe the tool that produces an article; every other relation
# type stores None even when a client sends a number.
CAVITY_RELATION_TYPE = "produces"


class RelationCreate(BaseModel):
    to_part_id: int
    relation_type: str = Field(..., description="produces, checks, assembles, related, mirror_of")
    notes: Optional[str] = None
    cavities: Optional[int] = Field(None, ge=1, description="Cavities of a 'produces' tool")
```

In `_relation_dict`, add the field before `"notes"`:
```python
        "cavities": rel.cavities,
```

In `create_relation`, pass the clamped value when constructing the row:
```python
        rel = PartRelation(
            from_part_id=part_id,
            to_part_id=body.to_part_id,
            relation_type=body.relation_type,
            notes=body.notes,
            cavities=body.cavities if body.relation_type == CAVITY_RELATION_TYPE else None,
            created_by=current_user.id,
        )
```

- [ ] **Step 7: Run to see it pass**

Run: `cd backend && python3 -m pytest tests/test_master_bom.py -q`
Expected: 2 passed.

Also run the existing relation tests, which must stay green:
Run: `cd backend && python3 -m pytest tests/test_part_relations.py tests/test_equipment_relations.py -q`
Expected: all passed.

- [ ] **Step 8: Commit**

```bash
git add backend/alembic/versions/066_master_bom.py backend/app/models/part.py backend/app/schemas/part.py backend/app/api/v1/items/part_relations.py backend/tests/test_master_bom.py
git commit -m "feat(bom): revision attributes, part volumes, mirror relations and cavities

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bts9vcERghAQ2cVvRSsFaY"
```

---

### Task 2: `RevisionService.active_revision`

**Files:**
- Modify: `backend/app/services/part_service.py` (module-level helpers directly above `class RevisionService` at line 180; two methods at the top of the class body, after its docstring on line 181)
- Test: `backend/tests/test_master_bom.py` (append)

**Interfaces:**
- Produces: `RevisionService.pick_active_revision(revisions: List[PartRevision]) -> Optional[PartRevision]` — sync, takes an already-loaded list, so a caller holding every revision of a project spends no extra query per part.
- Produces: `async RevisionService.active_revision(session: AsyncSession, part_id: int) -> Optional[PartRevision]`.
- Produces: module-level `ACTIVE_PHASE_PRIORITY`, `_enum_value(v) -> str`, `_revision_number(name: str) -> int`.
- Rule: the latest non-rejected major revision (`parent_revision_id is None`, highest number in `revision_name`) in the most advanced phase present — freeze, then engineering, then RFQ. Mirrors `getActiveRevisionLevel` in `frontend/src/pages/PartDetail.tsx` lines 131-160.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_master_bom.py`:
```python
async def _add_revision(s, part_id, name, phase, status, created_by, parent_id=None):
    rev = PartRevision(part_id=part_id, revision_name=name, phase=phase, status=status,
                       parent_revision_id=parent_id, created_by=created_by)
    s.add(rev)
    await s.flush()
    return rev


async def test_active_revision_prefers_the_most_advanced_phase(session_factory, seed):
    from app.services.part_service import RevisionService

    async with session_factory() as s:
        part = Part(project_id=seed["project_id"], part_number="A-3", name="Bracket",
                    part_type="internal_mfg", item_category="article",
                    created_by=seed["admin_id"])
        s.add(part)
        await s.flush()
        await _add_revision(s, part.id, "RFQ1", "rfq_phase", "in_progress", seed["admin_id"])
        await _add_revision(s, part.id, "ENG1", "engineering", "in_progress", seed["admin_id"])
        eng2 = await _add_revision(s, part.id, "ENG2", "engineering", "in_progress", seed["admin_id"])
        # A minor proposal is never the current revision.
        await _add_revision(s, part.id, "ENG2.1", "engineering", "draft", seed["admin_id"],
                            parent_id=eng2.id)
        await s.commit()
        part_id = part.id

    async with session_factory() as s:
        active = await RevisionService.active_revision(s, part_id)
        assert active is not None and active.revision_name == "ENG2"

    async with session_factory() as s:
        part = (await s.execute(select(Part).where(Part.id == part_id))).scalar_one()
        await _add_revision(s, part.id, "IND1", "freeze", "frozen", seed["admin_id"])
        await s.commit()

    async with session_factory() as s:
        active = await RevisionService.active_revision(s, part_id)
        assert active is not None and active.revision_name == "IND1"


async def test_active_revision_skips_rejected_and_falls_back(session_factory, seed):
    from app.services.part_service import RevisionService

    async with session_factory() as s:
        part = Part(project_id=seed["project_id"], part_number="A-4", name="Clip",
                    part_type="internal_mfg", item_category="article",
                    created_by=seed["admin_id"])
        s.add(part)
        await s.flush()
        await _add_revision(s, part.id, "RFQ1", "rfq_phase", "in_progress", seed["admin_id"])
        await _add_revision(s, part.id, "ENG1", "engineering", "rejected", seed["admin_id"])
        await s.commit()
        part_id = part.id

    async with session_factory() as s:
        active = await RevisionService.active_revision(s, part_id)
        assert active is not None and active.revision_name == "RFQ1"


async def test_active_revision_is_none_without_revisions(session_factory, seed):
    from app.services.part_service import RevisionService

    async with session_factory() as s:
        part = Part(project_id=seed["project_id"], part_number="A-5", name="Nut",
                    part_type="purchased", item_category="article",
                    created_by=seed["admin_id"])
        s.add(part)
        await s.commit()
        part_id = part.id

    async with session_factory() as s:
        assert await RevisionService.active_revision(s, part_id) is None
```

- [ ] **Step 2: Run to see it fail**

Run: `cd backend && python3 -m pytest tests/test_master_bom.py -q`
Expected: `AttributeError: type object 'RevisionService' has no attribute 'active_revision'` in three tests.

- [ ] **Step 3: Implement the rule**

In `backend/app/services/part_service.py`, insert directly above `class RevisionService:` (line 180):
```python
# Phase order for "the current revision": the most advanced phase a part has
# reached wins. This mirrors getActiveRevisionLevel in
# frontend/src/pages/PartDetail.tsx, which is what people read on the part
# page — the master BOM must not disagree with it. ECN work is always a minor
# proposal under a freeze, so the ECN phase never appears here.
ACTIVE_PHASE_PRIORITY = (
    RevisionPhase.DESIGN_FREEZE_PHASE.value,
    RevisionPhase.ENGINEERING_PHASE.value,
    RevisionPhase.RFQ_PHASE.value,
)


def _enum_value(value) -> str:
    """Enum columns come back as the enum or the raw string depending on the
    driver and whether the row was just written; both have to compare equal."""
    return value.value if hasattr(value, "value") else str(value)


def _revision_number(name: str) -> int:
    """The number in a major revision name: ENG12 -> 12, RFQ1 -> 1."""
    digits = "".join(ch for ch in name if ch.isdigit())
    return int(digits) if digits else 0


```

Then, inside `class RevisionService`, immediately after its docstring line and before the first `@staticmethod`:
```python
    @staticmethod
    def pick_active_revision(revisions: List[PartRevision]) -> Optional[PartRevision]:
        """The part's current revision, chosen from an already-loaded list.

        The latest non-rejected major (no parent revision) in the most
        advanced phase present. Callers that hold every revision of a project
        use this directly so the master BOM stays one query, not one per part.
        """
        for phase in ACTIVE_PHASE_PRIORITY:
            in_phase = [
                r for r in revisions
                if r.parent_revision_id is None and _enum_value(r.phase) == phase
            ]
            in_phase.sort(key=lambda r: _revision_number(r.revision_name), reverse=True)
            for revision in in_phase:
                if _enum_value(revision.status) != RevisionStatus.REJECTED.value:
                    return revision
        return None

    @staticmethod
    async def active_revision(
        session: AsyncSession,
        part_id: int,
    ) -> Optional[PartRevision]:
        """The part's current revision (see pick_active_revision)."""
        result = await session.execute(
            select(PartRevision).where(PartRevision.part_id == part_id)
        )
        return RevisionService.pick_active_revision(list(result.scalars().all()))

```

- [ ] **Step 4: Run to see it pass**

Run: `cd backend && python3 -m pytest tests/test_master_bom.py -q`
Expected: 5 passed.

Run: `cd backend && python3 -m pytest tests/test_parts.py tests/test_part_bom.py -q`
Expected: all passed (the new module-level names must not shadow anything).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/part_service.py backend/tests/test_master_bom.py
git commit -m "feat(bom): one server-side rule for a part's current revision

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bts9vcERghAQ2cVvRSsFaY"
```

---

### Task 3: Attributes, volumes, cavities and mirror rules

**Files:**
- Modify: `backend/app/api/v1/items/parts.py` (imports at lines 14-26; two endpoints after `get_revision`, which ends at line 166)
- Modify: `backend/app/api/v1/items/part_relations.py` (mirror guard inside `create_relation`, new `RelationUpdate` + `PATCH /relations/{relation_id}`)
- Test: `backend/tests/test_master_bom.py` (append)

**Interfaces:**
- Produces: `PATCH /v1/parts/revisions/{revision_id}/attributes` with body `RevisionAttributesUpdate` -> `PartRevisionResponse`; 409 `"Revision is frozen"` when the revision's status is `frozen`; 404 when unknown.
- Produces: `PATCH /v1/parts/{part_id}/volumes` with body `PartVolumesUpdate` -> `PartResponse`.
- Produces: `PATCH /v1/parts/relations/{relation_id}` with body `RelationUpdate(cavities)` -> the `_relation_dict` shape; the value is stored only for `produces`.
- Produces: `POST /v1/parts/{part_id}/relations` refuses a self-mirror and a second mirror on either part with 409.
- Consumes: `RevisionService.get_revision`, `PartService.get_part`, `ChangelogService.log_action` from `app/services/part_service.py`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_master_bom.py`:
```python
from tests.conftest import freeze_revision


async def _create_revision(client, auth, part_id):
    res = await client.post(f"/api/v1/parts/{part_id}/revisions/rfq",
                            json={"summary": "initial"}, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def test_attributes_patch_updates_and_refuses_frozen(client, eng_auth, seed, session_factory):
    part_id = await _create_part(client, eng_auth, seed, "A-20", "Cover SHUD LHD")
    revision_id = await _create_revision(client, eng_auth, part_id)

    res = await client.patch(
        f"/api/v1/parts/revisions/{revision_id}/attributes",
        json={"material": "PC/ABS", "weight_g": 203.6, "box_x_mm": 401.8,
              "box_y_mm": 338, "box_z_mm": 27.64, "finish": "EDM grain Feinnarbe L"},
        headers=eng_auth,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["material"] == "PC/ABS"
    assert body["weight_g"] == 203.6
    assert body["finish"] == "EDM grain Feinnarbe L"

    # A partial write leaves the other cells alone.
    res = await client.patch(f"/api/v1/parts/revisions/{revision_id}/attributes",
                             json={"weight_g": 210.0}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["weight_g"] == 210.0
    assert res.json()["material"] == "PC/ABS"

    await freeze_revision(session_factory, revision_id)
    res = await client.patch(f"/api/v1/parts/revisions/{revision_id}/attributes",
                             json={"material": "PA6-GF30"}, headers=eng_auth)
    assert res.status_code == 409, res.text
    assert res.json()["detail"] == "Revision is frozen"


async def test_volumes_patch(client, eng_auth, seed):
    part_id = await _create_part(client, eng_auth, seed, "A-21", "Cover assembly",
                                 part_type="sub_assembly")
    res = await client.patch(f"/api/v1/parts/{part_id}/volumes",
                             json={"peak_annual_volume": 41000, "lifetime_volume": 159000},
                             headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["peak_annual_volume"] == 41000
    assert res.json()["lifetime_volume"] == 159000

    res = await client.patch(f"/api/v1/parts/{part_id}/volumes",
                             json={"lifetime_volume": 170000}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["peak_annual_volume"] == 41000
    assert res.json()["lifetime_volume"] == 170000


async def test_mirror_rules(client, eng_auth, seed):
    left = await _create_part(client, eng_auth, seed, "A-22", "PD Inner LH")
    right = await _create_part(client, eng_auth, seed, "A-23", "PD Inner RH")
    third = await _create_part(client, eng_auth, seed, "A-24", "PD Inner spare")

    res = await client.post(f"/api/v1/parts/{left}/relations",
                            json={"to_part_id": left, "relation_type": "mirror_of"},
                            headers=eng_auth)
    assert res.status_code == 409, res.text

    res = await client.post(f"/api/v1/parts/{left}/relations",
                            json={"to_part_id": right, "relation_type": "mirror_of"},
                            headers=eng_auth)
    assert res.status_code == 201, res.text

    res = await client.post(f"/api/v1/parts/{left}/relations",
                            json={"to_part_id": third, "relation_type": "mirror_of"},
                            headers=eng_auth)
    assert res.status_code == 409, res.text

    # Also refused from the other side of the existing pair.
    res = await client.post(f"/api/v1/parts/{third}/relations",
                            json={"to_part_id": right, "relation_type": "mirror_of"},
                            headers=eng_auth)
    assert res.status_code == 409, res.text


async def test_cavities_patch_and_ignored_for_other_types(client, eng_auth, seed):
    article = await _create_part(client, eng_auth, seed, "A-25", "Grille carrier")
    tool = await _create_part(client, eng_auth, seed, "T-25", "T-0417",
                              part_type="purchased", item_category="tool")
    gauge = await _create_part(client, eng_auth, seed, "G-25", "Gauge 25",
                               part_type="purchased", item_category="gauge")

    res = await client.post(f"/api/v1/parts/{tool}/relations",
                            json={"to_part_id": article, "relation_type": "produces",
                                  "cavities": 1}, headers=eng_auth)
    assert res.status_code == 201, res.text
    tool_rel = res.json()["id"]

    res = await client.post(f"/api/v1/parts/{gauge}/relations",
                            json={"to_part_id": article, "relation_type": "checks",
                                  "cavities": 3}, headers=eng_auth)
    assert res.status_code == 201, res.text
    gauge_rel = res.json()["id"]
    assert res.json()["cavities"] is None

    res = await client.patch(f"/api/v1/parts/relations/{tool_rel}",
                             json={"cavities": 2}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["cavities"] == 2

    res = await client.patch(f"/api/v1/parts/relations/{gauge_rel}",
                             json={"cavities": 2}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["cavities"] is None

    res = await client.patch("/api/v1/parts/relations/999999",
                             json={"cavities": 2}, headers=eng_auth)
    assert res.status_code == 404
```

- [ ] **Step 2: Run to see it fail**

Run: `cd backend && python3 -m pytest tests/test_master_bom.py -q`
Expected: 4 failures — the two PATCH paths return 405 (`Method Not Allowed`), the self-mirror returns 400 instead of 409, and the second mirror returns 201.

- [ ] **Step 3: Add the attributes and volumes endpoints**

In `backend/app/api/v1/items/parts.py`, extend the model import on line 15:
```python
from app.models.part import PartFile, RevisionStatus
```

and the schema import block so it also brings in the two update models:
```python
from app.schemas.part import (
    PartCreate, PartUpdate, PartResponse, PartDetailResponse,
    PartRevisionResponse, PartRevisionDetailResponse,
    ChangelogEntryResponse, RevisionTreeNode,
    CreateRFQRequest, CreateRFQProposalRequest, PromoteRevisionRequest,
    RejectMajorRevisionRequest,
    TransitionToEngineeringRequest, CreateEngineeringProposalRequest,
    ApproveProposalRequest, RejectProposalRequest, CreateDesignFreezeRequest,
    CreateECRRequest, RevisionAttributesUpdate, PartVolumesUpdate
)
```

Insert both endpoints immediately after `get_revision` (which ends at line 166) and before the `# RFQ Phase Endpoints` comment:
```python
@router.patch("/revisions/{revision_id}/attributes", response_model=PartRevisionResponse)
async def update_revision_attributes(
    revision_id: int,
    body: RevisionAttributesUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set the master BOM's engineering basics on a revision.

    A frozen revision keeps the values it was approved with, so the write is
    refused rather than silently dropped: the cell in the UI reverts and says
    why. Only the keys actually sent are written, so editing one cell never
    clears the others.
    """
    revision = await RevisionService.get_revision(db, revision_id)
    if not revision:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found")

    current_status = revision.status.value if hasattr(revision.status, "value") else str(revision.status)
    if current_status == RevisionStatus.FROZEN.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Revision is frozen")

    updates = body.model_dump(exclude_unset=True)
    if updates:
        for field, value in updates.items():
            setattr(revision, field, value)
        revision.updated_by = current_user.id
        await ChangelogService.log_action(
            session=db,
            part_id=revision.part_id,
            revision_id=revision.id,
            action="metadata_updated",
            action_description=(
                f"Updated {revision.revision_name} attributes: " + ", ".join(sorted(updates))
            ),
            performed_by=current_user.id,
        )
    await db.commit()
    await db.refresh(revision)
    return revision


@router.patch("/{part_id}/volumes", response_model=PartResponse)
async def update_part_volumes(
    part_id: int,
    body: PartVolumesUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set peak annual and lifetime volumes. Quoted per assembly, but any
    part may carry them."""
    part = await PartService.get_part(db, part_id)
    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(part, field, value)
    if updates:
        part.updated_by = current_user.id
    await db.commit()
    await db.refresh(part)
    return part


```

- [ ] **Step 4: Add the mirror guard and the relation PATCH**

In `backend/app/api/v1/items/part_relations.py`, inside `create_relation`, insert the mirror block directly after the `relation_type` validation and **before** the existing self-relation check, so a self-mirror answers with the mirror rule's own 409 rather than the generic 400:
```python
        if body.relation_type == "mirror_of":
            if body.to_part_id == part_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A part cannot be its own mirror",
                )
            pair = [part_id, body.to_part_id]
            existing_mirror = await db.execute(
                select(PartRelation).where(
                    PartRelation.relation_type == "mirror_of",
                    or_(
                        PartRelation.from_part_id.in_(pair),
                        PartRelation.to_part_id.in_(pair),
                    ),
                )
            )
            if existing_mirror.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="One of these parts already has a mirror",
                )
```

Add the update model directly below `RelationCreate`:
```python
class RelationUpdate(BaseModel):
    cavities: Optional[int] = Field(None, ge=1)
```

And add the endpoint between `list_relations` and `delete_relation`:
```python
@router.patch("/relations/{relation_id}", response_model=dict)
async def update_relation(
    relation_id: int,
    body: RelationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set the cavity count on a tool-to-article link.

    Cavities describe an injection tool, so the number is kept only on a
    'produces' relation; on any other type it stays None, the same rule the
    create endpoint applies.
    """
    try:
        result = await db.execute(
            select(PartRelation)
            .where(PartRelation.id == relation_id)
            .options(joinedload(PartRelation.from_part), joinedload(PartRelation.to_part))
        )
        rel = result.unique().scalar_one_or_none()
        if not rel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relation not found")

        rel.cavities = body.cavities if rel.relation_type == CAVITY_RELATION_TYPE else None
        await db.commit()
        return _relation_dict(rel, "outgoing")
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update relation {relation_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


```

- [ ] **Step 5: Run to see it pass**

Run: `cd backend && python3 -m pytest tests/test_master_bom.py -q`
Expected: 9 passed.

Run: `cd backend && python3 -m pytest tests/test_part_relations.py tests/test_parts.py -q`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/items/parts.py backend/app/api/v1/items/part_relations.py backend/tests/test_master_bom.py
git commit -m "feat(bom): attribute and volume writes, cavities patch, one-mirror rule

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bts9vcERghAQ2cVvRSsFaY"
```

---

### Task 4: `GET /v1/projects/{id}/master-bom`

**Files:**
- Create: `backend/app/services/master_bom_service.py`
- Create: `backend/app/api/v1/items/project_bom.py`
- Modify: `backend/app/api/v1/__init__.py` (import next to the other `items` imports on lines 13-17; `include_router` next to the other items routers on lines 52-56)
- Test: `backend/tests/test_master_bom.py` (append)

**Interfaces:**
- Produces: `async build_master_bom(session, project_id) -> dict` with `{"groups": [...], "relation_kinds": {"tool": "produces", "gauge": "checks", "assembly_equipment": "assembles"}}`.
- Produces: a group `{part_id, name, customer_part_number, revision_id, revision_name, revision_status, peak_annual_volume, lifetime_volume, filled, total, rows}`; the last group is always `{"part_id": None, "name": "Unassigned", ...}`.
- Produces: a row `{part_id, bom_item_id, item_number, quantity, unit, name, customer_part_number, item_category, part_type, revision_id, revision_name, revision_status, frozen, material, weight_g, box_x_mm, box_y_mm, box_z_mm, finish, mirror_part_id, mirror_name, linked: {tool: [{part_id, name, cavities}], gauge: [], assembly_equipment: []}}`.
- Produces: constants `RELATION_KINDS`, `ATTRIBUTE_FIELDS`, `UNASSIGNED_NAME`, and helper `_load_project(session, project_id) -> (parts, active, relations)` reused by task 5.
- Produces: `GET /v1/projects/{project_id}/master-bom` (404 on an unknown project).
- Consumes: `RevisionService.pick_active_revision` and `_enum_value` from `app/services/part_service.py` (task 2).

Decisions this task pins, both consistent with the spec's rules rather than its abbreviated example: the `Unassigned` group is always present (so a project with two assemblies always answers with three groups), and its `filled`/`total` are counted the same way as any other group's rather than hardcoded to zero.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_master_bom.py`:
```python
async def _add_bom_item(client, auth, part_id, revision_id, **body):
    res = await client.post(f"/api/v1/parts/{part_id}/revisions/{revision_id}/bom",
                            json=body, headers=auth)
    assert res.status_code == 201, res.text
    return res.json()


async def _set_attributes(client, auth, revision_id, **body):
    res = await client.patch(f"/api/v1/parts/revisions/{revision_id}/attributes",
                             json=body, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


FULL_ATTRIBUTES = {"material": "PC/ABS", "weight_g": 203.6, "box_x_mm": 401.8,
                   "box_y_mm": 338.0, "box_z_mm": 27.64, "finish": "Feinnarbe L"}


async def test_master_bom_groups_assemblies_and_unassigned(client, eng_auth, seed):
    project_id = seed["project_id"]

    cover = await _create_part(client, eng_auth, seed, "SA-1", "Cover assembly LHD",
                               part_type="sub_assembly", customer_part_number="9656732")
    cover_rev = await _create_revision(client, eng_auth, cover)
    grille = await _create_part(client, eng_auth, seed, "SA-2", "Grille assembly",
                                part_type="sub_assembly")
    grille_rev = await _create_revision(client, eng_auth, grille)

    left = await _create_part(client, eng_auth, seed, "A-30", "Cover SHUD LHD",
                              customer_part_number="9656733")
    left_rev = await _create_revision(client, eng_auth, left)
    await _set_attributes(client, eng_auth, left_rev, **FULL_ATTRIBUTES)
    carrier = await _create_part(client, eng_auth, seed, "A-31", "Grille carrier")
    await _create_revision(client, eng_auth, carrier)
    loose = await _create_part(client, eng_auth, seed, "A-32", "Clip")
    await _create_revision(client, eng_auth, loose)
    # Tools are never rows, not even loose ones.
    await _create_part(client, eng_auth, seed, "T-30", "T-0412",
                       part_type="purchased", item_category="tool")

    await _add_bom_item(client, eng_auth, cover, cover_rev, child_part_id=left, quantity=1)
    await _add_bom_item(client, eng_auth, cover, cover_rev, name="Adhesive", quantity=0.5, unit="m")
    await _add_bom_item(client, eng_auth, grille, grille_rev, child_part_id=carrier, quantity=2)

    res = await client.get(f"/api/v1/projects/{project_id}/master-bom", headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["relation_kinds"] == {"tool": "produces", "gauge": "checks",
                                      "assembly_equipment": "assembles"}

    names = [g["name"] for g in body["groups"]]
    assert names == ["Cover assembly LHD", "Grille assembly", "Unassigned"]
    assert body["groups"][-1]["part_id"] is None

    cover_group = body["groups"][0]
    assert cover_group["customer_part_number"] == "9656732"
    assert cover_group["revision_name"] == "RFQ1"
    assert [r["name"] for r in cover_group["rows"]] == ["Cover SHUD LHD", "Adhesive"]

    row = cover_group["rows"][0]
    assert row["part_id"] == left
    assert row["item_number"] == "10"
    assert row["customer_part_number"] == "9656733"
    assert row["material"] == "PC/ABS"
    assert row["weight_g"] == 203.6
    assert row["frozen"] is False
    assert row["linked"] == {"tool": [], "gauge": [], "assembly_equipment": []}

    free_text = cover_group["rows"][1]
    assert free_text["part_id"] is None
    assert free_text["quantity"] == 0.5 and free_text["unit"] == "m"
    assert free_text["material"] is None

    # Only the row with a part counts, and only the fully filled one is filled.
    assert (cover_group["filled"], cover_group["total"]) == (1, 1)
    assert (body["groups"][1]["filled"], body["groups"][1]["total"]) == (0, 1)

    unassigned = body["groups"][-1]
    assert [r["name"] for r in unassigned["rows"]] == ["Clip"]
    assert unassigned["rows"][0]["part_id"] == loose


async def test_master_bom_reports_frozen_mirrors_and_links(client, eng_auth, seed, session_factory):
    project_id = seed["project_id"]

    assembly = await _create_part(client, eng_auth, seed, "SA-3", "PD assembly",
                                  part_type="sub_assembly")
    assembly_rev = await _create_revision(client, eng_auth, assembly)
    left = await _create_part(client, eng_auth, seed, "A-40", "PD Inner LH")
    left_rev = await _create_revision(client, eng_auth, left)
    right = await _create_part(client, eng_auth, seed, "A-41", "PD Inner RH")
    right_rev = await _create_revision(client, eng_auth, right)
    tool = await _create_part(client, eng_auth, seed, "T-40", "T-0418",
                              part_type="purchased", item_category="tool")
    gauge = await _create_part(client, eng_auth, seed, "G-40", "Gauge 40",
                               part_type="purchased", item_category="gauge")

    await _add_bom_item(client, eng_auth, assembly, assembly_rev, child_part_id=left)
    await _add_bom_item(client, eng_auth, assembly, assembly_rev, child_part_id=right)

    res = await client.post(f"/api/v1/parts/{left}/relations",
                            json={"to_part_id": right, "relation_type": "mirror_of"},
                            headers=eng_auth)
    assert res.status_code == 201, res.text
    res = await client.post(f"/api/v1/parts/{tool}/relations",
                            json={"to_part_id": left, "relation_type": "produces", "cavities": 1},
                            headers=eng_auth)
    assert res.status_code == 201, res.text
    res = await client.post(f"/api/v1/parts/{gauge}/relations",
                            json={"to_part_id": left, "relation_type": "checks"},
                            headers=eng_auth)
    assert res.status_code == 201, res.text

    await freeze_revision(session_factory, right_rev)

    res = await client.get(f"/api/v1/projects/{project_id}/master-bom", headers=eng_auth)
    rows = {r["name"]: r for r in res.json()["groups"][0]["rows"]}

    assert rows["PD Inner LH"]["revision_id"] == left_rev
    assert rows["PD Inner LH"]["frozen"] is False
    assert rows["PD Inner LH"]["mirror_part_id"] == right
    assert rows["PD Inner LH"]["mirror_name"] == "PD Inner RH"
    # The mirror is stored once and read from both sides.
    assert rows["PD Inner RH"]["mirror_part_id"] == left
    assert rows["PD Inner RH"]["mirror_name"] == "PD Inner LH"

    assert rows["PD Inner RH"]["frozen"] is True
    assert rows["PD Inner RH"]["revision_status"] == "frozen"

    assert rows["PD Inner LH"]["linked"]["tool"] == [
        {"part_id": tool, "name": "T-0418", "cavities": 1}]
    assert [g["name"] for g in rows["PD Inner LH"]["linked"]["gauge"]] == ["Gauge 40"]
    assert rows["PD Inner RH"]["linked"]["tool"] == []


async def test_master_bom_404_for_unknown_project(client, eng_auth, seed):
    res = await client.get("/api/v1/projects/999999/master-bom", headers=eng_auth)
    assert res.status_code == 404
```

- [ ] **Step 2: Run to see it fail**

Run: `cd backend && python3 -m pytest tests/test_master_bom.py -q`
Expected: 3 failures, all `assert 404 == 200` — the route does not exist yet.

- [ ] **Step 3: Write the service**

`backend/app/services/master_bom_service.py`:
```python
"""Master BOM and tooling board: one composed read per project.

The master BOM is the project's parts seen as a bill of materials. Every
sub-assembly is a group, its current revision's BOM items are the rows, and
the articles that appear in no assembly fall into a trailing "Unassigned"
group. The tooling board is the same article set seen from the other side:
which tool, gauge or piece of assembly equipment is linked to it.

Both reads load the whole project in a fixed number of queries and pick each
part's current revision with RevisionService.pick_active_revision, so the rule
that decides "current" lives in exactly one place and the part page, the
master BOM and the board can never disagree about it.
"""
import logging
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.part import Part, PartBOMItem, PartRelation, PartRevision, RevisionStatus
from app.services.part_service import RevisionService, _enum_value

logger = logging.getLogger(__name__)

# One board covers three kinds of item, because all three are the same shape
# of fact: a relation from the item to the article it serves.
RELATION_KINDS = {
    "tool": "produces",
    "gauge": "checks",
    "assembly_equipment": "assembles",
}

# The six engineering basics the master BOM shows and counts.
ATTRIBUTE_FIELDS = ("material", "weight_g", "box_x_mm", "box_y_mm", "box_z_mm", "finish")

UNASSIGNED_NAME = "Unassigned"

ARTICLE_CATEGORY = "article"

SUB_ASSEMBLY_TYPE = "sub_assembly"


def _attributes(revision: Optional[PartRevision]) -> dict:
    if revision is None:
        return {field: None for field in ATTRIBUTE_FIELDS}
    return {field: getattr(revision, field) for field in ATTRIBUTE_FIELDS}


def _is_complete(row: dict) -> bool:
    return all(row[field] not in (None, "") for field in ATTRIBUTE_FIELDS)


def _is_frozen(revision: Optional[PartRevision]) -> bool:
    return revision is not None and _enum_value(revision.status) == RevisionStatus.FROZEN.value


def _sort_key(part: Part) -> tuple:
    return (part.name or "", part.id)


async def _load_project(session: AsyncSession, project_id: int):
    """Every part of the project, its current revision, and every relation
    touching it — three queries, whatever the project's size."""
    parts = list((await session.execute(
        select(Part).where(Part.project_id == project_id).order_by(Part.name, Part.id)
    )).scalars().all())
    part_ids = [p.id for p in parts]

    revisions = []
    relations = []
    if part_ids:
        revisions = list((await session.execute(
            select(PartRevision).where(PartRevision.part_id.in_(part_ids))
        )).scalars().all())
        relations = list((await session.execute(
            select(PartRelation).where(or_(
                PartRelation.from_part_id.in_(part_ids),
                PartRelation.to_part_id.in_(part_ids),
            )).order_by(PartRelation.id)
        )).scalars().all())

    by_part: dict[int, list[PartRevision]] = {p.id: [] for p in parts}
    for revision in revisions:
        by_part.setdefault(revision.part_id, []).append(revision)
    active = {pid: RevisionService.pick_active_revision(revs) for pid, revs in by_part.items()}
    return parts, active, relations


async def _assembly_items(session: AsyncSession, assemblies, active) -> dict:
    """BOM items of every assembly's current revision, keyed by revision."""
    revision_ids = [active[a.id].id for a in assemblies if active.get(a.id)]
    if not revision_ids:
        return {}
    items = list((await session.execute(
        select(PartBOMItem)
        .where(PartBOMItem.revision_id.in_(revision_ids))
        .order_by(PartBOMItem.position, PartBOMItem.id)
    )).scalars().all())
    by_revision: dict[int, list[PartBOMItem]] = {}
    for item in items:
        by_revision.setdefault(item.revision_id, []).append(item)
    return by_revision


def _mirror_map(relations, by_id: dict) -> dict:
    """A mirror is stored once; both parts have to see it."""
    mirror: dict[int, Part] = {}
    for rel in relations:
        if rel.relation_type != "mirror_of":
            continue
        left, right = by_id.get(rel.from_part_id), by_id.get(rel.to_part_id)
        if left and right:
            mirror[left.id] = right
            mirror[right.id] = left
    return mirror


def _linked_map(relations, by_id: dict) -> dict:
    """Tools, gauges and equipment linked to each article, grouped by kind."""
    kind_by_type = {rel_type: kind for kind, rel_type in RELATION_KINDS.items()}
    linked: dict[int, dict[str, list]] = {}
    for rel in relations:
        kind = kind_by_type.get(rel.relation_type)
        item = by_id.get(rel.from_part_id)
        if kind is None or item is None:
            continue
        entry = {"part_id": item.id, "name": item.name, "cavities": rel.cavities}
        bucket = linked.setdefault(rel.to_part_id, {k: [] for k in RELATION_KINDS})
        bucket[kind].append(entry)
    return linked


def _empty_links() -> dict:
    return {kind: [] for kind in RELATION_KINDS}


async def build_master_bom(session: AsyncSession, project_id: int) -> dict:
    """The project's parts as a BOM grouped by sub-assembly."""
    parts, active, relations = await _load_project(session, project_id)
    by_id = {p.id: p for p in parts}
    mirror = _mirror_map(relations, by_id)
    linked = _linked_map(relations, by_id)

    assemblies = sorted([p for p in parts if p.part_type == SUB_ASSEMBLY_TYPE], key=_sort_key)
    assembly_ids = {a.id for a in assemblies}
    items_by_revision = await _assembly_items(session, assemblies, active)

    def row_for_part(part: Optional[Part], item: Optional[PartBOMItem]) -> dict:
        revision = active.get(part.id) if part else None
        partner = mirror.get(part.id) if part else None
        return {
            "part_id": part.id if part else None,
            "bom_item_id": item.id if item else None,
            "item_number": item.item_number if item else "",
            "quantity": item.quantity if item else 1.0,
            "unit": item.unit if item else "pcs",
            "name": part.name if part else (item.name if item else ""),
            "customer_part_number": part.customer_part_number if part else None,
            "item_category": part.item_category if part else None,
            "part_type": part.part_type if part else None,
            "revision_id": revision.id if revision else None,
            "revision_name": revision.revision_name if revision else None,
            "revision_status": _enum_value(revision.status) if revision else None,
            "frozen": _is_frozen(revision),
            **_attributes(revision),
            "mirror_part_id": partner.id if partner else None,
            "mirror_name": partner.name if partner else None,
            "linked": linked.get(part.id, _empty_links()) if part else _empty_links(),
        }

    groups = []
    in_an_assembly: set[int] = set()
    for assembly in assemblies:
        revision = active.get(assembly.id)
        rows = []
        for item in items_by_revision.get(revision.id, []) if revision else []:
            child = by_id.get(item.child_part_id) if item.child_part_id else None
            if child is not None:
                in_an_assembly.add(child.id)
            rows.append(row_for_part(child, item))
        groups.append({
            "part_id": assembly.id,
            "name": assembly.name,
            "customer_part_number": assembly.customer_part_number,
            "revision_id": revision.id if revision else None,
            "revision_name": revision.revision_name if revision else None,
            "revision_status": _enum_value(revision.status) if revision else None,
            "peak_annual_volume": assembly.peak_annual_volume,
            "lifetime_volume": assembly.lifetime_volume,
            "filled": sum(1 for r in rows if r["part_id"] and _is_complete(r)),
            "total": sum(1 for r in rows if r["part_id"]),
            "rows": rows,
        })

    # Articles that belong to no assembly. Tools, gauges and equipment are
    # never rows; they show up as links on the rows they serve.
    loose = sorted(
        [p for p in parts
         if p.item_category == ARTICLE_CATEGORY
         and p.id not in assembly_ids
         and p.id not in in_an_assembly],
        key=_sort_key,
    )
    loose_rows = [row_for_part(part, None) for part in loose]
    groups.append({
        "part_id": None,
        "name": UNASSIGNED_NAME,
        "customer_part_number": None,
        "revision_id": None,
        "revision_name": None,
        "revision_status": None,
        "peak_annual_volume": None,
        "lifetime_volume": None,
        "filled": sum(1 for r in loose_rows if _is_complete(r)),
        "total": len(loose_rows),
        "rows": loose_rows,
    })

    return {"groups": groups, "relation_kinds": dict(RELATION_KINDS)}
```

- [ ] **Step 4: Write the router**

`backend/app/api/v1/items/project_bom.py`:
```python
"""Project-scoped composed reads: the master BOM and the tooling board.

Both are pure reads over parts, revisions, BOM items and relations, and both
answer a question about a project rather than about one part, so they live
under /v1/projects instead of the parts prefix. Authentication is the same
get_current_user dependency every other item route uses; there is no separate
permission model.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.models.entities import Project
from app.services.master_bom_service import RELATION_KINDS, build_master_bom

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["master-bom"])


async def _require_project(db: AsyncSession, project_id: int) -> Project:
    project = (await db.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.get("/{project_id}/master-bom", response_model=dict)
async def get_master_bom(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The project's parts as a BOM grouped by sub-assembly."""
    await _require_project(db, project_id)
    return await build_master_bom(db, project_id)
```

Register it in `backend/app/api/v1/__init__.py` — import next to the other items imports:
```python
from app.api.v1.items.project_bom import router as project_bom_router
```
and include it next to the other items routers:
```python
api_router.include_router(project_bom_router)
```

- [ ] **Step 5: Run to see it pass**

Run: `cd backend && python3 -m pytest tests/test_master_bom.py -q`
Expected: 12 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/master_bom_service.py backend/app/api/v1/items/project_bom.py backend/app/api/v1/__init__.py backend/tests/test_master_bom.py
git commit -m "feat(bom): composed master BOM read grouped by sub-assembly

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bts9vcERghAQ2cVvRSsFaY"
```

---

### Task 5: `GET /v1/projects/{id}/tooling-board`

**Files:**
- Modify: `backend/app/services/master_bom_service.py` (add `build_tooling_board` at the end)
- Modify: `backend/app/api/v1/items/project_bom.py` (import and second endpoint)
- Test: `backend/tests/test_master_bom.py` (append)

**Interfaces:**
- Produces: `async build_tooling_board(session, project_id, kind) -> dict` with `{"kind", "relation_type", "assemblies": [{part_id, name, customer_part_number, peak_annual_volume, lifetime_volume, articles: [{part_id, name, customer_part_number, weight_g, assigned}]}], "items": [{part_id, name, part_number, supplier, revision_name, revision_status, articles: [{part_id, name, relation_id, cavities}]}], "articles_total", "articles_assigned"}`.
- Produces: `GET /v1/projects/{project_id}/tooling-board?kind=tool|gauge|assembly_equipment` (default `tool`; 400 on any other kind; 404 on an unknown project).
- Consumes: `_load_project`, `_assembly_items`, `RELATION_KINDS` from task 4.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_master_bom.py`:
```python
async def test_tooling_board_per_kind(client, eng_auth, seed):
    project_id = seed["project_id"]

    assembly = await _create_part(client, eng_auth, seed, "SA-5", "Bumper assembly",
                                  part_type="sub_assembly", customer_part_number="3CR853653")
    assembly_rev = await _create_revision(client, eng_auth, assembly)
    res = await client.patch(f"/api/v1/parts/{assembly}/volumes",
                             json={"peak_annual_volume": 41000, "lifetime_volume": 159000},
                             headers=eng_auth)
    assert res.status_code == 200, res.text

    left = await _create_part(client, eng_auth, seed, "A-50", "Bumper LH",
                              customer_part_number="3CR919491")
    left_rev = await _create_revision(client, eng_auth, left)
    await _set_attributes(client, eng_auth, left_rev, weight_g=203.6)
    right = await _create_part(client, eng_auth, seed, "A-51", "Bumper RH")
    await _create_revision(client, eng_auth, right)
    loose = await _create_part(client, eng_auth, seed, "A-52", "Clip 52")
    await _create_revision(client, eng_auth, loose)

    await _add_bom_item(client, eng_auth, assembly, assembly_rev, child_part_id=left)
    await _add_bom_item(client, eng_auth, assembly, assembly_rev, child_part_id=right)

    tool = await _create_part(client, eng_auth, seed, "T-50", "T-0412",
                              part_type="purchased", item_category="tool")
    res = await client.put(f"/api/v1/parts/{tool}", json={"supplier": "Werkzeugbau Nord"},
                           headers=eng_auth)
    assert res.status_code == 200, res.text
    gauge = await _create_part(client, eng_auth, seed, "G-50", "Gauge 50",
                               part_type="purchased", item_category="gauge")

    res = await client.post(f"/api/v1/parts/{tool}/relations",
                            json={"to_part_id": left, "relation_type": "produces", "cavities": 1},
                            headers=eng_auth)
    assert res.status_code == 201, res.text
    res = await client.post(f"/api/v1/parts/{gauge}/relations",
                            json={"to_part_id": right, "relation_type": "checks"},
                            headers=eng_auth)
    assert res.status_code == 201, res.text

    res = await client.get(f"/api/v1/projects/{project_id}/tooling-board?kind=tool",
                           headers=eng_auth)
    assert res.status_code == 200, res.text
    board = res.json()
    assert board["kind"] == "tool" and board["relation_type"] == "produces"

    bumper = next(a for a in board["assemblies"] if a["part_id"] == assembly)
    assert bumper["peak_annual_volume"] == 41000
    assert bumper["customer_part_number"] == "3CR853653"
    assigned = {a["name"]: a["assigned"] for a in bumper["articles"]}
    assert assigned == {"Bumper LH": True, "Bumper RH": False}
    assert next(a for a in bumper["articles"] if a["name"] == "Bumper LH")["weight_g"] == 203.6

    unassigned = board["assemblies"][-1]
    assert unassigned["part_id"] is None and unassigned["name"] == "Unassigned"
    assert [a["name"] for a in unassigned["articles"]] == ["Clip 52"]

    item = next(i for i in board["items"] if i["part_id"] == tool)
    assert item["part_number"] == "T-50"
    assert item["name"] == "T-0412"
    assert item["supplier"] == "Werkzeugbau Nord"
    assert item["revision_status"] is None  # the tool has no revision yet
    assert item["articles"] == [{"part_id": left, "name": "Bumper LH",
                                 "relation_id": item["articles"][0]["relation_id"],
                                 "cavities": 1}]
    assert [i["part_id"] for i in board["items"]] == [tool]
    assert (board["articles_total"], board["articles_assigned"]) == (3, 1)

    res = await client.get(f"/api/v1/projects/{project_id}/tooling-board?kind=gauge",
                           headers=eng_auth)
    gauge_board = res.json()
    assert gauge_board["relation_type"] == "checks"
    assert [i["part_id"] for i in gauge_board["items"]] == [gauge]
    assert [a["name"] for a in gauge_board["items"][0]["articles"]] == ["Bumper RH"]
    assigned = {a["name"]: a["assigned"]
                for grp in gauge_board["assemblies"] for a in grp["articles"]}
    assert assigned == {"Bumper LH": False, "Bumper RH": True, "Clip 52": False}
    assert (gauge_board["articles_total"], gauge_board["articles_assigned"]) == (3, 1)

    res = await client.get(
        f"/api/v1/projects/{project_id}/tooling-board?kind=assembly_equipment",
        headers=eng_auth)
    equipment_board = res.json()
    assert equipment_board["relation_type"] == "assembles"
    assert equipment_board["items"] == []
    assert equipment_board["articles_assigned"] == 0


async def test_tooling_board_rejects_unknown_kind(client, eng_auth, seed):
    res = await client.get(f"/api/v1/projects/{seed['project_id']}/tooling-board?kind=robot",
                           headers=eng_auth)
    assert res.status_code == 400
```

- [ ] **Step 2: Run to see it fail**

Run: `cd backend && python3 -m pytest tests/test_master_bom.py -q`
Expected: 2 failures, `assert 404 == 200` and `assert 404 == 400` — the route does not exist yet.

- [ ] **Step 3: Implement the board**

Append to `backend/app/services/master_bom_service.py`:
```python
async def build_tooling_board(session: AsyncSession, project_id: int, kind: str) -> dict:
    """The project's articles against the items of one kind linked to them.

    The rail (assemblies with their articles) is grouped exactly like the
    master BOM, so a person moving between the two tabs sees the same
    structure. An article counts as assigned once it carries at least one
    relation of the kind's type, however many items link to it.
    """
    relation_type = RELATION_KINDS[kind]
    parts, active, relations = await _load_project(session, project_id)
    by_id = {p.id: p for p in parts}

    assemblies = sorted([p for p in parts if p.part_type == SUB_ASSEMBLY_TYPE], key=_sort_key)
    assembly_ids = {a.id for a in assemblies}
    items_by_revision = await _assembly_items(session, assemblies, active)

    assigned_ids = {rel.to_part_id for rel in relations if rel.relation_type == relation_type}

    def article_entry(part: Part) -> dict:
        revision = active.get(part.id)
        return {
            "part_id": part.id,
            "name": part.name,
            "customer_part_number": part.customer_part_number,
            "weight_g": revision.weight_g if revision else None,
            "assigned": part.id in assigned_ids,
        }

    board_assemblies = []
    in_an_assembly: set[int] = set()
    for assembly in assemblies:
        revision = active.get(assembly.id)
        articles = []
        for item in items_by_revision.get(revision.id, []) if revision else []:
            child = by_id.get(item.child_part_id) if item.child_part_id else None
            if child is None or child.item_category != ARTICLE_CATEGORY:
                continue
            in_an_assembly.add(child.id)
            articles.append(article_entry(child))
        board_assemblies.append({
            "part_id": assembly.id,
            "name": assembly.name,
            "customer_part_number": assembly.customer_part_number,
            "peak_annual_volume": assembly.peak_annual_volume,
            "lifetime_volume": assembly.lifetime_volume,
            "articles": articles,
        })

    loose = sorted(
        [p for p in parts
         if p.item_category == ARTICLE_CATEGORY
         and p.id not in assembly_ids
         and p.id not in in_an_assembly],
        key=_sort_key,
    )
    board_assemblies.append({
        "part_id": None,
        "name": UNASSIGNED_NAME,
        "customer_part_number": None,
        "peak_annual_volume": None,
        "lifetime_volume": None,
        "articles": [article_entry(part) for part in loose],
    })

    board_items = []
    for part in sorted([p for p in parts if p.item_category == kind],
                       key=lambda p: (p.part_number or "", p.id)):
        revision = active.get(part.id)
        linked_articles = []
        for rel in relations:
            if rel.relation_type != relation_type or rel.from_part_id != part.id:
                continue
            target = by_id.get(rel.to_part_id)
            if target is None:
                continue
            linked_articles.append({
                "part_id": target.id,
                "name": target.name,
                "relation_id": rel.id,
                "cavities": rel.cavities,
            })
        linked_articles.sort(key=lambda a: (a["name"], a["part_id"]))
        board_items.append({
            "part_id": part.id,
            "name": part.name,
            "part_number": part.part_number,
            "supplier": part.supplier,
            "revision_name": revision.revision_name if revision else None,
            "revision_status": _enum_value(revision.status) if revision else None,
            "articles": linked_articles,
        })

    rail_ids = {a["part_id"] for group in board_assemblies for a in group["articles"]}
    return {
        "kind": kind,
        "relation_type": relation_type,
        "assemblies": board_assemblies,
        "items": board_items,
        "articles_total": len(rail_ids),
        "articles_assigned": len(rail_ids & assigned_ids),
    }
```

- [ ] **Step 4: Add the endpoint**

In `backend/app/api/v1/items/project_bom.py`, extend the service import:
```python
from app.services.master_bom_service import RELATION_KINDS, build_master_bom, build_tooling_board
```

and append:
```python
@router.get("/{project_id}/tooling-board", response_model=dict)
async def get_tooling_board(
    project_id: int,
    kind: str = Query("tool", description="tool, gauge or assembly_equipment"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The project's articles against the tools, gauges or assembly equipment
    linked to them."""
    if kind not in RELATION_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid kind. Valid: {', '.join(sorted(RELATION_KINDS))}",
        )
    await _require_project(db, project_id)
    return await build_tooling_board(db, project_id, kind)
```

- [ ] **Step 5: Run to see it pass**

Run: `cd backend && python3 -m pytest tests/test_master_bom.py -q`
Expected: 14 passed.

Run: `cd backend && python3 -m pytest tests/test_part_bom.py tests/test_part_relations.py tests/test_item_categories.py -q`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/master_bom_service.py backend/app/api/v1/items/project_bom.py backend/tests/test_master_bom.py
git commit -m "feat(bom): tooling board read for tools, gauges and assembly equipment

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bts9vcERghAQ2cVvRSsFaY"
```

---

### Task 6: Frontend types and API hooks

**Files:**
- Create: `frontend/src/components/bom/types.ts`
- Create: `frontend/src/components/bom/api.ts`
- Test: `frontend/src/components/bom/api.test.tsx`

**Interfaces:**
- Produces (types): `BoardKind`, `MasterBomLink`, `MasterBomRow`, `MasterBomGroup`, `MasterBom`, `BoardArticle`, `BoardAssembly`, `BoardItemArticle`, `BoardItem`, `ToolingBoard`, `AttributeKey`, `ATTRIBUTE_KEYS`.
- Produces (hooks): `useMasterBom(projectId: number)`, `useToolingBoard(projectId: number, kind: BoardKind)`, `useUpdateAttributes(projectId)`, `useUpdateVolumes(projectId)`, `useUpdateCavities(projectId)`, `useCreateRelation(projectId)`, `useDeleteRelation(projectId)`.
- Produces (keys): `masterBomKey(projectId)`, `toolingBoardKey(projectId, kind)`; every mutation invalidates both plus `['parts', projectId]`.
- Consumes: `client` from `../../api/client`, `toast` from `sonner`, `@tanstack/react-query`.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/bom/api.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useMasterBom, useToolingBoard, useUpdateAttributes } from './api';

const calls = vi.hoisted(() => ({ get: [] as string[], patch: [] as [string, unknown][] }));

vi.mock('../../api/client', () => ({
  default: {
    get: vi.fn(async (url: string) => {
      calls.get.push(url);
      if (url.includes('master-bom')) return { data: { groups: [], relation_kinds: {} } };
      return { data: { kind: 'gauge', relation_type: 'checks', assemblies: [], items: [], articles_total: 0, articles_assigned: 0 } };
    }),
    patch: vi.fn(async (url: string, body: unknown) => { calls.patch.push([url, body]); return { data: {} }; }),
    post: vi.fn(async () => ({ data: {} })),
    delete: vi.fn(async () => ({ data: {} })),
  },
  API_BASE_URL: '',
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function Probe() {
  const bom = useMasterBom(12);
  const board = useToolingBoard(12, 'gauge');
  const save = useUpdateAttributes(12);
  return (
    <div>
      <span data-testid="ready">{bom.data && board.data ? 'ready' : 'loading'}</span>
      <button onClick={() => save.mutate({ revisionId: 51, values: { weight_g: 203.6 } })}>save</button>
    </div>
  );
}

describe('bom api hooks', () => {
  beforeEach(() => { calls.get.length = 0; calls.patch.length = 0; });

  it('reads both project endpoints and patches revision attributes', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={qc}><Probe /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('ready'));
    expect(calls.get).toContain('/v1/projects/12/master-bom');
    expect(calls.get).toContain('/v1/projects/12/tooling-board?kind=gauge');

    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    await waitFor(() => expect(calls.patch).toEqual([
      ['/v1/parts/revisions/51/attributes', { weight_g: 203.6 }],
    ]));
    cleanup();
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `cd frontend && npx vitest run src/components/bom/api.test.tsx`
Expected: `Failed to resolve import "./api"`.

- [ ] **Step 3: Write the types**

`frontend/src/components/bom/types.ts`:
```ts
/**
 * Master BOM and tooling board response shapes.
 *
 * Mirrors backend/app/services/master_bom_service.py: one composed read per
 * view, so the components never assemble a picture out of several endpoints.
 */

export type BoardKind = 'tool' | 'gauge' | 'assembly_equipment';

export const ATTRIBUTE_KEYS = ['material', 'weight_g', 'box_x_mm', 'box_y_mm', 'box_z_mm', 'finish'] as const;
export type AttributeKey = (typeof ATTRIBUTE_KEYS)[number];

export interface MasterBomLink {
  part_id: number;
  name: string;
  cavities: number | null;
}

export interface MasterBomRow {
  part_id: number | null;
  bom_item_id: number | null;
  item_number: string;
  quantity: number;
  unit: string;
  name: string;
  customer_part_number: string | null;
  item_category: string | null;
  part_type: string | null;
  revision_id: number | null;
  revision_name: string | null;
  revision_status: string | null;
  frozen: boolean;
  material: string | null;
  weight_g: number | null;
  box_x_mm: number | null;
  box_y_mm: number | null;
  box_z_mm: number | null;
  finish: string | null;
  mirror_part_id: number | null;
  mirror_name: string | null;
  linked: Record<BoardKind, MasterBomLink[]>;
}

export interface MasterBomGroup {
  part_id: number | null;
  name: string;
  customer_part_number: string | null;
  revision_id: number | null;
  revision_name: string | null;
  revision_status: string | null;
  peak_annual_volume: number | null;
  lifetime_volume: number | null;
  filled: number;
  total: number;
  rows: MasterBomRow[];
}

export interface MasterBom {
  groups: MasterBomGroup[];
  relation_kinds: Record<string, string>;
}

export interface BoardArticle {
  part_id: number;
  name: string;
  customer_part_number: string | null;
  weight_g: number | null;
  assigned: boolean;
}

export interface BoardAssembly {
  part_id: number | null;
  name: string;
  customer_part_number: string | null;
  peak_annual_volume: number | null;
  lifetime_volume: number | null;
  articles: BoardArticle[];
}

export interface BoardItemArticle {
  part_id: number;
  name: string;
  relation_id: number;
  cavities: number | null;
}

export interface BoardItem {
  part_id: number;
  name: string;
  part_number: string;
  supplier: string | null;
  revision_name: string | null;
  revision_status: string | null;
  articles: BoardItemArticle[];
}

export interface ToolingBoard {
  kind: BoardKind;
  relation_type: string;
  assemblies: BoardAssembly[];
  items: BoardItem[];
  articles_total: number;
  articles_assigned: number;
}

export const BOARD_KIND_LABELS: Record<BoardKind, string> = {
  tool: 'Tools',
  gauge: 'Gauges',
  assembly_equipment: 'Assembly equipment',
};
```

- [ ] **Step 4: Write the hooks**

`frontend/src/components/bom/api.ts`:
```ts
/**
 * Queries and mutations behind the master BOM and the tooling board.
 *
 * Every write touches data both views show, so each mutation invalidates both
 * queries plus the project's part list rather than leaving each caller to
 * remember.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import type { AttributeKey, BoardKind, MasterBom, ToolingBoard } from './types';

export const masterBomKey = (projectId: number) => ['master-bom', projectId] as const;
export const toolingBoardKey = (projectId: number, kind: BoardKind) =>
  ['tooling-board', projectId, kind] as const;

export function useMasterBom(projectId: number) {
  return useQuery<MasterBom>({
    queryKey: masterBomKey(projectId),
    queryFn: async () => (await client.get(`/v1/projects/${projectId}/master-bom`)).data,
    enabled: !!projectId,
  });
}

export function useToolingBoard(projectId: number, kind: BoardKind) {
  return useQuery<ToolingBoard>({
    queryKey: toolingBoardKey(projectId, kind),
    queryFn: async () =>
      (await client.get(`/v1/projects/${projectId}/tooling-board?kind=${kind}`)).data,
    enabled: !!projectId,
  });
}

function useBomInvalidation(projectId: number) {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: ['master-bom', projectId] });
    queryClient.invalidateQueries({ queryKey: ['tooling-board', projectId] });
    queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
    queryClient.invalidateQueries({ queryKey: ['part-relations'] });
  };
}

export type AttributeValues = Partial<Record<AttributeKey, string | number | null>>;

export function useUpdateAttributes(projectId: number) {
  const invalidate = useBomInvalidation(projectId);
  return useMutation({
    mutationFn: async ({ revisionId, values }: { revisionId: number; values: AttributeValues }) => {
      await client.patch(`/v1/parts/revisions/${revisionId}/attributes`, values);
    },
    onSuccess: invalidate,
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to save');
      invalidate();
    },
  });
}

export function useUpdateVolumes(projectId: number) {
  const invalidate = useBomInvalidation(projectId);
  return useMutation({
    mutationFn: async ({ partId, values }: {
      partId: number;
      values: { peak_annual_volume?: number | null; lifetime_volume?: number | null };
    }) => {
      await client.patch(`/v1/parts/${partId}/volumes`, values);
    },
    onSuccess: invalidate,
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to save volumes');
      invalidate();
    },
  });
}

export function useUpdateCavities(projectId: number) {
  const invalidate = useBomInvalidation(projectId);
  return useMutation({
    mutationFn: async ({ relationId, cavities }: { relationId: number; cavities: number | null }) => {
      await client.patch(`/v1/parts/relations/${relationId}`, { cavities });
    },
    onSuccess: invalidate,
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to save cavities');
      invalidate();
    },
  });
}

export function useCreateRelation(projectId: number) {
  const invalidate = useBomInvalidation(projectId);
  return useMutation({
    mutationFn: async ({ fromPartId, toPartId, relationType }: {
      fromPartId: number; toPartId: number; relationType: string;
    }) => {
      await client.post(`/v1/parts/${fromPartId}/relations`, {
        to_part_id: toPartId,
        relation_type: relationType,
      });
    },
    onSuccess: () => {
      toast.success('Article assigned');
      invalidate();
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to assign article');
      invalidate();
    },
  });
}

export function useDeleteRelation(projectId: number) {
  const invalidate = useBomInvalidation(projectId);
  return useMutation({
    mutationFn: async (relationId: number) => {
      await client.delete(`/v1/parts/relations/${relationId}`);
    },
    onSuccess: () => {
      toast.success('Article removed');
      invalidate();
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to remove article');
      invalidate();
    },
  });
}
```

- [ ] **Step 5: Run to see it pass**

Run: `cd frontend && npx vitest run src/components/bom/api.test.tsx`
Expected: 1 passed.

Run: `cd frontend && npx tsc --noEmit -p .`
Expected: no output (0 errors).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/bom/types.ts frontend/src/components/bom/api.ts frontend/src/components/bom/api.test.tsx
git commit -m "feat(bom): frontend types and query hooks for master BOM and board

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bts9vcERghAQ2cVvRSsFaY"
```

---

### Task 7: `MasterBomSection`

**Files:**
- Create: `frontend/src/components/bom/MasterBomSection.tsx`
- Test: `frontend/src/components/bom/MasterBomSection.test.tsx`

**Interfaces:**
- Produces: `export default function MasterBomSection(props: { projectId: number; selectedPartId: number | null; onSelectPart: (partId: number) => void; onContextMenu?: (e: React.MouseEvent, partId: number) => void; onAddPart: (partType: 'purchased' | 'sub_assembly') => void })`.
- Consumes: `useMasterBom`, `useUpdateAttributes`, `useUpdateVolumes` from `./api`; `MasterBomGroup`, `MasterBomRow`, `AttributeKey`, `BoardKind` from `./types`.
- Behaviour pinned by tests: a row whose attribute is empty renders `data-missing="true"` on that cell; a frozen row renders no `<input>` and carries `title="Frozen revision"`; a group header shows `filled/total`; blurring a changed cell PATCHes the revision; the column picker persists to `localStorage` under `plm2.masterBom.columns`.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/bom/MasterBomSection.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import MasterBomSection from './MasterBomSection';

const patchCalls = vi.hoisted(() => [] as [string, unknown][]);

const MASTER_BOM = {
  relation_kinds: { tool: 'produces', gauge: 'checks', assembly_equipment: 'assembles' },
  groups: [
    {
      part_id: 12, name: 'Cover assembly LHD', customer_part_number: '9656732',
      revision_id: 40, revision_name: 'ENG1', revision_status: 'in_progress',
      peak_annual_volume: 41000, lifetime_volume: 159000, filled: 1, total: 2,
      rows: [
        {
          part_id: 15, bom_item_id: 77, item_number: '10', quantity: 1, unit: 'pcs',
          name: 'Cover SHUD LHD', customer_part_number: '9656733', item_category: 'article',
          part_type: 'internal_mfg', revision_id: 51, revision_name: 'ENG1',
          revision_status: 'in_progress', frozen: false,
          material: 'PC/ABS', weight_g: 203.6, box_x_mm: 401.8, box_y_mm: 338, box_z_mm: 27.64,
          finish: 'Feinnarbe L', mirror_part_id: 16, mirror_name: 'Cover SHUD RHD',
          linked: { tool: [{ part_id: 30, name: 'T-0412', cavities: 1 }], gauge: [], assembly_equipment: [] },
        },
        {
          part_id: 16, bom_item_id: 78, item_number: '20', quantity: 1, unit: 'pcs',
          name: 'Cover SHUD RHD', customer_part_number: null, item_category: 'article',
          part_type: 'internal_mfg', revision_id: 52, revision_name: 'IND1',
          revision_status: 'frozen', frozen: true,
          material: null, weight_g: null, box_x_mm: null, box_y_mm: null, box_z_mm: null,
          finish: null, mirror_part_id: 15, mirror_name: 'Cover SHUD LHD',
          linked: { tool: [], gauge: [], assembly_equipment: [] },
        },
      ],
    },
    {
      part_id: null, name: 'Unassigned', customer_part_number: null, revision_id: null,
      revision_name: null, revision_status: null, peak_annual_volume: null,
      lifetime_volume: null, filled: 0, total: 1,
      rows: [{
        part_id: 20, bom_item_id: null, item_number: '', quantity: 1, unit: 'pcs',
        name: 'Clip', customer_part_number: null, item_category: 'article',
        part_type: 'purchased', revision_id: 60, revision_name: 'RFQ1',
        revision_status: 'in_progress', frozen: false,
        material: null, weight_g: null, box_x_mm: null, box_y_mm: null, box_z_mm: null,
        finish: null, mirror_part_id: null, mirror_name: null,
        linked: { tool: [], gauge: [], assembly_equipment: [] },
      }],
    },
  ],
};

vi.mock('../../api/client', () => ({
  default: {
    get: vi.fn(async () => ({ data: MASTER_BOM })),
    patch: vi.fn(async (url: string, body: unknown) => { patchCalls.push([url, body]); return { data: {} }; }),
    post: vi.fn(async () => ({ data: {} })),
    delete: vi.fn(async () => ({ data: {} })),
  },
  API_BASE_URL: '',
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderSection(onSelectPart = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MasterBomSection projectId={12} selectedPartId={null} onSelectPart={onSelectPart} onAddPart={vi.fn()} />
    </QueryClientProvider>
  );
  return onSelectPart;
}

describe('MasterBomSection', () => {
  beforeEach(() => { patchCalls.length = 0; localStorage.clear(); });

  it('renders groups, rows, completeness and missing cells', async () => {
    renderSection();
    await waitFor(() => expect(screen.getByText('Cover assembly LHD')).toBeTruthy());
    expect(screen.getByText('9656732')).toBeTruthy();
    expect(screen.getByText('1/2 complete')).toBeTruthy();
    expect(screen.getByText('Unassigned')).toBeTruthy();
    expect(screen.getByText('Clip')).toBeTruthy();

    const filled = screen.getByTestId('cell-15-material');
    expect(filled.getAttribute('data-missing')).toBe('false');
    expect(within(filled).getByRole('textbox').getAttribute('value')).toBe('PC/ABS');

    const missing = screen.getByTestId('cell-20-material');
    expect(missing.getAttribute('data-missing')).toBe('true');
    cleanup();
  });

  it('keeps a frozen row read-only', async () => {
    renderSection();
    const cell = await screen.findByTestId('cell-16-material');
    expect(cell.querySelector('input')).toBeNull();
    expect(cell.getAttribute('title')).toBe('Frozen revision');
    cleanup();
  });

  it('saves an edited cell on blur', async () => {
    renderSection();
    const input = within(await screen.findByTestId('cell-15-weight_g')).getByRole('spinbutton');
    fireEvent.change(input, { target: { value: '210.5' } });
    fireEvent.blur(input);
    await waitFor(() => expect(patchCalls).toEqual([
      ['/v1/parts/revisions/51/attributes', { weight_g: 210.5 }],
    ]));
    cleanup();
  });

  it('saves an assembly volume on blur', async () => {
    renderSection();
    const input = within(await screen.findByTestId('volume-12-peak_annual_volume')).getByRole('spinbutton');
    fireEvent.change(input, { target: { value: '42000' } });
    fireEvent.blur(input);
    await waitFor(() => expect(patchCalls).toEqual([
      ['/v1/parts/12/volumes', { peak_annual_volume: 42000 }],
    ]));
    cleanup();
  });

  it('selects a part when its name is clicked and follows a mirror badge', async () => {
    const onSelectPart = renderSection();
    fireEvent.click(await screen.findByRole('button', { name: 'Cover SHUD LHD' }));
    expect(onSelectPart).toHaveBeenCalledWith(15);
    fireEvent.click(screen.getByTitle('Mirror of Cover SHUD RHD'));
    expect(onSelectPart).toHaveBeenCalledWith(16);
    cleanup();
  });

  it('hides a column through the picker and remembers it', async () => {
    renderSection();
    fireEvent.click(await screen.findByRole('button', { name: /columns/i }));
    fireEvent.click(screen.getByLabelText('Finish'));
    await waitFor(() => expect(screen.queryByTestId('cell-15-finish')).toBeNull());
    expect(JSON.parse(localStorage.getItem('plm2.masterBom.columns') || '{}').finish).toBe(false);
    cleanup();
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `cd frontend && npx vitest run src/components/bom/MasterBomSection.test.tsx`
Expected: `Failed to resolve import "./MasterBomSection"`.

- [ ] **Step 3: Write the component**

`frontend/src/components/bom/MasterBomSection.tsx`:
```tsx
/**
 * MasterBomSection - the project's parts as a bill of materials grouped by
 * sub-assembly, with the six engineering basics editable in place.
 *
 * This replaces the flat parts tree on the project page. Selection is still
 * owned by the page, so the part detail panel keeps working exactly as it did
 * under the tree.
 */
import { useEffect, useState } from 'react';
import type { AttributeKey, BoardKind, MasterBomGroup, MasterBomRow } from './types';
import { useMasterBom, useUpdateAttributes, useUpdateVolumes } from './api';

const COLUMN_STORAGE_KEY = 'plm2.masterBom.columns';

const OPTIONAL_COLUMNS = [
  { key: 'material', label: 'Material' },
  { key: 'weight', label: 'Weight' },
  { key: 'box', label: 'Box' },
  { key: 'finish', label: 'Finish' },
  { key: 'links', label: 'Links' },
] as const;
type ColumnKey = (typeof OPTIONAL_COLUMNS)[number]['key'];
type ColumnState = Record<ColumnKey, boolean>;

const ALL_COLUMNS: ColumnState = { material: true, weight: true, box: true, finish: true, links: true };

const NUMERIC_ATTRIBUTES: AttributeKey[] = ['weight_g', 'box_x_mm', 'box_y_mm', 'box_z_mm'];

const CELL = 'w-full rounded-md bg-slate-900 border border-slate-700/80 px-2 py-1.5 text-sm text-slate-100 ' +
  'hover:border-slate-600 transition-colors duration-150';
const CELL_MISSING = 'w-full rounded-md bg-amber-500/5 border border-amber-500/40 px-2 py-1.5 text-sm text-slate-100 ' +
  'hover:border-amber-400 transition-colors duration-150';
const READ_ONLY = 'min-h-[2.125rem] px-2 py-1.5 rounded-md text-sm bg-slate-800/40 text-slate-400 tabular-nums';
const BTN = 'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors duration-150';

function loadColumns(): ColumnState {
  try {
    const raw = localStorage.getItem(COLUMN_STORAGE_KEY);
    return raw ? { ...ALL_COLUMNS, ...JSON.parse(raw) } : ALL_COLUMNS;
  } catch {
    return ALL_COLUMNS;
  }
}

function storeColumns(next: ColumnState) {
  try {
    localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* a browser refusing storage must not break the table */
  }
}

/** A category glyph stands in for the CAD thumbnail PLM2 does not render yet. */
function CategoryGlyph({ category }: { category: string | null }) {
  const paths: Record<string, string> = {
    article: 'M4 3h9l4 4v14H4z',
    tool: 'M4 20l7-7m0 0a4 4 0 105-5l-2 2-2-2 2-2a4 4 0 10-5 5z',
    gauge: 'M3 12a9 9 0 1118 0M12 12l5-3',
    assembly_equipment: 'M4 20V9l8-5 8 5v11',
  };
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 text-slate-500" fill="none"
      stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d={paths[category ?? 'article'] ?? paths.article} />
    </svg>
  );
}

function StatusChip({ name, status }: { name: string | null; status: string | null }) {
  if (!name) return <span className="text-slate-600 text-xs">no revision</span>;
  const tone = status === 'frozen'
    ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
    : status === 'rejected' || status === 'cancelled'
      ? 'bg-rose-500/10 text-rose-300 border-rose-500/30'
      : 'bg-sky-500/10 text-sky-300 border-sky-500/30';
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${tone}`}>
      <span className="font-mono">{name}</span>
      <span className="text-slate-400">{(status ?? '').replace(/_/g, ' ')}</span>
    </span>
  );
}

function LinkCount({ kind, count }: { kind: BoardKind; count: number }) {
  const label: Record<BoardKind, string> = { tool: 'tools', gauge: 'gauges', assembly_equipment: 'equipment' };
  return (
    <span className={`inline-flex items-center gap-1 text-xs tabular-nums ${count ? 'text-slate-300' : 'text-slate-600'}`}
      title={`${count} ${label[kind]}`}>
      <CategoryGlyph category={kind} />
      {count}
    </span>
  );
}

function AttributeCell({ row, field, onSave }: {
  row: MasterBomRow;
  field: AttributeKey;
  onSave: (field: AttributeKey, raw: string) => void;
}) {
  const stored = row[field];
  const initial = stored === null || stored === undefined ? '' : String(stored);
  const [value, setValue] = useState(initial);
  useEffect(() => { setValue(initial); }, [initial]);

  const missing = initial === '';
  const editable = !row.frozen && !!row.revision_id;
  const numeric = NUMERIC_ATTRIBUTES.includes(field);

  if (!editable) {
    return (
      <div data-testid={`cell-${row.part_id}-${field}`} data-missing={String(missing)}
        title={row.frozen ? 'Frozen revision' : undefined}
        className={`${READ_ONLY} ${missing ? 'border border-amber-500/25' : ''}`}>
        {initial || '—'}
      </div>
    );
  }

  return (
    <div data-testid={`cell-${row.part_id}-${field}`} data-missing={String(missing)}>
      <input
        className={`${missing ? CELL_MISSING : CELL} ${numeric ? 'font-mono tabular-nums' : ''}`}
        type={numeric ? 'number' : 'text'}
        step={numeric ? 'any' : undefined}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => { if (value !== initial) onSave(field, value); }}
      />
    </div>
  );
}

function VolumeCell({ group, field, onSave }: {
  group: MasterBomGroup;
  field: 'peak_annual_volume' | 'lifetime_volume';
  onSave: (field: 'peak_annual_volume' | 'lifetime_volume', raw: string) => void;
}) {
  const stored = group[field];
  const initial = stored === null || stored === undefined ? '' : String(stored);
  const [value, setValue] = useState(initial);
  useEffect(() => { setValue(initial); }, [initial]);
  const label = field === 'peak_annual_volume' ? 'Peak/year' : 'Lifetime';
  return (
    <label data-testid={`volume-${group.part_id}-${field}`} className="flex items-center gap-1.5 text-xs text-slate-400">
      {label}
      <input
        className="w-24 rounded-md bg-slate-900 border border-slate-700 px-2 py-1 text-sm text-slate-100 font-mono tabular-nums"
        type="number"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => { if (value !== initial) onSave(field, value); }}
      />
    </label>
  );
}

interface Props {
  projectId: number;
  selectedPartId: number | null;
  onSelectPart: (partId: number) => void;
  onContextMenu?: (e: React.MouseEvent, partId: number) => void;
  onAddPart: (partType: 'purchased' | 'sub_assembly') => void;
}

export default function MasterBomSection({ projectId, selectedPartId, onSelectPart, onContextMenu, onAddPart }: Props) {
  const { data, isLoading } = useMasterBom(projectId);
  const updateAttributes = useUpdateAttributes(projectId);
  const updateVolumes = useUpdateVolumes(projectId);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [columns, setColumns] = useState<ColumnState>(loadColumns);
  const [showColumnPicker, setShowColumnPicker] = useState(false);

  const toggleColumn = (key: ColumnKey) => {
    const next = { ...columns, [key]: !columns[key] };
    setColumns(next);
    storeColumns(next);
  };

  const saveAttribute = (row: MasterBomRow) => (field: AttributeKey, raw: string) => {
    if (!row.revision_id) return;
    const numeric = NUMERIC_ATTRIBUTES.includes(field);
    const value = raw === '' ? null : numeric ? Number(raw) : raw;
    if (numeric && value !== null && Number.isNaN(value as number)) return;
    updateAttributes.mutate({ revisionId: row.revision_id, values: { [field]: value } });
  };

  const saveVolume = (group: MasterBomGroup) =>
    (field: 'peak_annual_volume' | 'lifetime_volume', raw: string) => {
      if (!group.part_id) return;
      const value = raw === '' ? null : Number(raw);
      if (value !== null && Number.isNaN(value)) return;
      updateVolumes.mutate({ partId: group.part_id, values: { [field]: value } });
    };

  if (isLoading) {
    return (
      <div className="rounded-lg border border-slate-700/70 bg-slate-800 p-4 shadow-panel space-y-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-8 rounded bg-slate-700/40 animate-pulse" />
        ))}
      </div>
    );
  }

  const groups = data?.groups ?? [];
  const hasRows = groups.some((g) => g.rows.length > 0);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Master BOM</h2>
        <div className="flex items-center gap-2">
          <div className="relative">
            <button onClick={() => setShowColumnPicker((v) => !v)}
              className={`${BTN} border border-slate-600 text-slate-200 hover:bg-slate-700/60`}>
              Columns
            </button>
            {showColumnPicker && (
              <div className="absolute right-0 z-20 mt-1 w-48 rounded-lg border border-slate-700/70 bg-slate-800 p-2 shadow-panel">
                {OPTIONAL_COLUMNS.map((col) => (
                  <label key={col.key} className="flex items-center gap-2 px-1 py-1 text-sm text-slate-200">
                    <input type="checkbox" aria-label={col.label} checked={columns[col.key]}
                      onChange={() => toggleColumn(col.key)}
                      className="h-4 w-4 rounded border-slate-600 bg-slate-900 accent-sky-500" />
                    {col.label}
                  </label>
                ))}
              </div>
            )}
          </div>
          <button onClick={() => onAddPart('purchased')}
            className={`${BTN} border border-slate-600 text-slate-200 hover:bg-slate-700/60`}>
            Add part
          </button>
          <button onClick={() => onAddPart('sub_assembly')}
            className={`${BTN} bg-sky-600 text-white hover:bg-sky-500 shadow-panel`}>
            Add assembly
          </button>
        </div>
      </div>

      {!hasRows && (
        <div className="rounded-lg border border-dashed border-slate-700 p-8 text-center">
          <p className="text-sm text-slate-400">This project has no parts yet.</p>
          <div className="mt-3 flex items-center justify-center gap-2">
            <button onClick={() => onAddPart('sub_assembly')}
              className={`${BTN} bg-sky-600 text-white hover:bg-sky-500`}>Add assembly</button>
            <button onClick={() => onAddPart('purchased')}
              className={`${BTN} border border-slate-600 text-slate-200 hover:bg-slate-700/60`}>Add part</button>
          </div>
        </div>
      )}

      {groups.filter((g) => g.rows.length > 0 || g.part_id !== null).map((group) => {
        const key = String(group.part_id ?? 'unassigned');
        const isCollapsed = collapsed[key];
        return (
          <section key={key} className="rounded-lg border border-slate-700/70 bg-slate-800 shadow-panel">
            <header className="flex flex-wrap items-center gap-3 border-b border-slate-700/70 px-4 py-3">
              <button onClick={() => setCollapsed({ ...collapsed, [key]: !isCollapsed })}
                className="text-slate-400 hover:text-slate-200" title={isCollapsed ? 'Expand' : 'Collapse'}>
                <svg viewBox="0 0 24 24" className={`h-4 w-4 transition-transform ${isCollapsed ? '' : 'rotate-90'}`}
                  fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M9 5l7 7-7 7" />
                </svg>
              </button>
              {group.part_id ? (
                <button onClick={() => onSelectPart(group.part_id as number)}
                  className="text-base font-semibold text-slate-100 hover:text-sky-300">{group.name}</button>
              ) : (
                <span className="text-base font-semibold text-slate-300">{group.name}</span>
              )}
              {group.customer_part_number && (
                <span className="font-mono text-xs text-slate-400">{group.customer_part_number}</span>
              )}
              <StatusChip name={group.revision_name} status={group.revision_status} />
              <span className="text-xs text-slate-500 tabular-nums">{group.rows.length} rows</span>
              <span className={`rounded-full border px-2 py-0.5 text-[11px] tabular-nums ${
                group.total > 0 && group.filled === group.total
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                  : 'border-amber-500/30 bg-amber-500/10 text-amber-300'}`}>
                {group.filled}/{group.total} complete
              </span>
              {group.part_id && (
                <div className="ml-auto flex items-center gap-3">
                  <VolumeCell group={group} field="peak_annual_volume" onSave={saveVolume(group)} />
                  <VolumeCell group={group} field="lifetime_volume" onSave={saveVolume(group)} />
                </div>
              )}
            </header>

            {!isCollapsed && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                      <th className="w-8 px-3 py-2" />
                      <th className="px-2 py-2">Name</th>
                      <th className="px-2 py-2">Customer no.</th>
                      <th className="px-2 py-2">Category</th>
                      <th className="px-2 py-2">Revision</th>
                      {columns.material && <th className="px-2 py-2">Material</th>}
                      {columns.weight && <th className="px-2 py-2">Weight (g)</th>}
                      {columns.box && <th className="px-2 py-2">Box (mm)</th>}
                      {columns.finish && <th className="px-2 py-2">Finish</th>}
                      {columns.links && <th className="px-2 py-2">Links</th>}
                      <th className="px-2 py-2">Mirror</th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.rows.map((row) => (
                      <tr key={row.bom_item_id ?? `p${row.part_id}`}
                        onContextMenu={(e) => { if (row.part_id && onContextMenu) onContextMenu(e, row.part_id); }}
                        className={`border-t border-slate-700/50 align-middle ${
                          row.part_id === selectedPartId ? 'bg-sky-500/5' : ''}`}>
                        <td className="px-3 py-1.5"><CategoryGlyph category={row.item_category} /></td>
                        <td className="px-2 py-1.5">
                          {row.part_id ? (
                            <button onClick={() => onSelectPart(row.part_id as number)}
                              className="text-left text-slate-100 hover:text-sky-300">{row.name}</button>
                          ) : (
                            <span className="text-slate-400">{row.name}</span>
                          )}
                          <span className="ml-2 font-mono text-[11px] text-slate-600 tabular-nums">
                            {row.item_number}
                          </span>
                        </td>
                        <td className="px-2 py-1.5 font-mono text-xs text-slate-400">
                          {row.customer_part_number ?? '—'}
                        </td>
                        <td className="px-2 py-1.5 text-xs text-slate-400">
                          {(row.item_category ?? 'free text').replace(/_/g, ' ')}
                        </td>
                        <td className="px-2 py-1.5">
                          <StatusChip name={row.revision_name} status={row.revision_status} />
                        </td>
                        {columns.material && (
                          <td className="px-2 py-1.5 min-w-[9rem]">
                            <AttributeCell row={row} field="material" onSave={saveAttribute(row)} />
                          </td>
                        )}
                        {columns.weight && (
                          <td className="px-2 py-1.5 min-w-[6rem]">
                            <AttributeCell row={row} field="weight_g" onSave={saveAttribute(row)} />
                          </td>
                        )}
                        {columns.box && (
                          <td className="px-2 py-1.5">
                            <div className="flex items-center gap-1">
                              <AttributeCell row={row} field="box_x_mm" onSave={saveAttribute(row)} />
                              <AttributeCell row={row} field="box_y_mm" onSave={saveAttribute(row)} />
                              <AttributeCell row={row} field="box_z_mm" onSave={saveAttribute(row)} />
                            </div>
                          </td>
                        )}
                        {columns.finish && (
                          <td className="px-2 py-1.5 min-w-[10rem]">
                            <AttributeCell row={row} field="finish" onSave={saveAttribute(row)} />
                          </td>
                        )}
                        {columns.links && (
                          <td className="px-2 py-1.5">
                            <div className="flex items-center gap-2">
                              <LinkCount kind="tool" count={row.linked.tool.length} />
                              <LinkCount kind="gauge" count={row.linked.gauge.length} />
                              <LinkCount kind="assembly_equipment" count={row.linked.assembly_equipment.length} />
                            </div>
                          </td>
                        )}
                        <td className="px-2 py-1.5">
                          {row.mirror_part_id ? (
                            <button title={`Mirror of ${row.mirror_name}`}
                              onClick={() => onSelectPart(row.mirror_part_id as number)}
                              className="rounded-full border border-slate-600 px-2 py-0.5 text-[11px] text-slate-300 hover:border-sky-500 hover:text-sky-300">
                              mirror
                            </button>
                          ) : (
                            <span className="text-slate-700">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {group.rows.length === 0 && (
                      <tr><td colSpan={11} className="px-4 py-3 text-sm text-slate-500">No rows</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run to see it pass**

Run: `cd frontend && npx vitest run src/components/bom/MasterBomSection.test.tsx`
Expected: 6 passed.

Run: `cd frontend && npx tsc --noEmit -p .`
Expected: no output (0 errors).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/bom/MasterBomSection.tsx frontend/src/components/bom/MasterBomSection.test.tsx
git commit -m "feat(bom): master BOM section with inline attribute editing

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bts9vcERghAQ2cVvRSsFaY"
```

---

### Task 8: Project page integration and the relations section

**Files:**
- Modify: `frontend/src/components/PartRelationsSection.tsx` (relation type options, cavities on `produces`)
- Create: `frontend/src/components/PartRelationsSection.test.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` — remove `interface TreeNode` (lines 71-74), `toolNumber` / `comparePartNodes` / `buildPartTree` with their comments (lines 158-217), `getDescendantIds` and `TreeNodeComponent` with their comments (lines 379-523), the drag/filter state (lines 910-912), `reparentMutation` / `handleDropOnPart` / `invalidDropIds` (lines 961-986), `const partTree = ...` (line 1021) and the whole "Left: Parts Tree" column (lines 1083-1159); replace the two-column grid with a stacked layout carrying `MasterBomSection`.

**Interfaces:**
- Consumes: `MasterBomSection` from `../components/bom/MasterBomSection`.
- Produces: `PartRelationsSection` gains a `Mirror of` option in the type select and, when the type is `produces`, a `cavities` number input sent with the create call.
- Kept working: `selectedPartId` state and the `?part=` deep link, the right-hand detail panel with all its sections, `ContextMenuComponent` (now opened by right-clicking a master BOM row), `ChangelogModal`, `AddPartModal`, `markCalibratedMutation`, `createRfqMutation`.
- Removed on purpose: drag-and-drop reparenting and the category filter chips. Assembly membership is edited in the assembly's BOM section, which is how the spec wants it; note this in the task-10 spec touch-up.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/PartRelationsSection.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import PartRelationsSection from './PartRelationsSection';

const posts = vi.hoisted(() => [] as [string, unknown][]);

vi.mock('../api/client', () => ({
  default: {
    get: vi.fn(async () => ({ data: [] })),
    post: vi.fn(async (url: string, body: unknown) => { posts.push([url, body]); return { data: {} }; }),
    patch: vi.fn(async () => ({ data: {} })),
    delete: vi.fn(async () => ({ data: {} })),
  },
  API_BASE_URL: '',
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const PARTS = [
  { id: 15, part_number: 'A-30', name: 'Cover LH', item_category: 'article' },
  { id: 16, part_number: 'A-31', name: 'Cover RH', item_category: 'article' },
];

function renderSection(itemCategory: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <PartRelationsSection partId={30} itemCategory={itemCategory} projectParts={PARTS} />
    </QueryClientProvider>
  );
}

describe('PartRelationsSection', () => {
  beforeEach(() => { posts.length = 0; });

  it('creates a mirror relation', async () => {
    renderSection('article');
    fireEvent.click(await screen.findByRole('button', { name: /link item/i }));
    fireEvent.change(screen.getByLabelText('Relation type'), { target: { value: 'mirror_of' } });
    fireEvent.change(screen.getByLabelText('Linked item'), { target: { value: '16' } });
    fireEvent.click(screen.getByRole('button', { name: /^link$/i }));
    await waitFor(() => expect(posts).toEqual([
      ['/v1/parts/30/relations', { to_part_id: 16, relation_type: 'mirror_of', cavities: null }],
    ]));
    cleanup();
  });

  it('sends cavities with a produces relation only', async () => {
    renderSection('tool');
    fireEvent.click(await screen.findByRole('button', { name: /link item/i }));
    expect((screen.getByLabelText('Relation type') as HTMLSelectElement).value).toBe('produces');
    fireEvent.change(screen.getByLabelText('Cavities'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Linked item'), { target: { value: '15' } });
    fireEvent.click(screen.getByRole('button', { name: /^link$/i }));
    await waitFor(() => expect(posts).toEqual([
      ['/v1/parts/30/relations', { to_part_id: 15, relation_type: 'produces', cavities: 2 }],
    ]));

    fireEvent.change(screen.getByLabelText('Relation type'), { target: { value: 'checks' } });
    expect(screen.queryByLabelText('Cavities')).toBeNull();
    cleanup();
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `cd frontend && npx vitest run src/components/PartRelationsSection.test.tsx`
Expected: `Unable to find a label with the text of: Relation type` — the selects carry no accessible name, there is no mirror option and no cavities input.

- [ ] **Step 3: Extend `PartRelationsSection`**

In `frontend/src/components/PartRelationsSection.tsx`, extend the `Relation` interface with the new field:
```tsx
  notes: string | null;
  cavities: number | null;
```

Replace the form state initialiser:
```tsx
  const [form, setForm] = useState({
    to_part_id: '',
    relation_type: DEFAULT_TYPE_BY_CATEGORY[itemCategory] ?? 'related',
    cavities: '',
  });
```

Replace the add mutation body so cavities travel with a `produces` link:
```tsx
  const addMutation = useMutation({
    mutationFn: async () => {
      await client.post(`/v1/parts/${partId}/relations`, {
        to_part_id: parseInt(form.to_part_id, 10),
        relation_type: form.relation_type,
        cavities: form.relation_type === 'produces' && form.cavities !== ''
          ? parseInt(form.cavities, 10)
          : null,
      });
    },
    onSuccess: () => {
      toast.success('Relation added');
      queryClient.invalidateQueries({ queryKey: ['part-relations'] });
      queryClient.invalidateQueries({ queryKey: ['master-bom'] });
      queryClient.invalidateQueries({ queryKey: ['tooling-board'] });
      setShowAdd(false);
      setForm({ ...form, to_part_id: '', cavities: '' });
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to add relation');
    },
  });
```

Give the delete mutation the same two extra invalidations:
```tsx
    onSuccess: () => {
      toast.success('Relation removed');
      queryClient.invalidateQueries({ queryKey: ['part-relations'] });
      queryClient.invalidateQueries({ queryKey: ['master-bom'] });
      queryClient.invalidateQueries({ queryKey: ['tooling-board'] });
    },
```

Show the cavity count on an existing tool link — inside the relation list item, directly after the part-number span:
```tsx
                {rel.relation_type === 'produces' && rel.cavities != null && (
                  <span className="ml-2 rounded-full border border-slate-600 px-1.5 py-0.5 text-[11px] text-slate-300 tabular-nums">
                    {rel.cavities} cav
                  </span>
                )}
```

Replace the add form's field row with labelled controls plus the conditional cavities input:
```tsx
          <div className="flex gap-2">
            <select
              aria-label="Relation type"
              value={form.relation_type}
              onChange={(e) => setForm({ ...form, relation_type: e.target.value })}
              className="bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-slate-100 text-xs"
            >
              <option value="produces">produces</option>
              <option value="checks">checks</option>
              <option value="assembles">assembles</option>
              <option value="mirror_of">mirror of</option>
              <option value="related">related to</option>
            </select>
            {form.relation_type === 'produces' && (
              <input
                aria-label="Cavities"
                type="number"
                min={1}
                placeholder="cav"
                value={form.cavities}
                onChange={(e) => setForm({ ...form, cavities: e.target.value })}
                className="w-16 bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-slate-100 text-xs font-mono tabular-nums"
              />
            )}
            <select
              aria-label="Linked item"
              value={form.to_part_id}
              onChange={(e) => setForm({ ...form, to_part_id: e.target.value })}
              className="flex-1 bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-slate-100 text-xs"
            >
              <option value="">-- Select item --</option>
              {availableParts.map((p) => (
                <option key={p.id} value={p.id}>
                  {CATEGORY_ICONS[p.item_category] ?? ''} {p.part_number} — {p.name}
                </option>
              ))}
            </select>
          </div>
```

- [ ] **Step 4: Run the relations test**

Run: `cd frontend && npx vitest run src/components/PartRelationsSection.test.tsx`
Expected: 2 passed.

- [ ] **Step 5: Replace the parts tree on the project page**

In `frontend/src/pages/ProjectDetailPage.tsx`:

Add the import next to the other component imports:
```tsx
import MasterBomSection from '../components/bom/MasterBomSection';
```

Delete `interface TreeNode { part: Part; children: TreeNode[] }` (lines 71-74), the `toolNumber` / `comparePartNodes` / `buildPartTree` block with its comments (lines 158-217), and the `getDescendantIds` + `TreeNodeComponent` block with its comments (lines 379-523).

In the component body, delete these three state lines:
```tsx
  const [draggingPartId, setDraggingPartId] = useState<number | null>(null);
  const [topLevelDragOver, setTopLevelDragOver] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
```

Delete `reparentMutation`, `handleDropOnPart` and `invalidDropIds` (lines 961-986) and the `const partTree = parts ? buildPartTree(parts) : [];` line.

Drop the now-unused loading flag from the parts query (`noUnusedLocals` rejects it):
```tsx
  const { data: parts } = useProjectParts(id);
```

Replace the grid opener and the whole left column (lines 1082-1160) with:
```tsx
      {/* Master BOM replaces the flat parts tree: the same parts, grouped by
          the assembly they belong to, with the engineering basics in place. */}
      <div className="space-y-6">
        <MasterBomSection
          projectId={id}
          selectedPartId={selectedPartId}
          onSelectPart={setSelectedPartId}
          onContextMenu={handleContextMenu}
          onAddPart={() => setShowAddModal(true)}
        />

```

and change the detail panel's opening `<div>` (line 1162) so it no longer spans grid columns:
```tsx
        <div
          className="space-y-4 min-h-96"
          onClick={() => setSelectedPartId(null)}
        >
```

The two closing `</div>`s that ended the grid stay as they are — they now close the detail panel and the stacked wrapper.

- [ ] **Step 6: Run the checks**

Run: `cd frontend && npx tsc --noEmit -p .`
Expected: no output (0 errors). If anything is reported it is a leftover from the removal — delete the symbol, do not re-add a use for it.

Run: `cd frontend && npx vitest run`
Expected: the whole frontend suite passes, including the two new bom test files.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx frontend/src/components/PartRelationsSection.tsx frontend/src/components/PartRelationsSection.test.tsx
git commit -m "feat(bom): master BOM replaces the project parts tree; mirror and cavities in relations

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bts9vcERghAQ2cVvRSsFaY"
```

---

### Task 9: `ToolingBoard` and the two-tab header

**Files:**
- Create: `frontend/src/components/bom/ToolingBoard.tsx`
- Create: `frontend/src/components/bom/ToolingBoard.test.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` (tab state around the `MasterBomSection` placed in task 8)

**Interfaces:**
- Produces: `export default function ToolingBoard(props: { projectId: number; onSelectPart: (partId: number) => void; onAddItem: () => void })`.
- Consumes: `useToolingBoard`, `useCreateRelation`, `useDeleteRelation`, `useUpdateCavities` from `./api`; `BOARD_KIND_LABELS`, `BoardKind`, `ToolingBoard as ToolingBoardData` from `./types`.
- Behaviour pinned by tests: the kind switch refetches with the new `kind`; the rail lists assemblies with their articles and marks assigned ones; "hide assigned" and the search box filter the rail; assigning posts `/v1/parts/{itemId}/relations` with the board's `relation_type`; removing deletes `/v1/parts/relations/{id}`; the cavities input patches the relation; the progress readout shows `assigned / total`.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/bom/ToolingBoard.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ToolingBoard from './ToolingBoard';

const calls = vi.hoisted(() => ({
  get: [] as string[], post: [] as [string, unknown][],
  del: [] as string[], patch: [] as [string, unknown][],
}));

const TOOL_BOARD = {
  kind: 'tool', relation_type: 'produces',
  assemblies: [
    {
      part_id: 12, name: 'Cover assembly LHD', customer_part_number: '9656732',
      peak_annual_volume: 41000, lifetime_volume: 159000,
      articles: [
        { part_id: 15, name: 'Cover SHUD LHD', customer_part_number: '9656733', weight_g: 203.6, assigned: true },
        { part_id: 16, name: 'Cover SHUD RHD', customer_part_number: null, weight_g: 201.2, assigned: false },
      ],
    },
    {
      part_id: null, name: 'Unassigned', customer_part_number: null,
      peak_annual_volume: null, lifetime_volume: null,
      articles: [{ part_id: 20, name: 'Clip', customer_part_number: null, weight_g: null, assigned: false }],
    },
  ],
  items: [{
    part_id: 30, name: 'T-0412', part_number: 'T-0412', supplier: 'Werkzeugbau Nord',
    revision_name: 'ENG1', revision_status: 'in_progress',
    articles: [{ part_id: 15, name: 'Cover SHUD LHD', relation_id: 91, cavities: 1 }],
  }],
  articles_total: 3, articles_assigned: 1,
};

const GAUGE_BOARD = {
  kind: 'gauge', relation_type: 'checks', assemblies: [], items: [],
  articles_total: 0, articles_assigned: 0,
};

vi.mock('../../api/client', () => ({
  default: {
    get: vi.fn(async (url: string) => {
      calls.get.push(url);
      return { data: url.includes('kind=gauge') ? GAUGE_BOARD : TOOL_BOARD };
    }),
    post: vi.fn(async (url: string, body: unknown) => { calls.post.push([url, body]); return { data: {} }; }),
    patch: vi.fn(async (url: string, body: unknown) => { calls.patch.push([url, body]); return { data: {} }; }),
    delete: vi.fn(async (url: string) => { calls.del.push(url); return { data: {} }; }),
  },
  API_BASE_URL: '',
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderBoard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ToolingBoard projectId={12} onSelectPart={vi.fn()} onAddItem={vi.fn()} />
    </QueryClientProvider>
  );
}

describe('ToolingBoard', () => {
  beforeEach(() => { calls.get.length = 0; calls.post.length = 0; calls.del.length = 0; calls.patch.length = 0; });

  it('renders the rail, the cards and the progress', async () => {
    renderBoard();
    await waitFor(() => expect(screen.getByText('T-0412')).toBeTruthy());
    expect(screen.getByText('Cover assembly LHD')).toBeTruthy();
    expect(screen.getByText('Werkzeugbau Nord')).toBeTruthy();
    expect(screen.getByTestId('board-progress').textContent).toBe('1 / 3 assigned');
    expect(screen.getByTestId('rail-article-15').getAttribute('data-assigned')).toBe('true');
    expect(screen.getByTestId('rail-article-16').getAttribute('data-assigned')).toBe('false');
    cleanup();
  });

  it('switches kind and refetches', async () => {
    renderBoard();
    await waitFor(() => expect(screen.getByText('T-0412')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Gauges' }));
    await waitFor(() => expect(calls.get).toContain('/v1/projects/12/tooling-board?kind=gauge'));
    cleanup();
  });

  it('hides assigned articles on request', async () => {
    renderBoard();
    await waitFor(() => expect(screen.getByTestId('rail-article-15')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('Hide assigned'));
    await waitFor(() => expect(screen.queryByTestId('rail-article-15')).toBeNull());
    expect(screen.getByTestId('rail-article-16')).toBeTruthy();
    cleanup();
  });

  it('assigns an article to an item', async () => {
    renderBoard();
    fireEvent.click(await screen.findByRole('button', { name: /assign article/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Cover SHUD RHD' }));
    await waitFor(() => expect(calls.post).toEqual([
      ['/v1/parts/30/relations', { to_part_id: 16, relation_type: 'produces' }],
    ]));
    cleanup();
  });

  it('removes a linked article and edits its cavities', async () => {
    renderBoard();
    const linked = await screen.findByTestId('linked-91');
    fireEvent.change(within(linked).getByRole('spinbutton'), { target: { value: '4' } });
    fireEvent.blur(within(linked).getByRole('spinbutton'));
    await waitFor(() => expect(calls.patch).toEqual([['/v1/parts/relations/91', { cavities: 4 }]]));

    fireEvent.click(within(linked).getByRole('button', { name: /remove/i }));
    await waitFor(() => expect(calls.del).toEqual(['/v1/parts/relations/91']));
    cleanup();
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `cd frontend && npx vitest run src/components/bom/ToolingBoard.test.tsx`
Expected: `Failed to resolve import "./ToolingBoard"`.

- [ ] **Step 3: Write the component**

`frontend/src/components/bom/ToolingBoard.tsx`:
```tsx
/**
 * ToolingBoard - articles on the left, the items that serve them on the right.
 *
 * One board covers tools, gauges and assembly equipment, because all three are
 * the same fact seen from the item's side: a relation to the article. The
 * switch only changes which relation type is read and written.
 */
import { useMemo, useState } from 'react';
import type { BoardArticle, BoardItem, BoardKind } from './types';
import { BOARD_KIND_LABELS } from './types';
import { useCreateRelation, useDeleteRelation, useToolingBoard, useUpdateCavities } from './api';

const BTN = 'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors duration-150';
const KINDS: BoardKind[] = ['tool', 'gauge', 'assembly_equipment'];

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 text-emerald-400" fill="none"
      stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
      <path d="M5 13l4 4L19 7" />
    </svg>
  );
}

function CavitiesInput({ relationId, cavities, onSave }: {
  relationId: number; cavities: number | null;
  onSave: (relationId: number, value: number | null) => void;
}) {
  const initial = cavities === null ? '' : String(cavities);
  const [value, setValue] = useState(initial);
  return (
    <input
      aria-label="Cavities"
      type="number"
      min={1}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={() => {
        if (value === initial) return;
        const next = value === '' ? null : Number(value);
        if (next !== null && Number.isNaN(next)) return;
        onSave(relationId, next);
      }}
      className="w-14 rounded-md bg-slate-900 border border-slate-700 px-2 py-1 text-xs text-slate-100 font-mono tabular-nums"
    />
  );
}

interface Props {
  projectId: number;
  onSelectPart: (partId: number) => void;
  onAddItem: () => void;
}

export default function ToolingBoard({ projectId, onSelectPart, onAddItem }: Props) {
  const [kind, setKind] = useState<BoardKind>('tool');
  const [search, setSearch] = useState('');
  const [hideAssigned, setHideAssigned] = useState(false);
  const [pickerItemId, setPickerItemId] = useState<number | null>(null);

  const { data, isLoading } = useToolingBoard(projectId, kind);
  const createRelation = useCreateRelation(projectId);
  const deleteRelation = useDeleteRelation(projectId);
  const updateCavities = useUpdateCavities(projectId);

  const matches = (article: BoardArticle) => {
    const needle = search.trim().toLowerCase();
    if (needle && !`${article.name} ${article.customer_part_number ?? ''}`.toLowerCase().includes(needle)) {
      return false;
    }
    return !(hideAssigned && article.assigned);
  };

  const rail = useMemo(
    () => (data?.assemblies ?? [])
      .map((group) => ({ ...group, articles: group.articles.filter(matches) }))
      .filter((group) => group.articles.length > 0),
    [data, search, hideAssigned]
  );

  const assign = (item: BoardItem, article: BoardArticle) => {
    setPickerItemId(null);
    createRelation.mutate({
      fromPartId: item.part_id,
      toPartId: article.part_id,
      relationType: data?.relation_type ?? 'produces',
    });
  };

  const pickable = (item: BoardItem) => {
    const linked = new Set(item.articles.map((a) => a.part_id));
    return (data?.assemblies ?? [])
      .flatMap((group) => group.articles)
      .filter((article) => !linked.has(article.part_id));
  };

  const progress = data ? `${data.articles_assigned} / ${data.articles_total} assigned` : '';
  const percent = data && data.articles_total > 0
    ? Math.round((data.articles_assigned / data.articles_total) * 100)
    : 0;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1 rounded-lg border border-slate-700/70 bg-slate-800 p-1">
          {KINDS.map((k) => (
            <button key={k} onClick={() => setKind(k)}
              className={`${BTN} ${kind === k ? 'bg-sky-600 text-white' : 'text-slate-300 hover:bg-slate-700/60'}`}>
              {BOARD_KIND_LABELS[k]}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-3">
          <div className="h-1.5 w-40 overflow-hidden rounded-full bg-slate-700">
            <div className="h-full bg-sky-500 transition-all" style={{ width: `${percent}%` }} />
          </div>
          <span data-testid="board-progress" className="text-xs text-slate-400 tabular-nums">{progress}</span>
          <button onClick={onAddItem} className={`${BTN} bg-sky-600 text-white hover:bg-sky-500 shadow-panel`}>
            New
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="h-40 rounded-lg bg-slate-700/30 animate-pulse" />
      ) : (
        <div className="grid grid-cols-3 gap-4">
          <aside className="rounded-lg border border-slate-700/70 bg-slate-800 p-3 shadow-panel space-y-3">
            <input
              placeholder="Search articles"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-500"
            />
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <input type="checkbox" aria-label="Hide assigned" checked={hideAssigned}
                onChange={(e) => setHideAssigned(e.target.checked)}
                className="h-4 w-4 rounded border-slate-600 bg-slate-900 accent-sky-500" />
              Hide assigned
            </label>
            {rail.length === 0 && <p className="text-sm text-slate-500">No articles match.</p>}
            {rail.map((group) => (
              <div key={String(group.part_id ?? 'unassigned')} className="space-y-1">
                <div className="flex items-baseline gap-2 border-b border-slate-700/60 pb-1">
                  <span className="text-sm font-semibold text-slate-200">{group.name}</span>
                  {group.peak_annual_volume != null && (
                    <span className="text-[11px] text-slate-500 tabular-nums">
                      {group.peak_annual_volume.toLocaleString()}/yr
                    </span>
                  )}
                </div>
                {group.articles.map((article) => (
                  <div key={article.part_id} data-testid={`rail-article-${article.part_id}`}
                    data-assigned={String(article.assigned)}
                    className="flex items-center gap-2 rounded px-2 py-1 hover:bg-slate-700/40">
                    {article.assigned ? <CheckIcon /> : <span className="w-3.5" />}
                    <button onClick={() => onSelectPart(article.part_id)}
                      className="flex-1 text-left text-sm text-slate-200 hover:text-sky-300">
                      {article.name}
                    </button>
                    {article.customer_part_number && (
                      <span className="font-mono text-[11px] text-slate-500">{article.customer_part_number}</span>
                    )}
                    {article.weight_g != null && (
                      <span className="text-[11px] text-slate-500 tabular-nums">{article.weight_g} g</span>
                    )}
                  </div>
                ))}
              </div>
            ))}
          </aside>

          <div className="col-span-2 space-y-3">
            {(data?.items ?? []).length === 0 && (
              <div className="rounded-lg border border-dashed border-slate-700 p-8 text-center text-sm text-slate-400">
                No {BOARD_KIND_LABELS[kind].toLowerCase()} in this project yet.
              </div>
            )}
            {(data?.items ?? []).map((item) => (
              <section key={item.part_id} className="rounded-lg border border-slate-700/70 bg-slate-800 p-4 shadow-panel">
                <div className="flex flex-wrap items-center gap-2">
                  <button onClick={() => onSelectPart(item.part_id)}
                    className="text-base font-semibold text-slate-100 hover:text-sky-300">{item.name}</button>
                  <span className="font-mono text-xs text-slate-400">{item.part_number}</span>
                  {item.supplier && <span className="text-xs text-slate-400">{item.supplier}</span>}
                  {item.revision_name && (
                    <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-[11px] text-sky-300">
                      <span className="font-mono">{item.revision_name}</span>{' '}
                      {(item.revision_status ?? '').replace(/_/g, ' ')}
                    </span>
                  )}
                  <button onClick={() => setPickerItemId(pickerItemId === item.part_id ? null : item.part_id)}
                    className={`${BTN} ml-auto border border-slate-600 text-slate-200 hover:bg-slate-700/60`}>
                    Assign article
                  </button>
                </div>

                <div className="mt-3 space-y-1">
                  {item.articles.length === 0 && (
                    <p className="text-sm text-slate-500">No articles assigned.</p>
                  )}
                  {item.articles.map((article) => (
                    <div key={article.relation_id} data-testid={`linked-${article.relation_id}`}
                      className="flex items-center gap-2 rounded border border-slate-700/60 bg-slate-900/40 px-2 py-1.5">
                      <button onClick={() => onSelectPart(article.part_id)}
                        className="flex-1 text-left text-sm text-slate-200 hover:text-sky-300">{article.name}</button>
                      {kind === 'tool' && (
                        <CavitiesInput relationId={article.relation_id} cavities={article.cavities}
                          onSave={(relationId, cavities) => updateCavities.mutate({ relationId, cavities })} />
                      )}
                      <button onClick={() => deleteRelation.mutate(article.relation_id)}
                        title="Remove article" aria-label="Remove article"
                        className="text-rose-400 hover:text-rose-300 text-xs px-1">
                        remove
                      </button>
                    </div>
                  ))}
                </div>

                {pickerItemId === item.part_id && (
                  <div className="mt-3 max-h-56 overflow-y-auto rounded border border-slate-700 bg-slate-900/60 p-2">
                    {pickable(item).length === 0 && (
                      <p className="text-sm text-slate-500">Every article is already linked.</p>
                    )}
                    {pickable(item).map((article) => (
                      <button key={article.part_id} onClick={() => assign(item, article)}
                        className="block w-full rounded px-2 py-1 text-left text-sm text-slate-200 hover:bg-slate-700/60">
                        {article.name}
                      </button>
                    ))}
                  </div>
                )}
              </section>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run to see it pass**

Run: `cd frontend && npx vitest run src/components/bom/ToolingBoard.test.tsx`
Expected: 5 passed.

- [ ] **Step 5: Add the two-tab header to the project page**

In `frontend/src/pages/ProjectDetailPage.tsx`, add the import:
```tsx
import ToolingBoard from '../components/bom/ToolingBoard';
```

Add the tab state next to the other `useState` calls in the component body:
```tsx
  const [partsTab, setPartsTab] = useState<'bom' | 'tooling'>('bom');
```

Replace the `<MasterBomSection ... />` block placed in task 8 with the tab header and both panes:
```tsx
        <div className="flex items-center gap-1 rounded-lg border border-slate-700/70 bg-slate-800 p-1 w-fit">
          <button onClick={() => setPartsTab('bom')}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors duration-150 ${
              partsTab === 'bom' ? 'bg-sky-600 text-white' : 'text-slate-300 hover:bg-slate-700/60'}`}>
            Master BOM
          </button>
          <button onClick={() => setPartsTab('tooling')}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors duration-150 ${
              partsTab === 'tooling' ? 'bg-sky-600 text-white' : 'text-slate-300 hover:bg-slate-700/60'}`}>
            Tooling &amp; equipment
          </button>
        </div>

        {partsTab === 'bom' ? (
          <MasterBomSection
            projectId={id}
            selectedPartId={selectedPartId}
            onSelectPart={setSelectedPartId}
            onContextMenu={handleContextMenu}
            onAddPart={() => setShowAddModal(true)}
          />
        ) : (
          <ToolingBoard
            projectId={id}
            onSelectPart={setSelectedPartId}
            onAddItem={() => setShowAddModal(true)}
          />
        )}

```

- [ ] **Step 6: Run the checks**

Run: `cd frontend && npx tsc --noEmit -p .`
Expected: no output (0 errors).

Run: `cd frontend && npx vitest run`
Expected: the whole frontend suite passes.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/bom/ToolingBoard.tsx frontend/src/components/bom/ToolingBoard.test.tsx frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(bom): tooling board tab with article rail and item cards

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bts9vcERghAQ2cVvRSsFaY"
```

---

### Task 10: Deployment note, spec touch-ups, memory

**Files:**
- Modify: `DEPLOYMENT.md` (one paragraph next to the SEP forms note)
- Modify: `docs/superpowers/specs/2026-09-08-master-bom-tooling-board-design.md`
- Create: `memory/master-bom-tooling-board.md`; add one pointer line to `memory/MEMORY.md`

- [ ] **Step 1: Deployment note** — in `DEPLOYMENT.md`, after the SEP forms paragraph: migration `066_master_bom` only adds nullable columns to `part_revisions`, `parts` and `part_relations`; there is no data migration and no new dependency, so `alembic upgrade head` (which the backend runs itself on startup for non-SQLite) is the whole deployment and the image does not need rebuilding. Mention that the frontend bundle must be rebuilt because the project page changed.

- [ ] **Step 2: Spec touch-ups** — record in the design document the decisions this build pinned:
  1. The project-scoped reads live on a new `/v1/projects` router (`app/api/v1/items/project_bom.py`), not under the parts prefix, because they answer a question about a project; auth and the permission model are unchanged, as the spec required.
  2. The `Unassigned` group is always present and its `filled`/`total` are counted the same way as any other group's (the spec's example showed `0/0`).
  3. A self-mirror answers 409, not the generic 400 the self-relation check returns, so both mirror-rule violations read the same to the UI.
  4. `cavities` sent with a non-`produces` relation is ignored on create *and* on PATCH, rather than rejected.
  5. Drag-and-drop reparenting and the category filter chips left the project page with the tree. Assembly membership is edited in the assembly's BOM section, which is what the spec asks for; the item-category filter has no equivalent in the master BOM and was not re-added.
  6. Groups are every `part_type = sub_assembly` part regardless of item category; only articles fall into `Unassigned`.

- [ ] **Step 3: Memory** — `memory/master-bom-tooling-board.md` (type: project): what shipped (migration 066, `RevisionService.active_revision`, `master_bom_service`, `/v1/projects/{id}/master-bom` and `/tooling-board`, `components/bom/*`, tree removed from the project page), where the current-revision rule lives and that `PartDetail.tsx` still has its own copy in `getActiveRevisionLevel` (two implementations of one rule — the follow-up is to have the part page read the server's answer), and the spec's "later, not now" list (CAD thumbnails for the glyph column, SEP gate rules on completeness, prefilling the sales handover parts table). Add the pointer line to `memory/MEMORY.md`.

- [ ] **Step 4: Full verification** — the controller runs `cd backend && python3 -m pytest tests -q` and `cd frontend && npx vitest run` once, here, and pastes the counts into the commit message. Individual tasks never run the full backend suite.

- [ ] **Step 5: Commit**

```bash
git add DEPLOYMENT.md docs/superpowers/specs/2026-09-08-master-bom-tooling-board-design.md docs/superpowers/plans/2026-09-08-master-bom-tooling-board.md memory
git commit -m "docs(bom): deployment note, spec decisions, memory

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bts9vcERghAQ2cVvRSsFaY"
```

Production rollout (the user runs this, it is not part of the plan): deploy the frontend bundle, restart the backend so `alembic upgrade head` applies 066, then open a project and check that the master BOM groups match what the tree showed and that a tool card lists its articles.
