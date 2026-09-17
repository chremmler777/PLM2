# Customer Data Index (E1 / 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the RFQ/ENG/IND/ECR revision naming with `E<n>[.<m>]` (customer review data) and `<n>[.<m>]` (customer official data), add a part lifecycle phase (rfq / nominated / series), and a "customer data received" action that is the only way to create a major revision.

**Architecture:** A pure naming module (`revision_naming.py`) owns parse/format/next-name rules and the legacy rename mapping, so it is unit-testable without a DB. `RevisionService` shrinks to phase-agnostic operations: receive customer data (major), create proposal (minor), promote, reject, unreject. The change engine spawns ECN revisions as minors under the part's active major. One Alembic migration adds columns and renames existing revisions. The frontend `PartDetail` page gets a new revision timeline and a customer-data dialog; all phase-specific buttons go away.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (backend, `cd backend && python -m pytest tests/ -q`), React + TanStack Query + Vitest (frontend, `cd frontend && npx vitest run`).

**Spec:** `docs/superpowers/specs/2026-09-17-customer-data-index-design.md`

## Global Constraints

- Revision names are exactly `E<n>`, `E<n>.<m>`, `<n>`, `<n>.<m>` with n, m ≥ 1. No other shape may be written to `part_revisions.revision_name`.
- `PartRevision.phase` values are exactly `review` and `official`.
- `Part.lifecycle_phase` values are exactly `rfq`, `nominated`, `series`.
- `customer_statement` values are exactly `review` and `official`; `source` values are exactly `customer` and `internal`.
- A major revision is created only through `RevisionService.receive_customer_data` or `RevisionService.promote_revision`. Both require `statement`.
- `review` data after any `official` major on the same part is rejected with HTTP 409.
- Counters never reset. The E counter and the numeric counter are independent.
- Migrations are forward-only, guarded with `inspect()` like `071_offer_is_partial.py`, dialect-neutral (SQLite in dev/tests, PostgreSQL in prod).
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Run the full backend suite (`cd backend && python -m pytest tests/ -q -x`) before every commit from Task 3 onward; it must stay green.

---

## File map

| File | Responsibility |
|---|---|
| `backend/app/services/revision_naming.py` (new) | Pure name rules: parse, format, next major, next minor, legacy rename, `RevisionRuleViolation` |
| `backend/tests/test_revision_naming.py` (new) | Unit tests for the module above |
| `backend/app/models/part.py` | `RevisionPhase` = review/official; new revision columns; new part columns |
| `backend/alembic/versions/072_customer_data_index.py` (new) | Add columns, rename legacy revisions |
| `backend/tests/test_migration_072.py` (new) | Runs the rename mapping against a legacy fixture |
| `backend/app/services/part_service.py` | `RevisionService`: receive_customer_data, create_proposal, promote_revision (with statement), reject, unreject, set_lifecycle_phase; delete phase-specific methods |
| `backend/app/schemas/part.py` | New request/response fields; delete phase-specific request schemas |
| `backend/app/api/v1/items/parts.py` | New endpoints `customer-data`, `proposals`, `lifecycle-phase`; delete phase-specific endpoints |
| `backend/app/services/change_service.py` | `spawn_ecn_revisions` uses `next_minor_name` under the active major |
| `backend/tests/conftest.py` | `part` fixture creates E1 via `customer-data` |
| `backend/tests/test_customer_data_index.py` (new) | API tests for the new flow |
| `backend/tests/test_wf_seeds.py`, `backend/tests/test_cancel_teardown.py`, `backend/tests/test_item_categories.py`, `backend/tests/test_revision_evidence.py`, `backend/tests/test_impact_tree.py`, `backend/tests/test_user_departments.py` | Replace `/revisions/rfq` and `ECR1.1`/`ecn` literals |
| `frontend/src/pages/PartDetail.tsx` | Uses `RevisionTimeline` and `CustomerDataDialog`; lifecycle phase header |
| `frontend/src/components/parts/RevisionTimeline.tsx` (new) | Grouped majors with minors, badges, action buttons |
| `frontend/src/components/parts/RevisionTimeline.test.tsx` (new) | Badge and grouping tests |
| `frontend/src/components/parts/CustomerDataDialog.tsx` (new) | Statement / index / date / summary form |
| `frontend/src/pages/ProjectDetailPage.tsx` | Replace RFQ button with the dialog; phase colours |

---

### Task 1: Pure naming module

**Files:**
- Create: `backend/app/services/revision_naming.py`
- Test: `backend/tests/test_revision_naming.py`

**Interfaces:**
- Produces:
  - `class RevisionRuleViolation(ValueError)` — raised when a rule (review after official) is broken.
  - `parse_name(name: str) -> tuple[bool, int, int | None]` — `(is_official, major, minor)`. Raises `ValueError` on any other shape.
  - `format_name(is_official: bool, major: int, minor: int | None = None) -> str`
  - `next_major_name(existing_major_names: list[str], statement: str) -> str` — `statement` is `"review"` or `"official"`.
  - `next_minor_name(parent_name: str, existing_child_names: list[str]) -> str`
  - `legacy_rename(rows: list[tuple[int, str, str, int | None, datetime]]) -> dict[int, tuple[str, str]]` — input `(id, revision_name, phase, parent_revision_id, created_at)` for one part; output `{id: (new_name, new_phase)}`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_revision_naming.py
"""Pure rules for E<n>[.<m>] (review) and <n>[.<m>] (official) names."""
from datetime import datetime

import pytest

from app.services.revision_naming import (
    RevisionRuleViolation, format_name, legacy_rename, next_major_name,
    next_minor_name, parse_name,
)


def test_parse_and_format_roundtrip():
    for name, expected in [
        ("E1", (False, 1, None)), ("E12.3", (False, 12, 3)),
        ("1", (True, 1, None)), ("4.2", (True, 4, 2)),
    ]:
        assert parse_name(name) == expected
        assert format_name(*expected) == name


@pytest.mark.parametrize("bad", ["RFQ1", "ENG1.1", "IND1", "ECR1.1", "E", "E0", "0", "1.0", "e1", "E1.1.1", ""])
def test_parse_rejects_legacy_and_garbage(bad):
    with pytest.raises(ValueError):
        parse_name(bad)


def test_first_major_is_e1_or_1():
    assert next_major_name([], "review") == "E1"
    assert next_major_name([], "official") == "1"


def test_counters_are_independent_and_never_reset():
    assert next_major_name(["E1", "E2"], "review") == "E3"
    assert next_major_name(["E1", "E2"], "official") == "1"
    assert next_major_name(["E1", "E2", "1"], "official") == "2"
    # gaps do not matter, highest wins
    assert next_major_name(["1", "3"], "official") == "4"


def test_review_after_official_is_a_rule_violation():
    with pytest.raises(RevisionRuleViolation):
        next_major_name(["E1", "1"], "review")


def test_next_major_ignores_minors_in_input():
    assert next_major_name(["E1", "E1.1", "E1.2"], "review") == "E2"


def test_next_minor():
    assert next_minor_name("E1", []) == "E1.1"
    assert next_minor_name("E1", ["E1.1", "E1.2"]) == "E1.3"
    assert next_minor_name("2", ["2.1"]) == "2.2"


def test_next_minor_refuses_minor_parent():
    with pytest.raises(ValueError):
        next_minor_name("E1.1", [])


def _row(i, name, phase, parent=None, day=1):
    return (i, name, phase, parent, datetime(2026, 1, day))


def test_legacy_rename_maps_rfq_eng_ind_ecr():
    rows = [
        _row(1, "RFQ1", "rfq_phase", day=1),
        _row(2, "RFQ1.1", "rfq_phase", parent=1, day=2),
        _row(3, "RFQ2", "rfq_phase", day=3),
        _row(4, "ENG1", "engineering", day=4),
        _row(5, "ENG1.1", "engineering", parent=4, day=5),
        _row(6, "IND1", "freeze", day=6),
        _row(7, "ECR1.1", "ecn", day=7),
        _row(8, "IND2", "freeze", day=8),
        _row(9, "ECR2.1", "ecn", day=9),
    ]
    assert legacy_rename(rows) == {
        1: ("E1", "review"), 2: ("E1.1", "review"), 3: ("E2", "review"),
        4: ("E3", "review"), 5: ("E3.1", "review"),
        6: ("1", "official"), 7: ("1.1", "official"),
        8: ("2", "official"), 9: ("2.1", "official"),
    }


def test_legacy_rename_orphan_ecr_without_freeze_hangs_off_first_official():
    # ECR spawned by the change engine on a part that never had IND: it
    # becomes 1.1 and phase official; a later ECR on the same part is 1.2.
    rows = [_row(1, "E1", "review"), _row(2, "ECR1.1", "ecn", day=2), _row(3, "ECR2.1", "ecn", day=3)]
    assert legacy_rename(rows) == {1: ("E1", "review"), 2: ("1.1", "official"), 3: ("1.2", "official")}


def test_legacy_rename_leaves_new_style_names_alone():
    rows = [_row(1, "E1", "review"), _row(2, "E1.1", "review", parent=1, day=2), _row(3, "1", "official", day=3)]
    assert legacy_rename(rows) == {1: ("E1", "review"), 2: ("E1.1", "review"), 3: ("1", "official")}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_revision_naming.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.revision_naming'`

- [ ] **Step 3: Write the module**

