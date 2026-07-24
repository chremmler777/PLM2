# Equipment Numbering and Gauge Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give equipment a standard number (`<tool#>-<op code>`), import the 171-row gauge inventory against it, and record which tools each piece of equipment serves.

**Architecture:** A pure-function numbering module (parse/validate/allocate) with no DB access, consumed by a dry-run-first import script. Equipment lands in the existing `parts` table using the `item_category` values the model already documents (`assembly_equipment`, `gauge`) — no migration. Tool linkage reuses the existing `part_relations` table with two new `relation_type` values.

**Tech Stack:** Python 3.11/3.12, SQLAlchemy async, openpyxl, pytest + pytest-asyncio. PostgreSQL live (container `claude-plm2-db-1`), SQLite for tests.

## Global Constraints

- Backend tests run from `backend/` with `pytest`. Async tests need `pytestmark = pytest.mark.asyncio`.
- **No migration is needed.** `parts.item_category` is a plain `String(30)` with no CHECK constraint, and `app/models/part.py:54` already documents the vocabulary as `article, tool, assembly_equipment, gauge`. Use `assembly_equipment` and `gauge` verbatim — do NOT invent an `equipment` value, and do NOT write an alembic revision.
- `part_relations.relation_type` is `String(30)`, documented at `app/models/part.py:321` as `produces, checks, assembles, related`. This plan adds `serves` and `feeds`. Update that comment when you add them.
- Op codes are exactly two digits. A one-digit suffix (`0674-2`) is the existing second-tool marker and MUST NOT be read as an op code.
- `parts.project_id` and `parts.part_type` are NOT NULL. Equipment inherits `project_id` from the tool it is numbered after, and uses `part_type="purchased"` (matching how tools are created in `import_atlas.py:101`).
- Tool numbers are zero-padded to 4 characters in `parts` (`0745`, `0918`) but appear unpadded in the gauge sheet (`745`, `918/919`). Every lookup normalises by zero-padding to width 4.
- Commit after each task. Commit messages end with:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- Never create a tool part that does not exist. An unmatched tool number is reported and its row skipped.

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/services/equipment_numbering.py` (new) | Pure functions: parse an equipment number, classify an op code, normalise a sheet tool reference, allocate the next index. No DB, no I/O. |
| `backend/tests/test_equipment_numbering.py` (new) | Unit tests for the above. No fixtures, no DB. |
| `backend/import_gauges.py` (new) | One-off dry-run-first importer for FM-QUA-0094-17. Follows the shape of the existing `backend/import_atlas.py`. |
| `backend/tests/test_gauge_import.py` (new) | Tests the importer's row-planning logic against an in-memory table of rows — no Excel file needed. |
| `backend/app/models/part.py` (modify) | Extend the `relation_type` comment on line 321. |
| `backend/seed_vw426_equipment.py` (new) | Seeds the VW426 cell: degaters, the shared punch-and-weld station, and the 3457 `feeds` relations. |

---

### Task 1: Equipment numbering module

Pure functions, no database. Everything later depends on these names.

**Files:**
- Create: `backend/app/services/equipment_numbering.py`
- Test: `backend/tests/test_equipment_numbering.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `OP_CODE_KINDS: dict[int, str]` — first-digit → kind.
  - `normalise_tool_ref(raw: str) -> list[str]` — sheet cell → sorted, zero-padded 4-char tool numbers.
  - `classify(op_code: str) -> str` — `"10"` → `"eoat"`. Raises `ValueError` on unknown.
  - `parse_equipment_number(number: str) -> tuple[str, str | None]` — `("3454", "40")`; `("0674", None)` for a mold or second-tool number. Raises `ValueError` on a 3+ digit suffix.
  - `equipment_number(tool: str, op_family: int, index: int) -> str` — `("3454", 4, 1)` → `"3454-41"`.
  - `item_category_for(op_code: str) -> str` — `"gauge"` for the 40 family, `"assembly_equipment"` otherwise.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_equipment_numbering.py`:

```python
"""Equipment numbering per the 2026-07-24 'Naming of Equipment' scheme:
<tool#>[-<2-digit op code>]. Molds keep the bare tool number."""
import pytest

