# ECM Phase A — Hard Gates, 4-Eyes Deviations, Unified Audit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the change lifecycle IATF/VDA-defensible: D1 gates always exist and always block, the free-text justification override is replaced by formal 4-eyes deviation objects, and every change-relevant event dual-writes into the (currently unused) hash-chained `AuditLog` with a per-change correlation id, queryable/verifiable/exportable via a new audit API.

**Architecture:** A new `AuditService` writes globally hash-chained `audit_logs` rows; the single dual-write hook lives in `ChangeService.append_changelog` (every change event already flows through it). A new `ChangeTransitionDeviation` model (propose → approve/reject by a *different* authorized user → consumed on use) replaces `justification` in `ChangeService.transition`. `create_change` seeds all three `ChangeGate` rows (decision `na`), so the existing gate check in `_guard` becomes always-on; migration `022` seeds gate rows for in-flight changes at their current effective state. Frontend swaps `window.prompt` for a deviation banner + reason dialog.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async (`Mapped`/`mapped_column`), Alembic, Pydantic v2, pytest + pytest-asyncio (`asyncio_mode=auto`); React + TypeScript, @tanstack/react-query, Tailwind, vitest + @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-07-02-ecm-lifecycle-design.md` (Phase A row of the phasing table + scope areas 3 and 5).

## Global Constraints

- Run backend tests from `backend/` with `python3 -m pytest` (bare `python` is absent on this host).
- Every new model MUST be imported in `backend/app/models/__init__.py` (tests build schema via `Base.metadata.create_all`).
- New Alembic migration id is `022`, `down_revision = '021'`. Use the idempotent `inspect(op.get_bind())` guard pattern; `sa.String` for enum-like columns; never `.create()` enums.
- Enum-like value tuples live as module constants next to the model (mirror `CHANGE_STATUSES`).
- Pydantic response models use `class Config: from_attributes = True`.
- All persisted audited actions append to the hash-chained changelog via `ChangeService.append_changelog(...)` (which after Task 1 also dual-writes `AuditLog`).
- The `quoted → approved` hard requirements (customer accepted + PM/Quality dual sign-off, different users) remain absolute — NOT bypassable by deviation.
- Table names in raw SQL: `change_requests`, `change_changelog`, `change_gate`, `audit_logs`.
- Test import convention: `from tests.conftest import <helper>`.
- Frontend tests: `cd frontend && npx vitest run <file>`; type-check with `npx tsc --noEmit`.
- Agent tiering (execution guidance from the spec): each task carries a **Tier** hint — haiku = mechanical/pattern-following, sonnet = standard feature work, opus = design-critical (hash chains, state machine, authorization rules). Never trade correctness for cost; when in doubt, tier up.

---

## File Structure

**Backend — create:**
- `backend/app/services/audit_service.py` — `AuditService.record` + `verify_chain` (global hash chain over `audit_logs`).
- `backend/app/schemas/audit.py` — `AuditEntryResponse`, `AuditVerifyResponse`.
- `backend/app/api/v1/audit.py` — `GET /audit` (filters), `GET /audit/verify`, `GET /audit/export` (CSV).
- `backend/alembic/versions/022_transition_deviations_hard_gates.py` — deviation table + gate seeding.
- `backend/tests/test_audit.py`, `backend/tests/test_change_deviations.py`.

**Backend — modify:**
- `backend/app/models/change.py` — `ChangeTransitionDeviation` + `DEVIATION_STATUSES` + relationship on `ChangeRequest`.
- `backend/app/models/__init__.py` — register the new model.
- `backend/app/services/change_service.py` — dual-write hook, deviation propose/decide, transition rework, gate seeding in `create_change`.
- `backend/app/schemas/change.py` — deviation schemas; drop `justification` from `TransitionRequest`.
- `backend/app/api/v1/changes/changes.py` — deviation routes, gate-decide authorization, transition call.
- `backend/app/api/v1/__init__.py` — register audit router.
- `backend/tests/conftest.py` — `approve_gates` helper.
- `backend/tests/test_changes.py`, `test_change_gates.py`, `test_change_routing.py` — adapt to hard gates / deviation flow.

**Frontend — create:**
- `frontend/src/components/changes/ReasonDialog.tsx` — generic modal with a textarea (used for cancel + deviation reasons).
- `frontend/src/components/changes/DeviationBanner.tsx` (+ `DeviationBanner.test.tsx`) — blocked-transition banner with propose/decide/retry.

**Frontend — modify:**
- `frontend/src/types/change.ts` — `TransitionDeviation` type.
- `frontend/src/api/changes.ts` — deviation endpoints; transition loses `justification`.
- `frontend/src/pages/ChangeDetailPage.tsx` — remove `window.prompt`, wire banner + dialog.

---

## Task 1: `AuditService` — global hash chain + dual-write from `append_changelog`

**Tier:** opus (hash-chain integrity is design-critical).

**Files:**
- Create: `backend/app/services/audit_service.py`
- Modify: `backend/app/services/change_service.py` (inside `append_changelog`)
- Test: `backend/tests/test_audit.py`

**Interfaces:**
- Produces: `AuditService.record(session, *, entity_type: str, entity_id: int, action: str, user_id: int | None = None, old_values=None, new_values=None, correlation_id: str | None = None, log_level: str = "info") -> AuditLog` and `AuditService.verify_chain(session) -> dict` returning `{"valid": bool, "checked": int, "first_broken_id": int | None}`.
- After this task every `ChangeService.append_changelog` call also creates one `audit_logs` row with `entity_type="change"`, `correlation_id=change.change_number`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_audit.py
import pytest
from sqlalchemy import select, update

pytestmark = pytest.mark.asyncio


async def test_record_chains_hashes(session_factory, seed):
    from app.models.entities import AuditLog
    from app.services.audit_service import AuditService
    async with session_factory() as s:
        e1 = await AuditService.record(
            s, entity_type="change", entity_id=1, action="created",
            user_id=seed["engineer_id"], correlation_id="CR-2026-0001")
        e2 = await AuditService.record(
            s, entity_type="change", entity_id=1, action="status_changed",
            user_id=seed["engineer_id"],
            old_values={"status": "captured"}, new_values={"status": "in_assessment"},
            correlation_id="CR-2026-0001")
        await s.commit()
    assert e1.entry_hash and len(e1.entry_hash) == 64
    assert e1.previous_hash is None
    assert e2.previous_hash == e1.entry_hash


async def test_change_actions_dual_write_audit(client, eng_auth, seed, session_factory):
    from app.models.entities import AuditLog
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "audit me",
        "change_type": "physical_part"}, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    number = res.json()["change_number"]
    async with session_factory() as s:
        rows = (await s.execute(
            select(AuditLog).where(AuditLog.correlation_id == number))).scalars().all()
    assert any(r.action == "created" for r in rows)
    assert all(r.entity_type == "change" for r in rows)


async def test_verify_chain_detects_tamper(session_factory, seed):
    from app.models.entities import AuditLog
    from app.services.audit_service import AuditService
    async with session_factory() as s:
        e1 = await AuditService.record(s, entity_type="change", entity_id=1,
                                       action="created", user_id=seed["engineer_id"])
        await AuditService.record(s, entity_type="change", entity_id=1,
                                  action="updated", user_id=seed["engineer_id"])
        await s.commit()
        assert (await AuditService.verify_chain(s))["valid"] is True
        await s.execute(update(AuditLog).where(AuditLog.id == e1.id)
                        .values(action="deleted"))
        await s.commit()
        result = await AuditService.verify_chain(s)
    assert result["valid"] is False
    assert result["first_broken_id"] == e1.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.audit_service'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/audit_service.py
"""Unified tamper-evident audit trail: globally hash-chained audit_logs rows
with a correlation id (the change number) for cross-entity timelines.

Chain design: each entry's payload hash covers its content plus the previous
entry's hash (global order by id). SQLite serializes writers, so the read-last/
write-next pattern is race-free here; revisit if moving to Postgres with
concurrent writers (advisory lock or per-correlation chains)."""
import hashlib
import json
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AuditLog


class AuditService:

    @staticmethod
    def _payload(entity_type: str, entity_id: int, action: str,
                 old_s: Optional[str], new_s: Optional[str],
                 user_id: Optional[int], ts: datetime, prev: Optional[str]) -> str:
        return "|".join([
            entity_type, str(entity_id), action, old_s or "", new_s or "",
            str(user_id or ""), ts.isoformat(), prev or "",
        ])

    @staticmethod
    async def record(
        session: AsyncSession, *, entity_type: str, entity_id: int, action: str,
        user_id: Optional[int] = None, old_values=None, new_values=None,
        correlation_id: Optional[str] = None, log_level: str = "info",
    ) -> AuditLog:
        prev = (await session.execute(
            select(AuditLog.entry_hash).order_by(AuditLog.id.desc()).limit(1)
        )).scalar_one_or_none()
        old_s = json.dumps(old_values) if old_values is not None else None
        new_s = json.dumps(new_values) if new_values is not None else None
        ts = datetime.utcnow()
        entry = AuditLog(
            entity_type=entity_type, entity_id=entity_id, action=action,
            user_id=user_id, timestamp=ts, old_values=old_s, new_values=new_s,
            correlation_id=correlation_id, log_level=log_level,
            previous_hash=prev,
            entry_hash=hashlib.sha256(AuditService._payload(
                entity_type, entity_id, action, old_s, new_s, user_id, ts, prev
            ).encode()).hexdigest(),
        )
        session.add(entry)
        await session.flush()
        return entry

    @staticmethod
    async def verify_chain(session: AsyncSession) -> dict:
        rows = (await session.execute(
            select(AuditLog).order_by(AuditLog.id))).scalars().all()
        prev = None
        for r in rows:
            expected = hashlib.sha256(AuditService._payload(
                r.entity_type, r.entity_id, r.action, r.old_values, r.new_values,
                r.user_id, r.timestamp, prev).encode()).hexdigest()
            if r.previous_hash != prev or r.entry_hash != expected:
                return {"valid": False, "checked": len(rows), "first_broken_id": r.id}
            prev = r.entry_hash
        return {"valid": True, "checked": len(rows), "first_broken_id": None}
```

