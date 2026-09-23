# Tool view: tool fields and DFM archive - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give tools (parts with `item_category = tool`) their own page: four sold-state fields (cavities, toolmaker, tonnage class, cycle time) and a per-tool DFM archive of topics, each a three-column append-only ledger (Toolmaker | KTX | Tier 1) with tagged files.

**Architecture:** Backend adds four nullable columns to `parts` (migration 077) guarded to tools, three new tables `dfm_topics` / `dfm_entries` / `dfm_entry_files` (migration 078) behind a `DfmService` and a router under `/api/v1/parts/{part_id}/dfm`. Frontend branches `PartDetail` on `item_category === 'tool'` into a new `ToolDetail` page that shows produced-article chips, a `ToolFieldsCard` and a `DfmArchive` (topic list -> `DfmLedger` -> `DfmEntryForm`). PDFs reuse `DocumentPane` via a new `inlineUrl` override.

**Tech Stack:** FastAPI + SQLAlchemy 2 async + Alembic (guarded migrations), pytest (SQLite, fixtures `client`, `eng_auth`, `seed`, `part`), React + Vite + TanStack Query + axios, vitest + testing-library.

**Spec:** `docs/superpowers/specs/2026-09-23-tool-dfm-archive-design.md`

## Global Constraints

- Migrations are guarded like `076_part_tier1_number.py` (inspect before add/create); `076` is the current head, this plan adds `077` then `078`.
- Tool fields on `parts`: `tool_cavities` integer, `toolmaker_id` FK `suppliers.id`, `tool_tonnage_class` integer, `tool_cycle_time_s` numeric(6,1). Meaningful only for `item_category = tool`; API rejects them on non-tools with 400.
- Update rule for tool fields: applied only when the key is in the request body (`update_<field>` flags, same as `customer_part_number` / `tier1_part_number`).
- DFM parties: exactly `toolmaker` | `ktx` | `tier1`. Topic statuses: `open` | `finished_confirmed`.
- No delete endpoint for topics, entries or files. A topic can be reopened; nothing else is reversible. An update is a new entry with `supersedes_id`; the old entry stays.
- Errors: non-tool on any DFM route or tool field -> 400 plain message; entry on a closed topic -> 409 `"Topic is finished, reopen it first"`; supersede across topics or across columns -> 400; storage failure -> 500 with nothing recorded.
- Files go under `<cwd>/uploads/dfm/<tool_part_id>/<entry_id>/<uuid><ext>` (the revision-file layout is `<cwd>/uploads/revisions/<revision_id>/`; `settings.upload_dir` is not used by any file route today, so stay with the cwd pattern the tests already `monkeypatch.chdir` around).
- Tool page: no 3D pane, no revision strip, no revision file list, no customer data actions; Tier 1 / customer numbers hidden.
- Copy: "Finish confirmed", "Reopen", "+ topic", "+ entry", "Update this entry", "(updated)", "earlier version".
- No em dashes in code comments, UI copy or commit messages (memory `no-em-dashes`).
- Do not commit in this plan's execution unless the human asks; the task "Commit" steps are the standard checkpoints and are run only when commits are wanted.

## Review Focus

1. `addressed_to` that names the entry's own party or an unknown party (e.g. `["ktx"]` on a KTX entry, `["brose"]`): expected 400, never stored. Test in Task 5.
2. `sent_at` sent as an empty string from the form (date input left blank): expected to be treated as null, not 422. Test in Task 5.
3. An entry with no note and no files: a bare "Finish confirmed" style entry is legitimate (see spec ledger), so it must be accepted; but a supersede that changes nothing is still a new entry. Test in Task 5.
4. Cavities on a tool whose `tool_cavities` is null but whose `produces` note says "2 cavities" (the prod state today): the tool page must show 2 with a hint, not "empty". Test in Task 10.
5. Superseding an already superseded entry (chain of three): history must show both earlier versions, oldest last, and the topic list must count four entries. Test in Task 5.

---

## File structure

Backend (create):
- `backend/alembic/versions/077_part_tool_fields.py` - four columns on `parts`.
- `backend/alembic/versions/078_dfm_archive.py` - three DFM tables.
- `backend/app/models/dfm.py` - `DfmTopic`, `DfmEntry`, `DfmEntryFile`, party/status constants.
- `backend/app/services/dfm_service.py` - topic open/close/reopen, entry recording with files, response shaping (history collapse), file paths.
- `backend/app/api/v1/items/dfm.py` - router `/parts/{part_id}/dfm/...`.
- `backend/scripts/set_1994_tool_fields.py` - one-off prod script.
- `backend/tests/test_tool_fields.py`, `test_dfm_models.py`, `test_dfm_topics.py`, `test_dfm_entries.py`, `test_dfm_files.py`.

Backend (modify):
- `backend/app/models/part.py` - tool columns on `Part`.
- `backend/app/models/__init__.py` - export DFM models.
- `backend/app/schemas/part.py` - tool fields on `PartBase` / `PartUpdate`.
- `backend/app/services/part_service.py` - create/update handling + tool guard.
- `backend/app/api/v1/items/parts.py` - pass tool fields through.
- `backend/app/api/v1/items/part_relations.py` - `other_active_revision_name`, `other_active_customer_index`.
- `backend/app/api/v1/__init__.py` - include the DFM router.

Frontend (create):
- `frontend/src/api/dfm.ts` - types, API calls, `dfmFileUrl`.
- `frontend/src/hooks/queries/useSuppliers.ts` - hook lifted out of `ProjectDetailPage`.
- `frontend/src/pages/ToolDetail.tsx` (+ `ToolDetail.test.tsx`) - tool page.
- `frontend/src/components/tools/ToolFieldsCard.tsx` (+ test) - four inline edits.
- `frontend/src/components/dfm/DfmArchive.tsx` (+ test) - topic list and selection.
- `frontend/src/components/dfm/DfmLedger.tsx` (+ test) - three-column ledger.
- `frontend/src/components/dfm/DfmEntryForm.tsx` (+ test) - entry form.
- `frontend/src/pages/PartDetail.tool.test.tsx` - the branch.

Frontend (modify):
- `frontend/src/pages/PartDetail.tsx` - branch to `ToolDetail`.
- `frontend/src/pages/ProjectDetailPage.tsx` - import `useSuppliers` from the hook file.
- `frontend/src/components/parts/DocumentPane.tsx` (+ test) - `inlineUrl` override.

Commands used throughout:
- Backend single file: `cd /home/nitrolinux/claude/plm2/backend && pytest tests/<file>.py -v -n 0`
- Backend all: `cd /home/nitrolinux/claude/plm2/backend && pytest`
- Frontend single file: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/<path>`
- Frontend all: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run && npx tsc --noEmit && npm run lint`

---

### Task 1: Migration 077 and tool fields on parts (backend)

**Files:**
- Create: `backend/alembic/versions/077_part_tool_fields.py`
- Create: `backend/tests/test_tool_fields.py`
- Modify: `backend/app/models/part.py` (Part, after `tier1_part_number`)
- Modify: `backend/app/schemas/part.py` (`PartBase`, `PartUpdate`)
- Modify: `backend/app/services/part_service.py` (`create_part`, `update_part`)
- Modify: `backend/app/api/v1/items/parts.py` (`create_part`, `update_part`)

**Interfaces:**
- Consumes: `PartService.update_part(... update_<field>=bool)` pattern; `Supplier` model (`app/models/supplier.py`).
- Produces: `Part.tool_cavities: int|None`, `Part.toolmaker_id: int|None`, `Part.tool_tonnage_class: int|None`, `Part.tool_cycle_time_s: float|None`; the same four keys in `PartResponse`; `PartService.TOOL_FIELDS = ("tool_cavities", "toolmaker_id", "tool_tonnage_class", "tool_cycle_time_s")`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_tool_fields.py`:

```python
"""Tool fields: cavities, toolmaker, tonnage class and target cycle time live
on the tool part (item_category = tool). They are refused on articles, and a
PUT only touches them when the key is in the body."""


async def _create(client, eng_auth, seed, item_category="tool", **extra):
    body = {
        "project_id": seed["project_id"],
        "part_number": "199403" if item_category == "tool" else "20-1994-003-0",
        "name": "ISOFIX Cover" if item_category == "tool" else "206.887.233 Isofix cover",
        "part_type": "purchased",
        "data_classification": "confidential",
        "item_category": item_category,
        **extra,
    }
    return await client.post("/api/v1/parts", json=body, headers=eng_auth)


async def _supplier(client, eng_auth, name="Toolshop Sued"):
    res = await client.post("/api/v1/suppliers", json={"name": name}, headers=eng_auth)
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def test_tool_fields_created_and_returned(client, eng_auth, seed):
    toolmaker = await _supplier(client, eng_auth)
    res = await _create(client, eng_auth, seed, tool_cavities=4, toolmaker_id=toolmaker,
                        tool_tonnage_class=650, tool_cycle_time_s=32.5)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tool_cavities"] == 4
    assert body["toolmaker_id"] == toolmaker
    assert body["tool_tonnage_class"] == 650
    assert body["tool_cycle_time_s"] == 32.5

    res = await client.get(f"/api/v1/parts/{body['id']}", headers=eng_auth)
    assert res.json()["tool_cycle_time_s"] == 32.5


async def test_tool_fields_default_null(client, eng_auth, seed):
    res = await _create(client, eng_auth, seed)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tool_cavities"] is None
    assert body["toolmaker_id"] is None
    assert body["tool_tonnage_class"] is None
    assert body["tool_cycle_time_s"] is None


async def test_tool_fields_update_only_when_key_present(client, eng_auth, seed):
    pid = (await _create(client, eng_auth, seed)).json()["id"]

    res = await client.put(f"/api/v1/parts/{pid}", json={"tool_cavities": 4}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["tool_cavities"] == 4

    res = await client.put(f"/api/v1/parts/{pid}", json={"name": "ISOFIX Cover 4-cav"}, headers=eng_auth)
    assert res.json()["tool_cavities"] == 4

    res = await client.put(f"/api/v1/parts/{pid}", json={"tool_cavities": None}, headers=eng_auth)
    assert res.json()["tool_cavities"] is None


async def test_tool_fields_rejected_on_article(client, eng_auth, seed):
    res = await _create(client, eng_auth, seed, item_category="article", tool_cavities=2)
    assert res.status_code == 400
    assert "tool" in res.json()["detail"].lower()

    pid = (await _create(client, eng_auth, seed, item_category="article")).json()["id"]
    res = await client.put(f"/api/v1/parts/{pid}", json={"tool_tonnage_class": 650}, headers=eng_auth)
    assert res.status_code == 400
    # Explicit null is still a tool-field write and is refused too
    res = await client.put(f"/api/v1/parts/{pid}", json={"tool_cavities": None}, headers=eng_auth)
    assert res.status_code == 400


async def test_toolmaker_must_be_a_supplier(client, eng_auth, seed):
    pid = (await _create(client, eng_auth, seed)).json()["id"]
    res = await client.put(f"/api/v1/parts/{pid}", json={"toolmaker_id": 999999}, headers=eng_auth)
    assert res.status_code == 400
    assert "toolmaker" in res.json()["detail"].lower()


async def test_tool_field_bounds(client, eng_auth, seed):
    pid = (await _create(client, eng_auth, seed)).json()["id"]
    assert (await client.put(f"/api/v1/parts/{pid}", json={"tool_cavities": 0}, headers=eng_auth)).status_code == 422
    assert (await client.put(f"/api/v1/parts/{pid}", json={"tool_cycle_time_s": -1}, headers=eng_auth)).status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/backend && pytest tests/test_tool_fields.py -v -n 0`
Expected: FAIL. `test_tool_fields_created_and_returned` gets a 200 without the keys (`KeyError: 'tool_cavities'`), the article test gets 200 instead of 400.

- [ ] **Step 3: Add the columns to the model**

In `backend/app/models/part.py`, import `Numeric` (extend the existing `from sqlalchemy import ...` line) and add to `Part` right after `tier1_part_number`:

```python
    # Tool fields (item_category = tool only). The sold state the DFM answers
    # rest on. tool_cavities is the source of truth over the "n cavities" note
    # on the produces relation.
    tool_cavities: Mapped[int | None] = mapped_column(Integer, nullable=True)
    toolmaker_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True, index=True)
    tool_tonnage_class: Mapped[int | None] = mapped_column(Integer, nullable=True)  # clamping force class, t
    tool_cycle_time_s: Mapped[float | None] = mapped_column(Numeric(6, 1, asdecimal=False), nullable=True)
```

`asdecimal=False` keeps SQLite quiet (no Decimal round-trip warning) and gives Pydantic a float.

- [ ] **Step 4: Write the guarded migration**

`backend/alembic/versions/077_part_tool_fields.py`:

```python
"""077: tool fields on parts.

Cavities, toolmaker, machine tonnage class and target cycle time for
item_category = tool. Nullable, meaningless on articles (the API refuses them
there).

Revision ID: 077
Revises: 076
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None

COLUMNS = [
    sa.Column("tool_cavities", sa.Integer(), nullable=True),
    sa.Column("toolmaker_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=True),
    sa.Column("tool_tonnage_class", sa.Integer(), nullable=True),
    sa.Column("tool_cycle_time_s", sa.Numeric(6, 1), nullable=True),
]


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    insp = inspect(op.get_bind())
    existing = _cols(insp, "parts")
    for col in COLUMNS:
        if col.name not in existing:
            op.add_column("parts", col.copy())
    if "toolmaker_id" not in existing:
        op.create_index("ix_parts_toolmaker_id", "parts", ["toolmaker_id"])


def downgrade() -> None:
    insp = inspect(op.get_bind())
    existing = _cols(insp, "parts")
    if "toolmaker_id" in existing:
        op.drop_index("ix_parts_toolmaker_id", table_name="parts")
    for col in reversed(COLUMNS):
        if col.name in existing:
            op.drop_column("parts", col.name)
```

- [ ] **Step 5: Extend the schemas**

In `backend/app/schemas/part.py`, add to `PartBase` after `next_calibration_due`:

```python
    # Tool fields (item_category = tool only)
    tool_cavities: Optional[int] = Field(None, ge=1, le=256, description="Cavities in the tool, total")
    toolmaker_id: Optional[int] = Field(None, description="Supplier building the tool")
    tool_tonnage_class: Optional[int] = Field(None, ge=1, le=10000, description="Machine clamping force class, t")
    tool_cycle_time_s: Optional[float] = Field(None, gt=0, le=9999.9, description="Target cycle time, s")
```

and the same four lines to `PartUpdate` after `last_calibrated_at`.

- [ ] **Step 6: Service: create and update with the tool guard**

In `backend/app/services/part_service.py`:

Add at module level (next to `VALID_ITEM_CATEGORIES`):

```python
TOOL_FIELDS = ("tool_cavities", "toolmaker_id", "tool_tonnage_class", "tool_cycle_time_s")
TOOL_FIELDS_ONLY_ON_TOOLS = "Tool fields (cavities, toolmaker, tonnage class, cycle time) only apply to tools"
```

Add the import `from app.models.supplier import Supplier` and a helper on `PartService`:

```python
    @staticmethod
    async def _check_toolmaker(session: AsyncSession, toolmaker_id: Optional[int]) -> None:
        if toolmaker_id is not None and await session.get(Supplier, toolmaker_id) is None:
            raise ValueError("Toolmaker not found: no supplier with that id")
```

`create_part`: add parameters after `tier1_part_number`:

```python
        tool_cavities: Optional[int] = None,
        toolmaker_id: Optional[int] = None,
        tool_tonnage_class: Optional[int] = None,
        tool_cycle_time_s: Optional[float] = None,
```

After the `VALID_ITEM_CATEGORIES` check and before `part = Part(...)`:

```python
        tool_values = {"tool_cavities": tool_cavities, "toolmaker_id": toolmaker_id,
                       "tool_tonnage_class": tool_tonnage_class, "tool_cycle_time_s": tool_cycle_time_s}
        if item_category != "tool" and any(v is not None for v in tool_values.values()):
            raise ValueError(TOOL_FIELDS_ONLY_ON_TOOLS)
        await PartService._check_toolmaker(session, toolmaker_id)
```

and pass `**tool_values` into the `Part(...)` constructor.

`update_part`: add parameters after `update_tier1_part_number`:

```python
        tool_cavities: Optional[int] = None,
        update_tool_cavities: bool = False,
        toolmaker_id: Optional[int] = None,
        update_toolmaker_id: bool = False,
        tool_tonnage_class: Optional[int] = None,
        update_tool_tonnage_class: bool = False,
        tool_cycle_time_s: Optional[float] = None,
        update_tool_cycle_time_s: bool = False,
```

and after the `tier1_part_number` block, before the `item_category` block:

```python
        tool_updates = {
            "tool_cavities": (update_tool_cavities, tool_cavities),
            "toolmaker_id": (update_toolmaker_id, toolmaker_id),
            "tool_tonnage_class": (update_tool_tonnage_class, tool_tonnage_class),
            "tool_cycle_time_s": (update_tool_cycle_time_s, tool_cycle_time_s),
        }
        if any(flag for flag, _ in tool_updates.values()):
            if (item_category or part.item_category) != "tool":
                raise ValueError(TOOL_FIELDS_ONLY_ON_TOOLS)
            if update_toolmaker_id:
                await PartService._check_toolmaker(session, toolmaker_id)
            for attr, (flag, value) in tool_updates.items():
                if flag:
                    setattr(part, attr, value)
```

- [ ] **Step 7: API: pass the fields through**

In `backend/app/api/v1/items/parts.py` `create_part`, add after `tier1_part_number=body.tier1_part_number,`:

```python
            tool_cavities=body.tool_cavities,
            toolmaker_id=body.toolmaker_id,
            tool_tonnage_class=body.tool_tonnage_class,
            tool_cycle_time_s=body.tool_cycle_time_s,
```

In `update_part`, after `update_tier1_part_number=...`:

```python
            tool_cavities=body.tool_cavities,
            update_tool_cavities='tool_cavities' in body.model_fields_set,
            toolmaker_id=body.toolmaker_id,
            update_toolmaker_id='toolmaker_id' in body.model_fields_set,
            tool_tonnage_class=body.tool_tonnage_class,
            update_tool_tonnage_class='tool_tonnage_class' in body.model_fields_set,
            tool_cycle_time_s=body.tool_cycle_time_s,
            update_tool_cycle_time_s='tool_cycle_time_s' in body.model_fields_set,
```

Both endpoints already map `ValueError` to 400 through their `except Exception` block.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2/backend && pytest tests/test_tool_fields.py tests/test_part_tier1_number.py tests/test_item_categories.py -v -n 0`
Expected: all PASS.

- [ ] **Step 9: Check the migration on a scratch SQLite DB**

Run: `cd /home/nitrolinux/claude/plm2/backend && DATABASE_URL=sqlite+aiosqlite:////tmp/claude-1000/-home-nitrolinux-claude-plm2/682e27d6-86ce-49d1-8aa2-d85ccfa61993/scratchpad/mig077.db alembic upgrade head && DATABASE_URL=sqlite+aiosqlite:////tmp/claude-1000/-home-nitrolinux-claude-plm2/682e27d6-86ce-49d1-8aa2-d85ccfa61993/scratchpad/mig077.db alembic upgrade head`
Expected: first run applies 077, second run is a no-op (guard works). If `alembic/env.py` reads the URL from settings differently, use whatever `run_backend.sh` relies on; the point is one upgrade then one idempotent re-run.

- [ ] **Step 10: Commit**

```bash
cd /home/nitrolinux/claude/plm2 && git add backend/alembic/versions/077_part_tool_fields.py backend/app/models/part.py backend/app/schemas/part.py backend/app/services/part_service.py backend/app/api/v1/items/parts.py backend/tests/test_tool_fields.py
git commit -m "feat(parts): tool fields cavities, toolmaker, tonnage class, cycle time (077)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: One-off script for the ten 1994 tools

**Files:**
- Create: `backend/scripts/set_1994_tool_fields.py`

**Interfaces:**
- Consumes: `Part.tool_cavities`, `Part.tool_tonnage_class`, `Part.tool_cycle_time_s`, `Part.toolmaker_id` (Task 1); `ChangelogService.log_action`; `Supplier`.
- Produces: nothing for later tasks; run on prod only.

No pytest here: the script mirrors `set_1994_tier1_numbers.py` (dry run by default, prod container). The check is a dry run against prod.

- [ ] **Step 1: Write the script**

Cavities below are the RFQ 26 nominated loop 37 REV8 values (memory `1994-brose-volume-sheet-2026-09-23`). Cycle time and tonnage are read from RFQ2 at execution time (see Step 2) and typed into the table before `--apply`; a `None` means "leave the field alone", never "set null".

```python
"""Set the sold-state tool fields on the ten 1994 tools from the nominated
RFQ 26 loop 37 (REV8): cavities, target cycle time, machine tonnage class,
and the toolmaker once known. One changelog entry per tool. Dry run by default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/set_1994_tool_fields.py [--toolmaker "<supplier name>"] [--apply]

