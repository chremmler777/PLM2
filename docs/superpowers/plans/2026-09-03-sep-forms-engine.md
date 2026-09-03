# SEP Forms Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In-app, JSON-defined forms attached to SEP work items; submitting a form marks its linked items done; the risk assessment form replaces the SEP risk tab.

**Architecture:** Form definitions are JSON files under `backend/app/data/forms/`, loaded into an immutable `form_definitions` table at startup. Filled forms are `form_instances` (JSON data) with a `form_events` audit trail. A tiny expression language, implemented in Python and TypeScript with shared test vectors, drives computed fields. A generic React renderer draws any definition; a side panel opens it from the SEP checklist.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (backend, tests with pytest + aiosqlite), React 18 + TanStack Query + Tailwind + react-hook-form/zod (frontend, tests with vitest + testing-library), reportlab for PDF.

**Spec:** `docs/superpowers/specs/2026-09-03-sep-forms-engine-design.md`

## Global Constraints

- English-only labels. No German text in definitions or UI.
- Definitions are immutable per (key, version); a change is a new version.
- SEP item references are `"<gate code>:<item_no>"` strings (item numbers restart per gate).
- Submit flips linked open items to done; reopen flips them back; closed gates and `not_applicable` items are never touched.
- `gate_items` flag exists on every definition and is `false` for all first-batch forms.
- `sep_risks` table and its endpoints stay in place; gate colour and sign-off read risk rows from the risk-assessment form instance.
- Backend tests run from `backend/` with `python -m pytest tests/<file> -v`. Frontend tests run from `frontend/` with `npx vitest run <file>`.
- Commit after every task with the trailer:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Bts9vcERghAQ2cVvRSsFaY
  ```
- Never push. Never touch `~/.claude/projects`. Memory lives in `<project-root>/memory/`.

## File map

Backend (all under `backend/`):

| file | responsibility |
|---|---|
| `app/forms/__init__.py` | package marker |
| `app/forms/expr.py` | expression tokenizer/parser/evaluator (`evaluate(expr, scope)`) |
| `app/forms/compute.py` | `recompute(definition, data)` — fills computed fields/columns and footers |
| `app/forms/validate.py` | `validate_definition(body, template)` and `missing_for_submit(definition, data)` |
| `app/forms/prefill.py` | `build_prefill(db, definition, project, user)` |
| `app/forms/loader.py` | `load_definitions(session)` — read JSON files, insert missing versions |
| `app/forms/service.py` | instance lifecycle: create, save, submit, reopen, sign, SEP item flipping |
| `app/forms/pdf.py` | `render_pdf(definition, instance, events, names) -> bytes` |
| `app/models/forms.py` | `FormDefinition`, `FormInstance`, `FormEvent` |
| `app/data/forms/*.json` | six definitions |
| `app/data/forms/expr_vectors.json` | shared expression test vectors |
| `app/api/v1/timing/forms.py` | `/v1/forms` router |
| `alembic/versions/065_sep_forms.py` | tables + risk migration |
| `scripts/load_form_definitions.py` | CLI loader |
| `tests/test_form_expr.py`, `tests/test_form_definitions.py`, `tests/test_forms.py` | tests |

Frontend (all under `frontend/src/`):

| file | responsibility |
|---|---|
| `forms/expr.ts` | TypeScript twin of `expr.py` |
| `forms/expr.test.ts` | runs the shared vectors |
| `forms/types.ts` | definition / instance types |
| `forms/compute.ts` | `recompute(definition, data)` |
| `forms/FormRenderer.tsx` | generic field/section/table renderer |
| `forms/FormRenderer.test.tsx` | renders every field type |
| `forms/FormPanel.tsx` | side panel: load instance, save/submit/reopen/sign/export |
| `forms/ProjectFormsTab.tsx` | list of instances for a project, grouped by gate |
| `components/ProjectSepSection.tsx` | item form button, Forms tab replaces Risks tab |
| `pages/MyTasksPage.tsx` | Forms section |

---

### Task 1: Expression language (Python) with shared vectors

**Files:**
- Create: `backend/app/forms/__init__.py` (empty)
- Create: `backend/app/forms/expr.py`
- Create: `backend/app/data/forms/expr_vectors.json`
- Test: `backend/tests/test_form_expr.py`

**Interfaces:**
- Produces: `evaluate(expr: str, scope: dict) -> Any`. Scope values are numbers, strings, booleans, `None`, or for `count`/`sum`, `scope["_rows"]` is a list of row dicts. Raises `ExprError` on syntax or unknown identifier.
- Helpers: `band(x, [limit, label]..., default)`, `count(<row predicate>)`, `sum(<row expr>)`, `today()` (ISO date string), `days_between(a, b)` (int, a and b ISO date strings, b - a).

Grammar (precedence low→high): `or`, `and`, `not`, comparison (`== != < <= > >=`), `+ -`, `* /`, unary `-`, primary (number, `'string'`, `true`, `false`, `null`, identifier, `[list]`, call `name(args)`, parenthesised). Identifiers resolve against `scope`; missing → `ExprError`. Inside `count(...)` and `sum(...)` the argument is evaluated once per row of `scope["_rows"]` with the row merged over the scope. Division by zero returns `0`. `None` in arithmetic is treated as `0`; in comparisons `None == None` is true.

- [ ] **Step 1: Write the vectors file**

`backend/app/data/forms/expr_vectors.json`:
```json
[
  {"expr": "(q + c + s) * p", "scope": {"q": 0.5, "c": 1, "s": 0, "p": 0.5}, "expected": 0.75},
  {"expr": "(q + c + s) * p", "scope": {"q": null, "c": 1, "s": 0, "p": 0.5}, "expected": 0.5},
  {"expr": "band(rkz, [0.4,'low'],[0.8,'medium'],[1.0,'high'],'very high')", "scope": {"rkz": 0.3}, "expected": "low"},
  {"expr": "band(rkz, [0.4,'low'],[0.8,'medium'],[1.0,'high'],'very high')", "scope": {"rkz": 0.8}, "expected": "medium"},
  {"expr": "band(rkz, [0.4,'low'],[0.8,'medium'],[1.0,'high'],'very high')", "scope": {"rkz": 1.5}, "expected": "very high"},
  {"expr": "count(status == 'open')", "scope": {"_rows": [{"status": "open"}, {"status": "done"}, {"status": "open"}]}, "expected": 2},
  {"expr": "sum(budget)", "scope": {"_rows": [{"budget": 10}, {"budget": 5.5}, {"budget": null}]}, "expected": 15.5},
  {"expr": "a / b", "scope": {"a": 1, "b": 0}, "expected": 0},
  {"expr": "not done and x > 1", "scope": {"done": false, "x": 2}, "expected": true},
  {"expr": "days_between('2026-01-01', '2026-01-11')", "scope": {}, "expected": 10},
  {"expr": "x == null", "scope": {"x": null}, "expected": true},
  {"expr": "-x + 3", "scope": {"x": 1}, "expected": 2},
  {"expr": "unknown + 1", "scope": {}, "error": true},
  {"expr": "1 +", "scope": {}, "error": true}
]
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_form_expr.py`:
```python
import json
from pathlib import Path

import pytest

from app.forms.expr import evaluate, ExprError

VECTORS = json.loads((Path(__file__).resolve().parents[1] / "app" / "data" / "forms" / "expr_vectors.json").read_text())


@pytest.mark.parametrize("vec", VECTORS, ids=[v["expr"] for v in VECTORS])
def test_vector(vec):
    if vec.get("error"):
        with pytest.raises(ExprError):
            evaluate(vec["expr"], vec["scope"])
    else:
        got = evaluate(vec["expr"], vec["scope"])
        if isinstance(vec["expected"], float):
            assert got == pytest.approx(vec["expected"])
        else:
            assert got == vec["expected"]


def test_today_is_iso_date():
    assert len(evaluate("today()", {})) == 10
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_form_expr.py -q`
Expected: ImportError `app.forms.expr`.

- [ ] **Step 4: Implement `expr.py`**

```python
"""Tiny expression language for computed form fields.

Mirrors frontend/src/forms/expr.ts; both are checked against
app/data/forms/expr_vectors.json.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

class ExprError(Exception):
    pass

_TOKEN = re.compile(r"\s*(?:(\d+\.\d+|\d+)|('(?:[^'\\]|\\.)*')|(==|!=|<=|>=|[-+*/()<>,\[\]])|([A-Za-z_][A-Za-z0-9_]*))")

def _tokenize(src: str) -> list[tuple[str, Any]]:
    out, pos = [], 0
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            if src[pos:].strip() == "":
                break
            raise ExprError(f"bad token at {pos}: {src[pos:pos+10]!r}")
        pos = m.end()
        num, s, op, ident = m.groups()
        if num is not None:
            out.append(("num", float(num) if "." in num else int(num)))
        elif s is not None:
            out.append(("str", s[1:-1].replace("\\'", "'")))
        elif op is not None:
            out.append(("op", op))
        else:
            out.append(("id", ident))
    out.append(("eof", None))
    return out

class _Parser:
    def __init__(self, tokens):
        self.t, self.i = tokens, 0
    def peek(self):
        return self.t[self.i]
    def take(self, kind=None, val=None):
        k, v = self.t[self.i]
        if (kind and k != kind) or (val is not None and v != val):
            raise ExprError(f"expected {val or kind}, got {v!r}")
        self.i += 1
        return v
    # precedence climbing
    def parse(self):
        node = self.p_or()
        if self.peek()[0] != "eof":
            raise ExprError(f"unexpected {self.peek()[1]!r}")
        return node
    def p_or(self):
        n = self.p_and()
        while self.peek() == ("id", "or"):
            self.take(); n = ("or", n, self.p_and())
        return n
    def p_and(self):
        n = self.p_not()
        while self.peek() == ("id", "and"):
            self.take(); n = ("and", n, self.p_not())
        return n
    def p_not(self):
        if self.peek() == ("id", "not"):
            self.take(); return ("not", self.p_not())
        return self.p_cmp()
    def p_cmp(self):
        n = self.p_add()
        while self.peek()[0] == "op" and self.peek()[1] in ("==", "!=", "<", "<=", ">", ">="):
            op = self.take(); n = ("cmp", op, n, self.p_add())
        return n
    def p_add(self):
        n = self.p_mul()
        while self.peek()[0] == "op" and self.peek()[1] in ("+", "-"):
            op = self.take(); n = ("bin", op, n, self.p_mul())
        return n
    def p_mul(self):
        n = self.p_unary()
        while self.peek()[0] == "op" and self.peek()[1] in ("*", "/"):
            op = self.take(); n = ("bin", op, n, self.p_unary())
        return n
    def p_unary(self):
        if self.peek() == ("op", "-"):
            self.take(); return ("neg", self.p_unary())
        return self.p_primary()
    def p_primary(self):
        k, v = self.peek()
        if k == "num": self.take(); return ("lit", v)
        if k == "str": self.take(); return ("lit", v)
        if k == "op" and v == "(":
            self.take(); n = self.p_or(); self.take("op", ")"); return n
        if k == "op" and v == "[":
            self.take(); items = []
            while self.peek() != ("op", "]"):
                items.append(self.p_or())
                if self.peek() == ("op", ","): self.take()
            self.take("op", "]"); return ("list", items)
        if k == "id":
            self.take()
            if v in ("true", "false"): return ("lit", v == "true")
            if v == "null": return ("lit", None)
            if self.peek() == ("op", "("):
                self.take(); args = []
                while self.peek() != ("op", ")"):
                    args.append(self.p_or())
                    if self.peek() == ("op", ","): self.take()
                self.take("op", ")"); return ("call", v, args)
            return ("var", v)
        raise ExprError(f"unexpected {v!r}")

def _num(x):
    return 0 if x is None or x is False else (1 if x is True else x)

def _eval(node, scope):
    kind = node[0]
    if kind == "lit": return node[1]
    if kind == "var":
        if node[1] not in scope: raise ExprError(f"unknown identifier {node[1]}")
        return scope[node[1]]
    if kind == "list": return [_eval(n, scope) for n in node[1]]
    if kind == "neg": return -_num(_eval(node[1], scope))
    if kind == "not": return not _eval(node[1], scope)
    if kind == "and": return bool(_eval(node[1], scope)) and bool(_eval(node[2], scope))
    if kind == "or": return bool(_eval(node[1], scope)) or bool(_eval(node[2], scope))
    if kind == "cmp":
        op, a, b = node[1], _eval(node[2], scope), _eval(node[3], scope)
        if op == "==": return a == b
        if op == "!=": return a != b
        a, b = _num(a), _num(b)
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    if kind == "bin":
        op, a, b = node[1], _num(_eval(node[2], scope)), _num(_eval(node[3], scope))
        if op == "+": return a + b
        if op == "-": return a - b
        if op == "*": return a * b
        return 0 if b == 0 else a / b
    if kind == "call":
        name, args = node[1], node[2]
        if name in ("count", "sum"):
            if len(args) != 1: raise ExprError(f"{name} takes one argument")
            rows = scope.get("_rows") or []
            vals = [_eval(args[0], {**scope, **row}) for row in rows]
            return sum(1 for v in vals if v) if name == "count" else sum(_num(v) for v in vals)
        vals = [_eval(a, scope) for a in args]
        if name == "band":
            x, *bands, default = vals
            x = _num(x)
            for limit, label in bands:
                if x <= _num(limit): return label
            return default
        if name == "today": return date.today().isoformat()
        if name == "days_between":
            a, b = date.fromisoformat(str(vals[0])[:10]), date.fromisoformat(str(vals[1])[:10])
            return (b - a).days
        raise ExprError(f"unknown function {name}")
    raise ExprError(f"bad node {kind}")

_CACHE: dict[str, tuple] = {}

def evaluate(expr: str, scope: dict) -> Any:
    ast = _CACHE.get(expr)
    if ast is None:
        ast = _Parser(_tokenize(expr)).parse()
        _CACHE[expr] = ast
    return _eval(ast, scope)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_form_expr.py -q`
Expected: all vectors PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/forms backend/app/data/forms/expr_vectors.json backend/tests/test_form_expr.py
git commit -m "feat(forms): expression language with shared test vectors"
```

---

### Task 2: Models and migration

**Files:**
- Create: `backend/app/models/forms.py`
- Modify: `backend/app/models/__init__.py` (add import next to the sep import on line 17)
- Create: `backend/alembic/versions/065_sep_forms.py`
- Test: `backend/tests/test_forms.py` (first test only)

**Interfaces:**
- Produces: `FormDefinition(key, version, title, implements, cardinality, gate_items, body)`, `FormInstance(project_id, definition_id, status, data, owner_id, created_by, updated_by, submitted_by, submitted_at)`, `FormEvent(instance_id, user_id, event, role, diff)`. Constants `FORM_STATUSES = ("draft", "submitted", "reopened")`, `FORM_EVENTS = ("created", "saved", "submitted", "reopened", "signed")`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_forms.py`:
```python
"""SEP forms engine: definitions, instances, events, SEP item linking."""
from sqlalchemy import select

from app.models.forms import FormDefinition, FormInstance, FormEvent


async def test_models_roundtrip(session_factory, seed):
    async with session_factory() as s:
        d = FormDefinition(key="t", version=1, title="T", implements=None, cardinality="single",
                           gate_items=False, body={"sections": []})
        s.add(d)
        await s.flush()
        inst = FormInstance(project_id=seed["project_id"], definition_id=d.id, status="draft",
                            data={"a": 1}, created_by=seed["admin_id"], updated_by=seed["admin_id"])
        s.add(inst)
        await s.flush()
        s.add(FormEvent(instance_id=inst.id, user_id=seed["admin_id"], event="created"))
        await s.commit()
    async with session_factory() as s:
        got = (await s.execute(select(FormInstance))).scalar_one()
        assert got.data == {"a": 1}
        ev = (await s.execute(select(FormEvent))).scalar_one()
        assert ev.event == "created" and ev.role is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_forms.py -q` → ImportError.

- [ ] **Step 3: Write the models**

`backend/app/models/forms.py`:
```python
"""SEP forms engine: JSON-defined forms filled per project.

Definitions are immutable per (key, version); instances hold the filled data as
JSON and point at the version they were created against; events are the audit
trail (created/saved/submitted/reopened/signed).
"""
from datetime import datetime

from sqlalchemy import String, Text, DateTime, Boolean, Integer, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

FORM_STATUSES = ("draft", "submitted", "reopened")
FORM_EVENTS = ("created", "saved", "submitted", "reopened", "signed")
FORM_CARDINALITIES = ("single", "multi")


class FormDefinition(Base):
    __tablename__ = "form_definitions"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_form_definition_key_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    implements: Mapped[str | None] = mapped_column(String(60), nullable=True)
    cardinality: Mapped[str] = mapped_column(String(10), default="single")
    gate_items: Mapped[bool] = mapped_column(Boolean, default=False)
    body: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FormInstance(Base):
    __tablename__ = "form_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("form_definitions.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    definition: Mapped["FormDefinition"] = relationship()
    events: Mapped[list["FormEvent"]] = relationship(
        back_populates="instance", cascade="all, delete-orphan", order_by="FormEvent.id"
    )