from app.services.equipment_numbering import (
    normalise_tool_ref, classify, parse_equipment_number, equipment_number,
    item_category_for,
)


def test_normalise_pads_to_four_digits():
    # The sheet writes 745; the PLM stores 0745.
    assert normalise_tool_ref("745") == ["0745"]
    assert normalise_tool_ref("3454") == ["3454"]


def test_normalise_splits_multi_tool_refs_and_sorts():
    assert normalise_tool_ref("918/919") == ["0918", "0919"]
    assert normalise_tool_ref("3454/3455") == ["3454", "3455"]


def test_normalise_strips_cavity_and_variant_suffixes():
    # 3197-001-0 and 930-002 name a variant of one tool, not an op code.
    assert normalise_tool_ref("3197-001-0") == ["3197"]
    assert normalise_tool_ref("930-002") == ["0930"]
    assert normalise_tool_ref("3101-01") == ["3101"]


def test_normalise_handles_mixed_multi_tool_and_suffix():
    assert normalise_tool_ref("931/990-001") == ["0931", "0990"]


def test_classify_maps_op_families():
    assert classify("10") == "eoat"
    assert classify("20") == "in_cell_station"
    assert classify("21") == "in_cell_station"
    assert classify("30") == "secondary_station"
    assert classify("40") == "gauge"
    assert classify("41") == "gauge"


def test_classify_rejects_unknown_family():
    with pytest.raises(ValueError):
        classify("50")


def test_parse_reads_tool_and_op_code():
    assert parse_equipment_number("3454-40") == ("3454", "40")


def test_parse_treats_bare_number_as_mold():
    assert parse_equipment_number("3454") == ("3454", None)


def test_parse_treats_single_digit_suffix_as_second_tool_not_op_code():
    # 0674-2 is the existing 'second tool' marker and must not become op code 2.
    assert parse_equipment_number("0674-2") == ("0674", None)


def test_parse_rejects_three_digit_suffix():
    with pytest.raises(ValueError):
        parse_equipment_number("3454-400")


def test_equipment_number_indexes_within_family():
    assert equipment_number("3454", 4, 0) == "3454-40"
    assert equipment_number("3454", 4, 1) == "3454-41"
    assert equipment_number("3450", 2, 0) == "3450-20"


def test_equipment_number_rejects_index_overflow():
    with pytest.raises(ValueError):
        equipment_number("3454", 4, 10)


def test_item_category_splits_gauges_from_equipment():
    assert item_category_for("40") == "gauge"
    assert item_category_for("41") == "gauge"
    assert item_category_for("10") == "assembly_equipment"
    assert item_category_for("30") == "assembly_equipment"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_equipment_numbering.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'app.services.equipment_numbering'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/equipment_numbering.py`:

```python
"""Equipment numbering: <tool#>[-<2-digit op code>].

Adopted 2026-07-24 from the 'Naming of Equipment' thread. Molds keep the bare
tool number — they take no -00 suffix — so the 251 existing tool records are
untouched. See docs/superpowers/specs/2026-07-24-equipment-numbering-and-gauge-import-design.md
"""
from __future__ import annotations

import re

TOOL_WIDTH = 4

# First digit of the op code -> kind of equipment.
OP_CODE_KINDS: dict[int, str] = {
    1: "eoat",
    2: "in_cell_station",
    3: "secondary_station",
    4: "gauge",
}

# A sheet cell may name several tools ("918/919") and may carry a cavity or
# variant suffix ("3197-001-0"). Only the leading 3-4 digit run identifies a tool.
_TOOL_TOKEN = re.compile(r"^(\d{3,4})")


def normalise_tool_ref(raw: str) -> list[str]:
    """Sheet tool reference -> sorted, zero-padded 4-char tool numbers.

    Splits multi-tool cells on '/', drops cavity/variant suffixes, and pads to the
    width the PLM stores ('745' -> '0745'). Returns [] when nothing parses, so the
    caller can report the row instead of inventing a tool.
    """
    out: list[str] = []
    for chunk in str(raw).split("/"):
        m = _TOOL_TOKEN.match(chunk.strip())
        if m:
            out.append(m.group(1).zfill(TOOL_WIDTH))
    return sorted(dict.fromkeys(out))


