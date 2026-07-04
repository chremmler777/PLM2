# Change Flow "Path to Quote" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a PM-owned scoping stage (meeting module) between capture and assessment, split the costing path into customer-quote vs. internal-approval branches, track per-assessment effort hours, and fix the deadline save/display bugs.

**Architecture:** New `scoping` status + `ChangeMeeting` table drive a pre-determination step whose "proceed" decision kicks off assessment with a department-scoped fan-out (filter applied in `ChangeRoutingService.build_routing` snapshot and mirrored in `WorkflowService._create_stage_tasks`). Gates stop being seeded at creation except `release`; the internal branch gets a hard `internal_approved_at` gate on `costing → approved`. Spec: `docs/superpowers/specs/2026-07-04-change-flow-path-to-quote-design.md`.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic (backend), React + TanStack Query + Tailwind + vitest (frontend), pytest-asyncio with per-test SQLite.

## Global Constraints

- Alembic: invoke the `alembic` console script directly (NOT `python3 -m alembic`), from `backend/`.
- Migrations: linear chain, next revision is `031` (revises `030`); idempotent `inspect(bind)` guards on every DDL op; must work on SQLite AND Postgres; `downgrade()` is `pass` (forward-only, consistent with 023–030).
- All UI strings go through `t('key')` from `src/i18n/cmLabels.ts` with DE + EN values.
- Backend tests: `cd backend && python3 -m pytest tests/ -x -q` (fixtures in `tests/conftest.py`; per-test SQLite via `Base.metadata.create_all`, so model changes apply without migrations in tests).
- Frontend tests: `cd frontend && npx vitest run`; typecheck via `npx tsc -b` — do not add NEW tsc errors beyond the existing baseline (21 errors).
- git: stage explicit paths only, never `git add -A`. Commit after each green task.
- Model tiering: tasks tagged **[mechanical]** may run on a lower-tier subagent model (haiku/sonnet); untagged tasks use the session default.
- Do not touch the implementation phase (`in_implementation` → `closed`), ECN spawn, or release logic.

---

### Task 1: Schema groundwork — ChangeMeeting model, effort/internal-approval columns, gate seeding, migration 031

**Files:**
- Modify: `backend/app/models/change.py` (add `MEETING_DECISIONS`, `ChangeMeeting`, `ChangeRequest` internal-approval columns + `meetings` relationship, `ChangeAssessment.effort_hours`)
- Modify: `backend/app/services/change_service.py:247-248` (seed only release gate)
- Create: `backend/alembic/versions/031_scoping_meetings.py`
- Modify: `backend/tests/test_change_gates.py` (seeding assertions)
- Test: `backend/tests/test_change_scoping.py` (new, first tests)

**Interfaces:**
- Produces: `ChangeMeeting` model (table `change_meetings`) with columns `id, change_id, meeting_date: datetime, participants: JSON list[{"name": str, "user_id": int|None}], notes: str|None, decision: str|None ('proceed'|'reject'|'needs_info'), selected_department_ids: JSON list[int], created_by, created_at, decided_by, decided_at`; constant `MEETING_DECISIONS = ("proceed", "reject", "needs_info")`.
- Produces: `ChangeRequest.internal_approved_by/at/amount/approval_note`, `ChangeAssessment.effort_hours: float|None`, `ChangeRequest.meetings` relationship (ordered by id).
- Produces: `create_change` seeds ONLY the `release` gate.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_change_scoping.py`:

```python
"""Scoping stage: meeting model, gate seeding, and (later tasks) the state machine."""
import pytest
from sqlalchemy import select

from tests.conftest import login, ADMIN_PASSWORD


async def create_change(client, auth, project_id, **overrides):
    body = {"project_id": project_id, "title": "Scoped change",
            "change_type": "physical_part", **overrides}
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.asyncio
async def test_create_seeds_only_release_gate(client, admin_auth, seed):
    change = await create_change(client, admin_auth, seed["project_id"])
    res = await client.get(f"/api/v1/changes/{change['id']}/gates", headers=admin_auth)
    assert res.status_code == 200
    assert [g["gate_key"] for g in res.json()] == ["release"]


@pytest.mark.asyncio
async def test_meeting_model_roundtrip(session_factory, client, admin_auth, seed):
    from datetime import datetime
    from app.models.change import ChangeMeeting
    change = await create_change(client, admin_auth, seed["project_id"])
    async with session_factory() as s:
        s.add(ChangeMeeting(
            change_id=change["id"], meeting_date=datetime.utcnow(),
            participants=[{"name": "PM Jane"}], notes="scope clarified",
            decision=None, selected_department_ids=[1, 2],
            created_by=seed["admin_id"]))
        await s.commit()
    async with session_factory() as s:
        row = (await s.execute(select(ChangeMeeting).where(
            ChangeMeeting.change_id == change["id"]))).scalar_one()
        assert row.participants == [{"name": "PM Jane"}]
        assert row.selected_department_ids == [1, 2]
        assert row.decision is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_change_scoping.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'ChangeMeeting'` (second test) and 3 gates instead of 1 (first test).

- [ ] **Step 3: Add model code**

In `backend/app/models/change.py`, after `IMPLEMENTATION_MODES` (line 46) add:

```python
MEETING_DECISIONS = ("proceed", "reject", "needs_info")
```

On `ChangeRequest`, after the `required_by_*` block (line 100) add:

```python
    # Internal branch of the costing path split: PM approves the summation
    # total for non-customer-relevant changes (no quote step). Amount is a
    # snapshot of the summation grand total at approval time (P&L hook).
    internal_approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    internal_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    internal_approved_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    internal_approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
```

In the `ChangeRequest` relationship block (after `affected_plants`, line 157):

```python
    meetings: Mapped[list["ChangeMeeting"]] = relationship(
        back_populates="change", cascade="all, delete-orphan", lazy="selectin",
        order_by="ChangeMeeting.id",
    )
```

On `ChangeAssessment`, after `lifecycle_cost` (line 199):

```python
    # Time the assessor spent on the feasibility check itself (effort tracking).
    effort_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
```

New model class after `ChangeAttachment` (line 308):

```python
class ChangeMeeting(Base):
    """A pre-determination (scoping) meeting record. The 'proceed' decision is
    what kicks off assessment; its selected_department_ids scope the stage-1
    fan-out. A change may hold several meetings (needs_info -> follow-up)."""
    __tablename__ = "change_meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)

    meeting_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    participants: Mapped[list] = mapped_column(JSON, default=list)   # [{"name": str, "user_id": int|None}]
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)  # proceed|reject|needs_info
    selected_department_ids: Mapped[list] = mapped_column(JSON, default=list)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    change: Mapped["ChangeRequest"] = relationship(back_populates="meetings", foreign_keys=[change_id])
```

In `backend/app/services/change_service.py:247-248`, replace:

```python
        for key in GATE_KEYS:
            session.add(ChangeGate(change_id=change.id, gate_key=key))
```

with:

```python
        # Only the release gate is seeded up front. Feasibility is answered by
        # the scoping meeting decision; budget by the costing path split
        # (customer quote acceptance / internal cost approval).
        session.add(ChangeGate(change_id=change.id, gate_key="release"))
