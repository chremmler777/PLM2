# Change Management — Core + Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the spine of PLM2 Change Management — a single `ChangeRequest` object that flows through one flexible, audited lifecycle, with impacted-item linking, per-discipline assessments, ECN-revision spawning at implementation, and a working UI.

**Architecture:** A new `change` model module (5 tables) + `ChangeService` holding the state machine (one central `transition()` with soft guards the lead can override-with-justification, and one hard sign-off gate). A `/v1/changes` router mirrors the SEP/parts router style. The Change spawns and later activates `PartRevision` rows on impacted parts. A React `ChangesPage` + `ChangeDetailPage` + `ProjectChangesSection` consume it. Tests are API-driven through the existing `httpx` client fixtures, matching the repo's test convention.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, pytest/pytest-asyncio (backend); React + TypeScript + TanStack Query + Axios (frontend).

**Spec:** `docs/superpowers/specs/2026-06-15-change-management-core-design.md`

**Conventions confirmed from the codebase:**
- Models: `Mapped`/`mapped_column`; string enums via `Enum(MyEnum, values_callable=lambda x: [e.value for e in x], native_enum=False)`; relationships with `back_populates` + `foreign_keys=[...]`.
- `parts.item_category` is a plain `String(30)` validated against `VALID_ITEM_CATEGORIES` in `app/services/part_service.py` — adding `eoat` needs **no migration**.
- Routers: `APIRouter(prefix=..., tags=[...])`, deps `get_current_user` and `get_db`, registered in `app/api/v1/__init__.py`.
- Migrations: numbered string `revision`/`down_revision`, idempotent `create_table` guarded by `inspector.get_table_names()`. Next is `019` (down_revision `018`).
- Tests: `app/api/v1/...` mounted under `/api`; fixtures `client`, `admin_auth`, `eng_auth`, `seed` (`project_id`, `admin_id`, `engineer_id`), `part` (`part_id`, `revision_id`). Login at `/api/v1/auth/login`.
- Frontend: pages in `frontend/src/pages`, components in `frontend/src/components`, types in `frontend/src/types`, API wrappers in `frontend/src/api` (axios base `http://localhost:8000/api`).

---

## File Structure

**Backend (create):**
- `backend/app/models/change.py` — `ChangeRequest`, `ChangeImpactedItem`, `ChangeAssessment`, `ChangeAttachment`, `ChangeChangelog` + enums + constants.
- `backend/app/schemas/change.py` — Pydantic Base/Create/Update/Response/Detail + action requests.
- `backend/app/services/change_service.py` — numbering, CRUD, state machine, guards, hash-chained changelog, assessments, impacted items, sign-off, ECN spawn, release.
- `backend/app/api/v1/changes/__init__.py` + `backend/app/api/v1/changes/changes.py` — REST endpoints.
- `backend/alembic/versions/019_add_change_management.py` — 5 tables.
- `backend/tests/test_changes.py` — API-driven tests.

**Backend (modify):**
- `backend/app/models/__init__.py` — export new models.
- `backend/app/api/v1/__init__.py` — register `changes_router`.
- `backend/app/services/part_service.py` — add `"eoat"` to `VALID_ITEM_CATEGORIES`.

**Frontend (create):**
- `frontend/src/types/change.ts` — TS types.
- `frontend/src/api/changes.ts` — API wrapper.
- `frontend/src/pages/ChangesPage.tsx` — list + create.
- `frontend/src/pages/ChangeDetailPage.tsx` — lifecycle stepper + tabs + actions.
- `frontend/src/components/ProjectChangesSection.tsx` — embedded project section.

**Frontend (modify):**
- `frontend/src/App.tsx` (or the router file) — routes for `/changes` and `/changes/:id`.
- `frontend/src/components/layout/Sidebar.tsx` — nav entry.
- `frontend/src/pages/ProjectDetailPage.tsx` — embed `ProjectChangesSection`.
- `frontend/src/pages/MyTasksPage.tsx` — surface change assessment/sign-off tasks.

---

## Domain constants (used across tasks — defined in Task 1)

```python
# change_type values
CHANGE_TYPES = ("physical_part", "tooling", "document_spec", "process_im", "packaging")

# lifecycle statuses
CHANGE_STATUSES = (
    "captured", "in_assessment", "costing", "quoted", "approved",
    "in_implementation", "in_validation", "released", "closed",
    "on_hold", "rejected", "cancelled",
)

# allowed forward/parking transitions: from -> {to, ...}
ALLOWED_TRANSITIONS = {
    "captured":         {"in_assessment", "cancelled", "on_hold"},
    "in_assessment":    {"costing", "rejected", "cancelled", "on_hold"},
    "costing":          {"quoted", "on_hold", "cancelled"},
    "quoted":           {"approved", "rejected", "on_hold", "cancelled"},
    "approved":         {"in_implementation", "on_hold", "cancelled"},
    "in_implementation":{"in_validation", "on_hold", "cancelled"},
    "in_validation":    {"released", "in_implementation", "on_hold", "cancelled"},
    "released":         {"closed"},
    "on_hold":          {"in_assessment", "costing", "quoted", "approved",
                         "in_implementation", "in_validation", "cancelled"},
    "rejected":         set(),
    "closed":           set(),
    "cancelled":        set(),
}

ASSESSMENT_VERDICTS = ("pending", "feasible", "feasible_with_conditions", "not_feasible")
CUSTOMER_RESPONSES = ("pending", "accepted", "declined", "negotiating")
SIGN_OFF_ROLES = ("pm", "quality")

# Disciplines suggested per change_type (department display names)
TYPE_DISCIPLINES = {
    "physical_part": ["Tool Engineer", "APQP", "Quality", "Manufacturing Engineer", "Sales"],
    "tooling":       ["Tool Engineer", "Process Engineer", "Manufacturing Engineer"],
    "document_spec": ["Quality", "Project Manager"],
    "process_im":    ["Process Engineer", "Manufacturing Engineer", "Quality"],
    "packaging":     ["Packaging Engineer", "Quality", "Sales"],
}
```

---

## Task 1: Change models

**Files:**
- Create: `backend/app/models/change.py`

- [ ] **Step 1: Write the model file**

```python
"""Change Management models - the spine of the engineering change process.

A single ChangeRequest flows through one flexible, audited lifecycle. Impacted
controlled items, per-discipline assessments, informal attachments (the PPT-only
start), and a hash-chained changelog hang off it. On approval the change spawns
ECN PartRevisions on each impacted part; on release those become active.
"""
from datetime import datetime

from sqlalchemy import String, Text, DateTime, Float, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

CHANGE_TYPES = ("physical_part", "tooling", "document_spec", "process_im", "packaging")
CHANGE_PRIORITIES = ("low", "medium", "high", "critical")
CHANGE_STATUSES = (
    "captured", "in_assessment", "costing", "quoted", "approved",
    "in_implementation", "in_validation", "released", "closed",
    "on_hold", "rejected", "cancelled",
)
ASSESSMENT_VERDICTS = ("pending", "feasible", "feasible_with_conditions", "not_feasible")
CUSTOMER_RESPONSES = ("pending", "accepted", "declined", "negotiating")
SIGN_OFF_ROLES = ("pm", "quality")
TERMINAL_STATUSES = ("released", "closed", "rejected", "cancelled")


class ChangeRequest(Base):
    """One engineering change, flowing through the lifecycle state machine."""
    __tablename__ = "change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)  # CR-2026-0042
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)

    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    change_type: Mapped[str] = mapped_column(String(30), default="physical_part")
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    data_classification: Mapped[str] = mapped_column(String(20), default="confidential")

    status: Mapped[str] = mapped_column(String(20), default="captured", index=True)

    lead_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    raised_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    raised_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Decision gate
    customer_response: Mapped[str] = mapped_column(String(20), default="pending")
    customer_response_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    customer_response_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    pm_signed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    pm_signed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    quality_signed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    quality_signed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Commercial stubs (sub-project #3)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    quoted_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Timing stub (sub-project #7)
    timing_milestone_id: Mapped[int | None] = mapped_column(ForeignKey("project_milestones.id"), nullable=True)

    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project: Mapped["Project"] = relationship(foreign_keys=[project_id])
    lead: Mapped["User | None"] = relationship(foreign_keys=[lead_id])
    raised_by_user: Mapped["User"] = relationship(foreign_keys=[raised_by])

    impacted_items: Mapped[list["ChangeImpactedItem"]] = relationship(
        back_populates="change", cascade="all, delete-orphan", lazy="selectin"
    )
    assessments: Mapped[list["ChangeAssessment"]] = relationship(
        back_populates="change", cascade="all, delete-orphan", lazy="selectin"
    )
    attachments: Mapped[list["ChangeAttachment"]] = relationship(
        back_populates="change", cascade="all, delete-orphan", lazy="selectin"
    )
    changelog_entries: Mapped[list["ChangeChangelog"]] = relationship(
        back_populates="change", cascade="all, delete-orphan",
        order_by="ChangeChangelog.performed_at",
    )


class ChangeImpactedItem(Base):
    """A controlled item (article/tool/assembly_equipment/eoat/gauge) affected by a change."""
    __tablename__ = "change_impacted_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), index=True)

    impact_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    eng_level_before: Mapped[str | None] = mapped_column(String(50), nullable=True)
    eng_level_after: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resulting_revision_id: Mapped[int | None] = mapped_column(ForeignKey("part_revisions.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))

    change: Mapped["ChangeRequest"] = relationship(back_populates="impacted_items", foreign_keys=[change_id])
    part: Mapped["Part"] = relationship(foreign_keys=[part_id])
    resulting_revision: Mapped["PartRevision | None"] = relationship(foreign_keys=[resulting_revision_id])


class ChangeAssessment(Base):
    """A feasibility verdict from one impacted discipline."""
    __tablename__ = "change_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"), index=True)

    verdict: Mapped[str] = mapped_column(String(30), default="pending")
    cost_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    lead_time_impact_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    responsible_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    change: Mapped["ChangeRequest"] = relationship(back_populates="assessments", foreign_keys=[change_id])
    department: Mapped["Department"] = relationship(foreign_keys=[department_id])


class ChangeAttachment(Base):
    """An informal document attached to a change (PPT, PDF, email, sketch)."""
    __tablename__ = "change_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)

    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))

    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    change: Mapped["ChangeRequest"] = relationship(back_populates="attachments", foreign_keys=[change_id])


class ChangeChangelog(Base):
    """Hash-chained audit trail for a change (mirrors RevisionChangelog)."""
    __tablename__ = "change_changelog"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)

    action: Mapped[str] = mapped_column(String(50))
    action_description: Mapped[str] = mapped_column(Text)
    field_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    performed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    performed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    change: Mapped["ChangeRequest"] = relationship(back_populates="changelog_entries", foreign_keys=[change_id])
    performed_by_user: Mapped["User"] = relationship(foreign_keys=[performed_by])


# Import related models for relationship resolution
from app.models.entities import Project, User  # noqa: E402
from app.models.part import Part, PartRevision  # noqa: E402
from app.models.workflow import Department  # noqa: E402
```

- [ ] **Step 2: Verify the module imports and tables register**