def classify(op_code: str) -> str:
    """Op code -> kind of equipment. Raises ValueError on an unknown family."""
    if not re.fullmatch(r"\d{2}", op_code):
        raise ValueError(f"Op code must be exactly two digits, got {op_code!r}")
    kind = OP_CODE_KINDS.get(int(op_code[0]))
    if kind is None:
        raise ValueError(f"Unknown op-code family {op_code!r}")
    return kind


def parse_equipment_number(number: str) -> tuple[str, str | None]:
    """Split an equipment number into (tool number, op code or None).

    A bare number is a mold. A ONE-digit suffix is the pre-existing 'second tool'
    marker ('0674-2') and yields None, not an op code — the two namespaces share a
    separator and only length tells them apart.
    """
    head, sep, tail = number.partition("-")
    if not sep:
        return head, None
    if len(tail) == 1 and tail.isdigit():
        return head, None
    if not re.fullmatch(r"\d{2}", tail):
        raise ValueError(f"Not a valid op-code suffix: {number!r}")
    classify(tail)  # reject an unknown family here rather than downstream
    return head, tail


def equipment_number(tool: str, op_family: int, index: int) -> str:
    """Compose a number: ('3454', 4, 1) -> '3454-41'."""
    if op_family not in OP_CODE_KINDS:
        raise ValueError(f"Unknown op-code family {op_family}")
    if not 0 <= index <= 9:
        raise ValueError(
            f"Only 10 slots per family; index {index} does not fit in one digit")
    return f"{tool}-{op_family}{index}"


def item_category_for(op_code: str) -> str:
    """Which parts.item_category an op code belongs in.

    Gauges are split out from generic equipment: they are inventoried, audited,
    and owned by Quality rather than Tooling.
    """
    return "gauge" if classify(op_code) == "gauge" else "assembly_equipment"
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && pytest tests/test_equipment_numbering.py -q`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add backend/app/services/equipment_numbering.py backend/tests/test_equipment_numbering.py
git commit -m "feat(equipment): operation-number parsing and classification

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Relation vocabulary

Two new `relation_type` values. A comment-only model change plus a test that pins the vocabulary, so a later reader does not have to guess which strings are legal.

**Files:**
- Modify: `backend/app/models/part.py:310-322`
- Test: `backend/tests/test_equipment_relations.py` (new)

**Interfaces:**
- Consumes: `PartRelation` from `app.models.part`.
- Produces: `EQUIPMENT_RELATION_TYPES: frozenset[str]` in `app/services/equipment_numbering.py` — `{"serves", "feeds"}`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_equipment_relations.py`:

```python
"""Equipment linkage reuses part_relations. 'serves' points equipment at every
tool it covers — the number only carries the lowest one, so coverage must be
readable without parsing numbers. 'feeds' points a tool at a downstream tool."""
import pytest

from app.services.equipment_numbering import EQUIPMENT_RELATION_TYPES

pytestmark = pytest.mark.asyncio


def test_vocabulary_is_pinned():
    assert EQUIPMENT_RELATION_TYPES == frozenset({"serves", "feeds"})


async def test_serves_records_every_covered_tool(session_factory, seed):
    """A gauge numbered after the lowest tool still records both tools."""
    from app.models.part import Part, PartRelation

    async with session_factory() as s:
        tools = []
        for pn in ("3454", "3455"):
            t = Part(project_id=seed["project_id"], part_number=pn, name=f"tool {pn}",
                     part_type="purchased", item_category="tool",
                     created_by=seed["admin_id"])
            s.add(t)
            tools.append(t)
        gauge = Part(project_id=seed["project_id"], part_number="3454-40",
                     name="Rear Cladding gauge", part_type="purchased",
                     item_category="gauge", created_by=seed["admin_id"])
        s.add(gauge)
        await s.flush()
        for t in tools:
            s.add(PartRelation(from_part_id=gauge.id, to_part_id=t.id,
                               relation_type="serves", created_by=seed["admin_id"]))
        await s.commit()
        gauge_id = gauge.id

    from sqlalchemy import select
    async with session_factory() as s:
        rows = (await s.execute(
            select(PartRelation).where(PartRelation.from_part_id == gauge_id))
        ).scalars().all()
        assert {r.relation_type for r in rows} == {"serves"}
        assert len(rows) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_equipment_relations.py -q`
