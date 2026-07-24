# ECM Phase D — Cockpit UI, Audit Timeline, Theme Cleanup, Legacy Retirement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The change detail page becomes a cockpit that always answers "where is this change, what blocks it, who is on the hook, what's next"; the hash-chained AuditLog gets a real timeline view with CSV export; changes start from the part/project they affect (no free-text IDs); the app renders one consistent dark-slate theme; and the dead legacy Article stack (backend + frontend) is removed.

**Architecture:** Backend work is small and front-loaded: widen the too-short `AuditLog.action` column (migration 025), retire the Article models/routers/schemas after extracting the shared `CatalogPart` into its own module (migration 026 drops the six legacy tables), and expose `lead_name` on change responses so the UI never shows raw IDs. The frontend then consolidates the triplicated status maps into `lib/changeStatus.ts`, rebuilds ChangeDetailPage around three new components (`LifecycleStepper`, `CockpitSummary`, `AuditTimeline` — the latter consuming the Phase A `/audit` API for the first time), introduces a reusable `StartChangeModal` wired from PartDetail, ProjectDetailPage, and ChangesPage, replaces every remaining `alert()`/`window.prompt` with sonner toasts / proper modals, and fixes the non-shimmed light-theme classes (3D-viewer cluster + stragglers).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async (`Mapped`/`mapped_column`), Alembic, Pydantic v2, pytest + pytest-asyncio (`asyncio_mode=auto`); React + TypeScript, @tanstack/react-query, react-router-dom, Tailwind dark-slate, sonner toasts, vitest + @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-07-02-ecm-lifecycle-design.md` — Phase D row plus scope areas 0 (context-first initiation), 5 (audit export/timeline), 6 (cockpit UI, no prompt/alert, resolved names, theme, Article retirement).

## Global Constraints

- Run backend tests from `backend/` with `python3 -m pytest` (bare `python` absent). Run Alembic via the `alembic` console script from `backend/` (NOT `python3 -m alembic` — a local package shadows the lib).
- New Alembic migrations: `025` (`down_revision = "024"`) and `026` (`down_revision = "025"`). Idempotent `inspect(op.get_bind())` guard pattern, mirroring migration 024.
- Backend suite baseline: **182 tests pass** — must stay green (or grow) after every task.
- Frontend: tests `cd frontend && npx vitest run` (**41 pass** baseline); type-check `npx tsc --noEmit` (**≈30 PRE-EXISTING errors**; Task 3 deletes article files which may reduce this — Task 3 records the NEW baseline, later tasks must add ZERO on top of it); scoped lint per task (`npm run lint 2>&1 | grep -A6 "<file>"` — repo-wide lint has known pre-existing failures, out of scope).
- Labels live in `frontend/src/i18n/cmLabels.ts` — `t(key, lang: 'de'|'en' = 'en')`, missing keys return the key. Every new user-visible string in change-module components goes through `t()` with DE+EN entries.
- Error display convention: `sonner` `toast.error(...)` (Toaster is mounted globally in `App.tsx`); error detail extraction via the file-local `errDetail` helper pattern: `const errDetail = (e: unknown): string | undefined => (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail`. NO new `alert()`/`window.prompt`/`window.confirm` anywhere.
- Theme: dark slate. `frontend/src/index.css` L128-175 contains a light→dark override shim (`bg-white`, `bg-gray-50/100/200`, `text-gray-900/700/600/500`, `border-gray-200/300`, `hover:bg-gray-100/200` are remapped) — the shim STAYS; only classes OUTSIDE the shim leak light styling and must be fixed. New components use explicit slate classes (`bg-slate-800`, `text-slate-200`, …), never shimmed light classes.
- `CatalogPart` / `catalog_parts` table is SHARED with the live Part BOM — it must survive Article retirement (moved, not deleted).
- Authorization/user context: frontend current user = `useAuth()` from `frontend/src/contexts/AuthContext.tsx` (`userId: number | null`).
- Test import convention (backend): `from tests.conftest import <helper>`; fixtures `seed`, `part`, `client`, `eng_auth`, `admin_auth`.
- Frontend test convention: `vi.hoisted` client mocks + `vi.mock('../api/...')`, wrap in `QueryClientProvider` + `MemoryRouter` (see `frontend/src/pages/MyTasksPage.test.tsx` for the exact pattern).
- Agent tiering: each task carries a **Tier** hint (haiku mechanical / sonnet standard / opus design-critical). Never trade correctness for cost.

---

## File Structure

**Backend — create:**
- `backend/alembic/versions/025_widen_audit_action.py` — `audit_logs.action` String(20) → String(64).
- `backend/alembic/versions/026_drop_legacy_article_tables.py` — drops 9 legacy tables.
- `backend/app/models/catalog.py` — new home for `CatalogPart`.
- `backend/tests/test_legacy_retirement.py` — /articles gone, catalog-parts alive.

**Backend — delete:**
- `backend/app/api/v1/articles.py`, `backend/app/api/v1/bom.py`, `backend/app/schemas/article.py`, `backend/app/services/revision_service.py`, `backend/app/models/article.py` (after CatalogPart moves out).

**Backend — modify:**
- `backend/app/models/entities.py` — `AuditLog.action` length.
- `backend/app/models/workflow.py` — remove legacy `WorkflowInstance/WorkflowTemplate/WorkflowStep/WorkflowTask` classes.
- `backend/app/models/__init__.py`, `backend/app/schemas/__init__.py`, `backend/app/api/v1/__init__.py` — deregistrations + catalog import.
- `backend/app/api/v1/items/part_bom.py`, `backend/app/api/v1/catalog_parts.py` — import `CatalogPart` from `app.models.catalog`.
- `backend/app/schemas/change.py` + change router — `lead_name` on change responses.

**Frontend — create:**
- `frontend/src/lib/changeStatus.ts` (+ test) — single source for status labels/transitions/colors.
- `frontend/src/api/audit.ts` — audit list/verify/export client.
- `frontend/src/components/changes/LifecycleStepper.tsx` (+ test) — lifecycle pills incl. off-path states.
- `frontend/src/components/changes/CockpitSummary.tsx` (+ test) — where/blocking/next panel.
- `frontend/src/components/changes/AuditTimeline.tsx` (+ test) — hash-chain timeline + export.
- `frontend/src/components/changes/StartChangeModal.tsx` (+ test) — context-first change creation.

**Frontend — delete:**
- `frontend/src/pages/ArticlesPage.tsx`, `frontend/src/components/articles/` (whole dir), `frontend/src/api/articles.ts`, `frontend/src/hooks/queries/useArticles.ts`, `frontend/src/types/article.ts`.

**Frontend — modify:**
- `frontend/src/api/bom.ts`, `frontend/src/hooks/queries/useBOM.ts`, `frontend/src/types/bom.ts` — strip legacy article-BOM halves.
- `frontend/src/pages/ChangeDetailPage.tsx` — cockpit rework.
- `frontend/src/pages/ChangesPage.tsx` — StartChangeModal + shared status lib + theme.
- `frontend/src/components/ProjectChangesSection.tsx` — shared status lib.
- `frontend/src/pages/PartDetail.tsx`, `frontend/src/pages/ProjectDetailPage.tsx` — "Start change" buttons.
- `frontend/src/pages/UsersPage.tsx` — prompt → modal.
- `frontend/src/components/changes/DeviationBanner.tsx`, `ImplementationPanel.tsx`, `ImpactTree.tsx` — alert → toast.
- `frontend/src/components/ViewerToolbar.tsx`, `Viewer3D.tsx`, `MeasurementReadout.tsx`, `CutPlaneControls.tsx`, `ObjectTree.tsx`, `frontend/src/components/common/ConfirmModal.tsx`, `frontend/src/components/workflows/StartWorkflowModal.tsx` — theme fixes.
- `frontend/src/types/change.ts` — `lead_name`, assessment owner fields.
- `frontend/src/i18n/cmLabels.ts` — new labels.

---

## Task 1: Widen `AuditLog.action` (migration 025)

**Tier:** haiku (mechanical, established migration pattern).

**Why:** `AuditLog.action` is `String(20)` (`backend/app/models/entities.py:183` region) but written actions exceed it (`customer_response_recorded` = 26, `routing_deviation_approved` = 26, `assessment_due_date_set` = 23). SQLite doesn't enforce VARCHAR length, so this is latent — but it's a real truncation bug on any enforcing backend and a compliance risk.

**Files:**
- Modify: `backend/app/models/entities.py` (AuditLog.action)
- Create: `backend/alembic/versions/025_widen_audit_action.py`
- Test: `backend/tests/test_audit_action_width.py`

**Interfaces:**
- Produces: `AuditLog.action` column type `String(64)`. No API change.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_audit_action_width.py
import pytest

pytestmark = pytest.mark.asyncio


async def test_audit_action_column_fits_long_actions(session_factory):
    from app.models.entities import AuditLog
    assert AuditLog.action.type.length >= 64, (
        "AuditLog.action must fit actions like 'customer_response_recorded' "
        "(26 chars) with headroom")


async def test_long_action_roundtrips(session_factory, seed):
    from app.services.audit_service import AuditService
    from app.models.entities import AuditLog
    from sqlalchemy import select

    long_action = "customer_response_recorded_with_negotiation"  # 43 chars
    async with session_factory() as s:
        await AuditService.record(
            s, entity_type="change", entity_id=999999, action=long_action,
            user_id=seed["engineer_id"], correlation_id="CR-TEST-WIDTH")
        await s.commit()
    async with session_factory() as s:
        row = (await s.execute(select(AuditLog).where(
            AuditLog.correlation_id == "CR-TEST-WIDTH"))).scalar_one()
        assert row.action == long_action
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_audit_action_width.py -v`
Expected: first test FAILS with an assertion on `.length` (currently 20). (Second may pass on SQLite — that's fine, it guards enforcing backends.)

- [ ] **Step 3: Implement**

In `backend/app/models/entities.py`, on `AuditLog`, change:

```python
    action: Mapped[str] = mapped_column(String(64), nullable=False)
```

(keep every other attribute of the line as-is — only the length changes; read the actual line first and preserve its exact form).

Create `backend/alembic/versions/025_widen_audit_action.py`:

```python
"""Phase D: widen audit_logs.action from String(20) to String(64).

Revision ID: 025
Revises: 024
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"]: c for c in inspect(bind).get_columns("audit_logs")}
    if "action" in cols:
        with op.batch_alter_table("audit_logs") as batch:
            batch.alter_column(
                "action", type_=sa.String(64), existing_type=sa.String(20),
                existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("audit_logs") as batch:
        batch.alter_column(
            "action", type_=sa.String(20), existing_type=sa.String(64),
            existing_nullable=False)
```

(`batch_alter_table` is required — SQLite cannot ALTER COLUMN directly.)

- [ ] **Step 4: Run tests + apply migration twice**

Run: `cd backend && python3 -m pytest tests/test_audit_action_width.py -v && alembic upgrade head && alembic upgrade head`
Expected: tests PASS; both alembic runs exit 0.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/entities.py \
        backend/alembic/versions/025_widen_audit_action.py \
        backend/tests/test_audit_action_width.py
git commit -m "fix(audit): widen AuditLog.action to String(64)"
```

---

## Task 2: Backend legacy Article retirement (migration 026)

**Tier:** sonnet (careful deletion with one shared-model extraction).

**Files:**
- Create: `backend/app/models/catalog.py`, `backend/alembic/versions/026_drop_legacy_article_tables.py`, `backend/tests/test_legacy_retirement.py`
- Delete: `backend/app/api/v1/articles.py`, `backend/app/api/v1/bom.py`, `backend/app/schemas/article.py`, `backend/app/services/revision_service.py`, `backend/app/models/article.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/schemas/__init__.py`, `backend/app/api/v1/__init__.py`, `backend/app/models/workflow.py`, `backend/app/api/v1/items/part_bom.py`, `backend/app/api/v1/catalog_parts.py`

**Interfaces:**
- Produces: `CatalogPart` importable from `app.models.catalog` (same class body as today in `app.models.article:8`). `/api/v1/articles/*` and `/api/v1/articles/.../bom` and `/api/v1/projects/{id}/bom-aggregation` return 404. `/api/v1/catalog-parts` unchanged.
- Removes: legacy models `Article`, `ArticleRevision`, `ArticleDocument`, `BOM`, `BOMItem` (from `article.py`) and `WorkflowInstance`, `WorkflowTemplate`, `WorkflowStep`, `WorkflowTask` (from `workflow.py` — these are referenced ONLY by `article.py`; the live engine uses `WfInstance`/`WfTemplate`). Migration 026 drops tables `bom_items`, `boms`, `article_documents`, `workflow_tasks`, `workflow_steps`, `workflow_instances`, `workflow_templates`, `article_revisions`, `articles` (legacy-only data; downgrade is documented as non-restoring).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_legacy_retirement.py
import pytest

pytestmark = pytest.mark.asyncio


async def test_articles_api_is_retired(client, eng_auth):
    res = await client.get("/api/v1/articles", headers=eng_auth)
    assert res.status_code == 404


async def test_catalog_parts_survive(client, eng_auth):
    res = await client.get("/api/v1/catalog-parts", headers=eng_auth)
    assert res.status_code == 200


async def test_catalog_part_import_location():
    from app.models.catalog import CatalogPart  # new canonical home
    from app.models import CatalogPart as reexported
    assert CatalogPart is reexported


async def test_legacy_models_gone():
    import app.models as m
    for name in ("Article", "ArticleRevision", "ArticleDocument", "BOM",
                 "BOMItem", "WorkflowInstance", "WorkflowTemplate",
                 "WorkflowStep", "WorkflowTask"):
        assert not hasattr(m, name), f"{name} should be retired"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_legacy_retirement.py -v`
Expected: FAIL — `/articles` returns 200/405 (mounted), `app.models.catalog` doesn't exist, legacy names still exported.

- [ ] **Step 3: Extract CatalogPart**

Create `backend/app/models/catalog.py` by MOVING the `CatalogPart` class (currently `backend/app/models/article.py:8-30`, read it first and copy verbatim) with the imports it needs:

```python
"""Catalog parts — purchasable/standard parts referenced by Part BOMs.

Extracted from the retired legacy article module (Phase D); the
catalog_parts table is shared with the live Part stack.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base


class CatalogPart(Base):
    __tablename__ = "catalog_parts"
    # ... copy the exact column definitions from article.py verbatim ...
```

(Copy the real body — column names/types must be identical; adjust the import list to exactly what the copied body uses. If `article.py`'s `CatalogPart` has relationships to legacy models, they don't exist — verify with a read; the explorer found none.)

Update importers:
- `backend/app/api/v1/items/part_bom.py:19`: `from app.models.catalog import CatalogPart`
- `backend/app/api/v1/catalog_parts.py:6`: `from app.models.catalog import CatalogPart`
- `backend/app/models/__init__.py`: replace the article import block (L7-9) with `from app.models.catalog import CatalogPart`; remove `Article, ArticleRevision, ArticleDocument, BOM, BOMItem` and `WorkflowInstance, WorkflowTemplate, WorkflowStep, WorkflowTask` from imports and `__all__` (keep `CatalogPart` in `__all__`).

- [ ] **Step 4: Delete the legacy stack**

```bash
git rm backend/app/api/v1/articles.py backend/app/api/v1/bom.py \
       backend/app/schemas/article.py backend/app/services/revision_service.py \
       backend/app/models/article.py
```

- `backend/app/api/v1/__init__.py`: remove the article import (L4), `include_router` for articles (L48), and both bom router mounts (L68-69) plus their import.
- `backend/app/schemas/__init__.py`: remove article schema imports/exports (L16-22).
- `backend/app/models/workflow.py`: delete the legacy `WorkflowInstance`, `WorkflowTemplate`, `WorkflowStep`, `WorkflowTask` classes (the live engine classes are `WfInstance`, `WfTemplate`, `WfStage`, `WfStep`, `WfStepRasic`, `WfInstanceTask` — do NOT touch those). Search the file for any relationship pointing at the deleted classes and remove it.
- Grep to confirm nothing else references the deleted names:

```bash
cd backend && grep -rn "from app.models.article\|from app.schemas.article\|from app.services.revision_service\|WorkflowInstance\|WorkflowTemplate\|WorkflowStep\b\|WorkflowTask\b\|ArticleRevision" app/ --include="*.py"
```

Expected: zero hits (except `app/models/catalog.py`'s docstring if worded that way).

- [ ] **Step 5: Write migration 026**

```python
# backend/alembic/versions/026_drop_legacy_article_tables.py
"""Phase D: drop legacy Article-stack tables.

These tables belong to the retired Article model stack (superseded by the
Part stack). Data in them is legacy-only; parts/part_bom_items never
reference them. catalog_parts is SHARED with the Part stack and is KEPT.

Revision ID: 026
Revises: 025
"""
from alembic import op
from sqlalchemy import inspect

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None

# child-before-parent drop order
_LEGACY_TABLES = (
    "bom_items", "boms", "article_documents",
    "workflow_tasks", "workflow_steps", "workflow_instances",
    "workflow_templates", "article_revisions", "articles",
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table in _LEGACY_TABLES:
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    # Irreversible by design: the legacy schema lives in migration 001 and
    # the data is retired. Recreate from 001 if ever needed.
    pass
```

- [ ] **Step 6: Run tests + apply migration twice + full suite**

Run: `cd backend && alembic upgrade head && alembic upgrade head && python3 -m pytest`
Expected: migrations exit 0 twice; full suite passes (186+ — the 4 new retirement tests included; NO existing test may break — the explorer confirmed no test touches `/v1/articles` or the Article models).

- [ ] **Step 7: Commit**

```bash
git add -A backend/app backend/alembic/versions/026_drop_legacy_article_tables.py \
        backend/tests/test_legacy_retirement.py
git commit -m "feat(retirement): remove legacy Article backend stack, extract shared CatalogPart"
```

(`git add -A backend/app` is acceptable here because the deletions were staged via `git rm`; verify `git status` shows only intended paths before committing.)

---

## Task 3: Frontend legacy Article retirement

**Tier:** sonnet.

**Files:**
- Delete: `frontend/src/pages/ArticlesPage.tsx`, `frontend/src/components/articles/` (entire directory), `frontend/src/api/articles.ts`, `frontend/src/hooks/queries/useArticles.ts`, `frontend/src/types/article.ts`
- Modify: `frontend/src/api/bom.ts`, `frontend/src/hooks/queries/useBOM.ts`, `frontend/src/types/bom.ts`

**Interfaces:**
- Removes: article API fns/hooks/types and the article-scoped BOM halves: in `api/bom.ts` the fns hitting `/v1/articles/.../bom` (`getBOM/addBOMItem/updateBOMItem/deleteBOMItem`, ~L56+); in `useBOM.ts` the hooks `useBOM/useAddBOMItem/useUpdateBOMItem/useDeleteBOMItem` (~L60-95) and `useProjectBOM` (~L99 — zero consumers); in `types/bom.ts` the `BOM*` interfaces.
- Keeps (SHARED — verify each survives): `api/bom.ts` catalog fns (`/v1/catalog-parts`), `useBOM.ts` catalog hooks (`useCatalogParts` etc. — used by `CatalogPage.tsx` and `PartBOMSection.tsx`), `types/bom.ts` `CatalogPart*` types.

- [ ] **Step 1: Verify the dead-code claim before deleting**

```bash
cd frontend && grep -rn "ArticlesPage\|components/articles\|api/articles\|useArticles\|types/article'" src --include="*.tsx" --include="*.ts" | grep -v "src/pages/ArticlesPage\|src/components/articles/\|src/api/articles\|src/hooks/queries/useArticles\|src/types/article"
```

Expected: ZERO hits (nothing outside the legacy island imports it). If any hit appears, STOP and reassess — do not delete a consumed file.

- [ ] **Step 2: Delete the island**

```bash
git rm -r frontend/src/pages/ArticlesPage.tsx frontend/src/components/articles \
          frontend/src/api/articles.ts frontend/src/hooks/queries/useArticles.ts \
          frontend/src/types/article.ts
```

- [ ] **Step 3: Strip the legacy halves of the bom trio**

Read each file, then remove ONLY the article-scoped pieces:
- `frontend/src/api/bom.ts`: delete the fns whose URLs contain `/v1/articles/` and any now-unused imports from `types/bom`.
- `frontend/src/hooks/queries/useBOM.ts`: delete `useBOM`, `useAddBOMItem`, `useUpdateBOMItem`, `useDeleteBOMItem`, `useProjectBOM` and their imports.
- `frontend/src/types/bom.ts`: delete the `BOM`/`BOMItem`-family interfaces (keep every `CatalogPart*` type; if `PartBOM*` types live here, keep them too — read consumers before deleting any type).

- [ ] **Step 4: Verify + record new tsc baseline**

Run: `cd frontend && npx vitest run && npx tsc --noEmit 2>&1 | grep -cE "error TS"`
Expected: 41 tests pass; note the tsc error count printed — this is the NEW pre-existing baseline for all later tasks (deleting article files may have reduced it below ≈30). Write the number in the commit message.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src
git commit -m "feat(retirement): remove legacy Article frontend stack (new tsc baseline: <N>)"
```

---

## Task 4: Shared change-status module

**Tier:** haiku (extraction refactor, no behavior change).

**Files:**
- Create: `frontend/src/lib/changeStatus.ts`, `frontend/src/lib/changeStatus.test.ts`
- Modify: `frontend/src/pages/ChangeDetailPage.tsx` (L20-31), `frontend/src/pages/ChangesPage.tsx` (L7-12), `frontend/src/components/ProjectChangesSection.tsx` (L9-22)

**Interfaces:**
- Produces (`frontend/src/lib/changeStatus.ts`):

```ts
import type { ChangeStatus } from '../types/change'

export const STATUS_LABELS: Record<ChangeStatus, string> = {
  captured: 'Captured', in_assessment: 'In Assessment', costing: 'Costing',
  quoted: 'Quoted', approved: 'Approved', in_implementation: 'Implementing',
  in_validation: 'Validation', released: 'Released', closed: 'Closed',
  on_hold: 'On Hold', rejected: 'Rejected', cancelled: 'Cancelled',
}

export const NEXT_STATUS: Partial<Record<ChangeStatus, ChangeStatus[]>> = {
  captured: ['in_assessment'], in_assessment: ['costing', 'rejected'],
  costing: ['quoted'], quoted: ['approved', 'rejected'],
  approved: ['in_implementation'], in_implementation: ['in_validation'],
  in_validation: ['released'], released: ['closed'],
}

/** pill classes per status, dark-slate theme */
export const STATUS_PILL: Record<ChangeStatus, string> = {
  captured: 'bg-slate-700 text-slate-200',
  in_assessment: 'bg-sky-900 text-sky-200',
  costing: 'bg-sky-900 text-sky-200',
  quoted: 'bg-indigo-900 text-indigo-200',
  approved: 'bg-emerald-900 text-emerald-200',
  in_implementation: 'bg-amber-900 text-amber-200',
  in_validation: 'bg-amber-900 text-amber-200',
  released: 'bg-emerald-900 text-emerald-200',
  closed: 'bg-slate-700 text-slate-300',
  on_hold: 'bg-amber-900 text-amber-200',
  rejected: 'bg-red-900 text-red-200',
  cancelled: 'bg-red-900 text-red-200',
}

export const OFF_PATH_STATUSES: ChangeStatus[] = ['on_hold', 'rejected', 'cancelled']
```

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/changeStatus.test.ts
import { describe, it, expect } from 'vitest'
import { STATUS_LABELS, NEXT_STATUS, STATUS_PILL, OFF_PATH_STATUSES } from './changeStatus'
import { CHANGE_STATUS_ORDER } from '../types/change'

describe('changeStatus', () => {
  it('labels and pills cover every status', () => {
    const all = [...CHANGE_STATUS_ORDER, ...OFF_PATH_STATUSES]
    for (const s of all) {
      expect(STATUS_LABELS[s], s).toBeTruthy()
      expect(STATUS_PILL[s], s).toBeTruthy()
    }
  })
  it('every NEXT_STATUS target is a known status', () => {
    for (const targets of Object.values(NEXT_STATUS))
      for (const t of targets!) expect(STATUS_LABELS[t], t).toBeTruthy()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/changeStatus.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Create the module and refactor the three consumers**

Create `frontend/src/lib/changeStatus.ts` with the exact content from Interfaces. Then in each consumer, delete the local `STATUS_LABELS`/`NEXT_STATUS` consts and import from `'../lib/changeStatus'` (ChangesPage keeps its local `CHANGE_TYPES` — that's change-type, not status; `ProjectChangesSection` at `frontend/src/components/ProjectChangesSection.tsx` — read L9-22 first; if its map includes colors, replace with `STATUS_PILL`). Types: where the old local maps were `Record<string, string>`, indexing with a `string` still compiles via `STATUS_LABELS[c.status]` because `status` is typed `ChangeStatus`; if any call site indexes with a plain `string`, cast at the call site (`STATUS_LABELS[s as ChangeStatus] ?? s`).

- [ ] **Step 4: Verify**

Run: `cd frontend && npx vitest run && npx tsc --noEmit 2>&1 | grep -cE "error TS"`
Expected: all tests pass (42+); tsc count == Task 3 baseline.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/changeStatus.ts frontend/src/lib/changeStatus.test.ts \
        frontend/src/pages/ChangeDetailPage.tsx frontend/src/pages/ChangesPage.tsx \
        frontend/src/components/ProjectChangesSection.tsx
git commit -m "refactor(frontend): single source of truth for change status labels/transitions/colors"
```

---

## Task 5: `lead_name` + assessment owner fields on change responses

**Tier:** sonnet.

**Files:**
- Modify: `backend/app/schemas/change.py`, `backend/app/models/change.py` (ChangeRequest lead relationship — check if present), `frontend/src/types/change.ts`
- Test: `backend/tests/test_changes.py` (extend with one test)

**Interfaces:**
- Produces (backend): `ChangeResponse`/`ChangeDetailResponse` (read `backend/app/schemas/change.py` for the actual class names) gain `lead_name: Optional[str] = None`, served via a `lead_name` property on the `ChangeRequest` model: relationship `lead: Mapped["User | None"] = relationship(foreign_keys=[lead_id], lazy="selectin")` + `@property def lead_name(self): return self.lead.full_name if self.lead else None`. Mirror EXACTLY the Phase C `owner`/`owner_name` pattern on `ChangeAssessment` (same file) — including `lazy="selectin"` (MissingGreenlet otherwise). If a `lead` relationship already exists, reuse it (verify its `lazy` setting; upgrade to selectin if lazy).
- Produces (frontend): `ChangeRequest` type += `lead_name?: string | null`; `Assessment` type += `owner_id: number | null`, `owner_name: string | null`, `accepted_at: string | null`, `due_date: string | null`, `overdue: boolean` (the backend `AssessmentResponse` already serves these since Phase C — the frontend type just never caught up).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_changes.py`:

```python
async def test_change_response_resolves_lead_name(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "lead name test",
        "change_type": "tooling", "lead_id": seed["engineer_id"]},
        headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    change_id = res.json()["id"]
    res = await client.get(f"/api/v1/changes/{change_id}", headers=eng_auth)
    assert res.status_code == 200
    assert res.json()["lead_name"]  # resolved full name, not an id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_changes.py -v -k lead_name`
Expected: FAIL with KeyError `'lead_name'`.

- [ ] **Step 3: Implement (model property + schema field + frontend types)**

Model (`backend/app/models/change.py`, on `ChangeRequest`; read existing relationships first):

```python
    lead: Mapped["User | None"] = relationship(
        foreign_keys=[lead_id], lazy="selectin")

    @property
    def lead_name(self) -> Optional[str]:
        return self.lead.full_name if self.lead is not None else None
```

Schema: add `lead_name: Optional[str] = None` to the change response class(es) that serve GET (find via `response_model=` in `backend/app/api/v1/changes/changes.py`).

Frontend `frontend/src/types/change.ts`: add `lead_name?: string | null;` to `ChangeRequest` (after `lead_id`), and the five owner fields to `Assessment` (after `status`).

- [ ] **Step 4: Verify**

Run: `cd backend && python3 -m pytest tests/test_changes.py tests/test_change_routing.py -v && cd ../frontend && npx tsc --noEmit 2>&1 | grep -cE "error TS"`
Expected: backend PASS; tsc count unchanged from baseline.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/change.py backend/app/schemas/change.py \
        backend/tests/test_changes.py frontend/src/types/change.ts
git commit -m "feat(change): resolved lead_name + assessment owner fields in responses"
```

---

## Task 6: Cockpit — LifecycleStepper + CockpitSummary + ChangeDetailPage rework

**Tier:** opus (UX-critical; this is the heart of Phase D).

**Files:**
- Create: `frontend/src/components/changes/LifecycleStepper.tsx`, `LifecycleStepper.test.tsx`, `frontend/src/components/changes/CockpitSummary.tsx`, `CockpitSummary.test.tsx`
- Modify: `frontend/src/pages/ChangeDetailPage.tsx`, `frontend/src/i18n/cmLabels.ts`

**Interfaces:**
- Consumes: Task 4 (`STATUS_LABELS`, `NEXT_STATUS`, `STATUS_PILL`, `OFF_PATH_STATUSES`), Task 5 (`lead_name`, assessment owner fields), existing `changesApi.getGates`, `changesApi.listDeviations`, `changesApi.getImplementation`.
- Produces:
  - `<LifecycleStepper status={ChangeStatus} />` — happy-path pills from `CHANGE_STATUS_ORDER` (past = `bg-emerald-900 text-emerald-200`, current = `bg-sky-600 text-white`, future = `bg-slate-800 text-slate-500`); when `status` is off-path (`on_hold`/`rejected`/`cancelled`) the row renders greyed with a leading `STATUS_PILL`-colored badge naming the state.
  - `<CockpitSummary change gates pendingDeviations impl onAdvance advancing />` — three-panel grid answering the four spec questions:
    - **Where** — status pill + label, `lead_name` ("Lead: …"), created/updated dates.
    - **Blocking** — one row per open blocker: each gate with `decision !== 'yes'` (amber, "Gate {t('gate.'+key)}: {decision}"); pending deviation count (amber); overdue assessments count (red, from `change.assessments.filter(a => a.overdue)`); unclaimed active assessments count (slate, `status === 'active' && owner_id === null`). Empty state: green "✓ {t('cockpit.nothingBlocking')}".
    - **Next** — FIRST allowed transition from `NEXT_STATUS[change.status]` as the single visually-primary button (`bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-2 rounded-lg`); remaining transitions as ghost buttons (`border border-slate-600 text-slate-300`); `ready_to_go` renders the green badge; terminal/off-path statuses render a status note instead of buttons.
  - ChangeDetailPage layout becomes: header (title + cancel) → `LifecycleStepper` → `DeviationBanner` (when blocked) → `CockpitSummary` (always visible, above tabs; the old standalone transition-button row at L129-142 is DELETED — its behavior moves into CockpitSummary's Next panel, still calling the page's `advance(to)` so cancel/deviation flows are untouched) → tabs → panels. Assessments tab: replace `Dept #{a.department_id}` with resolved department names via `useDepartments()` from `frontend/src/hooks/queries/useWorkflows.ts` (read its return shape first: list of `{id, name, ...}`), and show `owner_name` + overdue flag per assessment row.
  - New labels in `cmLabels.ts` (DE/EN): `cockpit.where` (Status), `cockpit.blocking` (DE 'Blockiert durch', EN 'Blocked by'), `cockpit.next` (DE 'Nächster Schritt', EN 'Next step'), `cockpit.nothingBlocking` (DE 'Nichts blockiert', EN 'Nothing blocking'), `cockpit.lead` (DE 'Verantwortlich (Lead)', EN 'Lead'), `cockpit.pendingDeviations` (DE 'Offene Abweichungen', EN 'Pending deviations'), `cockpit.overdueAssessments` (DE 'Überfällige Bewertungen', EN 'Overdue assessments'), `cockpit.unclaimed` (DE 'Nicht übernommen', EN 'Unclaimed'), `gate.feasibility` (DE 'Machbarkeit', EN 'Feasibility'), `gate.budget` (DE 'Budget', EN 'Budget'), `gate.release` (DE 'Freigabe', EN 'Release').

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/components/changes/LifecycleStepper.test.tsx
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import LifecycleStepper from './LifecycleStepper'

describe('LifecycleStepper', () => {
  afterEach(cleanup)

  it('marks past, current and future statuses', () => {
    render(<LifecycleStepper status="costing" />)
    expect(screen.getByText('Captured').className).toContain('emerald')
    expect(screen.getByText('Costing').className).toContain('sky-600')
    expect(screen.getByText('Released').className).toContain('slate-800')
  })

  it('shows an off-path badge for on_hold', () => {
    render(<LifecycleStepper status="on_hold" />)
    expect(screen.getByText('On Hold')).toBeDefined()
  })
})
```

```tsx
// frontend/src/components/changes/CockpitSummary.test.tsx
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import CockpitSummary from './CockpitSummary'
import type { ChangeDetail } from '../../types/change'

const change = (over: Partial<ChangeDetail> = {}): ChangeDetail => ({
  id: 7, change_number: 'CR-2026-0007', project_id: 1, title: 'Housing fix',
  change_type: 'tooling', priority: 'medium', status: 'quoted',
  raised_by: 1, customer_response: 'pending', lead_id: 5, lead_name: 'Eva Eng',
  created_at: '2026-07-01T00:00:00', updated_at: '2026-07-01T00:00:00',
  impacted_items: [], assessments: [], attachments: [], ...over,
} as ChangeDetail)

describe('CockpitSummary', () => {
  afterEach(cleanup)

  it('shows lead, blockers, and one primary next action', () => {
    const onAdvance = vi.fn()
    render(<CockpitSummary
      change={change({ assessments: [
        { id: 1, department_id: 2, verdict: 'pending', stage_order: 1,
          rasic_letter: 'R', status: 'active', owner_id: null, owner_name: null,
          accepted_at: null, due_date: '2026-06-01T00:00:00', overdue: true },
      ] as ChangeDetail['assessments'] })}
      gates={[
        { gate_key: 'feasibility', decision: 'yes' },
        { gate_key: 'budget', decision: 'na' },
      ]}
      pendingDeviations={1}
      onAdvance={onAdvance} advancing={false} />)
    expect(screen.getByText('Eva Eng')).toBeDefined()
    expect(screen.getByText(/Budget/)).toBeDefined()          // open gate named
    expect(screen.getByText(/Pending deviations/)).toBeDefined()
    expect(screen.getByText(/Overdue assessments/)).toBeDefined()
    const primary = screen.getByRole('button', { name: /Approved/ })
    expect(primary.className).toContain('bg-sky-600')
    fireEvent.click(primary)
    expect(onAdvance).toHaveBeenCalledWith('approved')
  })

  it('shows nothing-blocking empty state', () => {
    render(<CockpitSummary change={change({ status: 'captured' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />)
    expect(screen.getByText(/Nothing blocking/)).toBeDefined()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/changes/LifecycleStepper.test.tsx src/components/changes/CockpitSummary.test.tsx`
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement LifecycleStepper**

```tsx
// frontend/src/components/changes/LifecycleStepper.tsx
import { CHANGE_STATUS_ORDER, type ChangeStatus } from '../../types/change'
import { STATUS_LABELS, STATUS_PILL, OFF_PATH_STATUSES } from '../../lib/changeStatus'

export default function LifecycleStepper({ status }: { status: ChangeStatus }) {
  const offPath = OFF_PATH_STATUSES.includes(status)
  const idx = CHANGE_STATUS_ORDER.indexOf(status)
  return (
    <div className="flex items-center gap-1 text-xs flex-wrap">
      {offPath && (
        <span className={`px-2 py-1 rounded-full font-semibold mr-2 ${STATUS_PILL[status]}`}>
          {STATUS_LABELS[status]}
        </span>
      )}
      {CHANGE_STATUS_ORDER.map((s, i) => (
        <div key={s} className="flex items-center gap-1">
          <span className={`px-2 py-1 rounded-full ${
            offPath ? 'bg-slate-800 text-slate-600'
            : i < idx ? 'bg-emerald-900 text-emerald-200'
            : i === idx ? 'bg-sky-600 text-white'
            : 'bg-slate-800 text-slate-500'}`}>{STATUS_LABELS[s]}</span>
          {i < CHANGE_STATUS_ORDER.length - 1 && <span className="text-slate-600">→</span>}
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Implement CockpitSummary**

```tsx
// frontend/src/components/changes/CockpitSummary.tsx
import type { ChangeDetail, Gate } from '../../types/change'
import { STATUS_LABELS, STATUS_PILL, NEXT_STATUS, OFF_PATH_STATUSES } from '../../lib/changeStatus'
import { t } from '../../i18n/cmLabels'

interface Props {
  change: ChangeDetail
  gates: Gate[]
  pendingDeviations: number
  impl?: { ready_to_go: boolean } | undefined
  onAdvance: (to: string) => void
  advancing: boolean
}

export default function CockpitSummary({ change, gates, pendingDeviations, impl, onAdvance, advancing }: Props) {
  const openGates = gates.filter((g) => g.decision !== 'yes')
  const overdue = change.assessments.filter((a) => a.overdue).length
  const unclaimed = change.assessments.filter(
    (a) => a.status === 'active' && a.owner_id === null).length
  const blockers = openGates.length + (pendingDeviations > 0 ? 1 : 0)
    + (overdue > 0 ? 1 : 0)
  const next = NEXT_STATUS[change.status] ?? []
  const offPath = OFF_PATH_STATUSES.includes(change.status)

  return (
    <div className="grid md:grid-cols-3 gap-3 my-4">
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
        <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">{t('cockpit.where')}</h3>
        <span className={`px-2.5 py-1 rounded-full text-sm font-semibold ${STATUS_PILL[change.status]}`}>
          {STATUS_LABELS[change.status]}
        </span>
        <p className="mt-3 text-sm text-slate-300">
          {t('cockpit.lead')}: <span className="text-slate-100">{change.lead_name ?? '—'}</span>
        </p>
        <p className="mt-1 text-xs text-slate-500">
          {new Date(change.created_at).toLocaleDateString()} → {new Date(change.updated_at).toLocaleDateString()}
        </p>
      </div>

      <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
        <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">{t('cockpit.blocking')}</h3>
        {blockers === 0 && unclaimed === 0 ? (
          <p className="text-sm text-emerald-400">✓ {t('cockpit.nothingBlocking')}</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {openGates.map((g) => (
              <li key={g.gate_key} className="text-amber-300">
                ⚠ Gate {t('gate.' + g.gate_key)}: <span className="uppercase">{g.decision}</span>
              </li>
            ))}
            {pendingDeviations > 0 && (
              <li className="text-amber-300">⚠ {t('cockpit.pendingDeviations')}: {pendingDeviations}</li>
            )}
            {overdue > 0 && (
              <li className="text-red-400">⚠ {t('cockpit.overdueAssessments')}: {overdue}</li>
            )}
            {unclaimed > 0 && (
              <li className="text-slate-400">{t('cockpit.unclaimed')}: {unclaimed}</li>
            )}
          </ul>
        )}
      </div>

      <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
        <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">{t('cockpit.next')}</h3>
        {impl?.ready_to_go && (
          <span className="inline-block mb-2 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-900 text-emerald-200">
            ✓ {t('impl.readyToGo')}
          </span>
        )}
        {offPath || next.length === 0 ? (
          <p className="text-sm text-slate-400">{STATUS_LABELS[change.status]}</p>
        ) : (
          <div className="flex flex-col gap-2">
            <button
              className="bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-2 rounded-lg text-sm disabled:opacity-50"
              disabled={advancing}
              onClick={() => onAdvance(next[0])}>
              → {STATUS_LABELS[next[0]]}
            </button>
            {next.slice(1).map((to) => (
              <button key={to}
                className="border border-slate-600 text-slate-300 hover:bg-slate-700 px-4 py-2 rounded-lg text-sm disabled:opacity-50"
                disabled={advancing}
                onClick={() => onAdvance(to)}>
                → {STATUS_LABELS[to]}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
```

Add the eleven `cockpit.*`/`gate.*` labels to `frontend/src/i18n/cmLabels.ts` (DE/EN values from Interfaces).

- [ ] **Step 5: Rework ChangeDetailPage**

In `frontend/src/pages/ChangeDetailPage.tsx`:
1. Import `LifecycleStepper`, `CockpitSummary`, `useDepartments`; delete the inline `Stepper` function (L255-270) and its `CHANGE_STATUS_ORDER` import if now unused.
2. Add queries: gates (`queryKey: ['change', changeId, 'gates']`, `queryFn: () => changesApi.getGates(changeId)`) and deviations (`['change', changeId, 'deviations']`, `changesApi.listDeviations(changeId)`); compute `const pendingDeviations = deviations.filter((d) => d.status === 'pending').length` (read `TransitionDeviation` in `types/change.ts` for the real status field/value first). Drop the `enabled:` restriction on the `impl` query's status list? NO — keep it; pass `impl` through as-is.
3. Replace `<Stepper status={change.status} />` with `<LifecycleStepper status={change.status} />`.
4. DELETE the transition-button row (L129-142) and insert `<CockpitSummary change={change} gates={gates} pendingDeviations={pendingDeviations} impl={impl} onAdvance={advance} advancing={transition.isPending} />` between the dialogs and the tab bar. Keep the on_hold Resume behavior: `advance('in_assessment')` is reachable because on_hold renders no NEXT buttons — add on_hold explicitly: in CockpitSummary the off-path branch already shows the status; for Resume, ChangeDetailPage keeps a small "Resume" button next to Cancel in the header when `change.status === 'on_hold'`.
5. Assessments tab: `const { data: departments = [] } = useDepartments()` and build `const deptName = (id: number) => departments.find((d) => d.id === id)?.name ?? '#' + id` (adapt to the hook's actual return shape — READ `useWorkflows.ts` first); replace both `Dept #{a.department_id}` occurrences (L189, L197) with `{deptName(a.department_id)}`, and extend the assessment row with owner/overdue: after the verdict span add

```tsx
<span className="text-slate-400 text-xs">
  {a.owner_name ?? t('tasks.unclaimed')}
  {a.overdue && <span className="text-red-400 ml-2">⚠ {t('tasks.overdue')}</span>}
</span>
```

6. gate query invalidation: `transition.onSuccess` already invalidates `['change', changeId]` — broaden to prefix invalidation `qc.invalidateQueries({ queryKey: ['change', changeId] })` (already a prefix — verify gates/deviations keys start with the same prefix so they refetch).

- [ ] **Step 6: Run tests + full frontend verification**

Run: `cd frontend && npx vitest run && npx tsc --noEmit 2>&1 | grep -cE "error TS"`
Expected: all tests pass (45+); tsc count == baseline.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/changes/LifecycleStepper.tsx \
        frontend/src/components/changes/LifecycleStepper.test.tsx \
        frontend/src/components/changes/CockpitSummary.tsx \
        frontend/src/components/changes/CockpitSummary.test.tsx \
        frontend/src/pages/ChangeDetailPage.tsx frontend/src/i18n/cmLabels.ts
git commit -m "feat(cockpit): lifecycle stepper, where/blocking/next summary, resolved names"
```

---

## Task 7: Audit timeline view + export

**Tier:** sonnet (component work against a fixed API).

**Files:**
- Create: `frontend/src/api/audit.ts`, `frontend/src/components/changes/AuditTimeline.tsx`, `frontend/src/components/changes/AuditTimeline.test.tsx`
- Modify: `frontend/src/pages/ChangeDetailPage.tsx` (audit tab), `frontend/src/i18n/cmLabels.ts`

**Interfaces:**
- Consumes (Phase A backend, `backend/app/api/v1/audit.py` — verified live):
  - `GET /v1/audit?correlation_id=&entity_type=&limit=&offset=` → `AuditEntry[]` `{id, entity_type, entity_id, action, user_id, timestamp, old_values, new_values, correlation_id, log_level}` (old/new_values are JSON strings or null), ordered by id (chain order).
  - `GET /v1/audit/verify` → `{valid: boolean, checked: number, first_broken_id: number | null}`.
  - `GET /v1/audit/export?correlation_id=` → CSV stream.
- Produces:

```ts
// frontend/src/api/audit.ts
import client from './client'

export interface AuditEntry {
  id: number
  entity_type: string
  entity_id: number
  action: string
  user_id: number | null
  timestamp: string
  old_values: string | null
  new_values: string | null
  correlation_id: string | null
  log_level: string
}
export interface AuditVerify { valid: boolean; checked: number; first_broken_id: number | null }

export const auditApi = {
  list: (params: { correlation_id?: string; entity_type?: string; limit?: number; offset?: number }) =>
    client.get<AuditEntry[]>('/v1/audit', { params }).then((r) => r.data),
  verify: () => client.get<AuditVerify>('/v1/audit/verify').then((r) => r.data),
  downloadCsv: async (params: { correlation_id?: string }) => {
    const res = await client.get('/v1/audit/export', { params, responseType: 'blob' })
    const url = URL.createObjectURL(res.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `audit_${params.correlation_id ?? 'export'}.csv`
    a.click()
    URL.revokeObjectURL(url)
  },
}
```

  - `<AuditTimeline correlationId={string} />` — self-fetching (`queryKey: ['audit', correlationId]`); renders: header row with chain-integrity badge (verify query: green `✓ {t('audit.chainOk')}` / red `✗ {t('audit.chainBroken')}`) and an Export CSV button; entity-type filter chips (`all | change | wf_instance | part_revision` — derive the set from the loaded entries, "all" first); entries newest-first, grouped by calendar day (`toLocaleDateString()` headings), each row: time (mono, slate-500), humanized action (`action.replace(/_/g, ' ')`, slate-100), entity chip (`{entity_type}#{entity_id}`, slate-500 text-xs), expandable old/new values (`<details>` with `JSON.parse` pretty-print when parseable, raw string otherwise — wrap parse in try/catch). Empty state: `t('audit.empty')`.
  - Labels: `audit.title` (DE 'Audit-Trail', EN 'Audit trail'), `audit.chainOk` (DE 'Kette intakt', EN 'chain intact'), `audit.chainBroken` (DE 'Kette beschädigt', EN 'chain broken'), `audit.export` (DE 'CSV exportieren', EN 'Export CSV'), `audit.empty` (DE 'Noch keine Audit-Einträge.', EN 'No audit entries yet.'), `audit.all` (DE 'Alle', EN 'All').
  - ChangeDetailPage audit tab renders `<AuditTimeline correlationId={change.change_number} />` INSTEAD of the changelog `<ol>`; the `changelog` query (L51-55) is deleted (AuditLog dual-writes every changelog action since Phase A, so nothing is lost — the pre-Phase-A history of old changes lives only in ChangeChangelog, acceptable per spec "AuditLog becomes the cross-entity queryable layer").

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/changes/AuditTimeline.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AuditTimeline from './AuditTimeline'
import { auditApi } from '../../api/audit'

vi.mock('../../api/audit', () => ({
  auditApi: { list: vi.fn(), verify: vi.fn(), downloadCsv: vi.fn() },
}))

const entry = (over: Record<string, unknown>) => ({
  id: 1, entity_type: 'change', entity_id: 7, action: 'status_changed',
  user_id: 5, timestamp: '2026-07-01T10:00:00', old_values: '{"status": "captured"}',
  new_values: '{"status": "in_assessment"}', correlation_id: 'CR-2026-0007',
  log_level: 'info', ...over,
})

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('AuditTimeline', () => {
  beforeEach(() => {
    vi.mocked(auditApi.list).mockResolvedValue([
      entry({ id: 2, action: 'gate_decided', entity_type: 'change' }),
      entry({ id: 1, action: 'wf_started', entity_type: 'wf_instance', entity_id: 3 }),
    ])
    vi.mocked(auditApi.verify).mockResolvedValue({ valid: true, checked: 42, first_broken_id: null })
  })
  afterEach(cleanup)

  it('renders entries with humanized actions and chain badge', async () => {
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    expect(await screen.findByText('gate decided')).toBeDefined()
    expect(screen.getByText('wf started')).toBeDefined()
    expect(screen.getByText(/chain intact/)).toBeDefined()
  })

  it('filters by entity type and exports', async () => {
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    await screen.findByText('gate decided')
    fireEvent.click(screen.getByRole('button', { name: 'wf_instance' }))
    expect(screen.queryByText('gate decided')).toBeNull()
    expect(screen.getByText('wf started')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: /Export CSV/ }))
    expect(auditApi.downloadCsv).toHaveBeenCalledWith({ correlation_id: 'CR-2026-0007' })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/changes/AuditTimeline.test.tsx`
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement `api/audit.ts` and `AuditTimeline.tsx`**

`api/audit.ts` exactly as in Interfaces. Component:

```tsx
// frontend/src/components/changes/AuditTimeline.tsx
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { auditApi, type AuditEntry } from '../../api/audit'
import { t } from '../../i18n/cmLabels'

const pretty = (s: string | null): string | null => {
  if (!s) return null
  try { return JSON.stringify(JSON.parse(s), null, 2) } catch { return s }
}

export default function AuditTimeline({ correlationId }: { correlationId: string }) {
  const [entityFilter, setEntityFilter] = useState<string>('all')
  const { data: entries = [], isLoading } = useQuery({
    queryKey: ['audit', correlationId],
    queryFn: () => auditApi.list({ correlation_id: correlationId, limit: 1000 }),
  })
  const { data: chain } = useQuery({ queryKey: ['audit-verify'], queryFn: auditApi.verify })

  const entityTypes = useMemo(
    () => Array.from(new Set(entries.map((e) => e.entity_type))), [entries])
  const shown = useMemo(() => {
    const filtered = entityFilter === 'all' ? entries
      : entries.filter((e) => e.entity_type === entityFilter)
    return [...filtered].sort((a, b) => b.id - a.id)
  }, [entries, entityFilter])

  const byDay = useMemo(() => {
    const groups = new Map<string, AuditEntry[]>()
    for (const e of shown) {
      const day = new Date(e.timestamp).toLocaleDateString()
      if (!groups.has(day)) groups.set(day, [])
      groups.get(day)!.push(e)
    }
    return Array.from(groups.entries())
  }, [shown])

  if (isLoading) return <div className="text-slate-400 text-sm">…</div>

  return (
    <div>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-200">{t('audit.title')}</h3>
          {chain && (
            <span className={`text-xs px-2 py-0.5 rounded-full ${
              chain.valid ? 'bg-emerald-900 text-emerald-200' : 'bg-red-900 text-red-200'}`}>
              {chain.valid ? `✓ ${t('audit.chainOk')}` : `✗ ${t('audit.chainBroken')}`}
            </span>
          )}
        </div>
        <button
          className="text-xs border border-slate-600 text-slate-300 hover:bg-slate-700 px-3 py-1.5 rounded-lg"
          onClick={() => auditApi.downloadCsv({ correlation_id: correlationId })}>
          ⬇ {t('audit.export')}
        </button>
      </div>

      <div className="flex gap-1.5 mb-4 flex-wrap">
        {['all', ...entityTypes].map((et) => (
          <button key={et}
            className={`text-xs px-2.5 py-1 rounded-full ${
              entityFilter === et ? 'bg-sky-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
            onClick={() => setEntityFilter(et)}>
            {et === 'all' ? t('audit.all') : et}
          </button>
        ))}
      </div>

      {shown.length === 0 && <p className="text-sm text-slate-500">{t('audit.empty')}</p>}
      {byDay.map(([day, dayEntries]) => (
        <div key={day} className="mb-4">
          <h4 className="text-xs uppercase tracking-wide text-slate-500 mb-2">{day}</h4>
          <ol className="space-y-1.5 border-l border-slate-700 pl-4">
            {dayEntries.map((e) => (
              <li key={e.id} className="text-sm">
                <span className="font-mono text-xs text-slate-500 mr-2">
                  {new Date(e.timestamp).toLocaleTimeString()}
                </span>
                <span className="text-slate-100">{e.action.replace(/_/g, ' ')}</span>
                <span className="ml-2 text-xs text-slate-500">{e.entity_type}#{e.entity_id}</span>
                {(e.old_values || e.new_values) && (
                  <details className="ml-6 mt-0.5">
                    <summary className="text-xs text-slate-500 cursor-pointer">details</summary>
                    <pre className="text-xs text-slate-400 bg-slate-900 rounded p-2 mt-1 overflow-x-auto">
{pretty(e.old_values) ? `- ${pretty(e.old_values)}\n` : ''}{pretty(e.new_values) ? `+ ${pretty(e.new_values)}` : ''}
                    </pre>
                  </details>
                )}
              </li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  )
}
```

Add the six `audit.*` labels to `cmLabels.ts`. In `ChangeDetailPage.tsx`: replace the audit tab body (L241-250) with `<AuditTimeline correlationId={change.change_number} />`, delete the `changelog` query and the now-unused `ChangelogEntry` import if any.

- [ ] **Step 4: Run tests + verification**

Run: `cd frontend && npx vitest run && npx tsc --noEmit 2>&1 | grep -cE "error TS"`
Expected: all pass (47+); tsc == baseline.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/audit.ts frontend/src/components/changes/AuditTimeline.tsx \
        frontend/src/components/changes/AuditTimeline.test.tsx \
        frontend/src/pages/ChangeDetailPage.tsx frontend/src/i18n/cmLabels.ts
git commit -m "feat(audit): hash-chain timeline view with filters, verify badge, CSV export"
```

---

## Task 8: Context-first change initiation (StartChangeModal)

**Tier:** opus (UX-critical, spec scope 0).

**Files:**
- Create: `frontend/src/components/changes/StartChangeModal.tsx`, `StartChangeModal.test.tsx`
- Modify: `frontend/src/pages/ChangesPage.tsx` (replace CreateChangeModal), `frontend/src/pages/PartDetail.tsx` (header button), `frontend/src/pages/ProjectDetailPage.tsx` (header button), `frontend/src/api/changes.ts` (`addImpactedItem` body += `is_lead`), `frontend/src/i18n/cmLabels.ts`

**Interfaces:**
- Consumes: `GET /v1/plants/projects` (projects list `{id, name}[]` — the shape ProjectsPage uses at L30, read it), `GET /v1/parts/project/{projectId}` (parts list — read ProjectDetailPage L88 for the shape; parts have `id`, `part_number`, `name`, `item_category`), `changesApi.create` (accepts `lead_id`), `changesApi.addImpactedItem` (backend accepts `is_lead: boolean` — verified live in Phase C smoke; ADD it to the fn's body type), `useAuth().userId`, `useNavigate`.
- Produces:

```ts
interface StartChangePrefill {
  projectId?: number
  part?: { id: number; part_number: string; name: string; item_category: string }
}
interface StartChangeModalProps {
  open: boolean
  onClose: () => void
  prefill?: StartChangePrefill
}
```

  Behavior (spec scope 0, exact):
  - **Project select** — dropdown of projects by NAME (no free-text ID). Locked (rendered as static text) when `prefill.projectId` is set.
  - **Item picker** — searchable: a text input filtering the project's parts by `part_number` + `name` (case-insensitive substring), results grouped under "Articles" and "Tools" headings (`item_category === 'article'` → Articles; everything else → Tools group, labeled per category). Clicking a result selects it (shown as a chip with an ✕ to clear). Pre-selected when `prefill.part` given. REQUIRED — submit disabled without a part (context-first is the point; the item IS the context).
  - **change_type inference** — `tool`/`gauge`/`equipment` categories → `tooling`; `article` → `physical_part`; user can override via the type select (options = the existing `CHANGE_TYPES` from ChangesPage — move that const into the modal file).
  - **Title** (required), **Reason** (textarea, optional).
  - Submit: `changesApi.create({ project_id, title, change_type, reason, lead_id: userId ?? undefined })` → `changesApi.addImpactedItem(change.id, { part_id, is_lead: true })` → `onClose()` → `navigate('/changes/' + change.id)`. Errors → `toast.error(errDetail(e) ?? ...)`.
  - Dark-slate styling (`bg-slate-800` panel, explicit — NOT `bg-white`).
- Mount points:
  - `ChangesPage`: delete the old `CreateChangeModal` (L103-149); "New Change" button opens `<StartChangeModal open onClose prefill={undefined} />`.
  - `PartDetail`: "Start change" button in the header action area (read the header around L172+ first; place beside existing actions) opening the modal with `prefill={{ projectId: part.project_id, part: { id: part.id, part_number: part.part_number, name: part.name, item_category: part.item_category } }}` (verify the part object's field names in the page's Part type first).
  - `ProjectDetailPage`: "Start change" button near the page header (read the header area first) with `prefill={{ projectId: Number(projectId) }}`.
- Labels: `start.title` (DE 'Änderung starten', EN 'Start change'), `start.project` (DE 'Projekt', EN 'Project'), `start.item` (DE 'Betroffenes Teil', EN 'Affected item'), `start.searchItem` (DE 'Teil suchen…', EN 'Search item…'), `start.articles` (DE 'Artikel', EN 'Articles'), `start.tools` (DE 'Werkzeuge & Betriebsmittel', EN 'Tools & equipment'), `start.changeTitle` (DE 'Titel', EN 'Title'), `start.reason` (DE 'Begründung', EN 'Reason'), `start.type` (DE 'Änderungsart', EN 'Change type'), `start.create` (DE 'Änderung anlegen', EN 'Create change').

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/changes/StartChangeModal.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import StartChangeModal from './StartChangeModal'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('../../api/changes', () => ({
  changesApi: {
    create: vi.fn().mockResolvedValue({ id: 42, change_number: 'CR-2026-0042' }),
    addImpactedItem: vi.fn().mockResolvedValue({}),
  },
}))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ userId: 5 }),
}))
const navigate = vi.fn()
vi.mock('react-router-dom', async (orig) => ({
  ...(await orig()), useNavigate: () => navigate,
}))
import { changesApi } from '../../api/changes'

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
}

describe('StartChangeModal', () => {
  beforeEach(() => {
    navigate.mockClear()
    vi.mocked(changesApi.create).mockClear()
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('/plants/projects'))
        return Promise.resolve({ data: [{ id: 1, name: 'VW426 Atlas' }] })
      if (url.includes('/parts/project/'))
        return Promise.resolve({ data: [
          { id: 4, part_number: '20-3450-001-0', name: 'Clip', item_category: 'article' },
          { id: 9, part_number: '3450', name: 'Tool 3450', item_category: 'tool' },
        ] })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('infers tooling type from a tool prefill and creates change + lead item', async () => {
    wrap(<StartChangeModal open onClose={() => {}} prefill={{
      projectId: 1,
      part: { id: 9, part_number: '3450', name: 'Tool 3450', item_category: 'tool' },
    }} />)
    expect((screen.getByLabelText(/Change type/) as HTMLSelectElement).value).toBe('tooling')
    fireEvent.change(screen.getByLabelText(/Title/), { target: { value: 'Fix cavity' } })
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))
    await waitFor(() => expect(changesApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: 1, change_type: 'tooling', lead_id: 5 })))
    await waitFor(() => expect(changesApi.addImpactedItem).toHaveBeenCalledWith(
      42, { part_id: 9, is_lead: true }))
    expect(navigate).toHaveBeenCalledWith('/changes/42')
  })

  it('requires picking an item when not prefilled', async () => {
    wrap(<StartChangeModal open onClose={() => {}} prefill={{ projectId: 1 }} />)
    fireEvent.change(screen.getByLabelText(/Title/), { target: { value: 'X' } })
    expect(screen.getByRole('button', { name: /Create change/ })).toHaveProperty('disabled', true)
    fireEvent.change(screen.getByPlaceholderText(/Search item/), { target: { value: 'clip' } })
    fireEvent.click(await screen.findByText(/20-3450-001-0/))
    expect(screen.getByRole('button', { name: /Create change/ })).toHaveProperty('disabled', false)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/changes/StartChangeModal.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the modal**

Build `StartChangeModal.tsx` to the Interfaces contract. Skeleton (fill in the full JSX; labels via `t()`; every input gets an `id` + `<label htmlFor>` so the tests' `getByLabelText` works):

```tsx
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import client from '../../api/client'
import { changesApi } from '../../api/changes'
import { useAuth } from '../../contexts/AuthContext'
import { t } from '../../i18n/cmLabels'
import type { ChangeType } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const inferType = (category: string): ChangeType =>
  ['tool', 'gauge', 'equipment'].includes(category) ? 'tooling' : 'physical_part'
```

State: `projectId` (from prefill or select), `picked` part (from prefill or picker), `search`, `title`, `reason`, `changeType` (recomputed via `inferType` whenever `picked` changes UNLESS the user has manually overridden — track `typeTouched`). Queries: projects (`['projects']`, skip when prefilled+locked), parts (`['project-parts', projectId]`, `enabled: !!projectId`). Submit handler per Interfaces (async, sequential create → addImpactedItem → navigate; on addImpactedItem failure still navigate but `toast.error` — the change exists; user lands on it and can add items in the impact tree).

Update `frontend/src/api/changes.ts` `addImpactedItem` body type: `{ part_id: number; is_lead?: boolean; impact_note?: string; eng_level_before?: string }`.

- [ ] **Step 4: Wire the three mount points**

1. `ChangesPage.tsx`: delete `CreateChangeModal` (L103-149) and its usage; `{showCreate && <StartChangeModal open onClose={() => setShowCreate(false)} />}`; move `CHANGE_TYPES` into `StartChangeModal.tsx` (ChangesPage keeps no copy — check for other users first).
2. `PartDetail.tsx`: read the header region; add a `Start change`-labeled button (`bg-sky-600` primary style consistent with the page) + modal state + `<StartChangeModal>` with the part prefill (map the page's part object fields; `item_category` exists on the Part type — verify name).
3. `ProjectDetailPage.tsx`: read the header region; same pattern with `prefill={{ projectId: Number(projectId) }}`.

Add the ten `start.*` labels to `cmLabels.ts`.

- [ ] **Step 5: Run tests + full verification**

Run: `cd frontend && npx vitest run && npx tsc --noEmit 2>&1 | grep -cE "error TS"`
Expected: all pass (49+); tsc == baseline.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/changes/StartChangeModal.tsx \
        frontend/src/components/changes/StartChangeModal.test.tsx \
        frontend/src/pages/ChangesPage.tsx frontend/src/pages/PartDetail.tsx \
        frontend/src/pages/ProjectDetailPage.tsx frontend/src/api/changes.ts \
        frontend/src/i18n/cmLabels.ts
git commit -m "feat(change): context-first Start Change from part/project with item picker"
```

**NOTE:** `ProjectDetailPage.tsx` may carry an unrelated uncommitted diff (part-tree sorting). `git add` the file only if that diff was committed separately first — otherwise stage hunks via asking the user / committing the sort change separately BEFORE this task. Surface it, don't silently bundle.

---

## Task 9: Kill the last `alert()`/`window.prompt`

**Tier:** haiku (mechanical, established toast pattern).

**Files:**
- Modify: `frontend/src/pages/ChangeDetailPage.tsx` (2× alert), `frontend/src/components/changes/DeviationBanner.tsx` (1×), `frontend/src/components/changes/ImplementationPanel.tsx` (1×), `frontend/src/components/changes/ImpactTree.tsx` (1×), `frontend/src/pages/UsersPage.tsx` (window.prompt)

**Interfaces:**
- Every `alert(x)` becomes `toast.error(x)` with `import { toast } from 'sonner'` added where missing. Exact sites (verify with grep first — Task 6/7 edits may have shifted lines): `ChangeDetailPage.tsx` transition onError cancel branch + signOff onError; `DeviationBanner.tsx:38`; `ImplementationPanel.tsx:38`; `ImpactTree.tsx:63`.
- `UsersPage.tsx` `window.prompt('New password…')` (≈L237) becomes a local `SetPasswordModal`: read the surrounding mutation first and KEEP it — only the input mechanism changes.

```tsx
function SetPasswordModal({ userName, onSubmit, onClose }: {
  userName: string
  onSubmit: (password: string) => void
  onClose: () => void
}) {
  const [pw, setPw] = useState('')
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 w-full max-w-sm">
        <h2 className="text-lg font-semibold text-slate-100 mb-3">Set password — {userName}</h2>
        <input type="password" autoFocus minLength={8}
          className="w-full rounded-lg px-3 py-2 text-sm"
          placeholder="New password (min 8 characters)"
          value={pw} onChange={(e) => setPw(e.target.value)} />
        <div className="flex justify-end gap-2 mt-4">
          <button className="px-4 py-2 text-sm text-slate-300" onClick={onClose}>Cancel</button>
          <button className="px-4 py-2 rounded-lg bg-sky-600 text-white text-sm disabled:opacity-50"
            disabled={pw.length < 8}
            onClick={() => { onSubmit(pw); onClose() }}>Set password</button>
        </div>
      </div>
    </div>
  )
}
```

(adapt naming/props to how UsersPage tracks the target user — read the page first).

- [ ] **Step 1: Locate all sites**

Run: `cd frontend && grep -rn "alert(\|window.prompt\|window.confirm" src --include="*.tsx" | grep -v ".test."`
Expected: exactly the 6 sites listed (or fewer if earlier tasks touched them). Fix every hit.

- [ ] **Step 2: Implement replacements** (toast.error swaps + SetPasswordModal per Interfaces).

- [ ] **Step 3: Verify zero remain + suites**

Run: `cd frontend && grep -rn "alert(\|window.prompt\|window.confirm" src --include="*.tsx" | grep -v ".test." | wc -l && npx vitest run && npx tsc --noEmit 2>&1 | grep -cE "error TS"`
Expected: `0`; all tests pass; tsc == baseline.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ChangeDetailPage.tsx frontend/src/pages/UsersPage.tsx \
        frontend/src/components/changes/DeviationBanner.tsx \
        frontend/src/components/changes/ImplementationPanel.tsx \
        frontend/src/components/changes/ImpactTree.tsx
git commit -m "feat(frontend): replace alert/prompt with toasts and a proper password modal"
```

---

## Task 10: Theme cleanup — non-shimmed light classes

**Tier:** haiku (mechanical, explicit mapping).

**Files:**
- Modify: `frontend/src/components/ViewerToolbar.tsx`, `frontend/src/components/Viewer3D.tsx`, `frontend/src/components/MeasurementReadout.tsx`, `frontend/src/components/CutPlaneControls.tsx`, `frontend/src/components/ObjectTree.tsx`, `frontend/src/pages/PartDetail.tsx`, `frontend/src/pages/ChangesPage.tsx`, `frontend/src/components/common/ConfirmModal.tsx`, `frontend/src/components/workflows/StartWorkflowModal.tsx`

**Interfaces:** The `index.css` shim (L128-175) stays. Only classes the shim does NOT cover get fixed, per this mapping (apply as literal class replacements in the listed files — do not restructure markup):

| Light class (non-shimmed) | Replacement |
|---|---|
| `bg-gray-300` | `bg-slate-700` |
| `text-gray-800` | `text-slate-200` |
| `hover:bg-gray-50` | `hover:bg-slate-800/60` |
| `divide-gray-200` | `divide-slate-700` |
| `bg-gray-400` | `bg-slate-600` |
| `text-gray-300` (on light bg) | `text-slate-400` |
| `shadow-md` / `shadow-lg` (on cards) | `shadow-panel` |

While touching a file, ALSO make its shimmed classes explicit (e.g. `bg-white` → `bg-slate-800`, `bg-gray-50` → `bg-slate-800`, `text-gray-900` → `text-slate-100`, `text-gray-700`/`600`/`500` → `text-slate-300`/`400`/`500`, `border-gray-200`/`300` → `border-slate-700`, `hover:bg-gray-100/200` → `hover:bg-slate-700`) — the shim is a safety net, not a target state. ONLY in the nine listed files; do not sweep the whole codebase.

- [ ] **Step 1: Fix per file** — for each of the nine files: read it, apply the mapping, keep layout/behavior identical.

- [ ] **Step 2: Verify no non-shimmed light classes remain in the touched files**

Run:
```bash
cd frontend && grep -n "bg-gray-300\|bg-gray-400\|text-gray-800\|hover:bg-gray-50\b\|divide-gray-200" \
  src/components/ViewerToolbar.tsx src/components/Viewer3D.tsx \
  src/components/MeasurementReadout.tsx src/components/CutPlaneControls.tsx \
  src/components/ObjectTree.tsx src/pages/PartDetail.tsx src/pages/ChangesPage.tsx \
  src/components/common/ConfirmModal.tsx src/components/workflows/StartWorkflowModal.tsx
```
Expected: zero hits.

- [ ] **Step 3: Suites**

Run: `cd frontend && npx vitest run && npx tsc --noEmit 2>&1 | grep -cE "error TS"`
Expected: all pass; tsc == baseline.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ViewerToolbar.tsx frontend/src/components/Viewer3D.tsx \
        frontend/src/components/MeasurementReadout.tsx frontend/src/components/CutPlaneControls.tsx \
        frontend/src/components/ObjectTree.tsx frontend/src/pages/PartDetail.tsx \
        frontend/src/pages/ChangesPage.tsx frontend/src/components/common/ConfirmModal.tsx \
        frontend/src/components/workflows/StartWorkflowModal.tsx
git commit -m "style(theme): dark-slate consistency for 3D viewer cluster and stragglers"
```

---

## Task 11: Final verification

**Tier:** sonnet (verification), opus (whole-branch review — dispatched by the controller per SDD).

**Files:** none (fix regressions where they surface).

- [ ] **Step 1: Full backend suite + migration idempotency**

Run: `cd backend && python3 -m pytest && alembic upgrade head && alembic upgrade head`
Expected: 186+ pass; both alembic runs exit 0.

- [ ] **Step 2: Frontend suite + types + scoped lint**

Run: `cd frontend && npx vitest run && npx tsc --noEmit 2>&1 | grep -cE "error TS"`
Expected: 49+ pass; tsc == Task 3 baseline.
Run: `npm run lint 2>&1 | grep -A6 -E "(ChangeDetailPage|ChangesPage|LifecycleStepper|CockpitSummary|AuditTimeline|StartChangeModal|changeStatus|UsersPage|audit)\.(tsx|ts)$"`
Expected: zero errors under Phase D-touched file headers.

- [ ] **Step 3: Spec cross-check (manual)**

- Cockpit answers where/blocking/who/next at a glance → Task 6.
- One visually primary next action per screen → Task 6 (CockpitSummary Next panel).
- Audit timeline view, filterable + exportable, chain-verify surfaced → Task 7.
- Context-first initiation from part/project, fallback picker, no free-text IDs → Task 8.
- No `window.prompt`/`alert` → Task 9 (grep proves zero).
- Resolved names instead of raw IDs → Tasks 5/6 (lead_name, dept names, owner names).
- One consistent dark-slate theme → Task 10.
- Legacy Article stack retired (backend + frontend + tables) → Tasks 2/3.
- Audit action column fits every written action → Task 1.

- [ ] **Step 4: Live smoke (controller dispatches, mirroring Phase C)**

Boot the real backend (`uvicorn app.main:app --port 8001`, conda env per `run_backend.sh`), then over HTTP: confirm `/api/v1/articles` → 404 and `/api/v1/catalog-parts` → 200; create a change via the context-first payload sequence (create with `lead_id`, `addImpactedItem` with `is_lead: true`); fetch `/api/v1/audit?correlation_id=<its change number>` and confirm the `created` + `impacted_item_added` entries; hit `/api/v1/audit/export?correlation_id=...` and confirm CSV; `/api/v1/audit/verify` → `valid: true`. Cancel the smoke change (with `cancellation_reason`), kill the server.

- [ ] **Step 5: Commit any verification fixes**

```bash
git add <explicit paths only>
git commit -m "test: Phase D verification fixes"
```

(Skip if nothing changed. NEVER `git add -A` at repo root.)