```python
# backend/app/services/revision_naming.py
"""Revision name rules.

The major number is always a customer-stated data state; the minor number is
always our internal iteration on it. Review data is E-prefixed (E1, E1.1),
official data is a bare number (1, 1.1). The two counters are independent and
never reset. Once a part has official data, new review data is refused.
"""
from __future__ import annotations

import re
from datetime import datetime

NAME_RE = re.compile(r"^(E?)([1-9]\d*)(?:\.([1-9]\d*))?$")
LEGACY_RE = re.compile(r"^(RFQ|ENG|IND|ECR)([1-9]\d*)(?:\.([1-9]\d*))?$")

STATEMENT_REVIEW = "review"
STATEMENT_OFFICIAL = "official"
STATEMENTS = (STATEMENT_REVIEW, STATEMENT_OFFICIAL)


class RevisionRuleViolation(ValueError):
    """A naming rule was broken (e.g. review data after official data)."""


def parse_name(name: str) -> tuple[bool, int, int | None]:
    m = NAME_RE.match(name or "")
    if not m:
        raise ValueError(f"Not a revision name: {name!r}")
    prefix, major, minor = m.groups()
    return (prefix == "", int(major), int(minor) if minor else None)


def format_name(is_official: bool, major: int, minor: int | None = None) -> str:
    base = f"{'' if is_official else 'E'}{major}"
    return base if minor is None else f"{base}.{minor}"


def _majors(names: list[str]) -> list[tuple[bool, int]]:
    out = []
    for n in names:
        is_official, major, minor = parse_name(n)
        if minor is None:
            out.append((is_official, major))
    return out


def next_major_name(existing_major_names: list[str], statement: str) -> str:
    if statement not in STATEMENTS:
        raise ValueError(f"statement must be one of {STATEMENTS}, got {statement!r}")
    want_official = statement == STATEMENT_OFFICIAL
    majors = _majors(existing_major_names)
    if not want_official and any(is_official for is_official, _ in majors):
        raise RevisionRuleViolation(
            "This part already has official customer data; the customer cannot "
            "un-release it, so new data must be official too.")
    highest = max((n for is_off, n in majors if is_off == want_official), default=0)
    return format_name(want_official, highest + 1)


def next_minor_name(parent_name: str, existing_child_names: list[str]) -> str:
    is_official, major, minor = parse_name(parent_name)
    if minor is not None:
        raise ValueError(f"{parent_name} is a proposal; proposals hang off majors only")
    highest = 0
    for child in existing_child_names:
        c_off, c_major, c_minor = parse_name(child)
        if c_off == is_official and c_major == major and c_minor is not None:
            highest = max(highest, c_minor)
    return format_name(is_official, major, highest + 1)


def legacy_rename(
    rows: list[tuple[int, str, str, int | None, datetime]],
) -> dict[int, tuple[str, str]]:
    """Map one part's legacy revisions to the new scheme.

    RFQ and ENG majors become E1..Ek in creation order; their proposals keep
    the parent's new major. IND majors become 1..k; ECR<n>.<m> proposals hang
    off the official major <n> if it exists, otherwise off official major 1
    (created implicitly as a name only — no row is added; such orphans get
    consecutive minors). Rows that already carry new-style names pass
    through unchanged.
    """
    ordered = sorted(rows, key=lambda r: (r[4], r[0]))
    result: dict[int, tuple[str, str]] = {}
    review_count = 0
    official_count = 0
    legacy_major_to_new: dict[str, str] = {}        # "RFQ1" -> "E1", "IND2" -> "2"
    minors_under: dict[str, int] = {}               # new major name -> minor count

    for rid, name, phase, parent_id, _ in ordered:
        if NAME_RE.match(name):
            is_official, major, minor = parse_name(name)
            new_phase = "official" if is_official else "review"
            result[rid] = (name, new_phase)
            if minor is None:
                if is_official:
                    official_count = max(official_count, major)
                else:
                    review_count = max(review_count, major)
            else:
                minors_under[format_name(is_official, major)] = max(
                    minors_under.get(format_name(is_official, major), 0), minor)
            continue
        m = LEGACY_RE.match(name)
        if not m:
            raise ValueError(f"Cannot migrate revision name {name!r} (id {rid})")
        prefix, major_s, minor_s = m.groups()
        legacy_major = f"{prefix}{major_s}"
        if minor_s is None:
            if prefix in ("RFQ", "ENG"):
                review_count += 1
                new = format_name(False, review_count)
                new_phase = "review"
            else:  # IND (ECR majors do not exist, but treat like IND)
                official_count += 1
                new = format_name(True, official_count)
                new_phase = "official"
            legacy_major_to_new[legacy_major] = new
            result[rid] = (new, new_phase)
        else:
            if prefix == "ECR":
                target = legacy_major_to_new.get(f"IND{major_s}")
                if target is None:
                    if official_count == 0:
                        official_count = 1
                    target = format_name(True, min(int(major_s), official_count))
                new_phase = "official"
            else:
                target = legacy_major_to_new.get(legacy_major)
                if target is None:
                    raise ValueError(f"Proposal {name} (id {rid}) has no migrated parent")
                new_phase = "official" if prefix == "IND" else "review"
            minors_under[target] = minors_under.get(target, 0) + 1
            is_off, mj, _ = parse_name(target)
            result[rid] = (format_name(is_off, mj, minors_under[target]), new_phase)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_revision_naming.py -q`
Expected: all PASS. If `test_legacy_rename_orphan_ecr_without_freeze_hangs_off_first_official` fails on `ECR2.1 → 1.2`, check the `min(int(major_s), official_count)` line: with no IND rows `official_count` is 1 so ECR2 collapses to major 1.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/revision_naming.py backend/tests/test_revision_naming.py
git commit -m "feat(revisions): pure naming rules for E<n>/<n> customer data index

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Model columns and migration 072

**Files:**
- Modify: `backend/app/models/part.py:9-15` (RevisionPhase), `:36-80` (Part), `:117-170` (PartRevision)
- Create: `backend/alembic/versions/072_customer_data_index.py`
- Test: `backend/tests/test_migration_072.py`

**Interfaces:**
- Consumes: `legacy_rename` from Task 1.
- Produces (ORM):
  - `RevisionPhase.REVIEW = "review"`, `RevisionPhase.OFFICIAL = "official"` (the four old members are removed).
  - `PartRevision.customer_index: str | None`, `.customer_statement: str | None`, `.customer_received_at: date | None`, `.source: str` (default `"internal"`), `.part_phase_at_receipt: str` (default `"rfq"`).
  - `Part.lifecycle_phase: str` (default `"rfq"`), `.nominated_at: date | None`, `.sop_at: date | None`.
  - `LIFECYCLE_PHASES = ("rfq", "nominated", "series")` in `app/models/part.py`.
  - Migration exposes `rename_legacy_revisions(conn)` so the test can call it on a SQLite connection.

- [ ] **Step 1: Write the failing migration test**

```python
# backend/tests/test_migration_072.py
"""072 renames RFQ/ENG/IND/ECR rows to E<n>/<n> per part, in creation order."""
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.part import Part, PartRevision

MIG = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "072_customer_data_index.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig072", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_rename_legacy_revisions(session_factory, seed):
    mod = _load_migration()
    async with session_factory() as s:
        part = Part(project_id=seed["project_id"], part_number="P-L", name="Legacy",
                    part_type="purchased", created_by=seed["admin_id"])
        s.add(part)
        await s.flush()
        rows = [
            ("RFQ1", "rfq_phase", None, 1), ("ENG1", "engineering", None, 2),
            ("IND1", "freeze", None, 3), ("ECR1.1", "ecn", None, 4),
        ]
        ids = {}
        for name, phase, parent, day in rows:
            r = PartRevision(part_id=part.id, revision_name=name, phase=phase,
                             status="approved", created_by=seed["admin_id"],
                             created_at=datetime(2026, 1, day))
            s.add(r)
            await s.flush()
            ids[name] = r.id
        await s.commit()

    async with session_factory() as s:
        conn = await s.connection()
        await conn.run_sync(mod.rename_legacy_revisions)
        await s.commit()

    async with session_factory() as s:
        got = {r.id: (r.revision_name, r.phase) for r in
               (await s.execute(select(PartRevision))).scalars().all()}
    assert got[ids["RFQ1"]] == ("E1", "review")
    assert got[ids["ENG1"]] == ("E2", "review")
    assert got[ids["IND1"]] == ("1", "official")
    assert got[ids["ECR1.1"]] == ("1.1", "official")
```

Note: the ORM `phase` column is `Enum(..., native_enum=False)`, i.e. a VARCHAR, so inserting legacy strings works once the enum members are gone only because SQLAlchemy does not validate on the way in for non-native enums with `values_callable`. If the insert raises `LookupError`, set `validate_strings=False` on the `Enum` in the model (Step 3).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_migration_072.py -q`
Expected: FAIL with `FileNotFoundError` or `AttributeError: rename_legacy_revisions`.

- [ ] **Step 3: Update the model**

In `backend/app/models/part.py` replace the `RevisionPhase` enum:

```python
class RevisionPhase(str, enum.Enum):
    """Whether the customer stated this data is review or official."""
    REVIEW = "review"        # E1, E1.1 — customer review data, nothing binding
    OFFICIAL = "official"    # 1, 1.1  — customer-released, binding


LIFECYCLE_PHASES = ("rfq", "nominated", "series")
CUSTOMER_STATEMENTS = ("review", "official")
REVISION_SOURCES = ("customer", "internal")
```

Add `from datetime import date` to the imports (keep `datetime`), and `Date` to the sqlalchemy import.

In `Part`, after `active_revision_id`:

```python
    # Where the part is in its life: rfq → nominated → series. A milestone,
    # not a counter; revision numbering never resets on nomination.
    lifecycle_phase: Mapped[str] = mapped_column(String(20), default="rfq", server_default="rfq", index=True)
    nominated_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    sop_at: Mapped[date | None] = mapped_column(Date, nullable=True)
```

In `PartRevision`, change the two lines after `# Revision Identity`:

```python
    # Revision Identity: E<n>[.<m>] for review data, <n>[.<m>] for official data.
    # Major = customer-stated data state, minor = our internal iteration.
    revision_name: Mapped[str] = mapped_column(String(20), index=True)

    # review | official — mirrors the customer's statement of the major
    phase: Mapped[str] = mapped_column(Enum(RevisionPhase, values_callable=lambda x: [e.value for e in x], native_enum=False, validate_strings=False), index=True)
```

and add after `status`:

```python
    # What the customer said about this data. Set on majors (source=customer),
    # null on our internal proposals.
    customer_index: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_statement: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_received_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="internal", server_default="internal")
    # Part lifecycle phase when this revision was created, so a list can show
    # "E2 (rfq)" next to "E3 (nominated)".
    part_phase_at_receipt: Mapped[str] = mapped_column(String(20), default="rfq", server_default="rfq")
```

Update `backend/app/models/__init__.py` exports if `RevisionPhase` members are referenced there (they are not; only the class is exported — no change needed).

- [ ] **Step 4: Write the migration**

```python
# backend/alembic/versions/072_customer_data_index.py
"""072: customer data index — E<n>/<n> names, part lifecycle phase.

Adds the customer-statement columns on part_revisions, the lifecycle phase on
parts, then renames every legacy RFQ/ENG/IND/ECR revision per part in
creation order (see app.services.revision_naming.legacy_rename). Ids and
foreign keys are untouched. Forward-only.

Revision ID: 072
Revises: 071
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app.services.revision_naming import legacy_rename

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None


def rename_legacy_revisions(conn) -> None:
    rows = conn.execute(sa.text(
        "SELECT id, part_id, revision_name, phase, parent_revision_id, created_at "
        "FROM part_revisions ORDER BY part_id, created_at, id")).fetchall()
    by_part: dict[int, list] = {}
    for rid, part_id, name, phase, parent_id, created_at in rows:
        by_part.setdefault(part_id, []).append((rid, name, phase, parent_id, created_at))
    for part_rows in by_part.values():
        for rid, (new_name, new_phase) in legacy_rename(part_rows).items():
            conn.execute(sa.text(
                "UPDATE part_revisions SET revision_name = :n, phase = :p, "
                "source = CASE WHEN parent_revision_id IS NULL THEN 'customer' ELSE 'internal' END "
                "WHERE id = :id"), {"n": new_name, "p": new_phase, "id": rid})


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = insp.get_table_names()
    if "part_revisions" in tables:
        cols = {c["name"] for c in insp.get_columns("part_revisions")}
        for name, col in [
            ("customer_index", sa.Column("customer_index", sa.String(20), nullable=True)),
            ("customer_statement", sa.Column("customer_statement", sa.String(20), nullable=True)),
            ("customer_received_at", sa.Column("customer_received_at", sa.Date(), nullable=True)),
            ("source", sa.Column("source", sa.String(20), nullable=False, server_default="internal")),
            ("part_phase_at_receipt", sa.Column("part_phase_at_receipt", sa.String(20), nullable=False, server_default="rfq")),
        ]:
            if name not in cols:
                op.add_column("part_revisions", col)
    if "parts" in tables:
        cols = {c["name"] for c in insp.get_columns("parts")}
        if "lifecycle_phase" not in cols:
            op.add_column("parts", sa.Column("lifecycle_phase", sa.String(20), nullable=False, server_default="rfq"))
        if "nominated_at" not in cols:
            op.add_column("parts", sa.Column("nominated_at", sa.Date(), nullable=True))
        if "sop_at" not in cols:
            op.add_column("parts", sa.Column("sop_at", sa.Date(), nullable=True))
    if "part_revisions" in tables:
        rename_legacy_revisions(bind)


def downgrade() -> None:
    pass  # forward-only
```

- [ ] **Step 5: Run the migration test and the whole suite**

Run: `cd backend && python -m pytest tests/test_migration_072.py tests/test_revision_naming.py -q`
Expected: PASS.

Run: `cd backend && python -m pytest tests/ -q -x`
Expected: failures only in tests that use the old `RevisionPhase` members (`RFQ_PHASE` etc. inside `part_service.py` will raise `AttributeError` at import). That is expected here; Task 3 fixes the service. Do not commit a red suite: squash Task 2 and Task 3 into one commit if the suite is red at this point. If it is green (e.g. because import is lazy), commit now:

```bash
git add backend/app/models/part.py backend/alembic/versions/072_customer_data_index.py backend/tests/test_migration_072.py
git commit -m "feat(revisions): customer data columns, part lifecycle phase, migration 072

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: RevisionService rewrite

**Files:**
- Modify: `backend/app/services/part_service.py:180-1416` (class `RevisionService`)
- Modify: `backend/app/services/change_service.py:869-897` (`spawn_ecn_revisions`)
- Test: `backend/tests/test_customer_data_service.py` (new, service-level)

**Interfaces:**
- Consumes: Task 1 functions, Task 2 columns.
- Produces (all `@staticmethod async` on `RevisionService`):
  - `receive_customer_data(session, part_id: int, statement: str, received_at: date, customer_index: str | None = None, summary: str | None = None, created_by: int | None = None) -> PartRevision` — creates the next major, `source="customer"`, `status="approved"`, `part_phase_at_receipt=part.lifecycle_phase`, sets `part.active_revision_id`. Raises `RevisionRuleViolation` for review-after-official, `ValueError` for bad statement / missing part.
  - `create_proposal(session, part_id: int, parent_revision_id: int, summary: str | None = None, created_by: int | None = None) -> PartRevision` — next minor under a major, `status="draft"`, `source="internal"`, same `phase` as parent. `ValueError` if parent is not a major of that part.
  - `promote_revision(session, revision_id: int, statement: str, received_at: date, customer_index: str | None = None, created_by: int | None = None) -> PartRevision` — new major via `receive_customer_data` semantics, copies `summary` with "(promoted from X)", marks the proposal `approved`, rejects sibling proposals, changelog `promoted`.
  - `reject_revision`, `unreject_revision`, `get_revision`, `get_part_revisions` unchanged.
  - `set_lifecycle_phase(session, part_id: int, phase: str, effective: date, created_by: int | None) -> Part` — `rfq→nominated` sets `nominated_at`, `nominated→series` sets `sop_at`; any other transition raises `ValueError`. Changelog action `lifecycle_phase`.
  - Deleted: `get_latest_revision_in_phase`, `get_next_major_version_name`, `has_draft_proposals`, `create_rfq_revision`, `create_rfq_proposal`, `transition_rfq_to_engineering`, `create_engineering_proposal_simple`, `advance_engineering_proposal`, `create_engineering_major_version`, `transition_engineering_to_freeze`, `create_freeze_major_version`, `create_freeze_proposal_simple`, `advance_freeze_proposal`, `create_engineering_proposal`, `approve_engineering_proposal`, `reject_engineering_proposal`, `create_design_freeze`, `create_ecr_proposal`, `approve_ecr_proposal`, `reject_ecr_proposal`.
  - `ChangeService.spawn_ecn_revisions` creates `next_minor_name(parent.revision_name, siblings)` under `part.active_revision` (or the newest major if no active), `phase=parent.phase`, `source="internal"`; raises `ValueError("Part {id} has no revision to change")` when the part has no major.

- [ ] **Step 1: Write the failing service tests**

```python
# backend/tests/test_customer_data_service.py
"""RevisionService: majors only from customer statements, minors are ours."""
from datetime import date

import pytest
from sqlalchemy import select

from app.models.part import Part, PartRevision
from app.services.part_service import PartService, RevisionService
from app.services.revision_naming import RevisionRuleViolation


async def _part(session_factory, seed, number="P-S"):
    async with session_factory() as s:
        p = await PartService.create_part(s, project_id=seed["project_id"], part_number=number,
                                          name="Svc", part_type="purchased", created_by=seed["admin_id"])
        await s.commit()
        return p.id


@pytest.mark.asyncio
async def test_receive_review_then_official_then_minor(session_factory, seed):
    pid = await _part(session_factory, seed)
    async with session_factory() as s:
        e1 = await RevisionService.receive_customer_data(
            s, pid, "review", date(2026, 9, 1), customer_index="A", created_by=seed["admin_id"])
        assert (e1.revision_name, e1.phase, e1.source, e1.status) == ("E1", "review", "customer", "approved")
        assert e1.customer_index == "A" and e1.part_phase_at_receipt == "rfq"
        e2 = await RevisionService.receive_customer_data(s, pid, "review", date(2026, 9, 2), created_by=seed["admin_id"])
        assert e2.revision_name == "E2"
        one = await RevisionService.receive_customer_data(s, pid, "official", date(2026, 9, 3), created_by=seed["admin_id"])
        assert (one.revision_name, one.phase) == ("1", "official")
        part = await s.get(Part, pid)
        assert part.active_revision_id == one.id
        m = await RevisionService.create_proposal(s, pid, one.id, summary="tweak", created_by=seed["admin_id"])
        assert (m.revision_name, m.phase, m.source, m.status) == ("1.1", "official", "internal", "draft")
        with pytest.raises(RevisionRuleViolation):
            await RevisionService.receive_customer_data(s, pid, "review", date(2026, 9, 4), created_by=seed["admin_id"])
        await s.commit()


@pytest.mark.asyncio
async def test_promote_proposal_creates_next_major_with_statement(session_factory, seed):
    pid = await _part(session_factory, seed)
    async with session_factory() as s:
        e1 = await RevisionService.receive_customer_data(s, pid, "review", date(2026, 9, 1), created_by=seed["admin_id"])
        p1 = await RevisionService.create_proposal(s, pid, e1.id, created_by=seed["admin_id"])
        p2 = await RevisionService.create_proposal(s, pid, e1.id, created_by=seed["admin_id"])
        new = await RevisionService.promote_revision(s, p2.id, "official", date(2026, 9, 5), customer_index="B", created_by=seed["admin_id"])
        assert (new.revision_name, new.phase, new.customer_index) == ("1", "official", "B")
        assert "promoted from E1.2" in (new.summary or "")
        await s.refresh(p1); await s.refresh(p2)
        assert p2.status == "approved" and p1.status == "rejected"
        await s.commit()


@pytest.mark.asyncio
async def test_proposal_requires_major_parent_of_same_part(session_factory, seed):
    pid = await _part(session_factory, seed)
    other = await _part(session_factory, seed, number="P-O")
    async with session_factory() as s:
        e1 = await RevisionService.receive_customer_data(s, pid, "review", date(2026, 9, 1), created_by=seed["admin_id"])
        p = await RevisionService.create_proposal(s, pid, e1.id, created_by=seed["admin_id"])
        with pytest.raises(ValueError):
            await RevisionService.create_proposal(s, pid, p.id, created_by=seed["admin_id"])
        with pytest.raises(ValueError):
            await RevisionService.create_proposal(s, other, e1.id, created_by=seed["admin_id"])


