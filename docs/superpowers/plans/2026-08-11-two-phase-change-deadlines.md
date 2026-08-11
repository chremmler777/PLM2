# Two-Phase Change Deadlines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single change deadline with two phase-scoped ones: `required_by_*` becomes the quote deadline (customer-relevant only), and a new `release_due_*` deadline is set mandatorily at customer acceptance (Sales) or internal cost approval (PM).

**Architecture:** New columns on `change_requests` (release_due_* group + `quoted_at`), two pure model properties (`active_deadline`, `quoted_on_time`), and a phase-aware `ChangeService.deadline_state` that computes against whichever deadline is active. Acceptance/internal-approval endpoints require the release date. Frontend surfaces (cockpit banner, scoping panel, list, escalations, workload report) render the active deadline; `quoted` status shows a frozen quoted-on-time/late fact.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (SQLite), pytest-asyncio; React + TanStack Query + vitest/@testing-library.

**Spec:** `docs/superpowers/specs/2026-08-11-two-phase-change-deadlines-design.md`

## Global Constraints

- Alembic migrations are forward-only (`downgrade` = `pass`), SQLite-compatible: no `ADD COLUMN` with FK (FK lives in the ORM only), guard with column-existence checks — copy the pattern of `backend/alembic/versions/028_change_required_by.py`.
- Datetimes are stored naive UTC; request schemas use `NaiveUtcDatetime` (already defined in `backend/app/schemas/change.py`).
- Every deadline mutation gets a changelog row via `ChangeService.append_changelog` (pattern at `change_service.py:1457-1474`).
- Frontend dates sent as end-of-day UTC: `` `${date}T23:59:59Z` `` (pattern in `DeadlineEditor.tsx:54`).
- i18n: all new UI strings go through `t('...')` with `{de, en}` entries in `frontend/src/i18n/cmLabels.ts`.
- Backend tests: `cd backend && python -m pytest tests/<file> -v`. Frontend: `cd frontend && npx vitest run <file>`; full check `npx tsc --noEmit`.
- Commit after each task; message style `feat(changes): ...` / `test: ...` as in recent history.

---

### Task 1: Columns, model properties, schema fields

**Files:**
- Create: `backend/alembic/versions/040_release_deadline.py`
- Modify: `backend/app/models/change.py` (ChangeRequest class, after the `required_by_set_at` column at ~line 104; properties at the end of the class body)
- Modify: `backend/app/schemas/change.py` (ChangeUpdate ~line 47, CustomerResponseRequest ~line 57, InternalApprovalIn ~line 175, ChangeResponse ~line 207)
- Test: `backend/tests/test_change_deadline.py` (append)