A None in FIELDS leaves that field untouched. Fill cycle_time_s / tonnage
from RFQ2 before applying (see the plan, Task 2 Step 2).
"""
import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part
from app.models.supplier import Supplier
from app.services.part_service import ChangelogService

# tool part_number -> (cavities, cycle_time_s, tonnage_class)
# Cavities: RFQ 26 loop 37 REV8 on prod. Handles and latch covers are 1+1 tools.
FIELDS = {
    "199401": (2, None, None),   # Handle, height adjustment LH/RH
    "199402": (2, None, None),   # Latch cover 40/60
    "199403": (4, None, None),   # Isofix cover (relation note on prod says 2, RFQ says 4)
    "199404": (2, None, None),   # A-bracket inner trim
    "199405": (2, None, None),   # Cover trim, center back
    "199406": (2, None, None),   # Center bearing cover
    "199407": (2, None, None),   # Belt exit cover
    "199408": (2, None, None),   # Inner side shield
    "199409": (8, None, None),   # Decor cover
    "199410": (2, None, None),   # A-bracket outer trim
}
REASON = "Sold state from the nominated RFQ 26 loop 37 (REV8), set 2026-09"

LABELS = {"tool_cavities": "Cavities", "tool_cycle_time_s": "Target cycle time (s)",
          "tool_tonnage_class": "Tonnage class (t)", "toolmaker_id": "Toolmaker"}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="1994")
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--toolmaker", default=None, help="supplier name to set as toolmaker on all ten tools")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
        tools = (await s.execute(select(Part).where(
            Part.project_id == project.id, Part.item_category == "tool"))).scalars().all()
        by_number = {p.part_number: p for p in tools}

        toolmaker_id = None
        if args.toolmaker:
            supplier = (await s.execute(select(Supplier).where(Supplier.name == args.toolmaker))).scalar_one_or_none()
            if supplier is None:
                raise SystemExit(f"No supplier named {args.toolmaker!r}; create it on the Suppliers page first")
            toolmaker_id = supplier.id

        changes = []  # (part, field, old, new)
        for number, (cav, cycle, tonnage) in FIELDS.items():
            p = by_number.get(number)
            if p is None:
                print(f"   ! tool {number} not in project {args.project}")
                continue
            wanted = {"tool_cavities": cav, "tool_cycle_time_s": cycle, "tool_tonnage_class": tonnage}
            if toolmaker_id is not None:
                wanted["toolmaker_id"] = toolmaker_id
            for field, new in wanted.items():
                if new is None:
                    continue
                old = getattr(p, field)
                if old != new:
                    changes.append((p, field, old, new))

        print(f"== TOOL FIELDS ({len(changes)} changes)")
        for p, field, old, new in changes:
            print(f"   {p.part_number:<8} {LABELS[field]:<22} {old!r} -> {new!r}")
        if not args.apply:
            print("\nDRY RUN - nothing written.")
            await engine.dispose()
            return

        for p, field, old, new in changes:
            setattr(p, field, new)
            await ChangelogService.log_action(
                s, part_id=p.id, action="metadata_updated",
                action_description=f"{LABELS[field]} {old!r} -> {new!r}. {REASON}",
                performed_by=args.user, field_name=field,
                old_value=None if old is None else str(old), new_value=str(new))
        await s.commit()
        print("\nAPPLIED.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Read cycle time and tonnage from RFQ2 on prod and fill the table**

On prod (`source ~/.ssh/agent.env`, ssh to ktx-server), read loop 37 of RFQ 26:

```bash
docker exec -i rfq2-postgres-1 psql -U rfq_user -d rfq_db -c "\d tooling_variant_items"
docker exec -i rfq2-postgres-1 psql -U rfq_user -d rfq_db -c "select * from tooling_variant_items where tooling_calc_id in (204,205,206,207,208,209,210,211,212,213) order by tooling_calc_id;"
```

The tooling_calc ids 204..213 are the RFQ2 tool ids for 1994B tools 1..10 (`backend/scripts/import_brose.py` TOOLS). Confirm the loop column names from `\d` first, restrict to loop 37, then type `cycle_time_s` and tonnage (where the tooling inquiry sheet gives it) into `FIELDS`. Leave a value `None` when RFQ2 has none.

- [ ] **Step 3: Dry run in the prod backend container**

```bash
docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 python scripts/set_1994_tool_fields.py
```

Expected: a list of ten tools with the cavities (and any cycle/tonnage) diffs, then `DRY RUN - nothing written.` Only after the human confirms the numbers: rerun with `--apply` (and `--toolmaker "<name>"` once the toolmaker is known and exists as a supplier). Prod needs migration 077 applied first (`docker exec compose-plm2-backend-1 alembic upgrade head`, after a DB backup as in memory `live-db-is-postgres-2026-08-06`).

- [ ] **Step 4: Commit the script**

```bash
cd /home/nitrolinux/claude/plm2 && git add backend/scripts/set_1994_tool_fields.py
git commit -m "chore(scripts): set 1994 tool fields from RFQ 26 loop 37

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: DFM models and migration 078

**Files:**
- Create: `backend/app/models/dfm.py`
- Create: `backend/alembic/versions/078_dfm_archive.py`
- Create: `backend/tests/test_dfm_models.py`
- Modify: `backend/app/models/__init__.py`

**Interfaces:**
- Consumes: `Base` from `app.models.database`, `parts.id`, `users.id`.
- Produces: `DfmTopic(id, tool_part_id, title, status, opened_by, opened_at, closed_by, closed_at, entries)`, `DfmEntry(id, topic_id, party, addressed_to, note, supersedes_id, recorded_by, recorded_at, sent_at, files)`, `DfmEntryFile(id, entry_id, original_filename, saved_filename, file_size, content_type, uploaded_by, uploaded_at)`, constants `DFM_PARTIES = ("toolmaker", "ktx", "tier1")`, `DFM_TOPIC_OPEN = "open"`, `DFM_TOPIC_FINISHED = "finished_confirmed"`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_dfm_models.py`:

```python
"""DFM archive tables: a topic on a tool, entries in three columns, files per
entry, superseding chain. Pure model round-trip through the session."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import selectinload


async def _tool(session_factory, seed):
    from app.models.part import Part
    async with session_factory() as s:
        tool = Part(project_id=seed["project_id"], part_number="199403", name="ISOFIX Cover",
                    part_type="purchased", item_category="tool", created_by=seed["engineer_id"])
        s.add(tool)
        await s.commit()
        return tool.id


async def test_topic_entries_files_roundtrip(session_factory, seed):
    from app.models.dfm import DfmTopic, DfmEntry, DfmEntryFile, DFM_PARTIES, DFM_TOPIC_OPEN
    tool_id = await _tool(session_factory, seed)
    assert DFM_PARTIES == ("toolmaker", "ktx", "tier1")

    async with session_factory() as s:
        topic = DfmTopic(tool_part_id=tool_id, title="Gate position", opened_by=seed["engineer_id"])
        s.add(topic)
        await s.flush()
        assert topic.status == DFM_TOPIC_OPEN
        first = DfmEntry(topic_id=topic.id, party="ktx", addressed_to=["toolmaker", "tier1"],
                         note="DFM request rev A", recorded_by=seed["engineer_id"], sent_at=date(2026, 9, 24))
        s.add(first)
        await s.flush()
        s.add(DfmEntryFile(entry_id=first.id, original_filename="dfm_request_A.pdf", saved_filename="abc.pdf",
                           file_size=10, content_type="application/pdf", uploaded_by=seed["engineer_id"]))
        update = DfmEntry(topic_id=topic.id, party="ktx", addressed_to=["toolmaker"], note="rev B",
                          supersedes_id=first.id, recorded_by=seed["engineer_id"])
        s.add(update)
        await s.commit()
        topic_id = topic.id

    async with session_factory() as s:
        topic = (await s.execute(select(DfmTopic).where(DfmTopic.id == topic_id)
                                 .options(selectinload(DfmTopic.entries).selectinload(DfmEntry.files)))).scalar_one()
        assert topic.tool_part_id == tool_id
        assert [e.note for e in topic.entries] == ["DFM request rev A", "rev B"]
        assert topic.entries[0].addressed_to == ["toolmaker", "tier1"]
        assert topic.entries[0].sent_at == date(2026, 9, 24)
        assert topic.entries[0].files[0].original_filename == "dfm_request_A.pdf"
        assert topic.entries[1].supersedes_id == topic.entries[0].id
        assert topic.closed_at is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/nitrolinux/claude/plm2/backend && pytest tests/test_dfm_models.py -v -n 0`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.dfm'`.

- [ ] **Step 3: Write the models**

`backend/app/models/dfm.py`:

```python
"""DFM archive: per-tool topics, each a three-column ledger (toolmaker | KTX |
Tier 1) of append-only entries with files. Nothing here is deleted; an update
is a new entry that supersedes the old one, and the old one stays as history."""
from datetime import date, datetime

from sqlalchemy import String, Text, Date, DateTime, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

DFM_PARTIES = ("toolmaker", "ktx", "tier1")
DFM_TOPIC_OPEN = "open"
DFM_TOPIC_FINISHED = "finished_confirmed"
DFM_TOPIC_STATUSES = (DFM_TOPIC_OPEN, DFM_TOPIC_FINISHED)


class DfmTopic(Base):
    """One DFM question on one tool, closed by 'finished confirmed'."""
    __tablename__ = "dfm_topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    tool_part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default=DFM_TOPIC_OPEN, server_default=DFM_TOPIC_OPEN)

    opened_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    entries: Mapped[list["DfmEntry"]] = relationship(
        back_populates="topic", cascade="all, delete-orphan",
        order_by="DfmEntry.recorded_at, DfmEntry.id", lazy="selectin")


class DfmEntry(Base):
    """One row of the ledger, in its author's column (party)."""
    __tablename__ = "dfm_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("dfm_topics.id"), index=True)
    party: Mapped[str] = mapped_column(String(20))  # toolmaker | ktx | tier1
    addressed_to: Mapped[list] = mapped_column(JSON, default=list)  # one or two of the other parties
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("dfm_entries.id"), nullable=True)

    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))  # the KTX user who put it in
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sent_at: Mapped[date | None] = mapped_column(Date, nullable=True)  # mail date if different

    topic: Mapped["DfmTopic"] = relationship(back_populates="entries")
    files: Mapped[list["DfmEntryFile"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="DfmEntryFile.id", lazy="selectin")


class DfmEntryFile(Base):
    """A file attached to an entry. Kept forever with uploader and time."""
    __tablename__ = "dfm_entry_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("dfm_entries.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    saved_filename: Mapped[str] = mapped_column(String(255))  # <uuid><ext> under uploads/dfm/<tool>/<entry>/
    file_size: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(100))
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    entry: Mapped["DfmEntry"] = relationship(back_populates="files")
```

- [ ] **Step 4: Register the models**

In `backend/app/models/__init__.py` add after the `PartRelation` import block:

```python
from app.models.dfm import DfmTopic, DfmEntry, DfmEntryFile
```

and add `"DfmTopic", "DfmEntry", "DfmEntryFile",` to `__all__` after `"TestDataStatus",`.

- [ ] **Step 5: Write the guarded migration**

`backend/alembic/versions/078_dfm_archive.py`:

```python
"""078: DFM archive tables (dfm_topics, dfm_entries, dfm_entry_files).

Revision ID: 078
Revises: 077
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "dfm_topics" not in tables:
        op.create_table(
            "dfm_topics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tool_part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("opened_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("opened_at", sa.DateTime(), nullable=False),
            sa.Column("closed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_dfm_topics_tool_part_id", "dfm_topics", ["tool_part_id"])
    if "dfm_entries" not in tables:
        op.create_table(
            "dfm_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("topic_id", sa.Integer(), sa.ForeignKey("dfm_topics.id"), nullable=False),
            sa.Column("party", sa.String(20), nullable=False),
            sa.Column("addressed_to", sa.JSON(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("supersedes_id", sa.Integer(), sa.ForeignKey("dfm_entries.id"), nullable=True),
            sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.Column("sent_at", sa.Date(), nullable=True),
        )
        op.create_index("ix_dfm_entries_topic_id", "dfm_entries", ["topic_id"])
    if "dfm_entry_files" not in tables:
        op.create_table(
            "dfm_entry_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("entry_id", sa.Integer(), sa.ForeignKey("dfm_entries.id"), nullable=False),
            sa.Column("original_filename", sa.String(255), nullable=False),
            sa.Column("saved_filename", sa.String(255), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False),
            sa.Column("content_type", sa.String(100), nullable=False),
            sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_dfm_entry_files_entry_id", "dfm_entry_files", ["entry_id"])


def downgrade() -> None:
    insp = inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for name in ("dfm_entry_files", "dfm_entries", "dfm_topics"):
        if name in tables:
            op.drop_table(name)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd /home/nitrolinux/claude/plm2/backend && pytest tests/test_dfm_models.py -v -n 0`
Expected: PASS.

- [ ] **Step 7: Check the migration on the scratch SQLite DB**

Run the same two `alembic upgrade head` invocations as Task 1 Step 9 (same scratch DB path). Expected: 078 applies once, the re-run is a no-op.

- [ ] **Step 8: Commit**

```bash
cd /home/nitrolinux/claude/plm2 && git add backend/app/models/dfm.py backend/app/models/__init__.py backend/alembic/versions/078_dfm_archive.py backend/tests/test_dfm_models.py
git commit -m "feat(dfm): topic, entry and file models with migration 078

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: DFM service and topic endpoints

**Files:**
- Create: `backend/app/services/dfm_service.py`
- Create: `backend/app/api/v1/items/dfm.py`
- Create: `backend/tests/test_dfm_topics.py`
- Modify: `backend/app/api/v1/__init__.py`

**Interfaces:**
- Consumes: `DfmTopic`, `DfmEntry`, `DfmEntryFile`, `DFM_PARTIES`, `DFM_TOPIC_OPEN`, `DFM_TOPIC_FINISHED` (Task 3); `PartService.get_part`; `ChangelogService.log_action`; `_uploader_names` pattern from `revision_files.py` (re-implemented here as `user_names`).
- Produces:
  - `DfmError(ValueError)` with `.status` (400) and `DfmClosed(DfmError)` (409).
  - `DfmService.load_topic(session, tool_part_id, topic_id) -> DfmTopic` (raises `DfmError("Topic not found")` with status 404).
  - `DfmService.open_topic(session, tool, title, user_id) -> DfmTopic`
  - `DfmService.close_topic(session, tool, topic, user_id)`, `DfmService.reopen_topic(...)`
  - `DfmService.topic_summary(topic) -> dict` keys `id, tool_part_id, title, status, opened_by, opened_at, closed_by, closed_at, entry_count, last_activity`
  - `DfmService.topic_detail(topic, names) -> dict` = summary plus `entries: [entry_dict]` where `entry_dict` keys are `id, topic_id, party, addressed_to, note, sent_at, supersedes_id, recorded_by, recorded_by_name, recorded_at, files: [file_dict], history: [entry_dict without history]` and `file_dict` keys `id, entry_id, original_filename, file_size, content_type, uploaded_by, uploaded_by_name, uploaded_at`.
  - Router routes (all under `/parts/{part_id}/dfm`): `GET /topics`, `POST /topics`, `GET /topics/{topic_id}`, `POST /topics/{topic_id}/close`, `POST /topics/{topic_id}/reopen`. Entries and files come in Tasks 5 and 6.
  - Changelog actions written on the tool part: `dfm_topic_opened`, `dfm_topic_closed`, `dfm_topic_reopened` (Task 5 adds `dfm_entry_recorded`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_dfm_topics.py`:

```python
"""DFM topics on a tool: open, list, close (finished confirmed), reopen.
Only tools have an archive."""


async def make_tool(client, eng_auth, seed, number="199403", item_category="tool"):
    res = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": number, "name": "ISOFIX Cover",
        "part_type": "purchased", "data_classification": "confidential", "item_category": item_category,
    }, headers=eng_auth)
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def test_open_list_close_reopen(client, eng_auth, seed):
    tool = await make_tool(client, eng_auth, seed)

    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=eng_auth)
    assert res.status_code == 200 and res.json() == []

    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics", json={"title": "Gate position"}, headers=eng_auth)
    assert res.status_code == 201, res.text
    topic = res.json()
    assert topic["status"] == "open"
    assert topic["title"] == "Gate position"
    assert topic["opened_by"] == seed["engineer_id"]
    assert topic["entry_count"] == 0
    assert topic["last_activity"] == topic["opened_at"]
    assert topic["closed_at"] is None

    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=eng_auth)
    assert [t["id"] for t in res.json()] == [topic["id"]]

    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics/{topic['id']}", headers=eng_auth)
    assert res.status_code == 200
    assert res.json()["entries"] == []

    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic['id']}/close", headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "finished_confirmed"
    assert res.json()["closed_by"] == seed["engineer_id"]
    assert res.json()["closed_at"] is not None

    # closing twice is a no-op conflict
    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic['id']}/close", headers=eng_auth)
    assert res.status_code == 409

    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic['id']}/reopen", headers=eng_auth)
    assert res.status_code == 200
    assert res.json()["status"] == "open"
    assert res.json()["closed_at"] is None

    res = await client.get(f"/api/v1/parts/{tool}/changelog", headers=eng_auth)
    actions = [e["action"] for e in res.json()]
    assert actions.count("dfm_topic_opened") == 1
    assert actions.count("dfm_topic_closed") == 1
    assert actions.count("dfm_topic_reopened") == 1


async def test_title_required(client, eng_auth, seed):
    tool = await make_tool(client, eng_auth, seed)
    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics", json={"title": "   "}, headers=eng_auth)
    assert res.status_code == 422


async def test_dfm_only_on_tools(client, eng_auth, seed):
    article = await make_tool(client, eng_auth, seed, number="20-1994-003-0", item_category="article")
    res = await client.get(f"/api/v1/parts/{article}/dfm/topics", headers=eng_auth)
    assert res.status_code == 400
    assert res.json()["detail"] == "Only tools have a DFM archive"
    res = await client.post(f"/api/v1/parts/{article}/dfm/topics", json={"title": "x"}, headers=eng_auth)
    assert res.status_code == 400
    res = await client.get("/api/v1/parts/999999/dfm/topics", headers=eng_auth)
    assert res.status_code == 404


async def test_topic_belongs_to_its_tool(client, eng_auth, seed):
    tool_a = await make_tool(client, eng_auth, seed, number="199403")
    tool_b = await make_tool(client, eng_auth, seed, number="199404")
    topic = (await client.post(f"/api/v1/parts/{tool_a}/dfm/topics", json={"title": "Gate"}, headers=eng_auth)).json()
    res = await client.get(f"/api/v1/parts/{tool_b}/dfm/topics/{topic['id']}", headers=eng_auth)
    assert res.status_code == 404


async def test_requires_login(client, seed, eng_auth):
    tool = await make_tool(client, eng_auth, seed)
    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics")
    assert res.status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/backend && pytest tests/test_dfm_topics.py -v -n 0`
Expected: FAIL with 404s on every `/dfm/` route (router does not exist).

- [ ] **Step 3: Write the service**

`backend/app/services/dfm_service.py`:

```python
"""DFM archive service: topics per tool, append-only entries in three columns,
files on disk under uploads/dfm/<tool>/<entry>/. Nothing is deleted; an
update is a new entry that supersedes the old one."""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dfm import (
    DfmEntry, DfmEntryFile, DfmTopic, DFM_PARTIES, DFM_TOPIC_FINISHED, DFM_TOPIC_OPEN,
)
from app.models.entities import User
from app.models.part import Part
from app.services.part_service import ChangelogService

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB, same as revision files
TOPIC_CLOSED_MESSAGE = "Topic is finished, reopen it first"


class DfmError(ValueError):
    """Rule violation; .status is the HTTP status the router answers with."""
    status = 400

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        if status is not None:
            self.status = status


class DfmClosed(DfmError):
    status = 409


def dfm_dir(tool_part_id: int, entry_id: int) -> str:
    return os.path.join(os.getcwd(), "uploads", "dfm", str(tool_part_id), str(entry_id))


def file_path(tool_part_id: int, f: DfmEntryFile) -> str:
    return os.path.join(dfm_dir(tool_part_id, f.entry_id), f.saved_filename)


def _iso(v: datetime | date | None) -> str | None:
    return v.isoformat() if v else None


async def user_names(session: AsyncSession, user_ids: set) -> dict:
    """id -> display name in one query; lists never resolve users per row."""
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    rows = (await session.execute(
        select(User.id, User.full_name, User.username).where(User.id.in_(ids)))).all()
    return {uid: (full or username) for uid, full, username in rows}


def parse_addressed_to(raw: str | list | None, party: str) -> list[str]:
    """The form sends addressed_to as a JSON string; accept a list too. It must
    name one or two of the *other* parties."""
    if raw is None or raw == "":
        raise DfmError("addressed_to is required")
    value = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            raise DfmError("addressed_to must be a JSON list of parties")
    if not isinstance(value, list) or not value:
        raise DfmError("addressed_to must name at least one other party")
    seen: list[str] = []
    for p in value:
        if p not in DFM_PARTIES:
            raise DfmError(f"Unknown party '{p}'. Valid: {', '.join(DFM_PARTIES)}")
        if p == party:
            raise DfmError("An entry cannot be addressed to its own party")
        if p not in seen:
            seen.append(p)
    return seen


def parse_sent_at(raw: str | None) -> date | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise DfmError("sent_at must be a date (YYYY-MM-DD)")


class DfmService:

    @staticmethod
    async def load_topic(session: AsyncSession, tool_part_id: int, topic_id: int) -> DfmTopic:
        topic = (await session.execute(select(DfmTopic).where(
            DfmTopic.id == topic_id, DfmTopic.tool_part_id == tool_part_id))).scalar_one_or_none()
        if topic is None:
            raise DfmError("Topic not found", status=404)
        return topic

    @staticmethod
    async def list_topics(session: AsyncSession, tool_part_id: int) -> list[DfmTopic]:
        return list((await session.execute(
            select(DfmTopic).where(DfmTopic.tool_part_id == tool_part_id)
            .order_by(DfmTopic.opened_at.desc(), DfmTopic.id.desc()))).scalars().all())

    @staticmethod
    async def open_topic(session: AsyncSession, tool: Part, title: str, user_id: int) -> DfmTopic:
        topic = DfmTopic(tool_part_id=tool.id, title=title.strip(), opened_by=user_id)
        session.add(topic)
        await session.flush()
        await ChangelogService.log_action(
            session, part_id=tool.id, action="dfm_topic_opened",
            action_description=f"DFM topic opened: {topic.title}", performed_by=user_id)
        return topic

    @staticmethod
    async def close_topic(session: AsyncSession, tool: Part, topic: DfmTopic, user_id: int) -> DfmTopic:
        if topic.status == DFM_TOPIC_FINISHED:
            raise DfmClosed("Topic is already finished")
        topic.status = DFM_TOPIC_FINISHED
        topic.closed_by = user_id
        topic.closed_at = datetime.utcnow()
        await ChangelogService.log_action(
            session, part_id=tool.id, action="dfm_topic_closed",
            action_description=f"DFM topic finished confirmed: {topic.title}", performed_by=user_id)
        return topic

    @staticmethod
    async def reopen_topic(session: AsyncSession, tool: Part, topic: DfmTopic, user_id: int) -> DfmTopic:
        if topic.status == DFM_TOPIC_OPEN:
            raise DfmClosed("Topic is already open")
        topic.status = DFM_TOPIC_OPEN
        topic.closed_by = None
        topic.closed_at = None
        await ChangelogService.log_action(
            session, part_id=tool.id, action="dfm_topic_reopened",
            action_description=f"DFM topic reopened: {topic.title}", performed_by=user_id)
        return topic

    @staticmethod
    async def record_entry(session: AsyncSession, tool: Part, topic: DfmTopic, *, party: str,
                           addressed_to: str | list | None, note: str | None, sent_at: str | None,
                           supersedes_id: int | None, files: list[tuple[str, bytes, str | None]],
                           user_id: int) -> DfmEntry:
        """files: (original filename, bytes, content type). The row is flushed
        first for its id, the files are written, then the file rows are added;
        the caller commits. A failed write removes what was written and raises,
        so nothing is recorded."""
        if topic.status != DFM_TOPIC_OPEN:
            raise DfmClosed(TOPIC_CLOSED_MESSAGE)
        if party not in DFM_PARTIES:
            raise DfmError(f"Unknown party '{party}'. Valid: {', '.join(DFM_PARTIES)}")
        targets = parse_addressed_to(addressed_to, party)
        sent = parse_sent_at(sent_at)
        if supersedes_id is not None:
            old = await session.get(DfmEntry, supersedes_id)
            if old is None or old.topic_id != topic.id:
                raise DfmError("The entry to update is not in this topic")
            if old.party != party:
                raise DfmError("An entry can only be updated from its own column")
        for name, contents, _ in files:
            if not (name or "").strip():
                raise DfmError("A file needs a filename")
            if len(contents) > MAX_FILE_SIZE:
                raise DfmError(f"File {name} is over 100MB")

        entry = DfmEntry(topic_id=topic.id, party=party, addressed_to=targets,
                         note=(note or "").strip() or None, sent_at=sent,
                         supersedes_id=supersedes_id, recorded_by=user_id)
        session.add(entry)
        await session.flush()

        target_dir = dfm_dir(tool.id, entry.id)
        written: list[str] = []
        try:
            if files:
                os.makedirs(target_dir, exist_ok=True)
            for name, contents, content_type in files:
                ext = os.path.splitext(name)[1].lower()
                saved = f"{uuid.uuid4().hex}{ext}"
                path = os.path.join(target_dir, saved)
                with open(path, "wb") as fh:
                    fh.write(contents)
                written.append(path)
                session.add(DfmEntryFile(
                    entry_id=entry.id, original_filename=name, saved_filename=saved,
                    file_size=len(contents),
                    content_type=content_type or mimetypes.guess_type(name)[0] or "application/octet-stream",
                    uploaded_by=user_id))
            await session.flush()
            await session.refresh(entry, attribute_names=["files"])
            what = "updated" if supersedes_id else "recorded"
            await ChangelogService.log_action(
                session, part_id=tool.id, action="dfm_entry_recorded",
                action_description=f"DFM entry {what} in {topic.title} by {party} to {', '.join(targets)}"
                                   + (f" with {len(files)} file(s)" if files else ""),
                performed_by=user_id)
        except Exception:
            for path in written:
                try:
                    os.remove(path)
                except OSError:
                    pass
            raise
        return entry

    # ---- response shaping -------------------------------------------------

    @staticmethod
    def topic_summary(topic: DfmTopic) -> dict:
        stamps = [topic.opened_at] + [e.recorded_at for e in topic.entries]
        if topic.closed_at:
            stamps.append(topic.closed_at)
        return {
            "id": topic.id, "tool_part_id": topic.tool_part_id, "title": topic.title,
            "status": topic.status,
            "opened_by": topic.opened_by, "opened_at": _iso(topic.opened_at),
            "closed_by": topic.closed_by, "closed_at": _iso(topic.closed_at),
            "entry_count": len(topic.entries),
            "last_activity": _iso(max(s for s in stamps if s is not None)),
        }

    @staticmethod
    def file_dict(f: DfmEntryFile, names: dict) -> dict:
        return {
            "id": f.id, "entry_id": f.entry_id, "original_filename": f.original_filename,
            "file_size": f.file_size, "content_type": f.content_type,
            "uploaded_by": f.uploaded_by, "uploaded_by_name": names.get(f.uploaded_by),
            "uploaded_at": _iso(f.uploaded_at),
        }

    @staticmethod
    def entry_dict(e: DfmEntry, names: dict) -> dict:
        return {
            "id": e.id, "topic_id": e.topic_id, "party": e.party,
            "addressed_to": list(e.addressed_to or []), "note": e.note,
            "sent_at": _iso(e.sent_at), "supersedes_id": e.supersedes_id,
            "recorded_by": e.recorded_by, "recorded_by_name": names.get(e.recorded_by),
            "recorded_at": _iso(e.recorded_at),
            "files": [DfmService.file_dict(f, names) for f in e.files],
        }

    @staticmethod
    def topic_detail(topic: DfmTopic, names: dict) -> dict:
        """Entries in time order with each supersede chain collapsed onto its
        newest entry; `history` lists the earlier versions, newest first."""
        by_id = {e.id: e for e in topic.entries}
        superseded = {e.supersedes_id for e in topic.entries if e.supersedes_id is not None}
        entries = []
        for e in topic.entries:  # already ordered by recorded_at, id
            if e.id in superseded:
                continue
            d = DfmService.entry_dict(e, names)
            history = []
            cursor = by_id.get(e.supersedes_id) if e.supersedes_id else None
            while cursor is not None:
                history.append(DfmService.entry_dict(cursor, names))
                cursor = by_id.get(cursor.supersedes_id) if cursor.supersedes_id else None
            d["history"] = history
            entries.append(d)
        return {**DfmService.topic_summary(topic), "entries": entries}

    @staticmethod
    def user_ids(topic: DfmTopic) -> set:
        ids = {topic.opened_by, topic.closed_by}
        for e in topic.entries:
            ids.add(e.recorded_by)
            ids.update(f.uploaded_by for f in e.files)
        return ids
```

- [ ] **Step 4: Write the router (topics only for now)**

`backend/app/api/v1/items/dfm.py`:

```python
"""DFM archive endpoints: /parts/{part_id}/dfm/... . part_id must be a tool."""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.part import Part
from app.services.dfm_service import DfmError, DfmService, user_names
from app.services.part_service import PartService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parts", tags=["dfm"])

NOT_A_TOOL = "Only tools have a DFM archive"


class TopicCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v.strip()


async def _load_tool(db: AsyncSession, part_id: int) -> Part:
    part = await PartService.get_part(db, part_id)
    if part is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
    if part.item_category != "tool":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NOT_A_TOOL)
    return part


async def _topic(db: AsyncSession, tool: Part, topic_id: int):
    try:
        return await DfmService.load_topic(db, tool.id, topic_id)
    except DfmError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


async def _detail(db: AsyncSession, topic) -> dict:
    await db.refresh(topic, attribute_names=["entries"])
    names = await user_names(db, DfmService.user_ids(topic))
    return DfmService.topic_detail(topic, names)


@router.get("/{part_id}/dfm/topics", response_model=List[dict])
async def list_topics(part_id: int, current_user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    tool = await _load_tool(db, part_id)
    return [DfmService.topic_summary(t) for t in await DfmService.list_topics(db, tool.id)]


@router.post("/{part_id}/dfm/topics", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_topic(part_id: int, body: TopicCreate, current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    tool = await _load_tool(db, part_id)
    topic = await DfmService.open_topic(db, tool, body.title, current_user.id)
    await db.commit()
    await db.refresh(topic, attribute_names=["entries"])
    return DfmService.topic_summary(topic)


@router.get("/{part_id}/dfm/topics/{topic_id}", response_model=dict)
async def get_topic(part_id: int, topic_id: int, current_user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    tool = await _load_tool(db, part_id)
    return await _detail(db, await _topic(db, tool, topic_id))


@router.post("/{part_id}/dfm/topics/{topic_id}/close", response_model=dict)
async def close_topic(part_id: int, topic_id: int, current_user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    tool = await _load_tool(db, part_id)
    topic = await _topic(db, tool, topic_id)
    try:
        await DfmService.close_topic(db, tool, topic, current_user.id)
    except DfmError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    await db.commit()
    return await _detail(db, topic)


@router.post("/{part_id}/dfm/topics/{topic_id}/reopen", response_model=dict)
async def reopen_topic(part_id: int, topic_id: int, current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    tool = await _load_tool(db, part_id)
    topic = await _topic(db, tool, topic_id)
    try:
        await DfmService.reopen_topic(db, tool, topic, current_user.id)
    except DfmError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    await db.commit()
    return await _detail(db, topic)
```

(The `File`, `Form`, `UploadFile`, `FileResponse`, `Optional` imports are used by Tasks 5 and 6; leave them in.)

- [ ] **Step 5: Include the router**

In `backend/app/api/v1/__init__.py` add after the `process_flow` import:

```python
from app.api.v1.items.dfm import router as dfm_router
```

and after `api_router.include_router(process_flow_router)`:

```python
api_router.include_router(dfm_router)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2/backend && pytest tests/test_dfm_topics.py -v -n 0`
Expected: all PASS. If `test_title_required` returns 400 instead of 422 check the validator raises `ValueError` (Pydantic turns it into 422).

- [ ] **Step 7: Commit**

```bash
cd /home/nitrolinux/claude/plm2 && git add backend/app/services/dfm_service.py backend/app/api/v1/items/dfm.py backend/app/api/v1/__init__.py backend/tests/test_dfm_topics.py
git commit -m "feat(dfm): topics per tool with open, close and reopen

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Entries with files and the supersede chain

**Files:**
- Create: `backend/tests/test_dfm_entries.py`
- Modify: `backend/app/api/v1/items/dfm.py` (add the entries route)

**Interfaces:**
- Consumes: `DfmService.record_entry(...)`, `DfmService.topic_detail`, `DfmClosed`, `TOPIC_CLOSED_MESSAGE` (Task 4).
- Produces: `POST /parts/{part_id}/dfm/topics/{topic_id}/entries` multipart with form fields `party`, `addressed_to` (JSON list string), `note`, `sent_at`, `supersedes_id`, and repeated `files`; returns the entry dict (with `history`) and 201.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_dfm_entries.py`:

```python
"""DFM entries: three columns, addressed-to, files, supersede chain collapsed
into history, closed topics refuse entries."""
import json

from tests.test_dfm_topics import make_tool


async def make_topic(client, eng_auth, tool, title="Gate position"):
    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics", json={"title": title}, headers=eng_auth)
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def post_entry(client, eng_auth, tool, topic, party="ktx", addressed_to=("toolmaker", "tier1"),
                     note="DFM request rev A", sent_at="2026-09-24", supersedes_id=None, files=()):
    data = {"party": party, "addressed_to": json.dumps(list(addressed_to)), "note": note, "sent_at": sent_at}
    if supersedes_id is not None:
        data["supersedes_id"] = str(supersedes_id)
    multipart = [("files", (name, payload, ctype)) for name, payload, ctype in files]
    return await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/entries",
                             data=data, files=multipart or None, headers=eng_auth)


async def test_entry_with_two_files(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)

    res = await post_entry(client, eng_auth, tool, topic, files=[
        ("dfm_request_A.pdf", b"%PDF-1.4 a", "application/pdf"),
        ("volumes.xlsx", b"PK...", None),
    ])
    assert res.status_code == 201, res.text
    entry = res.json()
    assert entry["party"] == "ktx"
    assert entry["addressed_to"] == ["toolmaker", "tier1"]
    assert entry["note"] == "DFM request rev A"
    assert entry["sent_at"] == "2026-09-24"
    assert entry["recorded_by"] == seed["engineer_id"]
    assert entry["recorded_by_name"] == "Engineer"
    assert entry["history"] == []
    assert [f["original_filename"] for f in entry["files"]] == ["dfm_request_A.pdf", "volumes.xlsx"]
    assert entry["files"][0]["content_type"] == "application/pdf"
    assert entry["files"][1]["content_type"].startswith("application/")
    assert entry["files"][0]["uploaded_by_name"] == "Engineer"
    saved = tmp_path / "uploads" / "dfm" / str(tool) / str(entry["id"])
    assert len(list(saved.iterdir())) == 2

    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=eng_auth)
    assert res.json()[0]["entry_count"] == 1
    assert res.json()[0]["last_activity"] == entry["recorded_at"]

    res = await client.get(f"/api/v1/parts/{tool}/changelog", headers=eng_auth)
    assert any(e["action"] == "dfm_entry_recorded" and "2 file(s)" in e["action_description"] for e in res.json())


async def test_closed_topic_refuses_entries_until_reopened(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    assert (await post_entry(client, eng_auth, tool, topic)).status_code == 201

    assert (await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/close", headers=eng_auth)).status_code == 200
    res = await post_entry(client, eng_auth, tool, topic, party="toolmaker", addressed_to=["ktx"], note="late")
    assert res.status_code == 409
    assert res.json()["detail"] == "Topic is finished, reopen it first"

    assert (await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/reopen", headers=eng_auth)).status_code == 200
    res = await post_entry(client, eng_auth, tool, topic, party="toolmaker", addressed_to=["ktx"], note="late")
    assert res.status_code == 201


async def test_update_supersedes_and_keeps_history(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    first = (await post_entry(client, eng_auth, tool, topic, note="answer, 3 points open")).json()
    other = (await post_entry(client, eng_auth, tool, topic, party="toolmaker", addressed_to=["ktx"], note="study r1")).json()
    second = (await post_entry(client, eng_auth, tool, topic, note="answer, 2 points open", supersedes_id=first["id"])).json()
    assert second["supersedes_id"] == first["id"]
    third = (await post_entry(client, eng_auth, tool, topic, note="answer, 1 point open", supersedes_id=second["id"])).json()

    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics/{topic}", headers=eng_auth)
    detail = res.json()
    # newest of the chain only, at its own time; the toolmaker entry stays in between
    assert [e["id"] for e in detail["entries"]] == [other["id"], third["id"]]
    top = detail["entries"][1]
    assert top["note"] == "answer, 1 point open"
    assert [h["note"] for h in top["history"]] == ["answer, 2 points open", "answer, 3 points open"]
    assert "history" not in top["history"][0]
    assert detail["entry_count"] == 4


async def test_supersede_guards(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic_a = await make_topic(client, eng_auth, tool, "A")
    topic_b = await make_topic(client, eng_auth, tool, "B")
    in_a = (await post_entry(client, eng_auth, tool, topic_a)).json()

    res = await post_entry(client, eng_auth, tool, topic_b, supersedes_id=in_a["id"])
    assert res.status_code == 400
    assert "not in this topic" in res.json()["detail"]

    res = await post_entry(client, eng_auth, tool, topic_a, party="toolmaker", addressed_to=["ktx"], supersedes_id=in_a["id"])
    assert res.status_code == 400
    assert "own column" in res.json()["detail"]

    res = await post_entry(client, eng_auth, tool, topic_a, supersedes_id=999999)
    assert res.status_code == 400


async def test_addressed_to_rules(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    assert (await post_entry(client, eng_auth, tool, topic, party="ktx", addressed_to=["ktx"])).status_code == 400
    assert (await post_entry(client, eng_auth, tool, topic, party="ktx", addressed_to=["brose"])).status_code == 400
    assert (await post_entry(client, eng_auth, tool, topic, party="ktx", addressed_to=[])).status_code == 400
    assert (await post_entry(client, eng_auth, tool, topic, party="brose", addressed_to=["ktx"])).status_code == 400
    res = await post_entry(client, eng_auth, tool, topic, party="tier1", addressed_to=["ktx", "ktx"])
    assert res.status_code == 201
    assert res.json()["addressed_to"] == ["ktx"]


async def test_bare_entry_and_blank_sent_at(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    res = await post_entry(client, eng_auth, tool, topic, note="", sent_at="")
    assert res.status_code == 201, res.text
    assert res.json()["note"] is None
    assert res.json()["sent_at"] is None
    assert res.json()["files"] == []
    assert (await post_entry(client, eng_auth, tool, topic, sent_at="yesterday")).status_code == 400
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/backend && pytest tests/test_dfm_entries.py -v -n 0`
Expected: FAIL, every `post_entry` gets 404 / 405 (route missing).

- [ ] **Step 3: Add the entries route**

Append to `backend/app/api/v1/items/dfm.py`:

```python
@router.post("/{part_id}/dfm/topics/{topic_id}/entries", response_model=dict,
             status_code=status.HTTP_201_CREATED)
async def create_entry(
    part_id: int,
    topic_id: int,
    party: str = Form(...),
    addressed_to: str = Form(..., description="JSON list of the other parties"),
    note: Optional[str] = Form(None),
    sent_at: Optional[str] = Form(None),
    supersedes_id: Optional[int] = Form(None),
    files: List[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record one ledger entry in `party`'s column, optionally with files and
    as an update of one of that column's earlier entries."""
    tool = await _load_tool(db, part_id)
    topic = await _topic(db, tool, topic_id)
    payloads = [(f.filename or "", await f.read(), f.content_type) for f in files]
    try:
        entry = await DfmService.record_entry(
            db, tool, topic, party=party, addressed_to=addressed_to, note=note, sent_at=sent_at,
            supersedes_id=supersedes_id, files=payloads, user_id=current_user.id)
        await db.commit()
    except DfmError as e:
        await db.rollback()
        raise HTTPException(status_code=e.status, detail=str(e))
    except Exception as e:
        await db.rollback()
        logger.error(f"DFM entry on topic {topic_id} failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not store the entry")
    names = await user_names(db, {current_user.id})
    d = DfmService.entry_dict(entry, names)
    d["history"] = []
    if entry.supersedes_id:
        await db.refresh(topic, attribute_names=["entries"])
        names = await user_names(db, DfmService.user_ids(topic))
        detail = DfmService.topic_detail(topic, names)
        d = next(x for x in detail["entries"] if x["id"] == entry.id)
    return d
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2/backend && pytest tests/test_dfm_entries.py tests/test_dfm_topics.py -v -n 0`
Expected: all PASS. If `files=None` in the helper trips httpx, replace `multipart or None` with `multipart` and send `data` alone when empty; the route must accept a request with no `files` part at all (`test_bare_entry_and_blank_sent_at`).

- [ ] **Step 5: Commit**

```bash
cd /home/nitrolinux/claude/plm2 && git add backend/app/api/v1/items/dfm.py backend/tests/test_dfm_entries.py
git commit -m "feat(dfm): ledger entries with files and supersede history

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: File download and inline, storage failure

**Files:**
- Create: `backend/tests/test_dfm_files.py`
- Modify: `backend/app/api/v1/items/dfm.py` (add two file routes)

**Interfaces:**
- Consumes: `file_path(tool_part_id, DfmEntryFile)` from `dfm_service`, `DfmEntryFile`, `DfmEntry`, `DfmTopic`.
- Produces: `GET /parts/{part_id}/dfm/files/{file_id}/download` (attachment, original filename), `GET /parts/{part_id}/dfm/files/{file_id}/inline` (PDF only, `Content-Disposition: inline`, 415 otherwise). Note: the spec spells these `/dfm-files/{file_id}/...`; they sit under `/parts/{part_id}/dfm/files/...` so the tool check applies. `frontend/src/api/dfm.ts` (Task 11) builds URLs from this shape.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_dfm_files.py`:

```python
"""DFM files: download the stored bytes, PDFs inline for the document pane,
and a storage failure records nothing."""
import os

from tests.test_dfm_entries import make_topic, post_entry
from tests.test_dfm_topics import make_tool


async def _entry_with(client, eng_auth, seed, files):
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    res = await post_entry(client, eng_auth, tool, topic, files=files)
    assert res.status_code == 201, res.text
    return tool, topic, res.json()


async def test_download_returns_stored_bytes(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool, _, entry = await _entry_with(client, eng_auth, seed, [("ISOFIX_DFM_r1.pdf", b"%PDF-1.4 r1", "application/pdf")])
    fid = entry["files"][0]["id"]
    res = await client.get(f"/api/v1/parts/{tool}/dfm/files/{fid}/download", headers=eng_auth)
    assert res.status_code == 200
    assert res.content == b"%PDF-1.4 r1"
    assert res.headers["content-disposition"].startswith("attachment")
    assert "ISOFIX_DFM_r1.pdf" in res.headers["content-disposition"]


async def test_inline_pdf_only(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool, _, entry = await _entry_with(client, eng_auth, seed, [
        ("study.pdf", b"%PDF-1.4 s", "application/pdf"),
        ("mail.msg", b"mail", "application/vnd.ms-outlook"),
    ])
    pdf_id, msg_id = entry["files"][0]["id"], entry["files"][1]["id"]
    res = await client.get(f"/api/v1/parts/{tool}/dfm/files/{pdf_id}/inline", headers=eng_auth)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/pdf")
    assert res.headers["content-disposition"].startswith("inline")
    assert (await client.get(f"/api/v1/parts/{tool}/dfm/files/{msg_id}/inline", headers=eng_auth)).status_code == 415


async def test_file_must_belong_to_the_tool(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool, _, entry = await _entry_with(client, eng_auth, seed, [("a.pdf", b"%PDF a", "application/pdf")])
    other = await make_tool(client, eng_auth, seed, number="199404")
    fid = entry["files"][0]["id"]
    assert (await client.get(f"/api/v1/parts/{other}/dfm/files/{fid}/download", headers=eng_auth)).status_code == 404
    assert (await client.get(f"/api/v1/parts/{tool}/dfm/files/999999/download", headers=eng_auth)).status_code == 404


async def test_missing_on_disk_is_404(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool, _, entry = await _entry_with(client, eng_auth, seed, [("a.pdf", b"%PDF a", "application/pdf")])
    folder = tmp_path / "uploads" / "dfm" / str(tool) / str(entry["id"])
    for name in os.listdir(folder):
        os.remove(folder / name)
    fid = entry["files"][0]["id"]
    assert (await client.get(f"/api/v1/parts/{tool}/dfm/files/{fid}/download", headers=eng_auth)).status_code == 404


async def test_storage_failure_records_nothing(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)

    import app.services.dfm_service as svc

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(svc.os, "makedirs", boom)

    res = await post_entry(client, eng_auth, tool, topic, files=[("a.pdf", b"%PDF a", "application/pdf")])
    assert res.status_code == 500
    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics/{topic}", headers=eng_auth)
    assert res.json()["entries"] == []
    assert res.json()["entry_count"] == 0
    assert not (tmp_path / "uploads" / "dfm").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/backend && pytest tests/test_dfm_files.py -v -n 0`
Expected: download/inline tests FAIL with 404 (route missing); `test_storage_failure_records_nothing` may already pass.

- [ ] **Step 3: Add the file routes**

Append to `backend/app/api/v1/items/dfm.py` (add `from sqlalchemy import select` and `from app.models.dfm import DfmEntry, DfmEntryFile, DfmTopic` and `from app.services.dfm_service import file_path` to the imports, plus `import os`):

```python
async def _load_file(db: AsyncSession, tool: Part, file_id: int) -> tuple[DfmEntryFile, str]:
    row = (await db.execute(
        select(DfmEntryFile)
        .join(DfmEntry, DfmEntry.id == DfmEntryFile.entry_id)
        .join(DfmTopic, DfmTopic.id == DfmEntry.topic_id)
        .where(DfmEntryFile.id == file_id, DfmTopic.tool_part_id == tool.id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    path = file_path(tool.id, row)
    if not os.path.exists(path):
        logger.error(f"DFM file missing on disk: {path}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")
    return row, path


@router.get("/{part_id}/dfm/files/{file_id}/download")
async def download_dfm_file(part_id: int, file_id: int, current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    tool = await _load_tool(db, part_id)
    row, path = await _load_file(db, tool, file_id)
    return FileResponse(path=path, filename=row.original_filename, media_type="application/octet-stream")


@router.get("/{part_id}/dfm/files/{file_id}/inline")
async def inline_dfm_file(part_id: int, file_id: int, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """PDF for the document pane. Everything else downloads."""
    tool = await _load_tool(db, part_id)
    row, path = await _load_file(db, tool, file_id)
    if not row.original_filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Only PDF can be shown inline")
    return FileResponse(path=path, media_type="application/pdf", filename=row.original_filename,
                        content_disposition_type="inline")
```

The download and inline routes require login (the revision-file ones do not); the document pane `<iframe>` sends the session cookie, so this is fine.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2/backend && pytest tests/test_dfm_files.py tests/test_dfm_entries.py tests/test_dfm_topics.py tests/test_dfm_models.py -v -n 0`
Expected: all PASS.

- [ ] **Step 5: Run the whole backend suite**

Run: `cd /home/nitrolinux/claude/plm2/backend && pytest`
Expected: all PASS (no regressions in `test_revision_files`, `test_part_relations`, `test_item_categories`).

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2 && git add backend/app/api/v1/items/dfm.py backend/tests/test_dfm_files.py
git commit -m "feat(dfm): file download and inline PDF

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Relations carry the other part's active revision (backend)

The produced-article chips need `E1 · 003` from each article's active revision. The relations list already resolves the other part; add its active revision name and customer index so the tool page needs no per-article fetch.

**Files:**
- Modify: `backend/app/api/v1/items/part_relations.py` (`_relation_dict`)
- Modify: `backend/tests/test_part_relations.py` (append one test)

**Interfaces:**
- Consumes: `Part.revisions` (lazy selectin), `Part.active_revision_id`.
- Produces: two more keys on every relation dict: `other_active_revision_name: str|None`, `other_active_customer_index: str|None`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_part_relations.py`:

```python
async def test_relation_carries_other_active_revision(client, eng_auth, seed):
    article = await _create(client, eng_auth, seed, "20-1994-003-0", "206.887.233 Isofix cover")
    tool = await _create(client, eng_auth, seed, "199403", "ISOFIX Cover", "tool")
    res = await client.post(f"/api/v1/parts/{article}/revisions/customer-data",
                            json={"statement": "review", "received_at": "2026-09-01", "customer_index": "003"},
                            headers=eng_auth)
    assert res.status_code == 201, res.text
    res = await client.post(f"/api/v1/parts/{tool}/relations",
                            json={"to_part_id": article, "relation_type": "produces", "notes": "4 cavities"},
                            headers=eng_auth)
    assert res.status_code == 201, res.text

    res = await client.get(f"/api/v1/parts/{tool}/relations", headers=eng_auth)
    rel = res.json()[0]
    assert rel["other_part_id"] == article
    assert rel["other_active_revision_name"] == "E1"
    assert rel["other_active_customer_index"] == "003"
    assert rel["notes"] == "4 cavities"

    # the article side sees the tool, which has no revisions
    res = await client.get(f"/api/v1/parts/{article}/relations", headers=eng_auth)
    assert res.json()[0]["other_active_revision_name"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/nitrolinux/claude/plm2/backend && pytest tests/test_part_relations.py::test_relation_carries_other_active_revision -v -n 0`
Expected: FAIL with `KeyError: 'other_active_revision_name'`.

- [ ] **Step 3: Extend `_relation_dict`**

In `backend/app/api/v1/items/part_relations.py` replace `_relation_dict` with:

```python
def _relation_dict(rel: PartRelation, direction: str) -> dict:
    other = rel.to_part if direction == "outgoing" else rel.from_part
    forward, backward = RELATION_LABELS.get(rel.relation_type, (rel.relation_type, rel.relation_type))
    active = next((r for r in other.revisions if r.id == other.active_revision_id), None)
    return {
        "id": rel.id,
        "relation_type": rel.relation_type,
        "direction": direction,
        "label": forward if direction == "outgoing" else backward,
        "other_part_id": other.id,
        "other_part_number": other.part_number,
        "other_part_name": other.name,
        "other_item_category": other.item_category,
        # active revision of the other part, for chips like "E1 · 003"
        "other_active_revision_name": active.revision_name if active else None,
        "other_active_customer_index": active.customer_index if active else None,
        "notes": rel.notes,
    }
```