@pytest.mark.asyncio
async def test_lifecycle_phase_transitions(session_factory, seed):
    pid = await _part(session_factory, seed)
    async with session_factory() as s:
        with pytest.raises(ValueError):
            await RevisionService.set_lifecycle_phase(s, pid, "series", date(2026, 9, 1), seed["admin_id"])
        part = await RevisionService.set_lifecycle_phase(s, pid, "nominated", date(2026, 9, 1), seed["admin_id"])
        assert part.lifecycle_phase == "nominated" and part.nominated_at == date(2026, 9, 1)
        e1 = await RevisionService.receive_customer_data(s, pid, "review", date(2026, 9, 2), created_by=seed["admin_id"])
        assert e1.part_phase_at_receipt == "nominated"
        part = await RevisionService.set_lifecycle_phase(s, pid, "series", date(2027, 1, 1), seed["admin_id"])
        assert part.sop_at == date(2027, 1, 1)
        await s.commit()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_customer_data_service.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'receive_customer_data'` (or import error from the old enum members).

- [ ] **Step 3: Replace the naming-bound methods in `RevisionService`**

Delete every method listed under "Deleted" in the Interfaces block (lines 184-372 and 521-1393 of the current file, i.e. everything in `RevisionService` except `promote_revision`, `reject_revision`, `unreject_revision`, `get_revision`, `get_part_revisions`). Add these imports at the top of `part_service.py`:

```python
from datetime import date
from app.models.part import LIFECYCLE_PHASES, CUSTOMER_STATEMENTS
from app.services.revision_naming import (
    RevisionRuleViolation, next_major_name, next_minor_name, parse_name,
)
```

Insert at the start of `class RevisionService`:

```python
    @staticmethod
    async def _majors(session: AsyncSession, part_id: int) -> list[PartRevision]:
        result = await session.execute(
            select(PartRevision)
            .where((PartRevision.part_id == part_id) & (PartRevision.parent_revision_id.is_(None)))
            .order_by(PartRevision.created_at))
        return list(result.scalars().all())

    @staticmethod
    async def receive_customer_data(
        session: AsyncSession,
        part_id: int,
        statement: str,
        received_at: date,
        customer_index: Optional[str] = None,
        summary: Optional[str] = None,
        created_by: int = None,
    ) -> PartRevision:
        """Create the next major from a customer statement. This — and
        promote_revision, which delegates here — is the only way a major
        revision comes into existence."""
        if statement not in CUSTOMER_STATEMENTS:
            raise ValueError(f"statement must be one of {CUSTOMER_STATEMENTS}")
        part = await session.get(Part, part_id)
        if part is None:
            raise ValueError("Part not found")
        majors = await RevisionService._majors(session, part_id)
        name = next_major_name([m.revision_name for m in majors], statement)  # may raise RevisionRuleViolation
        revision = PartRevision(
            part_id=part_id,
            revision_name=name,
            phase=statement,
            status=RevisionStatus.APPROVED.value,
            source="customer",
            customer_statement=statement,
            customer_index=customer_index,
            customer_received_at=received_at,
            part_phase_at_receipt=part.lifecycle_phase,
            summary=summary,
            created_by=created_by,
        )
        session.add(revision)
        await session.flush()
        part.active_revision_id = revision.id
        await ChangelogService.log_action(
            session=session, part_id=part_id, revision_id=revision.id, action="created",
            action_description=(f"Customer {statement} data received as {name}"
                                + (f" (customer index {customer_index})" if customer_index else "")),
            performed_by=created_by,
        )
        logger.info(f"Customer {statement} data {name} on part {part_id}")
        return revision

    @staticmethod
    async def create_proposal(
        session: AsyncSession,
        part_id: int,
        parent_revision_id: int,
        summary: Optional[str] = None,
        created_by: int = None,
    ) -> PartRevision:
        """Our internal iteration on a customer major: E1 → E1.1, 1 → 1.1."""
        parent = await session.get(PartRevision, parent_revision_id)
        if parent is None or parent.part_id != part_id:
            raise ValueError("Parent revision not found on this part")
        if parent.parent_revision_id is not None:
            raise ValueError(f"{parent.revision_name} is a proposal; proposals hang off majors only")
        siblings = (await session.execute(
            select(PartRevision.revision_name).where(PartRevision.parent_revision_id == parent.id))).scalars().all()
        name = next_minor_name(parent.revision_name, list(siblings))
        proposal = PartRevision(
            part_id=part_id, revision_name=name, phase=parent.phase,
            status=RevisionStatus.DRAFT.value, parent_revision_id=parent.id,
            source="internal", part_phase_at_receipt=parent.part_phase_at_receipt,
            summary=summary, created_by=created_by,
        )
        session.add(proposal)
        await session.flush()
        await ChangelogService.log_action(
            session=session, part_id=part_id, revision_id=proposal.id, action="created",
            action_description=f"Created {name} as proposal to {parent.revision_name}",
            performed_by=created_by,
        )
        return proposal

    @staticmethod
    async def set_lifecycle_phase(
        session: AsyncSession, part_id: int, phase: str, effective: date, created_by: int = None,
    ) -> Part:
        part = await session.get(Part, part_id)
        if part is None:
            raise ValueError("Part not found")
        allowed = {"rfq": "nominated", "nominated": "series"}
        if allowed.get(part.lifecycle_phase) != phase:
            raise ValueError(f"Cannot move part from {part.lifecycle_phase} to {phase}")
        old = part.lifecycle_phase
        part.lifecycle_phase = phase
        if phase == "nominated":
            part.nominated_at = effective
        else:
            part.sop_at = effective
        await ChangelogService.log_action(
            session=session, part_id=part_id, revision_id=None, action="lifecycle_phase",
            action_description=f"Part moved from {old} to {phase} effective {effective.isoformat()}",
            field_name="lifecycle_phase", old_value=old, new_value=phase, performed_by=created_by,
        )
        await session.flush()
        return part
```

Replace the body of `promote_revision` with:

```python
    @staticmethod
    async def promote_revision(
        session: AsyncSession,
        revision_id: int,
        statement: str,
        received_at: date,
        customer_index: Optional[str] = None,
        created_by: int = None,
    ) -> PartRevision:
        """The customer adopted one of our proposals as their next data state.
        Creates the next major (per statement), marks the proposal approved
        and its siblings rejected."""
        revision = await session.get(PartRevision, revision_id)
        if revision is None:
            raise ValueError("Revision not found")
        summary = f"Promoted from {revision.revision_name}"
        if revision.summary:
            summary = f"{revision.summary} (promoted from {revision.revision_name})"
        new_revision = await RevisionService.receive_customer_data(
            session, revision.part_id, statement, received_at,
            customer_index=customer_index, summary=summary, created_by=created_by)
        revision.status = RevisionStatus.APPROVED.value
        await ChangelogService.log_action(
            session=session, part_id=revision.part_id, revision_id=revision.id, action="promoted",
            action_description=f"Promoted to {new_revision.revision_name}", performed_by=created_by)
        if revision.parent_revision_id:
            siblings = (await session.execute(
                select(PartRevision).where(
                    (PartRevision.parent_revision_id == revision.parent_revision_id)
                    & (PartRevision.id != revision.id)))).scalars().all()
            for sibling in siblings:
                sibling.status = RevisionStatus.REJECTED.value
                await ChangelogService.log_action(
                    session=session, part_id=revision.part_id, revision_id=sibling.id, action="rejected",
                    action_description=f"Rejected due to promotion of {revision.revision_name}",
                    performed_by=created_by)
        return new_revision