Then wire the dual-write: in `backend/app/services/change_service.py`, inside `append_changelog`, directly before the final `return entry`, add:

```python
        from app.services.audit_service import AuditService  # local import avoids cycle
        await AuditService.record(
            session, entity_type="change", entity_id=change.id, action=action,
            user_id=performed_by, old_values=old_value, new_values=new_value,
            correlation_id=change.change_number,
        )
```

(Note: `append_changelog` currently ends with `session.add(entry)` then `return entry` — insert the block between them.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_audit.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the change suites to prove no regression from the dual-write**

Run: `cd backend && python3 -m pytest tests/test_changes.py tests/test_change_gates.py tests/test_change_cost.py tests/test_change_routing.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/audit_service.py backend/app/services/change_service.py backend/tests/test_audit.py
git commit -m "feat(audit): hash-chained AuditService + dual-write from change changelog"
```

---

## Task 2: Audit query / verify / export API

**Tier:** sonnet.

**Files:**
- Create: `backend/app/schemas/audit.py`, `backend/app/api/v1/audit.py`
- Modify: `backend/app/api/v1/__init__.py`
- Test: `backend/tests/test_audit.py`

**Interfaces:**
- Consumes: `AuditService.verify_chain` (Task 1); `AuditLog` model.
- Produces endpoints:
  - `GET /api/v1/audit?correlation_id=&entity_type=&entity_id=&user_id=&date_from=&date_to=&limit=&offset=` → `list[AuditEntryResponse]` ordered by id ascending, default `limit=200`.
  - `GET /api/v1/audit/verify` → `AuditVerifyResponse`.
  - `GET /api/v1/audit/export?correlation_id=...` → `text/csv` attachment (same filters as the list).

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_audit.py
async def test_audit_api_filters_by_correlation_id(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "api audit",
        "change_type": "physical_part"}, headers=eng_auth)
    number = res.json()["change_number"]
    listed = await client.get(f"/api/v1/audit?correlation_id={number}", headers=eng_auth)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert len(body) >= 1
    assert all(e["correlation_id"] == number for e in body)

    verify = await client.get("/api/v1/audit/verify", headers=eng_auth)
    assert verify.json()["valid"] is True

    export = await client.get(f"/api/v1/audit/export?correlation_id={number}", headers=eng_auth)
    assert export.status_code == 200
    assert "text/csv" in export.headers["content-type"]
    assert number in export.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_audit.py::test_audit_api_filters_by_correlation_id -v`
Expected: FAIL with 404 (route not registered)

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/schemas/audit.py
"""Response schemas for the unified audit timeline API."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AuditEntryResponse(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    action: str
    user_id: Optional[int] = None
    timestamp: datetime
    old_values: Optional[str] = None
    new_values: Optional[str] = None
    correlation_id: Optional[str] = None
    log_level: str

    class Config:
        from_attributes = True


class AuditVerifyResponse(BaseModel):
    valid: bool
    checked: int
    first_broken_id: Optional[int] = None
```