Expected: collection error — `ImportError: cannot import name 'EQUIPMENT_RELATION_TYPES'`.

- [ ] **Step 3: Add the vocabulary constant**

Append to `backend/app/services/equipment_numbering.py`:

```python
# Linkage vocabulary added alongside part_relations' existing
# produces / checks / assembles / related.
#   serves - equipment -> each tool it covers. The number carries only the
#            lowest such tool, so these rows are the authority on coverage.
#   feeds  - tool -> downstream tool whose station consumes its parts.
EQUIPMENT_RELATION_TYPES = frozenset({"serves", "feeds"})
```

- [ ] **Step 4: Update the model comment**

In `backend/app/models/part.py`, replace line 321:

```python
    relation_type: Mapped[str] = mapped_column(String(30))  # produces, checks, assembles, related
```

with:

```python
    # produces, checks, assembles, related, serves, feeds
    # (serves/feeds link equipment and tools — see app/services/equipment_numbering.py)
    relation_type: Mapped[str] = mapped_column(String(30))
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && pytest tests/test_equipment_relations.py -q`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add backend/app/services/equipment_numbering.py backend/app/models/part.py backend/tests/test_equipment_relations.py
git commit -m "feat(equipment): add serves/feeds relation vocabulary

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Gauge import planner

The decision logic, separated from Excel reading and from the database so it can be tested on plain tuples. This is where the lowest-ID rule and index allocation live.

**Files:**
- Create: `backend/app/services/gauge_import.py`
- Test: `backend/tests/test_gauge_import.py`

**Interfaces:**
- Consumes: `normalise_tool_ref`, `equipment_number` from `app.services.equipment_numbering`.
- Produces:
  - `GaugeRow` — dataclass: `customer: str`, `tool_ref: str`, `description: str`, `legacy_no: str`, `storage: str`.
  - `PlannedGauge` — dataclass: `part_number: str`, `name: str`, `notes: str`, `owner_tool: str`, `serves: list[str]`, `legacy_no: str`.
  - `plan_import(rows: list[GaugeRow], known_tools: set[str], existing: set[tuple[str, str]]) -> tuple[list[PlannedGauge], list[str]]` — returns (plan, report lines). `existing` is a set of `(tool_number, legacy_no)` pairs already imported.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_gauge_import.py`:

```python
"""Planning the FM-QUA-0094-17 import. Pure decision logic over plain rows:
lowest-tool-ID ownership, per-tool index allocation, idempotency, and a report
that names every skipped row rather than guessing."""
import pytest

from app.services.gauge_import import GaugeRow, plan_import

TOOLS = {"0918", "0919", "3454", "3455", "0745"}


def row(tool_ref, desc="Cover", legacy="P1", customer="BMW", storage="Cage A/1/2"):
    return GaugeRow(customer=customer, tool_ref=tool_ref, description=desc,
                    legacy_no=legacy, storage=storage)


def test_single_tool_gauge_gets_index_zero():
    plan, report = plan_import([row("745", legacy="P7")], TOOLS, set())
    assert len(plan) == 1
    assert plan[0].part_number == "0745-40"
    assert plan[0].owner_tool == "0745"
    assert plan[0].serves == ["0745"]


def test_multi_tool_gauge_is_numbered_after_the_lowest_tool():
    plan, report = plan_import([row("3454/3455", legacy="P1289")], TOOLS, set())
    assert plan[0].part_number == "3454-40"
    assert plan[0].serves == ["3454", "3455"]
    assert any("3454/3455" in line and "3454" in line for line in report)


def test_two_gauges_on_one_tool_take_consecutive_indices():
    plan, _ = plan_import(
        [row("745", desc="LH", legacy="P7"), row("745", desc="RH", legacy="P57")],
        TOOLS, set())
    assert [p.part_number for p in plan] == ["0745-40", "0745-41"]