`Part.revisions` is `lazy="selectin"`, so `other.revisions` is loaded with the joined part; no extra query per row beyond the selectin batch. In `create_relation` the response is built from `from_part`/`to_part` fetched through `PartService.get_part`, which also loads revisions.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2/backend && pytest tests/test_part_relations.py tests/test_mirror_relation.py tests/test_equipment_relations.py -v -n 0`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/nitrolinux/claude/plm2 && git add backend/app/api/v1/items/part_relations.py backend/tests/test_part_relations.py
git commit -m "feat(relations): carry the other part's active revision

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Frontend groundwork: DFM API module, useSuppliers hook, DocumentPane inlineUrl

**Files:**
- Create: `frontend/src/api/dfm.ts`
- Create: `frontend/src/api/dfm.test.ts`
- Create: `frontend/src/hooks/queries/useSuppliers.ts`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` (lines 655-666: remove the local `SupplierOption` / `useSuppliers`, import the hook)
- Modify: `frontend/src/components/parts/DocumentPane.tsx`
- Modify: `frontend/src/components/parts/DocumentPane.test.tsx`

**Interfaces:**
- Consumes: axios `client` and `API_BASE_URL` from `../api/client`; backend routes from Tasks 4-6.
- Produces:
  - `api/dfm.ts`: `DfmParty`, `PARTIES: DfmParty[]`, `PARTY_LABELS`, `DfmFile`, `DfmEntry`, `DfmTopicSummary`, `DfmTopicDetail`, `listTopics(partId)`, `createTopic(partId, title)`, `getTopic(partId, topicId)`, `closeTopic(partId, topicId)`, `reopenTopic(partId, topicId)`, `createEntry(partId, topicId, input: DfmEntryInput)`, `dfmFileUrl(partId, fileId, 'download'|'inline')`, `buildEntryFormData(input)`.
  - `hooks/queries/useSuppliers.ts`: `useSuppliers()` returning `SupplierOption[]` (`{id, name}`), query key `['suppliers', false]`.
  - `DocumentPane`: `PaneDocument.inlineUrl?: string` used instead of the revision-file URL when set.

- [ ] **Step 1: Write the failing tests**

`frontend/src/api/dfm.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { buildEntryFormData, createEntry, dfmFileUrl, PARTIES, PARTY_LABELS } from './dfm'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('./client', () => ({ default: clientMocks, API_BASE_URL: '/plm2/api' }))

describe('dfm api', () => {
  beforeEach(() => { clientMocks.post.mockReset() })

  it('names the three parties in column order', () => {
    expect(PARTIES).toEqual(['toolmaker', 'ktx', 'tier1'])
    expect(PARTY_LABELS).toEqual({ toolmaker: 'Toolmaker', ktx: 'KTX', tier1: 'Tier 1' })
  })

  it('builds file urls under the tool', () => {
    expect(dfmFileUrl(7, 12, 'inline')).toBe('/plm2/api/v1/parts/7/dfm/files/12/inline')
    expect(dfmFileUrl(7, 12, 'download')).toBe('/plm2/api/v1/parts/7/dfm/files/12/download')
  })

  it('serialises an entry as multipart with addressed_to as JSON and repeated files', () => {
    const file = new File([new Uint8Array([1, 2])], 'dfm.pdf', { type: 'application/pdf' })
    const fd = buildEntryFormData({ party: 'ktx', addressed_to: ['toolmaker', 'tier1'], note: 'rev A', sent_at: '2026-09-24', supersedes_id: null, files: [file] })
    expect(fd.get('party')).toBe('ktx')
    expect(JSON.parse(fd.get('addressed_to') as string)).toEqual(['toolmaker', 'tier1'])
    expect(fd.get('note')).toBe('rev A')
    expect(fd.get('sent_at')).toBe('2026-09-24')
    expect(fd.has('supersedes_id')).toBe(false)
    expect(fd.getAll('files')).toHaveLength(1)
  })

  it('posts an update with supersedes_id and no sent date', async () => {
    clientMocks.post.mockResolvedValue({ data: { id: 3 } })
    await createEntry(7, 2, { party: 'ktx', addressed_to: ['toolmaker'], note: '', sent_at: '', supersedes_id: 1, files: [] })
    const [url, body] = clientMocks.post.mock.calls[0]
    expect(url).toBe('/v1/parts/7/dfm/topics/2/entries')
    expect((body as FormData).get('supersedes_id')).toBe('1')
    expect((body as FormData).has('sent_at')).toBe(false)
  })
})
```

Append to `frontend/src/components/parts/DocumentPane.test.tsx` inside the `describe`:

```ts
  it('uses an explicit inline url when the document carries one', () => {
    render(<DocumentPane document={{ fileId: 9, filename: 'study.pdf', kind: 'pdf', revisionName: 'Gate position', inlineUrl: '/api/v1/parts/7/dfm/files/9/inline' }} />)
    expect((screen.getByTestId('doc-iframe') as HTMLIFrameElement).src).toContain('/api/v1/parts/7/dfm/files/9/inline')
    expect(screen.getByTestId('doc-header').textContent).toContain('study.pdf · Gate position')
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/api/dfm.test.ts src/components/parts/DocumentPane.test.tsx`
Expected: `dfm.test.ts` fails to resolve `./dfm`; the DocumentPane test fails because the iframe src still points at `/revision-files/9/inline`.

- [ ] **Step 3: Write `api/dfm.ts`**

```ts
/**
 * DFM archive API: topics per tool, three-column ledger entries with files.
 * Mirrors backend/app/api/v1/items/dfm.py.
 */
import client, { API_BASE_URL } from './client';

export type DfmParty = 'toolmaker' | 'ktx' | 'tier1';
export const PARTIES: DfmParty[] = ['toolmaker', 'ktx', 'tier1'];
export const PARTY_LABELS: Record<DfmParty, string> = { toolmaker: 'Toolmaker', ktx: 'KTX', tier1: 'Tier 1' };

export interface DfmFile {
  id: number;
  entry_id: number;
  original_filename: string;
  file_size: number;
  content_type: string;
  uploaded_by: number;
  uploaded_by_name: string | null;
  uploaded_at: string;
}

export interface DfmEntry {
  id: number;
  topic_id: number;
  party: DfmParty;
  addressed_to: DfmParty[];
  note: string | null;
  sent_at: string | null;
  supersedes_id: number | null;
  recorded_by: number;
  recorded_by_name: string | null;
  recorded_at: string;
  files: DfmFile[];
  history: Omit<DfmEntry, 'history'>[];
}

export interface DfmTopicSummary {
  id: number;
  tool_part_id: number;
  title: string;
  status: 'open' | 'finished_confirmed';
  opened_by: number;
  opened_at: string;
  closed_by: number | null;
  closed_at: string | null;
  entry_count: number;
  last_activity: string;
}

export interface DfmTopicDetail extends DfmTopicSummary {
  entries: DfmEntry[];
}

export interface DfmEntryInput {
  party: DfmParty;
  addressed_to: DfmParty[];
  note: string;
  sent_at: string;
  supersedes_id: number | null;
  files: File[];
}

const base = (partId: number) => `/v1/parts/${partId}/dfm`;

export async function listTopics(partId: number): Promise<DfmTopicSummary[]> {
  return (await client.get(`${base(partId)}/topics`)).data;
}

export async function createTopic(partId: number, title: string): Promise<DfmTopicSummary> {
  return (await client.post(`${base(partId)}/topics`, { title })).data;
}

export async function getTopic(partId: number, topicId: number): Promise<DfmTopicDetail> {
  return (await client.get(`${base(partId)}/topics/${topicId}`)).data;
}

export async function closeTopic(partId: number, topicId: number): Promise<DfmTopicDetail> {
  return (await client.post(`${base(partId)}/topics/${topicId}/close`)).data;
}

export async function reopenTopic(partId: number, topicId: number): Promise<DfmTopicDetail> {
  return (await client.post(`${base(partId)}/topics/${topicId}/reopen`)).data;
}

export function buildEntryFormData(input: DfmEntryInput): FormData {
  const fd = new FormData();
  fd.append('party', input.party);
  fd.append('addressed_to', JSON.stringify(input.addressed_to));
  fd.append('note', input.note);
  if (input.sent_at) fd.append('sent_at', input.sent_at);
  if (input.supersedes_id != null) fd.append('supersedes_id', String(input.supersedes_id));
  for (const f of input.files) fd.append('files', f);
  return fd;
}

export async function createEntry(partId: number, topicId: number, input: DfmEntryInput): Promise<DfmEntry> {
  return (await client.post(`${base(partId)}/topics/${topicId}/entries`, buildEntryFormData(input),
    { headers: { 'Content-Type': 'multipart/form-data' } })).data;
}

export function dfmFileUrl(partId: number, fileId: number, mode: 'download' | 'inline'): string {
  return `${API_BASE_URL}${base(partId)}/files/${fileId}/${mode}`;
}
```

- [ ] **Step 4: Lift `useSuppliers` into a hook file**

`frontend/src/hooks/queries/useSuppliers.ts`:

```ts
/**
 * Supplier options for pickers (part supplier, toolmaker). Active suppliers only.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';

export interface SupplierOption {
  id: number;
  name: string;
}

export function useSuppliers() {
  return useQuery<SupplierOption[]>({
    queryKey: ['suppliers', false],
    queryFn: async () => (await client.get('/v1/suppliers')).data,
  });
}
```

In `frontend/src/pages/ProjectDetailPage.tsx` delete the local `interface SupplierOption` and `function useSuppliers()` (currently lines 655-666) and add to the imports:

```ts
import { useSuppliers } from '../hooks/queries/useSuppliers';
```

- [ ] **Step 5: DocumentPane inline override**

In `frontend/src/components/parts/DocumentPane.tsx` add to `PaneDocument`:

```ts
  /** Override for documents that are not revision files (DFM archive). */
  inlineUrl?: string;
```

and change the URL line to:

```ts
  const inlineUrl = document
    ? (document.inlineUrl ?? `${API_BASE_URL}/v1/parts/revision-files/${document.fileId}/inline`)
    : null;
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/api/dfm.test.ts src/components/parts/DocumentPane.test.tsx src/pages/ProjectDetailPage.article.test.tsx src/pages/ProjectDetailPage.upload.test.tsx && npx tsc --noEmit`
Expected: all PASS, tsc clean.

- [ ] **Step 7: Commit**

```bash
cd /home/nitrolinux/claude/plm2 && git add frontend/src/api/dfm.ts frontend/src/api/dfm.test.ts frontend/src/hooks/queries/useSuppliers.ts frontend/src/pages/ProjectDetailPage.tsx frontend/src/components/parts/DocumentPane.tsx frontend/src/components/parts/DocumentPane.test.tsx
git commit -m "feat(frontend): dfm api module, shared useSuppliers, DocumentPane inline override

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Tool page branch: header, produced-article chips, no 3D

**Files:**
- Create: `frontend/src/pages/ToolDetail.tsx`
- Create: `frontend/src/pages/ToolDetail.test.tsx`
- Create: `frontend/src/pages/PartDetail.tool.test.tsx`
- Modify: `frontend/src/pages/PartDetail.tsx`

**Interfaces:**
- Consumes: relations endpoint keys from Task 7; `revisionLabel` from `../components/parts/RevisionBadge`; `StartChangeModal` / `StartChangeButton` as `PartDetail` uses them.
- Produces: `ToolDetail({ part, onOpenPart, onBack })` where `part: ToolPart` (exported interface: `id, part_number, name, part_type, project_id, item_category, lifecycle_phase, tool_cavities, toolmaker_id, tool_tonnage_class, tool_cycle_time_s`); `ProducedArticle` type `{ part_id, part_number, name, revision_name, customer_index, notes }`; exported `producedArticles(relations)` helper. Task 10 adds `<ToolFieldsCard>` under the header, Task 11 adds `<DfmArchive>` and the `DocumentPane`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/pages/ToolDetail.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ToolDetail, { producedArticles, type ToolPart } from './ToolDetail'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isAdmin: true }) }))
const stub = vi.hoisted(() => (label: string) => ({ default: () => <div>{label}</div> }))
vi.mock('../components/changes/StartChangeModal', () => stub('start-change'))
vi.mock('../components/changes/StartChangeButton', () => stub('start-change-button'))

const tool: ToolPart = {
  id: 7, part_number: '199403', name: 'ISOFIX Cover', part_type: 'purchased', project_id: 2,
  item_category: 'tool', lifecycle_phase: 'nominated',
  tool_cavities: null, toolmaker_id: null, tool_tonnage_class: null, tool_cycle_time_s: null,
}
const relations = [
  { id: 1, relation_type: 'produces', direction: 'outgoing', label: 'produces', other_part_id: 9,
    other_part_number: '20-1994-003-0', other_part_name: '206.887.233 Isofix cover', other_item_category: 'article',
    other_active_revision_name: 'E1', other_active_customer_index: '003', notes: '2 cavities' },
  { id: 2, relation_type: 'serves', direction: 'incoming', label: 'served by', other_part_id: 30,
    other_part_number: '199403-41', other_part_name: 'Assembly station', other_item_category: 'assembly_equipment',
    other_active_revision_name: null, other_active_customer_index: null, notes: null },
]

function renderTool(onOpenPart = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><ToolDetail part={tool} onOpenPart={onOpenPart} onBack={() => {}} /></QueryClientProvider>)
  return onOpenPart
}

describe('ToolDetail', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/7/relations') return Promise.resolve({ data: relations })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('shows the tool number and name without customer or tier 1 numbers', async () => {
    renderTool()
    expect(await screen.findByText('199403')).toBeTruthy()
    expect(screen.getByText('ISOFIX Cover')).toBeTruthy()
    expect(screen.queryByTestId('edit-customer-part-number')).toBeNull()
    expect(screen.queryByTestId('edit-tier1-part-number')).toBeNull()
  })

  it('lists the produced articles as chips with their active revision and opens them', async () => {
    const onOpen = renderTool()
    const chips = await screen.findByTestId('produced-articles')
    expect(chips.textContent).toContain('206.887.233 Isofix cover · E1 · 003')
    expect(chips.textContent).not.toContain('Assembly station')
    fireEvent.click(screen.getByText(/206.887.233 Isofix cover/))
    expect(onOpen).toHaveBeenCalledWith(9)
  })

  it('says so when the tool produces nothing yet', async () => {
    clientMocks.get.mockImplementation(() => Promise.resolve({ data: [] }))
    renderTool()
    expect((await screen.findByTestId('produced-articles')).textContent).toContain('No produced article linked yet')
  })
})

describe('producedArticles', () => {
  it('keeps outgoing produces links only, in part number order', () => {
    const out = producedArticles([relations[1], relations[0]] as never)
    expect(out).toEqual([{ part_id: 9, part_number: '20-1994-003-0', name: '206.887.233 Isofix cover',
      revision_name: 'E1', customer_index: '003', notes: '2 cavities' }])
  })
})
```

`frontend/src/pages/PartDetail.tool.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import PartDetail from './PartDetail'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isAdmin: true }) }))

const stub = vi.hoisted(() => (label: string) => ({ default: () => <div>{label}</div> }))
vi.mock('../components/changes/StartChangeModal', () => stub('start-change'))
vi.mock('../components/changes/StartChangeButton', () => stub('start-change-button'))
vi.mock('../components/parts/RevisionTimeline', () => stub('timeline'))
vi.mock('../components/parts/CustomerDataDialog', () => stub('customer-data'))
vi.mock('../components/parts/CustomerPackageDialog', () => stub('customer-package'))
vi.mock('../components/parts/BomTree', () => stub('bom-tree'))
vi.mock('../components/parts/DocumentPane', () => ({ default: () => <div data-testid="document-pane" /> }))
vi.mock('../components/Viewer3D', () => stub('viewer-3d'))
vi.mock('../components/paint/PartPaintCard', () => stub('paint-card'))
vi.mock('./ToolDetail', () => ({ default: ({ part }: { part: { part_number: string } }) => <div data-testid="tool-detail">{part.part_number}</div> }))

const part = (over: Record<string, unknown> = {}) => ({
  id: 5, part_number: '199403', customer_part_number: null, name: 'ISOFIX Cover',
  part_type: 'purchased', data_classification: 'confidential', item_category: 'tool',
  project_id: 2, active_revision_id: null, lifecycle_phase: 'nominated', revisions: [], ...over,
})

function renderPart() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/parts/5']}>
        <Routes><Route path="/parts/:partId" element={<PartDetail />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>)
}

describe('PartDetail on a tool', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/5') return Promise.resolve({ data: part() })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('renders the tool page instead of the article page', async () => {
    renderPart()
    expect((await screen.findByTestId('tool-detail')).textContent).toBe('199403')
    expect(screen.queryByText('timeline')).toBeNull()
    expect(screen.queryByTestId('document-pane')).toBeNull()
    expect(screen.queryByText('customer-package')).toBeNull()
    expect(screen.queryByText('Bill of materials')).toBeNull()
  })

  it('does not fetch article-only data for a tool', async () => {
    renderPart()
    await screen.findByTestId('tool-detail')
    const urls = clientMocks.get.mock.calls.map((c) => c[0] as string)
    expect(urls).not.toContain('/v1/parts/5/bom-tree')
    expect(urls).not.toContain('/v1/parts/5/where-used')
  })

  it('still renders the article page for an article', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/5') return Promise.resolve({ data: part({ item_category: 'article', part_number: '20-1994-003-0' }) })
      if (url === '/v1/parts/5/paint') return Promise.resolve({ data: { paint_required: false, process: null, notes: null, layers: [] } })
      return Promise.resolve({ data: [] })
    })
    renderPart()
    expect(await screen.findByText('timeline')).toBeTruthy()
    expect(screen.queryByTestId('tool-detail')).toBeNull()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/pages/ToolDetail.test.tsx src/pages/PartDetail.tool.test.tsx`
Expected: `ToolDetail.test.tsx` cannot resolve `./ToolDetail`; `PartDetail.tool.test.tsx` fails on the mock of `./ToolDetail` (module missing) or, once the file exists, because `tool-detail` is never rendered.

- [ ] **Step 3: Write `ToolDetail.tsx`**