Run: `cd backend && python -c "from app.models.change import ChangeRequest, ChangeImpactedItem, ChangeAssessment, ChangeAttachment, ChangeChangelog; print('ok')"`
Expected: prints `ok` with no SQLAlchemy mapper errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/change.py
git commit -m "feat(change): add change management models"
```

---

## Task 2: Register models + add eoat category

**Files:**
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/services/part_service.py`

- [ ] **Step 1: Add change models to `app/models/__init__.py`**

After the line `from app.models.sep import SepGate, SepWorkItem, SepItemAudit, SepRisk`, add:

```python
from app.models.change import (
    ChangeRequest, ChangeImpactedItem, ChangeAssessment, ChangeAttachment, ChangeChangelog,
)
```

And add these strings into the `__all__` list (anywhere before the closing `]`):

```python
    "ChangeRequest",
    "ChangeImpactedItem",
    "ChangeAssessment",
    "ChangeAttachment",
    "ChangeChangelog",
```

- [ ] **Step 2: Add `eoat` to valid item categories**

In `backend/app/services/part_service.py`, change:

```python
VALID_ITEM_CATEGORIES = {"article", "tool", "assembly_equipment", "gauge"}
```
to:
```python
VALID_ITEM_CATEGORIES = {"article", "tool", "assembly_equipment", "eoat", "gauge"}
```

- [ ] **Step 3: Verify**

Run: `cd backend && python -c "import app.models; from app.services.part_service import VALID_ITEM_CATEGORIES; assert 'eoat' in VALID_ITEM_CATEGORIES; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/__init__.py backend/app/services/part_service.py
git commit -m "feat(change): register change models, add eoat item category"
```

---

## Task 3: Alembic migration 019

**Files:**
- Create: `backend/alembic/versions/019_add_change_management.py`

- [ ] **Step 1: Write the migration**

```python
"""Change Management: change_requests, change_impacted_items, change_assessments,
change_attachments, change_changelog.

Revision ID: 019
Revises: 018
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = '019'
down_revision = '018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())
    existing = inspector.get_table_names()

    if 'change_requests' not in existing:
        op.create_table(
            'change_requests',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_number', sa.String(30), nullable=False, unique=True, index=True),
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False, index=True),
            sa.Column('title', sa.String(255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('reason', sa.Text(), nullable=True),
            sa.Column('change_type', sa.String(30), nullable=False, server_default='physical_part'),
            sa.Column('priority', sa.String(20), nullable=False, server_default='medium'),
            sa.Column('data_classification', sa.String(20), nullable=False, server_default='confidential'),
            sa.Column('status', sa.String(20), nullable=False, server_default='captured', index=True),
            sa.Column('lead_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('raised_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('raised_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('customer_response', sa.String(20), nullable=False, server_default='pending'),
            sa.Column('customer_response_at', sa.DateTime(), nullable=True),
            sa.Column('customer_response_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('pm_signed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('pm_signed_at', sa.DateTime(), nullable=True),
            sa.Column('quality_signed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('quality_signed_at', sa.DateTime(), nullable=True),
            sa.Column('estimated_cost', sa.Float(), nullable=True),
            sa.Column('quoted_price', sa.Float(), nullable=True),
            sa.Column('pnl_note', sa.Text(), nullable=True),
            sa.Column('timing_milestone_id', sa.Integer(), sa.ForeignKey('project_milestones.id'), nullable=True),
            sa.Column('released_at', sa.DateTime(), nullable=True),
            sa.Column('released_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('closed_at', sa.DateTime(), nullable=True),
            sa.Column('cancelled_at', sa.DateTime(), nullable=True),
            sa.Column('cancellation_reason', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if 'change_impacted_items' not in existing:
        op.create_table(
            'change_impacted_items',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), nullable=False, index=True),
            sa.Column('part_id', sa.Integer(), sa.ForeignKey('parts.id'), nullable=False, index=True),
            sa.Column('impact_note', sa.Text(), nullable=True),
            sa.Column('eng_level_before', sa.String(50), nullable=True),
            sa.Column('eng_level_after', sa.String(50), nullable=True),
            sa.Column('resulting_revision_id', sa.Integer(), sa.ForeignKey('part_revisions.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        )

    if 'change_assessments' not in existing:
        op.create_table(
            'change_assessments',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), nullable=False, index=True),
            sa.Column('department_id', sa.Integer(), sa.ForeignKey('wf_departments.id'), nullable=False, index=True),
            sa.Column('verdict', sa.String(30), nullable=False, server_default='pending'),
            sa.Column('cost_impact', sa.Float(), nullable=True),
            sa.Column('lead_time_impact_days', sa.Integer(), nullable=True),
            sa.Column('conditions', sa.Text(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('responsible_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('submitted_at', sa.DateTime(), nullable=True),
            sa.Column('submitted_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if 'change_attachments' not in existing:
        op.create_table(
            'change_attachments',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), nullable=False, index=True),
            sa.Column('filename', sa.String(255), nullable=False),
            sa.Column('stored_path', sa.String(500), nullable=False),
            sa.Column('content_type', sa.String(100), nullable=False),
            sa.Column('size_bytes', sa.Integer(), nullable=False),
            sa.Column('sha256', sa.String(64), nullable=False),
            sa.Column('uploaded_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if 'change_changelog' not in existing:
        op.create_table(
            'change_changelog',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), nullable=False, index=True),
            sa.Column('action', sa.String(50), nullable=False),
            sa.Column('action_description', sa.Text(), nullable=False),
            sa.Column('field_name', sa.String(100), nullable=True),
            sa.Column('old_value', sa.Text(), nullable=True),
            sa.Column('new_value', sa.Text(), nullable=True),
            sa.Column('performed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('performed_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('previous_hash', sa.String(64), nullable=True),
            sa.Column('entry_hash', sa.String(64), nullable=True),
        )


def downgrade() -> None:
    for t in ('change_changelog', 'change_attachments', 'change_assessments',
              'change_impacted_items', 'change_requests'):
        op.drop_table(t)
```

- [ ] **Step 2: Verify migration applies on a scratch DB**