```

- [ ] **Step 4: Write migration 031**

Create `backend/alembic/versions/031_scoping_meetings.py`:

```python
"""031: Scoping stage groundwork — meeting records, effort tracking, internal
cost approval, gate-seeding change.

- change_meetings table (pre-determination meeting module)
- change_assessments.effort_hours (time spent on the feasibility check)
- change_requests internal_approved_* columns (internal costing branch)
- removes undecided feasibility/budget gate rows on not-yet-started
  (captured) changes: those decisions are superseded by the scoping meeting
  and the costing path split. Decided rows and in-flight changes keep their
  gates so history stays truthful.

Revision ID: 031
Revises: 030
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if "change_meetings" not in insp.get_table_names():
        op.create_table(
            "change_meetings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(),
                      sa.ForeignKey("change_requests.id"), nullable=False, index=True),
            sa.Column("meeting_date", sa.DateTime(), nullable=False),
            sa.Column("participants", sa.JSON(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("decision", sa.String(20), nullable=True),
            sa.Column("selected_department_ids", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
        )

    cols = {c["name"] for c in insp.get_columns("change_assessments")}
    if "effort_hours" not in cols:
        op.add_column("change_assessments",
                      sa.Column("effort_hours", sa.Float(), nullable=True))

    cr_cols = {c["name"] for c in insp.get_columns("change_requests")}
    if "internal_approved_by" not in cr_cols:
        op.add_column("change_requests",
                      sa.Column("internal_approved_by", sa.Integer(), nullable=True))
    if "internal_approved_at" not in cr_cols:
        op.add_column("change_requests",
                      sa.Column("internal_approved_at", sa.DateTime(), nullable=True))
    if "internal_approved_amount" not in cr_cols:
        op.add_column("change_requests",
                      sa.Column("internal_approved_amount", sa.Float(), nullable=True))
    if "internal_approval_note" not in cr_cols:
        op.add_column("change_requests",
                      sa.Column("internal_approval_note", sa.Text(), nullable=True))

    op.execute(sa.text(
        "DELETE FROM change_gate WHERE decision = 'na' "
        "AND gate_key IN ('feasibility', 'budget') "
        "AND change_id IN (SELECT id FROM change_requests WHERE status = 'captured')"))


def downgrade() -> None:
    pass  # forward-only, consistent with 023-030
```

- [ ] **Step 5: Fix `test_change_gates.py` seeding assertions**

Open `backend/tests/test_change_gates.py` and update any test asserting three seeded gates: creation now yields only `release`. Where a test needs a feasibility/budget gate to exist, it may still `PUT /gates/{key}` (`decide_gate` creates the row on demand, `change_service.py:146-148`) — the gate-blocks-transition behaviour for existing rows is unchanged and must stay tested.

- [ ] **Step 6: Run tests, apply migration to dev DB**

Run: `cd backend && python3 -m pytest tests/test_change_scoping.py tests/test_change_gates.py -x -q`
Expected: PASS.
Run: `cd backend && alembic upgrade head`
Expected: `Running upgrade 030 -> 031` without error (dev SQLite `plm.db`).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/change.py backend/app/services/change_service.py \
        backend/alembic/versions/031_scoping_meetings.py \
        backend/tests/test_change_scoping.py backend/tests/test_change_gates.py
git commit -m "feat(scoping): ChangeMeeting model, effort/internal-approval columns, release-only gate seeding (migration 031)"
```

---

### Task 2: State machine — `scoping` status, path split, hard gates, existing-test sweep

**Files:**
- Modify: `backend/app/models/change.py:25-29` (`CHANGE_STATUSES`)
- Modify: `backend/app/services/change_service.py:46-60` (`ALLOWED_TRANSITIONS`), `:480-531` (`_guard`), `:544-549` (hard gates in `transition`)
- Modify: `backend/tests/conftest.py` (new helpers)
- Test: `backend/tests/test_change_scoping.py` (extend)
- Modify: every existing test that transitions `captured → in_assessment` or `costing → quoted` (sweep, see Step 6)

**Interfaces:**
- Consumes: `ChangeMeeting` from Task 1.
- Produces: status `scoping`; transitions `captured→scoping`, `scoping→{in_assessment, rejected, cancelled, on_hold}`, `costing→approved` (internal); soft guard "proceed meeting required" on `→in_assessment`; hard errors: quote for internal changes, approval without internal approval / without customer acceptance.
- Produces: conftest helpers `record_proceed_meeting(session_factory, change_id, dept_ids=None, actor_id=1)` and `advance_to_assessment(client, auth, session_factory, change_id, dept_ids=None)` — all later tasks and swept tests use these.

- [ ] **Step 1: Write failing tests** (append to `test_change_scoping.py`)

```python
from tests.conftest import record_proceed_meeting, advance_to_assessment


async def add_item_and_lead(client, auth, change_id, part_id):
    res = await client.post(f"/api/v1/changes/{change_id}/impacted-items",
                            json={"part_id": part_id, "is_lead": True}, headers=auth)
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_captured_goes_to_scoping_not_assessment(client, admin_auth, seed, part):
    change = await create_change(client, admin_auth, seed["project_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "in_assessment"}, headers=admin_auth)
    assert res.status_code == 400  # no longer a legal edge
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "scoping"}, headers=admin_auth)
    assert res.status_code == 200
    assert res.json()["status"] == "scoping"


@pytest.mark.asyncio
async def test_assessment_requires_proceed_meeting(client, admin_auth, seed, part,
                                                   session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    await client.post(f"/api/v1/changes/{change['id']}/transition",
                      json={"to_status": "scoping"}, headers=admin_auth)
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "in_assessment"}, headers=admin_auth)
    assert res.status_code == 400
    assert "proceed" in res.json()["detail"].lower()
    await record_proceed_meeting(session_factory, change["id"],
                                 actor_id=seed["admin_id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "in_assessment"}, headers=admin_auth)
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_internal_change_skips_quote_and_needs_internal_approval(
        client, admin_auth, seed, part, session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    await advance_to_assessment(client, admin_auth, session_factory, change["id"])
    # drive to costing directly in DB (assessment mechanics are not under test here)
    from sqlalchemy import update
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(
            ChangeRequest.id == change["id"]).values(status="costing"))
        await s.commit()
    # internal change (customer_relevant defaults False): quote is a hard no
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "quoted"}, headers=admin_auth)
    assert res.status_code == 400
    # approved blocked until internal approval exists
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "approved"}, headers=admin_auth)
    assert res.status_code == 400
    assert "internal" in res.json()["detail"].lower()
    async with session_factory() as s:
        from datetime import datetime
        await s.execute(update(ChangeRequest).where(
            ChangeRequest.id == change["id"]).values(
            internal_approved_by=seed["admin_id"],
            internal_approved_at=datetime.utcnow()))
        await s.commit()
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "approved"}, headers=admin_auth)
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_customer_change_cannot_bypass_quote(client, admin_auth, seed, part,
                                                   session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await client.patch(f"/api/v1/changes/{change['id']}",
                       json={"customer_relevant": True}, headers=admin_auth)
    from sqlalchemy import update
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(
            ChangeRequest.id == change["id"]).values(status="costing"))
        await s.commit()
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "approved"}, headers=admin_auth)
    assert res.status_code == 400  # customer branch must go through quote
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_change_scoping.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'record_proceed_meeting'`.

- [ ] **Step 3: Add conftest helpers** (append to `backend/tests/conftest.py`)

```python
async def record_proceed_meeting(session_factory, change_id: int,
                                 dept_ids: list[int] | None = None,
                                 actor_id: int = 1):
    """Insert a decided 'proceed' scoping meeting directly (bypasses the API
    so state-machine tests don't depend on the meeting endpoints)."""
    from datetime import datetime
    from app.models.change import ChangeMeeting
    async with session_factory() as s:
        s.add(ChangeMeeting(
            change_id=change_id, meeting_date=datetime.utcnow(),
            participants=[{"name": "Test PM"}], notes="scope ok",
            decision="proceed", selected_department_ids=dept_ids or [],
            created_by=actor_id, decided_by=actor_id,
            decided_at=datetime.utcnow()))
        await s.commit()


async def advance_to_assessment(client, auth, session_factory, change_id: int,
                                dept_ids: list[int] | None = None):
    """captured -> scoping -> (proceed meeting) -> in_assessment."""
    res = await client.post(f"/api/v1/changes/{change_id}/transition",
                            json={"to_status": "scoping"}, headers=auth)
    assert res.status_code == 200, res.text
    await record_proceed_meeting(session_factory, change_id, dept_ids)
    res = await client.post(f"/api/v1/changes/{change_id}/transition",
                            json={"to_status": "in_assessment"}, headers=auth)
    assert res.status_code == 200, res.text
```

- [ ] **Step 4: Implement the state machine**

`backend/app/models/change.py:25-29` — insert `"scoping"`:

```python
CHANGE_STATUSES = (
    "captured", "scoping", "in_assessment", "costing", "quoted", "approved",
    "in_implementation", "in_validation", "released", "closed",
    "on_hold", "rejected", "cancelled",
)
```

`backend/app/services/change_service.py:46-60`:

```python
ALLOWED_TRANSITIONS = {
    "captured":          {"scoping", "cancelled", "on_hold"},
    "scoping":           {"in_assessment", "rejected", "cancelled", "on_hold"},
    "in_assessment":     {"costing", "rejected", "cancelled", "on_hold"},
    "costing":           {"quoted", "approved", "on_hold", "cancelled"},
    "quoted":            {"approved", "rejected", "on_hold", "cancelled"},
    "approved":          {"in_implementation", "on_hold", "cancelled"},
    "in_implementation": {"in_validation", "on_hold", "cancelled"},
    "in_validation":     {"released", "in_implementation", "on_hold", "cancelled"},
    "released":          {"closed"},
    "on_hold":           {"scoping", "in_assessment", "costing", "quoted", "approved",
                          "in_implementation", "in_validation", "cancelled"},
    "rejected":          set(),
    "closed":            set(),
    "cancelled":         set(),
}
```

In `_guard` (`change_service.py:480`), extend the `in_assessment` branch (import `ChangeMeeting` in the module-level import block from `app.models.change`):

```python
        if to_status == "in_assessment":
            count = len(change.impacted_items)
            if count == 0:
                return "No impacted items added yet"
            if change.lead_id is None:
                return "No lead (project manager) assigned"
            proceed = (await session.execute(
                select(ChangeMeeting.id).where(
                    ChangeMeeting.change_id == change.id,
                    ChangeMeeting.decision == "proceed").limit(1)
            )).scalar_one_or_none()
            if proceed is None:
                return "No scoping meeting with decision 'proceed' recorded"
```

In `transition` (`change_service.py:544-549`), replace the hard-gate block with:

```python
        # HARD gates: the approval decision cannot be forced.
        if to_status == "approved":
            if change.customer_relevant:
                if change.customer_response != "accepted":
                    raise ChangeError("Customer has not accepted the offer")
                if change.pm_signed_by is None or change.quality_signed_by is None:
                    raise ChangeError("Both PM and Quality sign-off are required")
                if change.status == "costing":
                    raise ChangeError(
                        "Customer-relevant changes must go through the quote")
            else:
                if change.internal_approved_at is None:
                    raise ChangeError(
                        "Internal cost approval is required before approval")
        if to_status == "quoted" and not change.customer_relevant:
            raise ChangeError(
                "Internal changes skip the quote — record internal cost approval instead")
```

- [ ] **Step 5: Run the new tests**

Run: `cd backend && python3 -m pytest tests/test_change_scoping.py -x -q`
Expected: PASS.

- [ ] **Step 6: Sweep existing tests onto the new flow**

Run: `cd backend && python3 -m pytest tests/ -q 2>&1 | tail -20` and fix every failure. Mechanical recipe:

1. `grep -rln '"to_status": "in_assessment"' tests/` — each hit that starts from `captured` becomes `await advance_to_assessment(client, <auth>, session_factory, change_id)` (add `session_factory` to the test's fixture args). Where the test previously called `approve_gates(..., "feasibility")` before kickoff, delete that call (the gate row no longer exists at creation; `approve_gates` without keys still works because `put_gate` creates rows on demand — leave those alone only if the test asserts gate behaviour itself).
2. `grep -rln '"to_status": "quoted"' tests/` — each hit needs `customer_relevant: True` set first via `PATCH /api/v1/changes/{id}` (and the same before any `quoted → approved` path relying on customer response + sign-offs).
3. Tests asserting the full status list or `ALLOWED_TRANSITIONS` shape: add `scoping`.
4. Do NOT weaken any assertion about gate blocking, deviations, or sign-offs — reroute the setup, keep the assertion.

Run: `cd backend && python3 -m pytest tests/ -q`
Expected: full suite PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/change.py backend/app/services/change_service.py \
        backend/tests/
git commit -m "feat(scoping): scoping status, costing path split, hard internal/quote gates; reroute tests"
```

---

### Task 3: Meeting service + REST endpoints

**Files:**
- Create: `backend/app/services/meeting_service.py`
- Modify: `backend/app/schemas/change.py` (meeting schemas)
- Modify: `backend/app/api/v1/changes/changes.py` (4 endpoints)
- Test: `backend/tests/test_change_meetings.py`

**Interfaces:**
- Consumes: `ChangeMeeting`, `MEETING_DECISIONS` (Task 1); `ChangeService.transition` with `scoping` edges (Task 2).
- Produces: `MeetingService.user_is_pm(session, user) -> bool`; `MeetingService.create_meeting(session, change, user, *, meeting_date, participants, notes, selected_department_ids) -> ChangeMeeting`; `MeetingService.update_meeting(session, change, meeting_id, user, **fields) -> ChangeMeeting`; `MeetingService.decide_meeting(session, change, meeting_id, decision, user) -> ChangeMeeting`.
- Produces REST: `GET /api/v1/changes/{id}/meetings` → `list[MeetingResponse]`; `POST .../meetings` (create); `PATCH .../meetings/{mid}` (edit while undecided); `POST .../meetings/{mid}/decide {"decision": ...}`. `decide` with `proceed` auto-hops `captured→scoping` if needed, then transitions to `in_assessment`; `reject` transitions to `rejected`.
- Produces: `MeetingResponse {id, change_id, meeting_date, participants, notes, decision, selected_department_ids, created_by, created_at, decided_by, decided_at}`.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_change_meetings.py`:

```python
"""Meeting module: CRUD, PM authz, decide side effects."""
import pytest

from tests.conftest import login, ENGINEER_PASSWORD
from tests.test_change_scoping import create_change, add_item_and_lead


async def post_meeting(client, auth, change_id, **overrides):
    body = {"participants": [{"name": "PM Jane"}, {"name": "Customer Rep"}],
            "notes": "Initial scope clarification",
            "selected_department_ids": [], **overrides}
    return await client.post(f"/api/v1/changes/{change_id}/meetings",
                             json=body, headers=auth)


@pytest.mark.asyncio
async def test_meeting_crud_and_needs_info(client, admin_auth, seed):
    change = await create_change(client, admin_auth, seed["project_id"])
    res = await post_meeting(client, admin_auth, change["id"])
    assert res.status_code == 200, res.text
    mid = res.json()["id"]
    res = await client.patch(f"/api/v1/changes/{change['id']}/meetings/{mid}",
                             json={"notes": "updated"}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["notes"] == "updated"
    res = await client.post(f"/api/v1/changes/{change['id']}/meetings/{mid}/decide",
                            json={"decision": "needs_info"}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["decision"] == "needs_info"
    # decided meetings are immutable
    res = await client.patch(f"/api/v1/changes/{change['id']}/meetings/{mid}",
                             json={"notes": "nope"}, headers=admin_auth)
    assert res.status_code == 400
    # change unaffected by needs_info
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=admin_auth)
    assert res.json()["status"] == "captured"
    # list shows the meeting
    res = await client.get(f"/api/v1/changes/{change['id']}/meetings", headers=admin_auth)
    assert len(res.json()) == 1


@pytest.mark.asyncio
async def test_proceed_kicks_off_assessment(client, admin_auth, seed, part,
                                            session_factory):
    from sqlalchemy import select
    from app.models.workflow import Department
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    async with session_factory() as s:
        dept_ids = [d for (d,) in await s.execute(select(Department.id))][:2]
    res = await post_meeting(client, admin_auth, change["id"],
                             selected_department_ids=dept_ids)
    mid = res.json()["id"]
    # proceed without departments is rejected on a fresh meeting
    res2 = await post_meeting(client, admin_auth, change["id"])
    res3 = await client.post(
        f"/api/v1/changes/{change['id']}/meetings/{res2.json()['id']}/decide",
        json={"decision": "proceed"}, headers=admin_auth)
    assert res3.status_code == 400
    # proceed with departments: captured -> scoping -> in_assessment in one call
    res = await client.post(f"/api/v1/changes/{change['id']}/meetings/{mid}/decide",
                            json={"decision": "proceed"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=admin_auth)
    assert res.json()["status"] == "in_assessment"


@pytest.mark.asyncio
async def test_reject_decision_rejects_change(client, admin_auth, seed):
    change = await create_change(client, admin_auth, seed["project_id"])
    res = await post_meeting(client, admin_auth, change["id"])
    mid = res.json()["id"]
    res = await client.post(f"/api/v1/changes/{change['id']}/meetings/{mid}/decide",
                            json={"decision": "reject"}, headers=admin_auth)
    assert res.status_code == 200
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=admin_auth)
    assert res.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_meeting_authz_pm_or_lead_or_admin(client, admin_auth, seed):
    # engineer is neither admin, lead, nor PM-department member
    change = await create_change(client, admin_auth, seed["project_id"])
    eng_auth = await login(client, "eng@test.io", ENGINEER_PASSWORD)
    res = await post_meeting(client, eng_auth, change["id"])
    assert res.status_code == 400
```

Note: `test_change_scoping.create_change` posts with admin auth headers passed in, so importing it is safe.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_change_meetings.py -x -q`
Expected: FAIL with 404s (endpoints missing).

- [ ] **Step 3: Implement `MeetingService`**

Create `backend/app/services/meeting_service.py`:

```python
"""Scoping-stage meeting records: PM-gated CRUD and the decide side effects
(proceed -> kick off assessment; reject -> reject the change)."""
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeRequest, ChangeMeeting, MEETING_DECISIONS
from app.models.entities import User
from app.models.workflow import Department
from app.services.change_service import ChangeService, ChangeError


class MeetingService:

    @staticmethod
    async def user_is_pm(session: AsyncSession, user: User) -> bool:
        """Admin, or member of the 'Project Manager' department (mirrors the
        pattern of ChangeService.user_can_confirm_impact for R&D)."""
        if user.role == "admin":
            return True
        from app.services.workflow_service import WorkflowService
        pm_dept = (await session.execute(
            select(Department).where(Department.name == "Project Manager"))
        ).scalar_one_or_none()
        if pm_dept is None:
            return False
        return pm_dept.id in await WorkflowService.get_user_department_ids(
            session, user.id)

    @staticmethod
    async def _authz(session: AsyncSession, change: ChangeRequest, user: User):
        if user.id == change.lead_id:
            return
        if not await MeetingService.user_is_pm(session, user):
            raise ChangeError(
                "Only Project Management, the change lead, or an admin "
                "may manage scoping meetings")

    @staticmethod
    async def _validate_departments(session: AsyncSession, dept_ids: list[int]) -> list[int]:
        dept_ids = list(dict.fromkeys(dept_ids or []))
        if dept_ids:
            found = {d for (d,) in await session.execute(
                select(Department.id).where(Department.id.in_(dept_ids)))}
            unknown = sorted(set(dept_ids) - found)
            if unknown:
                raise ChangeError(f"Unknown departments: {unknown}")
        return dept_ids

    @staticmethod
    async def create_meeting(
        session: AsyncSession, change: ChangeRequest, user: User, *,
        meeting_date: Optional[datetime] = None,
        participants: Optional[list] = None, notes: Optional[str] = None,
        selected_department_ids: Optional[list[int]] = None,
    ) -> ChangeMeeting:
        await MeetingService._authz(session, change, user)
        if change.status not in ("captured", "scoping"):
            raise ChangeError(
                "Scoping meetings can only be recorded before assessment starts")
        dept_ids = await MeetingService._validate_departments(
            session, selected_department_ids or [])
        meeting = ChangeMeeting(
            change_id=change.id, meeting_date=meeting_date or datetime.utcnow(),
            participants=participants or [], notes=notes,
            selected_department_ids=dept_ids, created_by=user.id)
        session.add(meeting)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "scoping_meeting_recorded",
            f"Scoping meeting #{meeting.id} recorded", user.id,
            new_value={"meeting_id": meeting.id})
        return meeting

    @staticmethod
    async def _get_meeting(session: AsyncSession, change: ChangeRequest,
                           meeting_id: int) -> ChangeMeeting:
        meeting = await session.get(ChangeMeeting, meeting_id)
        if meeting is None or meeting.change_id != change.id:
            raise ChangeError("Meeting not found on this change")
        return meeting

    @staticmethod
    async def update_meeting(
        session: AsyncSession, change: ChangeRequest, meeting_id: int,
        user: User, **fields,
    ) -> ChangeMeeting:
        await MeetingService._authz(session, change, user)
        meeting = await MeetingService._get_meeting(session, change, meeting_id)
        if meeting.decision is not None:
            raise ChangeError("A decided meeting can no longer be edited")
        if "selected_department_ids" in fields and fields["selected_department_ids"] is not None:
            fields["selected_department_ids"] = await MeetingService._validate_departments(
                session, fields["selected_department_ids"])
        for k in ("meeting_date", "participants", "notes", "selected_department_ids"):
            if k in fields and fields[k] is not None:
                setattr(meeting, k, fields[k])
        await session.flush()
        return meeting

    @staticmethod
    async def decide_meeting(
        session: AsyncSession, change: ChangeRequest, meeting_id: int,
        decision: str, user: User,
    ) -> ChangeMeeting:
        await MeetingService._authz(session, change, user)
        if decision not in MEETING_DECISIONS:
            raise ChangeError(f"Invalid meeting decision '{decision}'")
        meeting = await MeetingService._get_meeting(session, change, meeting_id)
        if meeting.decision is not None:
            raise ChangeError(f"Meeting already decided ('{meeting.decision}')")
        if decision == "proceed" and not meeting.selected_department_ids:
            raise ChangeError(
                "Select at least one impacted department before proceeding")
        meeting.decision = decision
        meeting.decided_by = user.id
        meeting.decided_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "scoping_meeting_decided",
            f"Scoping meeting #{meeting.id}: {decision}", user.id,
            field_name="decision", new_value=decision, notes=meeting.notes)
        if decision in ("proceed", "reject"):
            if change.status == "captured":
                await ChangeService.transition(session, change, "scoping", user.id)
            target = "in_assessment" if decision == "proceed" else "rejected"
            await ChangeService.transition(session, change, target, user.id)
        return meeting
```

Note `_authz` intentionally lets the change lead through without the PM check — admin passes via `user_is_pm`.

- [ ] **Step 4: Schemas + endpoints**

Append to `backend/app/schemas/change.py`:

```python
class MeetingParticipant(BaseModel):
    name: str
    user_id: Optional[int] = None


class MeetingCreate(BaseModel):
    meeting_date: Optional[datetime] = None
    participants: List[MeetingParticipant] = []
    notes: Optional[str] = None
    selected_department_ids: List[int] = []


class MeetingUpdate(BaseModel):
    meeting_date: Optional[datetime] = None
    participants: Optional[List[MeetingParticipant]] = None
    notes: Optional[str] = None
    selected_department_ids: Optional[List[int]] = None


class MeetingDecideIn(BaseModel):
    decision: str  # proceed | reject | needs_info


class MeetingResponse(BaseModel):
    id: int
    change_id: int
    meeting_date: datetime
    participants: List[MeetingParticipant] = []
    notes: Optional[str] = None
    decision: Optional[str] = None
    selected_department_ids: List[int] = []
    created_by: int
    created_at: datetime
    decided_by: Optional[int] = None
    decided_at: Optional[datetime] = None

    class Config:
        from_attributes = True
```

Append to `backend/app/api/v1/changes/changes.py` (import `MeetingCreate, MeetingUpdate, MeetingDecideIn, MeetingResponse` in the schemas import, and `MeetingService` from `app.services.meeting_service`):

```python
@router.get("/{change_id}/meetings", response_model=List[MeetingResponse])
async def list_meetings(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change.meetings


@router.post("/{change_id}/meetings", response_model=MeetingResponse)
async def create_meeting(
    change_id: int, body: MeetingCreate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        meeting = await MeetingService.create_meeting(
            db, change, current_user, meeting_date=body.meeting_date,
            participants=[p.model_dump() for p in body.participants],
            notes=body.notes, selected_department_ids=body.selected_department_ids)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(meeting)
    return meeting


@router.patch("/{change_id}/meetings/{meeting_id}", response_model=MeetingResponse)
async def update_meeting(
    change_id: int, meeting_id: int, body: MeetingUpdate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    fields = body.model_dump(exclude_unset=True)
    if "participants" in fields and fields["participants"] is not None:
        fields["participants"] = [
            p if isinstance(p, dict) else p.model_dump() for p in fields["participants"]]
    try:
        meeting = await MeetingService.update_meeting(
            db, change, meeting_id, current_user, **fields)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(meeting)
    return meeting


@router.post("/{change_id}/meetings/{meeting_id}/decide", response_model=MeetingResponse)
async def decide_meeting(
    change_id: int, meeting_id: int, body: MeetingDecideIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        meeting = await MeetingService.decide_meeting(
            db, change, meeting_id, body.decision, current_user)
    except ValueError as e:
        # transition side effects raise ChangeError (a ValueError subclass);
        # WorkflowService kick-off gates raise plain ValueError.
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(meeting)
    return meeting
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python3 -m pytest tests/test_change_meetings.py tests/test_change_scoping.py -x -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/meeting_service.py backend/app/schemas/change.py \
        backend/app/api/v1/changes/changes.py backend/tests/test_change_meetings.py
git commit -m "feat(scoping): meeting service + REST endpoints; proceed/reject drive the state machine"
```

---

### Task 4: Scoped assessment fan-out (stage-1 department filter)

**Files:**
- Modify: `backend/app/services/change_routing_service.py:115-176` (`build_routing`)
- Modify: `backend/app/services/workflow_service.py:165-233` (`_create_stage_tasks`)
- Test: `backend/tests/test_change_scoping.py` (extend)

**Interfaces:**
- Consumes: latest `ChangeMeeting` with `decision == "proceed"` (Tasks 1–3).
- Produces: `build_routing` filters **stage-1** snapshot departments (all letters incl. I) to the meeting's `selected_department_ids`; stages ≥ 2 are untouched (PM/Sales summation & quote are process roles, not impact roles). `_create_stage_tasks` skips template RASIC assignments absent from the change's routing snapshot for that stage, so engine tasks always mirror the snapshot.

- [ ] **Step 1: Write failing test** (append to `test_change_scoping.py`)

```python
@pytest.mark.asyncio
async def test_scoping_selection_filters_stage1_fanout(
        client, admin_auth, seed, part, session_factory):
    from sqlalchemy import select
    from app.models.change import ChangeAssessment
    from app.models.workflow import Department, WfInstance, WfInstanceTask
    # Seed the ECM Assessment routing standard so a real multi-dept template applies
    from app.services.wf_seed_service import seed_ecm_assessment_standard
    async with session_factory() as s:
        await seed_ecm_assessment_standard(s)
        await s.commit()
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    async with session_factory() as s:
        picked = [d for (d,) in await s.execute(
            select(Department.id).where(Department.name.in_(["Quality", "Logistics"])))]
    assert len(picked) == 2
    await advance_to_assessment(client, admin_auth, session_factory,
                                change["id"], dept_ids=picked)
    async with session_factory() as s:
        stage1 = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"],
            ChangeAssessment.stage_order == 1))).scalars().all()
        assert {a.department_id for a in stage1} == set(picked)
        # later stages keep template routing (PM/Sales exist beyond stage 1)
        later = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"],
            ChangeAssessment.stage_order > 1))).scalars().all()
        assert later, "stage >= 2 rows must not be filtered away"
        # engine stage-1 tasks are equally scoped
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == change["id"],
            WfInstance.status == "active"))).scalar_one()
        tasks = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id,
            WfInstanceTask.stage_order == 1))).scalars().all()
        assert {t.department_id for t in tasks} <= set(picked)
        assert tasks, "picked departments must have stage-1 tasks"
```

Check `backend/app/services/wf_seed_service.py` for the actual seeding function name for the ECM Assessment template/standard (around lines 23–47 and wherever `ChangeRoutingStandard` is written); adjust the import in the test to the real name — if only a combined `seed_*` entry point exists, call that.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_change_scoping.py::test_scoping_selection_filters_stage1_fanout -x -q`
Expected: FAIL — stage-1 set contains all template departments, not just the picked two.

- [ ] **Step 3: Filter the snapshot in `build_routing`**

In `change_routing_service.py`, import `ChangeMeeting` from `app.models.change`. After `resolve_standard` returns (line 129), before constructing `ChangeRouting`:

```python
        # Scoped fan-out: the latest 'proceed' scoping meeting restricts which
        # departments take part in stage 1 (the impact-assessment stage).
        # Later stages are process roles (summation, quote) and stay as the
        # template defines them.
        proceed = (await session.execute(
            select(ChangeMeeting)
            .where(ChangeMeeting.change_id == change.id,
                   ChangeMeeting.decision == "proceed")
            .order_by(ChangeMeeting.decided_at.desc(), ChangeMeeting.id.desc())
            .limit(1))).scalar_one_or_none()
        if proceed is not None and proceed.selected_department_ids:
            allowed = set(proceed.selected_department_ids)
            for stage in stages:
                if stage["stage_order"] == 1:
                    kept = [d for d in stage["departments"]
                            if d["department_id"] in allowed]
                    if not kept:
                        raise ValueError(
                            "Scoping selection matches no stage-1 department "
                            "of the routing standard")
                    stage["departments"] = kept
```

- [ ] **Step 4: Mirror the snapshot in `_create_stage_tasks`**

In `workflow_service.py:_create_stage_tasks`, before the `for step in ...` loop (line 175):

```python
        # Change-scoped instances execute the change's routing *snapshot*, which
        # may be scoped down from the template (scoping-meeting department
        # selection, deviations). Skip template assignments absent from the
        # snapshot so engine tasks never outnumber the governed routing.
        allowed_pairs: set | None = None
        if instance.change_id is not None:
            from app.models.change import ChangeRouting
            routing = (await db.execute(
                select(ChangeRouting).where(
                    ChangeRouting.change_id == instance.change_id)
            )).scalar_one_or_none()
            if routing is not None:
                snap_stage = next(
                    (st for st in routing.standard_snapshot.get("stages", [])
                     if st["stage_order"] == stage.stage_order), None)
                if snap_stage is not None:
                    allowed_pairs = {(d["department_id"], d["rasic_letter"])
                                     for d in snap_stage["departments"]}
```

and inside the inner `for rasic in step.rasic_assignments:` loop, as the first line:

```python
                if allowed_pairs is not None and \
                        (rasic.department_id, rasic.rasic_letter) not in allowed_pairs:
                    continue
```

(`build_routing` flushes the `ChangeRouting` row before `start_change_workflow` runs, so the query sees it within the same session.)

- [ ] **Step 5: Run tests — new test AND the full suite**

Run: `cd backend && python3 -m pytest tests/test_change_scoping.py -x -q && python3 -m pytest tests/ -q`
Expected: all PASS (tests using `advance_to_assessment` without `dept_ids` pass `[]` → no filter applied, full fan-out as before).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_routing_service.py \
        backend/app/services/workflow_service.py backend/tests/test_change_scoping.py
git commit -m "feat(scoping): stage-1 fan-out scoped to the proceed meeting's department selection"
```

---

### Task 5: Effort hours on assessments + summation rollup **[mechanical]**

**Files:**
- Modify: `backend/app/schemas/change.py` (`AssessmentSubmit`, `AssessmentResponse`, `SummationResponse` + new `EffortRollup`)
- Modify: `backend/app/services/change_service.py:1041-1097` (`submit_assessment`)
- Modify: `backend/app/api/v1/changes/changes.py:493-516` (pass-through)
- Modify: `backend/app/services/cost_service.py:82-109` (`summation`)
- Test: `backend/tests/test_assessment_effort.py`

**Interfaces:**
- Consumes: `ChangeAssessment.effort_hours` column (Task 1).
- Produces: `AssessmentSubmit.effort_hours: Optional[float] (ge=0)`; `submit_assessment(..., effort_hours=None)` persists it; `AssessmentResponse.effort_hours`; `SummationResponse.effort_by_department: [{department_id, effort_hours}]` and `total_effort_hours: float`.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_assessment_effort.py`:

```python
"""Effort tracking: submit carries effort_hours; summation rolls it up."""
import pytest
from sqlalchemy import select

from tests.conftest import advance_to_assessment
from tests.test_change_scoping import create_change, add_item_and_lead


@pytest.mark.asyncio
async def test_effort_hours_persist_and_roll_up(client, admin_auth, seed, part,
                                                session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    await advance_to_assessment(client, admin_auth, session_factory, change["id"])
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=admin_auth)
    assessments = res.json()["assessments"]
    assert assessments, "kickoff must create assessment rows"
    dept_id = assessments[0]["department_id"]
    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments",
        json={"department_id": dept_id, "verdict": "feasible",
              "effort_hours": 2.5, "notes": "quick check"},
        headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["effort_hours"] == 2.5
    res = await client.get(f"/api/v1/changes/{change['id']}/summation",
                           headers=admin_auth)
    body = res.json()
    assert body["total_effort_hours"] == 2.5
    assert {"department_id": dept_id, "effort_hours": 2.5} in body["effort_by_department"]


@pytest.mark.asyncio
async def test_negative_effort_rejected(client, admin_auth, seed, part,
                                        session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    await advance_to_assessment(client, admin_auth, session_factory, change["id"])
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=admin_auth)
    dept_id = res.json()["assessments"][0]["department_id"]
    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments",
        json={"department_id": dept_id, "verdict": "feasible", "effort_hours": -1},
        headers=admin_auth)
    assert res.status_code == 422
```

Note: submitting as admin passes the department-membership guard on linked engine tasks (`WorkflowService.complete_task` allows admin). If the first test's submit returns 400 for a membership reason, submit for a department the admin belongs to instead or add the admin to the department via `UserDepartment` — check `tests/test_change_kickoff.py` for the established pattern and mirror it.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_assessment_effort.py -x -q`
Expected: FAIL — `effort_hours` not accepted/echoed.

- [ ] **Step 3: Implement**

`schemas/change.py` — `AssessmentSubmit` add:

```python
    effort_hours: Optional[float] = Field(None, ge=0)
```

`AssessmentResponse` add `effort_hours: Optional[float] = None` and add `"effort_hours"` to the verbatim-copy tuple inside `_read_through` (the tuple listing `"id", "department_id", ...`).

`change_service.submit_assessment` — add keyword `effort_hours=None` to the signature and `a.effort_hours = effort_hours` next to the other field writes (line 1071 area).

`changes.py submit_assessment` endpoint — pass `effort_hours=body.effort_hours`.

`cost_service.summation` — import `func` is already available (`from sqlalchemy import select, func` — check header, add if missing); before the `return`:

```python
        efforts = (await session.execute(
            select(ChangeAssessment.department_id,
                   func.coalesce(func.sum(ChangeAssessment.effort_hours), 0.0))
            .where(ChangeAssessment.change_id == change.id,
                   ChangeAssessment.effort_hours.is_not(None))
            .group_by(ChangeAssessment.department_id))).all()
```

and extend the returned dict:

```python
            "effort_by_department": [
                {"department_id": d, "effort_hours": h} for d, h in sorted(efforts)],
            "total_effort_hours": float(sum(h for _, h in efforts)),
```

`schemas/change.py` — add and wire:

```python
class EffortRollup(BaseModel):
    department_id: int
    effort_hours: float
```

`SummationResponse` add:

```python
    effort_by_department: List[EffortRollup] = []
    total_effort_hours: float = 0.0
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python3 -m pytest tests/test_assessment_effort.py tests/test_change_cost.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/change.py backend/app/services/change_service.py \
        backend/app/services/cost_service.py backend/app/api/v1/changes/changes.py \
        backend/tests/test_assessment_effort.py
git commit -m "feat(effort): effort_hours on assessment submit + summation rollup"
```

---

### Task 6: Internal cost approval endpoint

**Files:**
- Modify: `backend/app/services/change_service.py` (new `approve_internal_costs`)
- Modify: `backend/app/schemas/change.py` (`InternalApprovalIn`, `ChangeResponse` fields)
- Modify: `backend/app/api/v1/changes/changes.py` (endpoint)
- Test: `backend/tests/test_internal_approval.py`

**Interfaces:**
- Consumes: `internal_approved_*` columns (Task 1), hard gate in `transition` (Task 2), `MeetingService.user_is_pm` (Task 3), `CostService.summation` (Task 5 shape).
- Produces: `ChangeService.approve_internal_costs(session, change, actor, *, note=None) -> ChangeRequest`; `POST /api/v1/changes/{id}/internal-approval {note?}` → `ChangeResponse`; `ChangeResponse.internal_approved_by/at/amount/approval_note`.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_internal_approval.py`:

```python
"""Internal costing branch: PM approves the summation total, no quote step."""
import pytest
from sqlalchemy import update

from tests.conftest import login, ENGINEER_PASSWORD, advance_to_assessment
from tests.test_change_scoping import create_change, add_item_and_lead


async def to_costing(session_factory, change_id):
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(
            ChangeRequest.id == change_id).values(status="costing"))
        await s.commit()