**Interfaces:**
- Consumes: existing `TERMINAL_STATUSES`, `_mk_change` helper in the test file.
- Produces: ORM columns `ChangeRequest.quoted_at`, `.release_due_date`, `.release_due_reason`, `.release_due_set_by`, `.release_due_set_at` (all nullable); properties `ChangeRequest.active_deadline -> str | None` ("quote" | "release" | None) and `ChangeRequest.quoted_on_time -> bool | None`; schema fields listed below. Later tasks rely on these exact names.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_change_deadline.py`:

```python
@pytest.mark.asyncio
async def test_active_deadline_and_quoted_on_time(session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(
            session, seed, change_number="C-DL-P1", customer_relevant=True,
            required_by_date=datetime.utcnow() + timedelta(days=10))
        # quote deadline drives the pre-quoted phase
        assert chg.active_deadline == "quote"
        assert chg.quoted_on_time is None
        # quoting on time freezes the fact and retires the quote deadline
        chg.quoted_at = datetime.utcnow()
        assert chg.active_deadline is None
        assert chg.quoted_on_time is True
        # a late quote reads as late
        chg.quoted_at = chg.required_by_date + timedelta(days=3)
        assert chg.quoted_on_time is False
        # once a release deadline exists it takes over
        chg.release_due_date = datetime.utcnow() + timedelta(days=40)
        assert chg.active_deadline == "release"
        # terminal statuses have no active deadline
        chg.status = "released"
        assert chg.active_deadline is None


@pytest.mark.asyncio
async def test_internal_change_has_no_quote_deadline(session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(
            session, seed, change_number="C-DL-P2", customer_relevant=False,
            required_by_date=datetime.utcnow() + timedelta(days=10))
        assert chg.active_deadline is None
        chg.release_due_date = datetime.utcnow() + timedelta(days=30)
        assert chg.active_deadline == "release"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_change_deadline.py -k "active_deadline or no_quote" -v`
Expected: FAIL — `ChangeRequest` has no attribute `quoted_at` / `active_deadline`.

- [ ] **Step 3: Add columns and properties to the model**

In `backend/app/models/change.py`, directly below `required_by_set_at`:

```python
    # Two-phase deadlines: required_by_* is the QUOTE deadline (customer-
    # relevant changes only); release_due_* is the RELEASE deadline, set at
    # customer acceptance (Sales) or internal cost approval (PM). quoted_at
    # freezes the quote-milestone moment (same pattern as released_at).
    quoted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    release_due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    release_due_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_due_set_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    release_due_set_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

At the end of the `ChangeRequest` class body:

```python
    @property
    def active_deadline(self) -> str | None:
        """Which deadline currently drives deadline_state: 'quote' until the
        change is quoted (customer-relevant only), 'release' once a release
        deadline exists, None otherwise (incl. terminal statuses)."""
        if self.status in TERMINAL_STATUSES:
            return None
        if self.release_due_date is not None:
            return "release"
        if (self.customer_relevant and self.required_by_date is not None
                and self.quoted_at is None):
            return "quote"
        return None

    @property
    def quoted_on_time(self) -> bool | None:
        """Frozen once quoted: was the quote deadline met? None while not yet
        quoted or when no quote deadline was ever set."""
        if self.quoted_at is None or self.required_by_date is None:
            return None
        return self.quoted_at <= self.required_by_date
```

- [ ] **Step 4: Write the migration**

Create `backend/alembic/versions/040_release_deadline.py`:

```python
"""040: two-phase deadlines — release_due_* group + quoted_at on change_requests.

required_by_* is reinterpreted as the quote deadline (customer-relevant
changes only); release_due_* is the release deadline set at customer
acceptance or internal cost approval. quoted_at freezes the moment the
change reached 'quoted' so the quoted-on-time fact never needs a
changelog query. Spec: docs/superpowers/specs/2026-08-11-two-phase-
change-deadlines-design.md
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("change_requests")}
    if "quoted_at" not in cols:
        op.add_column("change_requests",
                      sa.Column("quoted_at", sa.DateTime(), nullable=True))
    if "release_due_date" not in cols:
        op.add_column("change_requests",
                      sa.Column("release_due_date", sa.DateTime(), nullable=True))
    if "release_due_reason" not in cols:
        op.add_column("change_requests",
                      sa.Column("release_due_reason", sa.Text(), nullable=True))
    if "release_due_set_by" not in cols:
        # FK lives in the ORM only (SQLite cannot ADD COLUMN with FK)
        op.add_column("change_requests",
                      sa.Column("release_due_set_by", sa.Integer(), nullable=True))
    if "release_due_set_at" not in cols:
        op.add_column("change_requests",
                      sa.Column("release_due_set_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    pass  # forward-only
```

- [ ] **Step 5: Add schema fields**

In `backend/app/schemas/change.py`:

To `ChangeUpdate`, after `required_by_reason` (~line 47):

```python
    release_due_date: Optional[NaiveUtcDatetime] = None
    release_due_reason: Optional[str] = None
```

Replace `CustomerResponseRequest` (~line 57):

```python
class CustomerResponseRequest(BaseModel):
    response: str  # accepted | declined | negotiating
    # Mandatory when response == 'accepted' (enforced in the service)
    release_due_date: Optional[NaiveUtcDatetime] = None
    release_due_reason: Optional[str] = None
```

Replace `InternalApprovalIn` (~line 175):

```python
class InternalApprovalIn(BaseModel):
    note: Optional[str] = None
    # Mandatory — internal approval sets the release deadline (service enforces)
    release_due_date: Optional[NaiveUtcDatetime] = None
    release_due_reason: Optional[str] = None
```

To `ChangeResponse`, after `deadline_state` (~line 207):

```python
    quoted_at: Optional[datetime] = None
    quoted_on_time: Optional[bool] = None
    active_deadline: Optional[str] = None  # quote | release | None
    release_due_date: Optional[datetime] = None
    release_due_reason: Optional[str] = None
```

(`quoted_on_time`/`active_deadline` are model properties; `from_attributes` picks them up with no endpoint changes.)

- [ ] **Step 6: Run the migration and the tests**

Run: `cd backend && alembic upgrade head && python -m pytest tests/test_change_deadline.py -v`
Expected: all PASS (new tests use in-memory test DB created from models; `alembic upgrade head` verifies the migration runs against `plm.db`).

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/versions/040_release_deadline.py backend/app/models/change.py backend/app/schemas/change.py backend/tests/test_change_deadline.py
git commit -m "feat(changes): release-deadline columns, quoted_at, active-deadline model properties"
```

---

### Task 2: quoted_at stamping, phase-aware deadline_state, gate relaxation

**Files:**
- Modify: `backend/app/services/change_service.py` — `deadline_state` (~line 299), `_guard` in_assessment gate (~line 511), transition side effects (~line 660)
- Test: `backend/tests/test_change_deadline.py` (append)

**Interfaces:**
- Consumes: `ChangeRequest.active_deadline`, `.quoted_at`, `.release_due_date` from Task 1.
- Produces: `ChangeService.deadline_state(session, change) -> str | None` — same signature, now computed against the active deadline; `quoted_at` stamped on the transition into `quoted`; the "No deadline set" scoping→in_assessment gate applies only to customer-relevant changes.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_change_deadline.py`:

```python
@pytest.mark.asyncio
async def test_transition_to_quoted_stamps_quoted_at(session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(
            session, seed, change_number="C-DL-Q1", status="costing",
            customer_relevant=True, quoted_price=100.0,
            required_by_date=datetime.utcnow() + timedelta(days=10))
        await ChangeService.transition(session, chg, "quoted", seed["admin_id"])
        assert chg.status == "quoted"
        assert chg.quoted_at is not None


@pytest.mark.asyncio
async def test_deadline_state_follows_active_deadline(session_factory, seed):
    async with session_factory() as session:
        # overdue quote deadline while pre-quoted
        chg = await _mk_change(
            session, seed, change_number="C-DL-S1", status="costing",
            customer_relevant=True,
            required_by_date=datetime.utcnow() - timedelta(days=1))
        assert await ChangeService.deadline_state(session, chg) == "overdue"
        # quoted: quote deadline retired, nothing active -> None
        chg.quoted_at = datetime.utcnow()
        chg.status = "quoted"
        assert await ChangeService.deadline_state(session, chg) is None
        # release deadline takes over after acceptance/approval
        chg.status = "approved"
        chg.release_due_date = datetime.utcnow() - timedelta(days=2)
        assert await ChangeService.deadline_state(session, chg) == "overdue"
        chg.release_due_date = datetime.utcnow() + timedelta(days=60)
        assert await ChangeService.deadline_state(session, chg) == "on_track"


@pytest.mark.asyncio
async def test_internal_change_deadline_state_none_before_release_due(
        session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(
            session, seed, change_number="C-DL-S2", status="costing",
            customer_relevant=False,
            required_by_date=datetime.utcnow() - timedelta(days=5))
        assert await ChangeService.deadline_state(session, chg) is None


@pytest.mark.asyncio
async def test_in_assessment_gate_skips_deadline_for_internal(session_factory, seed):
    # The gate helper is ChangeService._guard(session, change, to_status) ->
    # str | None (reason string when blocked). The deadline gate sits behind
    # the item/lead gates, so give both changes an impacted item; _mk_change
    # already sets a lead. seed has no part, so create one (pattern from
    # tests/test_notifications.py:122).
    from app.models.change import ChangeImpactedItem
    from app.models.part import Part
    async with session_factory() as session:
        part = Part(project_id=seed["project_id"], part_number="P-DL-1",
                    name="P-DL-1", part_type="internal_mfg",
                    item_category="article", created_by=seed["admin_id"])
        session.add(part)
        await session.flush()
        chg = await _mk_change(
            session, seed, change_number="C-DL-G1", status="scoping",
            customer_relevant=False)
        session.add(ChangeImpactedItem(
            change_id=chg.id, part_id=part.id, is_lead=True))
        await session.flush()
        blocker = await ChangeService._guard(session, chg, "in_assessment")
        # internal change without a deadline: the deadline gate must not fire
        assert blocker is None or "deadline" not in blocker.lower()

        cust = await _mk_change(
            session, seed, change_number="C-DL-G2", status="scoping",
            customer_relevant=True)
        session.add(ChangeImpactedItem(
            change_id=cust.id, part_id=part.id, is_lead=True))
        await session.flush()
        blocker = await ChangeService._guard(session, cust, "in_assessment")
        # customer-relevant without a quote deadline still blocks
        assert blocker is not None and "deadline" in blocker.lower()
```

Note for the implementer: `_guard` reads `change.impacted_items` — if async lazy-loading errors appear, `await session.refresh(chg, ["impacted_items"])` after adding the item.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_change_deadline.py -k "quoted_at or follows_active or none_before or gate_skips" -v`
Expected: FAIL — `deadline_state` still reads `required_by_date` unconditionally; no `quoted_at` stamping.

- [ ] **Step 3: Implement**

In `change_service.py`, `deadline_state` (~line 299) — replace the guard and due-date source, keep the workflow heuristic untouched:

```python
    @staticmethod
    async def deadline_state(session: AsyncSession, change: ChangeRequest) -> str | None:
        """Computed on_track/at_risk/overdue for the phase's ACTIVE deadline:
        the Sales-set quote deadline (required_by_date) until the change is
        quoted, the release deadline (release_due_date) once one is set at
        acceptance / internal approval. None when nothing is active (terminal
        statuses, internal changes before approval, quoted changes waiting on
        the customer)."""
        kind = change.active_deadline
        if kind is None:
            return None
        due = change.release_due_date if kind == "release" else change.required_by_date
        from sqlalchemy.orm import selectinload
        from app.models.workflow import WfInstance, WfTemplate
        from app.services.workflow_service import DEFAULT_TASK_DUE_DAYS

        now = datetime.utcnow()
        if due < now:
            return "overdue"
        # ... existing insts query and `needed` loop unchanged ...
        days_left = (due - now).days
        return "at_risk" if needed > days_left else "on_track"
```

(The old `if change.required_by_date is None or change.status in TERMINAL_STATUSES` guard is subsumed by `active_deadline`; all other references to `change.required_by_date` inside this function become `due`.)

In the in_assessment gate (~line 511), change:

```python
            if change.required_by_date is None:
```

to:

```python
            # Internal changes have no quote deadline; only customer-relevant
            # changes must set the required-by date before assessment.
            if change.customer_relevant and change.required_by_date is None:
```

In the transition side effects (~line 660), next to the `released`/`closed` stamps:

```python
        if to_status == "quoted" and change.quoted_at is None:
            change.quoted_at = datetime.utcnow()
```

- [ ] **Step 4: Run the deadline tests, then the full backend suite**

Run: `cd backend && python -m pytest tests/test_change_deadline.py -v && python -m pytest -q`
Expected: deadline tests PASS. If any other test asserted the old unconditional deadline gate (search: `grep -rn "No deadline set" tests/`), update it to create the change as `customer_relevant=True` or drop the now-obsolete expectation — but as of writing no test does.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/change_service.py backend/tests/test_change_deadline.py
git commit -m "feat(changes): phase-aware deadline_state, quoted_at stamp, deadline gate only for customer-relevant"
```

---

### Task 3: Acceptance requires the release deadline

**Files:**
- Modify: `backend/app/services/change_service.py` — `record_customer_response` (~line 1508)
- Modify: `backend/app/api/v1/changes/changes.py` — `customer_response` endpoint (~line 647)
- Test: `backend/tests/test_change_deadline.py` (append); update existing accepted-response call sites (see Step 4)

**Interfaces:**
- Consumes: schema fields from Task 1 (`CustomerResponseRequest.release_due_date/-reason`).
- Produces: `ChangeService.record_customer_response(session, change, response, user_id, *, release_due_date: datetime | None = None, release_due_reason: str | None = None)`. Raises `ChangeError("Recording acceptance requires a release deadline")` when `response == "accepted"` and no date is given nor already set. Changelog action `"release_deadline_set"`, `field_name="release_due_date"`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_acceptance_requires_release_deadline(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Accept needs date", "reason": "r",
        "customer_relevant": True,
    }, headers=eng_auth)
    cid = res.json()["id"]

    res = await client.post(f"/api/v1/changes/{cid}/customer-response",
                            json={"response": "accepted"}, headers=eng_auth)
    assert res.status_code == 400
    assert "release deadline" in res.json()["detail"].lower()

    due = (datetime.utcnow() + timedelta(days=45)).isoformat()
    res = await client.post(f"/api/v1/changes/{cid}/customer-response", json={
        "response": "accepted", "release_due_date": due,
        "release_due_reason": "customer PO timing",
    }, headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["customer_response"] == "accepted"
    assert body["release_due_date"] is not None
    assert body["release_due_reason"] == "customer PO timing"
    assert body["active_deadline"] == "release"


@pytest.mark.asyncio
async def test_decline_does_not_require_release_deadline(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Decline no date", "reason": "r",
        "customer_relevant": True,
    }, headers=eng_auth)
    cid = res.json()["id"]
    res = await client.post(f"/api/v1/changes/{cid}/customer-response",
                            json={"response": "declined"}, headers=eng_auth)
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_acceptance_release_deadline_audited(client, eng_auth, seed, session_factory):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Audit release DL", "reason": "r",
        "customer_relevant": True,
    }, headers=eng_auth)
    cid = res.json()["id"]
    due = (datetime.utcnow() + timedelta(days=45)).isoformat()
    await client.post(f"/api/v1/changes/{cid}/customer-response", json={
        "response": "accepted", "release_due_date": due,
    }, headers=eng_auth)
    async with session_factory() as session:
        rows = (await session.execute(
            select(ChangeChangelog).where(
                ChangeChangelog.change_id == cid,
                ChangeChangelog.action == "release_deadline_set",
            ))).scalars().all()
        assert len(rows) == 1
        assert rows[0].field_name == "release_due_date"
        assert rows[0].old_value is None
        assert rows[0].new_value is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_change_deadline.py -k "acceptance or decline" -v`
Expected: FAIL — accepted without date currently returns 200; `release_due_date` not stored.

- [ ] **Step 3: Implement**

`record_customer_response` becomes:

```python
    @staticmethod
    async def record_customer_response(
        session: AsyncSession, change: ChangeRequest, response: str, user_id: int,
        *, release_due_date: Optional[datetime] = None,
        release_due_reason: Optional[str] = None,
    ) -> ChangeRequest:
        if response not in CUSTOMER_RESPONSES:
            raise ChangeError(f"Invalid customer response '{response}'")
        # Acceptance is the moment deadline #2 is born: the customer said yes,
        # so a released-by commitment must exist from here on.
        if (response == "accepted" and release_due_date is None
                and change.release_due_date is None):
            raise ChangeError(
                "Recording acceptance requires a release deadline (release_due_date)")
        change.customer_response = response
        change.customer_response_at = datetime.utcnow()
        change.customer_response_by = user_id
        if release_due_date is not None:
            old = change.release_due_date
            change.release_due_date = release_due_date
            if release_due_reason is not None:
                change.release_due_reason = release_due_reason
            change.release_due_set_by = user_id
            change.release_due_set_at = datetime.utcnow()
            await ChangeService.append_changelog(
                session, change, "release_deadline_set",
                f"Release due {old} -> {release_due_date}", user_id,
                field_name="release_due_date",
                old_value=str(old) if old else None,
                new_value=str(release_due_date), notes=change.release_due_reason)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "customer_response_recorded",
            f"Customer response: {response}", user_id,
            field_name="customer_response", new_value=response,
        )
        return change