```tsx
/**
 * ToolDetail - the part page for item_category = tool. A tool has no 3D
 * pane, no revision strip and no customer numbers; it shows what it
 * produces, its sold state (Task 10) and the DFM archive (Task 11).
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import client from '../api/client';
import StartChangeModal from '../components/changes/StartChangeModal';
import StartChangeButton from '../components/changes/StartChangeButton';
import { revisionLabel } from '../components/parts/RevisionBadge';

export interface ToolPart {
  id: number;
  part_number: string;
  name: string;
  part_type: string;
  project_id: number;
  item_category: string;
  lifecycle_phase: 'rfq' | 'nominated' | 'series';
  tool_cavities: number | null;
  toolmaker_id: number | null;
  tool_tonnage_class: number | null;
  tool_cycle_time_s: number | null;
}

export interface ToolRelation {
  id: number;
  relation_type: string;
  direction: 'outgoing' | 'incoming';
  other_part_id: number;
  other_part_number: string;
  other_part_name: string;
  other_item_category: string;
  other_active_revision_name: string | null;
  other_active_customer_index: string | null;
  notes: string | null;
}

export interface ProducedArticle {
  part_id: number;
  part_number: string;
  name: string;
  revision_name: string | null;
  customer_index: string | null;
  notes: string | null;
}

export function producedArticles(relations: ToolRelation[]): ProducedArticle[] {
  return relations
    .filter((r) => r.relation_type === 'produces' && r.direction === 'outgoing')
    .map((r) => ({
      part_id: r.other_part_id, part_number: r.other_part_number, name: r.other_part_name,
      revision_name: r.other_active_revision_name, customer_index: r.other_active_customer_index, notes: r.notes,
    }))
    .sort((a, b) => a.part_number.localeCompare(b.part_number));
}

interface Props {
  part: ToolPart;
  onOpenPart(partId: number): void;
  onBack(): void;
}

export default function ToolDetail({ part, onOpenPart, onBack }: Props) {
  const [showStartChange, setShowStartChange] = useState(false);
  const { data: relations } = useQuery({
    queryKey: ['part-relations', part.id],
    queryFn: async () => (await client.get(`/v1/parts/${part.id}/relations`)).data as ToolRelation[],
  });
  const produced = producedArticles(relations ?? []);

  return (
    <div className="min-h-screen bg-slate-900 p-8">
      <div className="max-w-5xl mx-auto">
        <div className="mb-8">
          <button onClick={onBack} className="mb-4 px-3 py-1 bg-slate-700 text-slate-100 rounded hover:bg-slate-600 text-sm">← Back</button>
          <div className="flex justify-between items-start gap-4">
            <div>
              <h1 className="text-4xl font-bold text-slate-100 mb-1">{part.part_number}</h1>
              <p className="text-slate-300 mb-2">{part.name}</p>
              <div className="flex items-center gap-2 flex-wrap mb-3">
                <span className="text-sm text-slate-200 bg-slate-700 px-3 py-1 rounded-md">Tool</span>
                <span data-testid="lifecycle-phase" className="text-sm text-slate-200 bg-slate-700 px-3 py-1 rounded-md capitalize">{part.lifecycle_phase}</span>
              </div>
              <div data-testid="produced-articles" className="flex items-center gap-2 flex-wrap text-sm">
                <span className="text-slate-400">Produces</span>
                {produced.length === 0 && <span className="text-slate-500">No produced article linked yet</span>}
                {produced.map((a) => (
                  <button key={a.part_id} onClick={() => onOpenPart(a.part_id)}
                    className="px-2 py-0.5 rounded bg-slate-700 text-slate-100 hover:bg-slate-600">
                    {a.name}
                    {a.revision_name && <span className="text-slate-400"> · {revisionLabel(a.revision_name, a.customer_index)}</span>}
                  </button>
                ))}
              </div>
            </div>
            <StartChangeButton label="Start change request" onClick={() => setShowStartChange(true)}
              className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-sm font-medium" />
          </div>
        </div>

        {showStartChange && (
          <StartChangeModal open onClose={() => setShowStartChange(false)}
            prefill={{ projectId: part.project_id, part: { id: part.id, part_number: part.part_number, name: part.name, item_category: part.item_category } }} />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Branch in `PartDetail.tsx`**

Add the import next to the other page-level imports:

```ts
import ToolDetail from './ToolDetail';
```

Extend the local `Part` interface with the four tool fields:

```ts
  tool_cavities?: number | null;
  toolmaker_id?: number | null;
  tool_tonnage_class?: number | null;
  tool_cycle_time_s?: number | null;
```

Gate the article-only queries. Change `bom-tree` and `where-used` to `enabled: !!part && part.item_category !== 'tool'` (they currently use `enabled: !!partId`). The `revision-files` query is already gated on `activeRevision`, and `projectParts` stays (harmless, cheap).

Right after the "Part not found" block (all hooks are above it), add:

```tsx
  if (part.item_category === 'tool') {
    return (
      <ToolDetail
        part={{
          id: part.id, part_number: part.part_number, name: part.name, part_type: part.part_type,
          project_id: part.project_id, item_category: part.item_category, lifecycle_phase: part.lifecycle_phase,
          tool_cavities: part.tool_cavities ?? null, toolmaker_id: part.toolmaker_id ?? null,
          tool_tonnage_class: part.tool_tonnage_class ?? null, tool_cycle_time_s: part.tool_cycle_time_s ?? null,
        }}
        onOpenPart={(id) => navigate(`/parts/${id}`)}
        onBack={() => navigate('/dashboard')}
      />
    );
  }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/pages/ToolDetail.test.tsx src/pages/PartDetail.tool.test.tsx src/pages/PartDetail.test.tsx src/pages/PartDetail.files.test.tsx && npx tsc --noEmit`
Expected: all PASS, tsc clean.

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2 && git add frontend/src/pages/ToolDetail.tsx frontend/src/pages/ToolDetail.test.tsx frontend/src/pages/PartDetail.tool.test.tsx frontend/src/pages/PartDetail.tsx
git commit -m "feat(tool-page): tool branch with produced article chips, no 3D

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Tool fields card with supplier picker

**Files:**
- Create: `frontend/src/components/tools/ToolFieldsCard.tsx`
- Create: `frontend/src/components/tools/ToolFieldsCard.test.tsx`
- Modify: `frontend/src/pages/ToolDetail.tsx` (render the card under the header)

**Interfaces:**
- Consumes: `useSuppliers()` (Task 8); `PUT /v1/parts/{id}` with one tool key (Task 1); `ProducedArticle.notes` (Task 9).
- Produces: `ToolFieldsCard({ partId, values, producedNotes })` with `values: { tool_cavities, toolmaker_id, tool_tonnage_class, tool_cycle_time_s }`; exported `cavitiesFromNotes(notes: (string|null)[]): number | null`. Test ids: `edit-tool-cavities`, `tool-cavities-input`, `save-tool-cavities`, `edit-tool-tonnage`, `tool-tonnage-input`, `save-tool-tonnage`, `edit-tool-cycle`, `tool-cycle-input`, `save-tool-cycle`, `toolmaker-select`, `cavities-fallback`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/tools/ToolFieldsCard.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ToolFieldsCard, { cavitiesFromNotes } from './ToolFieldsCard'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const empty = { tool_cavities: null, toolmaker_id: null, tool_tonnage_class: null, tool_cycle_time_s: null }

function wrap(values = empty, notes: (string | null)[] = []) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><ToolFieldsCard partId={7} values={values} producedNotes={notes} /></QueryClientProvider>)
}

describe('ToolFieldsCard', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.put.mockReset()
    clientMocks.get.mockResolvedValue({ data: [{ id: 3, name: 'Toolshop Sued' }, { id: 4, name: 'Formenbau Nord' }] })
    clientMocks.put.mockResolvedValue({ data: {} })
  })
  afterEach(cleanup)

  it('saves cavities as an integer', async () => {
    wrap()
    fireEvent.click(screen.getByTestId('edit-tool-cavities'))
    fireEvent.change(screen.getByTestId('tool-cavities-input'), { target: { value: '4' } })
    fireEvent.click(screen.getByTestId('save-tool-cavities'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7', { tool_cavities: 4 }))
  })

  it('clears a field when emptied and saves cycle time as a decimal', async () => {
    wrap({ ...empty, tool_tonnage_class: 650, tool_cycle_time_s: 32.5 })
    fireEvent.click(screen.getByTestId('edit-tool-tonnage'))
    fireEvent.change(screen.getByTestId('tool-tonnage-input'), { target: { value: '' } })
    fireEvent.click(screen.getByTestId('save-tool-tonnage'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7', { tool_tonnage_class: null }))

    fireEvent.click(screen.getByTestId('edit-tool-cycle'))
    fireEvent.change(screen.getByTestId('tool-cycle-input'), { target: { value: '31.8' } })
    fireEvent.keyDown(screen.getByTestId('tool-cycle-input'), { key: 'Enter' })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7', { tool_cycle_time_s: 31.8 }))
  })

  it('picks the toolmaker from the supplier list and saves at once', async () => {
    wrap()
    const select = await screen.findByTestId('toolmaker-select') as HTMLSelectElement
    await screen.findByRole('option', { name: 'Formenbau Nord' })
    fireEvent.change(select, { target: { value: '4' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7', { toolmaker_id: 4 }))
    fireEvent.change(select, { target: { value: '' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7', { toolmaker_id: null }))
  })

  it('falls back to the relation note for cavities and says so', async () => {
    wrap(empty, ['2 cavities', null])
    expect(screen.getByTestId('edit-tool-cavities').textContent).toContain('2')
    expect(screen.getByTestId('cavities-fallback').textContent).toContain('from the produces note')
  })

  it('prefers the stored cavities over the note', () => {
    wrap({ ...empty, tool_cavities: 4 }, ['2 cavities'])
    expect(screen.getByTestId('edit-tool-cavities').textContent).toContain('4')
    expect(screen.queryByTestId('cavities-fallback')).toBeNull()
  })
})

describe('cavitiesFromNotes', () => {
  it('sums the cavity counts it finds and ignores the rest', () => {
    expect(cavitiesFromNotes(['2 cavities', '1 cavity', 'RFQ2 bom_item 12', null])).toBe(3)
    expect(cavitiesFromNotes(['per RFQ'])).toBeNull()
    expect(cavitiesFromNotes([])).toBeNull()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/tools/ToolFieldsCard.test.tsx`
Expected: FAIL, module `./ToolFieldsCard` not found.

- [ ] **Step 3: Write the card**

`frontend/src/components/tools/ToolFieldsCard.tsx`:

```tsx
/**
 * ToolFieldsCard - the sold state of a tool: cavities, toolmaker, machine
 * tonnage class, target cycle time. Inline edits, one PUT per field with
 * only that key (the backend applies keys that are present). Cavities fall
 * back to the "n cavities" note on the produces relation until set here.
 */
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../../api/client';
import { toast } from 'sonner';
import { useSuppliers } from '../../hooks/queries/useSuppliers';

export interface ToolFieldValues {
  tool_cavities: number | null;
  toolmaker_id: number | null;
  tool_tonnage_class: number | null;
  tool_cycle_time_s: number | null;
}

export function cavitiesFromNotes(notes: (string | null | undefined)[]): number | null {
  let total = 0;
  let found = false;
  for (const n of notes) {
    const m = /(\d+)\s*cavit/i.exec(n ?? '');
    if (m) { total += parseInt(m[1], 10); found = true; }
  }
  return found ? total : null;
}

function errMsg(error: unknown, fallback: string) {
  return (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;
}

type NumericKey = 'tool_cavities' | 'tool_tonnage_class' | 'tool_cycle_time_s';

const NUMERIC: { key: NumericKey; id: string; label: string; unit: string; step: string; parse(v: string): number }[] = [
  { key: 'tool_cavities', id: 'cavities', label: 'Cavities', unit: '', step: '1', parse: (v) => parseInt(v, 10) },
  { key: 'tool_tonnage_class', id: 'tonnage', label: 'Tonnage class', unit: 't', step: '1', parse: (v) => parseInt(v, 10) },
  { key: 'tool_cycle_time_s', id: 'cycle', label: 'Target cycle time', unit: 's', step: '0.1', parse: (v) => parseFloat(v) },
];

interface Props {
  partId: number;
  values: ToolFieldValues;
  producedNotes: (string | null | undefined)[];
}

export default function ToolFieldsCard({ partId, values, producedNotes }: Props) {
  const queryClient = useQueryClient();
  const { data: suppliers } = useSuppliers();
  const [editing, setEditing] = useState<{ key: NumericKey; value: string } | null>(null);

  const save = useMutation({
    mutationFn: (payload: Partial<ToolFieldValues>) => client.put(`/v1/parts/${partId}`, payload),
    onSuccess: () => {
      toast.success('Tool data saved');
      setEditing(null);
      queryClient.invalidateQueries({ queryKey: ['part', String(partId)] });
    },
    onError: (e) => toast.error(errMsg(e, 'Could not save the tool data')),
  });

  const submitNumeric = (field: (typeof NUMERIC)[number], raw: string) => {
    const trimmed = raw.trim();
    if (trimmed === '') { save.mutate({ [field.key]: null }); return; }
    const n = field.parse(trimmed);
    if (Number.isNaN(n) || n <= 0) { toast.error(`${field.label} must be a positive number`); return; }
    save.mutate({ [field.key]: n });
  };

  const fallbackCavities = values.tool_cavities == null ? cavitiesFromNotes(producedNotes) : null;

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8">
      <h2 className="text-xl font-bold text-slate-100 mb-4">Tool</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {NUMERIC.map((field) => {
          const current = values[field.key];
          const shown = current ?? (field.key === 'tool_cavities' ? fallbackCavities : null);
          const isEditing = editing?.key === field.key;
          return (
            <div key={field.key}>
              <div className="text-sm text-slate-400">{field.label}{field.unit ? ` (${field.unit})` : ''}</div>
              {isEditing ? (
                <div className="flex items-center gap-2 mt-1">
                  <input data-testid={`tool-${field.id}-input`} autoFocus type="number" step={field.step} min="0"
                    value={editing.value} onChange={(e) => setEditing({ key: field.key, value: e.target.value })}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') submitNumeric(field, editing.value);
                      if (e.key === 'Escape') setEditing(null);
                    }}
                    className="w-24 bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 text-sm" />
                  <button data-testid={`save-tool-${field.id}`} disabled={save.isPending}
                    onClick={() => submitNumeric(field, editing.value)}
                    className="text-sm px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white">Save</button>
                  <button onClick={() => setEditing(null)} className="text-sm px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">Cancel</button>
                </div>
              ) : (
                <button data-testid={`edit-tool-${field.id}`} title={`Edit ${field.label.toLowerCase()}`}
                  onClick={() => setEditing({ key: field.key, value: current == null ? '' : String(current) })}
                  className="block font-medium text-slate-100 hover:text-blue-300 mt-1">
                  {shown == null ? <span className="text-slate-500">+ set</span> : shown}
                </button>
              )}
              {field.key === 'tool_cavities' && current == null && fallbackCavities != null && (
                <div data-testid="cavities-fallback" className="text-xs text-amber-300 mt-0.5">from the produces note, not confirmed</div>
              )}
            </div>
          );
        })}
        <div>
          <div className="text-sm text-slate-400">Toolmaker</div>
          <select data-testid="toolmaker-select" value={values.toolmaker_id ?? ''} disabled={save.isPending}
            onChange={(e) => save.mutate({ toolmaker_id: e.target.value ? parseInt(e.target.value, 10) : null })}
            className="mt-1 w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 text-sm">
            <option value="">— not set —</option>
            {suppliers?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Mount it in `ToolDetail.tsx`**

Add the import `import ToolFieldsCard from '../components/tools/ToolFieldsCard';` and, right after the closing `</div>` of the header block (`<div className="mb-8">...</div>`) and before the `showStartChange` modal, render:

```tsx
        <ToolFieldsCard partId={part.id}
          values={{ tool_cavities: part.tool_cavities, toolmaker_id: part.toolmaker_id,
            tool_tonnage_class: part.tool_tonnage_class, tool_cycle_time_s: part.tool_cycle_time_s }}
          producedNotes={produced.map((a) => a.notes)} />
```

Add to `ToolDetail.test.tsx` (the suppliers query returns `[]` from the default mock, which is fine):

```tsx
  it('shows the tool fields card', async () => {
    renderTool()
    expect(await screen.findByTestId('edit-tool-cavities')).toBeTruthy()
    expect(screen.getByTestId('toolmaker-select')).toBeTruthy()
  })
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/tools src/pages/ToolDetail.test.tsx && npx tsc --noEmit`
Expected: all PASS, tsc clean.

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2 && git add frontend/src/components/tools frontend/src/pages/ToolDetail.tsx frontend/src/pages/ToolDetail.test.tsx
git commit -m "feat(tool-page): tool fields card with toolmaker picker

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: DFM entry form

Leaf component first: the ledger (Task 12) opens it, the archive (Task 13) mounts the ledger.

**Files:**
- Create: `frontend/src/components/dfm/DfmEntryForm.tsx`
- Create: `frontend/src/components/dfm/DfmEntryForm.test.tsx`

**Interfaces:**
- Consumes: `createEntry`, `DfmParty`, `PARTIES`, `PARTY_LABELS`, `DfmEntryInput` from `../../api/dfm` (Task 8).
- Produces: `DfmEntryForm({ partId, topicId, party, supersedesId?, onDone, onCancel })`. Test ids: `dfm-entry-form`, `addressed-<party>` checkboxes, `dfm-note`, `dfm-sent-at`, `dfm-files-input`, `dfm-dropzone`, `dfm-submit`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/dfm/DfmEntryForm.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DfmEntryForm from './DfmEntryForm'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

function wrap(props: Partial<React.ComponentProps<typeof DfmEntryForm>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onDone = vi.fn(); const onCancel = vi.fn()
  render(<QueryClientProvider client={qc}>
    <DfmEntryForm partId={7} topicId={2} party="ktx" onDone={onDone} onCancel={onCancel} {...props} />
  </QueryClientProvider>)
  return { onDone, onCancel }
}

describe('DfmEntryForm', () => {
  beforeEach(() => { clientMocks.post.mockReset(); clientMocks.post.mockResolvedValue({ data: { id: 5 } }) })
  afterEach(cleanup)

  it('offers only the other two parties and posts multipart with party, addressed_to and files', async () => {
    const { onDone } = wrap()
    expect(screen.queryByTestId('addressed-ktx')).toBeNull()
    fireEvent.click(screen.getByTestId('addressed-toolmaker'))
    fireEvent.click(screen.getByTestId('addressed-tier1'))
    fireEvent.change(screen.getByTestId('dfm-note'), { target: { value: 'DFM request rev A' } })
    fireEvent.change(screen.getByTestId('dfm-sent-at'), { target: { value: '2026-09-24' } })
    const file = new File([new Uint8Array([1])], 'dfm_request_A.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByTestId('dfm-files-input'), { target: { files: [file] } })
    expect(screen.getByText('dfm_request_A.pdf')).toBeTruthy()
    fireEvent.click(screen.getByTestId('dfm-submit'))

    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    const [url, body] = clientMocks.post.mock.calls[0]
    expect(url).toBe('/v1/parts/7/dfm/topics/2/entries')
    const fd = body as FormData
    expect(fd.get('party')).toBe('ktx')
    expect(JSON.parse(fd.get('addressed_to') as string)).toEqual(['toolmaker', 'tier1'])
    expect(fd.get('note')).toBe('DFM request rev A')
    expect(fd.get('sent_at')).toBe('2026-09-24')
    expect(fd.getAll('files')).toHaveLength(1)
    await waitFor(() => expect(onDone).toHaveBeenCalled())
  })

  it('refuses to send without an addressee', async () => {
    wrap()
    fireEvent.click(screen.getByTestId('dfm-submit'))
    expect(clientMocks.post).not.toHaveBeenCalled()
    expect(screen.getByText(/at least one/)).toBeTruthy()
  })

  it('sends supersedes_id for an update and says it is one', async () => {
    wrap({ party: 'toolmaker', supersedesId: 11 })
    expect(screen.getByTestId('dfm-entry-form').textContent).toContain('Update this entry')
    fireEvent.click(screen.getByTestId('addressed-ktx'))
    fireEvent.click(screen.getByTestId('dfm-submit'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    expect((clientMocks.post.mock.calls[0][1] as FormData).get('supersedes_id')).toBe('11')
  })

  it('accepts dropped files', () => {
    wrap()
    const file = new File([new Uint8Array([1])], 'study.pdf', { type: 'application/pdf' })
    fireEvent.drop(screen.getByTestId('dfm-dropzone'), { dataTransfer: { files: [file] } })
    expect(screen.getByText('study.pdf')).toBeTruthy()
  })

  it('cancels', () => {
    const { onCancel } = wrap()
    fireEvent.click(screen.getByText('Cancel'))
    expect(onCancel).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/dfm/DfmEntryForm.test.tsx`