@pytest.mark.asyncio
async def test_internal_approval_snapshots_amount_and_unblocks_approved(
        client, admin_auth, seed, part, session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    await advance_to_assessment(client, admin_auth, session_factory, change["id"])
    await to_costing(session_factory, change["id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/internal-approval",
                            json={"note": "budget ok"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["internal_approved_by"] == seed["admin_id"]
    assert body["internal_approved_amount"] is not None  # summation snapshot (0.0 with no cost lines)
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "approved"}, headers=admin_auth)
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_internal_approval_guards(client, admin_auth, seed, part,
                                        session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    # wrong status
    res = await client.post(f"/api/v1/changes/{change['id']}/internal-approval",
                            json={}, headers=admin_auth)
    assert res.status_code == 400
    # customer-relevant change refuses internal approval
    await client.patch(f"/api/v1/changes/{change['id']}",
                       json={"customer_relevant": True}, headers=admin_auth)
    await to_costing(session_factory, change["id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/internal-approval",
                            json={}, headers=admin_auth)
    assert res.status_code == 400
    # non-PM engineer refused on an internal change
    change2 = await create_change(client, admin_auth, seed["project_id"],
                                  lead_id=seed["admin_id"])
    await to_costing(session_factory, change2["id"])
    eng_auth = await login(client, "eng@test.io", ENGINEER_PASSWORD)
    res = await client.post(f"/api/v1/changes/{change2['id']}/internal-approval",
                            json={}, headers=eng_auth)
    assert res.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_internal_approval.py -x -q`
Expected: FAIL with 404 (endpoint missing).

- [ ] **Step 3: Implement**

`change_service.py` — add after `sign_off` (line 1316):

```python
    @staticmethod
    async def approve_internal_costs(
        session: AsyncSession, change: ChangeRequest, actor: User,
        *, note: Optional[str] = None,
    ) -> ChangeRequest:
        """Internal costing branch: PM approves the summation total instead of
        a customer quote. Amount is snapshotted for the later P&L view."""
        from app.services.meeting_service import MeetingService
        if change.customer_relevant:
            raise ChangeError(
                "Customer-relevant changes are approved via the customer quote")
        if change.status != "costing":
            raise ChangeError("Internal cost approval happens in 'costing'")
        if actor.id != change.lead_id and not await MeetingService.user_is_pm(
                session, actor):
            raise ChangeError(
                "Only Project Management, the change lead, or an admin "
                "may approve internal costs")
        from app.services.cost_service import CostService
        summ = await CostService.summation(session, change)
        change.internal_approved_by = actor.id
        change.internal_approved_at = datetime.utcnow()
        change.internal_approved_amount = summ["totals"]["grand_total"]
        change.internal_approval_note = note
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "internal_costs_approved",
            f"Internal costs approved ({summ['totals']['grand_total']:.2f})",
            actor.id, field_name="internal_approved_amount",
            new_value=summ["totals"]["grand_total"], notes=note)
        return change
```

`schemas/change.py` — add `class InternalApprovalIn(BaseModel): note: Optional[str] = None`; on `ChangeResponse` add:

```python
    internal_approved_by: Optional[int] = None
    internal_approved_at: Optional[datetime] = None
    internal_approved_amount: Optional[float] = None
    internal_approval_note: Optional[str] = None
```

`changes.py` — endpoint (import `InternalApprovalIn`):

```python
@router.post("/{change_id}/internal-approval", response_model=ChangeResponse)
async def approve_internal_costs(
    change_id: int, body: InternalApprovalIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await ChangeService.approve_internal_costs(
            db, change, current_user, note=body.note)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    change.deadline_state = await ChangeService.deadline_state(db, change)
    return change
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python3 -m pytest tests/test_internal_approval.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/change_service.py backend/app/schemas/change.py \
        backend/app/api/v1/changes/changes.py backend/tests/test_internal_approval.py
git commit -m "feat(costing): internal cost approval endpoint (PM), amount snapshot for P&L"
```

---

### Task 7: Deadline backend fixes **[mechanical]**

**Files:**
- Modify: `backend/app/api/v1/changes/changes.py:575-597` (PATCH recomputes `deadline_state`)
- Modify: `backend/app/services/change_service.py:1233-1246` (reason preservation)
- Test: `backend/tests/test_change_deadline.py` (extend)

**Interfaces:**
- Produces: PATCH `/v1/changes/{id}` response carries a fresh `deadline_state`; a PATCH sending `required_by_date` WITHOUT `required_by_reason` leaves the stored reason untouched; sending an explicit `required_by_reason` (incl. null) still writes it.

- [ ] **Step 1: Write failing tests** (append to `backend/tests/test_change_deadline.py`, reuse its existing change-creation helper/fixtures — read the file first and match its style):

```python
@pytest.mark.asyncio
async def test_patch_response_recomputes_deadline_state(client, admin_auth, seed):
    # create a change (mirror this file's existing creation helper)
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "deadline", "change_type": "physical_part",
    }, headers=admin_auth)
    change_id = res.json()["id"]
    from datetime import datetime, timedelta
    future = (datetime.utcnow() + timedelta(days=30)).isoformat()
    res = await client.patch(f"/api/v1/changes/{change_id}",
                             json={"required_by_date": future,
                                   "required_by_reason": "customer SOP"},
                             headers=admin_auth)
    assert res.status_code == 200
    assert res.json()["deadline_state"] == "on_track"   # was null before the fix


@pytest.mark.asyncio
async def test_patch_date_only_keeps_reason(client, admin_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "deadline2", "change_type": "physical_part",
    }, headers=admin_auth)
    change_id = res.json()["id"]
    from datetime import datetime, timedelta
    d1 = (datetime.utcnow() + timedelta(days=10)).isoformat()
    d2 = (datetime.utcnow() + timedelta(days=20)).isoformat()
    await client.patch(f"/api/v1/changes/{change_id}",
                       json={"required_by_date": d1, "required_by_reason": "SOP"},
                       headers=admin_auth)
    res = await client.patch(f"/api/v1/changes/{change_id}",
                             json={"required_by_date": d2}, headers=admin_auth)
    assert res.json()["required_by_reason"] == "SOP"    # was nulled before the fix
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_change_deadline.py -x -q`
Expected: the two new tests FAIL (`deadline_state` null; reason nulled).

- [ ] **Step 3: Implement**

`changes.py` PATCH handler — after the fresh re-query (line 596), before `return change`:

```python
    change.deadline_state = await ChangeService.deadline_state(db, change)
```

`change_service.update_change` deadline branch (lines 1233-1246) — replace:

```python
        if "required_by_date" in fields:
            new_date = fields.pop("required_by_date")
            reason = fields.pop("required_by_reason", None)
            old = change.required_by_date
            change.required_by_date = new_date
            change.required_by_reason = reason
```

with:

```python
        if "required_by_date" in fields:
            new_date = fields.pop("required_by_date")
            old = change.required_by_date
            change.required_by_date = new_date
            # Reason only changes when the request explicitly carries it —
            # a date-only PATCH must not wipe the stored justification.
            if "required_by_reason" in fields:
                change.required_by_reason = fields.pop("required_by_reason")
            reason = change.required_by_reason
```

(the trailing `notes=reason` in the changelog call keeps working with the local `reason`.)

- [ ] **Step 4: Run tests**

Run: `cd backend && python3 -m pytest tests/test_change_deadline.py -x -q`
Expected: PASS (all, including pre-existing).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/changes/changes.py backend/app/services/change_service.py \
        backend/tests/test_change_deadline.py
git commit -m "fix(deadline): PATCH returns fresh deadline_state; date-only PATCH keeps reason"
```

---

### Task 8: Frontend foundation — types, status maps, API client, labels **[mechanical]**

**Files:**
- Modify: `frontend/src/types/change.ts`
- Modify: `frontend/src/lib/changeStatus.ts`
- Modify: `frontend/src/api/changes.ts`
- Modify: `frontend/src/i18n/cmLabels.ts`

**Interfaces:**
- Produces: `ChangeStatus` includes `'scoping'`; `ChangeMeeting`/`MeetingParticipant` types; `Assessment.effort_hours`; `ChangeRequest.internal_approved_*`; `Summation.effort_by_department`/`total_effort_hours`; API methods `listMeetings`, `createMeeting`, `updateMeeting`, `decideMeeting`, `approveInternalCosts`; `submitAssessment` accepts `effort_hours`; label keys under `scoping.*`, `meeting.*`, `effort.*`, `internal.*`.

- [ ] **Step 1: types/change.ts**

Add `'scoping'` to the `ChangeStatus` union (after `'captured'`) and to `CHANGE_STATUS_ORDER` (index 1). Add to `Assessment`: `effort_hours?: number | null;`. Add to `ChangeRequest`:

```ts
  internal_approved_by?: number | null;
  internal_approved_at?: string | null;
  internal_approved_amount?: number | null;
  internal_approval_note?: string | null;
```

Add to `Summation`:

```ts
  effort_by_department: { department_id: number; effort_hours: number }[];
  total_effort_hours: number;
```

New types:

```ts
export interface MeetingParticipant { name: string; user_id?: number | null }

export interface ChangeMeeting {
  id: number;
  change_id: number;
  meeting_date: string;
  participants: MeetingParticipant[];
  notes: string | null;
  decision: 'proceed' | 'reject' | 'needs_info' | null;
  selected_department_ids: number[];
  created_by: number;
  created_at: string;
  decided_by: number | null;
  decided_at: string | null;
}
```

- [ ] **Step 2: lib/changeStatus.ts**

```ts
STATUS_LABELS: add  scoping: 'Scoping',
NEXT_STATUS:  captured: ['scoping'],
              scoping: ['in_assessment', 'rejected'],
              costing: ['quoted', 'approved'],
STATUS_PILL:  add  scoping: 'bg-violet-900 text-violet-200',
```

- [ ] **Step 3: api/changes.ts**

```ts
  listMeetings: (id: number) =>
    client.get<ChangeMeeting[]>(`/v1/changes/${id}/meetings`).then((r) => r.data),
  createMeeting: (id: number, body: {
    meeting_date?: string; participants: MeetingParticipant[];
    notes?: string; selected_department_ids: number[];
  }) => client.post<ChangeMeeting>(`/v1/changes/${id}/meetings`, body).then((r) => r.data),
  updateMeeting: (id: number, meetingId: number, body: Record<string, unknown>) =>
    client.patch<ChangeMeeting>(`/v1/changes/${id}/meetings/${meetingId}`, body).then((r) => r.data),
  decideMeeting: (id: number, meetingId: number, decision: 'proceed' | 'reject' | 'needs_info') =>
    client.post<ChangeMeeting>(`/v1/changes/${id}/meetings/${meetingId}/decide`, { decision }).then((r) => r.data),
  approveInternalCosts: (id: number, note?: string) =>
    client.post<ChangeRequest>(`/v1/changes/${id}/internal-approval`, { note: note ?? null }).then((r) => r.data),
```

Extend `submitAssessment`'s body type with `effort_hours?: number`. Import the new types.

- [ ] **Step 4: cmLabels.ts** — add keys (DE first value, EN second, matching the file's `Record<Lang, string>` shape):

```ts
  'scoping.title': { de: 'Vorabklärung', en: 'Scoping' },
  'scoping.newMeeting': { de: 'Meeting erfassen', en: 'Record meeting' },
  'meeting.date': { de: 'Datum', en: 'Date' },
  'meeting.participants': { de: 'Teilnehmer', en: 'Participants' },
  'meeting.participantsHint': { de: 'Namen, durch Komma getrennt', en: 'Names, comma-separated' },
  'meeting.notes': { de: 'Protokoll', en: 'Meeting notes' },
  'meeting.departments': { de: 'Betroffene Abteilungen', en: 'Impacted departments' },
  'meeting.decision': { de: 'Entscheidung', en: 'Decision' },
  'meeting.proceed': { de: 'Freigeben & Bewertung starten', en: 'Proceed & start assessment' },
  'meeting.reject': { de: 'Ablehnen', en: 'Reject' },
  'meeting.needsInfo': { de: 'Weitere Infos nötig', en: 'Needs more info' },
  'meeting.decided': { de: 'Entschieden', en: 'Decided' },
  'meeting.none': { de: 'Noch kein Meeting erfasst.', en: 'No meeting recorded yet.' },
  'effort.hours': { de: 'Aufwand (Std.)', en: 'Effort (hours)' },
  'effort.total': { de: 'Bewertungsaufwand gesamt', en: 'Total assessment effort' },
  'assessment.submit': { de: 'Bewertung abgeben', en: 'Submit assessment' },
  'assessment.verdict': { de: 'Ergebnis', en: 'Verdict' },
  'internal.approve': { de: 'Interne Kosten freigeben', en: 'Approve internal costs' },
  'internal.approved': { de: 'Interne Kosten freigegeben', en: 'Internal costs approved' },
  'internal.note': { de: 'Anmerkung', en: 'Note' },
  'internal.amount': { de: 'Freigegebener Betrag', en: 'Approved amount' },
```

- [ ] **Step 5: Typecheck + commit**

Run: `cd frontend && npx tsc -b 2>&1 | tail -5` — no NEW errors vs. baseline.

```bash
git add frontend/src/types/change.ts frontend/src/lib/changeStatus.ts \
        frontend/src/api/changes.ts frontend/src/i18n/cmLabels.ts
git commit -m "feat(frontend): scoping/meeting/effort/internal-approval types, api, labels"
```

---

### Task 9: ScopingPanel (meeting module UI) + cockpit branch filtering

**Files:**
- Create: `frontend/src/components/changes/ScopingPanel.tsx`
- Modify: `frontend/src/pages/ChangeDetailPage.tsx` (tab `scoping`)
- Modify: `frontend/src/components/changes/CockpitSummary.tsx` (branch-aware next actions)
- Test: `frontend/src/components/changes/ScopingPanel.test.tsx`

**Interfaces:**
- Consumes: `changesApi.listMeetings/createMeeting/decideMeeting` and labels (Task 8); `useDepartments()` from `../../hooks/queries/useWorkflows`.
- Produces: `<ScopingPanel changeId={number} status={ChangeStatus} />` rendered in a new `scoping` tab; on `proceed` the change refetch shows `in_assessment`.

- [ ] **Step 1: Write component test**

Create `frontend/src/components/changes/ScopingPanel.test.tsx` (mirror the setup style of `DeadlineChip.test.tsx` — read it first; wrap in a `QueryClientProvider`, mock `../../api/changes` and `../../hooks/queries/useWorkflows` with `vi.mock`):

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ScopingPanel from './ScopingPanel'

vi.mock('../../api/changes', () => ({
  changesApi: {
    listMeetings: vi.fn().mockResolvedValue([{
      id: 1, change_id: 7, meeting_date: '2026-07-04T10:00:00Z',
      participants: [{ name: 'PM Jane' }], notes: 'scope ok',
      decision: 'needs_info', selected_department_ids: [2],
      created_by: 1, created_at: '2026-07-04T10:00:00Z',
      decided_by: 1, decided_at: '2026-07-04T11:00:00Z',
    }]),
    createMeeting: vi.fn(), decideMeeting: vi.fn(),
  },
}))
vi.mock('../../hooks/queries/useWorkflows', () => ({
  useDepartments: () => ({ data: [{ id: 2, name: 'Quality' }] }),
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe('ScopingPanel', () => {
  it('lists recorded meetings with their decision', async () => {
    render(wrap(<ScopingPanel changeId={7} status="scoping" />))
    expect(await screen.findByText(/PM Jane/)).toBeInTheDocument()
    expect(screen.getByText(/needs more info/i)).toBeInTheDocument()
  })
  it('offers the create form while scoping is open', async () => {
    render(wrap(<ScopingPanel changeId={7} status="scoping" />))
    expect(await screen.findByText(/record meeting/i)).toBeInTheDocument()
  })
})
```

Run: `cd frontend && npx vitest run src/components/changes/ScopingPanel.test.tsx`
Expected: FAIL (component missing).

- [ ] **Step 2: Implement `ScopingPanel.tsx`**

```tsx
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { useDepartments } from '../../hooks/queries/useWorkflows'
import { t } from '../../i18n/cmLabels'
import type { ChangeStatus, ChangeMeeting } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const DECISION_LABEL: Record<string, string> = {
  proceed: t('meeting.proceed'), reject: t('meeting.reject'),
  needs_info: t('meeting.needsInfo'),
}

export default function ScopingPanel({ changeId, status }: {
  changeId: number; status: ChangeStatus
}) {
  const qc = useQueryClient()
  const { data: meetings = [] } = useQuery({
    queryKey: ['change-meetings', changeId],
    queryFn: () => changesApi.listMeetings(changeId),
  })
  const { data: departments = [] } = useDepartments()

  const [date, setDate] = useState('')
  const [participants, setParticipants] = useState('')
  const [notes, setNotes] = useState('')
  const [deptIds, setDeptIds] = useState<number[]>([])

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['change-meetings', changeId] })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
  }
  const create = useMutation({
    mutationFn: () => changesApi.createMeeting(changeId, {
      meeting_date: date ? `${date}T12:00:00Z` : undefined,
      participants: participants.split(',').map((n) => n.trim())
        .filter(Boolean).map((name) => ({ name })),
      notes: notes || undefined,
      selected_department_ids: deptIds,
    }),
    onSuccess: () => { setNotes(''); setParticipants(''); invalidate() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not record the meeting'),
  })
  const decide = useMutation({
    mutationFn: (vars: { meetingId: number; decision: 'proceed' | 'reject' | 'needs_info' }) =>
      changesApi.decideMeeting(changeId, vars.meetingId, vars.decision),
    onSuccess: invalidate,
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Decision failed'),
  })

  const open = status === 'captured' || status === 'scoping'
  const toggleDept = (id: number) => setDeptIds((prev) =>
    prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id])

  return (
    <div className="space-y-4 text-sm">
      <ul className="divide-y divide-slate-700 border border-slate-700 rounded-lg">
        {meetings.map((m: ChangeMeeting) => (
          <li key={m.id} className="p-3 space-y-1">
            <div className="flex justify-between items-center">
              <span className="text-slate-200">
                {new Date(m.meeting_date).toLocaleDateString()} — {' '}
                {m.participants.map((p) => p.name).join(', ') || '—'}
              </span>
              {m.decision ? (
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-200">
                  {DECISION_LABEL[m.decision] ?? m.decision}
                </span>
              ) : open && (
                <span className="flex gap-2">
                  <button className="bg-emerald-700 hover:bg-emerald-600 text-white px-2.5 py-1 rounded text-xs"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ meetingId: m.id, decision: 'proceed' })}>
                    {t('meeting.proceed')}
                  </button>
                  <button className="bg-amber-700 hover:bg-amber-600 text-white px-2.5 py-1 rounded text-xs"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ meetingId: m.id, decision: 'needs_info' })}>
                    {t('meeting.needsInfo')}
                  </button>
                  <button className="bg-red-800 hover:bg-red-700 text-white px-2.5 py-1 rounded text-xs"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ meetingId: m.id, decision: 'reject' })}>
                    {t('meeting.reject')}
                  </button>
                </span>
              )}
            </div>
            {m.notes && <p className="text-slate-400 whitespace-pre-wrap">{m.notes}</p>}
            {m.selected_department_ids.length > 0 && (
              <p className="text-xs text-slate-500">
                {t('meeting.departments')}: {m.selected_department_ids.map((id) =>
                  departments.find((d) => d.id === id)?.name ?? `#${id}`).join(', ')}
              </p>
            )}
          </li>
        ))}
        {meetings.length === 0 && (
          <li className="p-3 text-slate-400">{t('meeting.none')}</li>
        )}
      </ul>

      {open && (
        <div className="border border-slate-700 rounded-lg p-4 space-y-3">
          <h3 className="text-xs uppercase tracking-wide text-slate-500">{t('scoping.newMeeting')}</h3>
          <div className="flex flex-wrap gap-3">
            <div>
              <label className="block text-xs text-slate-500 mb-1">{t('meeting.date')}</label>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
            </div>
            <div className="flex-1 min-w-[14rem]">
              <label className="block text-xs text-slate-500 mb-1">
                {t('meeting.participants')} <span className="opacity-60">({t('meeting.participantsHint')})</span>
              </label>
              <input type="text" value={participants} onChange={(e) => setParticipants(e.target.value)}
                className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
            </div>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">{t('meeting.notes')}</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={4}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">{t('meeting.departments')}</label>
            <div className="flex flex-wrap gap-2">
              {departments.map((d) => (
                <button key={d.id} type="button" onClick={() => toggleDept(d.id)}
                  className={`px-2.5 py-1 rounded-full text-xs border ${deptIds.includes(d.id)
                    ? 'bg-sky-600 text-white border-sky-500'
                    : 'bg-slate-900 text-slate-300 border-slate-600'}`}>
                  {d.name}
                </button>
              ))}
            </div>
          </div>
          <button
            className="bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-1.5 rounded-lg text-sm disabled:opacity-50"
            disabled={create.isPending}
            onClick={() => create.mutate()}>
            {t('scoping.newMeeting')}
          </button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Wire the tab + cockpit filtering**

`ChangeDetailPage.tsx`: extend the `Tab` union and `TABS` array with `'scoping'` (position it right after `'overview'`); import and render:

```tsx
      {tab === 'scoping' && change && (
        <ScopingPanel changeId={change.id} status={change.status} />
      )}
```

Tab label: in the tab bar render, map `scoping` to `t('scoping.title')` (same pattern as `implementation`).

`CockpitSummary.tsx:20` — make next actions branch-aware:

```tsx
  const next = (NEXT_STATUS[change.status] ?? []).filter((s) =>
    change.status !== 'costing'
      ? true
      : (change.customer_relevant ? s !== 'approved' : s !== 'quoted'))
```

- [ ] **Step 4: Run tests + typecheck**

Run: `cd frontend && npx vitest run && npx tsc -b 2>&1 | tail -5`
Expected: vitest PASS; no new tsc errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/changes/ScopingPanel.tsx \
        frontend/src/components/changes/ScopingPanel.test.tsx \
        frontend/src/pages/ChangeDetailPage.tsx \
        frontend/src/components/changes/CockpitSummary.tsx
git commit -m "feat(frontend): scoping tab with meeting module; branch-aware cockpit next actions"
```

---

### Task 10: Assessment submit form (with effort) + summation effort display

**Files:**
- Create: `frontend/src/components/changes/AssessmentSubmitForm.tsx`
- Modify: `frontend/src/pages/ChangeDetailPage.tsx` (assessments tab)
- Modify: `frontend/src/components/changes/SummationView.tsx` (effort rows)
- Test: `frontend/src/components/changes/AssessmentSubmitForm.test.tsx`

**Interfaces:**
- Consumes: `changesApi.submitAssessment` with `effort_hours` (Task 8); backend effort rollup (Task 5).
- Produces: `<AssessmentSubmitForm changeId department_id departmentName onDone />` — verdict select (`feasible | feasible_with_conditions | not_feasible`), required effort-hours number input (min 0, step 0.25), conditions (shown when verdict is conditional), notes; submit disabled until a verdict is chosen and effort entered.

- [ ] **Step 1: Component test** (mirror ScopingPanel test mocking style)

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AssessmentSubmitForm from './AssessmentSubmitForm'

const submitAssessment = vi.fn().mockResolvedValue({})
vi.mock('../../api/changes', () => ({
  changesApi: { submitAssessment: (...a: unknown[]) => submitAssessment(...a) },
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe('AssessmentSubmitForm', () => {
  it('requires effort hours before submitting', async () => {
    render(wrap(<AssessmentSubmitForm changeId={7} departmentId={2}
      departmentName="Quality" onDone={() => {}} />))
    fireEvent.change(screen.getByLabelText(/verdict/i), { target: { value: 'feasible' } })
    expect(screen.getByRole('button', { name: /submit assessment/i })).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/effort/i), { target: { value: '3.5' } })
    fireEvent.click(screen.getByRole('button', { name: /submit assessment/i }))
    await waitFor(() => expect(submitAssessment).toHaveBeenCalledWith(7,
      expect.objectContaining({ department_id: 2, verdict: 'feasible', effort_hours: 3.5 })))
  })
})
```

Run: `cd frontend && npx vitest run src/components/changes/AssessmentSubmitForm.test.tsx` → FAIL.

- [ ] **Step 2: Implement the form**

```tsx
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const VERDICTS = ['feasible', 'feasible_with_conditions', 'not_feasible'] as const

export default function AssessmentSubmitForm({ changeId, departmentId, departmentName, onDone }: {
  changeId: number; departmentId: number; departmentName: string; onDone: () => void
}) {
  const qc = useQueryClient()
  const [verdict, setVerdict] = useState('')
  const [effort, setEffort] = useState('')
  const [conditions, setConditions] = useState('')
  const [notes, setNotes] = useState('')
  const submit = useMutation({
    mutationFn: () => changesApi.submitAssessment(changeId, {
      department_id: departmentId, verdict,
      effort_hours: parseFloat(effort),
      conditions: conditions || undefined, notes: notes || undefined,
    }),
    onSuccess: () => {
      toast.success(`${departmentName}: ${verdict}`)
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change-routing', changeId] })
      onDone()
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Submit failed'),
  })
  const ready = verdict !== '' && effort !== '' && parseFloat(effort) >= 0
  return (
    <div className="border border-slate-700 rounded-lg p-3 space-y-2 text-sm">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={`verdict-${departmentId}`} className="block text-xs text-slate-500 mb-1">
            {t('assessment.verdict')}
          </label>
          <select id={`verdict-${departmentId}`} value={verdict}
            onChange={(e) => setVerdict(e.target.value)}
            className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100">
            <option value="">—</option>
            {VERDICTS.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor={`effort-${departmentId}`} className="block text-xs text-slate-500 mb-1">
            {t('effort.hours')}
          </label>
          <input id={`effort-${departmentId}`} type="number" min="0" step="0.25"
            value={effort} onChange={(e) => setEffort(e.target.value)}
            className="w-28 bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
        </div>
      </div>
      {verdict === 'feasible_with_conditions' && (
        <input type="text" placeholder={t('conditions') === 'conditions' ? 'Conditions' : t('conditions')}
          value={conditions} onChange={(e) => setConditions(e.target.value)}
          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
      )}
      <textarea rows={2} placeholder="Notes" value={notes}
        onChange={(e) => setNotes(e.target.value)}
        className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
      <button disabled={!ready || submit.isPending} onClick={() => submit.mutate()}
        className="bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-1.5 rounded-lg text-sm disabled:opacity-50">
        {t('assessment.submit')}
      </button>
    </div>
  )
}
```

- [ ] **Step 3: Wire into the assessments tab**

In `ChangeDetailPage.tsx` assessments tab (line 263-294 area): under each assessment list row whose `status === 'active'`, render an expand/collapse control (`useState<number | null>` for the open assessment id) showing `<AssessmentSubmitForm changeId={changeId} departmentId={a.department_id} departmentName={deptName(a.department_id)} onDone={() => setOpenAssessment(null)} />`. Keep the read-only list otherwise intact.

- [ ] **Step 4: SummationView effort display**

After the totals table in `SummationView.tsx`, add (types come from Task 8):

```tsx
      {data.total_effort_hours > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-300 mb-1">{t('effort.total')}</div>
          <table className="w-full text-xs">
            <tbody>
              {data.effort_by_department.map((row) => (
                <tr key={row.department_id} className="border-b border-slate-800">
                  <td className="py-0.5">Dept #{row.department_id}</td>
                  <td className="text-right tabular-nums">{row.effort_hours.toFixed(2)} h</td>
                </tr>
              ))}
              <tr className="font-semibold">
                <td>{t('total')}</td>
                <td className="text-right tabular-nums">{data.total_effort_hours.toFixed(2)} h</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
```

- [ ] **Step 5: Run tests + typecheck, commit**

Run: `cd frontend && npx vitest run && npx tsc -b 2>&1 | tail -5`

```bash
git add frontend/src/components/changes/AssessmentSubmitForm.tsx \
        frontend/src/components/changes/AssessmentSubmitForm.test.tsx \
        frontend/src/pages/ChangeDetailPage.tsx \
        frontend/src/components/changes/SummationView.tsx
git commit -m "feat(frontend): assessment submit form with required effort hours; summation effort rollup"
```

---

### Task 11: Internal approval UI + gates panel renders actual gates **[mechanical]**

**Files:**
- Modify: `frontend/src/pages/ChangeDetailPage.tsx` (commercial tab branch)
- Modify: `frontend/src/components/changes/D1MasterPanel.tsx` (gates from query, not fixed list)

**Interfaces:**
- Consumes: `changesApi.approveInternalCosts` (Task 8), `internal_approved_*` on `ChangeRequest`.
- Produces: commercial tab shows the internal-approval block for `!customer_relevant` changes (button in `costing`, approved summary afterwards) instead of quote/customer-response controls; D1 gate list shows only gates that exist on the change.

- [ ] **Step 1: Commercial tab branch**

In `ChangeDetailPage.tsx`, add the mutation next to the others:

```tsx
  const internalApprove = useMutation({
    mutationFn: (note?: string) => changesApi.approveInternalCosts(changeId, note),
    onSuccess: () => {
      toast.success(t('internal.approved'))
      qc.invalidateQueries({ queryKey: ['change', changeId] })
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Approval failed'),
  })
```

In the commercial tab JSX, wrap the existing quote/customer-response/sign-off block in `{change.customer_relevant ? ( ...existing... ) : ( ...internal block... )}` where the internal block is:

```tsx
        <div className="space-y-2">
          {change.internal_approved_at ? (
            <div className="border border-emerald-800 bg-emerald-950/40 rounded-lg p-3">
              <p className="text-emerald-300 font-medium">✓ {t('internal.approved')}</p>
              <p className="text-xs text-slate-400 mt-1">
                {t('internal.amount')}: {change.internal_approved_amount?.toFixed(2) ?? '—'}
                {' · '}{new Date(change.internal_approved_at).toLocaleDateString()}
              </p>
              {change.internal_approval_note && (
                <p className="text-xs text-slate-400">{change.internal_approval_note}</p>
              )}
            </div>
          ) : (
            <button
              className="bg-emerald-700 hover:bg-emerald-600 text-white font-semibold px-4 py-2 rounded-lg text-sm disabled:opacity-50"
              disabled={change.status !== 'costing' || internalApprove.isPending}
              onClick={() => internalApprove.mutate(undefined)}>
              {t('internal.approve')}
            </button>
          )}
        </div>
```

- [ ] **Step 2: D1MasterPanel gate list**

Replace the fixed `GATES` iteration (`D1MasterPanel.tsx:216 {GATES.map(...)}`) with iteration over the fetched gates themselves: `{gates.map((g) => { const key = g.gate_key; ... })}` (delete the `const GATES: GateKey[] = [...]` constant and the `byKey[key]` lookup — `g` is already in hand; keep the decide mutation and per-gate render logic identical). New changes then show only `release`; legacy changes still show their historical rows.

- [ ] **Step 3: Typecheck + vitest, commit**

Run: `cd frontend && npx vitest run && npx tsc -b 2>&1 | tail -5`

```bash
git add frontend/src/pages/ChangeDetailPage.tsx frontend/src/components/changes/D1MasterPanel.tsx
git commit -m "feat(frontend): internal cost approval in commercial tab; D1 renders existing gates only"
```

---

### Task 12: Deadline editor in cockpit header + date-only semantics

**Files:**
- Create: `frontend/src/components/changes/DeadlineEditor.tsx`
- Modify: `frontend/src/components/changes/CockpitSummary.tsx` (use editor in "Where" card)
- Modify: `frontend/src/pages/ChangeDetailPage.tsx` (remove overview deadline block + its state/mutation)
- Modify: `frontend/src/components/changes/DeadlineChip.test.tsx` (same-day case)

**Interfaces:**
- Consumes: `changesApi.update` PATCH (fixed in Task 7 to return fresh `deadline_state`).
- Produces: `<DeadlineEditor change={ChangeRequest} />` — renders the existing `DeadlineChip` plus an edit toggle (date + reason + save/clear); sends `required_by_date` as `` `${date}T23:59:59Z` `` (end-of-day UTC) so picking today is never instantly overdue; clearing sends `null` for both fields.

- [ ] **Step 1: Write the same-day chip test** (append to `DeadlineChip.test.tsx`, matching its existing render/setup style):

```tsx
  it('does not show a same-day end-of-day deadline as overdue-negative', () => {
    const today = new Date()
    const iso = `${today.toISOString().slice(0, 10)}T23:59:59Z`
    render(<DeadlineChip date={iso} state="on_track" />)
    const chip = screen.getByTestId('deadline-chip')
    expect(chip.textContent).not.toMatch(/over/)
  })
```

- [ ] **Step 2: Implement `DeadlineEditor.tsx`**

```tsx
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { DeadlineChip } from './DeadlineChip'
import { t } from '../../i18n/cmLabels'
import type { ChangeRequest } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

export function DeadlineEditor({ change }: { change: ChangeRequest }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [date, setDate] = useState(change.required_by_date?.slice(0, 10) ?? '')
  const [reason, setReason] = useState(change.required_by_reason ?? '')
  const save = useMutation({
    mutationFn: (body: { required_by_date: string | null; required_by_reason: string | null }) =>
      changesApi.update(change.id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change', change.id] })
      toast.success('Deadline saved')
      setOpen(false)
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Failed to save deadline'),
  })
  return (
    <span className="inline-flex items-center gap-1.5">
      <DeadlineChip date={change.required_by_date} state={change.deadline_state} />
      <button type="button" title={t('deadline.set')} data-testid="deadline-edit"
        onClick={() => setOpen((o) => !o)}
        className="text-xs text-slate-400 hover:text-slate-200 underline decoration-dotted underline-offset-2">
        {change.required_by_date ? '✎' : `+ ${t('deadline.title')}`}
      </button>
      {open && (
        <span className="flex flex-wrap items-center gap-2 ml-1">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
            className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
          <input type="text" value={reason} placeholder={t('deadline.reason')}
            onChange={(e) => setReason(e.target.value)}
            className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 w-40" />
          <button className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
            disabled={save.isPending}
            onClick={() => save.mutate({
              // End-of-day UTC: picking *today* must not render as overdue.
              required_by_date: date ? `${date}T23:59:59Z` : null,
              required_by_reason: reason || null,
            })}>
            {t('deadline.set')}
          </button>
        </span>
      )}
    </span>
  )
}
```

- [ ] **Step 3: Wire into CockpitSummary, remove overview block**

`CockpitSummary.tsx`: replace `<DeadlineChip date={change.required_by_date} state={change.deadline_state} />` (line 78) with `<DeadlineEditor change={change} />` (import it; drop the now-unused `DeadlineChip` import if nothing else uses it here).

`ChangeDetailPage.tsx`: delete the overview-tab deadline block (lines 207-235), the `deadlineDate`/`deadlineReason` state, the `deadline` mutation, the sync `useEffect` (lines 108-125), and the now-unused `DeadlineChip` import.

- [ ] **Step 4: Run tests + typecheck**

Run: `cd frontend && npx vitest run && npx tsc -b 2>&1 | tail -5`
Expected: all PASS, no new tsc errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/changes/DeadlineEditor.tsx \
        frontend/src/components/changes/CockpitSummary.tsx \
        frontend/src/pages/ChangeDetailPage.tsx \
        frontend/src/components/changes/DeadlineChip.test.tsx
git commit -m "fix(deadline): editable deadline in cockpit header, end-of-day UTC date semantics"
```

---

### Task 13: Verification — full suites, Postgres migration dry-run, smoke

**Files:**
- No production code (fixes only if verification fails).

- [ ] **Step 1: Full backend suite**

Run: `cd backend && python3 -m pytest tests/ -q`
Expected: 0 failures.

- [ ] **Step 2: Frontend suite + tsc baseline**

Run: `cd frontend && npx vitest run && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: vitest 0 failures; tsc error count ≤ 21 (existing baseline).

- [ ] **Step 3: Postgres migration dry-run (001 → 031)**

Check `backend/alembic/env.py` for the database-URL env var it honors (this was exercised for 027–030 in commit `ff7ec0cd` — reuse the same mechanism), then:

```bash
docker run --rm -d --name plm-scratch-pg -e POSTGRES_PASSWORD=scratch \
  -e POSTGRES_DB=plm -p 55432:5432 postgres:16
sleep 5
cd backend && DATABASE_URL=postgresql+asyncpg://postgres:scratch@localhost:55432/plm \
  alembic upgrade head
docker rm -f plm-scratch-pg
```

Expected: chain runs `001 -> ... -> 031` with no error. (Adjust the env-var name to whatever env.py actually reads.)

- [ ] **Step 4: Runtime smoke**

Start the backend (`./run_backend.sh` or the project's documented command) against dev SQLite, then verify via curl (login first, mirror existing smoke habits): create change → record meeting with departments → decide proceed → change is `in_assessment` and stage-1 assessments match the selection → submit one assessment with `effort_hours` → summation shows effort. Fix anything found; re-run suites.

- [ ] **Step 5: Final commit (if fixes were needed) and report**

```bash
git add <only files changed by fixes>
git commit -m "test(path-to-quote): verification fixes"
```

Report: suite counts, tsc baseline number, migration dry-run result, smoke outcome.

---

## Out of scope (explicitly)

- Milestone 2: implementation-phase redesign, P&L report UI, approval threshold rules, meeting-invite notifications, user-picker for meeting participants (free-text names only for now).
- Adding a department to stage 1 that the routing template doesn't contain (use the existing routing-deviation mechanism).