```

Endpoint (~line 656) — pass the new fields through:

```python
        await ChangeService.record_customer_response(
            db, change, body.response, current_user.id,
            release_due_date=body.release_due_date,
            release_due_reason=body.release_due_reason)
```

- [ ] **Step 4: Fix existing tests that record acceptance**

Search: `grep -rn "customer-response" backend/tests/`. Every existing call posting `{"response": "accepted"}` must gain a `release_due_date` (any future ISO date), e.g. in `test_changes.py`, `test_change_scoping.py`, `test_impact_confirmation.py`, `test_pnl.py`. Calls posting declined/negotiating stay untouched.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_service.py backend/app/api/v1/changes/changes.py backend/tests/
git commit -m "feat(changes): customer acceptance requires and sets the release deadline"
```

---

### Task 4: Internal approval requires the release deadline

**Files:**
- Modify: `backend/app/services/change_service.py` — `approve_internal_costs` (~line 1546)
- Modify: `backend/app/api/v1/changes/changes.py` — `approve_internal_costs` endpoint (~line 688)
- Test: `backend/tests/test_internal_approval.py` (update existing + append)

**Interfaces:**
- Consumes: `InternalApprovalIn.release_due_date/-reason` from Task 1.
- Produces: `ChangeService.approve_internal_costs(session, change, actor, *, note=None, release_due_date: datetime | None = None, release_due_reason: str | None = None)`; raises `ChangeError("Internal approval requires a release deadline")` when `release_due_date is None` and none set yet; writes the same `"release_deadline_set"` changelog row as Task 3.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_internal_approval.py` (reuse that file's existing fixtures/helpers for creating an internal change in `costing` — read the file first and copy its setup helper):

```python
@pytest.mark.asyncio
async def test_internal_approval_requires_release_deadline(client, admin_auth, seed):
    cid = await _internal_change_in_costing(client, admin_auth, seed)  # existing helper/pattern
    res = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                            json={"note": "ok"}, headers=admin_auth)
    assert res.status_code == 400
    assert "release deadline" in res.json()["detail"].lower()

    due = (datetime.utcnow() + timedelta(days=30)).isoformat()
    res = await client.post(f"/api/v1/changes/{cid}/internal-approval", json={
        "note": "ok", "release_due_date": due, "release_due_reason": "plant window",
    }, headers=admin_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["internal_approved_at"] is not None
    assert body["release_due_date"] is not None
    assert body["active_deadline"] == "release"
```

If the file has no such helper, build the change the way its existing tests do — do not invent a new setup path.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_internal_approval.py -v`
Expected: new test FAILS (approval succeeds without a date).

- [ ] **Step 3: Implement**

In `approve_internal_costs`, after the `internal_approved_at is not None` guard:

```python
        # Internal path has no quote step, so approval is where deadline #2
        # is born — mirror of the acceptance rule for customer changes.
        if release_due_date is None and change.release_due_date is None:
            raise ChangeError(
                "Internal approval requires a release deadline (release_due_date)")
```

Signature gains `release_due_date: Optional[datetime] = None, release_due_reason: Optional[str] = None` (keyword-only, next to `note`). After the existing field assignments, set + audit the release deadline exactly as in Task 3's block (same code, `actor.id` as user id).

Endpoint passes `release_due_date=body.release_due_date, release_due_reason=body.release_due_reason`.

- [ ] **Step 4: Fix existing internal-approval tests**

`grep -rn "internal-approval" backend/tests/` — add a future `release_due_date` to every existing successful-approval POST body (`test_internal_approval.py`, `test_pnl.py`, others per grep).

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_service.py backend/app/api/v1/changes/changes.py backend/tests/
git commit -m "feat(changes): internal cost approval requires and sets the release deadline"
```

---

### Task 5: Release-deadline edits via PATCH

**Files:**
- Modify: `backend/app/services/change_service.py` — `update()` deadline block (~line 1457)
- Test: `backend/tests/test_change_deadline.py` (append)

**Interfaces:**
- Consumes: `ChangeUpdate.release_due_date/-reason` (Task 1), acceptance flow (Task 3) to create an editable deadline in tests.
- Produces: PATCH `/api/v1/changes/{id}` accepts `release_due_date`/`release_due_reason` once a release deadline exists; rejects setting it earlier ("Release deadline is first set at customer acceptance or internal cost approval") and rejects clearing it ("Release deadline cannot be cleared"). Audited as `"release_deadline_set"`.

- [ ] **Step 1: Write the failing tests**

```python
async def _accepted_change(client, eng_auth, seed, title):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": title, "reason": "r",
        "customer_relevant": True,
    }, headers=eng_auth)
    cid = res.json()["id"]
    due = (datetime.utcnow() + timedelta(days=45)).isoformat()
    res = await client.post(f"/api/v1/changes/{cid}/customer-response", json={
        "response": "accepted", "release_due_date": due,
    }, headers=eng_auth)
    assert res.status_code == 200, res.text
    return cid