class FormEvent(Base):
    __tablename__ = "form_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("form_instances.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    event: Mapped[str] = mapped_column(String(20))
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    diff: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    instance: Mapped["FormInstance"] = relationship(back_populates="events")
```

In `backend/app/models/__init__.py`, after line 17 add:
```python
from app.models.forms import FormDefinition, FormInstance, FormEvent
```
and add the three names to `__all__` if the module defines one.

- [ ] **Step 4: Write the migration**

`backend/alembic/versions/065_sep_forms.py` (tables only; the risk data step is added in Task 7):
```python
"""SEP forms engine: form_definitions, form_instances, form_events.

Revision ID: 065
Revises: 064
Create Date: 2026-09-03
"""
from alembic import op
import sqlalchemy as sa

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    existing = inspect(op.get_bind()).get_table_names()

    if "form_definitions" not in existing:
        op.create_table(
            "form_definitions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(60), nullable=False, index=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("implements", sa.String(60), nullable=True),
            sa.Column("cardinality", sa.String(10), nullable=False, server_default="single"),
            sa.Column("gate_items", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("body", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("key", "version", name="uq_form_definition_key_version"),
        )
    if "form_instances" not in existing:
        op.create_table(
            "form_instances",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False, index=True),
            sa.Column("definition_id", sa.Integer(), sa.ForeignKey("form_definitions.id"), nullable=False, index=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft", index=True),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True, index=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
        )
    if "form_events" not in existing:
        op.create_table(
            "form_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("instance_id", sa.Integer(), sa.ForeignKey("form_instances.id"), nullable=False, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("event", sa.String(20), nullable=False),
            sa.Column("role", sa.String(20), nullable=True),
            sa.Column("diff", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table("form_events")
    op.drop_table("form_instances")
    op.drop_table("form_definitions")
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/test_forms.py tests/test_sep.py -q` → PASS (sep tests prove `create_all` still works with the new models).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/forms.py backend/app/models/__init__.py backend/alembic/versions/065_sep_forms.py backend/tests/test_forms.py
git commit -m "feat(forms): form definition/instance/event models and migration 065"
```

---

### Task 3: Compute, definition validation, and loader

**Files:**
- Create: `backend/app/forms/compute.py`
- Create: `backend/app/forms/validate.py`
- Create: `backend/app/forms/loader.py`
- Create: `backend/scripts/load_form_definitions.py`
- Test: `backend/tests/test_form_definitions.py`

**Interfaces:**
- Consumes: `evaluate` from Task 1.
- Produces:
  - `recompute(body: dict, data: dict) -> dict` — returns a new data dict with every `computed` field/column filled and `_footer` per table section (`data[section_id + "_footer"] = {label: value}`).
  - `validate_definition(body: dict, template: dict) -> list[str]` — list of problems (empty = valid). `template` is the parsed `sep_template.json`.
  - `missing_for_submit(body: dict, data: dict) -> list[str]` — human-readable missing paths.
  - `FIELD_TYPES`, `PREFILL_ROOTS = {"project.code","project.name","project.plant","user.me","user.me_name","date.today","team.members"}`, `SIGNATURE_ROLES = ("md","pm","quality","dt")`.
  - `load_definitions(session) -> int` (number inserted), `DEFINITIONS_DIR = backend/app/data/forms`.
  - `latest_definitions(session) -> list[FormDefinition]` one row per key, highest version.

Data shape: `data[section.id]` is a dict of `field.id -> value` for `fields` sections and a list of row dicts for `table` sections.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_form_definitions.py`:
```python
import json
from pathlib import Path

from sqlalchemy import select

from app.forms.compute import recompute
from app.forms.validate import validate_definition, missing_for_submit
from app.forms.loader import load_definitions, DEFINITIONS_DIR, latest_definitions
from app.models.forms import FormDefinition

TEMPLATE = json.loads((Path(__file__).resolve().parents[1] / "app" / "data" / "sep_template.json").read_text())

MINI = {
    "key": "mini", "version": 1, "title": "Mini", "implements": None, "cardinality": "single",
    "gate_items": False, "sep_items": ["K0/RG1:2"], "signatures": [], "required_for_submit": ["header.name", "rows"],
    "sections": [
        {"id": "header", "title": "H", "kind": "fields", "fields": [
            {"id": "name", "label": "Name", "type": "text", "prefill": "project.name"},
            {"id": "n", "label": "N", "type": "number"},
            {"id": "double", "label": "Double", "type": "computed", "expr": "n * 2"},
        ]},
        {"id": "rows", "title": "Rows", "kind": "table", "min_rows": 1, "columns": [
            {"id": "q", "label": "Q", "type": "number"},
            {"id": "p", "label": "P", "type": "number"},
            {"id": "r", "label": "R", "type": "computed", "expr": "q * p"},
            {"id": "status", "label": "Status", "type": "choice", "options": ["open", "done"]},
        ], "footer": [{"label": "Open", "expr": "count(status == 'open')"}]},
    ],
}


def test_recompute_fields_tables_footer():
    data = {"header": {"name": "x", "n": 2}, "rows": [{"q": 0.5, "p": 1, "status": "open"}, {"q": 1, "p": 1, "status": "done"}]}
    out = recompute(MINI, data)
    assert out["header"]["double"] == 4
    assert [r["r"] for r in out["rows"]] == [0.5, 1]
    assert out["rows_footer"] == {"Open": 1}


def test_validate_definition_catches_problems():
    assert validate_definition(MINI, TEMPLATE) == []
    bad = json.loads(json.dumps(MINI))
    bad["sep_items"] = ["K0/RG1:999"]
    bad["sections"][0]["fields"][0]["prefill"] = "rfq.sop"
    bad["sections"][0]["fields"][1]["type"] = "money"
    bad["sections"][0]["fields"][2]["expr"] = "nope * 2"
    problems = validate_definition(bad, TEMPLATE)
    assert any("K0/RG1:999" in p for p in problems)
    assert any("rfq.sop" in p for p in problems)
    assert any("money" in p for p in problems)
    assert any("nope" in p for p in problems)


def test_missing_for_submit():
    assert missing_for_submit(MINI, {"header": {"name": ""}, "rows": []}) == ["header.name", "rows"]
    assert missing_for_submit(MINI, {"header": {"name": "a"}, "rows": [{"q": 1}]}) == []


def test_all_shipped_definitions_valid():
    files = sorted(DEFINITIONS_DIR.glob("*.json"))
    keys = [f.stem for f in files if f.stem != "expr_vectors"]
    assert set(keys) >= {"risk_assessment", "sales_pm_handover", "project_legitimization",
                         "contact_list", "lop", "deviation_agreement"}
    for f in files:
        if f.stem == "expr_vectors":
            continue
        body = json.loads(f.read_text())
        assert body["key"] == f.stem
        assert validate_definition(body, TEMPLATE) == [], f.name
        recompute(body, {})  # empty data must not crash


async def test_loader_is_idempotent(session_factory, seed):
    async with session_factory() as s:
        n1 = await load_definitions(s)
        await s.commit()
    async with session_factory() as s:
        n2 = await load_definitions(s)
        await s.commit()
        rows = (await s.execute(select(FormDefinition))).scalars().all()
        latest = await latest_definitions(s)
    assert n1 >= 6 and n2 == 0
    assert len(rows) == n1 and len(latest) == n1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_form_definitions.py -q` → ImportError.

- [ ] **Step 3: Implement `compute.py`**

```python
"""Fill computed fields, computed columns and table footers of a form instance."""
from __future__ import annotations

from app.forms.expr import evaluate, ExprError


def _scope_for_fields(values: dict) -> dict:
    return dict(values)


def recompute(body: dict, data: dict) -> dict:
    out: dict = {}
    for section in body.get("sections", []):
        sid = section["id"]
        if section["kind"] == "fields":
            values = dict(data.get(sid) or {})
            for f in section["fields"]:
                if f["type"] == "computed":
                    try:
                        values[f["id"]] = evaluate(f["expr"], _scope_for_fields(values))
                    except ExprError:
                        values[f["id"]] = None
            out[sid] = values
        else:
            rows = [dict(r) for r in (data.get(sid) or [])]
            for row in rows:
                for c in section["columns"]:
                    if c["type"] == "computed":
                        try:
                            row[c["id"]] = evaluate(c["expr"], row)
                        except ExprError:
                            row[c["id"]] = None
            out[sid] = rows
            if section.get("footer"):
                footer = {}
                for f in section["footer"]:
                    try:
                        footer[f["label"]] = evaluate(f["expr"], {"_rows": rows})
                    except ExprError:
                        footer[f["label"]] = None
                out[f"{sid}_footer"] = footer
    # keep unknown keys (forward compatibility) without overriding computed sections
    for k, v in data.items():
        out.setdefault(k, v)
    return out
```

- [ ] **Step 4: Implement `validate.py`**

```python
"""Static validation of form definitions and submit-time completeness check."""
from __future__ import annotations

from app.forms.expr import evaluate, ExprError

FIELD_TYPES = {"text", "multiline", "number", "date", "checkbox", "choice", "multichoice", "user", "computed"}
PREFILL_ROOTS = {"project.code", "project.name", "project.plant", "user.me", "user.me_name", "date.today", "team.members"}
SIGNATURE_ROLES = ("md", "pm", "quality", "dt")
CARDINALITIES = ("single", "multi")


def _template_item_refs(template: dict) -> set[str]:
    return {f"{g['code']}:{i['item_no']}" for g in template["gates"] for i in g["items"]}


def _check_expr(expr: str, ids: list[str], problems: list[str], where: str) -> None:
    scope = {i: 0 for i in ids}
    scope["_rows"] = [dict(scope)]
    try:
        evaluate(expr, scope)
    except ExprError as e:
        problems.append(f"{where}: bad expression {expr!r}: {e}")


def validate_definition(body: dict, template: dict) -> list[str]:
    p: list[str] = []
    for req in ("key", "version", "title", "cardinality", "sections"):
        if req not in body:
            p.append(f"missing top-level key {req}")
    if p:
        return p
    if body["cardinality"] not in CARDINALITIES:
        p.append(f"cardinality must be one of {CARDINALITIES}")
    refs = _template_item_refs(template)
    for ref in body.get("sep_items", []):
        if ref not in refs:
            p.append(f"sep_items: unknown SEP item {ref}")
    for role in body.get("signatures", []):
        if role not in SIGNATURE_ROLES:
            p.append(f"signatures: unknown role {role}")
    section_ids: set[str] = set()
    for s in body["sections"]:
        sid = s.get("id")
        if not sid or sid in section_ids:
            p.append(f"section id missing or duplicate: {sid}")
        section_ids.add(sid)
        if s.get("kind") not in ("fields", "table"):
            p.append(f"section {sid}: kind must be fields or table")
            continue
        members = s.get("fields" if s["kind"] == "fields" else "columns", [])
        ids = [m.get("id") for m in members]
        if len(set(ids)) != len(ids):
            p.append(f"section {sid}: duplicate field ids")
        for m in members:
            where = f"section {sid}.{m.get('id')}"
            if m.get("type") not in FIELD_TYPES:
                p.append(f"{where}: unknown type {m.get('type')}")
                continue
            if m["type"] in ("choice", "multichoice") and not m.get("options"):
                p.append(f"{where}: choice needs options")
            if m["type"] == "computed":
                _check_expr(m.get("expr", ""), ids, p, where)
            if "prefill" in m and m["prefill"] not in PREFILL_ROOTS:
                p.append(f"{where}: unknown prefill {m['prefill']}")
        for f in s.get("footer", []) or []:
            if s["kind"] != "table":
                p.append(f"section {sid}: footer only on tables")
            _check_expr(f.get("expr", ""), ids, p, f"section {sid} footer {f.get('label')}")
    for path in body.get("required_for_submit", []):
        sec = path.split(".")[0]
        if sec not in section_ids:
            p.append(f"required_for_submit: unknown section in {path}")
    return p


def _empty(v) -> bool:
    return v is None or v == "" or v == [] or v is False


def missing_for_submit(body: dict, data: dict) -> list[str]:
    missing: list[str] = []
    sections = {s["id"]: s for s in body["sections"]}
    for path in body.get("required_for_submit", []):
        sid, _, fid = path.partition(".")
        s = sections[sid]
        if s["kind"] == "table":
            if len(data.get(sid) or []) < max(1, int(s.get("min_rows", 1) or 1)):
                missing.append(path)
        else:
            if _empty((data.get(sid) or {}).get(fid)):
                missing.append(path)
    for s in body["sections"]:
        if s["kind"] == "fields":
            for f in s["fields"]:
                if f.get("required") and _empty((data.get(s["id"]) or {}).get(f["id"])):
                    path = f"{s['id']}.{f['id']}"
                    if path not in missing:
                        missing.append(path)
    return missing
```

- [ ] **Step 5: Implement `loader.py` and the script**

`backend/app/forms/loader.py`:
```python
"""Load JSON form definitions into form_definitions (insert-only, idempotent)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.forms import FormDefinition

logger = logging.getLogger(__name__)
DEFINITIONS_DIR = Path(__file__).resolve().parents[1] / "data" / "forms"


def read_definition_files() -> list[dict]:
    out = []
    for f in sorted(DEFINITIONS_DIR.glob("*.json")):
        if f.stem == "expr_vectors":
            continue
        out.append(json.loads(f.read_text()))
    return out


async def load_definitions(session: AsyncSession) -> int:
    existing = {(k, v) for k, v in (await session.execute(
        select(FormDefinition.key, FormDefinition.version))).all()}
    inserted = 0
    for body in read_definition_files():
        if (body["key"], body["version"]) in existing:
            continue
        session.add(FormDefinition(
            key=body["key"], version=body["version"], title=body["title"],
            implements=body.get("implements"), cardinality=body.get("cardinality", "single"),
            gate_items=bool(body.get("gate_items", False)), body=body,
        ))
        inserted += 1
    if inserted:
        await session.flush()
        logger.info("Loaded %d form definition version(s)", inserted)
    return inserted


async def latest_definitions(session: AsyncSession) -> list[FormDefinition]:
    sub = select(FormDefinition.key, func.max(FormDefinition.version).label("v")).group_by(FormDefinition.key).subquery()
    rows = (await session.execute(
        select(FormDefinition).join(sub, (FormDefinition.key == sub.c.key) & (FormDefinition.version == sub.c.v))
        .order_by(FormDefinition.title)
    )).scalars().all()
    return list(rows)


async def latest_definition(session: AsyncSession, key: str) -> FormDefinition | None:
    return (await session.execute(
        select(FormDefinition).where(FormDefinition.key == key).order_by(FormDefinition.version.desc()).limit(1)
    )).scalar_one_or_none()
```

`backend/scripts/load_form_definitions.py`:
```python
"""Insert any new form definition versions from app/data/forms into the DB.

Usage (inside the backend container or venv): python scripts/load_form_definitions.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import AsyncSessionLocal  # noqa: E402
from app.forms.loader import load_definitions  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as session:
        n = await load_definitions(session)
        await session.commit()
    print(f"inserted {n} definition version(s)")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Write the six definitions** (next task section, Task 3b) then run
`cd backend && python -m pytest tests/test_form_definitions.py -q` → PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/forms backend/scripts/load_form_definitions.py backend/tests/test_form_definitions.py backend/app/data/forms
git commit -m "feat(forms): compute, definition validation, loader, first-batch definitions"
```

---

### Task 3b: The six first-batch definitions

**Files:**
- Create: `backend/app/data/forms/risk_assessment.json`, `sales_pm_handover.json`, `project_legitimization.json`, `contact_list.json`, `lop.json`, `deviation_agreement.json`

Every file must pass `validate_definition`. Common header block used by legitimization, deviation and handover (copy verbatim into each; do not share a file):

```json
{"id": "header", "title": "Project", "kind": "fields", "fields": [
  {"id": "project_no", "label": "Project No.", "type": "text", "prefill": "project.code", "readonly": true},
  {"id": "project_title", "label": "Project title", "type": "text", "prefill": "project.name"},
  {"id": "plant", "label": "Production location", "type": "text", "prefill": "project.plant", "readonly": true},
  {"id": "prepared_by", "label": "Prepared by", "type": "user", "prefill": "user.me"},
  {"id": "date", "label": "Date", "type": "date", "prefill": "date.today"},
  {"id": "sop", "label": "SOP", "type": "date"},
  {"id": "classification", "label": "Project classification", "type": "choice",
   "options": ["Strictly confidential", "Confidential", "Internal", "Public"]},
  {"id": "currency", "label": "Currency", "type": "choice", "options": ["USD", "EUR"]}
]}
```

- [ ] **Step 1: `risk_assessment.json`**

```json
{
  "key": "risk_assessment", "version": 1, "title": "Risk Assessment",
  "implements": "F-DVS-CORP-005 rev 01", "cardinality": "single", "gate_items": false,
  "sep_items": ["K0/RG1:2"], "signatures": [],
  "required_for_submit": ["header.project_manager"],
  "sections": [
    {"id": "header", "title": "Project", "kind": "fields", "fields": [
      {"id": "project_no", "label": "Project No.", "type": "text", "prefill": "project.code", "readonly": true},
      {"id": "project_title", "label": "Project title", "type": "text", "prefill": "project.name"},
      {"id": "project_manager", "label": "Project manager", "type": "user", "prefill": "user.me"},
      {"id": "date", "label": "Date", "type": "date", "prefill": "date.today"},
      {"id": "review_date", "label": "Last review", "type": "date"},
      {"id": "classification", "label": "ISMS classification", "type": "choice",
       "options": ["Strictly confidential", "Confidential", "Internal", "Public"]}
    ]},
    {"id": "risks", "title": "Project risks", "kind": "table", "min_rows": 0, "columns": [
      {"id": "gate", "label": "Gate", "type": "choice", "options": ["K0/RG1", "K/RG2", "E/RG3", "D/RG4", "C/RG5", "B/RG6", "A/RG7"]},
      {"id": "risk", "label": "Risk", "type": "multiline", "width": 3},
      {"id": "impact", "label": "Impact", "type": "multiline", "width": 2},
      {"id": "q", "label": "Q", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "c", "label": "C", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "s", "label": "T", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "p", "label": "PoC", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "rkz", "label": "RI", "type": "computed", "expr": "(q + c + s) * p"},
      {"id": "priority", "label": "Priority", "type": "computed", "expr": "band(rkz, [0.4,'low'],[0.8,'medium'],[1.0,'high'],'very_high')"},
      {"id": "countermeasure", "label": "Countermeasures", "type": "multiline", "width": 3},
      {"id": "responsible", "label": "Responsible", "type": "user"},
      {"id": "due", "label": "Due", "type": "date"},
      {"id": "q2", "label": "Q after", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "c2", "label": "C after", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "s2", "label": "T after", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "p2", "label": "PoC after", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "rkz2", "label": "RI after", "type": "computed", "expr": "(q2 + c2 + s2) * p2"},
      {"id": "status", "label": "Status", "type": "choice", "options": ["open", "started", "finished"]}
    ], "footer": [
      {"label": "Open", "expr": "count(status != 'finished')"},
      {"label": "High or very high", "expr": "count(status != 'finished' and rkz > 0.8)"}
    ]},
    {"id": "isms", "title": "Information security (ISMS)", "kind": "table", "min_rows": 0, "columns": [
      {"id": "risk", "label": "Risk", "type": "multiline", "width": 3},
      {"id": "impact", "label": "Impact", "type": "multiline", "width": 2},
      {"id": "c", "label": "C", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "i", "label": "I", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "v", "label": "V", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "p", "label": "PoC", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "rkz", "label": "RI", "type": "computed", "expr": "(c + i + v) * p"},
      {"id": "countermeasure", "label": "Countermeasures", "type": "multiline", "width": 3},
      {"id": "responsible", "label": "Responsible", "type": "user"},
      {"id": "due", "label": "Due", "type": "date"},
      {"id": "status", "label": "Status", "type": "choice", "options": ["open", "started", "finished"]}
    ]},
    {"id": "environment", "title": "Environment and energy", "kind": "table", "min_rows": 0, "columns": [
      {"id": "risk", "label": "Risk", "type": "multiline", "width": 3},
      {"id": "impact", "label": "Impact", "type": "multiline", "width": 2},
      {"id": "nd", "label": "ND", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "d", "label": "D", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "hd", "label": "HD", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "p", "label": "PoC", "type": "number", "min": 0, "max": 1, "step": 0.1},
      {"id": "rkz", "label": "RI", "type": "computed", "expr": "(nd + d + hd) * p"},
      {"id": "countermeasure", "label": "Countermeasures", "type": "multiline", "width": 3},
      {"id": "responsible", "label": "Responsible", "type": "user"},
      {"id": "due", "label": "Due", "type": "date"},
      {"id": "status", "label": "Status", "type": "choice", "options": ["open", "started", "finished"]}
    ]}
  ]
}
```

Priority labels use `very_high` (underscore) so they match `SEP_RISK_PRIORITIES` in `app/models/sep.py` and the existing frontend `PRIORITY_STYLE` keys.

- [ ] **Step 2: `sales_pm_handover.json`**

```json
{
  "key": "sales_pm_handover", "version": 1, "title": "Project Handover Sales to PM",
  "implements": "F-DVS-CORP-001", "cardinality": "single", "gate_items": false,
  "sep_items": ["K/RG2:10"], "signatures": [],
  "required_for_submit": ["header.project_title", "customer.customer", "checks.feasibility"],
  "references": [
    {"title": "Process description: Sales handover and kick-off", "path": "Documents/SEP/global-forms/Manual_1_Process-description_Sales_Handover_KICK-OFF.pdf"},
    {"title": "Example handover 1750 HSK", "path": "Documents/SEP/global-forms/Example_Project_Handover_from_EDD&PM_1750__HSK_GH.pdf"}
  ],
  "sections": [
    <<common header block>>,
    {"id": "customer", "title": "Customer and scope", "kind": "fields", "fields": [
      {"id": "customer", "label": "Customer", "type": "text"},
      {"id": "customer_contact", "label": "Customer contact", "type": "text"},
      {"id": "platform", "label": "Platform / vehicle", "type": "text"},
      {"id": "nomination_date", "label": "Nomination date", "type": "date"},
      {"id": "pre_series", "label": "Pre-series (home line production)", "type": "checkbox"},
      {"id": "description", "label": "Description", "type": "multiline"}
    ]},
    {"id": "parts", "title": "Parts", "kind": "table", "min_rows": 0, "columns": [
      {"id": "part_no", "label": "Customer part no.", "type": "text"},
      {"id": "name", "label": "Name", "type": "text", "width": 2},
      {"id": "material", "label": "Material", "type": "text"},
      {"id": "peak_volume", "label": "Peak volume / year", "type": "number"},
      {"id": "lifetime_volume", "label": "Lifetime volume", "type": "number"},
      {"id": "price", "label": "Piece price", "type": "number", "step": 0.01}
    ]},
    {"id": "commercial", "title": "Commercial", "kind": "fields", "fields": [
      {"id": "one_time_payment", "label": "One-time payment", "type": "number", "step": 0.01},
      {"id": "amortization_per_piece", "label": "Amortization / piece", "type": "number", "step": 0.01},
      {"id": "development_cost", "label": "Development", "type": "number", "step": 0.01},
      {"id": "project_budget", "label": "Project budget", "type": "number", "step": 0.01},
      {"id": "logistic_requirements", "label": "Logistic requirements", "type": "multiline"},
      {"id": "calculation_ref", "label": "Calculation reference", "type": "text"}
    ]},
    {"id": "milestones", "title": "Customer milestones", "kind": "table", "min_rows": 0, "columns": [
      {"id": "milestone", "label": "Milestone", "type": "text", "width": 2},
      {"id": "date", "label": "Date", "type": "date"},
      {"id": "comment", "label": "Comment", "type": "text", "width": 2}
    ]},
    {"id": "checks", "title": "Checks done before handover", "kind": "fields", "fields": [
      {"id": "feasibility", "label": "Feasibility check", "type": "checkbox"},
      {"id": "capacity", "label": "Capacity check", "type": "checkbox"},
      {"id": "risk", "label": "Risk assessment", "type": "checkbox"},
      {"id": "lessons", "label": "Lessons learned reviewed", "type": "checkbox"},
      {"id": "remarks", "label": "Remarks", "type": "multiline"}
    ]}
  ]
}
```

- [ ] **Step 3: `project_legitimization.json`**

```json
{
  "key": "project_legitimization", "version": 1, "title": "Project Legitimization",
  "implements": "F-DVS-CORP-013", "cardinality": "single", "gate_items": false,
  "sep_items": ["K0/RG1:39", "K/RG2:7"], "signatures": ["md", "pm"],
  "required_for_submit": ["header.project_title", "budget"],
  "sections": [
    <<common header block>>,
    {"id": "order", "title": "Project order", "kind": "fields", "fields": [
      {"id": "statement", "label": "Statement", "type": "multiline",
       "help": "By signing this, the Managing Director(s) and Head of Project Management officially commission the implementation of the project."}
    ]},
    {"id": "budget", "title": "Project budget", "kind": "table", "min_rows": 1, "columns": [
      {"id": "item", "label": "Description", "type": "choice", "width": 2,
       "options": ["Development", "Tooling", "Control gauge", "Gripper (FOTP)", "Packaging", "Assembly equipment", "CTM part transport", "BARA", "Other"]},
      {"id": "budget", "label": "Budget", "type": "number", "step": 0.01},
      {"id": "one_time_payment", "label": "One-time payment", "type": "number", "step": 0.01},
      {"id": "amortisation", "label": "Amortisation", "type": "number", "step": 0.01},
      {"id": "remark", "label": "Remark", "type": "text", "width": 2}
    ], "footer": [
      {"label": "Total budget", "expr": "sum(budget)"},
      {"label": "Total one-time payment", "expr": "sum(one_time_payment)"}
    ]},
    {"id": "savings", "title": "Savings", "kind": "fields", "fields": [
      {"id": "included_in", "label": "Savings included in", "type": "text"},
      {"id": "value_without", "label": "Value without savings", "type": "number", "step": 0.01},
      {"id": "value_with", "label": "Value with savings", "type": "number", "step": 0.01},
      {"id": "comment", "label": "Comment", "type": "multiline",
       "help": "If BARA and savings are hidden in the internal calculation (e.g. in cycle time), say so here."}
    ]}
  ]
}
```

- [ ] **Step 4: `contact_list.json`**

```json
{
  "key": "contact_list", "version": 1, "title": "Project Contact List",
  "implements": "F-DVS-CORP-004", "cardinality": "single", "gate_items": false,
  "sep_items": ["K/RG2:8"], "signatures": [], "required_for_submit": ["contacts"],
  "sections": [
    {"id": "header", "title": "Project", "kind": "fields", "fields": [
      {"id": "project_no", "label": "Project No.", "type": "text", "prefill": "project.code", "readonly": true},
      {"id": "project_title", "label": "Project", "type": "text", "prefill": "project.name"},
      {"id": "description", "label": "Description", "type": "multiline"}
    ]},
    {"id": "contacts", "title": "Contacts", "kind": "table", "min_rows": 1, "prefill": "team.members", "columns": [
      {"id": "name", "label": "Name", "type": "text", "width": 2},
      {"id": "department", "label": "Department", "type": "text"},
      {"id": "position", "label": "Position", "type": "text"},
      {"id": "phone", "label": "Phone", "type": "text"},
      {"id": "email", "label": "Email", "type": "text", "width": 2},
      {"id": "external", "label": "External", "type": "checkbox"}
    ]}
  ]
}
```

- [ ] **Step 5: `lop.json`**

```json
{
  "key": "lop", "version": 1, "title": "Open Points List (LOP)",
  "implements": "F-DVS-CORP-010", "cardinality": "single", "gate_items": false,
  "sep_items": [], "signatures": [], "required_for_submit": [],
  "sections": [
    {"id": "header", "title": "Project", "kind": "fields", "fields": [
      {"id": "project_no", "label": "Project No.", "type": "text", "prefill": "project.code", "readonly": true},
      {"id": "project_title", "label": "Project", "type": "text", "prefill": "project.name"},
      {"id": "owner", "label": "List owner", "type": "user", "prefill": "user.me"}
    ]},
    {"id": "points", "title": "Open points", "kind": "table", "min_rows": 0, "columns": [
      {"id": "entry_date", "label": "Entry", "type": "date"},
      {"id": "process", "label": "Process", "type": "text"},
      {"id": "task", "label": "Task", "type": "text", "width": 2},
      {"id": "description", "label": "Description", "type": "multiline", "width": 3},
      {"id": "scope", "label": "Int/Ext", "type": "choice", "options": ["internal", "external"]},
      {"id": "responsible", "label": "Responsible", "type": "user"},
      {"id": "due", "label": "Due", "type": "date"},
      {"id": "status", "label": "Status", "type": "choice", "options": ["on track", "at risk", "overdue", "complete"]},
      {"id": "comments", "label": "Comments / questions", "type": "multiline", "width": 2}
    ], "footer": [
      {"label": "Complete", "expr": "count(status == 'complete')"},
      {"label": "On track", "expr": "count(status == 'on track')"},
      {"label": "At risk", "expr": "count(status == 'at risk')"},
      {"label": "Overdue", "expr": "count(status == 'overdue')"}
    ]}
  ]
}
```

- [ ] **Step 6: `deviation_agreement.json`**

```json
{
  "key": "deviation_agreement", "version": 1, "title": "Project Deviation Agreement",
  "implements": "F-DVS-CORP-011", "cardinality": "multi", "gate_items": false,
  "sep_items": [], "signatures": ["md", "dt", "pm"],
  "required_for_submit": ["reason.reason", "budget"],
  "sections": [
    <<common header block>>,
    {"id": "reason", "title": "Reason", "kind": "fields", "fields": [
      {"id": "reason", "label": "Why is more budget needed", "type": "multiline", "help": "e.g. strategic project"}
    ]},
    {"id": "budget", "title": "Budget deviation", "kind": "table", "min_rows": 1, "columns": [
      {"id": "item", "label": "Description", "type": "text", "width": 2},
      {"id": "budget", "label": "Approved budget", "type": "number", "step": 0.01},
      {"id": "deviation", "label": "Deviation", "type": "number", "step": 0.01},
      {"id": "new_total", "label": "New total", "type": "computed", "expr": "budget + deviation"},
      {"id": "remark", "label": "Remark", "type": "text", "width": 2}
    ], "footer": [{"label": "Total deviation", "expr": "sum(deviation)"}]},
    {"id": "approval", "title": "Approval", "kind": "fields", "fields": [
      {"id": "approved", "label": "Budget increase approved", "type": "checkbox"}
    ]}
  ]
}
```

Replace `<<common header block>>` with the header JSON from the top of this task. `help` on a field is optional descriptive text the renderer shows under the label; the validator ignores unknown keys.

- [ ] **Step 7: Run and commit** (see Task 3 steps 6–7).

---

### Task 4: Prefill and instance service

**Files:**
- Create: `backend/app/forms/prefill.py`
- Create: `backend/app/forms/service.py`
- Test: `backend/tests/test_forms.py` (append)

**Interfaces:**
- Consumes: models (Task 2), `recompute`, `missing_for_submit` (Task 3), `latest_definition`.
- Produces (all async, take `db: AsyncSession`):
  - `build_prefill(db, body, project: Project, user: User) -> dict` — initial `data`.
  - `create_instance(db, project_id, key, user) -> FormInstance` — raises `FormError(409)` for a second `single` instance, `FormError(404)` for unknown key/project.
  - `save_instance(db, inst, data, user, owner_id=None) -> FormInstance` — 409 if `status == "submitted"`.
  - `submit_instance(db, inst, user) -> FormInstance` — 422 with `missing` list if incomplete; flips SEP items.
  - `reopen_instance(db, inst, user) -> FormInstance` — flips items back.
  - `sign_instance(db, inst, role, user) -> FormInstance`.
  - `signatures_state(inst) -> dict[role, {user_id, at} | None]`.
  - `FormError(Exception)` with `.status` and `.detail` (and optional `.extra` dict).
  - `sep_refs(body) -> list[tuple[str,int]]` parse `"K0/RG1:2"`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_forms.py`)

```python
import pytest
from datetime import datetime

from app.forms.loader import load_definitions
from app.forms.service import (
    create_instance, save_instance, submit_instance, reopen_instance, sign_instance,
    signatures_state, FormError,
)
from app.models import User
from app.models.sep import SepWorkItem, SepItemAudit, SepGate


async def _user(session_factory, uid):
    async with session_factory() as s:
        return await s.get(User, uid)


async def _activate_sep(client, auth, project_id):
    res = await client.post(f"/api/v1/sep/projects/{project_id}/activate", headers=auth)
    assert res.status_code == 201, res.text


async def test_create_prefills_and_enforces_single(session_factory, seed, client, eng_auth):
    await _activate_sep(client, eng_auth, seed["project_id"])
    async with session_factory() as s:
        await load_definitions(s)
        await s.commit()
    user = await _user(session_factory, seed["engineer_id"])
    async with session_factory() as s:
        inst = await create_instance(s, seed["project_id"], "risk_assessment", user)
        await s.commit()
        assert inst.status == "draft"
        assert inst.data["header"]["project_no"] == "proj"
        assert inst.data["header"]["project_manager"] == seed["engineer_id"]
        assert len(inst.data["header"]["date"]) == 10
        with pytest.raises(FormError) as ei:
            await create_instance(s, seed["project_id"], "risk_assessment", user)
        assert ei.value.status == 409
        with pytest.raises(FormError) as ei:
            await create_instance(s, seed["project_id"], "nope", user)
        assert ei.value.status == 404
        # multi cardinality allows a second instance
        await create_instance(s, seed["project_id"], "deviation_agreement", user)
        await create_instance(s, seed["project_id"], "deviation_agreement", user)
        await s.commit()


async def test_contact_list_prefills_team_from_sep_responsibles(session_factory, seed, client, eng_auth):
    await _activate_sep(client, eng_auth, seed["project_id"])
    async with session_factory() as s:
        await load_definitions(s)
        item = (await s.execute(select(SepWorkItem).where(SepWorkItem.project_id == seed["project_id"]).limit(1))).scalar_one()
        item.responsible_id = seed["admin_id"]
        await s.commit()
    user = await _user(session_factory, seed["engineer_id"])
    async with session_factory() as s:
        inst = await create_instance(s, seed["project_id"], "contact_list", user)
        assert [r["name"] for r in inst.data["contacts"]] == ["Admin"]
        assert inst.data["contacts"][0]["email"] == "admin@test.io"


async def test_save_recomputes_and_records_diff(session_factory, seed, client, eng_auth):
    await _activate_sep(client, eng_auth, seed["project_id"])
    async with session_factory() as s:
        await load_definitions(s); await s.commit()
    user = await _user(session_factory, seed["engineer_id"])
    async with session_factory() as s:
        inst = await create_instance(s, seed["project_id"], "risk_assessment", user)
        data = dict(inst.data)
        data["risks"] = [{"gate": "K0/RG1", "risk": "Late tooling", "q": 0.5, "c": 0.5, "s": 1, "p": 1, "status": "open"}]
        inst = await save_instance(s, inst, data, user)
        await s.commit()
        assert inst.data["risks"][0]["rkz"] == pytest.approx(2.0)
        assert inst.data["risks"][0]["priority"] == "very_high"
        assert inst.data["risks_footer"]["Open"] == 1
        ev = [e for e in inst.events if e.event == "saved"][-1]
        assert "risks" in ev.diff


async def test_submit_flips_linked_items_and_reopen_restores(session_factory, seed, client, eng_auth):
    await _activate_sep(client, eng_auth, seed["project_id"])
    async with session_factory() as s:
        await load_definitions(s); await s.commit()
    user = await _user(session_factory, seed["engineer_id"])
    async with session_factory() as s:
        inst = await create_instance(s, seed["project_id"], "project_legitimization", user)
        with pytest.raises(FormError) as ei:
            await submit_instance(s, inst, user)
        assert ei.value.status == 422 and "budget" in ei.value.extra["missing"]
        data = dict(inst.data)
        data["header"]["project_title"] = "P"
        data["budget"] = [{"item": "Tooling", "budget": 1000}]
        inst = await save_instance(s, inst, data, user)
        # one linked item is not_applicable: must stay untouched
        na_item = (await s.execute(select(SepWorkItem).join(SepGate).where(
            SepWorkItem.project_id == seed["project_id"], SepGate.code == "K/RG2", SepWorkItem.item_no == 7))).scalar_one()
        na_item.status = "not_applicable"
        await s.flush()
        inst = await submit_instance(s, inst, user)
        await s.commit()
        assert inst.status == "submitted" and inst.submitted_by == user.id
        k0 = (await s.execute(select(SepWorkItem).join(SepGate).where(
            SepWorkItem.project_id == seed["project_id"], SepGate.code == "K0/RG1", SepWorkItem.item_no == 39))).scalar_one()
        assert k0.status == "done" and k0.remark == "via form Project Legitimization"
        await s.refresh(na_item)
        assert na_item.status == "not_applicable"
        audits = (await s.execute(select(SepItemAudit).where(SepItemAudit.item_id == k0.id))).scalars().all()
        assert audits[-1].new_value == "done" and audits[-1].user_id == user.id
        # saving a submitted form is refused
        with pytest.raises(FormError) as ei:
            await save_instance(s, inst, data, user)
        assert ei.value.status == 409
        inst = await reopen_instance(s, inst, user)
        await s.commit()
        await s.refresh(k0)
        assert inst.status == "reopened" and k0.status == "open"


async def test_submit_does_not_touch_closed_gate_items(session_factory, seed, client, eng_auth):
    await _activate_sep(client, eng_auth, seed["project_id"])
    async with session_factory() as s:
        await load_definitions(s)
        gate = (await s.execute(select(SepGate).where(SepGate.project_id == seed["project_id"], SepGate.code == "K0/RG1"))).scalar_one()
        gate.status = "closed"
        await s.commit()
    user = await _user(session_factory, seed["engineer_id"])
    async with session_factory() as s:
        inst = await create_instance(s, seed["project_id"], "risk_assessment", user)
        inst = await submit_instance(s, inst, user)
        await s.commit()
        k0 = (await s.execute(select(SepWorkItem).join(SepGate).where(
            SepWorkItem.project_id == seed["project_id"], SepGate.code == "K0/RG1", SepWorkItem.item_no == 2))).scalar_one()
        assert k0.status == "open"


async def test_signatures_four_eyes(session_factory, seed, client, eng_auth):
    await _activate_sep(client, eng_auth, seed["project_id"])
    async with session_factory() as s:
        await load_definitions(s); await s.commit()
    eng = await _user(session_factory, seed["engineer_id"])
    adm = await _user(session_factory, seed["admin_id"])
    async with session_factory() as s:
        inst = await create_instance(s, seed["project_id"], "project_legitimization", eng)
        data = dict(inst.data); data["header"]["project_title"] = "P"; data["budget"] = [{"item": "Tooling", "budget": 1}]
        inst = await save_instance(s, inst, data, eng)
        inst = await submit_instance(s, inst, eng)
        with pytest.raises(FormError):
            await sign_instance(s, inst, "quality", eng)  # role not in definition
        inst = await sign_instance(s, inst, "pm", eng)
        with pytest.raises(FormError):
            await sign_instance(s, inst, "md", eng)  # same user, second role
        with pytest.raises(FormError):
            await sign_instance(s, inst, "pm", adm)  # already signed
        inst = await sign_instance(s, inst, "md", adm)
        await s.commit()
        state = signatures_state(inst)
        assert state["pm"]["user_id"] == eng.id and state["md"]["user_id"] == adm.id
        # reopen invalidates signatures
        inst = await reopen_instance(s, inst, eng)
        assert signatures_state(inst) == {"md": None, "pm": None}
```

- [ ] **Step 2: Run to verify failure** → ImportError on `app.forms.service`.

- [ ] **Step 3: Implement `prefill.py`**

```python
"""Initial data for a new form instance from project / user context."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Project, Plant
from app.models.sep import SepWorkItem


async def _team_rows(db: AsyncSession, project_id: int) -> list[dict]:
    uids = [u for (u,) in (await db.execute(
        select(SepWorkItem.responsible_id).where(
            SepWorkItem.project_id == project_id, SepWorkItem.responsible_id.isnot(None)
        ).distinct())).all()]
    if not uids:
        return []
    users = (await db.execute(select(User).where(User.id.in_(uids)).order_by(User.full_name))).scalars().all()
    return [{"name": u.full_name, "department": "", "position": "", "phone": "", "email": u.email, "external": False}
            for u in users]


async def build_prefill(db: AsyncSession, body: dict, project: Project, user: User) -> dict:
    plant = await db.get(Plant, project.plant_id)
    scalars = {
        "project.code": project.code,
        "project.name": project.name,
        "project.plant": plant.name if plant else "",
        "user.me": user.id,
        "user.me_name": user.full_name,
        "date.today": date.today().isoformat(),
    }
    data: dict = {}
    for s in body["sections"]:
        if s["kind"] == "fields":
            data[s["id"]] = {f["id"]: scalars.get(f["prefill"]) for f in s["fields"] if f.get("prefill")}
        else:
            data[s["id"]] = await _team_rows(db, project.id) if s.get("prefill") == "team.members" else []
    return data
```

Check `Plant` is exported from `app.models` (it is used in `tests/conftest.py`).

- [ ] **Step 4: Implement `service.py`**

```python
"""Form instance lifecycle and SEP item linking."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.forms.compute import recompute
from app.forms.loader import latest_definition
from app.forms.prefill import build_prefill
from app.forms.validate import missing_for_submit
from app.models import User, Project
from app.models.forms import FormInstance, FormEvent, FormDefinition
from app.models.sep import SepWorkItem, SepGate, SepItemAudit


class FormError(Exception):
    def __init__(self, status: int, detail: str, extra: dict | None = None):
        super().__init__(detail)
        self.status, self.detail, self.extra = status, detail, extra or {}


def sep_refs(body: dict) -> list[tuple[str, int]]:
    out = []
    for ref in body.get("sep_items", []):
        code, _, no = ref.rpartition(":")
        out.append((code, int(no)))
    return out


async def load_instance(db: AsyncSession, instance_id: int) -> FormInstance:
    inst = (await db.execute(
        select(FormInstance).options(selectinload(FormInstance.events), selectinload(FormInstance.definition))
        .where(FormInstance.id == instance_id))).scalar_one_or_none()
    if not inst:
        raise FormError(404, "Form instance not found")
    return inst


async def create_instance(db: AsyncSession, project_id: int, key: str, user: User) -> FormInstance:
    project = await db.get(Project, project_id)
    if not project:
        raise FormError(404, "Project not found")
    definition = await latest_definition(db, key)
    if not definition:
        raise FormError(404, f"Unknown form {key}")
    if definition.cardinality == "single":
        exists = (await db.execute(
            select(FormInstance.id).join(FormDefinition).where(
                FormInstance.project_id == project_id, FormDefinition.key == key).limit(1))).scalar_one_or_none()
        if exists:
            raise FormError(409, f"{definition.title} already exists for this project", {"instance_id": exists})
    data = recompute(definition.body, await build_prefill(db, definition.body, project, user))
    inst = FormInstance(project_id=project_id, definition_id=definition.id, status="draft", data=data,
                        owner_id=user.id, created_by=user.id, updated_by=user.id)
    db.add(inst)
    await db.flush()
    db.add(FormEvent(instance_id=inst.id, user_id=user.id, event="created"))
    await db.flush()
    return await load_instance(db, inst.id)


def _diff(old: dict, new: dict, prefix: str = "") -> dict:
    out = {}
    keys = set(old) | set(new)
    for k in keys:
        if k.endswith("_footer"):
            continue
        a, b = old.get(k), new.get(k)
        path = f"{prefix}{k}"
        if isinstance(a, dict) and isinstance(b, dict):
            out.update(_diff(a, b, path + "."))
        elif a != b:
            out[path] = [a, b]
    return out


async def save_instance(db: AsyncSession, inst: FormInstance, data: dict, user: User,
                        owner_id: int | None = None) -> FormInstance:
    if inst.status == "submitted":
        raise FormError(409, "Form is submitted; reopen it to edit")
    new = recompute(inst.definition.body, data)
    diff = _diff(inst.data or {}, new)
    if owner_id is not None and owner_id != inst.owner_id:
        diff["owner_id"] = [inst.owner_id, owner_id]
        inst.owner_id = owner_id
    inst.data = new
    inst.updated_by = user.id
    inst.updated_at = datetime.utcnow()
    db.add(FormEvent(instance_id=inst.id, user_id=user.id, event="saved", diff=diff))
    await db.flush()
    return await load_instance(db, inst.id)


async def _linked_items(db: AsyncSession, inst: FormInstance) -> list[tuple[SepWorkItem, SepGate]]:
    refs = sep_refs(inst.definition.body)
    if not refs:
        return []
    rows = (await db.execute(
        select(SepWorkItem, SepGate).join(SepGate, SepWorkItem.gate_id == SepGate.id)
        .where(SepWorkItem.project_id == inst.project_id))).all()
    return [(i, g) for i, g in rows if (g.code, i.item_no) in refs]


def _audit(item: SepWorkItem, user_id: int, old: str, new: str) -> SepItemAudit:
    return SepItemAudit(item_id=item.id, user_id=user_id, field="status", old_value=old, new_value=new)


async def submit_instance(db: AsyncSession, inst: FormInstance, user: User) -> FormInstance:
    if inst.status == "submitted":
        raise FormError(409, "Form already submitted")
    missing = missing_for_submit(inst.definition.body, inst.data or {})
    if missing:
        raise FormError(422, "Form is incomplete", {"missing": missing})
    title = inst.definition.title
    for item, gate in await _linked_items(db, inst):
        if gate.status == "closed" or item.status != "open":
            continue
        db.add(_audit(item, user.id, "open", "done"))
        item.status = "done"
        item.completed_at = datetime.utcnow()
        if not item.remark:
            item.remark = f"via form {title}"
    inst.status = "submitted"
    inst.submitted_by = user.id
    inst.submitted_at = datetime.utcnow()
    db.add(FormEvent(instance_id=inst.id, user_id=user.id, event="submitted"))
    await db.flush()
    return await load_instance(db, inst.id)


async def reopen_instance(db: AsyncSession, inst: FormInstance, user: User) -> FormInstance:
    if inst.status != "submitted":
        raise FormError(409, "Only submitted forms can be reopened")
    title = inst.definition.title
    for item, gate in await _linked_items(db, inst):
        if gate.status == "closed" or item.status != "done" or item.remark != f"via form {title}":
            continue
        db.add(_audit(item, user.id, "done", "open"))
        item.status = "open"
        item.completed_at = None
    inst.status = "reopened"
    db.add(FormEvent(instance_id=inst.id, user_id=user.id, event="reopened"))
    await db.flush()
    return await load_instance(db, inst.id)


def _events_since_submit(inst: FormInstance) -> list[FormEvent]:
    idx = 0
    for i, e in enumerate(inst.events):
        if e.event in ("submitted", "reopened"):
            idx = i
    return inst.events[idx:]


def signatures_state(inst: FormInstance) -> dict:
    roles = inst.definition.body.get("signatures", [])
    state = {r: None for r in roles}
    if inst.status != "submitted":
        return state
    for e in _events_since_submit(inst):
        if e.event == "signed" and e.role in state:
            state[e.role] = {"user_id": e.user_id, "at": e.created_at.isoformat()}
    return state


async def sign_instance(db: AsyncSession, inst: FormInstance, role: str, user: User) -> FormInstance:
    roles = inst.definition.body.get("signatures", [])
    if role not in roles:
        raise FormError(400, f"Role must be one of: {', '.join(roles) or 'none'}")
    if inst.status != "submitted":
        raise FormError(409, "Form must be submitted before signing")
    state = signatures_state(inst)
    if state[role]:
        raise FormError(409, f"{role.upper()} has already signed")
    if any(s and s["user_id"] == user.id for s in state.values()):
        raise FormError(409, "Each role must be signed by a different user")
    db.add(FormEvent(instance_id=inst.id, user_id=user.id, event="signed", role=role))
    await db.flush()
    return await load_instance(db, inst.id)
```

Note the reopen rule: only items whose remark still says `via form <title>` flip back, so an item someone ticked done by hand (different remark) stays done. Add this sentence to the spec's SEP link paragraph when the task is done.

- [ ] **Step 5: Run tests** → `python -m pytest tests/test_forms.py -q` PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/forms/prefill.py backend/app/forms/service.py backend/tests/test_forms.py
git commit -m "feat(forms): prefill and instance lifecycle service with SEP item linking"
```

---

### Task 5: `/v1/forms` router, startup loader, SEP payload enrichment

**Files:**
- Create: `backend/app/api/v1/timing/forms.py`
- Modify: `backend/app/api/v1/__init__.py` (import + include next to `sep_router`, lines 36 and 63)
- Modify: `backend/app/main.py` (call loader in `lifespan` right after `await seed_test_data()` on line 431, and also when not in debug)
- Modify: `backend/app/api/v1/timing/sep.py` (`_item_dict` gains `form` and `references`; `get_project_sep` collects them)
- Create: `backend/app/data/sep_references.json`
- Test: `backend/tests/test_forms.py` (append API tests)

**Interfaces:**
- Consumes: service functions from Task 4.
- Produces HTTP API per spec section 5. Instance JSON shape:
  ```
  {id, project_id, key, title, version, implements, cardinality, status, data, owner_id, owner_name,
   created_by, created_at, updated_by, updated_at, submitted_by, submitted_by_name, submitted_at,
   signatures: {role: {user_id, user_name, at} | null}, references: [{title, path}],
   sep_items: ["K0/RG1:2"], definition: <body> (only on GET /instances/{id}),
   events: [{id, user_id, user_name, event, role, diff, created_at}] (only on GET /instances/{id})}
  ```
- Also produces `app.forms.service.instances_for_project(db, project_id) -> list[FormInstance]` and `form_info_by_ref(db, project_id) -> dict[str, dict]` mapping `"K0/RG1:2"` → `{key, title, instance_id|None, status|None}` (used by the SEP router).

- [ ] **Step 1: Write the failing API tests** (append to `tests/test_forms.py`)

```python
async def _seed_defs(session_factory):
    async with session_factory() as s:
        await load_definitions(s); await s.commit()


async def test_api_lifecycle(client, eng_auth, admin_auth, seed, session_factory):
    await _activate_sep(client, eng_auth, seed["project_id"])
    await _seed_defs(session_factory)
    res = await client.get("/api/v1/forms/definitions", headers=eng_auth)
    assert res.status_code == 200 and {d["key"] for d in res.json()} >= {"risk_assessment", "lop"}

    res = await client.post(f"/api/v1/forms/projects/{seed['project_id']}/instances", json={"key": "project_legitimization"}, headers=eng_auth)
    assert res.status_code == 201, res.text
    inst = res.json()
    assert inst["status"] == "draft" and inst["data"]["header"]["project_no"] == "proj"
    res = await client.post(f"/api/v1/forms/projects/{seed['project_id']}/instances", json={"key": "project_legitimization"}, headers=eng_auth)
    assert res.status_code == 409

    res = await client.get(f"/api/v1/forms/instances/{inst['id']}", headers=eng_auth)
    assert res.status_code == 200 and res.json()["definition"]["key"] == "project_legitimization"
    assert [e["event"] for e in res.json()["events"]] == ["created"]

    res = await client.post(f"/api/v1/forms/instances/{inst['id']}/submit", headers=eng_auth)
    assert res.status_code == 422 and "budget" in res.json()["detail"]["missing"]

    data = inst["data"]; data["header"]["project_title"] = "P"; data["budget"] = [{"item": "Tooling", "budget": 5}]
    res = await client.patch(f"/api/v1/forms/instances/{inst['id']}", json={"data": data}, headers=eng_auth)
    assert res.status_code == 200 and res.json()["data"]["budget_footer"]["Total budget"] == 5

    res = await client.post(f"/api/v1/forms/instances/{inst['id']}/submit", headers=eng_auth)
    assert res.status_code == 200 and res.json()["status"] == "submitted"
    assert res.json()["signatures"] == {"md": None, "pm": None}

    res = await client.post(f"/api/v1/forms/instances/{inst['id']}/sign", json={"role": "pm"}, headers=eng_auth)
    assert res.status_code == 200 and res.json()["signatures"]["pm"]["user_name"] == "Engineer"
    res = await client.post(f"/api/v1/forms/instances/{inst['id']}/sign", json={"role": "md"}, headers=eng_auth)
    assert res.status_code == 409
    res = await client.post(f"/api/v1/forms/instances/{inst['id']}/sign", json={"role": "md"}, headers=admin_auth)
    assert res.status_code == 200

    # SEP payload shows the form on its items
    sep = (await client.get(f"/api/v1/sep/projects/{seed['project_id']}", headers=eng_auth)).json()
    k0 = next(g for g in sep["gates"] if g["code"] == "K0/RG1")
    item39 = next(i for i in k0["items"] if i["item_no"] == 39)
    assert item39["form"] == {"key": "project_legitimization", "title": "Project Legitimization",
                              "instance_id": inst["id"], "status": "submitted"}
    assert item39["status"] == "done"
    item2 = next(i for i in k0["items"] if i["item_no"] == 2)
    assert item2["form"]["key"] == "risk_assessment" and item2["form"]["instance_id"] is None

    res = await client.post(f"/api/v1/forms/instances/{inst['id']}/reopen", headers=admin_auth)
    assert res.status_code == 200 and res.json()["status"] == "reopened"

    res = await client.get(f"/api/v1/forms/projects/{seed['project_id']}", headers=eng_auth)
    assert res.status_code == 200
    groups = {g["key"]: g for g in res.json()}
    assert groups["project_legitimization"]["instances"][0]["status"] == "reopened"
    assert groups["lop"]["instances"] == [] and groups["lop"]["cardinality"] == "single"


async def test_my_forms(client, eng_auth, admin_auth, seed, session_factory):
    await _activate_sep(client, eng_auth, seed["project_id"])
    await _seed_defs(session_factory)
    res = await client.post(f"/api/v1/forms/projects/{seed['project_id']}/instances", json={"key": "lop"}, headers=eng_auth)
    assert res.status_code == 201
    mine = (await client.get("/api/v1/forms/my-forms", headers=eng_auth)).json()
    assert [m["key"] for m in mine] == ["lop"] and mine[0]["reason"] == "draft"
    assert (await client.get("/api/v1/forms/my-forms", headers=admin_auth)).json() == []


async def test_sep_references_on_items(client, eng_auth, seed):
    await _activate_sep(client, eng_auth, seed["project_id"])
    sep = (await client.get(f"/api/v1/sep/projects/{seed['project_id']}", headers=eng_auth)).json()
    k2 = next(g for g in sep["gates"] if g["code"] == "K/RG2")
    item10 = next(i for i in k2["items"] if i["item_no"] == 10)
    assert any(r["title"].startswith("Process description") for r in item10["references"])
```

- [ ] **Step 2: Run to verify failure** → 404s on `/api/v1/forms/...`.

- [ ] **Step 3: Add `instances_for_project` and `form_info_by_ref` to `service.py`**

```python
async def instances_for_project(db: AsyncSession, project_id: int) -> list[FormInstance]:
    return list((await db.execute(
        select(FormInstance).options(selectinload(FormInstance.definition), selectinload(FormInstance.events))
        .where(FormInstance.project_id == project_id).order_by(FormInstance.id))).scalars().all())


async def form_info_by_ref(db: AsyncSession, project_id: int) -> dict[str, dict]:
    """'K0/RG1:2' -> {key, title, instance_id, status} using the latest definition per key
    and the newest instance per key (single forms have at most one)."""
    from app.forms.loader import latest_definitions
    latest = await latest_definitions(db)
    insts = await instances_for_project(db, project_id)
    newest: dict[str, FormInstance] = {}
    for i in insts:
        newest[i.definition.key] = i
    out: dict[str, dict] = {}
    for d in latest:
        inst = newest.get(d.key)
        for ref in d.body.get("sep_items", []):
            out[ref] = {"key": d.key, "title": d.title,
                        "instance_id": inst.id if inst else None,
                        "status": inst.status if inst else None}
    return out
```

- [ ] **Step 4: Write the router**

`backend/app/api/v1/timing/forms.py`:
```python
"""SEP forms engine endpoints (/v1/forms)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User, Project
from app.forms.loader import latest_definitions, latest_definition
from app.forms import service as svc
from app.forms.service import FormError

router = APIRouter(prefix="/forms", tags=["forms"])


class CreateBody(BaseModel):
    key: str


class SaveBody(BaseModel):
    data: dict
    owner_id: Optional[int] = None


class SignBody(BaseModel):
    role: str


def _raise(e: FormError) -> None:
    detail = {"message": e.detail, **e.extra} if e.extra else e.detail
    raise HTTPException(status_code=e.status, detail=detail)


async def _names(db: AsyncSession, ids: set[int | None]) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.full_name).where(User.id.in_(ids)))).all()
    return {i: n for i, n in rows}


def _def_dict(d) -> dict:
    return {"key": d.key, "version": d.version, "title": d.title, "implements": d.implements,
            "cardinality": d.cardinality, "gate_items": d.gate_items,
            "sep_items": d.body.get("sep_items", []), "signatures": d.body.get("signatures", [])}


async def _inst_dict(db: AsyncSession, inst, full: bool = False) -> dict:
    d = inst.definition
    sigs = svc.signatures_state(inst)
    names = await _names(db, {inst.owner_id, inst.submitted_by, inst.updated_by}
                         | {s["user_id"] for s in sigs.values() if s} | {e.user_id for e in inst.events})
    out = {
        "id": inst.id, "project_id": inst.project_id, "key": d.key, "title": d.title, "version": d.version,
        "implements": d.implements, "cardinality": d.cardinality, "status": inst.status, "data": inst.data,
        "owner_id": inst.owner_id, "owner_name": names.get(inst.owner_id),
        "created_by": inst.created_by, "created_at": inst.created_at.isoformat(),
        "updated_by": inst.updated_by, "updated_by_name": names.get(inst.updated_by), "updated_at": inst.updated_at.isoformat(),
        "submitted_by": inst.submitted_by, "submitted_by_name": names.get(inst.submitted_by),
        "submitted_at": inst.submitted_at.isoformat() if inst.submitted_at else None,
        "signatures": {r: ({**s, "user_name": names.get(s["user_id"])} if s else None) for r, s in sigs.items()},
        "references": d.body.get("references", []), "sep_items": d.body.get("sep_items", []),
    }
    if full:
        out["definition"] = d.body
        out["events"] = [{"id": e.id, "user_id": e.user_id, "user_name": names.get(e.user_id), "event": e.event,
                          "role": e.role, "diff": e.diff, "created_at": e.created_at.isoformat()} for e in inst.events]
    return out


@router.get("/definitions", response_model=list[dict])
async def list_definitions(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return [_def_dict(d) for d in await latest_definitions(db)]


@router.get("/definitions/{key}", response_model=dict)
async def get_definition(key: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    d = await latest_definition(db, key)
    if not d:
        raise HTTPException(status_code=404, detail="Unknown form")
    return {**_def_dict(d), "body": d.body}


@router.get("/projects/{project_id}", response_model=list[dict])
async def project_forms(project_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    insts = await svc.instances_for_project(db, project_id)
    groups = []
    for d in await latest_definitions(db):
        mine = [await _inst_dict(db, i) for i in insts if i.definition.key == d.key]
        groups.append({**_def_dict(d), "instances": mine})
    return groups


@router.post("/projects/{project_id}/instances", response_model=dict, status_code=201)
async def create_instance(project_id: int, body: CreateBody,
                          current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        inst = await svc.create_instance(db, project_id, body.key, current_user)
    except FormError as e:
        _raise(e)
    await db.commit()
    return await _inst_dict(db, await svc.load_instance(db, inst.id), full=True)


@router.get("/instances/{instance_id}", response_model=dict)
async def get_instance(instance_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        inst = await svc.load_instance(db, instance_id)
    except FormError as e:
        _raise(e)
    return await _inst_dict(db, inst, full=True)


async def _mutate(db, instance_id, fn, *args):
    try:
        inst = await svc.load_instance(db, instance_id)
        inst = await fn(db, inst, *args)
    except FormError as e:
        _raise(e)
    await db.commit()
    return await _inst_dict(db, await svc.load_instance(db, inst.id), full=True)


@router.patch("/instances/{instance_id}", response_model=dict)
async def save_instance(instance_id: int, body: SaveBody,
                        current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _mutate(db, instance_id, lambda d, i, data, user: svc.save_instance(d, i, data, user, body.owner_id),
                         body.data, current_user)


@router.post("/instances/{instance_id}/submit", response_model=dict)
async def submit(instance_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _mutate(db, instance_id, svc.submit_instance, current_user)


@router.post("/instances/{instance_id}/reopen", response_model=dict)
async def reopen(instance_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _mutate(db, instance_id, svc.reopen_instance, current_user)


@router.post("/instances/{instance_id}/sign", response_model=dict)
async def sign(instance_id: int, body: SignBody,
               current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _mutate(db, instance_id, lambda d, i, user: svc.sign_instance(d, i, body.role.lower().strip(), user),
                         current_user)


@router.get("/my-forms", response_model=list[dict])
async def my_forms(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Drafts I own, plus submitted forms still missing a signature (anyone can sign, so shown to all)."""
    from sqlalchemy.orm import selectinload
    from app.models.forms import FormInstance
    rows = (await db.execute(
        select(FormInstance, Project).join(Project, FormInstance.project_id == Project.id)
        .options(selectinload(FormInstance.definition), selectinload(FormInstance.events))
        .where(FormInstance.status != "submitted", FormInstance.owner_id == current_user.id)
        .order_by(FormInstance.updated_at.desc()))).all()
    out = []
    for inst, project in rows:
        out.append({"id": inst.id, "key": inst.definition.key, "title": inst.definition.title, "status": inst.status,
                    "reason": "draft", "project_id": project.id, "project_name": project.name,
                    "updated_at": inst.updated_at.isoformat()})
    return out
```

Register in `backend/app/api/v1/__init__.py`:
```python
from app.api.v1.timing.forms import router as forms_router
...
api_router.include_router(forms_router)
```

The `reopen` permission rule ("project manager or owner") cannot be enforced because the project has no manager field; any authenticated user may reopen for now. Record that in the spec section 5 when done.

- [ ] **Step 5: Startup loader in `main.py`**

Inside `lifespan`, immediately after the `await seed_test_data()` call (and outside the debug guard if there is one), add:
```python
    from app.models import AsyncSessionLocal
    from app.forms.loader import load_definitions
    async with AsyncSessionLocal() as session:
        try:
            await load_definitions(session)
            await session.commit()
        except Exception as e:  # never block startup on a bad definition file
            logger.error(f"Form definitions not loaded: {e}")
            await session.rollback()
```

- [ ] **Step 6: SEP payload: form info and references**

`backend/app/data/sep_references.json`:
```json
{
  "K/RG2:10": [
    {"title": "Process description: Sales handover and kick-off", "path": "Documents/SEP/global-forms/Manual_1_Process-description_Sales_Handover_KICK-OFF.pdf"}
  ],
  "K/RG2:11": [
    {"title": "Work package template: Central tool management", "path": "Documents/SEP/global-forms/F_DVS_CORP_007_Template_WP_Central_Tool_Management.doc"},
    {"title": "Work package template: Industrial engineering", "path": "Documents/SEP/global-forms/F_DVS_CORP_008_Template_WP_Industrial_Engineering.doc"},
    {"title": "Work package template: APQP", "path": "Documents/SEP/global-forms/F_DVS_CORP_009_Template_WP_APQP.docx"}
  ],
  "K/RG2:18": [
    {"title": "Technical specification industrialization", "path": "Documents/SEP/global-forms/F_DVS-CORP-014_Technical_Spezification_Industrialization.docx"}
  ]
}
```

In `sep.py`: add near the top
```python
REFERENCES_PATH = Path(__file__).resolve().parents[3] / "data" / "sep_references.json"
_REFERENCES: dict[str, list[dict]] = json.loads(REFERENCES_PATH.read_text()) if REFERENCES_PATH.exists() else {}
```
Change `_item_dict(i, names)` to `_item_dict(i, names, gate_code: str | None = None, forms: dict | None = None)` and add to the dict:
```python
        "form": (forms or {}).get(f"{gate_code}:{i.item_no}"),
        "references": _REFERENCES.get(f"{gate_code}:{i.item_no}", []),
```
Change `_gate_dict(g, names, with_details=True, forms=None)` so `d["items"] = [_item_dict(i, names, g.code, forms) for i in g.items]`. In `get_project_sep` compute `forms = await form_info_by_ref(db, project_id)` (import from `app.forms.service`) and pass it into `_gate_dict`. Every other `_gate_dict` call keeps its defaults (`form` is `None` there).

- [ ] **Step 7: Run all backend tests** → `python -m pytest tests -q` PASS (SEP tests included).

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/v1/timing/forms.py backend/app/api/v1/__init__.py backend/app/main.py backend/app/api/v1/timing/sep.py backend/app/data/sep_references.json backend/app/forms/service.py backend/tests/test_forms.py
git commit -m "feat(forms): /v1/forms API, startup loader, SEP items expose form and references"
```

---

### Task 6: Gate colour and sign-off read risks from the form; risk data migration

**Files:**
- Modify: `backend/app/api/v1/timing/sep.py` (`_gate_color`, `_gate_dict` `open_risks`, `sign_off_gate` risk checks, `get_project_sep`, `sep_overview`, `get_rollup` where they build gate dicts)
- Modify: `backend/alembic/versions/065_sep_forms.py` (data step)
- Create: `backend/app/forms/risks.py`
- Test: `backend/tests/test_sep.py` (adjust the yellow-gate tests), `backend/tests/test_forms.py` (append migration test)

**Interfaces:**
- Produces: `app.forms.risks.risk_rows_by_gate(db, project_id) -> dict[str, list[dict]]` — rows of the project's newest `risk_assessment` instance grouped by `gate` code (rows without a gate go under `""`). Each row has `rkz`, `priority`, `status`, `countermeasure`, `responsible`, `due` as stored.
- Produces: `migrate_sep_risks(connection)` (sync, used by Alembic) and `copy_sep_risks_to_forms(session)` (async, for tests).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_forms.py`:
```python
from app.forms.risks import risk_rows_by_gate, copy_sep_risks_to_forms
from app.models.sep import SepRisk


async def test_gate_color_and_signoff_use_form_risks(client, eng_auth, admin_auth, seed, session_factory):
    await _activate_sep(client, eng_auth, seed["project_id"])
    await _seed_defs(session_factory)
    res = await client.post(f"/api/v1/forms/projects/{seed['project_id']}/instances", json={"key": "risk_assessment"}, headers=eng_auth)
    inst = res.json()
    data = inst["data"]
    data["risks"] = [{"gate": "K0/RG1", "risk": "x", "q": 1, "c": 1, "s": 1, "p": 1, "status": "open"}]
    await client.patch(f"/api/v1/forms/instances/{inst['id']}", json={"data": data}, headers=eng_auth)
    sep = (await client.get(f"/api/v1/sep/projects/{seed['project_id']}", headers=eng_auth)).json()
    k0 = sep["gates"][0]
    assert k0["color"] == "red" and k0["open_risks"] == 1
    # sign-off blocked: incomplete action plan
    res = await client.post(f"/api/v1/sep/gates/{k0['id']}/sign-off", json={"role": "pm"}, headers=eng_auth)
    assert res.status_code == 409 and "countermeasure" in res.text
    # complete the plan within 14 days, then PM sign-off passes
    from datetime import date, timedelta
    data["risks"][0].update({"countermeasure": "fix", "responsible": seed["admin_id"],
                             "due": (date.today() + timedelta(days=3)).isoformat()})
    await client.patch(f"/api/v1/forms/instances/{inst['id']}", json={"data": data}, headers=eng_auth)
    res = await client.post(f"/api/v1/sep/gates/{k0['id']}/sign-off", json={"role": "pm"}, headers=eng_auth)
    assert res.status_code == 200, res.text


async def test_copy_sep_risks_to_forms(session_factory, seed, client, eng_auth):
    await _activate_sep(client, eng_auth, seed["project_id"])
    await _seed_defs(session_factory)
    async with session_factory() as s:
        gate = (await s.execute(select(SepGate).where(SepGate.project_id == seed["project_id"], SepGate.seq == 1))).scalar_one()
        s.add(SepRisk(gate_id=gate.id, project_id=seed["project_id"], effect="Old risk", q_impact=0.5, c_impact=0.5,
                      s_impact=0, probability=1, countermeasure="do it", responsible_id=seed["admin_id"],
                      status="started", created_by=seed["admin_id"]))
        await s.commit()
    async with session_factory() as s:
        n = await copy_sep_risks_to_forms(s)
        await s.commit()
        assert n == 1
        rows = await risk_rows_by_gate(s, seed["project_id"])
        r = rows["K0/RG1"][0]
        assert r["risk"] == "Old risk" and r["rkz"] == pytest.approx(1.0) and r["priority"] == "high"
        assert r["status"] == "started" and r["responsible"] == seed["admin_id"]
        # idempotent
        assert await copy_sep_risks_to_forms(s) == 0
```

- [ ] **Step 2: Run to verify failure** → ImportError `app.forms.risks`.

- [ ] **Step 3: Implement `risks.py`**

```python
"""Risk rows of the risk_assessment form, and the one-off copy from sep_risks."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.forms.compute import recompute
from app.models.forms import FormInstance, FormDefinition, FormEvent
from app.models.sep import SepRisk, SepGate

KEY = "risk_assessment"
MIGRATED_MARK = "migrated_from_sep_risk"


async def _newest_instance(db: AsyncSession, project_id: int) -> FormInstance | None:
    return (await db.execute(
        select(FormInstance).join(FormDefinition).options(selectinload(FormInstance.definition))
        .where(FormInstance.project_id == project_id, FormDefinition.key == KEY)
        .order_by(FormInstance.id.desc()).limit(1))).scalar_one_or_none()


async def risk_rows_by_gate(db: AsyncSession, project_id: int) -> dict[str, list[dict]]:
    inst = await _newest_instance(db, project_id)
    out: dict[str, list[dict]] = {}
    if not inst:
        return out
    for row in (inst.data or {}).get("risks") or []:
        out.setdefault(row.get("gate") or "", []).append(row)
    return out


async def copy_sep_risks_to_forms(db: AsyncSession) -> int:
    """Create a risk_assessment instance per SEP project and append sep_risks rows not yet copied."""
    from app.forms.loader import latest_definition
    from app.models import Project, User
    definition = await latest_definition(db, KEY)
    if not definition:
        return 0
    copied = 0
    project_ids = [p for (p,) in (await db.execute(select(SepGate.project_id).distinct())).all()]
    for pid in project_ids:
        risks = (await db.execute(select(SepRisk, SepGate).join(SepGate, SepRisk.gate_id == SepGate.id)
                                  .where(SepRisk.project_id == pid).order_by(SepRisk.id))).all()
        inst = await _newest_instance(db, pid)
        if not inst and not risks:
            continue
        if not inst:
            actor = risks[0][0].created_by
            project = await db.get(Project, pid)
            inst = FormInstance(project_id=pid, definition_id=definition.id, status="draft",
                                data={"header": {"project_no": project.code, "project_title": project.name}, "risks": []},
                                owner_id=actor, created_by=actor, updated_by=actor)
            db.add(inst)
            await db.flush()
            db.add(FormEvent(instance_id=inst.id, user_id=actor, event="created"))
        data = dict(inst.data or {})
        rows = list(data.get("risks") or [])
        seen = {r.get(MIGRATED_MARK) for r in rows}
        for risk, gate in risks:
            if risk.id in seen:
                continue
            rows.append({
                MIGRATED_MARK: risk.id, "gate": gate.code, "risk": risk.effect, "impact": "",
                "q": risk.q_impact, "c": risk.c_impact, "s": risk.s_impact, "p": risk.probability,
                "countermeasure": risk.countermeasure, "responsible": risk.responsible_id,
                "due": risk.due_date.date().isoformat() if risk.due_date else None, "status": risk.status,
            })
            copied += 1
        data["risks"] = rows
        inst.data = recompute(definition.body, data)
    await db.flush()
    return copied
```

- [ ] **Step 4: Switch `sep.py` to form risks**

Replace `_gate_color(gate)` with a version that takes the rows:
```python
def _gate_color(gate: SepGate, risk_rows: list[dict] | None = None) -> str:
    """GREEN = no open items; YELLOW = open items; RED = high/very-high risk live (from the risk form)."""
    if gate.status == "closed":
        return "green"
    if any(r.get("status") != "finished" and r.get("priority") in ("high", "very_high") for r in (risk_rows or [])):
        return "red"
    if any(i.status == "open" for i in gate.items):
        return "yellow"
    return "green"
```
`_gate_dict(g, names, with_details=True, forms=None, risk_rows=None)` uses `_gate_color(g, risk_rows)` and `"open_risks": sum(1 for r in (risk_rows or []) if r.get("status") != "finished")`. Keep `d["risks"] = [...]` from `sep_risks` for now (frontend stops reading it in Task 10).

Every place that builds gate dicts (`get_project_sep`, `get_rollup`, `sep_overview`, `activate_sep`, `update_gate`, `sign_off_gate` return) fetches `rows = await risk_rows_by_gate(db, project_id)` once and passes `risk_rows=rows.get(g.code, [])`.

In `sign_off_gate`, replace the `gate.risks` based block with:
```python
    rows = (await risk_rows_by_gate(db, gate.project_id)).get(gate.code, [])
    open_items = [i for i in gate.items if i.status == "open"]
    unfinished = [r for r in rows if r.get("status") != "finished"]
    if open_items and not rows:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
            detail=f"{len(open_items)} open work items: a risk assessment entry for {gate.code} with action plan is required (yellow gate)")
    deadline = (datetime.utcnow() + timedelta(days=ACTION_PLAN_MAX_DAYS)).date().isoformat()
    if open_items or unfinished:
        incomplete = [i + 1 for i, r in enumerate(unfinished)
                      if not (r.get("countermeasure") or "").strip() or not r.get("due") or not r.get("responsible")]
        if incomplete:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                detail=f"Risk entries {incomplete} need countermeasure, responsible and due date before sign-off")
        overdue = [i + 1 for i, r in enumerate(unfinished) if str(r.get("due"))[:10] > deadline]
        if overdue:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                detail=f"Risk entries {overdue}: action plan due date must be within {ACTION_PLAN_MAX_DAYS} days")
```

- [ ] **Step 5: Adjust `tests/test_sep.py`**

Tests that create risks through `POST /gates/{id}/risks` to satisfy the yellow-gate rule must instead create the form instance and save a row. Add this helper at the top of `test_sep.py` and use it wherever a risk was created for sign-off:
```python
async def _add_form_risk(client, auth, project_id, gate_code, **row):
    from app.forms.loader import load_definitions  # noqa
    res = await client.get(f"/api/v1/forms/projects/{project_id}", headers=auth)
    group = next(g for g in res.json() if g["key"] == "risk_assessment")
    if group["instances"]:
        inst = (await client.get(f"/api/v1/forms/instances/{group['instances'][0]['id']}", headers=auth)).json()
    else:
        inst = (await client.post(f"/api/v1/forms/projects/{project_id}/instances", json={"key": "risk_assessment"}, headers=auth)).json()
    data = inst["data"]
    data["risks"] = list(data.get("risks") or []) + [{"gate": gate_code, "risk": "r", "q": 0.1, "c": 0.1, "s": 0.1, "p": 0.5, "status": "open", **row}]
    res = await client.patch(f"/api/v1/forms/instances/{inst['id']}", json={"data": data}, headers=auth)
    assert res.status_code == 200, res.text
```
Definitions must be loaded for those tests: add a `seed_forms` fixture in `tests/conftest.py`:
```python
@pytest_asyncio.fixture
async def seed_forms(session_factory, seed):
    from app.forms.loader import load_definitions
    async with session_factory() as s:
        await load_definitions(s)
        await s.commit()
```
and request it in the affected tests. Run `python -m pytest tests/test_sep.py -q`, fix each failure by replacing the `/risks` call with `_add_form_risk` (the old risk endpoints still exist but no longer influence colour or sign-off).

- [ ] **Step 6: Migration data step**

Append to `upgrade()` in `065_sep_forms.py`, after the table creation:
```python
    # Seed definitions and copy legacy sep_risks into the risk_assessment form.
    import asyncio
    from app.forms.loader import read_definition_files

    bind = op.get_bind()
    defs = sa.table("form_definitions", sa.column("key"), sa.column("version"), sa.column("title"),
                    sa.column("implements"), sa.column("cardinality"), sa.column("gate_items"), sa.column("body"))
    existing = {(k, v) for k, v in bind.execute(sa.select(defs.c.key, defs.c.version)).all()}
    for body in read_definition_files():
        if (body["key"], body["version"]) not in existing:
            bind.execute(defs.insert().values(key=body["key"], version=body["version"], title=body["title"],
                                              implements=body.get("implements"), cardinality=body.get("cardinality", "single"),
                                              gate_items=bool(body.get("gate_items", False)), body=body))
    # The row copy needs ORM sessions; run it through the app's async engine after the schema exists.
    from app.models import AsyncSessionLocal
    from app.forms.risks import copy_sep_risks_to_forms

    async def _copy():
        async with AsyncSessionLocal() as session:
            n = await copy_sep_risks_to_forms(session)
            await session.commit()
            return n
    try:
        asyncio.get_event_loop().run_until_complete(_copy())
    except RuntimeError:
        asyncio.run(_copy())
```
If running the async copy inside Alembic proves impossible in the container (event loop already running), leave only the definition insert in the migration and run `python scripts/migrate_sep_risks.py` (a 10-line script calling `copy_sep_risks_to_forms`) as a deploy step; document which one was used in the commit message.

- [ ] **Step 7: Run all backend tests** → PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/forms/risks.py backend/app/api/v1/timing/sep.py backend/alembic/versions/065_sep_forms.py backend/tests
git commit -m "feat(forms): gate colour and sign-off read the risk assessment form; migrate sep_risks"
```

---

### Task 7: PDF export

**Files:**
- Create: `backend/app/forms/pdf.py`
- Modify: `backend/app/api/v1/timing/forms.py` (add export endpoint)
- Modify: `backend/requirements.txt` (add `reportlab==4.2.5`)
- Test: `backend/tests/test_forms.py` (append)

**Interfaces:**
- Produces: `render_pdf(inst_dict: dict) -> bytes` taking the full instance dict from `_inst_dict(full=True)`.
- Endpoint `GET /v1/forms/instances/{id}/export.pdf` → `application/pdf`, filename `<key>-<project_id>-<id>.pdf`.

- [ ] **Step 1: Test**

```python
async def test_pdf_export(client, eng_auth, seed, session_factory):
    await _activate_sep(client, eng_auth, seed["project_id"])
    await _seed_defs(session_factory)
    inst = (await client.post(f"/api/v1/forms/projects/{seed['project_id']}/instances", json={"key": "lop"}, headers=eng_auth)).json()
    res = await client.get(f"/api/v1/forms/instances/{inst['id']}/export.pdf", headers=eng_auth)
    assert res.status_code == 200 and res.headers["content-type"].startswith("application/pdf")
    assert res.content[:4] == b"%PDF"
```

- [ ] **Step 2: Install and implement**

`pip install reportlab==4.2.5` in the dev venv; add the pin under `openpyxl>=3.1` in `requirements.txt`.

`backend/app/forms/pdf.py`:
```python
"""Render a form instance to PDF (landscape A4, tables in definition order, event history last)."""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak


def _fmt(v) -> str:
    if v is None or v is False:
        return ""
    if v is True:
        return "yes"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


def render_pdf(inst: dict) -> bytes:
    styles = getSampleStyleSheet()
    body_style = styles["BodyText"]
    body_style.fontSize = 8
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm)
    story = [Paragraph(inst["title"], styles["Title"]),
             Paragraph(f"Project {inst['project_id']} · version {inst['version']} · implements {inst.get('implements') or '-'} · "
                       f"status {inst['status']} · submitted by {inst.get('submitted_by_name') or '-'} {inst.get('submitted_at') or ''}",
                       body_style), Spacer(1, 4 * mm)]
    grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 7),
                       ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP")])
    names = {}  # user id -> name for user fields, filled from events/signatures where possible
    for e in inst.get("events", []):
        names[e["user_id"]] = e.get("user_name") or str(e["user_id"])
    data = inst["data"]
    for s in inst["definition"]["sections"]:
        story.append(Paragraph(s["title"], styles["Heading3"]))
        if s["kind"] == "fields":
            vals = data.get(s["id"]) or {}
            rows = [[Paragraph(f["label"], body_style),
                     Paragraph(_fmt(names.get(vals.get(f["id"]), vals.get(f["id"])) if f["type"] == "user" else vals.get(f["id"])), body_style)]
                    for f in s["fields"]]
            t = Table(rows, colWidths=[60 * mm, None]); t.setStyle(grid); story.append(t)
        else:
            cols = s["columns"]
            rows = [[Paragraph(c["label"], body_style) for c in cols]]
            for r in data.get(s["id"]) or []:
                rows.append([Paragraph(_fmt(names.get(r.get(c["id"]), r.get(c["id"])) if c["type"] == "user" else r.get(c["id"])), body_style) for c in cols])
            t = Table(rows, repeatRows=1); t.setStyle(grid); story.append(t)
            footer = data.get(f"{s['id']}_footer") or {}
            if footer:
                story.append(Paragraph(" · ".join(f"{k}: {_fmt(v)}" for k, v in footer.items()), body_style))
        story.append(Spacer(1, 3 * mm))
    sigs = inst.get("signatures") or {}
    if sigs:
        story.append(Paragraph("Signatures", styles["Heading3"]))
        story.append(Paragraph("<br/>".join(f"{r.upper()}: {(s or {}).get('user_name') or 'pending'} {(s or {}).get('at') or ''}" for r, s in sigs.items()), body_style))
    story.append(PageBreak())
    story.append(Paragraph("History", styles["Heading3"]))
    hist = [["When", "Who", "Event", "Role"]] + [[e["created_at"][:19], e.get("user_name") or "", e["event"], e.get("role") or ""] for e in inst.get("events", [])]
    t = Table(hist, repeatRows=1); t.setStyle(grid); story.append(t)
    doc.build(story)
    return buf.getvalue()
```

Endpoint in `forms.py`:
```python
@router.get("/instances/{instance_id}/export.pdf")
async def export_pdf(instance_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.forms.pdf import render_pdf
    try:
        inst = await svc.load_instance(db, instance_id)
    except FormError as e:
        _raise(e)
    payload = await _inst_dict(db, inst, full=True)
    pdf = render_pdf(payload)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{payload["key"]}-{payload["project_id"]}-{inst.id}.pdf"'})
```

- [ ] **Step 3: Run** `python -m pytest tests/test_forms.py -q` → PASS. Check the Docker build installs reportlab (it reads `requirements.txt`, Dockerfile line 22–24).

- [ ] **Step 4: Commit**

```bash
git add backend/app/forms/pdf.py backend/app/api/v1/timing/forms.py backend/requirements.txt backend/tests/test_forms.py
git commit -m "feat(forms): PDF export of form instances"
```

---

### Task 8: Frontend expression evaluator and compute

**Files:**
- Create: `frontend/src/forms/expr.ts`
- Create: `frontend/src/forms/expr.test.ts`
- Create: `frontend/src/forms/types.ts`
- Create: `frontend/src/forms/compute.ts`
- Create: `frontend/src/forms/compute.test.ts`

**Interfaces:**
- Produces: `evaluate(expr: string, scope: Record<string, unknown>): unknown` (throws `ExprError`), `recompute(body: FormDefinitionBody, data: FormData): FormData`, and the types below.

- [ ] **Step 1: Types**

`frontend/src/forms/types.ts`:
```ts
export type FieldType = 'text' | 'multiline' | 'number' | 'date' | 'checkbox' | 'choice' | 'multichoice' | 'user' | 'computed';

export interface FieldDef {
  id: string; label: string; type: FieldType; help?: string; required?: boolean; readonly?: boolean;
  options?: string[]; min?: number; max?: number; step?: number; expr?: string; prefill?: string; width?: number;
}
export interface FieldsSection { id: string; title: string; kind: 'fields'; fields: FieldDef[] }
export interface TableSection {
  id: string; title: string; kind: 'table'; min_rows?: number; columns: FieldDef[];
  footer?: { label: string; expr: string }[]; prefill?: string;
}
export type Section = FieldsSection | TableSection;
export interface FormDefinitionBody {
  key: string; version: number; title: string; implements?: string | null; cardinality: 'single' | 'multi';
  gate_items: boolean; sep_items: string[]; signatures: string[]; required_for_submit: string[];
  references?: { title: string; path: string }[]; sections: Section[];
}
export type Row = Record<string, unknown>;
export type FormData = Record<string, Record<string, unknown> | Row[] | undefined>;

export interface Signature { user_id: number; user_name: string | null; at: string }
export interface FormEvent { id: number; user_id: number; user_name: string | null; event: string; role: string | null; diff: Record<string, unknown> | null; created_at: string }
export interface FormInstance {
  id: number; project_id: number; key: string; title: string; version: number; implements: string | null;
  cardinality: 'single' | 'multi'; status: 'draft' | 'submitted' | 'reopened'; data: FormData;
  owner_id: number | null; owner_name: string | null; updated_by_name: string | null; updated_at: string;
  submitted_by_name: string | null; submitted_at: string | null;
  signatures: Record<string, Signature | null>; references: { title: string; path: string }[]; sep_items: string[];
  definition?: FormDefinitionBody; events?: FormEvent[];
}
export interface FormGroup {
  key: string; title: string; version: number; implements: string | null; cardinality: 'single' | 'multi';
  sep_items: string[]; signatures: string[]; instances: FormInstance[];
}
export interface ItemFormInfo { key: string; title: string; instance_id: number | null; status: string | null }
```

- [ ] **Step 2: Vector test**

`frontend/src/forms/expr.test.ts`:
```ts
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { evaluate, ExprError } from './expr';

const vectors = JSON.parse(readFileSync(resolve(__dirname, '../../../backend/app/data/forms/expr_vectors.json'), 'utf8')) as
  { expr: string; scope: Record<string, unknown>; expected?: unknown; error?: boolean }[];

describe('expr vectors', () => {
  for (const v of vectors) {
    it(v.expr, () => {
      if (v.error) expect(() => evaluate(v.expr, v.scope)).toThrow(ExprError);
      else if (typeof v.expected === 'number') expect(evaluate(v.expr, v.scope)).toBeCloseTo(v.expected, 6);
      else expect(evaluate(v.expr, v.scope)).toEqual(v.expected);
    });
  }
  it('today is ISO', () => expect(String(evaluate('today()', {}))).toHaveLength(10));
});
```

- [ ] **Step 3: Run** `npx vitest run src/forms/expr.test.ts` → fails (module missing).

- [ ] **Step 4: Implement `expr.ts`** — same grammar and semantics as `expr.py`:

```ts
export class ExprError extends Error {}

type Tok = { k: 'num' | 'str' | 'op' | 'id' | 'eof'; v: string | number | null };
const RE = /\s*(?:(\d+\.\d+|\d+)|('(?:[^'\\]|\\.)*')|(==|!=|<=|>=|[-+*/()<>,\[\]])|([A-Za-z_][A-Za-z0-9_]*))/y;

function tokenize(src: string): Tok[] {
  const out: Tok[] = []; let pos = 0;
  while (pos < src.length) {
    RE.lastIndex = pos; const m = RE.exec(src);
    if (!m || m[0].length === 0) { if (src.slice(pos).trim() === '') break; throw new ExprError(`bad token at ${pos}`); }
    pos = RE.lastIndex;
    if (m[1] !== undefined) out.push({ k: 'num', v: Number(m[1]) });
    else if (m[2] !== undefined) out.push({ k: 'str', v: m[2].slice(1, -1).replace(/\\'/g, "'") });
    else if (m[3] !== undefined) out.push({ k: 'op', v: m[3] });
    else out.push({ k: 'id', v: m[4] });
  }
  out.push({ k: 'eof', v: null });
  return out;
}

type Node = ['lit', unknown] | ['var', string] | ['list', Node[]] | ['neg', Node] | ['not', Node]
  | ['and', Node, Node] | ['or', Node, Node] | ['cmp', string, Node, Node] | ['bin', string, Node, Node] | ['call', string, Node[]];

class Parser {
  i = 0;
  constructor(private t: Tok[]) {}
  peek() { return this.t[this.i]; }
  is(k: Tok['k'], v?: string) { const p = this.peek(); return p.k === k && (v === undefined || p.v === v); }
  take(k?: Tok['k'], v?: string) { const p = this.peek(); if ((k && p.k !== k) || (v !== undefined && p.v !== v)) throw new ExprError(`expected ${v ?? k}, got ${p.v}`); this.i++; return p.v; }
  parse(): Node { const n = this.or(); if (!this.is('eof')) throw new ExprError(`unexpected ${this.peek().v}`); return n; }
  or(): Node { let n = this.and(); while (this.is('id', 'or')) { this.take(); n = ['or', n, this.and()]; } return n; }
  and(): Node { let n = this.not(); while (this.is('id', 'and')) { this.take(); n = ['and', n, this.not()]; } return n; }
  not(): Node { if (this.is('id', 'not')) { this.take(); return ['not', this.not()]; } return this.cmp(); }
  cmp(): Node { let n = this.add(); while (this.is('op') && ['==', '!=', '<', '<=', '>', '>='].includes(String(this.peek().v))) { const op = String(this.take()); n = ['cmp', op, n, this.add()]; } return n; }
  add(): Node { let n = this.mul(); while (this.is('op', '+') || this.is('op', '-')) { const op = String(this.take()); n = ['bin', op, n, this.mul()]; } return n; }
  mul(): Node { let n = this.unary(); while (this.is('op', '*') || this.is('op', '/')) { const op = String(this.take()); n = ['bin', op, n, this.unary()]; } return n; }
  unary(): Node { if (this.is('op', '-')) { this.take(); return ['neg', this.unary()]; } return this.primary(); }
  primary(): Node {
    const p = this.peek();
    if (p.k === 'num' || p.k === 'str') { this.take(); return ['lit', p.v]; }
    if (p.k === 'op' && p.v === '(') { this.take(); const n = this.or(); this.take('op', ')'); return n; }
    if (p.k === 'op' && p.v === '[') { this.take(); const items: Node[] = []; while (!this.is('op', ']')) { items.push(this.or()); if (this.is('op', ',')) this.take(); } this.take('op', ']'); return ['list', items]; }
    if (p.k === 'id') {
      const name = String(this.take());
      if (name === 'true' || name === 'false') return ['lit', name === 'true'];
      if (name === 'null') return ['lit', null];
      if (this.is('op', '(')) { this.take(); const args: Node[] = []; while (!this.is('op', ')')) { args.push(this.or()); if (this.is('op', ',')) this.take(); } this.take('op', ')'); return ['call', name, args]; }
      return ['var', name];
    }
    throw new ExprError(`unexpected ${p.v}`);
  }
}

const num = (x: unknown): number => (x === null || x === undefined || x === false || x === '' ? 0 : x === true ? 1 : Number(x));

function ev(n: Node, scope: Record<string, unknown>): unknown {
  switch (n[0]) {
    case 'lit': return n[1];
    case 'var': if (!(n[1] in scope)) throw new ExprError(`unknown identifier ${n[1]}`); return scope[n[1]];
    case 'list': return n[1].map((x) => ev(x, scope));
    case 'neg': return -num(ev(n[1], scope));
    case 'not': return !ev(n[1], scope);
    case 'and': return Boolean(ev(n[1], scope)) && Boolean(ev(n[2], scope));
    case 'or': return Boolean(ev(n[1], scope)) || Boolean(ev(n[2], scope));
    case 'cmp': {
      const a = ev(n[2], scope), b = ev(n[3], scope);
      if (n[1] === '==') return (a ?? null) === (b ?? null);
      if (n[1] === '!=') return (a ?? null) !== (b ?? null);
      const x = num(a), y = num(b);
      return n[1] === '<' ? x < y : n[1] === '<=' ? x <= y : n[1] === '>' ? x > y : x >= y;
    }
    case 'bin': {
      const a = num(ev(n[2], scope)), b = num(ev(n[3], scope));
      return n[1] === '+' ? a + b : n[1] === '-' ? a - b : n[1] === '*' ? a * b : b === 0 ? 0 : a / b;
    }
    case 'call': {
      const [, name, args] = n;
      if (name === 'count' || name === 'sum') {
        if (args.length !== 1) throw new ExprError(`${name} takes one argument`);
        const rows = (scope._rows as Record<string, unknown>[] | undefined) ?? [];
        const vals = rows.map((r) => ev(args[0], { ...scope, ...r }));
        return name === 'count' ? vals.filter(Boolean).length : vals.reduce<number>((s, v) => s + num(v), 0);
      }
      const vals = args.map((a) => ev(a, scope));
      if (name === 'band') {
        const x = num(vals[0]); const def = vals[vals.length - 1];
        for (const band of vals.slice(1, -1) as [unknown, unknown][]) if (x <= num(band[0])) return band[1];
        return def;
      }
      if (name === 'today') return new Date().toISOString().slice(0, 10);
      if (name === 'days_between') {
        const a = new Date(String(vals[0]).slice(0, 10)), b = new Date(String(vals[1]).slice(0, 10));
        return Math.round((b.getTime() - a.getTime()) / 86400000);
      }
      throw new ExprError(`unknown function ${name}`);
    }
  }
}

const cache = new Map<string, Node>();
export function evaluate(expr: string, scope: Record<string, unknown>): unknown {
  let ast = cache.get(expr);
  if (!ast) { ast = new Parser(tokenize(expr)).parse(); cache.set(expr, ast); }
  return ev(ast, scope);
}
```

Note: in the Python version, `None == None` is true and in JS `null === undefined` is false, hence the `?? null` normalisation in `cmp`.

- [ ] **Step 5: `compute.ts` and its test**

```ts
import { evaluate } from './expr';
import type { FormDefinitionBody, FormData, Row } from './types';

const safe = (expr: string, scope: Record<string, unknown>) => { try { return evaluate(expr, scope); } catch { return null; } };

export function recompute(body: FormDefinitionBody, data: FormData): FormData {
  const out: FormData = { ...data };
  for (const s of body.sections) {
    if (s.kind === 'fields') {
      const vals: Record<string, unknown> = { ...((data[s.id] as Record<string, unknown>) ?? {}) };
      for (const f of s.fields) if (f.type === 'computed') vals[f.id] = safe(f.expr ?? '', vals);
      out[s.id] = vals;
    } else {
      const rows = (((data[s.id] as Row[]) ?? []).map((r) => ({ ...r })));
      for (const r of rows) for (const c of s.columns) if (c.type === 'computed') r[c.id] = safe(c.expr ?? '', r);
      out[s.id] = rows;
      if (s.footer) out[`${s.id}_footer`] = Object.fromEntries(s.footer.map((f) => [f.label, safe(f.expr, { _rows: rows })]));
    }
  }
  return out;
}
```

`compute.test.ts`: reuse the `MINI` definition from the backend test (copy it as a TS object) and assert `double === 4`, row `r` values `[0.5, 1]`, `rows_footer.Open === 1`.

- [ ] **Step 6: Run** `npx vitest run src/forms` → PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/forms
git commit -m "feat(forms): frontend expression evaluator, types and recompute"
```

---

### Task 9: Generic form renderer

**Files:**
- Create: `frontend/src/forms/FormRenderer.tsx`
- Create: `frontend/src/forms/FormRenderer.test.tsx`

**Interfaces:**
- Produces: `<FormRenderer body data onChange readOnly users />` where `onChange(next: FormData)` receives recomputed data, `users: {id:number; name:string}[]` feeds `user` pickers. Table sections render add-row and remove-row buttons unless `readOnly`. Computed fields render as read-only text. `help` renders under the label. Footer renders as chips under the table.

Styling follows `ProjectSepSection.tsx`: dark slate palette (`bg-slate-800`, `border-slate-700`, `text-slate-200`), inputs `bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm`. Keep the component under ~250 lines; split `FieldInput.tsx` out if it grows past that.

- [ ] **Step 1: Test**

`FormRenderer.test.tsx`:
```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import FormRenderer from './FormRenderer';
import type { FormDefinitionBody } from './types';

const body: FormDefinitionBody = {
  key: 'all', version: 1, title: 'All', cardinality: 'single', gate_items: false, sep_items: [], signatures: [], required_for_submit: [],
  sections: [
    { id: 'h', title: 'Header', kind: 'fields', fields: [
      { id: 't', label: 'Text', type: 'text' }, { id: 'm', label: 'Multi', type: 'multiline' },
      { id: 'n', label: 'Num', type: 'number' }, { id: 'd', label: 'Date', type: 'date' },
      { id: 'b', label: 'Check', type: 'checkbox' }, { id: 'c', label: 'Choice', type: 'choice', options: ['a', 'b'] },
      { id: 'mc', label: 'Multi choice', type: 'multichoice', options: ['x', 'y'] },
      { id: 'u', label: 'User', type: 'user' }, { id: 'dbl', label: 'Double', type: 'computed', expr: 'n * 2', help: 'twice n' },
    ] },
    { id: 'rows', title: 'Rows', kind: 'table', columns: [
      { id: 'q', label: 'Q', type: 'number' }, { id: 'r', label: 'R', type: 'computed', expr: 'q * 2' },
    ], footer: [{ label: 'Sum R', expr: 'sum(r)' }] },
  ],
};

describe('FormRenderer', () => {
  it('renders every field type, recomputes on change, adds rows', () => {
    const onChange = vi.fn();
    render(<FormRenderer body={body} data={{ h: { n: 2 }, rows: [] }} onChange={onChange} users={[{ id: 1, name: 'Eng' }]} />);
    expect(screen.getByLabelText('Text')).toBeTruthy();
    expect(screen.getByLabelText('Multi')).toBeTruthy();
    expect(screen.getByLabelText('Date')).toBeTruthy();
    expect(screen.getByLabelText('Check')).toBeTruthy();
    expect(screen.getByLabelText('Choice')).toBeTruthy();
    expect(screen.getByLabelText('User')).toBeTruthy();
    expect(screen.getByText('twice n')).toBeTruthy();
    expect(screen.getByText('4')).toBeTruthy(); // computed double shown
    fireEvent.change(screen.getByLabelText('Num'), { target: { value: '5' } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ h: expect.objectContaining({ n: 5, dbl: 10 }) }));
    fireEvent.click(screen.getByRole('button', { name: /add row/i }));
    const last = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect((last.rows as unknown[]).length).toBe(1);
    cleanup();
  });

  it('read-only renders no inputs or add-row', () => {
    render(<FormRenderer body={body} data={{ h: { t: 'hello' }, rows: [{ q: 1 }] }} onChange={() => {}} readOnly users={[]} />);
    expect(screen.queryByRole('button', { name: /add row/i })).toBeNull();
    expect(screen.getByText('hello')).toBeTruthy();
    cleanup();
  });
});
```

- [ ] **Step 2: Run** → fails (module missing).

- [ ] **Step 3: Implement**

```tsx
import { recompute } from './compute';
import type { FormDefinitionBody, FormData, FieldDef, Row, TableSection } from './types';

interface UserOption { id: number; name: string }
interface Props { body: FormDefinitionBody; data: FormData; onChange: (next: FormData) => void; readOnly?: boolean; users: UserOption[] }

const INPUT = 'w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm text-slate-100 disabled:opacity-60';

function display(f: FieldDef, v: unknown, users: UserOption[]): string {
  if (v === null || v === undefined || v === '') return '';
  if (f.type === 'checkbox') return v ? 'yes' : 'no';
  if (f.type === 'user') return users.find((u) => u.id === Number(v))?.name ?? String(v);
  if (f.type === 'multichoice' && Array.isArray(v)) return v.join(', ');
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/\.?0+$/, '');
  return String(v);
}

function FieldInput({ f, value, onChange, readOnly, users, id }:
  { f: FieldDef; value: unknown; onChange: (v: unknown) => void; readOnly: boolean; users: UserOption[]; id: string }) {
  const ro = readOnly || f.readonly || f.type === 'computed';
  if (ro) return <div id={id} className="text-sm text-slate-200 min-h-[1.75rem] py-1">{display(f, value, users)}</div>;
  switch (f.type) {
    case 'multiline': return <textarea id={id} className={INPUT} rows={2} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value)} />;
    case 'number': return <input id={id} type="number" className={INPUT} min={f.min} max={f.max} step={f.step ?? 'any'}
      value={value === null || value === undefined ? '' : String(value)} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />;
    case 'date': return <input id={id} type="date" className={INPUT} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value || null)} />;
    case 'checkbox': return <input id={id} type="checkbox" className="h-4 w-4 mt-2" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />;
    case 'choice': return (
      <select id={id} className={INPUT} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">—</option>{f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>);
    case 'multichoice': return (
      <select id={id} multiple className={INPUT} value={(value as string[]) ?? []}
        onChange={(e) => onChange(Array.from(e.target.selectedOptions).map((o) => o.value))}>
        {f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>);
    case 'user': return (
      <select id={id} className={INPUT} value={value === null || value === undefined ? '' : String(value)} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">unassigned</option>{users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
      </select>);
    default: return <input id={id} type="text" className={INPUT} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value)} />;
  }
}

function TableEditor({ s, rows, footer, onRows, readOnly, users }:
  { s: TableSection; rows: Row[]; footer: Record<string, unknown> | undefined; onRows: (rows: Row[]) => void; readOnly: boolean; users: UserOption[] }) {
  const setCell = (i: number, id: string, v: unknown) => onRows(rows.map((r, j) => (j === i ? { ...r, [id]: v } : r)));
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-xs">
        <thead><tr className="text-slate-400">
          <th className="px-1 text-left w-6">#</th>
          {s.columns.map((c) => <th key={c.id} className="px-1 text-left font-medium" style={{ minWidth: `${(c.width ?? 1) * 6}rem` }}>{c.label}</th>)}
          {!readOnly && <th className="w-8" />}
        </tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-slate-700/60 align-top">
              <td className="px-1 py-1 text-slate-500">{i + 1}</td>
              {s.columns.map((c) => <td key={c.id} className="px-1 py-1">
                <FieldInput id={`${s.id}-${i}-${c.id}`} f={c} value={r[c.id]} onChange={(v) => setCell(i, c.id, v)} readOnly={readOnly} users={users} />
              </td>)}
              {!readOnly && <td className="px-1 py-1"><button type="button" aria-label="remove row" className="text-slate-500 hover:text-red-400" onClick={() => onRows(rows.filter((_, j) => j !== i))}>✕</button></td>}
            </tr>))}
        </tbody>
      </table>
      <div className="flex items-center gap-3 mt-2">
        {!readOnly && <button type="button" className="text-xs px-2 py-1 rounded border border-slate-600 text-slate-300 hover:border-slate-400" onClick={() => onRows([...rows, {}])}>+ Add row</button>}
        {footer && Object.entries(footer).map(([k, v]) => <span key={k} className="text-xs px-2 py-0.5 rounded bg-slate-700/60 text-slate-300">{k}: {display({ id: k, label: k, type: 'text' }, v, users)}</span>)}
      </div>
    </div>
  );
}

export default function FormRenderer({ body, data, onChange, readOnly = false, users }: Props) {
  const computed = recompute(body, data);
  const update = (next: FormData) => onChange(recompute(body, next));
  return (
    <div className="space-y-5">
      {body.sections.map((s) => (
        <section key={s.id}>
          <h4 className="text-xs uppercase tracking-wide text-slate-500 mb-2">{s.title}</h4>
          {s.kind === 'fields' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
              {s.fields.map((f) => {
                const id = `${s.id}-${f.id}`;
                const vals = (computed[s.id] as Record<string, unknown>) ?? {};
                return (
                  <div key={f.id}>
                    <label htmlFor={id} className="block text-xs text-slate-400 mb-0.5">{f.label}{f.required && ' *'}</label>
                    <FieldInput id={id} f={f} value={vals[f.id]} readOnly={readOnly} users={users}
                      onChange={(v) => update({ ...computed, [s.id]: { ...vals, [f.id]: v } })} />
                    {f.help && <p className="text-[11px] text-slate-500 mt-0.5">{f.help}</p>}
                  </div>);
              })}
            </div>
          ) : (
            <TableEditor s={s} rows={(computed[s.id] as Row[]) ?? []} footer={computed[`${s.id}_footer`] as Record<string, unknown> | undefined}
              onRows={(rows) => update({ ...computed, [s.id]: rows })} readOnly={readOnly} users={users} />
          )}
        </section>
      ))}
    </div>
  );
}
```

`getByLabelText` needs the `label htmlFor` to match the input `id`; for read-only fields the `div` has the same id so the label still resolves.

- [ ] **Step 4: Run** `npx vitest run src/forms` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/forms/FormRenderer.tsx frontend/src/forms/FormRenderer.test.tsx
git commit -m "feat(forms): generic form renderer"
```

---

### Task 10: Form panel, project forms tab, SEP checklist integration, My Tasks

**Files:**
- Create: `frontend/src/forms/FormPanel.tsx`
- Create: `frontend/src/forms/ProjectFormsTab.tsx`
- Modify: `frontend/src/components/ProjectSepSection.tsx` (item form button + references, Forms tab replaces Risks tab, remove `RiskTab`)
- Modify: `frontend/src/pages/MyTasksPage.tsx` (Forms section)
- Test: `frontend/src/forms/FormPanel.test.tsx`

**Interfaces:**
- `<FormPanel instanceId onClose />` — fetches `GET /v1/forms/instances/{id}`, renders header (title, status chip, version, owner, references links, signatures), `FormRenderer`, and buttons: Save (draft/reopened), Submit (draft/reopened), Reopen (submitted), Sign as <role> (submitted, per unsigned role), Export PDF (any status, opens `/api/v1/forms/instances/{id}/export.pdf` in a new tab). Invalidates `['sep']`, `['forms', projectId]`, `['my-forms']` on every mutation.
- `<ProjectFormsTab projectId gates />` — fetches `GET /v1/forms/projects/{id}`; lists each group with its instances and a "New" button (hidden for `single` groups that already have one). Clicking an instance opens `FormPanel`. Groups are ordered by the first gate in `sep_items`, groups without items last.
- `openForm(item)` in `ItemRow`: if `item.form.instance_id` open the panel, else `POST /v1/forms/projects/{projectId}/instances {key}` then open. On 409 with `instance_id` in the detail, open that one.

- [ ] **Step 1: FormPanel test**

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import FormPanel from './FormPanel';

vi.mock('../api/client', () => ({ default: {
  get: vi.fn(async (url: string) => {
    if (url === '/v1/forms/instances/7') return { data: {
      id: 7, project_id: 1, key: 'lop', title: 'Open Points List (LOP)', version: 1, implements: 'F-DVS-CORP-010', cardinality: 'single',
      status: 'submitted', data: { header: {}, points: [] }, owner_id: 1, owner_name: 'Eng', updated_by_name: 'Eng', updated_at: '2026-09-03T10:00:00',
      submitted_by_name: 'Eng', submitted_at: '2026-09-03T10:00:00', signatures: {}, references: [], sep_items: [],
      definition: { key: 'lop', version: 1, title: 'Open Points List (LOP)', cardinality: 'single', gate_items: false, sep_items: [], signatures: [], required_for_submit: [],
        sections: [{ id: 'header', title: 'Project', kind: 'fields', fields: [{ id: 'project_no', label: 'Project No.', type: 'text' }] }] },
      events: [{ id: 1, user_id: 1, user_name: 'Eng', event: 'submitted', role: null, diff: null, created_at: '2026-09-03T10:00:00' }],
    } };
    if (url === '/v1/lessons/assignable-users') return { data: [{ id: 1, name: 'Eng' }] };
    throw new Error(url);
  }),
  post: vi.fn(), patch: vi.fn(),
} }));

describe('FormPanel', () => {
  it('shows a submitted form read-only with reopen and export', async () => {
    const qc = new QueryClient();
    render(<QueryClientProvider client={qc}><FormPanel instanceId={7} onClose={() => {}} /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByText('Open Points List (LOP)')).toBeTruthy());
    expect(screen.getByText('submitted')).toBeTruthy();
    expect(screen.getByRole('button', { name: /reopen/i })).toBeTruthy();
    expect(screen.getByRole('link', { name: /export pdf/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^save$/i })).toBeNull();
    cleanup();
  });
});
```

- [ ] **Step 2: Run** → fails.

- [ ] **Step 3: Implement `FormPanel.tsx`**

```tsx
import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../api/client';
import FormRenderer from './FormRenderer';
import type { FormInstance, FormData } from './types';

const STATUS_STYLE: Record<string, string> = {
  draft: 'bg-amber-500/20 text-amber-300', reopened: 'bg-amber-500/20 text-amber-300', submitted: 'bg-emerald-600/20 text-emerald-300',
};
const errDetail = (e: any) => { const d = e?.response?.data?.detail; return typeof d === 'string' ? d : d?.message ?? 'Request failed'; };

export default function FormPanel({ instanceId, onClose }: { instanceId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<FormData | null>(null);
  const { data: inst } = useQuery({
    queryKey: ['form-instance', instanceId],
    queryFn: async () => (await client.get(`/v1/forms/instances/${instanceId}`)).data as FormInstance,
  });
  const { data: users = [] } = useQuery({
    queryKey: ['assignable-users'],
    queryFn: async () => (await client.get('/v1/lessons/assignable-users')).data as { id: number; name: string }[],
  });
  useEffect(() => { if (inst) setDraft(inst.data); }, [inst?.id, inst?.updated_at]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['form-instance', instanceId] });
    qc.invalidateQueries({ queryKey: ['sep'] });
    qc.invalidateQueries({ queryKey: ['forms'] });
    qc.invalidateQueries({ queryKey: ['my-forms'] });
  };
  const act = (label: string, fn: () => Promise<unknown>) => useMutation({
    mutationFn: fn, onSuccess: () => { toast.success(label); refresh(); }, onError: (e) => toast.error(errDetail(e)),
  });
  const save = act('Saved', () => client.patch(`/v1/forms/instances/${instanceId}`, { data: draft }));
  const submit = act('Submitted', async () => { await client.patch(`/v1/forms/instances/${instanceId}`, { data: draft }); return client.post(`/v1/forms/instances/${instanceId}/submit`); });
  const reopen = act('Reopened', () => client.post(`/v1/forms/instances/${instanceId}/reopen`));
  const sign = useMutation({
    mutationFn: (role: string) => client.post(`/v1/forms/instances/${instanceId}/sign`, { role }),
    onSuccess: () => { toast.success('Signed'); refresh(); }, onError: (e) => toast.error(errDetail(e)),
  });

  if (!inst || !draft) return <div className="p-4 text-slate-400 text-sm">Loading…</div>;
  const editable = inst.status !== 'submitted';
  const pendingRoles = Object.entries(inst.signatures).filter(([, s]) => !s).map(([r]) => r);

  return (
    <div className="fixed inset-y-0 right-0 w-full md:w-[46rem] bg-slate-800 border-l border-slate-700 shadow-xl z-40 flex flex-col">
      <div className="px-4 py-3 border-b border-slate-700 flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-slate-100 font-semibold">{inst.title}</div>
          <div className="text-xs text-slate-500">
            v{inst.version}{inst.implements ? ` · ${inst.implements}` : ''} · owner {inst.owner_name ?? '—'} · updated {inst.updated_at.slice(0, 10)} by {inst.updated_by_name ?? '—'}
          </div>
          {inst.references.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-2 text-xs">
              {inst.references.map((r) => <span key={r.path} className="text-blue-400" title={r.path}>📎 {r.title}</span>)}
            </div>)}
        </div>
        <span className={`px-2 py-0.5 rounded text-xs ${STATUS_STYLE[inst.status]}`}>{inst.status}</span>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-200" aria-label="close">✕</button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3">
        <FormRenderer body={inst.definition!} data={draft} onChange={setDraft} readOnly={!editable} users={users} />
        {Object.keys(inst.signatures).length > 0 && (
          <div className="mt-5 text-xs flex flex-wrap gap-2">
            {Object.entries(inst.signatures).map(([role, s]) => s
              ? <span key={role} className="px-2 py-1 rounded bg-emerald-600/20 text-emerald-300">✓ {role.toUpperCase()}: {s.user_name} ({s.at.slice(0, 10)})</span>
              : <span key={role} className="px-2 py-1 rounded bg-slate-700 text-slate-400">{role.toUpperCase()}: pending</span>)}
          </div>)}
        {inst.events && (
          <details className="mt-5 text-xs text-slate-500"><summary className="cursor-pointer">History ({inst.events.length})</summary>
            <ul className="mt-1 space-y-0.5">{inst.events.map((e) => <li key={e.id}>{e.created_at.slice(0, 16).replace('T', ' ')} · {e.user_name} · {e.event}{e.role ? ` as ${e.role.toUpperCase()}` : ''}</li>)}</ul>
          </details>)}
      </div>
      <div className="px-4 py-3 border-t border-slate-700 flex flex-wrap gap-2 text-sm">
        {editable && <button onClick={() => save.mutate()} disabled={save.isPending} className="px-3 py-1 rounded border border-slate-600 text-slate-200 hover:border-slate-400">Save</button>}
        {editable && <button onClick={() => submit.mutate()} disabled={submit.isPending} className="px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-500">Submit</button>}
        {!editable && <button onClick={() => reopen.mutate()} disabled={reopen.isPending} className="px-3 py-1 rounded border border-amber-500/60 text-amber-300 hover:border-amber-400">Reopen</button>}
        {!editable && pendingRoles.map((r) => <button key={r} onClick={() => sign.mutate(r)} className="px-3 py-1 rounded border border-emerald-500/60 text-emerald-300">Sign as {r.toUpperCase()}</button>)}
        <a href={`/api/v1/forms/instances/${instanceId}/export.pdf`} target="_blank" rel="noreferrer" className="ml-auto px-3 py-1 rounded border border-slate-600 text-slate-300 hover:border-slate-400">Export PDF</a>
      </div>
    </div>
  );
}
```

Hooks inside `act` are created in a fixed order on every render, which is valid; if the linter complains, inline the four `useMutation` calls.

- [ ] **Step 4: Implement `ProjectFormsTab.tsx`**

```tsx
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../api/client';
import FormPanel from './FormPanel';
import type { FormGroup } from './types';

const GATE_ORDER = ['K0/RG1', 'K/RG2', 'E/RG3', 'D/RG4', 'C/RG5', 'B/RG6', 'A/RG7'];
const gateIndex = (g: FormGroup) => Math.min(...g.sep_items.map((r) => GATE_ORDER.indexOf(r.split(':')[0])), 99);

export default function ProjectFormsTab({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState<number | null>(null);
  const { data: groups = [] } = useQuery({
    queryKey: ['forms', projectId],
    queryFn: async () => (await client.get(`/v1/forms/projects/${projectId}`)).data as FormGroup[],
  });
  const create = useMutation({
    mutationFn: async (key: string) => (await client.post(`/v1/forms/projects/${projectId}/instances`, { key })).data,
    onSuccess: (inst) => { qc.invalidateQueries({ queryKey: ['forms', projectId] }); setOpen(inst.id); },
    onError: (e: any) => { const d = e.response?.data?.detail; if (d?.instance_id) setOpen(d.instance_id); else toast.error(typeof d === 'string' ? d : 'Could not create form'); },
  });
  const sorted = [...groups].sort((a, b) => gateIndex(a) - gateIndex(b) || a.title.localeCompare(b.title));
  return (
    <div className="space-y-2">
      {sorted.map((g) => (
        <div key={g.key} className="rounded bg-slate-900/40 px-3 py-2">
          <div className="flex items-center gap-2">
            <div className="flex-1 text-sm text-slate-200">{g.title}
              <span className="ml-2 text-xs text-slate-500">{g.sep_items.map((r) => r.split(':')[0]).filter((v, i, a) => a.indexOf(v) === i).join(', ') || 'no gate item'}</span>
            </div>
            {(g.cardinality === 'multi' || g.instances.length === 0) && (
              <button onClick={() => create.mutate(g.key)} className="text-xs px-2 py-0.5 rounded border border-slate-600 text-slate-300 hover:border-slate-400">+ New</button>)}
          </div>
          {g.instances.map((i) => (
            <button key={i.id} onClick={() => setOpen(i.id)} className="mt-1 w-full text-left text-xs flex items-center gap-2 text-slate-300 hover:text-white">
              <span className={`px-1.5 rounded ${i.status === 'submitted' ? 'bg-emerald-600/20 text-emerald-300' : 'bg-amber-500/20 text-amber-300'}`}>{i.status}</span>
              <span>#{i.id} · {i.owner_name ?? '—'} · {i.updated_at.slice(0, 10)}</span>
            </button>))}
        </div>))}
      {open !== null && <FormPanel instanceId={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
```

- [ ] **Step 5: Modify `ProjectSepSection.tsx`**

1. Extend `SepItem` with `form: ItemFormInfo | null; references: { title: string; path: string }[]` (import the type from `../forms/types`).
2. Delete the `SepRisk` interface, `RiskTab` component, `PRIORITY_STYLE`, and `risks: SepRisk[]` from `SepGate` (keep `open_risks`).
3. `ItemRow` gets a `projectId: number` prop and an `onOpenForm: (id: number) => void` prop. After the title, render:
```tsx
{item.form && (
  <button type="button" onClick={() => openForm()} className={`ml-1.5 text-xs ${item.form.status === 'submitted' ? 'text-emerald-300' : 'text-blue-400 hover:text-blue-300'}`} title={item.form.title}>
    📝 {item.form.status ?? 'open form'}
  </button>)}
{item.references.map((r) => <span key={r.path} className="ml-1.5 text-xs text-slate-500" title={r.path}>📎 {r.title}</span>)}
```
where `openForm` posts `/v1/forms/projects/${projectId}/instances` with `{ key: item.form.key }` when `instance_id` is null (on 409 use `detail.instance_id`), then calls `onOpenForm(id)`.
4. `GateDetail` tab state becomes `'checklist' | 'forms'`; the tab label is `Forms`; the forms tab renders `<ProjectFormsTab projectId={gate.project_id} />` (add `project_id: number` to `SepGate`, the API already returns it). `GateDetail` also holds `const [openForm, setOpenForm] = useState<number | null>(null)` and renders `{openForm !== null && <FormPanel instanceId={openForm} onClose={() => setOpenForm(null)} />}`.
5. The red-gate hint text becomes `⛔ high risk live — see risk assessment form`.

- [ ] **Step 6: My Tasks section**

In `MyTasksPage.tsx` add next to `SepItemsSection`:
```tsx
interface MyForm { id: number; key: string; title: string; status: string; reason: string; project_id: number; project_name: string; updated_at: string }

function FormsSection() {
  const navigate = useNavigate();
  const [open, setOpen] = useState<number | null>(null);
  const { data: forms = [] } = useQuery({
    queryKey: ['my-forms'],
    queryFn: async () => (await client.get('/v1/forms/my-forms')).data as MyForm[],
    refetchInterval: 60_000,
  });
  if (forms.length === 0) return null;
  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-2">📝 SEP Forms ({forms.length})</h2>
      <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
        <table className="w-full text-sm"><tbody>
          {forms.map((f) => (
            <tr key={f.id} className="border-b border-slate-700 last:border-0">
              <td className="px-4 py-3 text-slate-100"><button onClick={() => setOpen(f.id)} className="hover:underline text-left">{f.title}</button>
                <span className="text-xs text-slate-500 ml-2">{f.status}</span></td>
              <td className="px-4 py-3"><button onClick={() => navigate(`/projects/${f.project_id}`)} className="text-blue-400 hover:text-blue-300 underline">{f.project_name}</button></td>
              <td className="px-4 py-3 text-xs text-slate-400">{f.updated_at.slice(0, 10)}</td>
            </tr>))}
        </tbody></table>
      </div>
      {open !== null && <FormPanel instanceId={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
```
Import `FormPanel from '../forms/FormPanel'` and render `<FormsSection />` directly under `<SepItemsSection />`.

- [ ] **Step 7: Run** `npx vitest run src/forms` and `npx tsc --noEmit -p .` (pre-existing errors are known; only new files must be clean) → PASS. Start the dev stack (`run` skill / docker compose) and open a project with SEP active: item 2 of K0/RG1 shows `📝 open form`, clicking creates the risk assessment and opens the panel; the Forms tab lists six groups; My Tasks shows the draft.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/forms frontend/src/components/ProjectSepSection.tsx frontend/src/pages/MyTasksPage.tsx
git commit -m "feat(forms): form panel, project forms tab, SEP checklist and My Tasks integration"
```

---

### Task 11: Spec touch-ups, memory, and production notes

**Files:**
- Modify: `docs/superpowers/specs/2026-09-03-sep-forms-engine-design.md`
- Create: `memory/sep-forms-engine.md` and add a line to `memory/MEMORY.md`
- Modify: `DEPLOYMENT.md` (one paragraph)

- [ ] **Step 1: Spec** — record the four decisions made during implementation: reopen only flips items whose remark still reads `via form <title>`; reopen is open to any authenticated user until projects have a manager field; `sep_items` empty means "Forms tab only"; `/my-forms` lists only drafts I own, because without a role model nobody can be told a signature is theirs to give.
- [ ] **Step 2: Deployment note** — in `DEPLOYMENT.md`: migration 065 seeds definitions and copies `sep_risks`; new definition versions are picked up at startup or via `python scripts/load_form_definitions.py`; `reportlab` is a new backend dependency, so the image must be rebuilt.
- [ ] **Step 3: Memory** — `memory/sep-forms-engine.md` (type: project): what exists, where definitions live, that `sep_risks` is dead data pending removal, and the follow-up list (remaining ~30 forms, gating flag, risk tab code removal). Add the pointer line to `memory/MEMORY.md`.
- [ ] **Step 4: Full test run** — `cd backend && python -m pytest tests -q` and `cd frontend && npx vitest run` → all green; paste counts into the commit message.
- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-09-03-sep-forms-engine-design.md DEPLOYMENT.md memory
git commit -m "docs(forms): spec decisions, deployment note, memory"
```

Production rollout (user runs, not part of this plan): rebuild backend image, `alembic upgrade head`, verify 1994A/1994B have a risk assessment instance with their old risks, then check the K0/RG1 gate colours match what they were before.
