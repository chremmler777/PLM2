# PLM2 Data Route (from Brose / to Brose) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PLM2's six version-creating entry points with two dialogs: "⬇ Data from Brose" and "⬆ Data to Brose". Unconfirmed data becomes an E x.x carrying a direction marker, and it ends with Confirm (files carried into the next folder) or Close (reason required).

**Architecture:**
- Two nullable columns on `part_revisions`: `direction` and `close_reason`.
- Three new multipart/JSON endpoints that create a version and its files in one transaction: `from-customer`, `iterations`, `confirm`, plus a `close` endpoint.
- The frontend gets two dialogs, launched from the VersionNav header, and a ⋯ menu on iteration rows.
- The old paths are removed from the UI: the "+", "+ Customer package" header, the upload dialog's major branch, and the part page actions. The backend endpoints stay for scripts and tests.

**Tech Stack:**
- Backend: FastAPI, async SQLAlchemy, Alembic, pytest (`uv run pytest`).
- Frontend: React + TypeScript, TanStack Query, Tailwind, lucide-react, vitest + Testing Library (`npx vitest run`).

**Spec:** `docs/superpowers/specs/2026-10-19-data-route-design.md`

## Global Constraints

- Folders (majors) hold confirmed data only. Anything unconfirmed is an E x.x (minor).
- `direction` is one of `from_customer`, `to_customer`, `internal`. It is set on minors only and is null on majors.
- Nothing is created without files and a reason. The iterations endpoint rejects zero files and an empty summary with 422.
- Close requires a non-blank reason (422 otherwise).
- Confirm carries the x.x files into the new major. Siblings are **not** auto-rejected; this changes `apply_promotion`.
- Mail: the event list is unchanged. Close logs `rejected` and Confirm logs `promoted`. Each create dialog has a "don't mail" option, which removes only the outbox rows queued by that request.
- E vs official numbering: the server defaults the statement to `official` if the part already has an official major, else `review`. The dialog can override it.
- Copy is the product's language: "Data from Brose", "Data to Brose", "Confirm", "Close", "awaiting confirmation", "awaiting Brose", "internal check".
- UI work: follow the `impeccable` craft floor. Use lucide icons, never emoji, as icons. Dark slate palette as in `VersionNav.tsx`.
- Prod data writes and deploys need Christoph's explicit OK. Say up front which ones send mail.

## Review Focus

1. **Brose files with the index of an existing folder** (e.g. the drawing arrives a week later) must go into that folder, not create a new major. Pinned in Task 4: `test_from_customer_existing_index_adds_files`.
2. **"Don't mail" on a project that already has other pending outbox rows** must remove only this request's rows. Pinned in Task 3: `test_discard_new_keeps_other_rows`.
3. **Confirm while another index of the part already waits for triage** must answer 409 with a message, not a 500 and not a silent supersede. Pinned in Task 5: `test_confirm_while_intake_pending_is_409`.
4. **A whitespace-only reason or summary** counts as empty: 422 for Close and Iteration. Pinned in Tasks 5 and 4.
5. **Confirmed files deleted later on the x.x** must not vanish from the new folder (shared stored file, soft delete). Pinned in Task 2: `test_copy_files_survives_source_soft_delete`.

---

## File Structure

**Backend**
- `backend/alembic/versions/146_revision_direction.py` (create): columns `direction` and `close_reason`. See Task 0 for the number.
- `backend/app/models/part.py` (modify): the two columns.
- `backend/app/schemas/part.py` (modify): response fields, plus `ConfirmIterationRequest` and `CloseRevisionRequest`.
- `backend/app/services/data_route_service.py` (create): the routing logic for the new flows (`from_customer`, `create_iteration`, `confirm`, `close`, `copy_files`). Keeps `part_service.py` from growing.
- `backend/app/services/part_service.py` (modify): `create_proposal` takes `direction`; `apply_promotion` no longer rejects siblings; `unreject_revision` clears `close_reason`.
- `backend/app/services/part_data_mail.py` (modify): `pending_ids(session, revision_id)` and `discard_new(session, revision_id, before)`.
- `backend/app/services/customer_naming.py` (modify): `ParsedName.draft`.
- `backend/app/api/v1/items/data_route.py` (create): the four endpoints. Registered next to the parts router.
- `backend/scripts/backfill_1994_direction.py` (create): sets direction on existing 1994 minors.
- Tests (create): `backend/tests/test_data_route_service.py`, `backend/tests/test_data_route_api.py`.

**Frontend**
- `frontend/src/api/dataRoute.ts` (create): API calls.
- `frontend/src/components/parts/DataFromBroseDialog.tsx` (create).
- `frontend/src/components/parts/DataToBroseDialog.tsx` (create).
- `frontend/src/components/parts/IterationActions.tsx` (create): the ⋯ menu with the Confirm, Close and Reopen dialogs.
- `frontend/src/components/parts/versionTree.ts` (modify): direction-aware `versionState`.
- `frontend/src/components/parts/VersionNav.tsx` (modify): header buttons, direction icon, ⋯ menu, "+" removed.
- `frontend/src/components/project/DocumentsTab.tsx` (modify): wiring; header "+ Customer package" and empty-state "+ Customer data" removed.
- `frontend/src/components/parts/UploadDialog.tsx` (modify): major branch removed, "looks like new Brose data" hint added.
- `frontend/src/pages/PartDetail.tsx` (modify): timeline read-only plus a link.
- `frontend/src/components/project/projectTypes.ts` (modify): `direction` and `close_reason` on `PartRevision`.
- Tests next to each component.

---

### Task 0: Agree the migration number with the ECR session

**Files:** none (coordination).

The `feature/ecr-solid` branch (owned by the "addi plm" session) holds migrations 117–145, with 117 revising "116", and is not merged to main yet. This plan's migration must not collide with it.

- [ ] **Step 1:** Run `git fetch origin && git ls-tree --name-only origin/feature/ecr-solid backend/alembic/versions/ | sort | tail -1` and note the highest number N.
- [ ] **Step 2:** Use ListAgents and SendMessage to tell the ECR session: "data-route will add migration N+1 (`revision_direction`, revises N). It ships after ecr-solid is merged to main. Please tell me if you add more migrations before merging." Wait for the answer.
- [ ] **Step 3:** Decide:
  - If ecr-solid will merge before this deploys (the default), use number N+1 with `down_revision = "N"`. At plan time N = 145, so the file is `146_revision_direction.py`. Build and test on a branch based on main. **Before deploy, rebase onto main after ECR has merged.** Locally, the migration is exercised only via the test DB's `create_all`, so the gap does not block tests. Confirm by checking `backend/tests/conftest.py`: the tables come from `Base.metadata.create_all`.
  - If Christoph wants this before ECR merges, use `117_revision_direction.py` with `down_revision = "116"`, and tell the ECR session to shift to 118+ with their first `down_revision = "117"`.
- [ ] **Step 4:** Record the decision in `memory/session-state-2026-10-19.md` (create it) with one line.

---

### Task 1: Columns `direction` and `close_reason`

**Files:**
- Create: `backend/alembic/versions/146_revision_direction.py` (number per Task 0)
- Modify: `backend/app/models/part.py` (PartRevision, near `source` at ~line 210)
- Modify: `backend/app/schemas/part.py:142` (PartRevisionResponse)
- Modify: `frontend/src/components/project/projectTypes.ts` (PartRevision)
- Test: `backend/tests/test_data_route_service.py`

**Interfaces:**
- Produces:
  - `PartRevision.direction: Optional[str]` and `PartRevision.close_reason: Optional[str]`
  - `PartRevisionResponse.direction` and `.close_reason`
  - module constant `DIRECTIONS = ("from_customer", "to_customer", "internal")` in `app/models/part.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_data_route_service.py
"""Data route: from Brose / to Brose (spec 2026-10-19)."""
import pytest

from app.models.part import DIRECTIONS, PartRevision

pytestmark = pytest.mark.asyncio


async def test_revision_has_direction_and_close_reason(client, eng_auth, part):
    res = await client.get(f"/api/v1/parts/{part['part_id']}/revisions", headers=eng_auth)
    assert res.status_code == 200
    row = res.json()[0]
    assert row["direction"] is None
    assert row["close_reason"] is None
    assert DIRECTIONS == ("from_customer", "to_customer", "internal")
```

Check the top of an existing async test file (e.g. `tests/test_revision_files.py`) for whether `pytestmark` is needed. If those tests run without it (asyncio auto mode), drop the `pytestmark` line here and in every later test file.

- [ ] **Step 2:** Run `cd backend && uv run pytest tests/test_data_route_service.py -q`. Expected: FAIL (ImportError: DIRECTIONS).

- [ ] **Step 3: Implement**

In `backend/app/models/part.py`, after `REVISION_SOURCES = ("customer", "internal")`:

```python
# Minors only: where unconfirmed data came from (spec 2026-10-19 data route).
DIRECTIONS = ("from_customer", "to_customer", "internal")
```

In `class PartRevision`, after the `source` column:

```python
    direction = Column(String(20), nullable=True)      # minors: DIRECTIONS
    close_reason = Column(Text, nullable=True)          # set by Close, cleared by Reopen
```

In `backend/app/schemas/part.py`, inside `PartRevisionResponse`, after `source`:

```python
    direction: Optional[str] = None
    close_reason: Optional[str] = None
```

Migration `backend/alembic/versions/146_revision_direction.py` (copy the header style of `116_tool_moldflow.py`):

```python
"""part_revisions.direction + close_reason (data route from/to Brose)

Revision ID: 146
Revises: 145
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "146"
down_revision = "145"
branch_labels = None
depends_on = None


def _cols(bind):
    return {c["name"] for c in inspect(bind).get_columns("part_revisions")}


def upgrade():
    cols = _cols(op.get_bind())
    if "direction" not in cols:
        op.add_column("part_revisions", sa.Column("direction", sa.String(20), nullable=True))
    if "close_reason" not in cols:
        op.add_column("part_revisions", sa.Column("close_reason", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("part_revisions", "close_reason")
    op.drop_column("part_revisions", "direction")
```

In `frontend/src/components/project/projectTypes.ts`, in `PartRevision`, after `customer_received_at`:

```ts
  /** Minors only: where unconfirmed data came from. */
  direction?: 'from_customer' | 'to_customer' | 'internal' | null;
  close_reason?: string | null;
```