```

- [ ] **Step 4: Update `spawn_ecn_revisions` in `change_service.py`**

Replace lines 869-897 (the `for item in change.impacted_items:` body up to and including the `append_changelog` call) with:

```python
    @staticmethod
    async def spawn_ecn_revisions(session: AsyncSession, change: ChangeRequest, user_id: int):
        from app.services.revision_naming import next_minor_name
        for item in change.impacted_items:
            if item.resulting_revision_id is None:
                part = await session.get(Part, item.part_id)
                parent = await session.get(PartRevision, part.active_revision_id) if part.active_revision_id else None
                if parent is None or parent.parent_revision_id is not None:
                    # fall back to the newest major on the part
                    parent = (await session.execute(
                        select(PartRevision)
                        .where((PartRevision.part_id == item.part_id) & (PartRevision.parent_revision_id.is_(None)))
                        .order_by(PartRevision.created_at.desc()).limit(1))).scalar_one_or_none()
                if parent is None:
                    raise ValueError(f"Part {item.part_id} has no revision to change")
                siblings = (await session.execute(
                    select(PartRevision.revision_name).where(PartRevision.parent_revision_id == parent.id))).scalars().all()
                rev = PartRevision(
                    part_id=item.part_id,
                    revision_name=next_minor_name(parent.revision_name, list(siblings)),
                    phase=parent.phase,
                    status="draft",
                    parent_revision_id=parent.id,
                    source="internal",
                    part_phase_at_receipt=part.lifecycle_phase,
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
```

Make sure `Part` and `PartRevision` are imported in `change_service.py` (they already are: `rev = PartRevision(` and `await session.get(Part, ...)` exist in `release`).

- [ ] **Step 5: Run the new tests**

Run: `cd backend && python -m pytest tests/test_customer_data_service.py tests/test_revision_naming.py tests/test_migration_072.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite to see what the API layer broke**

Run: `cd backend && python -m pytest tests/ -q -x 2>&1 | tail -20`
Expected: import errors in `app/api/v1/items/parts.py` (deleted service methods and schemas). Task 4 fixes them; commit Task 3 together with Task 4 if the suite is red.

---

### Task 4: API endpoints and schemas

**Files:**
- Modify: `backend/app/schemas/part.py`
- Modify: `backend/app/api/v1/items/parts.py:168-660`
- Modify: `backend/tests/conftest.py:271-296`
- Modify: `backend/tests/test_wf_seeds.py:99`, `backend/tests/test_cancel_teardown.py:40`, `backend/tests/test_item_categories.py:66`, `backend/tests/test_revision_evidence.py:78`, `backend/tests/test_impact_tree.py:17`, `backend/tests/test_user_departments.py:177`
- Test: `backend/tests/test_customer_data_index.py` (new)

**Interfaces:**
- Consumes: Task 3 service methods.
- Produces (HTTP, all under `/api/v1/parts`):
  - `POST /{part_id}/revisions/customer-data` body `CustomerDataReceivedRequest {statement: "review"|"official", received_at: date, customer_index?: str, summary?: str}` → 201 `PartRevisionResponse`; 409 on `RevisionRuleViolation`; 400 on other `ValueError`.
  - `POST /{part_id}/revisions/proposals` body `CreateProposalRequest {parent_revision_id: int, summary?: str}` → 201.
  - `POST /{part_id}/revisions/{revision_id}/promote` body `PromoteRevisionRequest {statement, received_at, customer_index?}` → 200; 409/400 as above.
  - `POST /{part_id}/lifecycle-phase` body `SetLifecyclePhaseRequest {phase: "nominated"|"series", effective: date}` → 200 `PartResponse`; admin only (403 otherwise).
  - `PartRevisionResponse` gains `customer_index`, `customer_statement`, `customer_received_at`, `source`, `part_phase_at_receipt`.
  - `PartResponse` gains `lifecycle_phase`, `nominated_at`, `sop_at`.
  - Removed: `/revisions/rfq`, `/revisions/rfq-proposal`, `/{rfq}/to-engineering`, `/revisions/engineering-proposal`, `/{id}/advance-engineering`, `/{id}/to-freeze`, `/revisions/freeze-proposal`, `/{id}/advance-freeze`, `/revisions/engineering`, `/revisions/freeze`, `/revisions/{id}/propose-engineering`, `/revisions/{id}/approve`, `/revisions/{id}/reject` (the parent-less one; keep `/{part_id}/revisions/{revision_id}/reject`), `/revisions/{id}/freeze`, `/revisions/{id}/propose-ecr`, `/revisions/{id}/approve-ecr`, `/revisions/{id}/reject-ecr`.

- [ ] **Step 1: Write the failing API tests**

```python
# backend/tests/test_customer_data_index.py
"""HTTP flow: customer data → E1/E2 → official 1 → proposal 1.1 → promote."""
import pytest


async def _mk_part(client, auth, seed, number="P-CD"):
    res = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": number, "name": "Panel",
        "part_type": "internal_mfg", "data_classification": "confidential"}, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def test_customer_data_flow(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed)
    r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=eng_auth,
                          json={"statement": "review", "received_at": "2026-09-01", "customer_index": "A"})
    assert r.status_code == 201, r.text
    e1 = r.json()
    assert e1["revision_name"] == "E1" and e1["phase"] == "review" and e1["source"] == "customer"
    assert e1["customer_index"] == "A" and e1["part_phase_at_receipt"] == "rfq"

    r = await client.post(f"/api/v1/parts/{pid}/revisions/proposals", headers=eng_auth,
                          json={"parent_revision_id": e1["id"], "summary": "our tweak"})
    assert r.status_code == 201 and r.json()["revision_name"] == "E1.1"

    r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=eng_auth,
                          json={"statement": "official", "received_at": "2026-09-10", "customer_index": "B"})
    assert r.status_code == 201 and r.json()["revision_name"] == "1"

    r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=eng_auth,
                          json={"statement": "review", "received_at": "2026-09-11"})
    assert r.status_code == 409

    part = (await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)).json()
    assert [x["revision_name"] for x in part["revisions"]] == ["E1", "E1.1", "1"]
    assert part["active_revision_id"] == [x for x in part["revisions"] if x["revision_name"] == "1"][0]["id"]


async def test_promote_needs_statement(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed)
    e1 = (await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=eng_auth,
                            json={"statement": "review", "received_at": "2026-09-01"})).json()
    p = (await client.post(f"/api/v1/parts/{pid}/revisions/proposals", headers=eng_auth,
                           json={"parent_revision_id": e1["id"]})).json()
    r = await client.post(f"/api/v1/parts/{pid}/revisions/{p['id']}/promote", headers=eng_auth, json={})
    assert r.status_code == 422
    r = await client.post(f"/api/v1/parts/{pid}/revisions/{p['id']}/promote", headers=eng_auth,
                          json={"statement": "review", "received_at": "2026-09-05"})
    assert r.status_code == 200 and r.json()["revision_name"] == "E2"


async def test_lifecycle_phase_admin_only(client, eng_auth, admin_auth, seed):
    pid = await _mk_part(client, eng_auth, seed)
    r = await client.post(f"/api/v1/parts/{pid}/lifecycle-phase", headers=eng_auth,
                          json={"phase": "nominated", "effective": "2026-09-01"})
    assert r.status_code == 403
    r = await client.post(f"/api/v1/parts/{pid}/lifecycle-phase", headers=admin_auth,
                          json={"phase": "nominated", "effective": "2026-09-01"})
    assert r.status_code == 200, r.text
    assert r.json()["lifecycle_phase"] == "nominated" and r.json()["nominated_at"] == "2026-09-01"
    r = await client.post(f"/api/v1/parts/{pid}/lifecycle-phase", headers=admin_auth,
                          json={"phase": "nominated", "effective": "2026-09-02"})
    assert r.status_code == 400


async def test_legacy_endpoints_are_gone(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed)
    for path in ("revisions/rfq", "revisions/engineering", "revisions/freeze"):
        r = await client.post(f"/api/v1/parts/{pid}/{path}", headers=eng_auth, json={"summary": "x"})
        assert r.status_code in (404, 405), path
```

Check `admin_auth` and `eng_auth` fixture names exist in `conftest.py` (`grep -n "def admin_auth\|def eng_auth" backend/tests/conftest.py`). Note the `eng_auth` fixture mints an admin role cookie in SSO mode (`_mint_cookie(..., admin=True)`); check what `login(..., admin=False)` yields and use whichever fixture gives a non-admin `current_user.role`. If every fixture yields admin, build a non-admin header inline in the test with `login(client, "eng@test.io", admin=False)` and assert the 403 with that.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_customer_data_index.py -q`
Expected: FAIL (404 on `customer-data`, or import error).

- [ ] **Step 3: Schemas**

In `backend/app/schemas/part.py`:

Add `from datetime import date` to imports. In `PartResponse` add:

```python
    lifecycle_phase: str = "rfq"
    nominated_at: Optional[date] = None
    sop_at: Optional[date] = None
```

Change `PartRevisionBase` descriptions and add fields:

```python
class PartRevisionBase(BaseModel):
    """Base revision information."""
    revision_name: str = Field(..., description="E1, E1.1 (review) or 1, 1.1 (official)")
    phase: str = Field(..., description="review, official")
    status: str = Field(default="draft", description="draft, in_progress, in_review, approved, rejected, archived, frozen, cancelled")
    summary: Optional[str] = None
    change_reason: Optional[str] = None
    impact_analysis: Optional[str] = None
```

In `PartRevisionResponse` add after `supersedes_revision_id`:

```python
    customer_index: Optional[str] = None
    customer_statement: Optional[str] = None
    customer_received_at: Optional[date] = None
    source: str = "internal"
    part_phase_at_receipt: str = "rfq"
```

Delete `CreateRFQRequest`, `CreateRFQProposalRequest`, `TransitionToEngineeringRequest`, `CreateEngineeringProposalRequest`, `ApproveProposalRequest`, `RejectProposalRequest`, `CreateDesignFreezeRequest`, `CreateECRRequest`. Replace `PromoteRevisionRequest` and add the new ones:

```python
class CustomerDataReceivedRequest(BaseModel):
    """The customer sent data and stated whether it is review or official."""
    statement: Literal["review", "official"]
    received_at: date
    customer_index: Optional[str] = Field(None, max_length=20, description="Customer's own index, e.g. B")
    summary: Optional[str] = None


class CreateProposalRequest(BaseModel):
    """Our internal iteration under a customer major (E1 → E1.1, 1 → 1.1)."""
    parent_revision_id: int
    summary: Optional[str] = None


class PromoteRevisionRequest(BaseModel):
    """The customer adopted this proposal as their next data state."""
    statement: Literal["review", "official"]
    received_at: date
    customer_index: Optional[str] = Field(None, max_length=20)


class SetLifecyclePhaseRequest(BaseModel):
    phase: Literal["nominated", "series"]
    effective: date
```

Add `from typing import Optional, List, Literal`.

- [ ] **Step 4: Endpoints**

In `backend/app/api/v1/items/parts.py` delete every endpoint from `# RFQ Phase Endpoints` (line 168) through the end of `reject_ecr_proposal` (line ~660), except keep `reject_revision` (`/{part_id}/revisions/{revision_id}/reject`) and `unreject_revision`. Fix the import line from `app.schemas.part` to import `CustomerDataReceivedRequest, CreateProposalRequest, PromoteRevisionRequest, RejectMajorRevisionRequest, SetLifecyclePhaseRequest` and drop the deleted names. Add `from app.services.revision_naming import RevisionRuleViolation` and `from datetime import date`. Insert:

```python
# Customer data (the only way a major revision is created)
@router.post("/{part_id}/revisions/customer-data", response_model=PartRevisionResponse,
             status_code=status.HTTP_201_CREATED)
async def receive_customer_data(
    part_id: int,
    body: CustomerDataReceivedRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record customer data as the next major: E<n> for review, <n> for official."""
    try:
        revision = await RevisionService.receive_customer_data(
            db, part_id, body.statement, body.received_at,
            customer_index=body.customer_index, summary=body.summary, created_by=current_user.id)
        await db.commit()
        return revision
    except RevisionRuleViolation as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{part_id}/revisions/proposals", response_model=PartRevisionResponse,
             status_code=status.HTTP_201_CREATED)
async def create_proposal(
    part_id: int,
    body: CreateProposalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Our internal iteration under a customer major (E1 → E1.1, 1 → 1.1)."""
    try:
        proposal = await RevisionService.create_proposal(
            db, part_id, body.parent_revision_id, summary=body.summary, created_by=current_user.id)
        await db.commit()
        return proposal
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{part_id}/revisions/{revision_id}/promote", response_model=PartRevisionResponse)
async def promote_revision(
    part_id: int,
    revision_id: int,
    body: PromoteRevisionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The customer adopted this proposal as their next data state."""
    try:
        new_revision = await RevisionService.promote_revision(
            db, revision_id, body.statement, body.received_at,
            customer_index=body.customer_index, created_by=current_user.id)
        await db.commit()
        return new_revision
    except RevisionRuleViolation as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{part_id}/lifecycle-phase", response_model=PartResponse)
async def set_lifecycle_phase(
    part_id: int,
    body: SetLifecyclePhaseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """rfq → nominated (sets nominated_at) → series (sets sop_at). Admin only."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    try:
        part = await RevisionService.set_lifecycle_phase(
            db, part_id, body.phase, body.effective, created_by=current_user.id)
        await db.commit()
        return part
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
```

Keep the existing `reject_revision` and `unreject_revision` endpoints as they are.

- [ ] **Step 5: Update the `part` fixture and legacy literals in tests**

`backend/tests/conftest.py` `part` fixture: replace the `/revisions/rfq` call with

```python
    res = await client.post(
        f"/api/v1/parts/{part_id}/revisions/customer-data",
        json={"statement": "review", "received_at": "2026-09-01", "summary": "initial"},
        headers=eng_auth,
    )
    assert res.status_code == 201, res.text
```

and update the docstring to "A part with one customer review revision E1".

Then in each listed test file replace `/revisions/rfq` calls the same way (status 201, body with `statement`/`received_at`), and replace `revision_name="ECR1.1", phase="ecn"` with `revision_name="1.1", phase="official"` in `test_wf_seeds.py:99` and `test_cancel_teardown.py:40`. Grep to be sure nothing is left:

Run: `cd backend && grep -rn "revisions/rfq\|\"ecn\"\|ECR1\|IND1\|ENG1\|RFQ1" tests/ app/ | grep -v revision_naming | grep -v test_migration_072 | grep -v test_revision_naming`
Expected: no output.

- [ ] **Step 6: Run the full suite**

Run: `cd backend && python -m pytest tests/ -q -x`
Expected: PASS. Common breakage and fixes:
- A change-flow test creates a change on a part with no revisions → `spawn_ecn_revisions` raises. Give that test's part an E1 via `customer-data` (the `part` fixture already does).
- `test_revision_files` asserts `revision_id` from the fixture is uploadable: `approved` is not in `LOCKED_STATUSES`, so this passes.
- Frontend-facing `get_part` response includes new fields; nothing in the backend tests asserts exact key sets.

- [ ] **Step 7: Commit (Tasks 2–4 together if they were held)**

```bash
git add -A backend/app backend/alembic backend/tests
git commit -m "feat(revisions): customer data index — E<n> review, <n> official, part lifecycle phase

Majors are created only from a customer statement (review/official);
minors are internal proposals. Replaces RFQ/ENG/IND/ECR naming and
endpoints. Migration 072 renames existing revisions in place.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Frontend — RevisionTimeline and CustomerDataDialog

**Files:**
- Create: `frontend/src/components/parts/RevisionTimeline.tsx`
- Create: `frontend/src/components/parts/RevisionTimeline.test.tsx`
- Create: `frontend/src/components/parts/CustomerDataDialog.tsx`

**Interfaces:**
- Produces:
  - `export interface Revision { id: number; revision_name: string; phase: 'review' | 'official'; status: string; summary?: string | null; parent_revision_id?: number | null; source: 'customer' | 'internal'; customer_index?: string | null; customer_received_at?: string | null; part_phase_at_receipt: string; created_at: string; }`
  - `export function groupByMajor(revisions: Revision[]): { major: Revision; minors: Revision[] }[]` — majors sorted newest first (official before review, then by number desc); minors sorted by minor number asc.
  - `export default function RevisionTimeline(props: { revisions: Revision[]; activeRevisionId?: number | null; onNewProposal(parentId: number): void; onPromote(rev: Revision): void; onReject(id: number): void; onUnreject(id: number): void; })`
  - `export default function CustomerDataDialog(props: { open: boolean; title: string; onClose(): void; onSubmit(v: { statement: 'review' | 'official'; received_at: string; customer_index?: string; summary?: string }): void; pending?: boolean; officialOnly?: boolean; })`

- [ ] **Step 1: Write the failing component tests**

```tsx
// frontend/src/components/parts/RevisionTimeline.test.tsx
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import RevisionTimeline, { groupByMajor, type Revision } from './RevisionTimeline'

const rev = (over: Partial<Revision>): Revision => ({
  id: 1, revision_name: 'E1', phase: 'review', status: 'approved', source: 'customer',
  part_phase_at_receipt: 'rfq', created_at: '2026-09-01T00:00:00', ...over,
})

const set: Revision[] = [
  rev({ id: 1, revision_name: 'E1', part_phase_at_receipt: 'rfq', customer_index: 'A' }),
  rev({ id: 2, revision_name: 'E1.1', parent_revision_id: 1, source: 'internal', status: 'draft' }),
  rev({ id: 3, revision_name: 'E2', part_phase_at_receipt: 'nominated' }),
  rev({ id: 4, revision_name: '1', phase: 'official', part_phase_at_receipt: 'nominated', customer_index: 'B' }),
  rev({ id: 5, revision_name: '1.2', phase: 'official', parent_revision_id: 4, source: 'internal', status: 'draft' }),
  rev({ id: 6, revision_name: '1.1', phase: 'official', parent_revision_id: 4, source: 'internal', status: 'rejected' }),
]

describe('groupByMajor', () => {
  it('puts official first, newest first, minors ascending', () => {
    const g = groupByMajor(set)
    expect(g.map((x) => x.major.revision_name)).toEqual(['1', 'E2', 'E1'])
    expect(g[0].minors.map((m) => m.revision_name)).toEqual(['1.1', '1.2'])
  })
})

describe('RevisionTimeline', () => {
  afterEach(cleanup)
  const noop = { onNewProposal: vi.fn(), onPromote: vi.fn(), onReject: vi.fn(), onUnreject: vi.fn() }

  it('shows phase-at-receipt, customer index and official badge', () => {
    render(<RevisionTimeline revisions={set} activeRevisionId={4} {...noop} />)
    const one = screen.getByTestId('major-1')
    expect(one.textContent).toContain('official')
    expect(one.textContent).toContain('nominated')
    expect(one.textContent).toContain('index B')
    expect(one.textContent).toContain('active')
    expect(screen.getByTestId('major-E1').textContent).toContain('rfq')
  })

  it('offers promote only on draft minors and new-proposal on majors', () => {
    render(<RevisionTimeline revisions={set} {...noop} />)
    fireEvent.click(screen.getByTestId('promote-5'))
    expect(noop.onPromote).toHaveBeenCalledWith(expect.objectContaining({ id: 5 }))
    expect(screen.queryByTestId('promote-6')).toBeNull()
    fireEvent.click(screen.getByTestId('new-proposal-4'))
    expect(noop.onNewProposal).toHaveBeenCalledWith(4)
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/parts/RevisionTimeline.test.tsx`
Expected: FAIL, module not found.

- [ ] **Step 3: Write `RevisionTimeline.tsx`**

```tsx
// frontend/src/components/parts/RevisionTimeline.tsx
/**
 * Revision timeline: one card per customer major (E1, E2, 1, 2 …) with our
 * internal proposals (E1.1, 1.1 …) nested underneath.
 */
export interface Revision {
  id: number;
  revision_name: string;
  phase: 'review' | 'official';
  status: string;
  summary?: string | null;
  parent_revision_id?: number | null;
  source: 'customer' | 'internal';
  customer_index?: string | null;
  customer_received_at?: string | null;
  part_phase_at_receipt: string;
  created_at: string;
}

function parse(name: string): { official: boolean; major: number; minor: number | null } {
  const m = /^(E?)(\d+)(?:\.(\d+))?$/.exec(name);
  if (!m) return { official: false, major: 0, minor: null };
  return { official: m[1] === '', major: Number(m[2]), minor: m[3] ? Number(m[3]) : null };
}

export function groupByMajor(revisions: Revision[]): { major: Revision; minors: Revision[] }[] {
  const majors = revisions.filter((r) => !r.parent_revision_id);
  return majors
    .map((major) => ({
      major,
      minors: revisions
        .filter((r) => r.parent_revision_id === major.id)
        .sort((a, b) => (parse(a.revision_name).minor ?? 0) - (parse(b.revision_name).minor ?? 0)),
    }))
    .sort((a, b) => {
      const pa = parse(a.major.revision_name);
      const pb = parse(b.major.revision_name);
      if (pa.official !== pb.official) return pa.official ? -1 : 1;
      return pb.major - pa.major;
    });
}

const statusColor: Record<string, string> = {
  draft: 'bg-slate-700 text-slate-200',
  approved: 'bg-emerald-900/40 text-emerald-300',
  rejected: 'bg-red-900/40 text-red-300',
  archived: 'bg-slate-800 text-slate-400',
  frozen: 'bg-sky-900/40 text-sky-300',
};

function Badge({ children, tone = 'bg-slate-700 text-slate-200', testId }: { children: React.ReactNode; tone?: string; testId?: string }) {
  return <span data-testid={testId} className={`text-xs px-2 py-0.5 rounded-full ${tone}`}>{children}</span>;
}

interface Props {
  revisions: Revision[];
  activeRevisionId?: number | null;
  onNewProposal(parentId: number): void;
  onPromote(rev: Revision): void;
  onReject(id: number): void;
  onUnreject(id: number): void;
}

export default function RevisionTimeline({ revisions, activeRevisionId, onNewProposal, onPromote, onReject, onUnreject }: Props) {
  const groups = groupByMajor(revisions);
  if (groups.length === 0) {
    return <p className="text-slate-400 text-center py-8">No customer data yet.</p>;
  }
  return (
    <div className="space-y-4">
      {groups.map(({ major, minors }) => (
        <div key={major.id} data-testid={`major-${major.revision_name}`}
          className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-lg font-bold text-slate-100">{major.revision_name}</span>
                <Badge tone={major.phase === 'official' ? 'bg-amber-900/40 text-amber-300' : 'bg-blue-900/40 text-blue-300'}>
                  {major.phase}
                </Badge>
                <Badge>{major.part_phase_at_receipt}</Badge>
                {major.customer_index && <Badge>index {major.customer_index}</Badge>}
                {activeRevisionId === major.id && <Badge tone="bg-emerald-900/40 text-emerald-300">active</Badge>}
                <Badge tone={statusColor[major.status] ?? ''}>{major.status}</Badge>
              </div>
              {major.summary && <p className="text-sm text-slate-300">{major.summary}</p>}
              <p className="text-xs text-slate-500">
                {major.customer_received_at ? `Received ${major.customer_received_at}` : `Created ${new Date(major.created_at).toLocaleDateString()}`}
              </p>
            </div>
            <button data-testid={`new-proposal-${major.id}`} onClick={() => onNewProposal(major.id)}
              className="px-3 py-1 text-sm rounded bg-slate-700 text-slate-100 hover:bg-slate-600">
              + Proposal
            </button>
          </div>

          {minors.length > 0 && (
            <div className="mt-3 space-y-2 border-l-2 border-slate-700 pl-4">
              {minors.map((m) => (
                <div key={m.id} data-testid={`minor-${m.revision_name}`} className="flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-slate-100">{m.revision_name}</span>
                      <Badge tone={statusColor[m.status] ?? ''}>{m.status}</Badge>
                    </div>
                    {m.summary && <p className="text-sm text-slate-300">{m.summary}</p>}
                  </div>
                  <div className="flex gap-2">
                    {m.status === 'draft' && (
                      <button data-testid={`promote-${m.id}`} onClick={() => onPromote(m)}
                        className="px-3 py-1 text-sm rounded bg-purple-900/40 text-purple-200 hover:bg-purple-900/60">
                        Customer adopted
                      </button>
                    )}
                    {m.status !== 'rejected' && m.status !== 'archived' && m.status !== 'approved' && (
                      <button onClick={() => onReject(m.id)}
                        className="px-3 py-1 text-sm rounded bg-red-900/40 text-red-200 hover:bg-red-900/60">Reject</button>
                    )}
                    {(m.status === 'rejected' || m.status === 'archived') && (
                      <button onClick={() => onUnreject(m.id)}
                        className="px-3 py-1 text-sm rounded bg-yellow-900/40 text-yellow-200 hover:bg-yellow-900/60">Restore</button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Write `CustomerDataDialog.tsx`**

```tsx
// frontend/src/components/parts/CustomerDataDialog.tsx
import { useState } from 'react';

export interface CustomerDataInput {
  statement: 'review' | 'official';
  received_at: string;
  customer_index?: string;
  summary?: string;
}

interface Props {
  open: boolean;
  title: string;
  onClose(): void;
  onSubmit(v: CustomerDataInput): void;
  pending?: boolean;
  /** Once a part has official data the customer cannot go back to review. */
  officialOnly?: boolean;
}

export default function CustomerDataDialog({ open, title, onClose, onSubmit, pending, officialOnly }: Props) {
  const [statement, setStatement] = useState<'review' | 'official'>(officialOnly ? 'official' : 'review');
  const [receivedAt, setReceivedAt] = useState(() => new Date().toISOString().slice(0, 10));
  const [index, setIndex] = useState('');
  const [summary, setSummary] = useState('');
  if (!open) return null;
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-lg shadow-lg max-w-md w-full mx-4 p-6 space-y-4">
        <h3 className="text-lg font-bold text-slate-100">{title}</h3>
        <fieldset className="space-y-2">
          <legend className="text-sm text-slate-400">What did the customer state?</legend>
          {(['review', 'official'] as const).map((s) => (
            <label key={s} className={`flex items-center gap-2 text-slate-100 ${officialOnly && s === 'review' ? 'opacity-40' : ''}`}>
              <input type="radio" name="statement" value={s} checked={statement === s}
                disabled={officialOnly && s === 'review'} onChange={() => setStatement(s)} />
              <span className="capitalize">{s}</span>
              <span className="text-xs text-slate-400">{s === 'review' ? '→ E-index, nothing binding' : '→ numeric index, released'}</span>
            </label>
          ))}
        </fieldset>
        <label className="block text-sm text-slate-400">Received on
          <input type="date" value={receivedAt} onChange={(e) => setReceivedAt(e.target.value)}
            className="mt-1 w-full p-2 rounded bg-slate-900 border border-slate-700 text-slate-100" />
        </label>
        <label className="block text-sm text-slate-400">Customer index (optional)
          <input value={index} onChange={(e) => setIndex(e.target.value)} placeholder="e.g. B"
            className="mt-1 w-full p-2 rounded bg-slate-900 border border-slate-700 text-slate-100" />
        </label>
        <label className="block text-sm text-slate-400">Summary (optional)
          <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={2}
            className="mt-1 w-full p-2 rounded bg-slate-900 border border-slate-700 text-slate-100" />
        </label>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 rounded bg-slate-700 text-slate-100 hover:bg-slate-600">Cancel</button>
          <button disabled={pending || !receivedAt}
            onClick={() => onSubmit({ statement, received_at: receivedAt, customer_index: index.trim() || undefined, summary: summary.trim() || undefined })}
            className="px-4 py-2 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:bg-slate-600">
            {pending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run the component tests**

Run: `cd frontend && npx vitest run src/components/parts/RevisionTimeline.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/parts/
git commit -m "feat(ui): revision timeline and customer data dialog for E<n>/<n> index

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Frontend — wire PartDetail and ProjectDetailPage

**Files:**
- Modify: `frontend/src/pages/PartDetail.tsx` (whole file)
- Modify: `frontend/src/pages/ProjectDetailPage.tsx:58-60, 228-236, 988-1005, 1240-1270, 1380-1390`

**Interfaces:**
- Consumes: Task 4 endpoints, Task 5 components.

- [ ] **Step 1: Rewrite `PartDetail.tsx`**

Replace the file with the version below. It keeps the header, part info card, and `StartChangeModal`, and swaps the revision section for `RevisionTimeline`.

```tsx
/**
 * PartDetail - part header, lifecycle phase, and the revision timeline.
 * Majors come only from customer data (E<n> review, <n> official); minors
 * are our proposals.
 */
import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';
import StartChangeModal from '../components/changes/StartChangeModal';
import StartChangeButton from '../components/changes/StartChangeButton';
import RevisionTimeline, { type Revision } from '../components/parts/RevisionTimeline';
import CustomerDataDialog, { type CustomerDataInput } from '../components/parts/CustomerDataDialog';
import { useAuth } from '../contexts/AuthContext';

interface Part {
  id: number;
  part_number: string;
  customer_part_number?: string | null;
  name: string;
  part_type: string;
  data_classification: string;
  item_category: string;
  project_id: number;
  active_revision_id?: number | null;
  lifecycle_phase: 'rfq' | 'nominated' | 'series';
  nominated_at?: string | null;
  sop_at?: string | null;
  revisions: Revision[];
}

const NEXT_PHASE: Record<Part['lifecycle_phase'], 'nominated' | 'series' | null> = {
  rfq: 'nominated', nominated: 'series', series: null,
};

function errMsg(error: unknown, fallback: string) {
  return (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;
}

export default function PartDetail() {
  const { partId } = useParams<{ partId: string }>();
  const navigate = useNavigate();
  const { isAdmin } = useAuth();
  const [showStartChange, setShowStartChange] = useState(false);
  const [showCustomerData, setShowCustomerData] = useState(false);
  const [promoting, setPromoting] = useState<Revision | null>(null);
  const [proposalParent, setProposalParent] = useState<number | null>(null);
  const [proposalSummary, setProposalSummary] = useState('');

  const { data: part, isLoading, error: partError, refetch } = useQuery({
    queryKey: ['part', partId],
    queryFn: async () => (await client.get(`/v1/parts/${partId}`)).data as Part,
  });

  const customerData = useMutation({
    mutationFn: (v: CustomerDataInput) => client.post(`/v1/parts/${partId}/revisions/customer-data`, v),
    onSuccess: (res) => { toast.success(`Recorded ${res.data.revision_name}`); setShowCustomerData(false); refetch(); },
    onError: (e) => toast.error(errMsg(e, 'Could not record customer data')),
  });
  const promote = useMutation({
    mutationFn: ({ id, v }: { id: number; v: CustomerDataInput }) =>
      client.post(`/v1/parts/${partId}/revisions/${id}/promote`, { statement: v.statement, received_at: v.received_at, customer_index: v.customer_index }),
    onSuccess: (res) => { toast.success(`Now ${res.data.revision_name}`); setPromoting(null); refetch(); },
    onError: (e) => toast.error(errMsg(e, 'Could not promote')),
  });
  const proposal = useMutation({
    mutationFn: (parent_revision_id: number) =>
      client.post(`/v1/parts/${partId}/revisions/proposals`, { parent_revision_id, summary: proposalSummary || undefined }),
    onSuccess: (res) => { toast.success(`Created ${res.data.revision_name}`); setProposalParent(null); setProposalSummary(''); refetch(); },
    onError: (e) => toast.error(errMsg(e, 'Could not create proposal')),
  });
  const reject = useMutation({
    mutationFn: (id: number) => client.post(`/v1/parts/${partId}/revisions/${id}/reject`, {}),
    onSuccess: () => refetch(), onError: (e) => toast.error(errMsg(e, 'Could not reject')),
  });
  const unreject = useMutation({
    mutationFn: (id: number) => client.post(`/v1/parts/${partId}/revisions/${id}/unreject`, {}),
    onSuccess: () => refetch(), onError: (e) => toast.error(errMsg(e, 'Could not restore')),
  });
  const phase = useMutation({
    mutationFn: (next: 'nominated' | 'series') =>
      client.post(`/v1/parts/${partId}/lifecycle-phase`, { phase: next, effective: new Date().toISOString().slice(0, 10) }),
    onSuccess: (res) => { toast.success(`Part is now ${res.data.lifecycle_phase}`); refetch(); },
    onError: (e) => toast.error(errMsg(e, 'Could not change phase')),
  });

  if (isLoading) return <div className="p-8 text-center">Loading...</div>;
  if (partError || !part) {
    return (
      <div className="min-h-screen bg-slate-900 p-8">
        <div className="max-w-4xl mx-auto bg-red-50 border border-red-200 rounded-lg p-6">
          <h2 className="text-lg font-bold text-red-800 mb-2">Part not found</h2>
          <p className="text-red-700">{(partError as Error | null)?.message || 'The requested part could not be loaded.'}</p>
        </div>
      </div>
    );
  }

  const hasOfficial = part.revisions.some((r) => r.phase === 'official' && !r.parent_revision_id);
  const active = part.revisions.find((r) => r.id === part.active_revision_id);
  const nextPhase = NEXT_PHASE[part.lifecycle_phase];

  return (
    <div className="min-h-screen bg-slate-900 p-8">
      <div className="max-w-5xl mx-auto">
        <div className="mb-8">
          <button onClick={() => navigate('/dashboard')}
            className="mb-4 px-3 py-1 bg-slate-700 text-slate-100 rounded hover:bg-slate-600 text-sm">← Back</button>
          <div className="flex justify-between items-start gap-4">
            <div>
              <h1 className="text-4xl font-bold text-slate-100 mb-1">{part.part_number}</h1>
              {part.customer_part_number && <p className="text-slate-400 font-mono text-sm mb-1">{part.customer_part_number}</p>}
              <p className="text-slate-300 mb-2">{part.name}</p>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-semibold text-blue-300 bg-blue-900 px-3 py-1 rounded-md">
                  {active ? `${active.revision_name} (active)` : 'no customer data yet'}
                </span>
                <span data-testid="lifecycle-phase" className="text-sm text-slate-200 bg-slate-700 px-3 py-1 rounded-md capitalize">
                  {part.lifecycle_phase}{part.nominated_at ? ` · nominated ${part.nominated_at}` : ''}{part.sop_at ? ` · SOP ${part.sop_at}` : ''}
                </span>
                {isAdmin && nextPhase && (
                  <button onClick={() => phase.mutate(nextPhase)} disabled={phase.isPending}
                    className="text-sm px-3 py-1 rounded-md bg-slate-700 text-slate-100 hover:bg-slate-600">
                    Mark {nextPhase}
                  </button>
                )}
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={() => setShowCustomerData(true)}
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium">
                + Customer data
              </button>
              <StartChangeButton label="Start change request" onClick={() => setShowStartChange(true)}
                className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-sm font-medium" />
            </div>
          </div>
        </div>

        {showStartChange && (
          <StartChangeModal open onClose={() => setShowStartChange(false)}
            prefill={{ projectId: part.project_id, part: { id: part.id, part_number: part.part_number, name: part.name, item_category: part.item_category } }} />
        )}

        <CustomerDataDialog open={showCustomerData} title="Customer data received" officialOnly={hasOfficial}
          pending={customerData.isPending} onClose={() => setShowCustomerData(false)} onSubmit={(v) => customerData.mutate(v)} />

        {promoting && (
          <CustomerDataDialog open title={`Customer adopted ${promoting.revision_name} as…`} officialOnly={hasOfficial}
            pending={promote.isPending} onClose={() => setPromoting(null)} onSubmit={(v) => promote.mutate({ id: promoting.id, v })} />
        )}

        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8">
          <h2 className="text-xl font-bold text-slate-100 mb-4">Part Information</h2>
          <div className="grid grid-cols-2 gap-4">
            <div><div className="text-sm text-slate-400">Type</div><div className="font-medium text-slate-100 capitalize">{part.part_type}</div></div>
            <div><div className="text-sm text-slate-400">Classification</div><div className="font-medium text-slate-100 capitalize">{part.data_classification}</div></div>
          </div>
        </div>

        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8">
          <h2 className="text-xl font-bold text-slate-100 mb-6">Revisions</h2>
          <RevisionTimeline revisions={part.revisions} activeRevisionId={part.active_revision_id}
            onNewProposal={(id) => setProposalParent(id)} onPromote={(r) => setPromoting(r)}
            onReject={(id) => reject.mutate(id)} onUnreject={(id) => unreject.mutate(id)} />

          {proposalParent !== null && (
            <div className="mt-4 p-4 bg-slate-900 rounded-lg border border-slate-700">
              <textarea value={proposalSummary} onChange={(e) => setProposalSummary(e.target.value)} rows={3}
                placeholder="What are we changing in this proposal?"
                className="w-full p-2 border border-slate-700 rounded text-sm mb-2 bg-slate-800 text-slate-100" />
              <div className="flex gap-2">
                <button onClick={() => proposal.mutate(proposalParent)} disabled={proposal.isPending}
                  className="px-3 py-1 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:bg-slate-600">Create proposal</button>
                <button onClick={() => { setProposalParent(null); setProposalSummary(''); }}
                  className="px-3 py-1 bg-slate-700 text-slate-100 text-sm rounded hover:bg-slate-600">Cancel</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update `ProjectDetailPage.tsx`**

1. Around line 58, the local revision type: change `phase: string;` to `phase: 'review' | 'official';` and add `part_phase_at_receipt?: string; customer_index?: string | null;`.
2. Replace `phaseColor` (line 228) with:

```tsx
function phaseColor(phase: string): string {
  return phase === 'official' ? 'bg-amber-900/30 text-amber-300' : 'bg-blue-900/30 text-blue-300';
}
```

3. Replace `createRfqMutation` (lines 988-1005) with a dialog-driven mutation:

```tsx
  const [showCustomerData, setShowCustomerData] = useState(false);
  const customerDataMutation = useMutation({
    mutationFn: async (v: CustomerDataInput) => {
      const res = await client.post(`/v1/parts/${selectedPartId}/revisions/customer-data`, v);
      return res.data;
    },
    onSuccess: (data) => {
      toast.success(`Recorded ${data.revision_name}`);
      setShowCustomerData(false);
      queryClient.invalidateQueries({ queryKey: ['part-revisions', selectedPartId] });
      queryClient.invalidateQueries({ queryKey: ['parts', id] });
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to record customer data');
    },
  });
```

   Add `import CustomerDataDialog, { type CustomerDataInput } from '../components/parts/CustomerDataDialog';` at the top.

4. Around line 1263, replace the `+ Create RFQ Revision` button with:

```tsx
                    <button onClick={() => setShowCustomerData(true)}
                      className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium">
                      + Customer data
                    </button>
                    <CustomerDataDialog open={showCustomerData} title="Customer data received"
                      pending={customerDataMutation.isPending} onClose={() => setShowCustomerData(false)}
                      onSubmit={(v) => customerDataMutation.mutate(v)} />
```

5. Around line 1386, where the phase badge renders `rev.phase.replace(/_/g, ' ')`, append the phase-at-receipt: `{rev.phase}{rev.part_phase_at_receipt ? ` · ${rev.part_phase_at_receipt}` : ''}`.

- [ ] **Step 3: Typecheck, lint, and test**

Run: `cd frontend && npx tsc --noEmit && npm run lint && npx vitest run`
Expected: clean. Typical fix: unused imports left in `ProjectDetailPage.tsx` from the removed mutation.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/PartDetail.tsx frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(ui): part page uses customer data index and lifecycle phase

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Docs and end-to-end check

**Files:**
- Modify: `DEPLOYMENT.md` (operational notes)
- Modify: `docs/CHANGE_MANAGEMENT_FLOW.md` if it names ECR revisions

- [ ] **Step 1: Deployment note**

Append to the "Operational notes" list in `DEPLOYMENT.md`:

```markdown
- **Customer data index (migration 072):** revision names change from
  RFQ/ENG/IND/ECR to `E<n>` (customer review data) and `<n>` (customer
  official data); minors `.<m>` are internal proposals. The migration renames
  existing rows in place per part in creation order; ids are unchanged. After
  deploy, set the lifecycle phase of nominated parts by hand on the part page
  (admin: "Mark nominated"). No rebuild needed, restart applies the migration.
```

- [ ] **Step 2: Grep docs for stale names**

Run: `grep -rn "ECR1\|IND1\|ENG1\|RFQ1\|rfq_phase" docs/*.md README.md MODULES.md 2>/dev/null`
Update each hit to the new vocabulary (E1 / 1 / 1.1) or delete the sentence if it describes a removed endpoint.

- [ ] **Step 3: Full verification**

Run:
```bash
cd backend && python -m pytest tests/ -q
cd ../frontend && npx tsc --noEmit && npm run lint && npx vitest run
```
Expected: both green. Record the counts in the commit body.

- [ ] **Step 4: Manual smoke on the dev stack**

Run `./run_backend.sh` and `cd frontend && npm run dev`, open a part, click "+ Customer data" → review → E1 appears with `rfq` badge; "Mark nominated" (admin) → header shows nominated; "+ Customer data" → official → `1`; "+ Proposal" on `1` → `1.1`; "Customer adopted" on `1.1` → `2`. Upload a file to E1 through the project page to confirm `approved` customer majors accept uploads.

- [ ] **Step 5: Commit**

```bash
git add DEPLOYMENT.md docs
git commit -m "docs: customer data index deployment note

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