def test_index_allocation_counts_against_the_owner_tool_only():
    plan, _ = plan_import(
        [row("3454/3455", legacy="P1289"), row("3455", legacy="P9")], TOOLS, set())
    # the multi-tool gauge is owned by 3454, so 3455 is still free at index 0
    assert [p.part_number for p in plan] == ["3454-40", "3455-40"]


def test_unknown_tool_is_reported_and_skipped():
    plan, report = plan_import([row("9999", legacy="P3")], TOOLS, set())
    assert plan == []
    assert any("9999" in line for line in report)


def test_unparseable_tool_ref_is_reported_and_skipped():
    plan, report = plan_import([row("n/a", legacy="P3")], TOOLS, set())
    assert plan == []
    assert any("n/a" in line for line in report)


def test_already_imported_row_is_skipped():
    # Idempotency key is (owner tool, legacy no) — P468/P481/P419 each appear
    # twice in the sheet on DIFFERENT tools, so the legacy number alone is not unique.
    plan, _ = plan_import([row("745", legacy="P7")], TOOLS, {("0745", "P7")})
    assert plan == []


def test_same_legacy_number_on_two_tools_both_import():
    plan, _ = plan_import(
        [row("745", legacy="P468"), row("3454", legacy="P468")], TOOLS, set())
    assert [p.part_number for p in plan] == ["0745-40", "3454-40"]


def test_notes_carry_the_legacy_number_and_storage():
    plan, _ = plan_import(
        [row("745", legacy="P7", storage="Cage Racks / C / 5 / 3")], TOOLS, set())
    assert "P7" in plan[0].notes
    assert "Cage Racks / C / 5 / 3" in plan[0].notes


def test_eleventh_gauge_on_one_tool_is_reported_not_crashed():
    rows = [row("745", legacy=f"P{i}") for i in range(11)]
    plan, report = plan_import(rows, TOOLS, set())
    assert len(plan) == 10
    assert any("P10" in line for line in report)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_gauge_import.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'app.services.gauge_import'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/gauge_import.py`:

```python
"""Plan the FM-QUA-0094-17 gauge-inventory import.

Pure decision logic over plain rows so it can be tested without Excel or a
database. The importer script reads the sheet, calls plan_import, prints the
report, and only then writes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.equipment_numbering import equipment_number, normalise_tool_ref

GAUGE_FAMILY = 4
MAX_PER_TOOL = 10


@dataclass
class GaugeRow:
    """One data row of the inventory sheet."""
    customer: str
    tool_ref: str
    description: str
    legacy_no: str
    storage: str


@dataclass
class PlannedGauge:
    part_number: str
    name: str
    notes: str
    owner_tool: str
    serves: list[str] = field(default_factory=list)
    legacy_no: str = ""


def plan_import(
    rows: list[GaugeRow],
    known_tools: set[str],
    existing: set[tuple[str, str]],
) -> tuple[list[PlannedGauge], list[str]]:
    """Turn sheet rows into a write plan plus a human-readable report.

    ``known_tools`` are the zero-padded numbers of tool parts that exist. Rows
    naming anything else are skipped and reported — this importer never creates a
    tool. ``existing`` holds (owner tool, legacy no) pairs already imported; the
    legacy number alone is not unique across the sheet.
    """
    plan: list[PlannedGauge] = []
    report: list[str] = []
    next_index: dict[str, int] = {}

    for r in rows:
        tools = normalise_tool_ref(r.tool_ref)
        if not tools:
            report.append(f"SKIP unparseable tool reference {r.tool_ref!r} "
                          f"({r.legacy_no} {r.description})")
            continue

        unknown = [t for t in tools if t not in known_tools]
        if unknown:
            report.append(f"SKIP {r.tool_ref!r}: no tool part for "
                          f"{', '.join(unknown)} ({r.legacy_no} {r.description})")
            continue

        owner = tools[0]  # normalise_tool_ref sorts, so this is the lowest
        if len(tools) > 1:
            report.append(f"COLLAPSE {r.tool_ref!r} -> owner {owner}, "
                          f"serves {', '.join(tools)} ({r.legacy_no})")

        if (owner, r.legacy_no) in existing:
            report.append(f"SKIP already imported: {owner} / {r.legacy_no}")
            continue

        index = next_index.get(owner, 0)
        if index >= MAX_PER_TOOL:
            report.append(f"SKIP {r.legacy_no}: tool {owner} already has "
                          f"{MAX_PER_TOOL} gauges; op code has one index digit")
            continue
        next_index[owner] = index + 1

        notes = (f"Legacy gauge no: {r.legacy_no}. Storage: {r.storage}. "
                 f"Customer: {r.customer}. Sheet tool ref: {r.tool_ref}.")
        plan.append(PlannedGauge(
            part_number=equipment_number(owner, GAUGE_FAMILY, index),
            name=r.description.strip(),
            notes=notes,
            owner_tool=owner,
            serves=tools,
            legacy_no=r.legacy_no,
        ))

    return plan, report
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && pytest tests/test_gauge_import.py -q`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add backend/app/services/gauge_import.py backend/tests/test_gauge_import.py
git commit -m "feat(equipment): gauge-import planner with lowest-tool-ID ownership

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Importer script

Reads the workbook, loads existing state, prints the report, and writes only when told to. Mirrors `backend/import_atlas.py` in shape and idempotency.

**Files:**
- Create: `backend/import_gauges.py`

**Interfaces:**
- Consumes: `GaugeRow`, `plan_import` (Task 3); `Part`, `PartRelation` from `app.models.part`; `AsyncSessionLocal` from `app.models.database`.
- Produces: a CLI — `python import_gauges.py <xlsx path>` for a dry run, `--write` to commit.

- [ ] **Step 1: Write the script**

Create `backend/import_gauges.py`:

```python
"""Import the gauge inventory (FM-QUA-0094-17) as 'gauge' parts.