- [ ] **Step 4:** Run `uv run pytest tests/test_data_route_service.py -q && cd ../frontend && npx tsc --noEmit -p .`. Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/146_revision_direction.py backend/app/models/part.py backend/app/schemas/part.py backend/tests/test_data_route_service.py frontend/src/components/project/projectTypes.ts
git commit -m "feat(revisions): direction + close_reason columns (data route)"
```

---

### Task 2: Service core: direction on proposals, file carry-over, no sibling rejection, reopen clears reason

**Files:**
- Create: `backend/app/services/data_route_service.py`
- Modify: `backend/app/services/part_service.py`:
  - `create_proposal` (~430)
  - `apply_promotion` (~497)
  - `unreject_revision` (~578)
- Modify: `backend/tests/test_revision_intake.py:547` (sibling expectation)
- Test: `backend/tests/test_data_route_service.py`

**Interfaces:**
- Consumes: Task 1 columns.
- Produces:
  - `RevisionService.create_proposal(session, part_id, parent_revision_id, summary=None, created_by=None, direction: Optional[str] = None) -> PartRevision`, which raises `ValueError` on an unknown direction.
  - `DataRouteService.copy_files(session, src: PartRevision, dst: PartRevision, user_id: int) -> list[RevisionFile]`: new rows sharing `file_path` / `viewer_file_path` / `file_hash`. Logs one changelog `files_carried` (not a mail event).
  - `apply_promotion(...)` approves the proposal and leaves siblings untouched.
  - `unreject_revision(...)` sets `close_reason = None`.

- [ ] **Step 1: Write failing tests** (append to `test_data_route_service.py`)

```python
import os

from sqlalchemy import select

from app.models.part import RevisionFile
from app.services.data_route_service import DataRouteService
from app.services.part_service import RevisionService
from app.services.revision_file_service import store_revision_file


async def _rev(session_factory, rid):
    async with session_factory() as s:
        return await s.get(PartRevision, rid)


async def test_create_proposal_stores_direction(session_factory, part, seed):
    async with session_factory() as s:
        p = await RevisionService.create_proposal(
            s, part["part_id"], part["revision_id"], summary="FZ per DFM",
            created_by=seed["engineer_id"], direction="to_customer")
        await s.commit()
        assert p.direction == "to_customer"
        with pytest.raises(ValueError):
            await RevisionService.create_proposal(
                s, part["part_id"], part["revision_id"], direction="sideways")