@pytest.mark.asyncio
async def test_release_deadline_editable_after_acceptance(client, eng_auth, seed):
    cid = await _accepted_change(client, eng_auth, seed, "Edit release DL")
    new_due = (datetime.utcnow() + timedelta(days=60)).isoformat()
    res = await client.patch(f"/api/v1/changes/{cid}", json={
        "release_due_date": new_due, "release_due_reason": "customer moved SOP",
    }, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["release_due_reason"] == "customer moved SOP"


@pytest.mark.asyncio
async def test_release_deadline_not_settable_before_acceptance(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Too early", "reason": "r",
        "customer_relevant": True,
    }, headers=eng_auth)
    cid = res.json()["id"]
    res = await client.patch(f"/api/v1/changes/{cid}", json={
        "release_due_date": (datetime.utcnow() + timedelta(days=60)).isoformat(),
    }, headers=eng_auth)
    assert res.status_code == 400
    assert "acceptance or internal cost approval" in res.json()["detail"]


@pytest.mark.asyncio
async def test_release_deadline_cannot_be_cleared(client, eng_auth, seed):
    cid = await _accepted_change(client, eng_auth, seed, "No clearing")
    res = await client.patch(f"/api/v1/changes/{cid}", json={
        "release_due_date": None,
    }, headers=eng_auth)
    assert res.status_code == 400