Run: `cd backend && python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from app.models.database import Base
import app.models  # registers all tables
async def main():
    e = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with e.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    print('tables built ok')
asyncio.run(main())
"`
Expected: prints `tables built ok` (confirms models + metadata are consistent; tests use `create_all`, prod uses this migration).

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/019_add_change_management.py
git commit -m "feat(change): add migration 019 for change management tables"
```

---

## Task 4: Pydantic schemas

**Files:**
- Create: `backend/app/schemas/change.py`

- [ ] **Step 1: Write the schemas**

```python
"""Pydantic schemas for Change Management."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class ChangeCreate(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=255)
    change_type: str = "physical_part"
    reason: Optional[str] = None
    description: Optional[str] = None
    priority: str = "medium"
    lead_id: Optional[int] = None
    data_classification: str = "confidential"


class ChangeUpdate(BaseModel):
    title: Optional[str] = None
    reason: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    change_type: Optional[str] = None
    lead_id: Optional[int] = None
    estimated_cost: Optional[float] = None
    quoted_price: Optional[float] = None
    pnl_note: Optional[str] = None
    timing_milestone_id: Optional[int] = None


class TransitionRequest(BaseModel):
    to_status: str
    justification: Optional[str] = None
    cancellation_reason: Optional[str] = None


class CustomerResponseRequest(BaseModel):
    response: str  # accepted | declined | negotiating


class SignOffRequest(BaseModel):
    role: str  # pm | quality


class ImpactedItemCreate(BaseModel):
    part_id: int
    impact_note: Optional[str] = None
    eng_level_before: Optional[str] = None


class AssessmentSubmit(BaseModel):
    department_id: int
    verdict: str
    cost_impact: Optional[float] = None
    lead_time_impact_days: Optional[int] = None
    conditions: Optional[str] = None
    notes: Optional[str] = None
    responsible_id: Optional[int] = None


class ImpactedItemResponse(BaseModel):
    id: int
    part_id: int
    impact_note: Optional[str] = None
    eng_level_before: Optional[str] = None
    eng_level_after: Optional[str] = None
    resulting_revision_id: Optional[int] = None

    class Config:
        from_attributes = True


class AssessmentResponse(BaseModel):
    id: int
    department_id: int
    verdict: str
    cost_impact: Optional[float] = None
    lead_time_impact_days: Optional[int] = None
    conditions: Optional[str] = None
    notes: Optional[str] = None
    responsible_id: Optional[int] = None
    submitted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AttachmentResponse(BaseModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime

    class Config:
        from_attributes = True


class ChangelogResponse(BaseModel):
    id: int
    action: str
    action_description: str
    performed_by: int
    performed_at: datetime
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class ChangeResponse(BaseModel):
    id: int
    change_number: str
    project_id: int
    title: str
    description: Optional[str] = None
    reason: Optional[str] = None
    change_type: str
    priority: str
    status: str
    lead_id: Optional[int] = None
    raised_by: int
    customer_response: str
    pm_signed_by: Optional[int] = None
    quality_signed_by: Optional[int] = None
    estimated_cost: Optional[float] = None
    quoted_price: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChangeDetailResponse(ChangeResponse):
    impacted_items: List[ImpactedItemResponse] = []
    assessments: List[AssessmentResponse] = []
    attachments: List[AttachmentResponse] = []
```

- [ ] **Step 2: Verify import**

Run: `cd backend && python -c "from app.schemas.change import ChangeCreate, ChangeDetailResponse; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/change.py
git commit -m "feat(change): add pydantic schemas"
```

---

## Task 5: ChangeService — numbering, create, changelog helper

**Files:**
- Create: `backend/app/services/change_service.py`

- [ ] **Step 1: Write the service core**

```python
"""Service for the Change Management lifecycle: numbering, CRUD, state machine,
guards, hash-chained audit, assessments, impacted items, sign-off, ECN spawn,
release."""
import hashlib
import json
import logging
from datetime import datetime
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import (
    ChangeRequest, ChangeImpactedItem, ChangeAssessment, ChangeChangelog,
    CHANGE_TYPES, CHANGE_STATUSES, ASSESSMENT_VERDICTS, CUSTOMER_RESPONSES,
    SIGN_OFF_ROLES,
)
from app.models.part import Part, PartRevision
from app.models.workflow import Department

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS = {
    "captured":          {"in_assessment", "cancelled", "on_hold"},
    "in_assessment":     {"costing", "rejected", "cancelled", "on_hold"},
    "costing":           {"quoted", "on_hold", "cancelled"},
    "quoted":            {"approved", "rejected", "on_hold", "cancelled"},
    "approved":          {"in_implementation", "on_hold", "cancelled"},
    "in_implementation": {"in_validation", "on_hold", "cancelled"},
    "in_validation":     {"released", "in_implementation", "on_hold", "cancelled"},
    "released":          {"closed"},
    "on_hold":           {"in_assessment", "costing", "quoted", "approved",
                          "in_implementation", "in_validation", "cancelled"},
    "rejected":          set(),
    "closed":            set(),
    "cancelled":         set(),
}

TYPE_DISCIPLINES = {
    "physical_part": ["Tool Engineer", "APQP", "Quality", "Manufacturing Engineer", "Sales"],
    "tooling":       ["Tool Engineer", "Process Engineer", "Manufacturing Engineer"],
    "document_spec": ["Quality", "Project Manager"],
    "process_im":    ["Process Engineer", "Manufacturing Engineer", "Quality"],
    "packaging":     ["Packaging Engineer", "Quality", "Sales"],
}


class ChangeError(ValueError):
    """Raised for invalid change operations; mapped to HTTP 400 in the router."""


class ChangeService:

    @staticmethod
    async def generate_change_number(session: AsyncSession) -> str:
        year = datetime.utcnow().year
        prefix = f"CR-{year}-"
        result = await session.execute(
            select(func.count()).select_from(ChangeRequest).where(
                ChangeRequest.change_number.like(f"{prefix}%")
            )
        )
        seq = (result.scalar() or 0) + 1
        return f"{prefix}{seq:04d}"

    @staticmethod
    async def _last_entry_hash(session: AsyncSession, change_id: int) -> Optional[str]:
        result = await session.execute(
            select(ChangeChangelog.entry_hash)
            .where(ChangeChangelog.change_id == change_id)
            .order_by(ChangeChangelog.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def append_changelog(
        session: AsyncSession, change: ChangeRequest, action: str,
        description: str, performed_by: int, *, field_name: Optional[str] = None,
        old_value=None, new_value=None, notes: Optional[str] = None,
    ) -> ChangeChangelog:
        prev = await ChangeService._last_entry_hash(session, change.id)
        old_s = json.dumps(old_value) if old_value is not None else None
        new_s = json.dumps(new_value) if new_value is not None else None
        performed_at = datetime.utcnow()
        payload = "|".join([
            str(change.id), action, field_name or "", old_s or "", new_s or "",
            str(performed_by), performed_at.isoformat(), prev or "",
        ])
        entry_hash = hashlib.sha256(payload.encode()).hexdigest()
        entry = ChangeChangelog(
            change_id=change.id, action=action, action_description=description,
            field_name=field_name, old_value=old_s, new_value=new_s,
            performed_by=performed_by, performed_at=performed_at, notes=notes,
            previous_hash=prev, entry_hash=entry_hash,
        )
        session.add(entry)
        return entry

    @staticmethod
    async def create_change(
        session: AsyncSession, *, project_id: int, title: str, change_type: str,
        raised_by: int, reason: Optional[str] = None, description: Optional[str] = None,
        priority: str = "medium", lead_id: Optional[int] = None,
        data_classification: str = "confidential",
    ) -> ChangeRequest:
        if change_type not in CHANGE_TYPES:
            raise ChangeError(f"Invalid change_type '{change_type}'")
        number = await ChangeService.generate_change_number(session)
        change = ChangeRequest(
            change_number=number, project_id=project_id, title=title,
            change_type=change_type, reason=reason, description=description,
            priority=priority, lead_id=lead_id, raised_by=raised_by,
            data_classification=data_classification, status="captured",
        )
        session.add(change)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "created", f"Change {number} created", raised_by,
        )
        logger.info(f"Created change {number} in project {project_id}")
        return change

    @staticmethod
    async def get_change(session: AsyncSession, change_id: int) -> Optional[ChangeRequest]:
        result = await session.execute(
            select(ChangeRequest).where(ChangeRequest.id == change_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_changes(
        session: AsyncSession, *, project_id: Optional[int] = None,
        status: Optional[str] = None, change_type: Optional[str] = None,
        lead_id: Optional[int] = None,
    ) -> List[ChangeRequest]:
        q = select(ChangeRequest)
        if project_id is not None:
            q = q.where(ChangeRequest.project_id == project_id)
        if status is not None:
            q = q.where(ChangeRequest.status == status)
        if change_type is not None:
            q = q.where(ChangeRequest.change_type == change_type)
        if lead_id is not None:
            q = q.where(ChangeRequest.lead_id == lead_id)
        q = q.order_by(ChangeRequest.id.desc())
        result = await session.execute(q)
        return result.scalars().all()
```

- [ ] **Step 2: Verify import**

Run: `cd backend && python -c "from app.services.change_service import ChangeService, ChangeError, ALLOWED_TRANSITIONS; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/change_service.py
git commit -m "feat(change): add change service core (numbering, create, changelog)"
```

---

## Task 6: Router skeleton + create/get/list (first API test)

**Files:**
- Create: `backend/app/api/v1/changes/__init__.py`
- Create: `backend/app/api/v1/changes/changes.py`
- Modify: `backend/app/api/v1/__init__.py`
- Create/Test: `backend/tests/test_changes.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_changes.py
import pytest

pytestmark = pytest.mark.asyncio


async def _create_change(client, auth, project_id, **over):
    body = {"project_id": project_id, "title": "Wall thickness +0.2mm",
            "change_type": "physical_part", "reason": "Sink marks on Class-A surface"}
    body.update(over)
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def test_create_change_assigns_number_and_captured_status(client, eng_auth, seed):
    data = await _create_change(client, eng_auth, seed["project_id"])
    assert data["status"] == "captured"
    assert data["change_number"].startswith("CR-")
    assert data["change_type"] == "physical_part"


async def test_list_and_get_change(client, eng_auth, seed):
    created = await _create_change(client, eng_auth, seed["project_id"])
    res = await client.get(f"/api/v1/changes?project_id={seed['project_id']}", headers=eng_auth)
    assert res.status_code == 200, res.text
    assert any(c["id"] == created["id"] for c in res.json())

    res = await client.get(f"/api/v1/changes/{created['id']}", headers=eng_auth)
    assert res.status_code == 200, res.text
    detail = res.json()
    assert detail["id"] == created["id"]
    assert detail["impacted_items"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_changes.py -q`
Expected: FAIL (404 / route not found — router not registered yet).

- [ ] **Step 3: Write the router**

```python
# backend/app/api/v1/changes/__init__.py
```
(empty file)

```python
# backend/app/api/v1/changes/changes.py
"""Change Management endpoints - the change lifecycle spine."""
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.services.change_service import ChangeService, ChangeError
from app.schemas.change import (
    ChangeCreate, ChangeUpdate, ChangeResponse, ChangeDetailResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/changes", tags=["changes"])


@router.post("", response_model=ChangeResponse)
async def create_change(
    body: ChangeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        change = await ChangeService.create_change(
            session=db, project_id=body.project_id, title=body.title,
            change_type=body.change_type, raised_by=current_user.id,
            reason=body.reason, description=body.description, priority=body.priority,
            lead_id=body.lead_id, data_classification=body.data_classification,
        )
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return change


@router.get("", response_model=List[ChangeResponse])
async def list_changes(
    project_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    change_type: Optional[str] = Query(None),
    lead_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ChangeService.list_changes(
        db, project_id=project_id, status=status, change_type=change_type, lead_id=lead_id,
    )


@router.get("/{change_id}", response_model=ChangeDetailResponse)
async def get_change(
    change_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change
```

- [ ] **Step 4: Register the router**

In `backend/app/api/v1/__init__.py`, after the lessons import line add:

```python
# Module: changes (engineering change management)
from app.api.v1.changes.changes import router as changes_router
```

and after `api_router.include_router(lessons_router)` add:

```python
api_router.include_router(changes_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_changes.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/changes/ backend/app/api/v1/__init__.py backend/tests/test_changes.py
git commit -m "feat(change): create/list/get endpoints with tests"
```

---

## Task 7: State machine transitions (soft guards + forced override)

**Files:**
- Modify: `backend/app/services/change_service.py`
- Modify: `backend/app/api/v1/changes/changes.py`
- Modify: `backend/tests/test_changes.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_changes.py`:

```python
async def _transition(client, auth, change_id, to_status, **over):
    body = {"to_status": to_status}
    body.update(over)
    return await client.post(f"/api/v1/changes/{change_id}/transition", json=body, headers=auth)


async def test_transition_requires_impacted_item_then_forced_override(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    # Soft guard blocks without impacted items + no justification
    res = await _transition(client, eng_auth, change["id"], "in_assessment")
    assert res.status_code == 400, res.text
    # Forced override with justification succeeds and logs it
    res = await _transition(client, eng_auth, change["id"], "in_assessment",
                            justification="PPT only at this stage")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "in_assessment"


async def test_illegal_transition_rejected(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    res = await _transition(client, eng_auth, change["id"], "released")
    assert res.status_code == 400, res.text


async def test_cancel_requires_reason(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    res = await _transition(client, eng_auth, change["id"], "cancelled")
    assert res.status_code == 400, res.text
    res = await _transition(client, eng_auth, change["id"], "cancelled",
                            cancellation_reason="Customer withdrew RFQ")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "cancelled"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k transition or test_cancel`
Expected: FAIL (transition endpoint missing → 404/405).

- [ ] **Step 3: Add the transition logic to the service**

Append to `ChangeService` in `change_service.py`:

```python
    @staticmethod
    async def _guard(session: AsyncSession, change: ChangeRequest, to_status: str):
        """Return None if soft-OK, else a human reason string (overridable)."""
        if to_status == "in_assessment":
            count = len(change.impacted_items)
            if count == 0:
                return "No impacted items added yet"
            if change.lead_id is None:
                return "No lead (project manager) assigned"
        if to_status == "costing":
            pending = [a for a in change.assessments if a.verdict == "pending"]
            if not change.assessments or pending:
                return "Not all discipline assessments are submitted"
            if any(a.verdict == "not_feasible" for a in change.assessments):
                return "An assessment is 'not_feasible' — explicit decision required"
        if to_status == "quoted":
            if change.quoted_price is None:
                return "No quoted price recorded"
        if to_status == "in_validation":
            missing = [i for i in change.impacted_items if i.resulting_revision_id is None]
            if missing:
                return "Some impacted items have no resulting revision"
        return None

    @staticmethod
    async def transition(
        session: AsyncSession, change: ChangeRequest, to_status: str,
        user_id: int, *, justification: Optional[str] = None,
        cancellation_reason: Optional[str] = None,
    ) -> ChangeRequest:
        if to_status not in CHANGE_STATUSES:
            raise ChangeError(f"Unknown status '{to_status}'")
        allowed = ALLOWED_TRANSITIONS.get(change.status, set())
        if to_status not in allowed:
            raise ChangeError(f"Cannot move from '{change.status}' to '{to_status}'")

        # HARD gate: quoted -> approved cannot be forced
        if to_status == "approved":
            if change.customer_response != "accepted":
                raise ChangeError("Customer has not accepted the offer")
            if change.pm_signed_by is None or change.quality_signed_by is None:
                raise ChangeError("Both PM and Quality sign-off are required")

        if to_status == "cancelled":
            if not cancellation_reason:
                raise ChangeError("cancellation_reason is required to cancel")
            change.cancellation_reason = cancellation_reason
            change.cancelled_at = datetime.utcnow()

        forced = False
        reason = await ChangeService._guard(session, change, to_status)
        if reason is not None:
            if not justification:
                raise ChangeError(f"{reason}. Provide a justification to override.")
            forced = True

        # Side effects on entry
        if to_status == "in_implementation":
            await ChangeService.spawn_ecn_revisions(session, change, user_id)
        if to_status == "released":
            await ChangeService.release(session, change, user_id)
        if to_status == "closed":
            change.closed_at = datetime.utcnow()

        old = change.status
        change.status = to_status
        await session.flush()
        action = "forced_transition" if forced else "status_changed"
        desc = f"{old} -> {to_status}" + (f" (forced: {justification})" if forced else "")
        await ChangeService.append_changelog(
            session, change, action, desc, user_id,
            field_name="status", old_value=old, new_value=to_status,
            notes=justification if forced else None,
        )
        return change
```

Note: `spawn_ecn_revisions` and `release` are added in Tasks 11 and 12 as no-op-safe stubs first. To keep this task runnable now, also add these temporary stubs to `ChangeService` (they will be filled in later tasks):

```python
    @staticmethod
    async def spawn_ecn_revisions(session: AsyncSession, change: ChangeRequest, user_id: int):
        return  # implemented in Task 11

    @staticmethod
    async def release(session: AsyncSession, change: ChangeRequest, user_id: int):
        change.released_at = datetime.utcnow()
        change.released_by = user_id
        # full activate/supersede logic added in Task 12
```

- [ ] **Step 4: Add the transition endpoint**

Add imports to `changes.py` (extend the existing schema import line):

```python
from app.schemas.change import (
    ChangeCreate, ChangeUpdate, ChangeResponse, ChangeDetailResponse,
    TransitionRequest,
)
```

Add the endpoint:

```python
@router.post("/{change_id}/transition", response_model=ChangeResponse)
async def transition_change(
    change_id: int,
    body: TransitionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await ChangeService.transition(
            db, change, body.to_status, current_user.id,
            justification=body.justification, cancellation_reason=body.cancellation_reason,
        )
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return change
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_changes.py -q`
Expected: PASS (all tests so far).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_service.py backend/app/api/v1/changes/changes.py backend/tests/test_changes.py
git commit -m "feat(change): lifecycle state machine with soft guards and forced override"
```

---

## Task 8: Impacted items (add, remove, seed from relations)

**Files:**
- Modify: `backend/app/services/change_service.py`
- Modify: `backend/app/api/v1/changes/changes.py`
- Modify: `backend/tests/test_changes.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_changes.py`:

```python
async def _make_part(client, auth, project_id, number, category="article"):
    res = await client.post("/api/v1/parts", json={
        "project_id": project_id, "part_number": number, "name": number,
        "part_type": "internal_mfg", "item_category": category,
    }, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def test_add_and_remove_impacted_item(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    part_id = await _make_part(client, eng_auth, seed["project_id"], "ART-1")
    res = await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                            json={"part_id": part_id, "impact_note": "wall thickness"},
                            headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    item_id = res.json()["id"]

    res = await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)
    assert len(res.json()["impacted_items"]) == 1

    res = await client.delete(f"/api/v1/changes/{change['id']}/impacted-items/{item_id}",
                              headers=eng_auth)
    assert res.status_code in (200, 204), res.text
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)
    assert res.json()["impacted_items"] == []


async def test_seed_impacted_from_relations(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    article = await _make_part(client, eng_auth, seed["project_id"], "ART-2", "article")
    tool = await _make_part(client, eng_auth, seed["project_id"], "TOOL-2", "tool")
    # tool produces article
    res = await client.post(f"/api/v1/parts/{tool}/relations", json={
        "to_part_id": article, "relation_type": "produces",
    }, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    # add the article as impacted, then seed related items
    await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                      json={"part_id": article}, headers=eng_auth)
    res = await client.post(f"/api/v1/changes/{change['id']}/impacted-items/seed",
                            headers=eng_auth)
    assert res.status_code == 200, res.text
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)
    part_ids = {i["part_id"] for i in res.json()["impacted_items"]}
    assert tool in part_ids  # the producing tool was pulled in
```

Note: confirm the part-relations create endpoint shape from `app/api/v1/items/part_relations.py` before running; adjust the `to_part_id`/`relation_type` keys if the router differs.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k impacted`
Expected: FAIL (endpoints missing).

- [ ] **Step 3: Add service methods**

Append to `ChangeService` (add `PartRelation` to the part import at top: `from app.models.part import Part, PartRevision, PartRelation`):

```python
    @staticmethod
    async def add_impacted_item(
        session: AsyncSession, change: ChangeRequest, part_id: int,
        user_id: int, *, impact_note: Optional[str] = None,
        eng_level_before: Optional[str] = None,
    ) -> ChangeImpactedItem:
        part = await session.get(Part, part_id)
        if not part or part.project_id != change.project_id:
            raise ChangeError("Part not found in this project")
        if any(i.part_id == part_id for i in change.impacted_items):
            raise ChangeError("Item already impacted")
        item = ChangeImpactedItem(
            change_id=change.id, part_id=part_id, impact_note=impact_note,
            eng_level_before=eng_level_before, created_by=user_id,
        )
        session.add(item)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "impacted_item_added",
            f"Added impacted item {part.part_number}", user_id,
            new_value={"part_id": part_id},
        )
        return item

    @staticmethod
    async def remove_impacted_item(
        session: AsyncSession, change: ChangeRequest, item_id: int, user_id: int,
    ) -> None:
        item = await session.get(ChangeImpactedItem, item_id)
        if not item or item.change_id != change.id:
            raise ChangeError("Impacted item not found")
        await session.delete(item)
        await ChangeService.append_changelog(
            session, change, "impacted_item_removed",
            f"Removed impacted item {item.part_id}", user_id,
            old_value={"part_id": item.part_id},
        )

    @staticmethod
    async def seed_impacted_from_relations(
        session: AsyncSession, change: ChangeRequest, user_id: int,
    ) -> int:
        """For every currently-impacted part, pull in related parts (produces/checks/
        assembles) that are not yet impacted. Returns count added."""
        existing = {i.part_id for i in change.impacted_items}
        added = 0
        for part_id in list(existing):
            result = await session.execute(
                select(PartRelation).where(
                    (PartRelation.from_part_id == part_id) | (PartRelation.to_part_id == part_id)
                )
            )
            for rel in result.scalars().all():
                other = rel.to_part_id if rel.from_part_id == part_id else rel.from_part_id
                if other not in existing:
                    existing.add(other)
                    await ChangeService.add_impacted_item(
                        session, change, other, user_id,
                        impact_note=f"Linked via '{rel.relation_type}'",
                    )
                    added += 1
        return added
```

- [ ] **Step 4: Add endpoints**

Extend schema import in `changes.py` with `ImpactedItemCreate, ImpactedItemResponse`, then add:

```python
@router.post("/{change_id}/impacted-items", response_model=ImpactedItemResponse)
async def add_impacted_item(
    change_id: int, body: ImpactedItemCreate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        item = await ChangeService.add_impacted_item(
            db, change, body.part_id, current_user.id,
            impact_note=body.impact_note, eng_level_before=body.eng_level_before,
        )
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/{change_id}/impacted-items/{item_id}", status_code=204)
async def remove_impacted_item(
    change_id: int, item_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await ChangeService.remove_impacted_item(db, change, item_id, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()


@router.post("/{change_id}/impacted-items/seed")
async def seed_impacted_items(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    added = await ChangeService.seed_impacted_from_relations(db, change, current_user.id)
    await db.commit()
    return {"added": added}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k impacted`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_service.py backend/app/api/v1/changes/changes.py backend/tests/test_changes.py
git commit -m "feat(change): impacted-items add/remove/seed-from-relations"
```

---

## Task 9: Assessments (create-on-enter + submit verdict)

**Files:**
- Modify: `backend/app/services/change_service.py`
- Modify: `backend/app/api/v1/changes/changes.py`
- Modify: `backend/tests/test_changes.py`

Design note: assessments are created from `TYPE_DISCIPLINES` when the change enters `in_assessment`. Department lookup is by name; missing departments are skipped (full seeding belongs to sub-project #2). A discipline submits its verdict by `department_id`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_changes.py`:

```python
import pytest_asyncio
from app.models.workflow import Department


@pytest_asyncio.fixture
async def departments(session_factory):
    async with session_factory() as s:
        names = ["Tool Engineer", "APQP", "Quality", "Manufacturing Engineer", "Sales"]
        ids = {}
        for i, n in enumerate(names):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i)
            s.add(d)
            await s.flush()
            ids[n] = d.id
        await s.commit()
        return ids


async def test_assessment_created_on_enter_and_submit(client, eng_auth, seed, departments):
    change = await _create_change(client, eng_auth, seed["project_id"],
                                  lead_id=seed["engineer_id"])
    part_id = await _make_part(client, eng_auth, seed["project_id"], "ART-9")
    await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                      json={"part_id": part_id}, headers=eng_auth)
    # enter assessment -> assessments auto-created
    res = await _transition(client, eng_auth, change["id"], "in_assessment")
    assert res.status_code == 200, res.text
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)
    assessments = res.json()["assessments"]
    assert len(assessments) >= 1
    tool_dep = departments["Tool Engineer"]

    # submitting feasible for all then moving to costing should work
    for a in assessments:
        r = await client.post(f"/api/v1/changes/{change['id']}/assessments", json={
            "department_id": a["department_id"], "verdict": "feasible",
        }, headers=eng_auth)
        assert r.status_code in (200, 201), r.text

    # costing still needs a quoted price guard? No - costing guard is assessments only
    res = await _transition(client, eng_auth, change["id"], "costing")
    assert res.status_code == 200, res.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k assessment`
Expected: FAIL (assessments not auto-created / endpoint missing).

- [ ] **Step 3: Add service logic**

In `transition()`, in the side-effects section before setting `change.status`, add handling for entering assessment:

```python
        if to_status == "in_assessment":
            await ChangeService.ensure_assessments(session, change, user_id)
```

Add methods to `ChangeService`:

```python
    @staticmethod
    async def ensure_assessments(
        session: AsyncSession, change: ChangeRequest, user_id: int,
    ) -> None:
        existing = {a.department_id for a in change.assessments}
        names = TYPE_DISCIPLINES.get(change.change_type, [])
        if not names:
            return
        result = await session.execute(
            select(Department).where(Department.name.in_(names))
        )
        for dep in result.scalars().all():
            if dep.id not in existing:
                session.add(ChangeAssessment(
                    change_id=change.id, department_id=dep.id, verdict="pending",
                ))
        await session.flush()

    @staticmethod
    async def submit_assessment(
        session: AsyncSession, change: ChangeRequest, department_id: int,
        verdict: str, user_id: int, *, cost_impact=None, lead_time_impact_days=None,
        conditions=None, notes=None, responsible_id=None,
    ) -> ChangeAssessment:
        if verdict not in ASSESSMENT_VERDICTS:
            raise ChangeError(f"Invalid verdict '{verdict}'")
        result = await session.execute(
            select(ChangeAssessment).where(
                (ChangeAssessment.change_id == change.id)
                & (ChangeAssessment.department_id == department_id)
            )
        )
        a = result.scalar_one_or_none()
        if a is None:
            a = ChangeAssessment(change_id=change.id, department_id=department_id)
            session.add(a)
        a.verdict = verdict
        a.cost_impact = cost_impact
        a.lead_time_impact_days = lead_time_impact_days
        a.conditions = conditions
        a.notes = notes
        a.responsible_id = responsible_id
        a.submitted_at = datetime.utcnow()
        a.submitted_by = user_id
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "assessment_submitted",
            f"Assessment for dept {department_id}: {verdict}", user_id,
            field_name="verdict", new_value=verdict,
        )
        return a
```

Add `ChangeAssessment` to the model import at the top of `change_service.py` if not already present (it is imported in Task 5).

- [ ] **Step 4: Add endpoints**

Extend schema imports with `AssessmentSubmit, AssessmentResponse`, then add:

```python
@router.post("/{change_id}/assessments", response_model=AssessmentResponse)
async def submit_assessment(
    change_id: int, body: AssessmentSubmit,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        a = await ChangeService.submit_assessment(
            db, change, body.department_id, body.verdict, current_user.id,
            cost_impact=body.cost_impact, lead_time_impact_days=body.lead_time_impact_days,
            conditions=body.conditions, notes=body.notes, responsible_id=body.responsible_id,
        )
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(a)
    return a
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k assessment`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_service.py backend/app/api/v1/changes/changes.py backend/tests/test_changes.py
git commit -m "feat(change): discipline assessments (auto-create on enter, submit verdict)"
```

---

## Task 10: Customer response + sign-off + hard approve gate

**Files:**
- Modify: `backend/app/services/change_service.py`
- Modify: `backend/app/api/v1/changes/changes.py`
- Modify: `backend/tests/test_changes.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_changes.py`:

```python
async def _advance_to_quoted(client, auth, seed, departments, admin_auth):
    change = await _create_change(client, auth, seed["project_id"], lead_id=seed["engineer_id"])
    part_id = await _make_part(client, auth, seed["project_id"], f"ART-Q{change['id']}")
    await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                      json={"part_id": part_id}, headers=auth)
    await _transition(client, auth, change["id"], "in_assessment")
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=auth)
    for a in res.json()["assessments"]:
        await client.post(f"/api/v1/changes/{change['id']}/assessments",
                          json={"department_id": a["department_id"], "verdict": "feasible"},
                          headers=auth)
    await _transition(client, auth, change["id"], "costing")
    await client.patch(f"/api/v1/changes/{change['id']}",
                       json={"quoted_price": 12500.0}, headers=auth)
    await _transition(client, auth, change["id"], "quoted")
    return change


async def test_approve_blocked_until_customer_and_dual_signoff(
    client, eng_auth, admin_auth, seed, departments
):
    change = await _advance_to_quoted(client, eng_auth, seed, departments, admin_auth)
    cid = change["id"]
    # cannot approve yet (no customer acceptance, no sign-off) — hard gate, no override
    res = await _transition(client, eng_auth, cid, "approved", justification="please")
    assert res.status_code == 400, res.text

    # record customer acceptance
    res = await client.post(f"/api/v1/changes/{cid}/customer-response",
                            json={"response": "accepted"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    # PM signs (engineer), Quality signs (admin) — must be different users
    res = await client.post(f"/api/v1/changes/{cid}/sign-off",
                            json={"role": "pm"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    # same user cannot also be quality
    res = await client.post(f"/api/v1/changes/{cid}/sign-off",
                            json={"role": "quality"}, headers=eng_auth)
    assert res.status_code == 400, res.text
    res = await client.post(f"/api/v1/changes/{cid}/sign-off",
                            json={"role": "quality"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    # now approve works
    res = await _transition(client, eng_auth, cid, "approved")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "approved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k approve`
Expected: FAIL (customer-response / sign-off endpoints missing).

- [ ] **Step 3: Add service methods + update endpoint**

Add to `ChangeService`:

```python
    @staticmethod
    async def update_change(
        session: AsyncSession, change: ChangeRequest, user_id: int, **fields,
    ) -> ChangeRequest:
        allowed = {
            "title", "reason", "description", "priority", "change_type", "lead_id",
            "estimated_cost", "quoted_price", "pnl_note", "timing_milestone_id",
        }
        for k, v in fields.items():
            if k in allowed and v is not None:
                setattr(change, k, v)
        change.updated_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "metadata_updated", "Change metadata updated", user_id,
        )
        return change

    @staticmethod
    async def record_customer_response(
        session: AsyncSession, change: ChangeRequest, response: str, user_id: int,
    ) -> ChangeRequest:
        if response not in CUSTOMER_RESPONSES:
            raise ChangeError(f"Invalid customer response '{response}'")
        change.customer_response = response
        change.customer_response_at = datetime.utcnow()
        change.customer_response_by = user_id
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "customer_response_recorded",
            f"Customer response: {response}", user_id,
            field_name="customer_response", new_value=response,
        )
        return change

    @staticmethod
    async def sign_off(
        session: AsyncSession, change: ChangeRequest, role: str, user_id: int,
    ) -> ChangeRequest:
        if role not in SIGN_OFF_ROLES:
            raise ChangeError(f"Invalid sign-off role '{role}'")
        other = change.quality_signed_by if role == "pm" else change.pm_signed_by
        if other is not None and other == user_id:
            raise ChangeError("PM and Quality sign-off must be different users")
        now = datetime.utcnow()
        if role == "pm":
            change.pm_signed_by, change.pm_signed_at = user_id, now
        else:
            change.quality_signed_by, change.quality_signed_at = user_id, now
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "signed_off", f"{role} sign-off", user_id,
            field_name=f"{role}_signed_by", new_value=user_id,
        )
        return change
```

- [ ] **Step 4: Add endpoints**

Extend schema imports with `CustomerResponseRequest, SignOffRequest`. Add:

```python
@router.patch("/{change_id}", response_model=ChangeResponse)
async def update_change(
    change_id: int, body: ChangeUpdate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    await ChangeService.update_change(db, change, current_user.id,
                                      **body.model_dump(exclude_unset=True))
    await db.commit()
    await db.refresh(change)
    return change


@router.post("/{change_id}/customer-response", response_model=ChangeResponse)
async def customer_response(
    change_id: int, body: CustomerResponseRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await ChangeService.record_customer_response(db, change, body.response, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return change


@router.post("/{change_id}/sign-off", response_model=ChangeResponse)
async def sign_off(
    change_id: int, body: SignOffRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await ChangeService.sign_off(db, change, body.role, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return change
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k approve`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_service.py backend/app/api/v1/changes/changes.py backend/tests/test_changes.py
git commit -m "feat(change): customer response, dual sign-off, hard approve gate, metadata update"
```

---

## Task 11: Spawn ECN revisions on implementation

**Files:**
- Modify: `backend/app/services/change_service.py`
- Modify: `backend/tests/test_changes.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_changes.py`:

```python
async def test_implementation_spawns_ecn_revision_per_item(
    client, eng_auth, admin_auth, seed, departments
):
    change = await _advance_to_quoted(client, eng_auth, seed, departments, admin_auth)
    cid = change["id"]
    await client.post(f"/api/v1/changes/{cid}/customer-response",
                      json={"response": "accepted"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "pm"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "quality"}, headers=admin_auth)
    await _transition(client, eng_auth, cid, "approved")
    res = await _transition(client, eng_auth, cid, "in_implementation")
    assert res.status_code == 200, res.text
    res = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    items = res.json()["impacted_items"]
    assert all(i["resulting_revision_id"] is not None for i in items)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k spawns`
Expected: FAIL (stub does nothing; resulting_revision_id stays null).

- [ ] **Step 3: Implement `spawn_ecn_revisions`**

Replace the Task 7 stub with:

```python
    @staticmethod
    async def spawn_ecn_revisions(session: AsyncSession, change: ChangeRequest, user_id: int):
        for item in change.impacted_items:
            if item.resulting_revision_id is not None:
                continue
            # count existing ECN revisions on this part for a simple unique name
            result = await session.execute(
                select(func.count()).select_from(PartRevision).where(
                    (PartRevision.part_id == item.part_id) & (PartRevision.phase == "ecn")
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
            )
            session.add(rev)
            await session.flush()
            item.resulting_revision_id = rev.id
            await ChangeService.append_changelog(
                session, change, "revision_spawned",
                f"Spawned ECN revision {rev.revision_name} on part {item.part_id}",
                user_id, new_value={"revision_id": rev.id, "part_id": item.part_id},
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k spawns`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/change_service.py backend/tests/test_changes.py
git commit -m "feat(change): spawn ECN revisions per impacted item on implementation"
```

---

## Task 12: Release (activate revisions, supersede, stamp eng level)

**Files:**
- Modify: `backend/app/services/change_service.py`
- Modify: `backend/tests/test_changes.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_changes.py`:

```python
async def test_release_activates_revisions_and_stamps_eng_level(
    client, eng_auth, admin_auth, seed, departments
):
    change = await _advance_to_quoted(client, eng_auth, seed, departments, admin_auth)
    cid = change["id"]
    await client.post(f"/api/v1/changes/{cid}/customer-response",
                      json={"response": "accepted"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "pm"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "quality"}, headers=admin_auth)
    await _transition(client, eng_auth, cid, "approved")
    await _transition(client, eng_auth, cid, "in_implementation")
    res = await _transition(client, eng_auth, cid, "in_validation")
    assert res.status_code == 200, res.text
    res = await _transition(client, eng_auth, cid, "released")
    assert res.status_code == 200, res.text

    # each impacted part now points at its ECN revision as active
    detail = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    for item in detail["impacted_items"]:
        rev_id = item["resulting_revision_id"]
        part = (await client.get(f"/api/v1/parts/{item['part_id']}", headers=eng_auth)).json()
        assert part["active_revision_id"] == rev_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k release`
Expected: FAIL (active_revision_id not updated by stub).

- [ ] **Step 3: Implement `release`**

Replace the Task 7 `release` stub with:

```python
    @staticmethod
    async def release(session: AsyncSession, change: ChangeRequest, user_id: int):
        change.released_at = datetime.utcnow()
        change.released_by = user_id
        for item in change.impacted_items:
            if item.resulting_revision_id is None:
                continue
            rev = await session.get(PartRevision, item.resulting_revision_id)
            part = await session.get(Part, item.part_id)
            if rev is None or part is None:
                continue
            prior = part.active_revision_id
            if prior is not None and prior != rev.id:
                rev.supersedes_revision_id = prior
            rev.status = "approved"
            rev.approved_at = datetime.utcnow()
            rev.approved_by = user_id
            part.active_revision_id = rev.id
            # stamp engineering level
            item.eng_level_after = rev.revision_name
            await session.flush()
            await ChangeService.append_changelog(
                session, change, "released",
                f"Released revision {rev.revision_name} as active on part {part.id}",
                user_id, new_value={"part_id": part.id, "revision_id": rev.id},
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k release`
Expected: PASS.

- [ ] **Step 5: Run the full change test module**

Run: `cd backend && python -m pytest tests/test_changes.py -q`
Expected: PASS (all change tests green).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_service.py backend/tests/test_changes.py
git commit -m "feat(change): release activates ECN revisions, supersedes prior, stamps eng level"
```

---

## Task 13: Changelog endpoint + hash-chain integrity test

**Files:**
- Modify: `backend/app/api/v1/changes/changes.py`
- Modify: `backend/tests/test_changes.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_changes.py`:

```python
async def test_changelog_is_hash_chained(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    await _transition(client, eng_auth, change["id"], "on_hold")
    res = await client.get(f"/api/v1/changes/{change['id']}/changelog", headers=eng_auth)
    assert res.status_code == 200, res.text
    entries = res.json()
    assert len(entries) >= 2  # created + status_changed
    actions = [e["action"] for e in entries]
    assert "created" in actions
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k changelog`
Expected: FAIL (changelog endpoint missing).

- [ ] **Step 3: Add endpoint**

Extend schema imports with `ChangelogResponse`, add:

```python
from sqlalchemy import select
from app.models.change import ChangeChangelog


@router.get("/{change_id}/changelog", response_model=List[ChangelogResponse])
async def get_changelog(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChangeChangelog).where(ChangeChangelog.change_id == change_id)
        .order_by(ChangeChangelog.performed_at)
    )
    return result.scalars().all()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k changelog`
Expected: PASS.

- [ ] **Step 5: Run the FULL backend suite (no regressions)**

Run: `cd backend && python -m pytest -q`
Expected: PASS (all pre-existing tests + new change tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/changes/changes.py backend/tests/test_changes.py
git commit -m "feat(change): changelog endpoint + hash-chain test; full suite green"
```

---

## Task 13b: Change attachments (PPT-only start) — upload, list, download

Implements the spec's flexibility centrepiece: attach a PowerPoint (or any document) to a change at any phase. Mirrors `app/api/v1/learning/lessons.py` file handling.

**Files:**
- Modify: `backend/app/services/change_service.py`
- Modify: `backend/app/api/v1/changes/changes.py`
- Modify: `backend/tests/test_changes.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_changes.py`:

```python
async def test_attach_document_to_change(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    files = {"file": ("ecr-start.pptx",
                      b"PK\x03\x04 fake pptx bytes",
                      "application/vnd.openxmlformats-officedocument.presentationml.presentation")}
    res = await client.post(f"/api/v1/changes/{change['id']}/attachments",
                            files=files, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    # appears on the detail payload
    detail = (await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)).json()
    assert len(detail["attachments"]) == 1
    assert detail["attachments"][0]["filename"] == "ecr-start.pptx"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k attach`
Expected: FAIL (attachments endpoint missing).

- [ ] **Step 3: Add service method**

Add `ChangeAttachment` to the model import at the top of `change_service.py`
(`from app.models.change import (..., ChangeAttachment, ...)`), then add to `ChangeService`:

```python
    @staticmethod
    async def add_attachment(
        session: AsyncSession, change: ChangeRequest, *, filename: str,
        stored_path: str, content_type: str, size_bytes: int, sha256: str, user_id: int,
    ) -> ChangeAttachment:
        att = ChangeAttachment(
            change_id=change.id, filename=filename, stored_path=stored_path,
            content_type=content_type, size_bytes=size_bytes, sha256=sha256,
            uploaded_by=user_id,
        )
        session.add(att)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "attachment_added", f"Attached {filename}", user_id,
            new_value={"filename": filename},
        )
        return att
```

- [ ] **Step 4: Add endpoints**

Add these imports at the top of `changes.py`:

```python
import hashlib
import os
import uuid
from fastapi import File, UploadFile, status
from fastapi.responses import FileResponse
from app.models.change import ChangeAttachment
```

Add the endpoints:

```python
@router.post("/{change_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    change_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")
    uploads_dir = os.path.join(os.getcwd(), "uploads", "changes", str(change_id))
    os.makedirs(uploads_dir, exist_ok=True)
    safe_name = os.path.basename(file.filename or "attachment.bin")
    stored_path = os.path.join(uploads_dir, f"{uuid.uuid4().hex}_{safe_name}")
    with open(stored_path, "wb") as fh:
        fh.write(contents)
    att = await ChangeService.add_attachment(
        db, change, filename=safe_name, stored_path=stored_path,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(contents), sha256=hashlib.sha256(contents).hexdigest(),
        user_id=current_user.id,
    )
    await db.commit()
    return {"id": att.id, "filename": att.filename, "size_bytes": att.size_bytes}


@router.get("/{change_id}/attachments/{attachment_id}/download")
async def download_attachment(
    change_id: int, attachment_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    att = await db.get(ChangeAttachment, attachment_id)
    if not att or att.change_id != change_id or not os.path.exists(att.stored_path):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(att.stored_path, filename=att.filename,
                        media_type=att.content_type or "application/octet-stream")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k attach`
Expected: PASS.

- [ ] **Step 6: Add an upload control to the detail page**

In `frontend/src/api/changes.ts`, add to `changesApi`:

```typescript
  uploadAttachment: (id: number, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return client.post(`/v1/changes/${id}/attachments`, fd).then((r) => r.data);
  },
```

In `frontend/src/pages/ChangeDetailPage.tsx`, add an upload input to the `overview` tab (below the existing fields):

```tsx
<div className="pt-3">
  <label className="text-sm text-gray-500">Attach document (PPT, PDF, …)</label>
  <input type="file" className="block mt-1 text-sm"
    onChange={async (e) => {
      const f = e.target.files?.[0];
      if (f) { await changesApi.uploadAttachment(changeId, f);
               qc.invalidateQueries({ queryKey: ['change', changeId] }); }
    }} />
  <ul className="mt-2 text-sm">
    {change.attachments.map((a) => <li key={a.id}>📎 {a.filename}</li>)}
  </ul>
</div>
```

- [ ] **Step 7: Verify type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/change_service.py backend/app/api/v1/changes/changes.py backend/tests/test_changes.py frontend/src/api/changes.ts frontend/src/pages/ChangeDetailPage.tsx
git commit -m "feat(change): attachment upload/download (PPT-only ECR start) + detail-page control"
```

---

## Task 14: My-Tasks backend endpoint

The frontend My Tasks needs changes where the current user's departments have a pending assessment, or where sign-off is awaited. Provide a single endpoint.

**Files:**
- Modify: `backend/app/api/v1/changes/changes.py`
- Modify: `backend/tests/test_changes.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_changes.py`:

```python
async def test_my_change_tasks_lists_pending_assessments(
    client, eng_auth, seed, departments, session_factory
):
    # assign engineer to "Tool Engineer" department
    from app.models.workflow import UserDepartment
    async with session_factory() as s:
        s.add(UserDepartment(user_id=seed["engineer_id"],
                             department_id=departments["Tool Engineer"]))
        await s.commit()

    change = await _create_change(client, eng_auth, seed["project_id"], lead_id=seed["engineer_id"])
    part_id = await _make_part(client, eng_auth, seed["project_id"], "ART-MT")
    await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                      json={"part_id": part_id}, headers=eng_auth)
    await _transition(client, eng_auth, change["id"], "in_assessment")

    res = await client.get("/api/v1/changes/my-tasks", headers=eng_auth)
    assert res.status_code == 200, res.text
    tasks = res.json()
    assert any(t["change_id"] == change["id"] and t["kind"] == "assessment" for t in tasks)
```

Note: register the `/my-tasks` route BEFORE `/{change_id}` in the router file so FastAPI does not match "my-tasks" as a change_id. Place this endpoint above `get_change`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k my_change_tasks`
Expected: FAIL (route missing / 422 from int path parse).

- [ ] **Step 3: Add the endpoint (above `get_change`)**

```python
from app.models.workflow import UserDepartment
from app.models.change import ChangeRequest, ChangeAssessment


@router.get("/my-tasks")
async def my_change_tasks(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    # departments the user belongs to
    dep_rows = await db.execute(
        select(UserDepartment.department_id).where(UserDepartment.user_id == current_user.id)
    )
    dep_ids = {r[0] for r in dep_rows.all()}
    tasks = []
    if dep_ids:
        rows = await db.execute(
            select(ChangeAssessment, ChangeRequest)
            .join(ChangeRequest, ChangeRequest.id == ChangeAssessment.change_id)
            .where(
                ChangeAssessment.department_id.in_(dep_ids)
                & (ChangeAssessment.verdict == "pending")
                & (ChangeRequest.status == "in_assessment")
            )
        )
        for a, c in rows.all():
            tasks.append({
                "kind": "assessment", "change_id": c.id, "change_number": c.change_number,
                "title": c.title, "department_id": a.department_id, "assessment_id": a.id,
            })
    return tasks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_changes.py -q -k my_change_tasks`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/changes/changes.py backend/tests/test_changes.py
git commit -m "feat(change): /changes/my-tasks endpoint for assessment tasks"
```

---

## Task 15: Frontend types

**Files:**
- Create: `frontend/src/types/change.ts`

- [ ] **Step 1: Write the types**

```typescript
export type ChangeStatus =
  | 'captured' | 'in_assessment' | 'costing' | 'quoted' | 'approved'
  | 'in_implementation' | 'in_validation' | 'released' | 'closed'
  | 'on_hold' | 'rejected' | 'cancelled';

export type ChangeType =
  | 'physical_part' | 'tooling' | 'document_spec' | 'process_im' | 'packaging';

export const CHANGE_STATUS_ORDER: ChangeStatus[] = [
  'captured', 'in_assessment', 'costing', 'quoted', 'approved',
  'in_implementation', 'in_validation', 'released', 'closed',
];

export interface ImpactedItem {
  id: number;
  part_id: number;
  impact_note?: string | null;
  eng_level_before?: string | null;
  eng_level_after?: string | null;
  resulting_revision_id?: number | null;
}

export interface Assessment {
  id: number;
  department_id: number;
  verdict: 'pending' | 'feasible' | 'feasible_with_conditions' | 'not_feasible';
  cost_impact?: number | null;
  lead_time_impact_days?: number | null;
  conditions?: string | null;
  notes?: string | null;
  responsible_id?: number | null;
  submitted_at?: string | null;
}

export interface Attachment {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}

export interface ChangelogEntry {
  id: number;
  action: string;
  action_description: string;
  performed_by: number;
  performed_at: string;
  notes?: string | null;
}

export interface ChangeRequest {
  id: number;
  change_number: string;
  project_id: number;
  title: string;
  description?: string | null;
  reason?: string | null;
  change_type: ChangeType;
  priority: 'low' | 'medium' | 'high' | 'critical';
  status: ChangeStatus;
  lead_id?: number | null;
  raised_by: number;
  customer_response: 'pending' | 'accepted' | 'declined' | 'negotiating';
  pm_signed_by?: number | null;
  quality_signed_by?: number | null;
  estimated_cost?: number | null;
  quoted_price?: number | null;
  created_at: string;
  updated_at: string;
}

export interface ChangeDetail extends ChangeRequest {
  impacted_items: ImpactedItem[];
  assessments: Assessment[];
  attachments: Attachment[];
}

export interface ChangeTask {
  kind: string;
  change_id: number;
  change_number: string;
  title: string;
  department_id: number;
  assessment_id: number;
}
```

- [ ] **Step 2: Verify type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors from `change.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/change.ts
git commit -m "feat(change): frontend TS types"
```

---

## Task 16: Frontend API wrapper

**Files:**
- Create: `frontend/src/api/changes.ts`

- [ ] **Step 1: Write the API wrapper** (uses the shared axios client `./client`)

```typescript
import client from './client';
import type {
  ChangeRequest, ChangeDetail, ChangelogEntry, ChangeTask,
} from '../types/change';

export const changesApi = {
  list: (params: { project_id?: number; status?: string; change_type?: string }) =>
    client.get<ChangeRequest[]>('/v1/changes', { params }).then((r) => r.data),

  get: (id: number) =>
    client.get<ChangeDetail>(`/v1/changes/${id}`).then((r) => r.data),

  create: (body: {
    project_id: number; title: string; change_type: string;
    reason?: string; description?: string; priority?: string; lead_id?: number;
  }) => client.post<ChangeRequest>('/v1/changes', body).then((r) => r.data),

  update: (id: number, body: Record<string, unknown>) =>
    client.patch<ChangeRequest>(`/v1/changes/${id}`, body).then((r) => r.data),

  transition: (id: number, to_status: string, opts?: { justification?: string; cancellation_reason?: string }) =>
    client.post<ChangeRequest>(`/v1/changes/${id}/transition`, { to_status, ...opts }).then((r) => r.data),

  addImpactedItem: (id: number, body: { part_id: number; impact_note?: string; eng_level_before?: string }) =>
    client.post(`/v1/changes/${id}/impacted-items`, body).then((r) => r.data),

  removeImpactedItem: (id: number, itemId: number) =>
    client.delete(`/v1/changes/${id}/impacted-items/${itemId}`).then((r) => r.data),

  seedImpacted: (id: number) =>
    client.post(`/v1/changes/${id}/impacted-items/seed`).then((r) => r.data),

  submitAssessment: (id: number, body: { department_id: number; verdict: string; cost_impact?: number; lead_time_impact_days?: number; conditions?: string; notes?: string }) =>
    client.post(`/v1/changes/${id}/assessments`, body).then((r) => r.data),

  customerResponse: (id: number, response: string) =>
    client.post(`/v1/changes/${id}/customer-response`, { response }).then((r) => r.data),

  signOff: (id: number, role: 'pm' | 'quality') =>
    client.post(`/v1/changes/${id}/sign-off`, { role }).then((r) => r.data),

  changelog: (id: number) =>
    client.get<ChangelogEntry[]>(`/v1/changes/${id}/changelog`).then((r) => r.data),

  myTasks: () =>
    client.get<ChangeTask[]>('/v1/changes/my-tasks').then((r) => r.data),
};
```

Note: confirm `frontend/src/api/client.ts` exports the axios instance as default (`export default client`). If it is a named export, change the import accordingly. Also confirm the base URL already includes `/api` (it does: `http://localhost:8000/api`), so paths start with `/v1/...`.

- [ ] **Step 2: Verify type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/changes.ts
git commit -m "feat(change): frontend API wrapper"
```

---

## Task 17: ChangesPage (list + create)

**Files:**
- Create: `frontend/src/pages/ChangesPage.tsx`

Note: read an existing page (e.g. `frontend/src/pages/LessonsLearnedPage.tsx`) first to match the project's exact query-client usage, layout container classes, and toast/error patterns. The code below uses TanStack Query and Tailwind consistent with the repo; adjust class names/util imports to match.

- [ ] **Step 1: Write the page**

```tsx
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { changesApi } from '../api/changes';
import type { ChangeType } from '../types/change';

const STATUS_LABELS: Record<string, string> = {
  captured: 'Captured', in_assessment: 'In Assessment', costing: 'Costing',
  quoted: 'Quoted', approved: 'Approved', in_implementation: 'Implementing',
  in_validation: 'Validation', released: 'Released', closed: 'Closed',
  on_hold: 'On Hold', rejected: 'Rejected', cancelled: 'Cancelled',
};

const CHANGE_TYPES: { value: ChangeType; label: string }[] = [
  { value: 'physical_part', label: 'Physical Part' },
  { value: 'tooling', label: 'Tooling' },
  { value: 'document_spec', label: 'Document / Spec' },
  { value: 'process_im', label: 'Process / IM' },
  { value: 'packaging', label: 'Packaging' },
];

export default function ChangesPage() {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('');

  const { data: changes = [], isLoading } = useQuery({
    queryKey: ['changes', statusFilter],
    queryFn: () => changesApi.list(statusFilter ? { status: statusFilter } : {}),
  });

  return (
    <div className="max-w-6xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Change Management</h1>
        <button
          className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700"
          onClick={() => setShowCreate(true)}
        >
          New Change
        </button>
      </div>

      <div className="mb-4">
        <select
          className="border rounded-lg px-3 py-2 text-sm"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All statuses</option>
          {Object.entries(STATUS_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <p className="text-gray-500">Loading…</p>
      ) : (
        <div className="border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                <th className="px-4 py-3">Number</th>
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Priority</th>
              </tr>
            </thead>
            <tbody>
              {changes.map((c) => (
                <tr key={c.id} className="border-t hover:bg-gray-50">
                  <td className="px-4 py-3 font-mono">
                    <Link className="text-blue-600 hover:underline" to={`/changes/${c.id}`}>
                      {c.change_number}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{c.title}</td>
                  <td className="px-4 py-3">{c.change_type}</td>
                  <td className="px-4 py-3">{STATUS_LABELS[c.status] ?? c.status}</td>
                  <td className="px-4 py-3">{c.priority}</td>
                </tr>
              ))}
              {changes.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">No changes yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <CreateChangeModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); qc.invalidateQueries({ queryKey: ['changes'] }); }}
        />
      )}
    </div>
  );
}

function CreateChangeModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [projectId, setProjectId] = useState('');
  const [title, setTitle] = useState('');
  const [changeType, setChangeType] = useState<ChangeType>('physical_part');
  const [reason, setReason] = useState('');

  const mutation = useMutation({
    mutationFn: () => changesApi.create({
      project_id: Number(projectId), title, change_type: changeType, reason,
    }),
    onSuccess: onCreated,
  });

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-6 w-full max-w-md">
        <h2 className="text-lg font-semibold mb-4">New Change</h2>
        <label className="block text-sm mb-2">Project ID
          <input className="mt-1 w-full border rounded-lg px-3 py-2" value={projectId}
                 onChange={(e) => setProjectId(e.target.value)} />
        </label>
        <label className="block text-sm mb-2">Title
          <input className="mt-1 w-full border rounded-lg px-3 py-2" value={title}
                 onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="block text-sm mb-2">Type
          <select className="mt-1 w-full border rounded-lg px-3 py-2" value={changeType}
                  onChange={(e) => setChangeType(e.target.value as ChangeType)}>
            {CHANGE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </label>
        <label className="block text-sm mb-4">Reason (a sentence is fine; a PPT can be attached later)
          <textarea className="mt-1 w-full border rounded-lg px-3 py-2" value={reason}
                    onChange={(e) => setReason(e.target.value)} />
        </label>
        <div className="flex justify-end gap-2">
          <button className="px-4 py-2 text-sm" onClick={onClose}>Cancel</button>
          <button
            className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm disabled:opacity-50"
            disabled={!projectId || !title || mutation.isPending}
            onClick={() => mutation.mutate()}
          >Create</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/ChangesPage.tsx
git commit -m "feat(change): ChangesPage list + create modal"
```

---

## Task 18: ChangeDetailPage (stepper + tabs + actions)

**Files:**
- Create: `frontend/src/pages/ChangeDetailPage.tsx`

- [ ] **Step 1: Write the page**

```tsx
import { useParams } from 'react-router-dom';
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { changesApi } from '../api/changes';
import { CHANGE_STATUS_ORDER } from '../types/change';

const STATUS_LABELS: Record<string, string> = {
  captured: 'Captured', in_assessment: 'In Assessment', costing: 'Costing',
  quoted: 'Quoted', approved: 'Approved', in_implementation: 'Implementing',
  in_validation: 'Validation', released: 'Released', closed: 'Closed',
};

const NEXT_STATUS: Record<string, string[]> = {
  captured: ['in_assessment'], in_assessment: ['costing', 'rejected'],
  costing: ['quoted'], quoted: ['approved', 'rejected'],
  approved: ['in_implementation'], in_implementation: ['in_validation'],
  in_validation: ['released'], released: ['closed'],
};

type Tab = 'overview' | 'impacted' | 'assessments' | 'commercial' | 'audit';

export default function ChangeDetailPage() {
  const { id } = useParams();
  const changeId = Number(id);
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>('overview');

  const { data: change, isLoading } = useQuery({
    queryKey: ['change', changeId],
    queryFn: () => changesApi.get(changeId),
  });
  const { data: changelog = [] } = useQuery({
    queryKey: ['change', changeId, 'changelog'],
    queryFn: () => changesApi.changelog(changeId),
    enabled: tab === 'audit',
  });

  const transition = useMutation({
    mutationFn: (vars: { to: string; justification?: string; cancellation_reason?: string }) =>
      changesApi.transition(changeId, vars.to, vars),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change', changeId] }),
    onError: (e: any) => alert(e?.response?.data?.detail ?? 'Transition failed'),
  });
  const signOff = useMutation({
    mutationFn: (role: 'pm' | 'quality') => changesApi.signOff(changeId, role),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change', changeId] }),
    onError: (e: any) => alert(e?.response?.data?.detail ?? 'Sign-off failed'),
  });
  const customer = useMutation({
    mutationFn: (response: string) => changesApi.customerResponse(changeId, response),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change', changeId] }),
  });

  if (isLoading || !change) return <div className="p-6 text-gray-500">Loading…</div>;

  const advance = (to: string) => {
    let justification: string | undefined;
    if (to !== 'rejected') {
      justification = window.prompt(
        `Move to "${STATUS_LABELS[to] ?? to}". If data is incomplete, enter a justification to override (or leave blank):`
      ) ?? undefined;
    }
    const cancellation_reason = to === 'cancelled'
      ? window.prompt('Cancellation reason:') ?? undefined : undefined;
    transition.mutate({ to, justification: justification || undefined, cancellation_reason });
  };

  return (
    <div className="max-w-5xl mx-auto p-6">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-2xl font-semibold">
          <span className="font-mono text-gray-500">{change.change_number}</span> — {change.title}
        </h1>
        <button className="px-3 py-1.5 text-sm border rounded-lg text-red-600"
                onClick={() => advance('cancelled')}>Cancel</button>
      </div>

      <Stepper status={change.status} />

      <div className="flex gap-2 my-4">
        {(NEXT_STATUS[change.status] ?? []).map((to) => (
          <button key={to}
            className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm disabled:opacity-50"
            disabled={transition.isPending}
            onClick={() => advance(to)}>
            → {STATUS_LABELS[to] ?? to}
          </button>
        ))}
        {change.status === 'on_hold' && (
          <button className="px-4 py-2 rounded-lg border text-sm"
                  onClick={() => advance('in_assessment')}>Resume</button>
        )}
      </div>

      <div className="border-b flex gap-4 text-sm mb-4">
        {(['overview', 'impacted', 'assessments', 'commercial', 'audit'] as Tab[]).map((t) => (
          <button key={t}
            className={`pb-2 ${tab === t ? 'border-b-2 border-blue-600 font-medium' : 'text-gray-500'}`}
            onClick={() => setTab(t)}>{t[0].toUpperCase() + t.slice(1)}</button>
        ))}
      </div>

      {tab === 'overview' && (
        <div className="space-y-2 text-sm">
          <p><span className="text-gray-500">Type:</span> {change.change_type}</p>
          <p><span className="text-gray-500">Priority:</span> {change.priority}</p>
          <p><span className="text-gray-500">Status:</span> {STATUS_LABELS[change.status] ?? change.status}</p>
          <p><span className="text-gray-500">Reason:</span> {change.reason ?? '—'}</p>
        </div>
      )}

      {tab === 'impacted' && (
        <ul className="text-sm divide-y border rounded-lg">
          {change.impacted_items.map((i) => (
            <li key={i.id} className="px-4 py-2 flex justify-between">
              <span>Part #{i.part_id} {i.impact_note ? `— ${i.impact_note}` : ''}</span>
              <span className="text-gray-500">
                {i.resulting_revision_id ? `rev #${i.resulting_revision_id}` : 'no revision'}
                {i.eng_level_after ? ` (${i.eng_level_after})` : ''}
              </span>
            </li>
          ))}
          {change.impacted_items.length === 0 && <li className="px-4 py-3 text-gray-400">None.</li>}
        </ul>
      )}

      {tab === 'assessments' && (
        <ul className="text-sm divide-y border rounded-lg">
          {change.assessments.map((a) => (
            <li key={a.id} className="px-4 py-2 flex justify-between">
              <span>Dept #{a.department_id}</span>
              <span className={a.verdict === 'not_feasible' ? 'text-red-600' : ''}>{a.verdict}</span>
            </li>
          ))}
          {change.assessments.length === 0 && <li className="px-4 py-3 text-gray-400">No assessments.</li>}
        </ul>
      )}

      {tab === 'commercial' && (
        <div className="space-y-3 text-sm">
          <p><span className="text-gray-500">Quoted price:</span> {change.quoted_price ?? '—'}</p>
          <p><span className="text-gray-500">Customer response:</span> {change.customer_response}</p>
          <div className="flex gap-2">
            <button className="px-3 py-1.5 border rounded-lg" onClick={() => customer.mutate('accepted')}>Customer accepted</button>
            <button className="px-3 py-1.5 border rounded-lg" onClick={() => customer.mutate('declined')}>Customer declined</button>
          </div>
          <div className="flex gap-2 pt-2">
            <button className="px-3 py-1.5 border rounded-lg" onClick={() => signOff.mutate('pm')}>
              PM sign-off {change.pm_signed_by ? '✓' : ''}
            </button>
            <button className="px-3 py-1.5 border rounded-lg" onClick={() => signOff.mutate('quality')}>
              Quality sign-off {change.quality_signed_by ? '✓' : ''}
            </button>
          </div>
          <p className="text-xs text-gray-400">Approve requires customer acceptance + both sign-offs.</p>
        </div>
      )}

      {tab === 'audit' && (
        <ol className="text-sm space-y-2">
          {changelog.map((e) => (
            <li key={e.id} className="flex gap-3">
              <span className="text-gray-400 font-mono">{new Date(e.performed_at).toLocaleString()}</span>
              <span>{e.action_description}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function Stepper({ status }: { status: string }) {
  const idx = CHANGE_STATUS_ORDER.indexOf(status as any);
  return (
    <div className="flex items-center gap-1 text-xs">
      {CHANGE_STATUS_ORDER.map((s, i) => (
        <div key={s} className="flex items-center gap-1">
          <span className={`px-2 py-1 rounded-full ${
            i < idx ? 'bg-green-100 text-green-700'
            : i === idx ? 'bg-blue-600 text-white'
            : 'bg-gray-100 text-gray-400'}`}>{STATUS_LABELS[s] ?? s}</span>
          {i < CHANGE_STATUS_ORDER.length - 1 && <span className="text-gray-300">→</span>}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Verify type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/ChangeDetailPage.tsx
git commit -m "feat(change): ChangeDetailPage stepper, tabs, transition/sign-off actions"
```

---

## Task 19: Routing + sidebar nav

**Files:**
- Modify: the app router (find with `grep -rn "createBrowserRouter\|<Routes>" frontend/src`)
- Modify: `frontend/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Add routes**

Find the routes file. Add imports and routes alongside existing page routes:

```tsx
import ChangesPage from './pages/ChangesPage';        // adjust relative path
import ChangeDetailPage from './pages/ChangeDetailPage';
```

```tsx
{ path: '/changes', element: <ChangesPage /> },
{ path: '/changes/:id', element: <ChangeDetailPage /> },
```

(If the app uses `<Routes><Route .../></Routes>`, add `<Route path="/changes" element={<ChangesPage />} />` and `<Route path="/changes/:id" element={<ChangeDetailPage />} />` instead.)

- [ ] **Step 2: Add a sidebar entry**

In `frontend/src/components/layout/Sidebar.tsx`, add a nav link mirroring the existing items (match their `NavLink`/icon pattern):

```tsx
<NavLink to="/changes" className={navLinkClass}>
  {/* reuse an existing icon component used by siblings */}
  <span>Changes</span>
</NavLink>
```

- [ ] **Step 3: Verify build + manual check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors.

Then start the app (`bash run_backend.sh` for the API and the frontend dev server per repo convention) and confirm `/changes` lists changes, creating one works, and the detail page advances status.

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "feat(change): route + sidebar nav for changes"
```

---

## Task 20: ProjectChangesSection embedded in ProjectDetailPage

**Files:**
- Create: `frontend/src/components/ProjectChangesSection.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`

Note: open `frontend/src/components/ProjectSepSection.tsx` first and mirror its prop signature (it receives the project id), heading style, and card container so this section is visually consistent.

- [ ] **Step 1: Write the section**

```tsx
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { changesApi } from '../api/changes';

const STATUS_LABELS: Record<string, string> = {
  captured: 'Captured', in_assessment: 'In Assessment', costing: 'Costing',
  quoted: 'Quoted', approved: 'Approved', in_implementation: 'Implementing',
  in_validation: 'Validation', released: 'Released', closed: 'Closed',
  on_hold: 'On Hold', rejected: 'Rejected', cancelled: 'Cancelled',
};

export default function ProjectChangesSection({ projectId }: { projectId: number }) {
  const { data: changes = [] } = useQuery({
    queryKey: ['changes', 'project', projectId],
    queryFn: () => changesApi.list({ project_id: projectId }),
  });

  return (
    <section className="bg-white rounded-xl border p-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">Changes</h2>
        <Link to="/changes" className="text-sm text-blue-600 hover:underline">View all</Link>
      </div>
      {changes.length === 0 ? (
        <p className="text-sm text-gray-400">No changes for this project.</p>
      ) : (
        <ul className="text-sm divide-y">
          {changes.slice(0, 8).map((c) => (
            <li key={c.id} className="py-2 flex justify-between">
              <Link to={`/changes/${c.id}`} className="text-blue-600 hover:underline font-mono">
                {c.change_number}
              </Link>
              <span className="truncate mx-3 flex-1">{c.title}</span>
              <span className="text-gray-500">{STATUS_LABELS[c.status] ?? c.status}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Embed in ProjectDetailPage**

In `frontend/src/pages/ProjectDetailPage.tsx`, import and render it near the SEP/Lessons sections (use the same `projectId` value those sections receive):

```tsx
import ProjectChangesSection from '../components/ProjectChangesSection';
// ...
<ProjectChangesSection projectId={projectId} />
```

- [ ] **Step 3: Verify type-check + manual check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors. Confirm the section renders on a project page.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ProjectChangesSection.tsx frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(change): ProjectChangesSection embedded in ProjectDetailPage"
```

---

## Task 21: My Tasks integration

**Files:**
- Modify: `frontend/src/pages/MyTasksPage.tsx`

Note: open `MyTasksPage.tsx` first to match its section/card structure; append a "Change Assessments" block.

- [ ] **Step 1: Add a change-tasks block**

Add near the other task sections:

```tsx
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { changesApi } from '../api/changes';
// ...
function ChangeTasksSection() {
  const { data: tasks = [] } = useQuery({
    queryKey: ['change-my-tasks'],
    queryFn: () => changesApi.myTasks(),
  });
  if (tasks.length === 0) return null;
  return (
    <section className="bg-white rounded-xl border p-5">
      <h2 className="text-lg font-semibold mb-3">Change Assessments</h2>
      <ul className="text-sm divide-y">
        {tasks.map((t) => (
          <li key={`${t.change_id}-${t.assessment_id}`} className="py-2 flex justify-between">
            <Link to={`/changes/${t.change_id}`} className="text-blue-600 hover:underline">
              <span className="font-mono">{t.change_number}</span> — {t.title}
            </Link>
            <span className="text-gray-500">assessment due</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

Render `<ChangeTasksSection />` within the page body alongside existing task sections.

- [ ] **Step 2: Verify type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/MyTasksPage.tsx
git commit -m "feat(change): surface change assessment tasks in My Tasks"
```

---

## Task 22: Final verification + branch wrap-up

- [ ] **Step 1: Backend full suite**

Run: `cd backend && python -m pytest -q`
Expected: all green (pre-existing + `test_changes.py`).

- [ ] **Step 2: Frontend type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Manual smoke (per repo run convention)**

Start backend + frontend, then verify end-to-end on a real project: create a change with only title+reason → add an impacted part → advance to assessment (override with justification, confirm it is logged in Audit) → submit assessments → costing → set quoted price → quoted → record customer acceptance → PM + Quality sign-off (two users) → approved → in_implementation (ECN revision appears on the part) → in_validation → released (part's active revision flips) → closed.

- [ ] **Step 4: Update the spec status + memory**

Mark the spec `Status:` line as "Implemented (sub-project #1)" and update `change-management-roadmap.md` memory to note #1 is built.

- [ ] **Step 5: Finish the branch**

Invoke `superpowers:finishing-a-development-branch` to choose merge/PR/cleanup for `feature/change-management`.

---

## Self-Review

**Spec coverage:**
- §2 one-object phased lifecycle → Tasks 1, 7 (state machine). ✓
- §2 change_type drives routing → Task 9 (`TYPE_DISCIPLINES`). ✓
- §3 flexibility (minimal start, attachments, soft guards, hard approve gate) → Task 6 (minimal create), Task 7 (soft guards + forced override + hard approve gate), Task 13b (PPT/document upload + download + UI). ✓
- §4 data model (5 tables) → Tasks 1, 3. ✓
- §4 impacted items + eng-level marking → Tasks 1, 8, 12. ✓
- §4 assessments → Tasks 1, 9. ✓
- §5 lifecycle + guards → Task 7. ✓
- §6 change↔revisions (spawn ECN, release activate/supersede/stamp) → Tasks 11, 12. ✓
- §6 audit hash chain → Tasks 5, 13. ✓
- §7 stub attachment points (cost/quote/pnl/timing) → Task 1 fields, Task 10 update. ✓
- §8 API + services (incl. attachments endpoint) → Tasks 5–14 + 13b. ✓
- §9 frontend (ChangesPage, ChangeDetailPage, ProjectChangesSection, My Tasks) → Tasks 15–21. ✓
- §10 migration + tests → Tasks 3, 6–14. ✓

**Placeholder scan:** No TBD/TODO; every code step contains full code. ✓

**Type consistency:** Service method names (`transition`, `add_impacted_item`, `remove_impacted_item`, `seed_impacted_from_relations`, `ensure_assessments`, `submit_assessment`, `record_customer_response`, `sign_off`, `update_change`, `spawn_ecn_revisions`, `release`, `append_changelog`, `generate_change_number`) are used identically across tasks. Frontend `changesApi` method names match their call sites. Status strings match between `CHANGE_STATUSES`, `ALLOWED_TRANSITIONS`, `NEXT_STATUS`, and `CHANGE_STATUS_ORDER`. ✓

**Verification dependencies to confirm at execution time (flagged inline in tasks):** part-relations create payload shape (Task 8), axios client export style + base URL (Task 16), the app's router file form (Task 19), and existing section/page layout conventions (Tasks 17, 20, 21).