async def test_copy_files_shares_the_stored_file(session_factory, part, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    async with session_factory() as s:
        src = await s.get(PartRevision, part["revision_id"])
        dst = await RevisionService.create_proposal(s, part["part_id"], src.id, created_by=seed["engineer_id"])
        f = await store_revision_file(s, src, "a.txt", b"abc", seed["engineer_id"])
        copies = await DataRouteService.copy_files(s, src, dst, seed["engineer_id"])
        await s.commit()
        assert len(copies) == 1
        c = copies[0]
        assert c.revision_id == dst.id and c.id != f.id
        assert c.file_path == f.file_path and c.file_hash == f.file_hash and c.filename == "a.txt"


async def test_copy_files_survives_source_soft_delete(client, eng_auth, session_factory, part, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    async with session_factory() as s:
        src = await s.get(PartRevision, part["revision_id"])
        dst = await RevisionService.create_proposal(s, part["part_id"], src.id, created_by=seed["engineer_id"])
        f = await store_revision_file(s, src, "a.txt", b"abc", seed["engineer_id"])
        (c,) = await DataRouteService.copy_files(s, src, dst, seed["engineer_id"])
        await s.commit()
        fid, cid = f.id, c.id
    assert (await client.delete(f"/api/v1/parts/revision-files/{fid}", headers=eng_auth)).status_code == 200
    res = await client.get(f"/api/v1/parts/revision-files/{cid}/download")
    assert res.status_code == 200 and res.content == b"abc"
```

For sibling rejection, change `backend/tests/test_revision_intake.py:547` from `== "rejected"` to `== "draft"`, and add the comment `# spec 2026-10-19: Confirm leaves sibling iterations open`.

Add the reopen test:

```python
async def test_unreject_clears_close_reason(session_factory, part, seed):
    async with session_factory() as s:
        p = await RevisionService.create_proposal(s, part["part_id"], part["revision_id"], created_by=seed["engineer_id"])
        p.close_reason = "Brose rejected"
        await RevisionService.reject_revision(s, p.id, created_by=seed["engineer_id"])
        await RevisionService.unreject_revision(s, p.id, created_by=seed["engineer_id"])
        await s.commit()
        assert p.close_reason is None and p.status == "draft"
```

Check `conftest.py` for the session fixture name (the code map reports `session_factory` being used in `test_revision_intake.py`). Use exactly that name.

- [ ] **Step 2:** Run `uv run pytest tests/test_data_route_service.py tests/test_revision_intake.py -q`. Expected: the new tests fail (ImportError for `data_route_service`, TypeError for `direction`), and test_revision_intake:547 fails.

- [ ] **Step 3: Implement**

`create_proposal` in `part_service.py`: add the parameter `direction: Optional[str] = None`. At the start, add:

```python
        if direction is not None and direction not in DIRECTIONS:
            raise ValueError(f"direction must be one of {DIRECTIONS}")
```

Then pass `direction=direction` into the `PartRevision(...)` constructor, and import `DIRECTIONS` from `app.models.part`.

`apply_promotion`: delete the whole `if revision.parent_revision_id:` sibling block. Update the docstring to say: "The adopted iteration is approved. Sibling iterations stay open (spec 2026-10-19): a feasibility E1.2 from Brose can coexist with our E1.1."

`unreject_revision`: right where the new status is set, add `revision.close_reason = None`.

Create `backend/app/services/data_route_service.py`:

```python
"""Data route (spec docs/superpowers/specs/2026-10-19-data-route-design.md):
data from Brose / to Brose, Confirm and Close of unconfirmed iterations."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.part import PartRevision, RevisionFile
from app.services.part_service import ChangelogService

# Columns a carried file gets fresh values for; everything else is copied.
_FRESH = {"id", "revision_id", "uploaded_at", "uploaded_by", "is_deleted", "deleted_at"}


class DataRouteService:
    @staticmethod
    async def copy_files(session: AsyncSession, src: PartRevision, dst: PartRevision,
                         user_id: int) -> list[RevisionFile]:
        """Carry src's live files to dst. The stored file is shared (delete is
        soft, so the copy never loses its bytes)."""
        files = (await session.execute(select(RevisionFile).where(
            RevisionFile.revision_id == src.id, RevisionFile.is_deleted == False))).scalars().all()  # noqa: E712
        copies = []
        for f in files:
            data = {c.name: getattr(f, c.name) for c in RevisionFile.__table__.columns if c.name not in _FRESH}
            copy = RevisionFile(**data, revision_id=dst.id, uploaded_by=user_id)
            session.add(copy)
            copies.append(copy)
        await session.flush()
        if copies:
            await ChangelogService.log_action(
                session, part_id=dst.part_id, revision_id=dst.id, action="files_carried",
                action_description=f"{len(copies)} file(s) carried over from {src.revision_name}",
                performed_by=user_id)
        return copies
```

`RevisionFile.__table__.columns` names are the DB column names. If any attribute name differs from its column name (check `models/part.py:295-340`), map through `RevisionFile.__mapper__.column_attrs` instead and use `attr.key`.

- [ ] **Step 4:** Run `uv run pytest tests/test_data_route_service.py tests/test_revision_intake.py tests/test_customer_data_service.py -q`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/data_route_service.py backend/app/services/part_service.py backend/tests/test_data_route_service.py backend/tests/test_revision_intake.py
git commit -m "feat(revisions): direction on iterations, carry files, keep siblings open on confirm"
```

---

### Task 3: "Don't mail" helper

**Files:**
- Modify: `backend/app/services/part_data_mail.py` (after `enqueue`, ~line 130)
- Test: `backend/tests/test_part_data_mail.py`

**Interfaces:**
- Produces:
  - `async def pending_ids(session, revision_id: int) -> set[int]`
  - `async def discard_new(session, revision_id: int, before: set[int]) -> int`: deletes pending outbox rows of that revision whose id is not in `before`, and returns how many it deleted.

- [ ] **Step 1: Write failing test** (append to `tests/test_part_data_mail.py`; reuse that file's existing fixtures for a project with an active list. Read its first 80 lines to find the helper that creates the list. The name below is an example and must match the file.)

```python
async def test_discard_new_keeps_other_rows(session_factory, mail_world):
    from app.models.mail import MailOutbox
    from app.services.part_data_mail import discard_new, enqueue, pending_ids
    async with session_factory() as s:
        old = await enqueue(s, part_id=mail_world["part_id"], action="created", summary="old",
                            performed_by=None, revision_id=mail_world["revision_id"])
        other = await enqueue(s, part_id=mail_world["part_id"], action="created", summary="other part",
                              performed_by=None, revision_id=mail_world["other_revision_id"])
        await s.flush()
        before = await pending_ids(s, mail_world["revision_id"])
        await enqueue(s, part_id=mail_world["part_id"], action="file_uploaded", summary="new",
                      performed_by=None, revision_id=mail_world["revision_id"])
        await s.flush()
        assert await discard_new(s, mail_world["revision_id"], before) == 1
        await s.flush()
        ids = {r.id for r in (await s.execute(select(MailOutbox))).scalars()}
        assert old.id in ids and other.id in ids and len(ids) == 2
```

If `test_part_data_mail.py` has no fixture giving two revisions of one project with an active list, build `mail_world` in the test module from the existing setup helper. It returns `{"part_id", "revision_id", "other_revision_id"}`.

- [ ] **Step 2:** Run `uv run pytest tests/test_part_data_mail.py -k discard_new -q`. Expected: FAIL (ImportError).

- [ ] **Step 3: Implement** (in `part_data_mail.py`, below `enqueue`):

```python
async def pending_ids(session: AsyncSession, revision_id: int) -> set[int]:
    """Pending outbox rows of a revision, before a request queues its own."""
    return set((await session.execute(select(MailOutbox.id).where(
        MailOutbox.revision_id == revision_id, MailOutbox.mail_status == "pending"))).scalars())


async def discard_new(session: AsyncSession, revision_id: int, before: set[int]) -> int:
    """'Don't mail': drop the rows this request queued for the revision, leave
    everything else (other parts, earlier events) alone."""
    await session.flush()
    rows = (await session.execute(select(MailOutbox).where(
        MailOutbox.revision_id == revision_id, MailOutbox.mail_status == "pending"))).scalars().all()
    gone = [r for r in rows if r.id not in before]
    for r in gone:
        await session.delete(r)
    return len(gone)
```

- [ ] **Step 4:** Run `uv run pytest tests/test_part_data_mail.py -q`. Expected: PASS (all).

- [ ] **Step 5: Commit:** `git commit -am "feat(mail): discard_new for 'don't mail' on data-route requests"`

---

### Task 4: Endpoints: Data from Brose, Data to Brose (iterations)

**Files:**
- Modify: `backend/app/services/customer_naming.py` (`ParsedName.draft`)
- Modify: `backend/app/services/data_route_service.py`
- Create: `backend/app/api/v1/items/data_route.py`
- Modify: the router registration where `customer_package` router is included. Find it with `grep -rn "customer_package" backend/app/api/v1/__init__.py backend/app/main.py`.
- Test: `backend/tests/test_data_route_api.py`

**Interfaces:**
- Consumes:
  - `create_proposal(..., direction=)`
  - `pending_ids` and `discard_new`
  - `receive_customer_data`
  - `store_revision_file`
- Produces (HTTP):
  - `POST /api/v1/parts/{part_id}/revisions/from-customer` (multipart). Form fields:
    - `official: bool`
    - `customer_index: str = ""`
    - `target_revision_id: int | None`: an existing major to add files to
    - `parent_revision_id: int | None`: the base for feasibility, default the active revision
    - `received_at: date`
    - `note: str = ""`
    - `statement: str | None`
    - `mail: bool = True`
    - `files: list[UploadFile]` (at least 1)

    Response 201 `{revision: PartRevisionResponse, route: "new_major"|"added"|"iteration", files: [ids]}`.
  - `POST /api/v1/parts/{part_id}/revisions/iterations` (multipart). Form fields:
    - `parent_revision_id: int`
    - `direction: "to_customer"|"internal"`
    - `summary: str` (non-blank)
    - `mail: bool = True`
    - `files` (at least 1)

    Response 201 `PartRevisionResponse`.
- Produces (Python):
  - `DataRouteService.from_customer(session, part_id, *, official, customer_index, target_revision_id, parent_revision_id, received_at, note, statement, files: list[tuple[str, bytes, str | None]], user_id) -> tuple[PartRevision, str, list[RevisionFile]]`
  - `DataRouteService.create_iteration(session, part_id, *, parent_revision_id, direction, summary, files, user_id) -> PartRevision`
- `ParsedName.draft: bool`: True when the name contains `DRAFT`, `DRAFT_MOD` or `DRAFT-MOD`.

Routing rule for `from_customer`, decided in this order:
1. If `target_revision_id` is given, that major must belong to the part and must not be a minor or locked. The files are added to it, and the route is `added`.
2. Else, if `official` and `customer_index` equals (case-insensitive) the index of an existing non-rejected major, the files are added to that major, and the route is `added`.
3. Else, if `official`, call `receive_customer_data(statement=statement or default, customer_index, summary=note or None, intake_source="customer_data")` and then store the files. The route is `new_major`.
4. Else (feasibility), call `create_proposal(parent=parent_revision_id or part.active_revision_id, direction="from_customer", summary=note or "Feasibility data from Brose")` and then store the files. The route is `iteration`.

Default statement: `"official"` if any major of the part has `phase == "official"`, else `"review"`.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_data_route_api.py
"""HTTP tests for the data route (spec 2026-10-19)."""
import pytest

API = "/api/v1/parts"


def _files(*names):
    return [("files", (n, b"x" * 10, "application/octet-stream")) for n in names]


@pytest.fixture(autouse=True)
def _uploads_in_tmp(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)


async def test_from_customer_official_new_index_makes_pending_major(client, eng_auth, part):
    r = await client.post(f"{API}/{part['part_id']}/revisions/from-customer", headers=eng_auth,
                          data={"official": "true", "customer_index": "005", "received_at": "2026-10-15",
                                "note": "GlobalX 15.10."}, files=_files("x_005.txt"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["route"] == "new_major"
    assert body["revision"]["revision_name"] == "E2" and body["revision"]["customer_index"] == "005"
    assert body["revision"]["status"] == "in_review" and len(body["files"]) == 1


async def test_from_customer_existing_index_adds_files(client, eng_auth, part):
    first = (await client.post(f"{API}/{part['part_id']}/revisions/from-customer", headers=eng_auth,
                               data={"official": "true", "customer_index": "005", "received_at": "2026-10-15"},
                               files=_files("model.txt"))).json()
    r = await client.post(f"{API}/{part['part_id']}/revisions/from-customer", headers=eng_auth,
                          data={"official": "true", "customer_index": "005", "received_at": "2026-10-22"},
                          files=_files("drawing.txt"))
    assert r.status_code == 201, r.text
    assert r.json()["route"] == "added"
    assert r.json()["revision"]["id"] == first["revision"]["id"]


async def test_from_customer_feasibility_makes_from_customer_iteration(client, eng_auth, part):
    r = await client.post(f"{API}/{part['part_id']}/revisions/from-customer", headers=eng_auth,
                          data={"official": "false", "received_at": "2026-05-29", "note": "DRAFT_MOD"},
                          files=_files("draft.txt"))
    assert r.status_code == 201, r.text
    rev = r.json()["revision"]
    assert r.json()["route"] == "iteration"
    assert rev["revision_name"] == "E1.1" and rev["direction"] == "from_customer"
    assert rev["parent_revision_id"] == part["revision_id"]


async def test_from_customer_without_files_is_422(client, eng_auth, part):
    r = await client.post(f"{API}/{part['part_id']}/revisions/from-customer", headers=eng_auth,
                          data={"official": "true", "customer_index": "005", "received_at": "2026-10-15"})
    assert r.status_code == 422


async def test_iteration_to_customer(client, eng_auth, part):
    r = await client.post(f"{API}/{part['part_id']}/revisions/iterations", headers=eng_auth,
                          data={"parent_revision_id": str(part["revision_id"]), "direction": "to_customer",
                                "summary": "FZ per DFM, sent via GlobalX"}, files=_files("fz.txt"))
    assert r.status_code == 201, r.text
    assert r.json()["direction"] == "to_customer" and r.json()["summary"].startswith("FZ per DFM")


@pytest.mark.parametrize("summary,files", [("   ", True), ("ok reason", False)])
async def test_iteration_needs_reason_and_files(client, eng_auth, part, summary, files):
    r = await client.post(f"{API}/{part['part_id']}/revisions/iterations", headers=eng_auth,
                          data={"parent_revision_id": str(part["revision_id"]), "direction": "internal",
                                "summary": summary}, files=_files("a.txt") if files else None)
    assert r.status_code == 422


async def test_iteration_rejects_from_customer_direction(client, eng_auth, part):
    r = await client.post(f"{API}/{part['part_id']}/revisions/iterations", headers=eng_auth,
                          data={"parent_revision_id": str(part["revision_id"]), "direction": "from_customer",
                                "summary": "x"}, files=_files("a.txt"))
    assert r.status_code == 422


async def test_dont_mail_flag_reaches_service(client, eng_auth, part, monkeypatch):
    seen = {}
    import app.api.v1.items.data_route as mod

    async def fake_discard(session, revision_id, before):
        seen["rev"] = revision_id
        return 0
    monkeypatch.setattr(mod, "discard_new", fake_discard)
    r = await client.post(f"{API}/{part['part_id']}/revisions/iterations", headers=eng_auth,
                          data={"parent_revision_id": str(part["revision_id"]), "direction": "internal",
                                "summary": "check", "mail": "false"}, files=_files("a.txt"))
    assert r.status_code == 201 and seen["rev"] == r.json()["id"]
```

Also add a unit test for the parser in `backend/tests/test_customer_data_index.py` (append):

```python
def test_parse_filename_flags_draft():
    from app.services.customer_naming import parse_filename
    assert parse_filename("206_886_197_DRAFT_MOD_004.CATPart", None).draft is True
    assert parse_filename("206_883_607____KPR_TM__005_____B-RELEASE___20260528.CATPart", None).draft is False
```

- [ ] **Step 2:** Run `uv run pytest tests/test_data_route_api.py tests/test_customer_data_index.py -q`. Expected: FAIL (404s and AttributeError on `draft`).

- [ ] **Step 3: Implement**

`customer_naming.py`: add `draft: bool = False` to `ParsedName`. Add `_DRAFT = re.compile(r"DRAFT([-_]MOD)?", re.I)` next to `_VW_RELEASE`. In `parse_filename`, right after `out` is created (before any convention-specific return), add `out.draft = bool(_DRAFT.search(filename))`.

`data_route_service.py`, append to the class (with imports `from datetime import date`, `from typing import Optional`, `from app.models.part import Part, DIRECTIONS`, `from app.services.part_service import RevisionService`, `from app.services.revision_file_service import store_revision_file`, `from fastapi import HTTPException`, not used here; raise `ValueError` instead):

```python
    LOCKED = {"frozen", "cancelled", "archived"}

    @staticmethod
    async def _store(session, rev, files, user_id):
        return [await store_revision_file(session, rev, name, data, user_id, content_type=ctype)
                for name, data, ctype in files]

    @staticmethod
    async def default_statement(session, part_id: int) -> str:
        majors = await RevisionService._majors(session, part_id)
        return "official" if any(m.phase == "official" for m in majors) else "review"

    @staticmethod
    async def from_customer(session, part_id: int, *, official: bool, customer_index: str,
                            target_revision_id: Optional[int], parent_revision_id: Optional[int],
                            received_at: date, note: str, statement: Optional[str],
                            files: list, user_id: int):
        if not files:
            raise ValueError("Add at least one file")
        part = await session.get(Part, part_id)
        if part is None:
            raise ValueError("Part not found")
        majors = await RevisionService._majors(session, part_id)
        target = None
        if target_revision_id is not None:
            target = next((m for m in majors if m.id == target_revision_id), None)
            if target is None:
                raise ValueError("Target must be a customer version of this part")
        elif official and customer_index.strip():
            idx = customer_index.strip().lower()
            target = next((m for m in majors if (m.customer_index or "").lower() == idx
                           and m.status not in ("rejected", "cancelled")), None)
        if target is not None:
            if target.status in DataRouteService.LOCKED:
                raise ValueError(f"{target.revision_name} is {target.status}; files are read-only")
            return target, "added", await DataRouteService._store(session, target, files, user_id)
        if official:
            rev = await RevisionService.receive_customer_data(
                session, part_id, statement or await DataRouteService.default_statement(session, part_id),
                received_at, customer_index=customer_index.strip() or None, summary=note.strip() or None,
                created_by=user_id, intake_source="customer_data")
            return rev, "new_major", await DataRouteService._store(session, rev, files, user_id)
        parent_id = parent_revision_id or part.active_revision_id
        if parent_id is None:
            raise ValueError("No customer version to hang the feasibility data on; file official data first")
        rev = await RevisionService.create_proposal(
            session, part_id, parent_id, summary=note.strip() or "Feasibility data from Brose",
            created_by=user_id, direction="from_customer")
        rev.customer_received_at = received_at
        rev.source = "customer"
        return rev, "iteration", await DataRouteService._store(session, rev, files, user_id)

    @staticmethod
    async def create_iteration(session, part_id: int, *, parent_revision_id: int, direction: str,
                               summary: str, files: list, user_id: int) -> PartRevision:
        if direction not in ("to_customer", "internal"):
            raise ValueError("direction must be to_customer or internal")
        if not summary.strip():
            raise ValueError("A reason is required")
        if not files:
            raise ValueError("Add at least one file")
        rev = await RevisionService.create_proposal(
            session, part_id, parent_revision_id, summary=summary.strip(), created_by=user_id, direction=direction)
        await DataRouteService._store(session, rev, files, user_id)
        return rev
```

`receive_customer_data` with `intake_source` may raise `IntakeError` (supersede refused). Let it propagate; the endpoint maps it to 409.

Create `backend/app/api/v1/items/data_route.py`:

```python
"""Data route endpoints (spec 2026-10-19): Data from Brose, Data to Brose,
Confirm, Close. Each creates the version and its files in one transaction."""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.schemas.part import PartRevisionResponse
from app.services.data_route_service import DataRouteService
from app.services.part_data_mail import discard_new, pending_ids
from app.services.revision_file_service import MAX_FILE_SIZE, UnsupportedFile
from app.services.revision_intake_service import IntakeError
from app.services.revision_naming import RevisionRuleViolation

router = APIRouter(prefix="/parts", tags=["data-route"])
HTTP_422 = status.HTTP_422_UNPROCESSABLE_ENTITY


async def _read(files: List[UploadFile]) -> list[tuple[str, bytes, Optional[str]]]:
    out = []
    for f in files or []:
        data = await f.read()
        if len(data) > MAX_FILE_SIZE:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{f.filename} is over 100 MB")
        out.append((f.filename, data, f.content_type))
    return out


async def _run(db: AsyncSession, work, revision_of, mail: bool):
    """Run work(), honour 'don't mail', commit; map domain errors to HTTP."""
    try:
        result = await work()
        rev = revision_of(result)
        if not mail:
            await discard_new(db, rev.id, _run.before)
        await db.commit()
        await db.refresh(rev)
        return result
    except (ValueError, UnsupportedFile) as e:
        await db.rollback()
        raise HTTPException(HTTP_422, str(e))
    except (IntakeError, RevisionRuleViolation) as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
```

`_run.before` above is a sketch; don't ship a function attribute. Implement instead as follows. Before calling work, there is no revision id yet for new revisions, and pending rows of a brand-new revision are all new. So for new revisions use `before=set()`. For `added` (an existing target), take `before = await pending_ids(db, target.id)` **before** storing. To keep it simple, give `DataRouteService.from_customer` / `create_iteration` a keyword `mail: bool = True` and call `discard_new` inside the service right after storing files:
- for a new revision: `before = set()`
- for the `added` route: `before = await pending_ids(session, target.id)`, taken before `_store`

The endpoint then only commits. Update the service code above accordingly. Patch the test `test_dont_mail_flag_reaches_service` to monkeypatch `app.services.data_route_service.discard_new` (import it into that module with `from app.services.part_data_mail import discard_new, pending_ids`).

Final endpoint code:

```python
def _errors(e: Exception) -> HTTPException:
    if isinstance(e, (IntakeError, RevisionRuleViolation)):
        return HTTPException(status.HTTP_409_CONFLICT, str(e))
    return HTTPException(HTTP_422, str(e))


@router.post("/{part_id}/revisions/from-customer", status_code=status.HTTP_201_CREATED)
async def data_from_customer(
    part_id: int,
    official: bool = Form(...),
    received_at: date = Form(...),
    customer_index: str = Form(""),
    target_revision_id: Optional[int] = Form(None),
    parent_revision_id: Optional[int] = Form(None),
    note: str = Form(""),
    statement: Optional[str] = Form(None),
    mail: bool = Form(True),
    files: List[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    blobs = await _read(files)
    try:
        rev, route, stored = await DataRouteService.from_customer(
            db, part_id, official=official, customer_index=customer_index,
            target_revision_id=target_revision_id, parent_revision_id=parent_revision_id,
            received_at=received_at, note=note, statement=statement, files=blobs,
            user_id=current_user.id, mail=mail)
        await db.commit()
    except (ValueError, UnsupportedFile, IntakeError, RevisionRuleViolation) as e:
        await db.rollback()
        raise _errors(e)
    await db.refresh(rev)
    return {"revision": PartRevisionResponse.model_validate(rev).model_dump(mode="json"),
            "route": route, "files": [f.id for f in stored]}


@router.post("/{part_id}/revisions/iterations", response_model=PartRevisionResponse,
             status_code=status.HTTP_201_CREATED)
async def data_to_customer(
    part_id: int,
    parent_revision_id: int = Form(...),
    direction: str = Form(...),
    summary: str = Form(...),
    mail: bool = Form(True),
    files: List[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    blobs = await _read(files)
    try:
        rev = await DataRouteService.create_iteration(
            db, part_id, parent_revision_id=parent_revision_id, direction=direction,
            summary=summary, files=blobs, user_id=current_user.id, mail=mail)
        await db.commit()
    except (ValueError, UnsupportedFile, IntakeError, RevisionRuleViolation) as e:
        await db.rollback()
        raise _errors(e)
    await db.refresh(rev)
    return rev
```

Delete the `_run` sketch; only `_read`, `_errors` and the endpoints ship.

Storing files writes to disk before commit. On rollback those files leak, but that is harmless: the same behaviour as `store_revision_file` failures elsewhere. `customer_package_service.confirm` (lines 231-236) shows the cleanup pattern. Copy it: collect `f.file_path` / `f.viewer_file_path` of the stored rows and call `remove_files(...)` from `revision_file_service` in the except branch. Expose the stored list from the service by catching inside the service:

```python
        try:
            stored = await DataRouteService._store(session, rev, files, user_id)
        except Exception:
            raise
```

Keep it simple: wrap `_store` itself:

```python
    @staticmethod
    async def _store(session, rev, files, user_id):
        stored = []
        try:
            for name, data, ctype in files:
                stored.append(await store_revision_file(session, rev, name, data, user_id, content_type=ctype))
        except Exception:
            remove_files([p for f in stored for p in (f.file_path, f.viewer_file_path) if p])
            raise
        return stored
```

(`remove_files` lives in `revision_file_service.py`; the code map shows it used at line 75/140. Import it.)

Register the router: in the file that includes `customer_package.router`, add `from app.api.v1.items import data_route` and the same `include_router(data_route.router, ...)` call with the same prefix arguments.

- [ ] **Step 4:** Run `uv run pytest tests/test_data_route_api.py tests/test_customer_data_index.py tests/test_data_route_service.py -q`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/items/data_route.py backend/app/services/data_route_service.py backend/app/services/customer_naming.py backend/tests/test_data_route_api.py backend/tests/test_customer_data_index.py backend/app/api/v1/__init__.py backend/app/main.py
git commit -m "feat(data-route): Data from Brose / Data to Brose endpoints"
```

---

### Task 5: Confirm and Close endpoints

**Files:**
- Modify: `backend/app/services/data_route_service.py`
- Modify: `backend/app/api/v1/items/data_route.py`
- Modify: `backend/app/schemas/part.py` (two request models)
- Test: `backend/tests/test_data_route_api.py`

**Interfaces:**
- Produces:
  - `ConfirmIterationRequest {customer_index: str (1..20), received_at: date}`
  - `CloseRevisionRequest {reason: str}`
  - `POST /api/v1/parts/{part_id}/revisions/{revision_id}/confirm` → 201 `PartRevisionResponse` of the **new major**, pending triage, with the x.x files carried over
  - `POST /api/v1/parts/{part_id}/revisions/{revision_id}/close` → 200 `PartRevisionResponse` (status `rejected`, `close_reason` set)
  - `DataRouteService.confirm(session, part_id, revision_id, *, customer_index, received_at, user_id) -> PartRevision`
  - `DataRouteService.close(session, part_id, revision_id, *, reason, user_id) -> PartRevision`

- [ ] **Step 1: Write failing tests** (append to `test_data_route_api.py`)

```python
async def _iteration(client, eng_auth, part, direction="to_customer"):
    r = await client.post(f"{API}/{part['part_id']}/revisions/iterations", headers=eng_auth,
                          data={"parent_revision_id": str(part["revision_id"]), "direction": direction,
                                "summary": "FZ per DFM"}, files=_files("fz.txt"))
    assert r.status_code == 201, r.text
    return r.json()


async def test_confirm_makes_pending_major_with_carried_files(client, eng_auth, part):
    it = await _iteration(client, eng_auth, part)
    sib = await _iteration(client, eng_auth, part, direction="internal")
    r = await client.post(f"{API}/{part['part_id']}/revisions/{it['id']}/confirm", headers=eng_auth,
                          json={"customer_index": "004", "received_at": "2026-10-25"})
    assert r.status_code == 201, r.text
    major = r.json()
    assert major["revision_name"] == "E2" and major["customer_index"] == "004" and major["status"] == "in_review"
    files = (await client.get(f"{API}/revisions/{major['id']}/files", headers=eng_auth)).json()
    assert [f["filename"] for f in files] == ["fz.txt"]
    revs = {x["id"]: x for x in (await client.get(f"{API}/{part['part_id']}/revisions", headers=eng_auth)).json()}
    assert revs[sib["id"]]["status"] == "draft"


async def test_confirm_only_iterations(client, eng_auth, part):
    r = await client.post(f"{API}/{part['part_id']}/revisions/{part['revision_id']}/confirm", headers=eng_auth,
                          json={"customer_index": "004", "received_at": "2026-10-25"})
    assert r.status_code == 422


async def test_confirm_while_intake_pending_is_409(client, eng_auth, part):
    it = await _iteration(client, eng_auth, part)
    await client.post(f"{API}/{part['part_id']}/revisions/from-customer", headers=eng_auth,
                      data={"official": "true", "customer_index": "005", "received_at": "2026-10-15"},
                      files=_files("x.txt"))
    # a second pending major supersedes or is refused per supersedable(); with a linked
    # change it is refused. Without one it supersedes, so assert the documented outcome:
    r = await client.post(f"{API}/{part['part_id']}/revisions/{it['id']}/confirm", headers=eng_auth,
                          json={"customer_index": "006", "received_at": "2026-10-25"})
    assert r.status_code in (201, 409), r.text
    if r.status_code == 409:
        assert r.json()["detail"]
```

The third test pins only "no 500". Before writing it, read `RevisionIntakeService.supersedable` (revision_intake_service.py:263). If it supersedes silently when no change is linked, the spec's "say so and offer add to pending" applies at the **dialog** level (Task 7 shows the hint). Keep the backend behaviour and assert exactly the outcome `supersedable` gives (201 + the earlier intake superseded). Replace the `in (201, 409)` with that exact expectation.

```python
@pytest.mark.parametrize("reason", ["", "   "])
async def test_close_needs_reason(client, eng_auth, part, reason):
    it = await _iteration(client, eng_auth, part)
    r = await client.post(f"{API}/{part['part_id']}/revisions/{it['id']}/close", headers=eng_auth,
                          json={"reason": reason})
    assert r.status_code == 422


async def test_close_and_reopen(client, eng_auth, part):
    it = await _iteration(client, eng_auth, part)
    r = await client.post(f"{API}/{part['part_id']}/revisions/{it['id']}/close", headers=eng_auth,
                          json={"reason": "Brose rejected 21.10."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected" and r.json()["close_reason"] == "Brose rejected 21.10."
    r = await client.post(f"{API}/{part['part_id']}/revisions/{it['id']}/unreject", headers=eng_auth, json={})
    assert r.status_code == 200 and r.json()["close_reason"] is None
```

`reject`/`unreject` are guarded by `_may_reject_revision` (triage rights). Check whether `eng_auth` passes that guard in `tests/test_revision_intake.py`. If not, use `admin_auth` in `test_close_and_reopen`. Close uses the **same guard** (see Step 3).

- [ ] **Step 2:** Run `uv run pytest tests/test_data_route_api.py -k "confirm or close" -q`. Expected: FAIL (404).

- [ ] **Step 3: Implement**

`schemas/part.py`:

```python
class ConfirmIterationRequest(BaseModel):
    customer_index: str = Field(..., min_length=1, max_length=20)
    received_at: date


class CloseRevisionRequest(BaseModel):
    reason: str
```

Service (append):

```python
    @staticmethod
    async def confirm(session, part_id: int, revision_id: int, *, customer_index: str,
                      received_at: date, user_id: int) -> PartRevision:
        it = await session.get(PartRevision, revision_id)
        if it is None or it.part_id != part_id:
            raise ValueError("Revision not found on this part")
        if it.parent_revision_id is None:
            raise ValueError("Only an iteration (E x.x) can be confirmed")
        if it.status in ("rejected", "cancelled", "approved"):
            raise ValueError(f"{it.revision_name} is {it.status}")
        major = await RevisionService.promote_revision(
            session, it.id, await DataRouteService.default_statement(session, part_id), received_at,
            customer_index=customer_index.strip(), created_by=user_id, intake_source="promote")
        await DataRouteService.copy_files(session, it, major, user_id)
        return major

    @staticmethod
    async def close(session, part_id: int, revision_id: int, *, reason: str, user_id: int) -> PartRevision:
        if not reason.strip():
            raise ValueError("A reason is required")
        rev = await session.get(PartRevision, revision_id)
        if rev is None or rev.part_id != part_id:
            raise ValueError("Revision not found on this part")
        rev.close_reason = reason.strip()
        return await RevisionService.reject_revision(session, revision_id, created_by=user_id)
```

Endpoints: Close reuses the triage guard. Import `_may_reject_revision` from `app.api.v1.items.parts` and call it exactly as `reject` does at parts.py:407-433. Read those lines and mirror the call signature.

```python
@router.post("/{part_id}/revisions/{revision_id}/confirm", response_model=PartRevisionResponse,
             status_code=status.HTTP_201_CREATED)
async def confirm_iteration(part_id: int, revision_id: int, body: ConfirmIterationRequest,
                            current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    try:
        major = await DataRouteService.confirm(db, part_id, revision_id, customer_index=body.customer_index,
                                               received_at=body.received_at, user_id=current_user.id)
        await db.commit()
    except (ValueError, IntakeError, RevisionRuleViolation) as e:
        await db.rollback()
        raise _errors(e)
    await db.refresh(major)
    return major


@router.post("/{part_id}/revisions/{revision_id}/close", response_model=PartRevisionResponse)
async def close_revision(part_id: int, revision_id: int, body: CloseRevisionRequest,
                         current_user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    await _may_reject_revision(db, part_id, revision_id, current_user)  # same guard as /reject
    try:
        rev = await DataRouteService.close(db, part_id, revision_id, reason=body.reason, user_id=current_user.id)
        await db.commit()
    except (ValueError, IntakeError) as e:
        await db.rollback()
        raise _errors(e)
    await db.refresh(rev)
    return rev
```

- [ ] **Step 4:** Run `uv run pytest tests/test_data_route_api.py tests/test_data_route_service.py tests/test_revision_intake.py -q`. Expected: PASS. Then run the full backend suite: `uv run pytest -q -x`. Expected: PASS. A known bcrypt `__about__` warning is printed and is not a failure.

- [ ] **Step 5: Commit:** `git commit -am "feat(data-route): Confirm (carries files, pending triage) and Close (reason required)"`

---

### Task 6: Frontend API + direction-aware tree states

**Files:**
- Create: `frontend/src/api/dataRoute.ts`
- Modify: `frontend/src/components/parts/versionTree.ts` (`TreeRevision`, `versionState`)
- Test: `frontend/src/components/parts/versionTree.test.ts`, `frontend/src/api/dataRoute.test.ts`

**Interfaces:**
- Produces:
  - `dataRoute.fromBrose(partId, input: FromBroseInput): Promise<FromBroseResult>`
  - `dataRoute.toBrose(partId, input: ToBroseInput): Promise<PartRevision>`
  - `dataRoute.confirm(partId, revisionId, {customer_index, received_at})`
  - `dataRoute.close(partId, revisionId, reason)`
  - `dataRoute.reopen(partId, revisionId)`
  - `TreeRevision` gains `direction?` and `close_reason?`
  - `versionState` labels (minors):
    - `from_customer` → `awaiting confirmation` (tone `waiting`)
    - `to_customer` → `awaiting Brose` (`open`)
    - `internal` → `internal check` (`neutral`)
    - null → `open iteration` (`open`)
    - approved → `confirmed` (`done`)
    - rejected with `close_reason` → `closed: <reason>` (`dead`)

- [ ] **Step 1: Failing tests**

Add to `versionTree.test.ts` inside `describe('versionState')`:

```ts
  it('names iterations by direction and outcome', () => {
    const it = (extra: Record<string, unknown>) => rev(3, 'E1.1', { parent_revision_id: 1, status: 'draft', ...extra });
    expect(versionState(it({ direction: 'from_customer' }), opts)).toMatchObject({ label: 'awaiting confirmation', tone: 'waiting' });
    expect(versionState(it({ direction: 'to_customer' }), opts)).toMatchObject({ label: 'awaiting Brose', tone: 'open' });
    expect(versionState(it({ direction: 'internal' }), opts)).toMatchObject({ label: 'internal check', tone: 'neutral' });
    expect(versionState(it({ status: 'approved' }), opts)).toMatchObject({ label: 'confirmed', tone: 'done' });
    expect(versionState(it({ status: 'rejected', close_reason: 'Brose rejected' }), opts))
      .toMatchObject({ label: 'closed: Brose rejected', tone: 'dead' });
  });
```

Update the existing expectation `'adopted by customer'` to `'confirmed'`. Also update `VersionNav.test.tsx` if it asserts `open iteration` for a revision without direction; it stays `open iteration`, so no change is needed.

Create `frontend/src/api/dataRoute.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('./client', () => ({ default: clientMocks, API_BASE_URL: '' }));
import { dataRoute } from './dataRoute';

describe('dataRoute', () => {
  beforeEach(() => clientMocks.post.mockReset().mockResolvedValue({ data: {} }));

  it('posts Brose data as multipart with the routing fields', async () => {
    const f = new File(['x'], 'a_005.CATPart');
    await dataRoute.fromBrose(7, { official: true, customer_index: '005', received_at: '2026-10-15', note: 'GlobalX', mail: false, files: [f] });
    const [url, body] = clientMocks.post.mock.calls[0];
    expect(url).toBe('/v1/parts/7/revisions/from-customer');
    const fd = body as FormData;
    expect(fd.get('official')).toBe('true');
    expect(fd.get('customer_index')).toBe('005');
    expect(fd.get('mail')).toBe('false');
    expect(fd.getAll('files')).toHaveLength(1);
  });

  it('closes with a reason', async () => {
    await dataRoute.close(7, 9, 'Brose rejected');
    expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/revisions/9/close', { reason: 'Brose rejected' });
  });
});
```

- [ ] **Step 2:** Run `cd frontend && npx vitest run src/components/parts/versionTree.test.ts src/api/dataRoute.test.ts`. Expected: FAIL.

- [ ] **Step 3: Implement**

`frontend/src/api/dataRoute.ts`:

```ts
/** Data route (spec 2026-10-19): Data from Brose, Data to Brose, Confirm, Close. */
import client from './client';
import type { PartRevision } from '../components/project/projectTypes';

export interface FromBroseInput {
  official: boolean;
  customer_index?: string;
  received_at: string;
  note?: string;
  target_revision_id?: number;
  parent_revision_id?: number;
  mail: boolean;
  files: File[];
}
export interface FromBroseResult { revision: PartRevision; route: 'new_major' | 'added' | 'iteration'; files: number[] }
export interface ToBroseInput {
  parent_revision_id: number;
  direction: 'to_customer' | 'internal';
  summary: string;
  mail: boolean;
  files: File[];
}

function form(fields: Record<string, string | number | boolean | undefined>, files: File[]): FormData {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) if (v !== undefined && v !== '') fd.append(k, String(v));
  for (const f of files) fd.append('files', f);
  return fd;
}

export const dataRoute = {
  async fromBrose(partId: number, i: FromBroseInput): Promise<FromBroseResult> {
    const { files, ...fields } = i;
    return (await client.post(`/v1/parts/${partId}/revisions/from-customer`, form(fields, files))).data;
  },
  async toBrose(partId: number, i: ToBroseInput): Promise<PartRevision> {
    const { files, ...fields } = i;
    return (await client.post(`/v1/parts/${partId}/revisions/iterations`, form(fields, files))).data;
  },
  async confirm(partId: number, revisionId: number, body: { customer_index: string; received_at: string }): Promise<PartRevision> {
    return (await client.post(`/v1/parts/${partId}/revisions/${revisionId}/confirm`, body)).data;
  },
  async close(partId: number, revisionId: number, reason: string): Promise<PartRevision> {
    return (await client.post(`/v1/parts/${partId}/revisions/${revisionId}/close`, { reason })).data;
  },
  async reopen(partId: number, revisionId: number): Promise<PartRevision> {
    return (await client.post(`/v1/parts/${partId}/revisions/${revisionId}/unreject`, {})).data;
  },
};
```

`versionTree.ts`: add to `TreeRevision`:

```ts
  direction?: 'from_customer' | 'to_customer' | 'internal' | null;
  close_reason?: string | null;
```

Widen `versionState`'s first parameter to `Pick<TreeRevision, 'id' | 'status' | 'parent_revision_id' | 'direction' | 'close_reason'>` and replace its body's start and minor branch:

```ts
  const minor = rev.parent_revision_id != null;
  if (rev.status === 'rejected' || rev.status === 'cancelled') {
    return { label: rev.close_reason ? `closed: ${rev.close_reason}` : rev.status === 'rejected' ? 'rejected' : 'closed', tone: 'dead' };
  }
  const pending = opts.pending?.get(rev.id);
  if (pending) return { label: pending, tone: 'waiting' };
  if (minor) {
    if (rev.status === 'approved') return { label: 'confirmed', tone: 'done' };
    if (rev.status === 'archived') return { label: 'superseded', tone: 'dead' };
    if (rev.direction === 'from_customer') return { label: 'awaiting confirmation', tone: 'waiting' };
    if (rev.direction === 'to_customer') return { label: 'awaiting Brose', tone: 'open' };
    if (rev.direction === 'internal') return { label: 'internal check', tone: 'neutral' };
    return { label: 'open iteration', tone: 'open' };
  }
```

(The major branch below stays as is.)

- [ ] **Step 4:** Run `npx vitest run src/components/parts src/api/dataRoute.test.ts && npx tsc --noEmit -p .`. Expected: PASS.
- [ ] **Step 5: Commit:** `git commit -am "feat(data-route): frontend API and direction-aware version states"` (also `git add` the two new files).

---

### Task 7: Data from Brose dialog

**Files:**
- Create: `frontend/src/components/parts/DataFromBroseDialog.tsx`
- Test: `frontend/src/components/parts/DataFromBroseDialog.test.tsx`

**Interfaces:**
- Consumes:
  - `dataRoute.fromBrose`
  - `GET /v1/parts/${partId}/files/parse?filenames=…` (existing; returns `{convention, rows: ParsedRow[]}` where a row has `customer_index`, `release`, `draft`, `dated`). Check the exact query-param format in `UploadDialog.tsx:75-85` and copy it.
- Produces:
  - `export default function DataFromBroseDialog(props: { partId: number; revisions: PartRevision[]; activeId: number | null; initialFiles?: File[]; onClose(): void; onDone(r: FromBroseResult): void })`
  - `export function guessOfficial(rows: { release?: string | null; draft?: boolean }[]): boolean | null`: `true` if any row has a release and none is a draft, `false` if any is a draft, else `null`.

Dialog behaviour (one screen):
1. A drop zone (plus a click-to-pick input) holds the file list.
2. On a file change, call parse. Fill the index from the first parsed `customer_index` and the date from the first `dated` (default today).
3. **Official?** A radio with two options: "Official / confirmed by Brose" and "Feasibility / draft: needs confirmation". Preselect from `guessOfficial`. With `null`, nothing is preselected and submit is disabled until the user picks one. Show the reason under the radio: "Guessed from file name: B-RELEASE" or "DRAFT_MOD".
4. If official, show the index input. A live outcome line reads either:
   - "Adds files to E2 · 005", when the index matches an existing non-rejected major (case-insensitive), or
   - "Creates E3 · 006, waiting for triage" otherwise. Compute the next name from the majors as `E{max+1}`, or `{max+1}` when an official major exists.

   If another major already has `intake_pending`, add the amber hint: "E2 · 005 is still waiting for triage. Filing a new index replaces it in triage. To add files to it instead, set index 005."
5. If feasibility, show a "Based on" select (majors, default `activeId`). The outcome line reads "Creates E1.2 ⬇ under E1 · 003, awaiting confirmation".
6. Received date, plus a note (placeholder "e.g. GlobalX 15.10. 16:46, Philip Paluch").
7. A checkbox "Mail the project list", checked by default.
8. Submit is labelled by the outcome ("Add files", "Create E3 · 006", "Create E1.2"). While submitting it is disabled. An error shows `apiErrorMessage(err)` inline.

- [ ] **Step 1: Failing tests**

```tsx
// frontend/src/components/parts/DataFromBroseDialog.test.tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }));
import DataFromBroseDialog, { guessOfficial } from './DataFromBroseDialog';

const revisions = [
  { id: 1, part_id: 7, revision_name: 'E1', customer_index: '003', phase: 'review' as const, status: 'approved', created_at: '2026-09-02' },
  { id: 2, part_id: 7, revision_name: 'E2', customer_index: '005', phase: 'review' as const, status: 'in_review', created_at: '2026-10-19', intake_pending: true },
];
function mount(parsed: Record<string, unknown>) {
  clientMocks.get.mockResolvedValue({ data: { convention: 'scout', rows: [{ customer_index: '005', release: null, draft: false, dated: '2026-10-15', ...parsed }] } });
  clientMocks.post.mockResolvedValue({ data: { revision: revisions[1], route: 'added', files: [1] } });
  const onDone = vi.fn();
  render(<QueryClientProvider client={new QueryClient()}>
    <DataFromBroseDialog partId={7} revisions={revisions} activeId={1} onClose={vi.fn()} onDone={onDone}
      initialFiles={[new File(['x'], '206_883_607_DRW_005.pdf')]} />
  </QueryClientProvider>);
  return onDone;
}

describe('guessOfficial', () => {
  it('reads B-RELEASE as official and DRAFT as feasibility, else unknown', () => {
    expect(guessOfficial([{ release: 'B-RELEASE' }])).toBe(true);
    expect(guessOfficial([{ release: 'B-RELEASE' }, { draft: true }])).toBe(false);
    expect(guessOfficial([{}])).toBeNull();
  });
});

describe('DataFromBroseDialog', () => {
  beforeEach(() => { clientMocks.get.mockReset(); clientMocks.post.mockReset(); });
  afterEach(cleanup);

  it('adds files to the existing folder when the index matches', async () => {
    const onDone = mount({ release: 'B-RELEASE' });
    expect(await screen.findByText('Adds files to E2 · 005')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Add files' }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    const fd = clientMocks.post.mock.calls[0][1] as FormData;
    expect(fd.get('official')).toBe('true');
    expect(fd.get('customer_index')).toBe('005');
  });

  it('makes feasibility data an iteration under the base version', async () => {
    mount({ draft: true, customer_index: null });
    expect(await screen.findByText(/Creates E1\.1 .*under E1 · 003, awaiting confirmation/)).toBeTruthy();
  });

  it('waits for the user to choose when the name does not tell', async () => {
    mount({});
    const submit = await screen.findByRole('button', { name: /Create|Add/ });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
  });

  it('warns that a new index replaces the one waiting for triage', async () => {
    mount({ release: 'B-RELEASE', customer_index: '006' });
    expect(await screen.findByText(/still waiting for triage/)).toBeTruthy();
  });
});
```

- [ ] **Step 2:** Run `npx vitest run src/components/parts/DataFromBroseDialog.test.tsx`. Expected: FAIL (module missing).

- [ ] **Step 3: Implement** `DataFromBroseDialog.tsx`. Match the modal markup of `CustomerDataDialog.tsx`: same overlay, panel classes, focus handling and Escape-to-close. Read that file first and reuse its wrapper verbatim. Structure:

```tsx
/** ⬇ Data from Brose: one dialog for every file Brose sends. Official data
 *  becomes or extends a folder (E2 · 005), feasibility data an E x.x ⬇. */
import { useEffect, useMemo, useState } from 'react';
import client from '../../api/client';
import { dataRoute, type FromBroseResult } from '../../api/dataRoute';
import { apiErrorMessage } from '../../lib/apiError';
import { revisionLabel } from './RevisionBadge';
import type { PartRevision } from '../project/projectTypes';

interface Parsed { customer_index?: string | null; release?: string | null; draft?: boolean; dated?: string | null }

export function guessOfficial(rows: Parsed[]): boolean | null {
  if (rows.some((r) => r.draft)) return false;
  if (rows.some((r) => r.release)) return true;
  return null;
}

const today = () => new Date().toISOString().slice(0, 10);
const LIVE = (r: PartRevision) => r.status !== 'rejected' && r.status !== 'cancelled';

export default function DataFromBroseDialog({ partId, revisions, activeId, initialFiles = [], onClose, onDone }: {
  partId: number; revisions: PartRevision[]; activeId: number | null; initialFiles?: File[];
  onClose(): void; onDone(r: FromBroseResult): void;
}) {
  const [files, setFiles] = useState<File[]>(initialFiles);
  const [parsed, setParsed] = useState<Parsed[]>([]);
  const [official, setOfficial] = useState<boolean | null>(null);
  const [index, setIndex] = useState('');
  const [receivedAt, setReceivedAt] = useState(today());
  const [note, setNote] = useState('');
  const [baseId, setBaseId] = useState<number | null>(activeId);
  const [mail, setMail] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!files.length) return;
    let live = true;
    // same request shape as UploadDialog.tsx:75-85
    client.get(`/v1/parts/${partId}/files/parse`, { params: { filenames: files.map((f) => f.name) } })
      .then((res) => {
        if (!live) return;
        const rows: Parsed[] = res.data.rows ?? [];
        setParsed(rows);
        setOfficial(guessOfficial(rows));
        const idx = rows.find((r) => r.customer_index)?.customer_index;
        if (idx) setIndex(idx);
        const d = rows.find((r) => r.dated)?.dated;
        if (d) setReceivedAt(d.slice(0, 10));
      })
      .catch(() => { /* parsing only prefills */ });
    return () => { live = false; };
  }, [files, partId]);

  const majors = useMemo(() => revisions.filter((r) => !r.parent_revision_id), [revisions]);
  const minorsOf = (id: number) => revisions.filter((r) => r.parent_revision_id === id);
  const match = official && index.trim()
    ? majors.find((m) => LIVE(m) && (m.customer_index ?? '').toLowerCase() === index.trim().toLowerCase())
    : undefined;
  const waiting = majors.find((m) => m.intake_pending && m.id !== match?.id);
  const hasOfficial = majors.some((m) => m.phase === 'official');
  const nextMajor = (() => {
    const nums = majors.filter((m) => (m.revision_name.startsWith('E')) !== hasOfficial)
      .map((m) => parseInt(m.revision_name.replace(/^E/, ''), 10)).filter(Number.isFinite);
    const n = Math.max(0, ...nums) + 1;
    return hasOfficial ? String(n) : `E${n}`;
  })();
  const base = majors.find((m) => m.id === baseId);
  const nextMinor = base ? `${base.revision_name}.${minorsOf(base.id).length + 1}` : '';

  let outcome = '';
  let action = '';
  if (official === true) {
    if (match) { outcome = `Adds files to ${revisionLabel(match.revision_name, match.customer_index)}`; action = 'Add files'; }
    else { const n = revisionLabel(nextMajor, index.trim() || null); outcome = `Creates ${n}, waiting for triage`; action = `Create ${n}`; }
  } else if (official === false && base) {
    outcome = `Creates ${nextMinor} ⬇ under ${revisionLabel(base.revision_name, base.customer_index)}, awaiting confirmation`;
    action = `Create ${nextMinor}`;
  }
  const canSubmit = files.length > 0 && official !== null && !busy && (official ? !!index.trim() || !!match : !!base);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const r = await dataRoute.fromBrose(partId, {
        official: official!, customer_index: index.trim(), received_at: receivedAt, note,
        target_revision_id: match?.id, parent_revision_id: official ? undefined : baseId ?? undefined,
        mail, files,
      });
      onDone(r);
    } catch (e) { setError(apiErrorMessage(e, 'Could not file the data')); }
    finally { setBusy(false); }
  };

  return (/* modal wrapper copied from CustomerDataDialog, title "Data from Brose", containing:
    drop zone + file list,
    fieldset "Is this official / confirmed by Brose?" with the two radios + guess reason
      (`parsed.some(r=>r.draft) ? 'Guessed from file name: draft' : parsed.some(r=>r.release) ? `Guessed from file name: ${parsed.find(r=>r.release)!.release}` : ''`),
    official ? index input : base select (majors.filter(LIVE)),
    {waiting && official && !match && <p className="text-amber-300 text-xs">{revisionLabel(waiting.revision_name, waiting.customer_index)} is still waiting for triage. Filing a new index replaces it in triage. To add files to it instead, set index {waiting.customer_index}.</p>},
    received date input, note input, mail checkbox "Mail the project list",
    <p data-testid="from-brose-outcome">{outcome}</p>, error line,
    footer: Cancel + <button disabled={!canSubmit} onClick={submit}>{action || 'Create'}</button> */
    null);
}
```

The `return` above lists every element and its exact copy. Write it as real JSX using the CustomerDataDialog wrapper; the comment is not code. The submit button's accessible name is its text (`action || 'Create'`). Tests rely on that. Each radio gets a `<label>`.

- [ ] **Step 4:** Run `npx vitest run src/components/parts/DataFromBroseDialog.test.tsx && npx tsc --noEmit -p . && npx eslint src/components/parts/DataFromBroseDialog.tsx --max-warnings 0`. Expected: PASS.
- [ ] **Step 5: Commit:** `git add` both files, then `git commit -m "feat(data-route): Data from Brose dialog"`

---

### Task 8: Data to Brose dialog and iteration actions (Confirm / Close / Reopen)

**Files:**
- Create: `frontend/src/components/parts/DataToBroseDialog.tsx`
- Create: `frontend/src/components/parts/IterationActions.tsx`
- Tests: `DataToBroseDialog.test.tsx`, `IterationActions.test.tsx` (same folder)

**Interfaces:**
- Consumes: `dataRoute.toBrose`, `dataRoute.confirm`, `dataRoute.close`, `dataRoute.reopen`.
- Produces:
  - `DataToBroseDialog(props: { partId: number; revisions: PartRevision[]; activeId: number | null; initialFiles?: File[]; onClose(): void; onDone(rev: PartRevision): void })`
  - `IterationActions(props: { partId: number; revision: { id: number; revision_name: string; status: string; parent_revision_id?: number | null }; onChanged(): void })`: a ⋯ button. Its menu offers:
    - "Confirm…" and "Close…" when the iteration is open (status not rejected, cancelled or approved)
    - "Reopen" when it is rejected

    Each opens a small inline dialog:
    - **Confirm:** index (required) and date (default today). Note under it: "Creates the next version from {name} with its files, waiting for triage."
    - **Close:** a reason textarea; the button is disabled while the reason is blank.

DataToBroseDialog content:
- Files (required) and a "Based on" select (live majors, default `activeId`).
- Radio "Sent to Brose" (default) / "Internal only, not sent".
- Reason textarea (required, placeholder "e.g. FZ per DFM: sharp steel at slide entry, sent via GlobalX 19.10. 08:12, requested by Dale").
- Mail checkbox, checked by default for sent and unchecked for internal (the user can override).
- Outcome line "Creates E1.2 ⬆ under E1 · 003, awaiting Brose" (or "● internal check").
- Submit button `Create E1.2`, disabled until there are files and a non-blank reason.

- [ ] **Step 1: Failing tests**

```tsx
// DataToBroseDialog.test.tsx
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }));
import DataToBroseDialog from './DataToBroseDialog';