```python
# backend/app/api/v1/audit.py
"""Unified audit timeline: filterable list, chain verification, CSV export."""
import csv
import io
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.entities import AuditLog
from app.schemas.audit import AuditEntryResponse, AuditVerifyResponse
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit", tags=["audit"])


def _filtered(correlation_id, entity_type, entity_id, user_id, date_from, date_to):
    q = select(AuditLog).order_by(AuditLog.id)
    if correlation_id is not None:
        q = q.where(AuditLog.correlation_id == correlation_id)
    if entity_type is not None:
        q = q.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        q = q.where(AuditLog.entity_id == entity_id)
    if user_id is not None:
        q = q.where(AuditLog.user_id == user_id)
    if date_from is not None:
        q = q.where(AuditLog.timestamp >= date_from)
    if date_to is not None:
        q = q.where(AuditLog.timestamp <= date_to)
    return q


@router.get("", response_model=List[AuditEntryResponse])
async def list_audit(
    correlation_id: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[int] = Query(None),
    user_id: Optional[int] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = _filtered(correlation_id, entity_type, entity_id, user_id, date_from, date_to)
    rows = (await db.execute(q.limit(limit).offset(offset))).scalars().all()
    return rows


@router.get("/verify", response_model=AuditVerifyResponse)
async def verify_audit(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await AuditService.verify_chain(db)


@router.get("/export")
async def export_audit(
    correlation_id: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[int] = Query(None),
    user_id: Optional[int] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = _filtered(correlation_id, entity_type, entity_id, user_id, date_from, date_to)
    rows = (await db.execute(q)).scalars().all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "timestamp", "correlation_id", "entity_type", "entity_id",
                     "action", "user_id", "old_values", "new_values",
                     "previous_hash", "entry_hash"])
    for r in rows:
        writer.writerow([r.id, r.timestamp.isoformat(), r.correlation_id, r.entity_type,
                         r.entity_id, r.action, r.user_id, r.old_values, r.new_values,
                         r.previous_hash, r.entry_hash])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_export.csv"})
```

In `backend/app/api/v1/__init__.py`: add the import next to the changes import —

```python
from app.api.v1.audit import router as audit_router
```

and register it directly after `api_router.include_router(changes_router)`:

```python
api_router.include_router(audit_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_audit.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/audit.py backend/app/api/v1/audit.py backend/app/api/v1/__init__.py backend/tests/test_audit.py
git commit -m "feat(audit): timeline list, chain verify, and CSV export API"
```

---

## Task 3: `ChangeTransitionDeviation` model + migration 022 (table + gate seeding)

**Tier:** sonnet (model is mechanical; migration data-seed needs care).

**Files:**
- Modify: `backend/app/models/change.py`, `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/022_transition_deviations_hard_gates.py`
- Test: `backend/tests/test_change_deviations.py`