Expected: FAIL, module not found.

- [ ] **Step 3: Write the form**

`frontend/src/components/dfm/DfmEntryForm.tsx`:

```tsx
/**
 * DfmEntryForm - one ledger entry in `party`'s column: who it is addressed
 * to (the other two parties), a note, the mail date, files. With
 * supersedesId it records an update of an earlier entry in the same column.
 */
import { useRef, useState, type DragEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { createEntry, PARTIES, PARTY_LABELS, type DfmParty } from '../../api/dfm';

interface Props {
  partId: number;
  topicId: number;
  party: DfmParty;
  supersedesId?: number | null;
  onDone(): void;
  onCancel(): void;
}

function errMsg(error: unknown, fallback: string) {
  return (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;
}

export default function DfmEntryForm({ partId, topicId, party, supersedesId = null, onDone, onCancel }: Props) {
  const others = PARTIES.filter((p) => p !== party);
  const [addressed, setAddressed] = useState<DfmParty[]>([]);
  const [note, setNote] = useState('');
  const [sentAt, setSentAt] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const save = useMutation({
    mutationFn: () => createEntry(partId, topicId, { party, addressed_to: addressed, note, sent_at: sentAt, supersedes_id: supersedesId, files }),
    onSuccess: () => { toast.success(supersedesId ? 'Entry updated' : 'Entry recorded'); onDone(); },
    onError: (e) => toast.error(errMsg(e, 'Could not record the entry')),
  });

  const toggle = (p: DfmParty) =>
    setAddressed((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...others.filter((o) => o === p || cur.includes(o))]));

  const addFiles = (list: FileList | File[] | null) => {
    if (!list) return;
    setFiles((cur) => [...cur, ...Array.from(list)]);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    addFiles(e.dataTransfer?.files ?? null);
  };

  const submit = () => {
    if (addressed.length === 0) { setError('Address the entry to at least one party'); return; }
    setError(null);
    save.mutate();
  };

  return (
    <div data-testid="dfm-entry-form" className="mt-2 p-3 rounded-lg border border-slate-600 bg-slate-900 text-sm">
      <div className="font-medium text-slate-100 mb-2">
        {supersedesId ? 'Update this entry' : '+ entry'} <span className="text-slate-400">· {PARTY_LABELS[party]}</span>
      </div>
      <div className="flex items-center gap-4 mb-2">
        <span className="text-slate-400">To</span>
        {others.map((p) => (
          <label key={p} className="flex items-center gap-1 text-slate-200">
            <input data-testid={`addressed-${p}`} type="checkbox" checked={addressed.includes(p)} onChange={() => toggle(p)} />
            {PARTY_LABELS[p]}
          </label>
        ))}
      </div>
      <textarea data-testid="dfm-note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="Note"
        className="w-full p-2 border border-slate-700 rounded bg-slate-800 text-slate-100 mb-2" />
      <div className="flex items-center gap-2 mb-2">
        <span className="text-slate-400">Sent / received</span>
        <input data-testid="dfm-sent-at" type="date" value={sentAt} onChange={(e) => setSentAt(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100" />
      </div>
      <div data-testid="dfm-dropzone" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className="border border-dashed border-slate-600 rounded p-3 text-slate-400 text-center cursor-pointer hover:border-slate-400 mb-2">
        Drop files here or click to choose
        <input ref={inputRef} data-testid="dfm-files-input" type="file" multiple className="hidden"
          onChange={(e) => { addFiles(e.target.files); e.target.value = ''; }} />
      </div>
      {files.length > 0 && (
        <ul className="mb-2 text-slate-200">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center gap-2">
              <span className="font-mono text-xs">{f.name}</span>
              <button onClick={() => setFiles((cur) => cur.filter((_, j) => j !== i))} className="text-slate-500 hover:text-red-300">remove</button>
            </li>
          ))}
        </ul>
      )}
      {error && <div className="text-red-300 mb-2">{error}</div>}
      <div className="flex gap-2">
        <button data-testid="dfm-submit" onClick={submit} disabled={save.isPending}
          className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white">
          {supersedesId ? 'Record update' : 'Record entry'}
        </button>
        <button onClick={onCancel} className="px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">Cancel</button>
      </div>
    </div>
  );
}
```

The `toggle` keeps `addressed` in `PARTIES` order so the payload order is stable.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/dfm/DfmEntryForm.test.tsx && npx tsc --noEmit`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/nitrolinux/claude/plm2 && git add frontend/src/components/dfm/DfmEntryForm.tsx frontend/src/components/dfm/DfmEntryForm.test.tsx
git commit -m "feat(dfm): entry form with addressees, mail date and files

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: Three-column ledger

**Files:**
- Create: `frontend/src/components/dfm/DfmLedger.tsx`
- Create: `frontend/src/components/dfm/DfmLedger.test.tsx`

**Interfaces:**
- Consumes: `getTopic`, `closeTopic`, `reopenTopic`, `dfmFileUrl`, `PARTIES`, `PARTY_LABELS`, `DfmEntry`, `DfmTopicDetail` (Task 8); `DfmEntryForm` (Task 11); `PaneDocument` (Task 8).
- Produces: `DfmLedger({ partId, topicId, onOpenPdf })` where `onOpenPdf(doc: PaneDocument)`; exported helpers `initials(name)`, `shortDate(iso)`. Query key `['dfm-topic', partId, topicId]`; on close/reopen/entry it invalidates that key and `['dfm-topics', partId]`. Test ids: `dfm-ledger`, `dfm-column-<party>`, `dfm-entry-<id>` (with attribute `data-party`), `dfm-add-<party>`, `dfm-update-<id>`, `dfm-history-<id>`, `dfm-finish`, `dfm-reopen`, `dfm-file-<fileId>`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/dfm/DfmLedger.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DfmLedger, { initials, shortDate } from './DfmLedger'
import type { DfmTopicDetail } from '../../api/dfm'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '/api' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('./DfmEntryForm', () => ({ default: (p: { party: string; supersedesId?: number | null }) =>
  <div data-testid="entry-form">{p.party}:{p.supersedesId ?? 'new'}</div> }))

const entry = (over: Record<string, unknown>) => ({
  id: 1, topic_id: 2, party: 'ktx', addressed_to: ['toolmaker', 'tier1'], note: 'DFM request rev A', sent_at: '2026-09-24',
  supersedes_id: null, recorded_by: 14, recorded_by_name: 'Christoph Demmler', recorded_at: '2026-09-24T10:00:00', files: [], history: [], ...over,
})
const topic = (over: Partial<DfmTopicDetail> = {}): DfmTopicDetail => ({
  id: 2, tool_part_id: 7, title: 'Gate position', status: 'open', opened_by: 14, opened_at: '2026-09-24T09:00:00',
  closed_by: null, closed_at: null, entry_count: 3, last_activity: '2026-09-27T10:00:00',
  entries: [
    entry({ id: 1, files: [{ id: 41, entry_id: 1, original_filename: 'dfm_request_A.pdf', file_size: 10, content_type: 'application/pdf', uploaded_by: 14, uploaded_by_name: 'Christoph Demmler', uploaded_at: '2026-09-24T10:00:00' }] }),
    entry({ id: 2, party: 'toolmaker', addressed_to: ['ktx'], note: 'DFM study rev 1', sent_at: '2026-09-26', recorded_at: '2026-09-26T08:00:00',
      files: [{ id: 42, entry_id: 2, original_filename: 'volumes.xlsx', file_size: 10, content_type: 'application/vnd.ms-excel', uploaded_by: 14, uploaded_by_name: 'Christoph Demmler', uploaded_at: '2026-09-26T08:00:00' }] }),
    entry({ id: 4, addressed_to: ['toolmaker'], note: 'answer, 2 points open', sent_at: '2026-09-27', recorded_at: '2026-09-27T10:00:00', supersedes_id: 3,
      recorded_by_name: 'Karl Huber', history: [entry({ id: 3, addressed_to: ['toolmaker'], note: 'answer, 3 points open', sent_at: '2026-09-26', recorded_at: '2026-09-26T12:00:00' })] }),
  ],
  ...over,
})

function wrap(onOpenPdf = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><DfmLedger partId={7} topicId={2} onOpenPdf={onOpenPdf} /></QueryClientProvider>)
  return onOpenPdf
}

describe('DfmLedger', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.post.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/7/dfm/topics/2') return Promise.resolve({ data: topic() })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('puts entries in their party column, in time order, with the addressed-to line', async () => {
    wrap()
    const ledger = await screen.findByTestId('dfm-ledger')
    const rows = ledger.querySelectorAll('[data-testid^="dfm-entry-"]')
    expect(Array.from(rows).map((r) => r.getAttribute('data-testid'))).toEqual(['dfm-entry-1', 'dfm-entry-2', 'dfm-entry-4'])
    expect(Array.from(rows).map((r) => r.getAttribute('data-party'))).toEqual(['ktx', 'toolmaker', 'ktx'])
    expect(screen.getByTestId('dfm-entry-1').textContent).toContain('09-24 → Toolmaker, Tier 1')
    expect(screen.getByTestId('dfm-entry-2').textContent).toContain('09-26 → KTX')
    expect(screen.getByTestId('dfm-entry-1').textContent).toContain('↑CD')
    expect(screen.getByTestId('dfm-entry-4').textContent).toContain('↑KH')
    expect(screen.getByTestId('dfm-column-toolmaker').textContent).toContain('Toolmaker')
  })

  it('marks an updated entry and collapses the earlier version', async () => {
    wrap()
    const updated = await screen.findByTestId('dfm-entry-4')
    expect(updated.textContent).toContain('(updated)')
    expect(updated.textContent).toContain('1 earlier version')
    expect(updated.textContent).not.toContain('answer, 3 points open')
    fireEvent.click(within(updated).getByTestId('dfm-history-4'))
    expect(updated.textContent).toContain('answer, 3 points open')
  })

  it('opens PDFs in the pane and downloads other files', async () => {
    const onOpenPdf = wrap()
    fireEvent.click(await screen.findByTestId('dfm-file-41'))
    expect(onOpenPdf).toHaveBeenCalledWith({ fileId: 41, filename: 'dfm_request_A.pdf', kind: 'pdf', revisionName: 'Gate position', inlineUrl: '/api/v1/parts/7/dfm/files/41/inline' })
    const link = screen.getByTestId('dfm-file-42') as HTMLAnchorElement
    expect(link.tagName).toBe('A')
    expect(link.href).toContain('/api/v1/parts/7/dfm/files/42/download')
  })

  it('opens the entry form under a column and the update form on an own entry', async () => {
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-add-tier1'))
    expect(screen.getByTestId('entry-form').textContent).toBe('tier1:new')
    fireEvent.click(screen.getByTestId('dfm-update-4'))
    expect(screen.getByTestId('entry-form').textContent).toBe('ktx:4')
  })

  it('finishes an open topic', async () => {
    clientMocks.post.mockResolvedValue({ data: topic({ status: 'finished_confirmed' }) })
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-finish'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/dfm/topics/2/close'))
  })

  it('renders a finished topic read-only with Reopen', async () => {
    clientMocks.get.mockImplementation(() => Promise.resolve({ data: topic({ status: 'finished_confirmed', closed_at: '2026-10-01T09:00:00' }) }))
    clientMocks.post.mockResolvedValue({ data: topic() })
    wrap()
    expect(await screen.findByTestId('dfm-reopen')).toBeTruthy()
    expect(screen.queryByTestId('dfm-finish')).toBeNull()
    expect(screen.queryByTestId('dfm-add-ktx')).toBeNull()
    expect(screen.queryByTestId('dfm-update-4')).toBeNull()
    expect(screen.getByTestId('dfm-ledger').textContent).toContain('Finished confirmed')
    fireEvent.click(screen.getByTestId('dfm-reopen'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/dfm/topics/2/reopen'))
  })
})

describe('helpers', () => {
  it('initials and short dates', () => {
    expect(initials('Christoph Demmler')).toBe('CD')
    expect(initials('karl')).toBe('K')
    expect(initials(null)).toBe('?')
    expect(shortDate('2026-09-24')).toBe('09-24')
    expect(shortDate('2026-09-24T10:00:00')).toBe('09-24')
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/dfm/DfmLedger.test.tsx`
Expected: FAIL, module not found.

- [ ] **Step 3: Write the ledger**

`frontend/src/components/dfm/DfmLedger.tsx`:

```tsx
/**
 * DfmLedger - one topic's three-column ledger: Toolmaker | KTX | Tier 1.
 * One row per entry, chronological, in its author's column. Updates show
 * "(updated)" with the earlier versions collapsed. A finished topic is
 * read-only with Reopen; an open one has Finish confirmed.
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { closeTopic, dfmFileUrl, getTopic, reopenTopic, PARTIES, PARTY_LABELS, type DfmEntry, type DfmParty } from '../../api/dfm';
import type { PaneDocument } from '../parts/DocumentPane';
import DfmEntryForm from './DfmEntryForm';

export function initials(name: string | null | undefined): string {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  return parts.map((p) => p[0].toUpperCase()).join('');
}

export function shortDate(iso: string | null | undefined): string {
  return iso ? iso.slice(5, 10) : '';
}

function errMsg(error: unknown, fallback: string) {
  return (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;
}

interface Props {
  partId: number;
  topicId: number;
  onOpenPdf(doc: PaneDocument): void;
}

type FormState = { party: DfmParty; supersedesId: number | null } | null;

export default function DfmLedger({ partId, topicId, onOpenPdf }: Props) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<FormState>(null);
  const [openHistory, setOpenHistory] = useState<Set<number>>(new Set());

  const { data: topic } = useQuery({
    queryKey: ['dfm-topic', partId, topicId],
    queryFn: () => getTopic(partId, topicId),
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['dfm-topic', partId, topicId] });
    queryClient.invalidateQueries({ queryKey: ['dfm-topics', partId] });
    queryClient.invalidateQueries({ queryKey: ['changelog', String(partId)] });
  };
  const finish = useMutation({
    mutationFn: () => closeTopic(partId, topicId),
    onSuccess: () => { toast.success('Topic finished confirmed'); setForm(null); refresh(); },
    onError: (e) => toast.error(errMsg(e, 'Could not finish the topic')),
  });
  const reopen = useMutation({
    mutationFn: () => reopenTopic(partId, topicId),
    onSuccess: () => { toast.success('Topic reopened'); refresh(); },
    onError: (e) => toast.error(errMsg(e, 'Could not reopen the topic')),
  });

  if (!topic) return <div className="text-slate-400 text-sm">Loading…</div>;
  const open = topic.status === 'open';

  const fileLink = (f: DfmEntry['files'][number]) =>
    f.original_filename.toLowerCase().endsWith('.pdf') ? (
      <button key={f.id} data-testid={`dfm-file-${f.id}`}
        onClick={() => onOpenPdf({ fileId: f.id, filename: f.original_filename, kind: 'pdf', revisionName: topic.title, inlineUrl: dfmFileUrl(partId, f.id, 'inline') })}
        className="font-mono text-xs text-blue-300 hover:underline">{f.original_filename}</button>
    ) : (
      <a key={f.id} data-testid={`dfm-file-${f.id}`} href={dfmFileUrl(partId, f.id, 'download')}
        className="font-mono text-xs text-blue-300 hover:underline">{f.original_filename}</a>
    );

  const body = (e: Omit<DfmEntry, 'history'>) => (
    <>
      <div className="text-xs text-slate-400">
        {shortDate(e.sent_at ?? e.recorded_at)} → {e.addressed_to.map((p) => PARTY_LABELS[p]).join(', ')}
      </div>
      {e.note && <div className="text-slate-100 whitespace-pre-wrap">{e.note}</div>}
      {e.files.length > 0 && (
        <div className="flex flex-col gap-0.5 mt-1">
          {e.files.map((f) => <span key={f.id}>{fileLink(f)} <span className="text-xs text-slate-500">↑{initials(f.uploaded_by_name)}</span></span>)}
        </div>
      )}
    </>
  );

  return (
    <div data-testid="dfm-ledger" className="mt-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <span className="text-lg font-semibold text-slate-100">{topic.title}</span>
          <span className={`ml-2 text-xs px-2 py-0.5 rounded ${open ? 'bg-emerald-900 text-emerald-200' : 'bg-slate-700 text-slate-200'}`}>
            {open ? 'Open' : 'Finished confirmed'}
          </span>
        </div>
        {open ? (
          <button data-testid="dfm-finish" onClick={() => finish.mutate()} disabled={finish.isPending}
            className="px-3 py-1 rounded bg-emerald-700 hover:bg-emerald-600 disabled:bg-slate-600 text-white text-sm">Finish confirmed</button>
        ) : (
          <button data-testid="dfm-reopen" onClick={() => reopen.mutate()} disabled={reopen.isPending}
            className="px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100 text-sm">Reopen</button>
        )}
      </div>

      <div className="grid grid-cols-3 gap-3">
        {PARTIES.map((p) => (
          <div key={p} data-testid={`dfm-column-${p}`} className="border-b border-slate-600 pb-2 flex items-center justify-between">
            <span className="font-semibold text-slate-200">{PARTY_LABELS[p]}</span>
            {open && (
              <button data-testid={`dfm-add-${p}`} onClick={() => setForm({ party: p, supersedesId: null })}
                className="text-xs px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">+ entry</button>
            )}
          </div>
        ))}
        {topic.entries.map((e) => (
          <div key={e.id} className="contents">
            {PARTIES.map((p) => (
              <div key={p} className="min-h-[1px]">
                {p === e.party && (
                  <div data-testid={`dfm-entry-${e.id}`} data-party={e.party}
                    className="rounded-lg border border-slate-700 bg-slate-800 p-2 text-sm">
                    {body(e)}
                    <div className="flex items-center gap-2 mt-1 text-xs text-slate-500">
                      <span>↑{initials(e.recorded_by_name)}</span>
                      {e.history.length > 0 && <span className="text-amber-300">(updated)</span>}
                      {open && (
                        <button data-testid={`dfm-update-${e.id}`} onClick={() => setForm({ party: e.party, supersedesId: e.id })}
                          className="ml-auto text-slate-400 hover:text-slate-200">Update this entry</button>
                      )}
                    </div>
                    {e.history.length > 0 && (
                      <div className="mt-1">
                        <button data-testid={`dfm-history-${e.id}`}
                          onClick={() => setOpenHistory((cur) => { const next = new Set(cur); if (next.has(e.id)) next.delete(e.id); else next.add(e.id); return next; })}
                          className="text-xs text-slate-400 hover:text-slate-200">
                          {openHistory.has(e.id) ? '▾' : '▸'} {e.history.length} earlier version{e.history.length > 1 ? 's' : ''}
                        </button>
                        {openHistory.has(e.id) && e.history.map((h) => (
                          <div key={h.id} className="mt-1 pl-2 border-l border-slate-600 opacity-75">{body(h)}</div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      {form && open && (
        <DfmEntryForm partId={partId} topicId={topicId} party={form.party} supersedesId={form.supersedesId}
          onDone={() => { setForm(null); refresh(); }} onCancel={() => setForm(null)} />
      )}
    </div>
  );
}
```