Dry run by default — prints the full plan and writes nothing:
    python import_gauges.py "/path/to/FM-QUA-0094-17 Gauge Inventory.xlsx"

Commit it:
    python import_gauges.py "/path/to/...xlsx" --write

Idempotent: a gauge already recorded for the same (owner tool, legacy no) is
skipped, so re-running adds nothing. Never creates a tool part — rows naming an
unknown tool are reported and skipped.
"""
import asyncio
import sys

import openpyxl
from sqlalchemy import select

from app.models.database import AsyncSessionLocal
from app.models.part import Part, PartRelation
from app.services.gauge_import import GaugeRow, plan_import

CREATED_BY = 3  # chris
HEADER_ROWS = 2  # title row + column headers; data starts on row 3


def read_rows(path: str) -> list[GaugeRow]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Sheet1"]
    rows: list[GaugeRow] = []
    for raw in ws.iter_rows(min_row=HEADER_ROWS + 1, values_only=True):
        customer, tool_ref, desc, legacy, area, row_, bay, shelf = (raw + (None,) * 8)[:8]
        if not tool_ref:
            continue
        storage = " / ".join(str(x).strip() for x in (area, row_, bay, shelf) if x)
        rows.append(GaugeRow(
            customer=str(customer or "").strip(),
            tool_ref=str(tool_ref).strip(),
            description=str(desc or "").strip(),
            legacy_no=str(legacy or "").strip(),
            storage=storage,
        ))
    return rows


async def main(path: str, write: bool) -> None:
    rows = read_rows(path)
    print(f"Read {len(rows)} data rows from {path}")

    async with AsyncSessionLocal() as s:
        tool_rows = (await s.execute(
            select(Part.part_number, Part.id, Part.project_id).where(
                Part.item_category == "tool"))).all()
        known_tools = {r.part_number for r in tool_rows}
        tool_by_number = {r.part_number: r for r in tool_rows}

        # Existing gauges keyed by (owner tool, legacy no), recovered from the
        # notes text this importer writes.
        existing: set[tuple[str, str]] = set()
        for pn, notes in (await s.execute(
                select(Part.part_number, Part.description).where(
                    Part.item_category == "gauge"))).all():
            owner = pn.split("-")[0]
            if notes and "Legacy gauge no: " in notes:
                legacy = notes.split("Legacy gauge no: ", 1)[1].split(".", 1)[0].strip()
                existing.add((owner, legacy))

        plan, report = plan_import(rows, known_tools, existing)

        print(f"\n--- report ({len(report)} lines) ---")
        for line in report:
            print(" ", line)
        print(f"\n--- plan ({len(plan)} gauges) ---")
        for p in plan:
            print(f"  {p.part_number:12} serves {','.join(p.serves):12} {p.name}")

        if not write:
            print("\nDRY RUN — nothing written. Re-run with --write to commit.")
            return

        for p in plan:
            owner = tool_by_number[p.owner_tool]
            gauge = Part(project_id=owner.project_id, part_number=p.part_number,
                         name=p.name or p.part_number, description=p.notes,
                         part_type="purchased", item_category="gauge",
                         data_classification="confidential", created_by=CREATED_BY)
            s.add(gauge)
            await s.flush()
            for tool_number in p.serves:
                s.add(PartRelation(
                    from_part_id=gauge.id, to_part_id=tool_by_number[tool_number].id,
                    relation_type="serves", created_by=CREATED_BY))
        await s.commit()
        print(f"\nWrote {len(plan)} gauges.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--write"]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    asyncio.run(main(args[0], "--write" in sys.argv))
```

- [ ] **Step 2: Dry-run it against the real sheet**

Run:
```bash
cd /home/nitrolinux/claude/plm2/backend
python import_gauges.py "/mnt/c/Users/christoph.demmler/OneDrive - KTX America Corporation/Desktop/Claude/FM-QUA-0094-17 Gauge Inventory.xlsx"
```
Expected: `Read 171 data rows`; a report containing 5 `COLLAPSE` lines (`918/919`, `929/991`, `931/990-001`, `931/990-002`, `3454/3455`); a plan listing gauges as `<tool>-4N`; and `DRY RUN — nothing written`.

**Do not pass `--write` yet.** Report the dry-run counts — how many planned, how many skipped for an unknown tool — and hand back to the user for a decision. Importing 171 rows into the live database is theirs to authorise.

- [ ] **Step 3: Commit the script**

```bash
cd /home/nitrolinux/claude/plm2
git add backend/import_gauges.py
git commit -m "feat(equipment): dry-run-first gauge inventory importer

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: VW426 cell equipment seed

The stations for tools 3450-3457, including the shared punch-and-weld and the 3457 feed. Small enough to state as data.

**Files:**
- Create: `backend/seed_vw426_equipment.py`

**Interfaces:**
- Consumes: `equipment_number`, `item_category_for` (Task 1); `Part`, `PartRelation`; `AsyncSessionLocal`.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the script**

Create `backend/seed_vw426_equipment.py`:

```python
"""Seed the VW426 (project 1864) cell equipment. Dry run by default; --write commits.