```

Note: `"release_due_date": None` in a PATCH only reaches the service if the endpoint uses `exclude_unset` semantics — check how the changes PATCH endpoint builds `fields` (`grep -n "exclude_unset\|dict(" backend/app/api/v1/changes/changes.py` near the PATCH route). If `None` is indistinguishable from "not sent", drop the clearing test and the clearing guard, and note it in the commit message.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_change_deadline.py -k "release_deadline" -v`
Expected: FAIL — PATCH currently ignores `release_due_date` (not in the allowed fields).

- [ ] **Step 3: Implement**

In `update()`, directly after the existing `required_by_date` block (~line 1474):

```python
        # Release deadline: born at acceptance / internal approval (Tasks 3-4);
        # PATCH only ever *moves* it, with the same audited-set pattern.
        if "release_due_date" in fields:
            new_date = fields.pop("release_due_date")
            if change.release_due_date is None:
                raise ChangeError(
                    "Release deadline is first set at customer acceptance "
                    "or internal cost approval")
            if new_date is None:
                raise ChangeError("Release deadline cannot be cleared")
            old = change.release_due_date
            change.release_due_date = new_date
            if "release_due_reason" in fields:
                change.release_due_reason = fields.pop("release_due_reason")
            change.release_due_set_by = user_id
            change.release_due_set_at = datetime.utcnow()
            await ChangeService.append_changelog(
                session, change, "release_deadline_set",
                f"Release due {old} -> {new_date}", user_id,
                field_name="release_due_date",
                old_value=str(old), new_value=str(new_date),
                notes=change.release_due_reason)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_change_deadline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/change_service.py backend/tests/test_change_deadline.py
git commit -m "feat(changes): audited PATCH edits of the release deadline"
```

---

### Task 6: Escalations and workload report use the active deadline

**Files:**
- Modify: `backend/app/services/change_service.py` — `lead_escalations` deadline block (~line 410-430)
- Modify: `backend/app/services/report_service.py` — at-risk block (~line 182-197)
- Test: `backend/tests/test_change_deadline.py` (append; check `backend/tests/test_my_actions.py` and report tests for affected assertions)

**Interfaces:**
- Consumes: `active_deadline`, phase-aware `deadline_state`.
- Produces: escalation dicts keep the key `required_by_date` (EscalationsCard reads it) but fill it with the *active* deadline's date, and the label reads `"Quote due YYYY-MM-DD"` / `"Release due YYYY-MM-DD"`. Workload report rows become `{"id", "change_number", "title", "required_by_date": <active due date>, "state": <deadline_state>}` — note the key rename `deadline_state` → `state`, fixing the existing mismatch with `WorkloadAtRiskChange.state` in `frontend/src/api/reports.ts:45`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_lead_escalations_use_active_deadline(session_factory, seed):
    async with session_factory() as session:
        # released-phase change overdue on its release deadline
        chg = await _mk_change(
            session, seed, change_number="C-DL-E1", status="approved",
            customer_relevant=True, lead_id=seed["admin_id"],
            required_by_date=datetime.utcnow() - timedelta(days=30),
            quoted_at=datetime.utcnow() - timedelta(days=20),
            release_due_date=datetime.utcnow() - timedelta(days=2))
        out = await ChangeService.lead_escalations(session, seed["admin_id"])
        rows = [e for e in out if e.get("kind") == "deadline"
                and e["change_id"] == chg.id]
        assert len(rows) == 1
        assert rows[0]["label"].startswith("Release due")
        assert rows[0]["state"] == "overdue"
        # the date shown is the release date, not the stale quote date
        assert rows[0]["required_by_date"] == chg.release_due_date.isoformat()


@pytest.mark.asyncio
async def test_workload_report_uses_active_deadline_and_state_key(
        session_factory, seed):
    from app.services.report_service import ReportService
    async with session_factory() as session:
        await _mk_change(
            session, seed, change_number="C-DL-R1", status="approved",
            customer_relevant=True,
            required_by_date=datetime.utcnow() - timedelta(days=30),
            quoted_at=datetime.utcnow() - timedelta(days=20),
            release_due_date=datetime.utcnow() - timedelta(days=2))
        report = await ReportService.workload(session, None)
        rows = [r for r in report["at_risk_changes"]
                if r["change_number"] == "C-DL-R1"]
        assert len(rows) == 1
        assert rows[0]["state"] == "overdue"
```

Note: check `ReportService.workload`'s actual name and signature first (`grep -n "def workload\|async def" backend/app/services/report_service.py`) and call it the way existing report tests do (viewer argument may be required).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_change_deadline.py -k "escalations or workload" -v`
Expected: FAIL — escalation label reads `Required by`, report key is `deadline_state`, and a quoted/approved change either doesn't appear or shows the quote date.

- [ ] **Step 3: Implement**

`lead_escalations` deadline block (~line 411) becomes:

```python
        # Active-phase deadlines at risk or already overdue (quote deadline
        # pre-quoted, release deadline post-approval).
        for c in changes:
            kind = c.active_deadline
            if kind is None:
                continue
            due = c.release_due_date if kind == "release" else c.required_by_date
            state = await ChangeService.deadline_state(session, c)
            if state not in ("at_risk", "overdue"):
                continue
            days_overdue = (now - due).days if state == "overdue" else -(due - now).days
            out.append({
                "kind": "deadline", "change_id": c.id,
                "change_number": c.change_number, "change_title": c.title,
                "label": f"{'Release' if kind == 'release' else 'Quote'} due "
                         f"{due.date().isoformat()}",
                # key kept for EscalationsCard compatibility; value is the
                # active deadline's date, whichever kind that is.
                "required_by_date": due.isoformat(),
                "state": state,
                "days_overdue": days_overdue,
            })
```

`report_service.py` at-risk block: widen the candidate query (drop the `required_by_date.is_not(None)` filter — `deadline_state` now returns None where nothing is active) and emit the active date under the old key plus the `state` key:

```python
        candidates = (await session.execute(_org_scope(
            select(ChangeRequest).where(
                ChangeRequest.status.not_in(TERMINAL_STATUSES),
            ), viewer,
        ))).scalars().all()
        at_risk_changes = []
        for c in candidates:
            state = await ChangeService.deadline_state(session, c)
            if state in ("at_risk", "overdue"):
                due = (c.release_due_date if c.active_deadline == "release"
                       else c.required_by_date)
                at_risk_changes.append({
                    "id": c.id, "change_number": c.change_number, "title": c.title,
                    "required_by_date": due.isoformat(),
                    "state": state,
                })
```