const revisions = [{ id: 1, part_id: 7, revision_name: 'E1', customer_index: '003', phase: 'review' as const, status: 'approved', created_at: '2026-09-02' }];

describe('DataToBroseDialog', () => {
  afterEach(cleanup);
  it('needs files and a reason, then creates a to-Brose iteration', async () => {
    clientMocks.post.mockResolvedValue({ data: { id: 9, revision_name: 'E1.1' } });
    const onDone = vi.fn();
    render(<DataToBroseDialog partId={7} revisions={revisions} activeId={1} onClose={vi.fn()} onDone={onDone}
      initialFiles={[new File(['x'], 'fz.stp')]} />);
    const submit = screen.getByRole('button', { name: 'Create E1.1' }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: '   ' } });
    expect(submit.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'FZ per DFM' } });
    expect(screen.getByText('Creates E1.1 ⬆ under E1 · 003, awaiting Brose')).toBeTruthy();
    fireEvent.click(submit);
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    const fd = clientMocks.post.mock.calls[0][1] as FormData;
    expect(fd.get('direction')).toBe('to_customer');
    expect(fd.get('summary')).toBe('FZ per DFM');
  });

  it('defaults mail off for an internal check', () => {
    render(<DataToBroseDialog partId={7} revisions={revisions} activeId={1} onClose={vi.fn()} onDone={vi.fn()} />);
    fireEvent.click(screen.getByLabelText('Internal only, not sent'));
    expect((screen.getByLabelText('Mail the project list') as HTMLInputElement).checked).toBe(false);
  });
});
```

```tsx
// IterationActions.test.tsx
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }));
import IterationActions from './IterationActions';