The `div.contents` wrapper keeps each entry a full grid row (three cells) so rows stay in time order down the page while the card sits in its party's column.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/dfm && npx tsc --noEmit`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/nitrolinux/claude/plm2 && git add frontend/src/components/dfm/DfmLedger.tsx frontend/src/components/dfm/DfmLedger.test.tsx
git commit -m "feat(dfm): three-column ledger with history and finish/reopen

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: DFM archive topic list, mounted on the tool page with the document pane

**Files:**
- Create: `frontend/src/components/dfm/DfmArchive.tsx`
- Create: `frontend/src/components/dfm/DfmArchive.test.tsx`
- Modify: `frontend/src/pages/ToolDetail.tsx` (mount `DfmArchive` and a `DocumentPane` for PDFs)
- Modify: `frontend/src/pages/ToolDetail.test.tsx` (one more test)

**Interfaces:**
- Consumes: `listTopics`, `createTopic`, `DfmTopicSummary` (Task 8); `DfmLedger` (Task 12); `DocumentPane`, `PaneDocument` (Task 8).
- Produces: `DfmArchive({ partId, onOpenPdf })`. Query key `['dfm-topics', partId]`. Test ids: `dfm-archive`, `dfm-topic-<id>`, `dfm-new-topic`, `dfm-topic-title`, `dfm-create-topic`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/dfm/DfmArchive.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DfmArchive from './DfmArchive'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('./DfmLedger', () => ({ default: (p: { topicId: number }) => <div data-testid="ledger">topic {p.topicId}</div> }))

const topics = [
  { id: 2, tool_part_id: 7, title: 'Gate position', status: 'open', opened_by: 14, opened_at: '2026-09-24T09:00:00',
    closed_by: null, closed_at: null, entry_count: 3, last_activity: '2026-09-27T10:00:00' },
  { id: 1, tool_part_id: 7, title: 'Draft angles', status: 'finished_confirmed', opened_by: 14, opened_at: '2026-09-10T09:00:00',
    closed_by: 14, closed_at: '2026-09-20T09:00:00', entry_count: 5, last_activity: '2026-09-20T09:00:00' },
]

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><DfmArchive partId={7} onOpenPdf={vi.fn()} /></QueryClientProvider>)
}

describe('DfmArchive', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.post.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/7/dfm/topics') return Promise.resolve({ data: topics })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('lists topics with status, entry count and last activity', async () => {
    wrap()
    const row = await screen.findByTestId('dfm-topic-2')
    expect(row.textContent).toContain('Gate position')
    expect(row.textContent).toContain('Open')
    expect(row.textContent).toContain('3 entries')
    expect(row.textContent).toContain('2026-09-27')
    expect(screen.getByTestId('dfm-topic-1').textContent).toContain('Finished confirmed')
  })

  it('opens the ledger of the selected topic', async () => {
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-topic-2'))
    expect(screen.getByTestId('ledger').textContent).toBe('topic 2')
  })

  it('creates a topic and selects it', async () => {
    clientMocks.post.mockResolvedValue({ data: { ...topics[0], id: 9, title: 'Cooling layout', entry_count: 0 } })
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-new-topic'))
    fireEvent.change(screen.getByTestId('dfm-topic-title'), { target: { value: 'Cooling layout' } })
    fireEvent.click(screen.getByTestId('dfm-create-topic'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/dfm/topics', { title: 'Cooling layout' }))
    await waitFor(() => expect(screen.getByTestId('ledger').textContent).toBe('topic 9'))
  })

  it('says when there is nothing yet', async () => {
    clientMocks.get.mockImplementation(() => Promise.resolve({ data: [] }))
    wrap()
    expect((await screen.findByTestId('dfm-archive')).textContent).toContain('No DFM topic yet')
  })
})
```

Append to `frontend/src/pages/ToolDetail.test.tsx` (add `vi.mock('../components/dfm/DfmArchive', () => ({ default: () => <div data-testid="dfm-archive" /> }))` next to the other mocks):

```tsx
  it('mounts the DFM archive and no revision file list', async () => {
    renderTool()
    expect(await screen.findByTestId('dfm-archive')).toBeTruthy()
    expect(screen.queryByText(/Files ·/)).toBeNull()
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/dfm/DfmArchive.test.tsx src/pages/ToolDetail.test.tsx`
Expected: FAIL, `./DfmArchive` not found; the ToolDetail test fails on the mock of a missing module.

- [ ] **Step 3: Write the archive**

`frontend/src/components/dfm/DfmArchive.tsx`:

```tsx
/**
 * DfmArchive - the folder-like archive on a tool: one row per topic (title,
 * status, entries, last activity), "+ topic", and the selected topic's ledger.
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { createTopic, listTopics } from '../../api/dfm';
import type { PaneDocument } from '../parts/DocumentPane';
import DfmLedger from './DfmLedger';

function errMsg(error: unknown, fallback: string) {
  return (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;
}

interface Props {
  partId: number;
  onOpenPdf(doc: PaneDocument): void;
}

export default function DfmArchive({ partId, onOpenPdf }: Props) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<number | null>(null);
  const [newTitle, setNewTitle] = useState<string | null>(null);  // null = not adding

  const { data: topics } = useQuery({
    queryKey: ['dfm-topics', partId],
    queryFn: () => listTopics(partId),
  });

  const create = useMutation({
    mutationFn: (title: string) => createTopic(partId, title),
    onSuccess: (t) => {
      toast.success(`Topic "${t.title}" opened`);
      setNewTitle(null);
      setSelected(t.id);
      queryClient.invalidateQueries({ queryKey: ['dfm-topics', partId] });
      queryClient.invalidateQueries({ queryKey: ['changelog', String(partId)] });
    },
    onError: (e) => toast.error(errMsg(e, 'Could not open the topic')),
  });

  const submit = () => {
    const title = (newTitle ?? '').trim();
    if (!title) { toast.error('Give the topic a title'); return; }
    create.mutate(title);
  };

  return (
    <div data-testid="dfm-archive" className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xl font-bold text-slate-100">DFM archive</h2>
        {newTitle === null ? (
          <button data-testid="dfm-new-topic" onClick={() => setNewTitle('')}
            className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm">+ topic</button>
        ) : (
          <div className="flex items-center gap-2">
            <input data-testid="dfm-topic-title" autoFocus value={newTitle} onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') submit(); if (e.key === 'Escape') setNewTitle(null); }}
              placeholder="Topic, e.g. Gate position"
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 text-sm w-64" />
            <button data-testid="dfm-create-topic" onClick={submit} disabled={create.isPending}
              className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-sm">Open topic</button>
            <button onClick={() => setNewTitle(null)} className="px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100 text-sm">Cancel</button>
          </div>
        )}
      </div>

      {topics && topics.length === 0 && <p className="text-slate-500 text-sm">No DFM topic yet. Open one for the first request or study.</p>}
      <div className="divide-y divide-slate-700">
        {topics?.map((t) => (
          <button key={t.id} data-testid={`dfm-topic-${t.id}`} onClick={() => setSelected(t.id)}
            className={`w-full flex items-center gap-3 py-2 px-2 text-left text-sm rounded ${selected === t.id ? 'bg-slate-700' : 'hover:bg-slate-700/50'}`}>
            <span className="flex-1 text-slate-100 font-medium">{t.title}</span>
            <span className={`text-xs px-2 py-0.5 rounded ${t.status === 'open' ? 'bg-emerald-900 text-emerald-200' : 'bg-slate-600 text-slate-200'}`}>
              {t.status === 'open' ? 'Open' : 'Finished confirmed'}
            </span>
            <span className="text-slate-400 w-20 text-right">{t.entry_count} {t.entry_count === 1 ? 'entry' : 'entries'}</span>
            <span className="text-slate-500 font-mono text-xs w-24 text-right">{t.last_activity.slice(0, 10)}</span>
          </button>
        ))}
      </div>

      {selected !== null && <DfmLedger partId={partId} topicId={selected} onOpenPdf={onOpenPdf} />}
    </div>
  );
}
```

- [ ] **Step 4: Mount on the tool page with a document pane**

In `frontend/src/pages/ToolDetail.tsx` add imports:

```ts
import DocumentPane, { type PaneDocument } from '../components/parts/DocumentPane';
import DfmArchive from '../components/dfm/DfmArchive';
```

add state next to `showStartChange`:

```ts
  const [openDoc, setOpenDoc] = useState<PaneDocument | null>(null);
```

and render after `<ToolFieldsCard ... />`:

```tsx
        {openDoc && (
          <div className="bg-slate-800 rounded-lg border border-slate-700 mb-8 overflow-hidden">
            <div className="flex justify-end px-3 py-1">
              <button onClick={() => setOpenDoc(null)} className="text-xs text-slate-400 hover:text-slate-200">close</button>
            </div>
            <DocumentPane document={openDoc} />
          </div>
        )}
        <DfmArchive partId={part.id} onOpenPdf={setOpenDoc} />
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/dfm src/pages/ToolDetail.test.tsx src/pages/PartDetail.tool.test.tsx && npx tsc --noEmit`
Expected: all PASS, tsc clean.

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2 && git add frontend/src/components/dfm/DfmArchive.tsx frontend/src/components/dfm/DfmArchive.test.tsx frontend/src/pages/ToolDetail.tsx frontend/src/pages/ToolDetail.test.tsx
git commit -m "feat(dfm): topic list on the tool page with PDF pane

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 14: Verification

**Files:**
- Modify: `memory/1994-brose-volume-sheet-2026-09-23.md` (one paragraph: what shipped, commit, migrations)
- Modify: `docs/superpowers/specs/2026-09-23-tool-dfm-archive-design.md` (status line only: "plan executed", file route spelling `/parts/{id}/dfm/files/{file_id}/...`)

- [ ] **Step 1: Backend suite, lint-free**

Run: `cd /home/nitrolinux/claude/plm2/backend && pytest`
Expected: all PASS, including `test_tool_fields.py`, `test_dfm_models.py`, `test_dfm_topics.py`, `test_dfm_entries.py`, `test_dfm_files.py`, `test_part_relations.py`.

- [ ] **Step 2: Frontend suite, types and lint**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run && npx tsc --noEmit && npm run lint`
Expected: all PASS, tsc clean, lint 0 warnings.

- [ ] **Step 3: Migrations on the scratch SQLite DB, both directions**

```bash
cd /home/nitrolinux/claude/plm2/backend
DB=sqlite+aiosqlite:////tmp/claude-1000/-home-nitrolinux-claude-plm2/682e27d6-86ce-49d1-8aa2-d85ccfa61993/scratchpad/verify.db
DATABASE_URL=$DB alembic upgrade head
DATABASE_URL=$DB alembic downgrade 076
DATABASE_URL=$DB alembic upgrade head
DATABASE_URL=$DB alembic current
```

Expected: ends at `078 (head)`, no errors on the downgrade.

- [ ] **Step 4: Walk the feature in the running app**

Start the stack the usual way (`./run_backend.sh` and `cd frontend && npm run dev`, or the compose stack) and, on a tool part:
1. Open `/parts/<tool id>`: no 3D pane, no revision timeline, produced-article chips with `E<n> · <index>`, chip navigates to the article.
2. Tool tab: set cavities 4, tonnage 650, cycle 32.5, pick a toolmaker; reload, values stay; the changelog endpoint shows nothing for these (by design), the DFM actions below do.
3. DFM archive: "+ topic" "Gate position"; "+ entry" under KTX to Toolmaker + Tier 1 with a PDF and an xlsx; "+ entry" under Toolmaker to KTX; "Update this entry" on the KTX entry; the ledger shows "(updated)" and "1 earlier version"; click the PDF, it opens in the pane; the xlsx downloads.
4. "Finish confirmed": columns lose "+ entry", "Reopen" appears; reopen; add another entry.
5. `GET /api/v1/parts/<tool id>/changelog` lists `dfm_topic_opened`, `dfm_entry_recorded` (x4), `dfm_topic_closed`, `dfm_topic_reopened`.
6. Open an article part: page unchanged.

- [ ] **Step 5: Record the outcome**

Append to `memory/1994-brose-volume-sheet-2026-09-23.md`:

```markdown
**Tool view + DFM archive (plan docs/superpowers/plans/2026-09-23-tool-dfm-archive.md):**
alembic 077 (tool fields on parts) and 078 (dfm_topics / dfm_entries / dfm_entry_files);
`/api/v1/parts/{id}/dfm/...`; tools open in `ToolDetail` (no 3D, produced-article chips,
Tool card, DFM archive with three-column ledger). Prod: back up, `alembic upgrade head`
in the backend container, then `scripts/set_1994_tool_fields.py` dry run and `--apply`
after the cavities / cycle / tonnage are confirmed against RFQ 26 loop 37.
```

Update the spec's status line to `Status: design approved in chat ("go with approach"); implemented per plan 2026-09-23-tool-dfm-archive.md (file routes live at /parts/{id}/dfm/files/{file_id}/download|inline).`

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2 && git add memory/1994-brose-volume-sheet-2026-09-23.md docs/superpowers/specs/2026-09-23-tool-dfm-archive-design.md
git commit -m "docs(memory): tool view and DFM archive shipped

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

**Spec coverage.** §1 tool fields: Task 1 (columns, schema, update rule, 400 on non-tools), cavities fallback to the note: Task 10, 1994 script: Task 2. §2 models and append-only rules, file layout, changelog: Tasks 3-6. §3 API: topics Task 4, entries Task 5, files Task 6 (route spelled `/parts/{id}/dfm/files/...`, noted in Task 6 and Task 14). §4 tool page: branch and chips Task 9, Tool tab Task 10, archive/ledger/form Tasks 11-13, PDFs in the document pane Task 8 + 13. §5 errors: Tasks 1, 4, 5, 6. Testing list in the spec: every bullet maps to a test in Tasks 1, 5, 6, 9, 10, 11, 12, 13.

**Deviations from the spec, on purpose.** (a) File routes live under `/parts/{part_id}/dfm/files/{file_id}/...` rather than `/dfm-files/...` so the tool check and the part scope apply. (b) Files go under `<cwd>/uploads/dfm/...` like revision files, not `settings.upload_dir` (unused by every existing file route). (c) The 1994 script carries cavities in code and reads cycle/tonnage from RFQ2 by hand before apply, because the RFQ2 join columns are not known from this repo.

**Type consistency.** Relation keys `other_active_revision_name` / `other_active_customer_index` (Task 7) are what `ToolRelation` in Task 9 reads. `PaneDocument.inlineUrl` (Task 8) is what `DfmLedger.onOpenPdf` (Task 12) builds and `ToolDetail` (Task 13) renders. `DfmEntryInput` (Task 8) is what `DfmEntryForm` (Task 11) posts. Query keys: `['dfm-topics', partId]` (Task 13) and `['dfm-topic', partId, topicId]` (Task 12) are the ones each other invalidates; `['part', String(partId)]` (Task 10) matches `PartDetail`'s `['part', partId]` where `partId` is the route string.

**Review Focus coverage.** 1, 2, 3, 5 -> `test_addressed_to_rules`, `test_bare_entry_and_blank_sent_at`, `test_update_supersedes_and_keeps_history` (Task 5). 4 -> `falls back to the relation note` (Task 10).