**Interfaces:**
- Produces: `ChangeTransitionDeviation(id, change_id, to_status: str, reason: str, status: str = "pending", proposed_by: int, proposed_at, decided_by: int | None, decided_at, decision_note: str | None)`; constant `DEVIATION_STATUSES = ("pending", "approved", "rejected", "consumed")`; `ChangeRequest.transition_deviations` relationship (selectin, delete-orphan).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_change_deviations.py
import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def test_deviation_model_persists(session_factory, seed):
    from app.models.change import (
        ChangeRequest, ChangeTransitionDeviation, DEVIATION_STATUSES,
    )
    async with session_factory() as s:
        change = ChangeRequest(
            change_number="CR-D-1", project_id=seed["project_id"], title="d",
            change_type="physical_part", status="captured",
            raised_by=seed["engineer_id"])
        s.add(change); await s.flush()
        s.add(ChangeTransitionDeviation(
            change_id=change.id, to_status="in_assessment",
            reason="PPT only at this stage", proposed_by=seed["engineer_id"]))
        await s.commit()
        dev = (await s.execute(select(ChangeTransitionDeviation))).scalar_one()
    assert dev.status == "pending"
    assert dev.to_status == "in_assessment"
    assert DEVIATION_STATUSES == ("pending", "approved", "rejected", "consumed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_change_deviations.py -v`
Expected: FAIL with `ImportError: cannot import name 'ChangeTransitionDeviation'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/models/change.py` (after `ChangeRoutingStandard`; `String`, `Text`, `DateTime`, `ForeignKey`, `Mapped`, `mapped_column`, `relationship`, `datetime` are already imported at the top of the file):

```python
DEVIATION_STATUSES = ("pending", "approved", "rejected", "consumed")


class ChangeTransitionDeviation(Base):
    """Formal 4-eyes bypass for a soft-blocked transition (replaces the old
    free-text justification override). Lifecycle: pending -> approved|rejected;
    an approved deviation is consumed by the transition that uses it."""
    __tablename__ = "change_transition_deviations"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)
    to_status: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="pending")
    proposed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    proposed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    change: Mapped["ChangeRequest"] = relationship(back_populates="transition_deviations")
```

Add to `ChangeRequest` (next to the `gates` relationship):

```python
    transition_deviations: Mapped[list["ChangeTransitionDeviation"]] = relationship(
        back_populates="change", cascade="all, delete-orphan", lazy="selectin",
    )
```

In `backend/app/models/__init__.py`, extend the `from app.models.change import (...)` block with `ChangeTransitionDeviation` and append `"ChangeTransitionDeviation",` to `__all__`.

Create `backend/alembic/versions/022_transition_deviations_hard_gates.py`:

```python
"""Transition deviations table + seed gate rows for in-flight changes.

Revision ID: 022
Revises: 021
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None

GATE_TARGETS = {"feasibility": "in_assessment", "budget": "costing",
                "release": "in_implementation"}
STATUS_ORDER = ["captured", "in_assessment", "costing", "quoted", "approved",
                "in_implementation", "in_validation", "released", "closed"]


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = insp.get_table_names()

    if "change_transition_deviations" not in tables:
        op.create_table(
            "change_transition_deviations",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("change_id", sa.Integer,
                      sa.ForeignKey("change_requests.id"), nullable=False, index=True),
            sa.Column("to_status", sa.String(30), nullable=False),
            sa.Column("reason", sa.Text, nullable=False),
            sa.Column("status", sa.String(15), nullable=False, server_default="pending"),
            sa.Column("proposed_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("proposed_at", sa.DateTime, nullable=True),
            sa.Column("decided_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
            sa.Column("decided_at", sa.DateTime, nullable=True),
            sa.Column("decision_note", sa.Text, nullable=True),
        )

    # Seed gate rows for in-flight changes at their current effective state:
    # a gate whose target status was already reached (per changelog, or implied
    # by the current status on the linear path) is seeded "yes", else "na".
    if "change_gate" in tables and "change_requests" in tables:
        changes = bind.execute(
            sa.text("SELECT id, status FROM change_requests")).fetchall()
        have = {(r[0], r[1]) for r in bind.execute(
            sa.text("SELECT change_id, gate_key FROM change_gate")).fetchall()}
        reached: dict = {}
        for cid, nv in bind.execute(sa.text(
                "SELECT change_id, new_value FROM change_changelog "
                "WHERE field_name = 'status'")).fetchall():
            reached.setdefault(cid, set()).add((nv or "").strip('"'))
        for cid, status in changes:
            seen = reached.get(cid, set())
            for key, target in GATE_TARGETS.items():
                if (cid, key) in have:
                    continue
                passed = target in seen or (
                    status in STATUS_ORDER
                    and STATUS_ORDER.index(status) >= STATUS_ORDER.index(target))
                bind.execute(sa.text(
                    "INSERT INTO change_gate (change_id, gate_key, decision) "
                    "VALUES (:c, :k, :d)"),
                    {"c": cid, "k": key, "d": "yes" if passed else "na"})


def downgrade() -> None:
    op.drop_table("change_transition_deviations")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_change_deviations.py -v`
Expected: PASS

- [ ] **Step 5: Verify the migration runs against the dev DB**

Run: `cd backend && python3 -m alembic upgrade head && python3 -m alembic current`
Expected: `022 (head)` with no traceback. Then sanity-check the seed:
`python3 -c "import sqlite3; db=sqlite3.connect('plm.db'); print(db.execute('select count(*) from change_gate').fetchone())"` — count ≥ 3 × number of changes.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/change.py backend/app/models/__init__.py backend/alembic/versions/022_transition_deviations_hard_gates.py backend/tests/test_change_deviations.py
git commit -m "feat(change): transition-deviation model + migration seeding gate rows"
```

---

## Task 4: Deviation propose/decide service (4-eyes) + API

**Tier:** opus (authorization rules).

**Files:**
- Modify: `backend/app/services/change_service.py`, `backend/app/schemas/change.py`, `backend/app/api/v1/changes/changes.py`
- Test: `backend/tests/test_change_deviations.py`

**Interfaces:**
- Consumes: `ChangeTransitionDeviation`, `DEVIATION_STATUSES` (Task 3).
- Produces:
  - `ChangeService.propose_transition_deviation(session, change, to_status: str, reason: str, user_id: int) -> ChangeTransitionDeviation`
  - `ChangeService.decide_transition_deviation(session, change, deviation_id: int, decision: str, actor: User, *, note: str | None = None) -> ChangeTransitionDeviation` — `decision` ∈ (`approved`, `rejected`); raises `ChangeError` on self-decision or unauthorized actor.
  - Endpoints: `GET /api/v1/changes/{change_id}/deviations` → `list[TransitionDeviationResponse]`; `POST /api/v1/changes/{change_id}/deviations` body `DeviationProposeIn{to_status, reason}`; `POST /api/v1/changes/{change_id}/deviations/{dev_id}/decide` body `DeviationDecideIn{decision, note?}`.
- 4-eyes rule (mirrors routing deviations): decider ≠ proposer; decider must be an admin, or the change lead, or (when the lead proposed) any other user.

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_change_deviations.py
async def _change(client, auth, seed, **over):
    body = {"project_id": seed["project_id"], "title": "dev flow",
            "change_type": "physical_part", "lead_id": seed["engineer_id"]}
    body.update(over)
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def test_propose_and_admin_approves(client, eng_auth, admin_auth, seed):
    c = await _change(client, eng_auth, seed)
    res = await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "PPT only"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    dev = res.json()
    assert dev["status"] == "pending"

    # 4-eyes: proposer cannot decide their own deviation
    veto = await client.post(
        f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
        json={"decision": "approved"}, headers=eng_auth)
    assert veto.status_code == 400
    assert "own" in veto.json()["detail"].lower()

    ok = await client.post(
        f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
        json={"decision": "approved", "note": "ok for capture-stage"}, headers=admin_auth)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"

    listed = await client.get(f"/api/v1/changes/{c['id']}/deviations", headers=eng_auth)
    assert listed.json()[0]["status"] == "approved"


async def test_reject_and_duplicate_pending_blocked(client, eng_auth, admin_auth, seed):
    c = await _change(client, eng_auth, seed)
    dev = (await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "r1"}, headers=eng_auth)).json()
    dup = await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "r2"}, headers=eng_auth)
    assert dup.status_code == 400
    rej = await client.post(
        f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
        json={"decision": "rejected", "note": "not enough info"}, headers=admin_auth)
    assert rej.json()["status"] == "rejected"
    # after rejection a new proposal is allowed again
    again = await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "r3"}, headers=eng_auth)
    assert again.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_change_deviations.py -v`
Expected: new tests FAIL with 404/405 (routes missing); `test_deviation_model_persists` still PASSES.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/change_service.py`:
- extend the models import: add `ChangeTransitionDeviation` to the `from app.models.change import (...)` block, and add `from app.models.entities import User` below it.
- add to `ChangeService`:

```python
    @staticmethod
    async def propose_transition_deviation(
        session: AsyncSession, change: ChangeRequest, to_status: str,
        reason: str, user_id: int,
    ) -> ChangeTransitionDeviation:
        if to_status not in CHANGE_STATUSES:
            raise ChangeError(f"Unknown status '{to_status}'")
        if not reason or not reason.strip():
            raise ChangeError("A reason is required to propose a deviation")
        if any(d.to_status == to_status and d.status == "pending"
               for d in change.transition_deviations):
            raise ChangeError("A deviation for this transition is already pending")
        dev = ChangeTransitionDeviation(
            change_id=change.id, to_status=to_status, reason=reason.strip(),
            proposed_by=user_id,
        )
        session.add(dev)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "deviation_proposed",
            f"Transition deviation to '{to_status}' proposed", user_id,
            field_name="deviation",
            new_value={"deviation_id": dev.id, "to_status": to_status},
            notes=reason.strip(),
        )
        return dev

    @staticmethod
    async def decide_transition_deviation(
        session: AsyncSession, change: ChangeRequest, deviation_id: int,
        decision: str, actor: User, *, note: Optional[str] = None,
    ) -> ChangeTransitionDeviation:
        if decision not in ("approved", "rejected"):
            raise ChangeError(f"Invalid deviation decision '{decision}'")
        dev = next((d for d in change.transition_deviations if d.id == deviation_id), None)
        if dev is None:
            raise ChangeError("Deviation not found")
        if dev.status != "pending":
            raise ChangeError(f"Deviation is '{dev.status}', not pending")
        if dev.proposed_by == actor.id:
            raise ChangeError("Cannot decide your own deviation (4-eyes rule)")
        if (actor.role != "admin" and actor.id != change.lead_id
                and dev.proposed_by != change.lead_id):
            raise ChangeError("Only the change lead or an admin may decide this deviation")
        dev.status = decision
        dev.decided_by = actor.id
        dev.decided_at = datetime.utcnow()
        dev.decision_note = note
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "deviation_decided",
            f"Deviation #{dev.id} ({dev.to_status}): {decision}", actor.id,
            field_name="deviation",
            new_value={"deviation_id": dev.id, "decision": decision},
            notes=note,
        )
        return dev