- [ ] **Step 4: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS. If a report/my-actions test asserted the `deadline_state` key or the `Required by` label, update it to the new contract.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/change_service.py backend/app/services/report_service.py backend/tests/
git commit -m "feat(changes): escalations and workload report track the active deadline"
```

---

### Task 7: Frontend types, API signatures, labels

**Files:**
- Modify: `frontend/src/types/change.ts` (~line 124)
- Modify: `frontend/src/api/changes.ts` (`customerResponse` line 49, `approveInternalCosts` line 142)
- Modify: `frontend/src/i18n/cmLabels.ts` (deadline block ~line 273)

**Interfaces:**
- Produces (used by Tasks 8-11):
  - Types on `ChangeRequest`: `quoted_at: string | null; quoted_on_time: boolean | null; active_deadline: 'quote' | 'release' | null; release_due_date: string | null; release_due_reason: string | null;`
  - `changesApi.customerResponse(id: number, response: string, body?: { release_due_date?: string; release_due_reason?: string | null })`
  - `changesApi.approveInternalCosts(id: number, body: { note?: string | null; release_due_date?: string; release_due_reason?: string | null })`
  - Label keys: `deadline.quote`, `deadline.release`, `deadline.quotedOnTime`, `deadline.quotedLate`, `customer.releaseDue`, `customer.releaseDueReason`, `customer.confirmAccept`.

- [ ] **Step 1: Add the type fields**

In `frontend/src/types/change.ts` after `deadline_state`:

```ts
  quoted_at: string | null;
  quoted_on_time: boolean | null;
  active_deadline: 'quote' | 'release' | null;
  release_due_date: string | null;
  release_due_reason: string | null;
```

- [ ] **Step 2: Update the API functions**

```ts
  customerResponse: (
    id: number, response: string,
    body?: { release_due_date?: string; release_due_reason?: string | null },
  ) =>
    client.post(`/v1/changes/${id}/customer-response`, { response, ...body }).then((r) => r.data),
```

```ts
  approveInternalCosts: (
    id: number,
    body: { note?: string | null; release_due_date?: string; release_due_reason?: string | null },
  ) =>
    client.post<ChangeRequest>(`/v1/changes/${id}/internal-approval`, {
      note: body.note ?? null, release_due_date: body.release_due_date,
      release_due_reason: body.release_due_reason ?? null,
    }).then((r) => r.data),
```

- [ ] **Step 3: Add labels**

In `cmLabels.ts` next to the existing `deadline.*` entries:

```ts
  'deadline.quote': { de: 'Angebotstermin', en: 'Quote deadline' },
  'deadline.release': { de: 'Freigabetermin', en: 'Release deadline' },
  'deadline.quotedOnTime': { de: 'Fristgerecht angeboten', en: 'Quoted on time' },
  'deadline.quotedLate': { de: 'Verspätet angeboten', en: 'Quoted late' },
  'customer.releaseDue': { de: 'Freigabe bis', en: 'Release by' },
  'customer.releaseDueReason': { de: 'Begründung', en: 'Reason' },
  'customer.confirmAccept': { de: 'Annahme bestätigen', en: 'Confirm acceptance' },
```

- [ ] **Step 4: Compile and fix call-site errors**

Run: `cd frontend && npx tsc --noEmit`
Expected: errors at `ChangeDetailPage.tsx:174` (`approveInternalCosts` now takes a body object) and possibly test files constructing `ChangeRequest` literals. Fix the ChangeDetailPage call minimally for now (`internalApprove.mutate` passing `{ note: undefined }` — Task 10 replaces this flow) and add the five new fields to any test fixture factories that build full `ChangeRequest`/`ChangeDetail` objects (most use `Partial` casts and won't error). Re-run until clean.

- [ ] **Step 5: Run the frontend suite and commit**

Run: `cd frontend && npx vitest run`
Expected: PASS.

```bash
git add frontend/src/types/change.ts frontend/src/api/changes.ts frontend/src/i18n/cmLabels.ts frontend/src/pages/ChangeDetailPage.tsx
git commit -m "feat(frontend): two-phase deadline types, api signatures, labels"
```

---

### Task 8: Phase-aware deadline UI (editor kind, quoted fact, cockpit/scoping wiring)

**Files:**
- Modify: `frontend/src/components/changes/DeadlineChip.tsx` (add `QuotedFactChip`)
- Modify: `frontend/src/components/changes/DeadlineEditor.tsx` (add `kind` prop)
- Modify: `frontend/src/components/changes/CockpitSummary.tsx:102`, `frontend/src/components/changes/ScopingPanel.tsx:155`
- Test: `frontend/src/components/changes/DeadlineEditor.test.tsx` (create), `frontend/src/components/changes/CockpitSummary.test.tsx` (append)

**Interfaces:**
- Consumes: types/labels from Task 7.
- Produces: `DeadlineEditor({ change, kind })` with `kind: 'quote' | 'release'` (default `'quote'`) editing `required_by_*` or `release_due_*` respectively; `QuotedFactChip({ change })` rendering the frozen quoted-on-time/late fact; cockpit shows the active-phase widget; scoping panel shows the quote editor only for customer-relevant changes.

- [ ] **Step 1: Write the failing tests**

`DeadlineEditor.test.tsx` (mock `changesApi.update` with `vi.mock('../../api/changes', ...)`, wrap in `QueryClientProvider` — copy the harness style from `CockpitSummary.test.tsx`):

```tsx
it('edits release_due_date when kind is release', async () => {
  render(wrap(<DeadlineEditor change={change({
    release_due_date: '2026-10-01T23:59:59', release_due_reason: null,
  })} kind="release" />))
  fireEvent.click(screen.getByTestId('deadline-edit'))
  fireEvent.change(screen.getByDisplayValue('2026-10-01'), { target: { value: '2026-11-15' } })
  fireEvent.click(screen.getByText(t('deadline.set')))
  await waitFor(() => expect(changesApi.update).toHaveBeenCalledWith(7, {
    release_due_date: '2026-11-15T23:59:59Z', release_due_reason: null,
  }))
})

it('defaults to editing required_by_date (quote kind)', async () => {
  render(wrap(<DeadlineEditor change={change({ required_by_date: null })} />))
  fireEvent.click(screen.getByTestId('deadline-edit'))
  fireEvent.change(screen.getByRole('textbox', { hidden: true }) ?? document.querySelector('input[type=date]')!, { target: { value: '2026-09-01' } })
  fireEvent.click(screen.getByText(t('deadline.set')))
  await waitFor(() => expect(changesApi.update).toHaveBeenCalledWith(7, {
    required_by_date: '2026-09-01T23:59:59Z', required_by_reason: null,
  }))
})
```

(Adjust the date-input query to whatever the component renders — `container.querySelector('input[type="date"]')` is the reliable form.)

`CockpitSummary.test.tsx` additions:

```tsx
it('shows the frozen quoted-late fact while waiting on the customer', () => {
  render(wrap(<CockpitSummary change={change({
    status: 'quoted', customer_relevant: true,
    required_by_date: '2026-06-01T23:59:59', quoted_at: '2026-06-10T00:00:00',
    quoted_on_time: false, active_deadline: null,
  })} />))
  expect(screen.getByText(new RegExp(t('deadline.quotedLate')))).toBeTruthy()
})