Facts, per Christoph 2026-07-24:
  - 3450, 3451, 3452, 3453, 3456 each have a degater and are finished after degating.
  - 3454 and 3455 share one punch-and-weld station; it is numbered after the
    lowest tool it serves, so 3454-30.
  - 3457 has no degater. Its brackets are welded downstream: two into 3454 and
    two into 3455.
"""
import asyncio
import sys

from sqlalchemy import select

from app.models.database import AsyncSessionLocal
from app.models.part import Part, PartRelation
from app.services.equipment_numbering import equipment_number, item_category_for

CREATED_BY = 3  # chris

DEGATER_TOOLS = ["3450", "3451", "3452", "3453", "3456"]
PW_STATION_SERVES = ["3454", "3455", "3457"]
FEEDS = [("3457", "3454", "2 brackets"), ("3457", "3455", "2 brackets")]


async def main(write: bool) -> None:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(Part.part_number, Part.id, Part.project_id).where(
                Part.item_category == "tool",
                Part.part_number.in_(DEGATER_TOOLS + PW_STATION_SERVES)))).all()
        by_number = {r.part_number: r for r in rows}

        missing = set(DEGATER_TOOLS + PW_STATION_SERVES) - set(by_number)
        if missing:
            print(f"ABORT: missing tool parts {sorted(missing)}")
            return

        planned: list[tuple[str, str, list[str]]] = []
        for tool in DEGATER_TOOLS:
            planned.append((equipment_number(tool, 2, 0), "Degate station", [tool]))
        planned.append((equipment_number("3454", 3, 0),
                        "Punch & weld station", PW_STATION_SERVES))

        existing = {pn for (pn,) in (await s.execute(
            select(Part.part_number).where(
                Part.part_number.in_([p[0] for p in planned])))).all()}

        for number, name, serves in planned:
            mark = "EXISTS" if number in existing else "CREATE"
            print(f"  {mark} {number:10} {name:22} serves {','.join(serves)}")
        for src, dst, note in FEEDS:
            print(f"  FEEDS  {src} -> {dst} ({note})")

        if not write:
            print("\nDRY RUN — nothing written. Re-run with --write to commit.")
            return

        for number, name, serves in planned:
            if number in existing:
                continue
            owner = by_number[serves[0]]
            eq = Part(project_id=owner.project_id, part_number=number, name=name,
                      part_type="purchased",
                      item_category=item_category_for(number.split("-")[1]),
                      data_classification="confidential", created_by=CREATED_BY)
            s.add(eq)
            await s.flush()
            for tool in serves:
                s.add(PartRelation(from_part_id=eq.id, to_part_id=by_number[tool].id,
                                   relation_type="serves", created_by=CREATED_BY))
        for src, dst, note in FEEDS:
            s.add(PartRelation(from_part_id=by_number[src].id,
                               to_part_id=by_number[dst].id,
                               relation_type="feeds", notes=note,
                               created_by=CREATED_BY))
        await s.commit()
        print("\nSeeded VW426 cell equipment.")


if __name__ == "__main__":
    asyncio.run(main("--write" in sys.argv))
```

- [ ] **Step 2: Dry-run it**

Run: `cd backend && python seed_vw426_equipment.py`
Expected: six `CREATE` lines (`3450-20`, `3451-20`, `3452-20`, `3453-20`, `3456-20`, `3454-30`), two `FEEDS` lines, then `DRY RUN`.

Hand the output to the user before writing. Do not pass `--write` without their go-ahead.

- [ ] **Step 3: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add backend/seed_vw426_equipment.py
git commit -m "feat(equipment): VW426 cell equipment seed script

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Full-suite regression check

**Files:** none.

- [ ] **Step 1: Run the backend suite**

Run: `cd backend && pytest -q -p no:logging`
Expected: all pass. The suite takes roughly 8 minutes; run it in the background rather than blocking.

No frontend change is in scope, so `npm test` is not required.

- [ ] **Step 2: Report**

State the pass/fail counts and the two dry-run summaries. The live writes (`--write` on both scripts) remain the user's call.

---

## Self-Review

**Spec coverage:**
- §1 numbering, including the one-digit second-tool collision rule → Task 1. ✓
- §2 storage: `assembly_equipment`/`gauge` categories, legacy no + location in notes, no side table → Tasks 1 (`item_category_for`), 3 (`notes`), 4 (write). ✓
- §3 linkage: `serves` and `feeds`, lowest-ID ownership → Tasks 2, 3, 5. ✓
- §4 import: dry-run first, collapse report, unmatched report, idempotent re-run → Tasks 3, 4. ✓
- §5 process flow and §6 picker → deliberately out of scope; the spec sequences them after this plan.

**Deviations from the spec, and why:**
- The spec said `item_category` gains `equipment`; the model at `part.py:54` already documents `assembly_equipment`. Using the existing word, and no migration is needed at all — the spec assumed one.
- The spec implied the legacy `P#` could key idempotency. It cannot: `P468`, `P481` and `P419` each appear twice in the sheet. The key is `(owner tool, legacy no)`.
- The spec did not mention zero-padding. The PLM stores `0745` where the sheet says `745`; without normalisation nearly every BMW row would be reported as an unknown tool.

**Placeholder scan:** no TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `normalise_tool_ref`, `equipment_number`, `item_category_for`, `classify`, `parse_equipment_number` are defined in Task 1 and used with those exact signatures in Tasks 3 and 5. `GaugeRow`/`PlannedGauge` field names match between Task 3's definition and Task 4's use (`part_number`, `name`, `notes`, `owner_tool`, `serves`, `legacy_no`). `EQUIPMENT_RELATION_TYPES` defined in Task 2, asserted in its own test. ✓