```

Append to `backend/app/schemas/change.py`:

```python
class DeviationProposeIn(BaseModel):
    to_status: str
    reason: str


class DeviationDecideIn(BaseModel):
    decision: str  # approved | rejected
    note: Optional[str] = None


class TransitionDeviationResponse(BaseModel):
    id: int
    to_status: str
    reason: str
    status: str
    proposed_by: int
    proposed_at: datetime
    decided_by: Optional[int] = None
    decided_at: Optional[datetime] = None
    decision_note: Optional[str] = None

    class Config:
        from_attributes = True
```

In `backend/app/api/v1/changes/changes.py`: extend the schema import with `DeviationProposeIn, DeviationDecideIn, TransitionDeviationResponse`, then add among the `/{change_id}/...` routes (after `put_gate`):

```python
@router.get("/{change_id}/deviations", response_model=List[TransitionDeviationResponse])
async def list_deviations(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change.transition_deviations


@router.post("/{change_id}/deviations", response_model=TransitionDeviationResponse)
async def propose_deviation(
    change_id: int, body: DeviationProposeIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        dev = await ChangeService.propose_transition_deviation(
            db, change, body.to_status, body.reason, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return dev


@router.post("/{change_id}/deviations/{dev_id}/decide",
             response_model=TransitionDeviationResponse)
async def decide_deviation(
    change_id: int, dev_id: int, body: DeviationDecideIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        dev = await ChangeService.decide_transition_deviation(
            db, change, dev_id, body.decision, current_user, note=body.note)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return dev
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_change_deviations.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/change_service.py backend/app/schemas/change.py backend/app/api/v1/changes/changes.py backend/tests/test_change_deviations.py
git commit -m "feat(change): 4-eyes transition-deviation propose/decide service + API"
```

---

## Task 5: Transition rework — deviation consumption replaces `justification`

**Tier:** opus (state machine).

**Files:**
- Modify: `backend/app/services/change_service.py`, `backend/app/schemas/change.py`, `backend/app/api/v1/changes/changes.py`
- Test: `backend/tests/test_change_deviations.py`, modify `backend/tests/test_changes.py`

**Interfaces:**
- Consumes: `propose/decide_transition_deviation` (Task 4).
- Produces: `ChangeService.transition(session, change, to_status, user_id, *, cancellation_reason=None)` — **`justification` parameter removed**. When `_guard` returns a reason, the transition succeeds only if an `approved` deviation for that `to_status` exists; it is set to `consumed` and the changelog action is `deviated_transition`. Otherwise `ChangeError("<reason>. An approved deviation is required to proceed.")`.
- `TransitionRequest` schema loses `justification` (keeps `to_status`, `cancellation_reason`).
- The `quoted → approved` hard requirements raise BEFORE any deviation logic and cannot be bypassed.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_change_deviations.py
async def test_blocked_transition_requires_approved_deviation(
        client, eng_auth, admin_auth, seed):
    c = await _change(client, eng_auth, seed)  # no impacted items -> guard blocks
    blocked = await client.post(f"/api/v1/changes/{c['id']}/transition",
                                json={"to_status": "in_assessment"}, headers=eng_auth)
    assert blocked.status_code == 400
    assert "deviation" in blocked.json()["detail"].lower()

    dev = (await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "PPT only at capture"},
        headers=eng_auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
                      json={"decision": "approved"}, headers=admin_auth)

    ok = await client.post(f"/api/v1/changes/{c['id']}/transition",
                           json={"to_status": "in_assessment"}, headers=eng_auth)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "in_assessment"

    # deviation is consumed and cannot be reused
    listed = (await client.get(f"/api/v1/changes/{c['id']}/deviations",
                               headers=eng_auth)).json()
    assert listed[0]["status"] == "consumed"

    log = (await client.get(f"/api/v1/changes/{c['id']}/changelog",
                            headers=eng_auth)).json()
    assert any(e["action"] == "deviated_transition" for e in log)
```

Note: this test passes only after Task 6 removes the gate pre-condition? No — gates are still only created by `create_change` after Task 6. At this point (Task 5) changes have no gate rows, so the only guard is "no impacted items", which the deviation bypasses. The test is valid now and stays valid after Task 6 *if* it approves the feasibility gate — Task 6 updates this test accordingly (see Task 6 Step 1).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_change_deviations.py::test_blocked_transition_requires_approved_deviation -v`
Expected: FAIL — the blocked response says "Provide a justification to override", not "deviation".

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/change_service.py`, `transition(...)`:

1. Change the signature — remove `justification`:

```python
    @staticmethod
    async def transition(
        session: AsyncSession, change: ChangeRequest, to_status: str,
        user_id: int, *, cancellation_reason: Optional[str] = None,
    ) -> ChangeRequest:
```

2. Replace the `forced = False ... forced = True` block with:

```python
        deviation = None
        reason = await ChangeService._guard(session, change, to_status)
        if reason is not None:
            deviation = next(
                (d for d in change.transition_deviations
                 if d.to_status == to_status and d.status == "approved"), None)
            if deviation is None:
                raise ChangeError(
                    f"{reason}. An approved deviation is required to proceed.")
            deviation.status = "consumed"
```

3. Replace the changelog block at the end of `transition` with:

```python
        old = change.status
        change.status = to_status
        await session.flush()
        action = "deviated_transition" if deviation else "status_changed"
        desc = f"{old} -> {to_status}" + (
            f" (deviation #{deviation.id}: {deviation.reason})" if deviation else "")
        await ChangeService.append_changelog(
            session, change, action, desc, user_id,
            field_name="status", old_value=old, new_value=to_status,
            notes=deviation.reason if deviation else None,
        )
        return change
```

In `backend/app/schemas/change.py`, `TransitionRequest` becomes:

```python
class TransitionRequest(BaseModel):
    to_status: str
    cancellation_reason: Optional[str] = None
```

In `backend/app/api/v1/changes/changes.py`, `transition_change` — drop the kwarg:

```python
        await ChangeService.transition(
            db, change, body.to_status, current_user.id,
            cancellation_reason=body.cancellation_reason,
        )
```

Update `backend/tests/test_changes.py`:

1. Replace `test_transition_requires_impacted_item_then_forced_override` entirely with:

```python
async def test_transition_blocked_without_impacted_items(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    res = await _transition(client, eng_auth, change["id"], "in_assessment")
    assert res.status_code == 400, res.text
    assert "deviation" in res.json()["detail"].lower()
```

(The full deviation-override flow is covered in `test_change_deviations.py`.)

2. At the line currently reading `res = await _transition(client, eng_auth, cid, "approved", justification="please")` (~line 186): remove the `justification="please"` argument.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_change_deviations.py tests/test_changes.py -v`
Expected: PASS

- [ ] **Step 5: Run the full change-related suites**

Run: `cd backend && python3 -m pytest tests/test_changes.py tests/test_change_gates.py tests/test_change_cost.py tests/test_change_routing.py tests/test_change_deviations.py tests/test_audit.py -q`
Expected: all PASS (routing/cost tests never used `justification`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_service.py backend/app/schemas/change.py backend/app/api/v1/changes/changes.py backend/tests/test_changes.py backend/tests/test_change_deviations.py
git commit -m "feat(change): deviation consumption replaces free-text justification override"
```

---

## Task 6: Hard gates — seeded at creation, always blocking, lead/admin-only decisions

**Tier:** sonnet (behavior flip is small; the work is the deliberate test migration).

**Files:**
- Modify: `backend/app/services/change_service.py`, `backend/app/api/v1/changes/changes.py`, `backend/tests/conftest.py`, `backend/tests/test_change_gates.py`, `backend/tests/test_changes.py`, `backend/tests/test_change_routing.py`, `backend/tests/test_change_deviations.py`

**Interfaces:**
- Produces: `create_change` seeds one `ChangeGate` row per `GATE_KEYS` entry (decision `na`) — so `_guard`'s existing gate loop now always constrains `in_assessment` / `costing` / `in_implementation`. `PUT /{change_id}/gates/{gate_key}` returns 403 unless the caller is the change lead or an admin. Test helper `approve_gates(client, auth, change_id, *keys)` in `tests/conftest.py` (approves all three gates when no keys given).
- Accepted residual: changes inserted directly into the DB (test fixtures) have no gate rows and are not gate-constrained; API-created changes and migration-seeded in-flight changes always are.

- [ ] **Step 1: Write/adjust the failing tests**

Append to `backend/tests/test_change_gates.py`:

```python
async def test_gates_exist_from_creation_and_block_by_default(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "hard", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    gates = (await client.get(f"/api/v1/changes/{cid}/gates", headers=eng_auth)).json()
    assert {g["gate_key"] for g in gates} == {"feasibility", "budget", "release"}
    assert all(g["decision"] == "na" for g in gates)
    # default 'na' blocks even when other guards would pass
    pres = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": "PG-H1", "name": "x",
        "part_type": "sub_assembly", "data_classification": "confidential"},
        headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": pres.json()["id"]}, headers=eng_auth)
    blocked = await client.post(f"/api/v1/changes/{cid}/transition",
                                json={"to_status": "in_assessment"}, headers=eng_auth)
    assert blocked.status_code == 400
    assert "gate" in blocked.json()["detail"].lower()


async def test_gate_decide_requires_lead_or_admin(client, eng_auth, admin_auth, seed):
    # lead is the ADMIN here, so the engineer must be rejected
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "authz", "change_type": "physical_part",
        "lead_id": seed["admin_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    denied = await client.put(f"/api/v1/changes/{cid}/gates/feasibility",
                              json={"decision": "yes"}, headers=eng_auth)
    assert denied.status_code == 403
    ok = await client.put(f"/api/v1/changes/{cid}/gates/feasibility",
                          json={"decision": "yes"}, headers=admin_auth)
    assert ok.status_code == 200, ok.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_change_gates.py -v`
Expected: the two new tests FAIL (gates list is empty at creation; engineer gets 200 not 403).

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/change_service.py`, `create_change` — after the existing `await session.flush()` and before the `append_changelog` call, add:

```python
        for key in GATE_KEYS:
            session.add(ChangeGate(change_id=change.id, gate_key=key))
        await session.flush()
```

In `backend/app/api/v1/changes/changes.py`, `put_gate` — after the 404 check, add:

```python
    if current_user.role != "admin" and change.lead_id != current_user.id:
        raise HTTPException(status_code=403,
                            detail="Only the change lead or an admin may decide gates")
```

Add to `backend/tests/conftest.py` (module level, next to `login`):

```python
async def approve_gates(client, auth, change_id: int, *keys):
    """Set the given change gates to 'yes' (all three when no keys given)."""
    for k in keys or ("feasibility", "budget", "release"):
        res = await client.put(
            f"/api/v1/changes/{change_id}/gates/{k}",
            json={"decision": "yes"}, headers=auth,
        )
        assert res.status_code == 200, res.text
```

- [ ] **Step 4: Update the existing tests that now hit hard gates**

All updates use `from tests.conftest import approve_gates`.

**`backend/tests/test_changes.py`:**
- Add the import at the top: `from tests.conftest import approve_gates`.
- Every test that POSTs a transition must (a) create the change with `lead_id=seed["engineer_id"]` (pass it via `_create_change(..., lead_id=seed["engineer_id"])` so `eng_auth` may decide gates) and (b) call `await approve_gates(client, eng_auth, change_id)` before its first transition. Affected tests: every test in this file that calls `_transition(...)` and expects 200 for `in_assessment`/`costing`/`in_implementation` (walk the file; the full-lifecycle test needs all three gates, which the helper's no-keys default covers). Tests asserting a 400 for a *different* guard (e.g. `test_transition_blocked_without_impacted_items` from Task 5) must ALSO approve gates first so the assertion still targets the intended guard — update that test to create with `lead_id=seed["engineer_id"]`, call `approve_gates`, and keep asserting 400 ("no impacted items" is still a blocker).
- `test_illegal_transition_rejected` and `test_cancel_requires_reason` need no gate changes (structurally-illegal transitions and cancellation are not gate targets).

**`backend/tests/test_change_routing.py`:**
- Add the import: `from tests.conftest import approve_gates`.
- In `_api_change_in_assessment` (line ~151), right after the change is created, add `await approve_gates(client, auth, c["id"])`. This unblocks `in_assessment` and later `costing` transitions in all tests using the helper.
- Two tests (~lines 317, 367) build changes inline without the helper; add the same `approve_gates` call after their change creation.
- Tests asserting `costing` returns 400 while blocking assessments are pending still pass — the assessment guard fires independently of gates.

**`backend/tests/test_change_gates.py`:**
- `test_gate_blocks_transition_until_yes`: unchanged in spirit — but it now must NOT rely on the gate row being absent initially. It already PUTs `feasibility` explicitly; verify it still passes as written.

**`backend/tests/test_change_deviations.py`:**
- `test_blocked_transition_requires_approved_deviation`: the change now also has `na` gates. Since the deviation bypasses ALL guard reasons for its `to_status` (gates included), the test still passes — the block reason simply becomes the gate. Keep as-is; it now doubles as the gate-bypass-by-deviation test.

**`backend/tests/test_change_cost.py`:** no changes — its changes are either created in `captured` (no transition) or inserted directly in the DB.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && python3 -m pytest -q`
Expected: ALL tests pass. If a transition site was missed, the failure message names the gate — fix by adding `approve_gates` at that site.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/change_service.py backend/app/api/v1/changes/changes.py backend/tests/conftest.py backend/tests/test_change_gates.py backend/tests/test_changes.py backend/tests/test_change_routing.py backend/tests/test_change_deviations.py
git commit -m "feat(change): hard gates seeded at creation with lead/admin-only decisions"
```

---

## Task 7: Frontend — deviation banner + reason dialog replace `window.prompt`

**Tier:** sonnet (follow existing component conventions; check `D1MasterPanel.test.tsx` for the test wrapper pattern before writing the test).

**Files:**
- Create: `frontend/src/components/changes/ReasonDialog.tsx`, `frontend/src/components/changes/DeviationBanner.tsx`, `frontend/src/components/changes/DeviationBanner.test.tsx`
- Modify: `frontend/src/types/change.ts`, `frontend/src/api/changes.ts`, `frontend/src/pages/ChangeDetailPage.tsx`

**Interfaces:**
- Consumes: `GET/POST /changes/{id}/deviations`, `POST .../deviations/{devId}/decide` (Task 4); transition API without `justification` (Task 5).
- Produces:
  - `TransitionDeviation` type.
  - `changesApi.listDeviations(id)`, `proposeDeviation(id, {to_status, reason})`, `decideDeviation(id, devId, {decision, note?})`.
  - `<ReasonDialog open title label submitLabel onSubmit(reason) onClose />`.
  - `<DeviationBanner changeId blockedTo blockedReason onRetry onClose />`.

- [ ] **Step 1: Write the failing test**

First read `frontend/src/components/changes/D1MasterPanel.test.tsx` and mirror its render-wrapper/mocking conventions. The test below assumes the standard pattern (adapt imports/wrapper to match the existing file):

```tsx
// frontend/src/components/changes/DeviationBanner.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import DeviationBanner from './DeviationBanner';
import { changesApi } from '../../api/changes';

vi.mock('../../api/changes', () => ({
  changesApi: {
    listDeviations: vi.fn().mockResolvedValue([]),
    proposeDeviation: vi.fn().mockResolvedValue({ id: 1, status: 'pending' }),
    decideDeviation: vi.fn(),
  },
}));

function renderBanner() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DeviationBanner
        changeId={7}
        blockedTo="in_assessment"
        blockedReason="No impacted items added yet. An approved deviation is required to proceed."
        onRetry={() => {}}
        onClose={() => {}}
      />
    </QueryClientProvider>
  );
}

describe('DeviationBanner', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows the block reason', async () => {
    renderBanner();
    expect(await screen.findByText(/No impacted items/)).toBeInTheDocument();
  });

  it('proposes a deviation with the entered reason', async () => {
    renderBanner();
    fireEvent.click(await screen.findByRole('button', { name: /request deviation/i }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'PPT only' } });
    fireEvent.click(screen.getByRole('button', { name: /submit/i }));
    await waitFor(() =>
      expect(changesApi.proposeDeviation).toHaveBeenCalledWith(7, {
        to_status: 'in_assessment', reason: 'PPT only',
      })
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/changes/DeviationBanner.test.tsx`
Expected: FAIL — `Cannot find module './DeviationBanner'`

- [ ] **Step 3: Write the implementation**

Add to `frontend/src/types/change.ts`:

```ts
export interface TransitionDeviation {
  id: number;
  to_status: string;
  reason: string;
  status: 'pending' | 'approved' | 'rejected' | 'consumed';
  proposed_by: number;
  proposed_at: string;
  decided_by?: number | null;
  decided_at?: string | null;
  decision_note?: string | null;
}
```

In `frontend/src/api/changes.ts`: import the type, change `transition` to drop `justification`, and add the three deviation calls:

```ts
  transition: (id: number, to_status: string, opts?: { cancellation_reason?: string }) =>
    client.post<ChangeRequest>(`/v1/changes/${id}/transition`, { to_status, ...opts }).then((r) => r.data),

  listDeviations: (id: number) =>
    client.get<TransitionDeviation[]>(`/v1/changes/${id}/deviations`).then((r) => r.data),
  proposeDeviation: (id: number, body: { to_status: string; reason: string }) =>
    client.post<TransitionDeviation>(`/v1/changes/${id}/deviations`, body).then((r) => r.data),
  decideDeviation: (id: number, devId: number, body: { decision: 'approved' | 'rejected'; note?: string }) =>
    client.post<TransitionDeviation>(`/v1/changes/${id}/deviations/${devId}/decide`, body).then((r) => r.data),
```

Create `frontend/src/components/changes/ReasonDialog.tsx`:

```tsx
import { useState } from 'react';

interface Props {
  open: boolean;
  title: string;
  label: string;
  submitLabel?: string;
  onSubmit: (reason: string) => void;
  onClose: () => void;
}

export default function ReasonDialog({ open, title, label, submitLabel = 'Submit', onSubmit, onClose }: Props) {
  const [reason, setReason] = useState('');
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" role="dialog">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-5">
        <h3 className="text-base font-semibold mb-2">{title}</h3>
        <label className="block text-sm text-gray-600 mb-1">{label}</label>
        <textarea
          className="w-full border rounded-lg p-2 text-sm min-h-[80px]"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          autoFocus
        />
        <div className="flex justify-end gap-2 mt-4">
          <button className="px-3 py-1.5 text-sm border rounded-lg" onClick={onClose}>Cancel</button>
          <button
            className="px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white disabled:opacity-50"
            disabled={!reason.trim()}
            onClick={() => { onSubmit(reason.trim()); setReason(''); }}
          >{submitLabel}</button>
        </div>
      </div>
    </div>
  );
}
```

Create `frontend/src/components/changes/DeviationBanner.tsx`:

```tsx
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import ReasonDialog from './ReasonDialog';

interface Props {
  changeId: number;
  blockedTo: string;
  blockedReason: string;
  onRetry: () => void;
  onClose: () => void;
}

const STATUS_STYLE: Record<string, string> = {
  pending: 'bg-amber-100 text-amber-800',
  approved: 'bg-green-100 text-green-800',
  rejected: 'bg-red-100 text-red-700',
  consumed: 'bg-gray-100 text-gray-500',
};

export default function DeviationBanner({ changeId, blockedTo, blockedReason, onRetry, onClose }: Props) {
  const qc = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);

  const { data: deviations = [] } = useQuery({
    queryKey: ['change', changeId, 'deviations'],
    queryFn: () => changesApi.listDeviations(changeId),
  });
  const propose = useMutation({
    mutationFn: (reason: string) =>
      changesApi.proposeDeviation(changeId, { to_status: blockedTo, reason }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change', changeId, 'deviations'] }),
  });
  const decide = useMutation({
    mutationFn: (vars: { devId: number; decision: 'approved' | 'rejected' }) =>
      changesApi.decideDeviation(changeId, vars.devId, { decision: vars.decision }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change', changeId, 'deviations'] }),
    onError: (e: any) => alert(e?.response?.data?.detail ?? 'Decision failed'),
  });

  const relevant = deviations.filter((d) => d.to_status === blockedTo);
  const hasApproved = relevant.some((d) => d.status === 'approved');
  const hasPending = relevant.some((d) => d.status === 'pending');

  return (
    <div className="border border-amber-300 bg-amber-50 rounded-xl p-4 my-3 text-sm" data-testid="deviation-banner">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-medium text-amber-900">Transition blocked</p>
          <p className="text-amber-800 mt-0.5">{blockedReason}</p>
        </div>
        <button className="text-amber-700 text-xs" onClick={onClose}>Dismiss</button>
      </div>

      {relevant.length > 0 && (
        <ul className="mt-3 space-y-1">
          {relevant.map((d) => (
            <li key={d.id} className="flex items-center gap-2">
              <span className={`px-2 py-0.5 rounded-full text-xs ${STATUS_STYLE[d.status]}`}>{d.status}</span>
              <span className="text-gray-700">{d.reason}</span>
              {d.status === 'pending' && (
                <span className="ml-auto flex gap-1">
                  <button className="px-2 py-0.5 text-xs border rounded-lg text-green-700"
                          onClick={() => decide.mutate({ devId: d.id, decision: 'approved' })}>Approve</button>
                  <button className="px-2 py-0.5 text-xs border rounded-lg text-red-600"
                          onClick={() => decide.mutate({ devId: d.id, decision: 'rejected' })}>Reject</button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="flex gap-2 mt-3">
        {!hasPending && !hasApproved && (
          <button className="px-3 py-1.5 rounded-lg bg-amber-600 text-white text-xs"
                  onClick={() => setDialogOpen(true)}>Request deviation</button>
        )}
        {hasApproved && (
          <button className="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs"
                  onClick={onRetry}>Retry transition</button>
        )}
      </div>

      <ReasonDialog
        open={dialogOpen}
        title={`Deviation for transition to "${blockedTo}"`}
        label="Reason (recorded in the audit trail, requires 4-eyes approval)"
        submitLabel="Submit"
        onSubmit={(reason) => { propose.mutate(reason); setDialogOpen(false); }}
        onClose={() => setDialogOpen(false)}
      />
    </div>
  );
}
```

Modify `frontend/src/pages/ChangeDetailPage.tsx`:

1. Add imports:

```tsx
import DeviationBanner from '../components/changes/DeviationBanner';
import ReasonDialog from '../components/changes/ReasonDialog';
```

2. Add state next to `const [tab, setTab] = ...`:

```tsx
const [blocked, setBlocked] = useState<{ to: string; reason: string } | null>(null);
const [cancelOpen, setCancelOpen] = useState(false);
```

3. Replace the `transition` mutation's `onError`/`onSuccess`:

```tsx
  const transition = useMutation({
    mutationFn: (vars: { to: string; cancellation_reason?: string }) =>
      changesApi.transition(changeId, vars.to, vars),
    onSuccess: () => {
      setBlocked(null);
      qc.invalidateQueries({ queryKey: ['change', changeId] });
    },
    onError: (e: any, vars) => {
      const detail = e?.response?.data?.detail ?? 'Transition failed';
      if (vars.to !== 'cancelled') setBlocked({ to: vars.to, reason: detail });
      else alert(detail);
    },
  });
```

4. Replace the whole `advance` function (removing both `window.prompt` calls):

```tsx
  const advance = (to: string) => {
    if (to === 'cancelled') { setCancelOpen(true); return; }
    transition.mutate({ to });
  };
```

5. Directly under `<Stepper status={change.status} />` render the banner and dialog:

```tsx
      {blocked && (
        <DeviationBanner
          changeId={changeId}
          blockedTo={blocked.to}
          blockedReason={blocked.reason}
          onRetry={() => transition.mutate({ to: blocked.to })}
          onClose={() => setBlocked(null)}
        />
      )}
      <ReasonDialog
        open={cancelOpen}
        title="Cancel change"
        label="Cancellation reason (required, audited)"
        submitLabel="Cancel change"
        onSubmit={(reason) => { setCancelOpen(false); transition.mutate({ to: 'cancelled', cancellation_reason: reason }); }}
        onClose={() => setCancelOpen(false)}
      />
```

- [ ] **Step 4: Run test + type check to verify**

Run: `cd frontend && npx vitest run src/components/changes/DeviationBanner.test.tsx && npx tsc --noEmit`
Expected: tests PASS, no type errors (a leftover `justification` usage anywhere would fail the type check).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/change.ts frontend/src/api/changes.ts frontend/src/components/changes/ReasonDialog.tsx frontend/src/components/changes/DeviationBanner.tsx frontend/src/components/changes/DeviationBanner.test.tsx frontend/src/pages/ChangeDetailPage.tsx
git commit -m "feat(change): deviation banner + reason dialog replace window.prompt"
```

---

## Task 8: Final verification

**Tier:** opus (review pass).

- [ ] **Step 1: Full backend suite**

Run: `cd backend && python3 -m pytest -q`
Expected: ALL pass, 0 failures.

- [ ] **Step 2: Frontend tests + types**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: ALL pass, no type errors.

- [ ] **Step 3: End-to-end smoke via the running app**

Start backend (`./run_backend.sh`) + frontend (`cd frontend && npm run dev`), then walk one change through: create → gates show as `na` in the D1 panel → transition blocked with banner → request deviation as engineer → approve as admin (second browser/user) → retry succeeds → check the Audit tab shows `deviation_proposed`, `deviation_decided`, `deviated_transition` → `GET /api/v1/audit/verify` returns `valid: true`.

- [ ] **Step 4: Commit any smoke-test fixes, then update memory**

Update `memory/change-management-roadmap.md`: Phase A status → BUILT, note the commit range.