it('shows the release deadline editor once active', () => {
  render(wrap(<CockpitSummary change={change({
    status: 'approved', customer_relevant: true, active_deadline: 'release',
    release_due_date: '2026-10-01T23:59:59', release_due_reason: null,
    deadline_state: 'on_track',
  })} />))
  expect(screen.getByTestId('deadline-chip')).toBeTruthy()
})

it('hides the quote deadline editor for internal changes', () => {
  render(wrap(<CockpitSummary change={change({
    status: 'costing', customer_relevant: false, active_deadline: null,
    required_by_date: null,
  })} />))
  expect(screen.queryByTestId('deadline-edit')).toBeNull()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/changes/DeadlineEditor.test.tsx src/components/changes/CockpitSummary.test.tsx`
Expected: FAIL — no `kind` prop, no quoted-fact rendering.

- [ ] **Step 3: Implement**

`DeadlineChip.tsx` — add:

```tsx
import { t } from '../../i18n/cmLabels'
import type { ChangeRequest } from '../../types/change'

export function QuotedFactChip({ change }: { change: ChangeRequest }) {
  if (change.quoted_on_time === null) return null
  const ok = change.quoted_on_time
  return (
    <span data-testid="quoted-fact-chip"
      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs ${
        ok ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
           : 'bg-red-500/10 text-red-300 border-red-500/30'}`}
      title={change.required_by_date ? new Date(change.required_by_date).toLocaleDateString() : undefined}>
      {ok ? `✓ ${t('deadline.quotedOnTime')}` : t('deadline.quotedLate')}
    </span>
  )
}
```

`DeadlineEditor.tsx` — generalize over the field pair:

```tsx
export function DeadlineEditor({ change, kind = 'quote' }:
    { change: ChangeRequest; kind?: 'quote' | 'release' }) {
  const dateField = kind === 'release' ? 'release_due_date' : 'required_by_date'
  const reasonField = kind === 'release' ? 'release_due_reason' : 'required_by_reason'
  const curDate = change[dateField]
  const curReason = change[reasonField]
  ...
```

All `change.required_by_date`/`change.required_by_reason` reads become `curDate`/`curReason`; the mutate body becomes:

```tsx
save.mutate({
  [dateField]: date ? `${date}T23:59:59Z` : null,
  [reasonField]: reason || null,
})
```

Title/label uses `t(kind === 'release' ? 'deadline.release' : 'deadline.quote')` in place of the bare `t('deadline.title')` where the "+ Termin" affordance renders. Keep `data-testid="deadline-edit"` and the DeadlineChip (`state={change.deadline_state}` is correct for whichever kind is active; pass `date={curDate}`).

`CockpitSummary.tsx:102` — replace `<DeadlineEditor change={change} />` with:

```tsx
{change.active_deadline === 'release' ? (
  <DeadlineEditor change={change} kind="release" />
) : change.quoted_on_time !== null ? (
  <QuotedFactChip change={change} />
) : change.customer_relevant ? (
  <DeadlineEditor change={change} kind="quote" />
) : null}
```

`ScopingPanel.tsx:155` — wrap: `{change.customer_relevant && <DeadlineEditor change={change} kind="quote" />}`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/changes && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/changes/DeadlineChip.tsx frontend/src/components/changes/DeadlineEditor.tsx frontend/src/components/changes/CockpitSummary.tsx frontend/src/components/changes/ScopingPanel.tsx frontend/src/components/changes/DeadlineEditor.test.tsx frontend/src/components/changes/CockpitSummary.test.tsx
git commit -m "feat(frontend): phase-aware deadline editor, frozen quoted fact, cockpit/scoping wiring"
```

---

### Task 9: Customer-accepted flow collects the release deadline

**Files:**
- Modify: `frontend/src/pages/ChangeDetailPage.tsx` (customer mutation ~line 169; buttons ~line 439-443)
- Test: `frontend/src/pages/ChangeDetailPage.test.tsx` (append)

**Interfaces:**
- Consumes: `changesApi.customerResponse(id, response, body?)` from Task 7.
- Produces: clicking "Customer accepted" reveals an inline confirm row (date input required + reason input + confirm button, `data-testid="accept-release-due"` on the date input, `data-testid="accept-confirm"` on the button); confirm disabled until a date is chosen; "Customer declined" still posts directly with no dialog.

- [ ] **Step 1: Write the failing test**

Append to `ChangeDetailPage.test.tsx` (reuse its existing mock/render harness — it already mocks `changesApi`; find the test that clicks Customer accepted or the harness that renders a `quoted` change):

```tsx
it('requires a release date before recording customer acceptance', async () => {
  renderDetail({ status: 'quoted', customer_relevant: true })  // existing harness helper
  fireEvent.click(screen.getByText('Customer accepted'))
  // no API call yet — the confirm row opened instead
  expect(changesApi.customerResponse).not.toHaveBeenCalled()
  const confirm = screen.getByTestId('accept-confirm')
  expect((confirm as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(screen.getByTestId('accept-release-due'), { target: { value: '2026-11-30' } })
  fireEvent.click(confirm)
  await waitFor(() => expect(changesApi.customerResponse).toHaveBeenCalledWith(
    expect.any(Number), 'accepted',
    { release_due_date: '2026-11-30T23:59:59Z', release_due_reason: null }))
})
```

Adapt `renderDetail` to the file's actual helper name; read the file's existing tests first.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/ChangeDetailPage.test.tsx`
Expected: FAIL — the button posts immediately.

- [ ] **Step 3: Implement**

In `ChangeDetailPage.tsx`, add local state near the other dialog states:

```tsx
const [acceptOpen, setAcceptOpen] = useState(false);
const [acceptDue, setAcceptDue] = useState('');
const [acceptReason, setAcceptReason] = useState('');
```

Update the mutation to pass the body through:

```tsx
const customer = useMutation({
  mutationFn: (vars: { response: string; release_due_date?: string; release_due_reason?: string | null }) =>
    changesApi.customerResponse(changeId, vars.response,
      vars.response === 'accepted'
        ? { release_due_date: vars.release_due_date, release_due_reason: vars.release_due_reason }
        : undefined),
  onSuccess: () => { setAcceptOpen(false); qc.invalidateQueries({ queryKey: ['change', changeId] }); },
  onError: (e: unknown) => toast.error(errDetail(e) ?? 'Failed to record customer response'),
});
```

Replace the buttons block (~line 439):

```tsx
<div className="flex flex-wrap items-center gap-2">
  <button className="px-3 py-1.5 border rounded-lg"
    onClick={() => setAcceptOpen((o) => !o)}>Customer accepted</button>
  <button className="px-3 py-1.5 border rounded-lg"
    onClick={() => customer.mutate({ response: 'declined' })}>Customer declined</button>
</div>
{acceptOpen && (
  <div className="flex flex-wrap items-center gap-2 mt-2">
    <label className="text-xs text-slate-400">{t('customer.releaseDue')}</label>
    <input type="date" data-testid="accept-release-due" value={acceptDue}
      onChange={(e) => setAcceptDue(e.target.value)}
      className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
    <input type="text" placeholder={t('customer.releaseDueReason')} value={acceptReason}
      onChange={(e) => setAcceptReason(e.target.value)}
      className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 w-40" />
    <button data-testid="accept-confirm"
      className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
      disabled={!acceptDue || customer.isPending}
      onClick={() => customer.mutate({
        response: 'accepted',
        release_due_date: `${acceptDue}T23:59:59Z`,
        release_due_reason: acceptReason || null,
      })}>
      {t('customer.confirmAccept')}
    </button>
  </div>
)}
```

If existing tests click "Customer accepted" expecting an immediate post, update them to go through the confirm row.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/ChangeDetailPage.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ChangeDetailPage.tsx frontend/src/pages/ChangeDetailPage.test.tsx
git commit -m "feat(frontend): acceptance flow collects the mandatory release deadline"
```

---

### Task 10: Internal approval collects the release deadline

**Files:**
- Modify: `frontend/src/pages/ChangeDetailPage.tsx` (internal approval block ~line 477-483, mutation ~line 173)
- Test: `frontend/src/pages/ChangeDetailPage.test.tsx` (append)

**Interfaces:**
- Consumes: `changesApi.approveInternalCosts(id, body)` from Task 7.
- Produces: the internal-approval button opens the same style of confirm row (`data-testid="internal-release-due"` date input, `data-testid="internal-approve-confirm"` button, disabled until dated) and posts `{ note, release_due_date, release_due_reason }`.

- [ ] **Step 1: Write the failing test**

```tsx
it('requires a release date before internal cost approval', async () => {
  renderDetail({ status: 'costing', customer_relevant: false })  // + whatever flags the harness needs for canApproveInternalCosts
  fireEvent.click(screen.getByText(t('internal.approve')))
  expect(changesApi.approveInternalCosts).not.toHaveBeenCalled()
  const confirm = screen.getByTestId('internal-approve-confirm')
  expect((confirm as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(screen.getByTestId('internal-release-due'), { target: { value: '2026-12-15' } })
  fireEvent.click(confirm)
  await waitFor(() => expect(changesApi.approveInternalCosts).toHaveBeenCalledWith(
    expect.any(Number),
    { note: null, release_due_date: '2026-12-15T23:59:59Z', release_due_reason: null }))
})
```

Check how existing tests satisfy `canApproveInternalCosts` (grep the test file for `internal`) and reuse that setup.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/ChangeDetailPage.test.tsx`
Expected: FAIL — button posts immediately.

- [ ] **Step 3: Implement**

State: `const [internalOpen, setInternalOpen] = useState(false); const [internalDue, setInternalDue] = useState('');` — mutation becomes:

```tsx
const internalApprove = useMutation({
  mutationFn: (vars: { note?: string | null; release_due_date: string }) =>
    changesApi.approveInternalCosts(changeId, {
      note: vars.note ?? null, release_due_date: vars.release_due_date,
      release_due_reason: null,
    }),
  onSuccess: () => {
    toast.success(t('internal.approved'));
    setInternalOpen(false);
    qc.invalidateQueries({ queryKey: ['change', changeId] });
  },
  onError: (e: unknown) => toast.error(errDetail(e) ?? 'Approval failed'),
});
```

Button block: the existing approve button toggles `setInternalOpen`; below it, when open:

```tsx
{internalOpen && (
  <div className="flex flex-wrap items-center gap-2 mt-2">
    <label className="text-xs text-slate-400">{t('customer.releaseDue')}</label>
    <input type="date" data-testid="internal-release-due" value={internalDue}
      onChange={(e) => setInternalDue(e.target.value)}
      className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
    <button data-testid="internal-approve-confirm"
      className="bg-emerald-700 hover:bg-emerald-600 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
      disabled={!internalDue || internalApprove.isPending}
      onClick={() => internalApprove.mutate({ release_due_date: `${internalDue}T23:59:59Z` })}>
      {t('internal.approve')}
    </button>
  </div>
)}
```

Update any existing test that clicked approve expecting an immediate call.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/ChangeDetailPage.test.tsx && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ChangeDetailPage.tsx frontend/src/pages/ChangeDetailPage.test.tsx
git commit -m "feat(frontend): internal approval collects the mandatory release deadline"
```

---

### Task 11: List, escalations, and report show the active deadline

**Files:**
- Modify: `frontend/src/pages/ChangesPage.tsx:84`
- Modify: `frontend/src/pages/ReportsPage.tsx:175` (verify field names against the Task 6 payload)
- Test: `frontend/src/pages/ReportsPage.test.tsx` / list test as applicable

**Interfaces:**
- Consumes: `active_deadline`/`release_due_date` on list rows; report rows `{required_by_date, state}` from Task 6.
- Produces: list chip shows the active deadline's date or nothing; report chip gets a real `state` again.

- [ ] **Step 1: Update ChangesPage**

Replace line 84:

```tsx
<DeadlineChip
  date={c.active_deadline === 'release' ? c.release_due_date
      : c.active_deadline === 'quote' ? c.required_by_date : null}
  state={c.deadline_state} />
```

- [ ] **Step 2: Verify ReportsPage/EscalationsCard against the new payload**

`ReportsPage.tsx:175` already reads `c.required_by_date` and `c.state` — Task 6 now actually populates `state` (the old backend key was `deadline_state`, so the chip silently defaulted; this is the fix landing). `EscalationsCard.tsx` reads `e.required_by_date`, `e.state`, `e.label` — all still present. No frontend change needed beyond confirming; add/extend a ReportsPage test asserting the chip renders the overdue style when `state: 'overdue'` if one doesn't exist.

- [ ] **Step 3: Full frontend verification**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS.

- [ ] **Step 4: Full backend verification**

Run: `cd backend && python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ChangesPage.tsx frontend/src/pages/ReportsPage.tsx frontend/src/pages/ReportsPage.test.tsx
git commit -m "feat(frontend): active-deadline chips in changes list and workload report"
```