const open = { id: 9, revision_name: 'E1.1', status: 'draft', parent_revision_id: 1 };

describe('IterationActions', () => {
  afterEach(cleanup);
  it('confirms with the customer index', async () => {
    clientMocks.post.mockResolvedValue({ data: {} });
    const onChanged = vi.fn();
    render(<IterationActions partId={7} revision={open} onChanged={onChanged} />);
    fireEvent.click(screen.getByLabelText('Actions for E1.1'));
    fireEvent.click(screen.getByText('Confirm…'));
    fireEvent.change(screen.getByLabelText('Brose index'), { target: { value: '004' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm E1.1' }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(clientMocks.post.mock.calls[0][0]).toBe('/v1/parts/7/revisions/9/confirm');
    expect(clientMocks.post.mock.calls[0][1]).toMatchObject({ customer_index: '004' });
  });

  it('will not close without a reason', () => {
    render(<IterationActions partId={7} revision={open} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByLabelText('Actions for E1.1'));
    fireEvent.click(screen.getByText('Close…'));
    expect((screen.getByRole('button', { name: 'Close E1.1' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('offers Reopen on a closed iteration', () => {
    render(<IterationActions partId={7} revision={{ ...open, status: 'rejected' }} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByLabelText('Actions for E1.1'));
    expect(screen.getByText('Reopen')).toBeTruthy();
    expect(screen.queryByText('Confirm…')).toBeNull();
  });
});
```

- [ ] **Step 2:** Run `npx vitest run src/components/parts/DataToBroseDialog.test.tsx src/components/parts/IterationActions.test.tsx`. Expected: FAIL.

- [ ] **Step 3: Implement** both components:
  - Use the same modal wrapper as Task 7.
  - Label every input with `<label htmlFor>` using the exact texts the tests use: "Reason", "Internal only, not sent", "Sent to Brose", "Mail the project list", "Brose index", "Date".
  - Use the lucide `Ellipsis` icon for the ⋯ button, with `aria-label={`Actions for ${revision.revision_name}`}`.
  - The menu is a small absolutely positioned list that closes on Escape or an outside click.
  - The Confirm and Close submit buttons read `Confirm ${name}` and `Close ${name}`.
  - Show errors with `apiErrorMessage`.
  - Mail default rule in DataToBroseDialog: whenever the direction radio changes, `setMail(direction === 'to_customer')`.

- [ ] **Step 4:** Run the two tests, then `npx tsc --noEmit -p . && npx eslint src/components/parts/DataToBroseDialog.tsx src/components/parts/IterationActions.tsx --max-warnings 0`. Expected: PASS.
- [ ] **Step 5: Commit:** `git add` the four files, then `git commit -m "feat(data-route): Data to Brose dialog and Confirm/Close/Reopen actions"`

---

### Task 9: Wire it in: VersionNav header and rows, DocumentsTab, UploadDialog hint, PartDetail read-only

**Files:**
- Modify: `frontend/src/components/parts/VersionNav.tsx`
- Modify: `frontend/src/components/project/DocumentsTab.tsx` (lines per the code map: 10-13 imports; 64-66 state; 90 `proposalMutation`; 177-183 package; 209-224 empty state; 232-241 VersionNav; 296-315 UploadDialog)
- Modify: `frontend/src/components/parts/UploadDialog.tsx` (major branch at 140-148 and 253-281)
- Modify: `frontend/src/pages/PartDetail.tsx` (102-105, 158-192, 340, 358-372, 431-443)
- Tests:
  - `VersionNav.test.tsx`
  - `src/pages/ProjectDetailPage.article.test.tsx`
  - `src/pages/ProjectDetailPage.files.test.tsx`
  - `UploadDialog.test.tsx`
  - `src/pages/PartDetail*.test.tsx`

**Interfaces:**
- VersionNav Props:
  - remove `onNewIteration`
  - add `onFromBrose(): void`, `onToBrose(): void`, `partId: number`, `onChanged(): void` (refetch after an action)
- UploadDialog Props: add `onNewCustomerData?(files: File[]): void`. Remove the `level === 'major'` path.

- [ ] **Step 1: Failing tests**

In `VersionNav.test.tsx`:
- Replace the `offers a new iteration…` test.
- Add `partId: 7, onFromBrose: vi.fn(), onToBrose: vi.fn(), onChanged: vi.fn()` to the `mount` defaults, and remove `onNewIteration`.

```tsx
  it('creates versions only through the two buttons', () => {
    const p = mount();
    fireEvent.click(screen.getByRole('button', { name: 'Data from Brose' }));
    fireEvent.click(screen.getByRole('button', { name: 'Data to Brose' }));
    expect(p.onFromBrose).toHaveBeenCalled();
    expect(p.onToBrose).toHaveBeenCalled();
    expect(screen.queryByTestId('nav-new-iteration-1')).toBeNull();
  });

  it('marks iteration direction and offers actions on iterations only', () => {
    mount({ revisions: revs.map((r) => (r.id === 3 ? { ...r, direction: 'to_customer' as const } : r)) });
    expect(screen.getByTestId('nav-state-3').textContent).toBe('awaiting Brose');
    expect(screen.getByLabelText('Actions for E1.1')).toBeTruthy();
    expect(screen.queryByLabelText('Actions for E1')).toBeNull();
  });
```

In `src/pages/ProjectDetailPage.article.test.tsx`:
- Replace the `+ New iteration on the selected major posts a proposal` test with one that clicks "Data to Brose" and expects the dialog title "Data to Brose" to appear.
- Remove the assertion on `+ Customer package` in `ProjectDetailPage.files.test.tsx`. Replace it with: click "Data from Brose" and expect the dialog title.

UploadDialog test (append to `UploadDialog.test.tsx`). Mock parse to return `customer_index: '006'` for a part whose current revision has index `005`:

```tsx
  it('sends files that look like a new Brose index to Data from Brose', async () => {
    // arrange per the file's existing mount helper; parse returns customer_index '006' while current is '005'
    const onNew = vi.fn();
    // mount(..., { onNewCustomerData: onNew })
    fireEvent.click(await screen.findByRole('button', { name: 'Open Data from Brose' }));
    expect(onNew).toHaveBeenCalledWith(expect.any(Array));
    expect(screen.queryByText(/Next customer data/)).toBeNull();
  });
```

Write the arrange part using that file's existing mount helper and parse mock (read the file first). No comment placeholders in the final test.

For PartDetail, add or adjust a test in `src/pages/PartDetail.test.tsx`: the part page shows no "+ Proposal", "Customer adopted" or "+ Customer data" buttons, and shows a link "Manage versions in the project's Documents tab" pointing to `/projects/${part.project_id}?part=${part.id}`.

- [ ] **Step 2:** Run `npx vitest run src/components/parts src/pages`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement**

**VersionNav:**
- In the expanded header, under the "Versions" row, add two full-width buttons in a `grid grid-cols-2 gap-1 px-2 pb-2`:

```tsx
<button type="button" onClick={onFromBrose} className="inline-flex items-center justify-center gap-1 rounded bg-blue-700 px-2 py-1 text-xs font-medium text-white hover:bg-blue-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400">
  <ArrowDownToLine aria-hidden className="h-3.5 w-3.5" />Data from Brose
</button>
<button type="button" onClick={onToBrose} className="inline-flex items-center justify-center gap-1 rounded border border-slate-600 px-2 py-1 text-xs font-medium text-slate-200 hover:bg-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400">
  <ArrowUpFromLine aria-hidden className="h-3.5 w-3.5" />Data to Brose
</button>
```

  The accessible name is the text: "Data from Brose" / "Data to Brose".
- Remove the `onNewIteration` prop and the `Plus` button.
- In `VersionRow`, the iteration icon becomes:
  - `ArrowDownToLine` (sky) for `from_customer`
  - `ArrowUpFromLine` (amber) for `to_customer`
  - `CircleDot` (slate) for `internal`
  - `GitBranch` for null

  The direction label goes in the icon's `title`.
- For minors, render `<IterationActions partId={partId} revision={node.rev} onChanged={onChanged} />` where the Plus button was.

**DocumentsTab:**
- Remove `proposalMutation`, the header "+ Customer package" button and its dialog, the empty-state "+ Customer data" button and `CustomerDataDialog`.
- Add state `const [route, setRoute] = useState<null | { kind: 'from' | 'to'; files?: File[] }>(null);`.
- Empty state (no revisions): replace the button with the same **Data from Brose** button. Its `revisions={[]}` forces the official path: when there are no majors, `DataFromBroseDialog` disables the feasibility radio with the hint "First Brose data must be official". Add that rule and a test in Task 7's file if not present.
- Pass these props to VersionNav:
  - `partId={part.id}`
  - `onFromBrose={() => setRoute({ kind: 'from' })}`
  - `onToBrose={() => setRoute({ kind: 'to' })}`
  - `onChanged={refresh}`

  where `refresh` invalidates `['part-revisions', part.id]`, `['revision-files']`, `['intakes']`, `['parts', projectId]` and `['project-structure', projectId]` (copy the keys `customerDataMutation.onSuccess` uses today).
- Render the dialogs. On done: refresh, `sel.selectRevision(result.revision.id)` (or `rev.id`), and show a toast:
  - `Filed as ${revisionLabel(...)}` for from-Brose
  - `Created ${rev.revision_name}` for to-Brose
- UploadDialog: pass `onNewCustomerData={(files) => { setUpload(null); setRoute({ kind: 'from', files }); }}`. Pass `route.files` as `initialFiles` to the from-Brose dialog.

**UploadDialog:**
- Delete the "Next customer data → {majorName}" radio, its fields (253-281) and the `level === 'major'` submit branch (140-148), plus now-unused state and imports. Keep the proposal branch only if the dialog still offers "new proposal". The spec removes creating iterations from uploads too, so delete that branch as well. The dialog only adds files to `currentRevision`.
- After parsing, if any parsed `customer_index` is set and differs (case-insensitive) from `currentRevision.customer_index`, show this block above the file list:

```tsx
<div className="rounded border border-amber-700 bg-amber-900/30 p-2 text-xs text-amber-200">
  These files carry index {idx}, not {currentRevision.customer_index ?? '–'}. New Brose data goes through Data from Brose.
  {onNewCustomerData && <button type="button" onClick={() => onNewCustomerData(files)} className="ml-2 underline">Open Data from Brose</button>}
</div>
```

**PartDetail:**
- Remove the `customerData`, `promote`, `proposal`, `reject` and `unreject` mutations, the dialogs at 358-372, the proposal summary box at 435-443, and the "+ Customer data" button at 340.
- Render `RevisionTimeline` read-only. Make `onNewProposal`, `onPromote`, `onReject` and `onUnreject` optional in `RevisionTimeline` Props, and render those buttons only when the handler is given. Above it, add:

```tsx
<Link to={`/projects/${part.project_id}?part=${part.id}`} className="text-xs text-blue-300 hover:underline">Manage versions in the project's Documents tab</Link>
```

- Remove `CustomerDataDialog` and `CustomerPackageDialog` imports where they are no longer used. Leave both component files in place; scripts and other pages may still import them. Check with `grep -rn "CustomerPackageDialog\|CustomerDataDialog" frontend/src --include=*.tsx | grep -v test`. If a component has zero remaining importers, delete it and its test.

- [ ] **Step 4:** Run `npx vitest run && npx tsc --noEmit -p . && npx eslint src --ext ts,tsx --max-warnings 0 && npm run build`. Expected: all PASS, build OK. Then run the impeccable detector: `/home/nitrolinux/.claude/skills/impeccable/scripts/impeccable detect --json frontend/src/components/parts/VersionNav.tsx frontend/src/components/parts/DataFromBroseDialog.tsx frontend/src/components/parts/DataToBroseDialog.tsx frontend/src/components/parts/IterationActions.tsx`. Expected: `[]`.

- [ ] **Step 5: Visual check (one batched round):**
  - Build a throwaway preview page the way the version navigator was checked. A `frontend/preview-*.html` plus `src/__preview_*.tsx`, served by `npx vite --port 5199` under `/plm2/`.
  - Show the nav with all four iteration kinds, and both dialogs open with Belt-exit-like data.
  - Screenshot at 900px and 420px widths with Playwright (Python). Fix what shows in one batch, then delete the preview files.
- [ ] **Step 6: Commit:** `git add -A frontend/src` (check `git status` first, so no `node_modules/.vite` files are staged), then `git commit -m "feat(data-route): two-button version creation in Documents; old entry points removed"`

---

### Task 10: 1994 direction backfill script

**Files:**
- Create: `backend/scripts/backfill_1994_direction.py`
- Test: `backend/tests/test_data_route_service.py`

**Interfaces:**
- Produces:
  - A script with `--apply` (dry run by default) and `--project 1994`.
  - A pure function `classify(summary: str | None) -> str`:
    - a summary starting with "Toolmaker data" → `to_customer`
    - one containing "DRAFT_MOD" or starting with "Investigation data" → `from_customer`
    - else `internal`

- [ ] **Step 1: Failing test**

```python
def test_backfill_classify():
    from scripts.backfill_1994_direction import classify
    assert classify("Toolmaker data, awaiting customer confirmation: 206.885.967 …") == "to_customer"
    assert classify("Investigation data, not official: Brose DRAFT_MOD of 2026-05-29") == "from_customer"
    assert classify(None) == "internal"
```

If `scripts` is not importable from tests, add `sys.path` handling the way existing script tests do. Check with `grep -rln "from scripts" backend/tests`. If none exist, put `classify` in `app/services/data_route_service.py` as `DataRouteService.classify_legacy` and import it from the script.

- [ ] **Step 2:** Run the test. Expected: FAIL.
- [ ] **Step 3: Implement** the script, following the pattern of `backend/scripts/add_1994_data_20261019.py` (async engine from `DATABASE_URL`, dry run by default):
  - Select the project's minors (`parent_revision_id IS NOT NULL`) where `direction IS NULL`.
  - Print `part_number revision_name -> direction | summary[:70]` for each.
  - On `--apply`, set `direction` and commit.
  - No changelog entries and no mail, because this is a data correction.
- [ ] **Step 4:** Run the test. Expected: PASS.
- [ ] **Step 5: Commit:** `git commit -am "chore(1994): direction backfill script"` (also `git add` the script).

---

### Task 11: Deploy (only with Christoph's OK)

**Files:** `memory/` notes only.

- [ ] **Step 1:** Run the full test suites: `cd backend && uv run pytest -q` and `cd frontend && npx vitest run && npm run build`. All must pass.
- [ ] **Step 2:** Re-check Task 0. If ecr-solid is not merged yet and the migration revises 145, **stop** and tell Christoph: deploy waits for ECR, or renumber per Task 0's alternative. Do not deploy a migration whose `down_revision` is missing on main.
- [ ] **Step 3:** Ask Christoph for the deploy OK. Tell him no mail is sent by the deploy. Then:
  1. Fast-forward `main` and `git push origin main`.
  2. On prod: `cd /data/compose/plm2 && git pull --ff-only`.
  3. Back up the DB with a unique name: `docker exec compose-plm2-db-1 pg_dump -U plm plm | gzip > /data/compose/db-backups/plm2-pre-data-route-$(date +%Y%m%d-%H%M%S).sql.gz`.
  4. `docker compose build plm2-backend plm2-frontend && docker compose up -d plm2-backend plm2-frontend`.
  5. Verify that `alembic_version` equals the new number and the logs show "Application startup complete".

  SSH rules: run `ktx-ssh-status` first. On any lock or REFUSED, stop and report.
- [ ] **Step 4:** Copy the backfill script into the container (`docker cp`), dry-run it, and show Christoph the list. **Apply only after his OK.** Expected list: 206.886.197 E1.1 → from_customer, five FZ E1.1s → to_customer.
- [ ] **Step 5:** Update `memory/version-nav-2026-10-19.md`, or create `memory/data-route-2026-10-19.md`, with what shipped. Add the MEMORY.md line and commit locally.

---

## Self-Review Notes

- Spec coverage:
  - Model: Tasks 1, 2 and 6.
  - Screens 1–5: Tasks 7, 8 and 9.
  - Removed/merged table: Task 9.
  - Data: Tasks 1, 2 and 10.
  - Errors: Tasks 4, 5 and 7 (triage hint).
  - Testing: every task.
  - Multi-part package: **merged differently than the spec states.** The header "+ Customer package" is removed, and multi-part Brose drops aren't yet handled by Data from Brose (single part). The package backend stays. Flagged to Christoph at plan review: multi-part can be a follow-up that reuses `CustomerPackageService.preview` inside the from-Brose dialog.
- The spec says "Confirm … goes through triage like any new folder". This is covered by `intake_source="promote"` in Task 5.
- The spec's "add to pending E2" offer is implemented as the dialog hint plus index-match routing (Task 7), not a separate button.
