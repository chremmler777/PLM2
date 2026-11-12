"""SEP work items and SEP risk rows as lines of the project LOP.

A line only references its source (`ref_key` = SEP item id, or the risk row's
`lop_key`); closing the line and closing the source are the same record.
SEP items enter only through the Project Manager (`add_sep_item`,
`add_sep_gate`); risk rows with a countermeasure and a due date enter
automatically (`sync_project_lines`, run when a LOP is opened).
Datetimes are naive UTC.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.forms.risks import (
    LOP_KEY, ensure_risk_keys, risk_rows_by_key, set_risk_row_status,
)
from app.forms.service import FormError
from app.models.entities import User
from app.models.lop import LopEvent, LopLine
from app.models.sep import SepGate, SepWorkItem
from app.services.lop_departments import SEP_DEPARTMENT_MAP, department_id_for
from app.services.lop_service import (
    PM_DEPARTMENT, LopConflict, LopError, LopForbidden, LopNotFound, LopService,
)
from app.services.project_team_service import ProjectTeamService
from app.services.sep_status import apply_item_status

logger = logging.getLogger(__name__)

SOURCE_KINDS = ("sep_item", "risk")
SEP_CLOSED_ITEM = ("done", "not_applicable")


# ------------------------------------------------------------ line changes
def _event(session: AsyncSession, line: LopLine, user_id: Optional[int], field: str,
           old, new, reason: Optional[str] = None) -> None:
    session.add(LopEvent(line_id=line.id, user_id=user_id, field=field, reason=reason,
                         old_value=None if old is None else str(old),
                         new_value=None if new is None else str(new)))


def _close_line(session: AsyncSession, line: LopLine, by: Optional[int],
                at: Optional[datetime], reason: str) -> None:
    """The source closed: the line is closed from that moment, by that person."""
    at = at or datetime.utcnow()
    _event(session, line, by, "status", line.status, "closed", reason)
    line.status, line.closed_at, line.closed_by = "closed", at, by
    line.last_update_at, line.last_update_by = at, by


def _reopen_line(session: AsyncSession, line: LopLine, by: Optional[int], reason: str) -> None:
    now = datetime.utcnow()
    _event(session, line, by, "status", "closed", "open", reason)
    line.status, line.closed_at, line.closed_by = "open", None, None
    line.last_update_at, line.last_update_by = now, by


# ------------------------------------------------------- source of a line
def _item_source(line: LopLine, item: SepWorkItem, gate: SepGate) -> dict:
    gate_closed = gate.status == "closed"
    closed = gate_closed or item.status in SEP_CLOSED_ITEM
    closed_at = item.completed_at if item.status in SEP_CLOSED_ITEM else (
        gate.closed_at if gate_closed else None)
    return {"text": item.title_en or item.title_de, "label": f"SEP {gate.code} item {item.item_no}",
            "closed": closed, "closed_at": closed_at, "context": None}


def _risk_source(line: LopLine, row: Optional[dict]) -> dict:
    if row is None:           # row deleted from the form: nothing left to do
        return {"text": line.title or "Risk row removed", "label": "SEP risk",
                "closed": True, "closed_at": None, "context": None}
    cm = (row.get("countermeasure") or "").strip()
    return {"text": cm or (row.get("risk") or ""), "label": "SEP risk",
            "closed": row.get("status") == "finished", "closed_at": None,
            "context": (row.get("risk") or "").strip() or None}


async def load_sources(session: AsyncSession, lines: list[LopLine]) -> dict[int, dict]:
    """line id -> {text, label, closed, closed_at, context} for SEP item and
    risk lines (other kinds are not in the result)."""
    out: dict[int, dict] = {}
    items = [ln for ln in lines if ln.kind == "sep_item" and ln.ref_key]
    if items:
        rows = {i.id: (i, g) for i, g in (await session.execute(
            select(SepWorkItem, SepGate).join(SepGate, SepGate.id == SepWorkItem.gate_id)
            .where(SepWorkItem.id.in_([int(ln.ref_key) for ln in items])))).all()}
        for ln in items:
            hit = rows.get(int(ln.ref_key))
            out[ln.id] = (_item_source(ln, *hit) if hit else
                          {"text": ln.title or "SEP item removed", "label": "SEP item",
                           "closed": True, "closed_at": None, "context": None})
    by_project: dict[int, list[LopLine]] = {}
    for ln in lines:
        if ln.kind == "risk":
            by_project.setdefault(ln.project_id, []).append(ln)
    for pid, rlines in by_project.items():
        rows = await risk_rows_by_key(session, pid) or {}
        for ln in rlines:
            out[ln.id] = _risk_source(ln, rows.get(ln.ref_key))
    return out


# --------------------------------------------- LOP write -> source
async def _item_and_gate(session: AsyncSession, line: LopLine):
    if line.kind != "sep_item" or not line.ref_key:
        return None, None
    item = await session.get(SepWorkItem, int(line.ref_key))
    return item, (await session.get(SepGate, item.gate_id) if item else None)


async def assert_editable(session: AsyncSession, line: LopLine) -> None:
    """A line whose SEP gate is closed is locked, like the gate's items."""
    _, gate = await _item_and_gate(session, line)
    if gate is not None and gate.status == "closed":
        raise LopConflict("The SEP gate is closed; this line is locked")


async def push_status(session: AsyncSession, line: LopLine, user: User,
                      old: str, new: str) -> None:
    """Closing a line completes its source; reopening it reopens the source."""
    if line.kind not in SOURCE_KINDS or (new != "closed" and old != "closed"):
        return
    closing = new == "closed"
    if line.kind == "sep_item":
        item, _ = await _item_and_gate(session, line)
        if item is not None:
            apply_item_status(session, item, "done" if closing else "open", user.id)
            if closing:
                line.closed_at = item.completed_at or line.closed_at
    else:
        try:
            await set_risk_row_status(session, line.project_id, line.ref_key,
                                      "finished" if closing else "started", user)
        except FormError as e:
            raise LopConflict(e.detail if e.status == 409
                              else f"The risk form cannot be saved: {e.detail}")


# --------------------------------------------- SEP view write -> LOP
async def _line_for_item(session: AsyncSession, item: SepWorkItem) -> Optional[LopLine]:
    return (await session.execute(select(LopLine).where(
        LopLine.project_id == item.project_id, LopLine.kind == "sep_item",
        LopLine.ref_key == str(item.id)))).scalar_one_or_none()


async def report_done_instead(session: AsyncSession, item: SepWorkItem,
                              new_status: str, user: User) -> bool:
    """A caller who may not manage the project's LOP cannot set an item that has
    an open line to done / not applicable: the line becomes done_check and the
    item stays open. True when that happened (the caller skips the status)."""
    if new_status not in SEP_CLOSED_ITEM:
        return False
    line = await _line_for_item(session, item)
    if line is None or line.status == "closed":
        return False
    if await LopService.can_manage(session, user, item.project_id):
        return False
    if line.status != "done_check":
        _event(session, line, user.id, "status", line.status, "done_check",
               f"reported done in the SEP view ({new_status})")
        line.status = "done_check"
        line.last_update_at, line.last_update_by = datetime.utcnow(), user.id
    return True


async def item_status_changed(session: AsyncSession, item: SepWorkItem, user_id: int) -> None:
    """The item's status was set in the SEP view: its line follows."""
    line = await _line_for_item(session, item)
    if line is None:
        return
    if item.status in SEP_CLOSED_ITEM and line.status != "closed":
        _close_line(session, line, user_id, datetime.utcnow(), f"SEP item set to {item.status}")
    elif item.status == "open" and line.status == "closed":
        _reopen_line(session, line, user_id, "SEP item reopened")


async def item_line_status(session: AsyncSession, item: SepWorkItem) -> Optional[str]:
    line = await _line_for_item(session, item)
    return line.status if line is not None else None


async def _insert_line(session: AsyncSession, line: LopLine) -> bool:
    """Insert in a savepoint. False when the same source is already a line
    (another request was first): the caller re-reads it instead of failing."""
    try:
        async with session.begin_nested():
            session.add(line)
            await session.flush()
    except IntegrityError:
        return False
    return True


async def _existing(session: AsyncSession, project_id: int, kind: str, ref_key: str) -> LopLine:
    return (await session.execute(select(LopLine).where(
        LopLine.project_id == project_id, LopLine.kind == kind,
        LopLine.ref_key == ref_key))).scalar_one()


# ------------------------------------------------------------ SEP items in
async def _new_sep_line(session: AsyncSession, user: User, project_id: int,
                        item: SepWorkItem, gate: SepGate, due: Optional[date],
                        resolved: dict[int, tuple]) -> tuple[LopLine, bool]:
    """(line, created); an item that is already a line returns that line."""
    dept_id = await department_id_for(session, SEP_DEPARTMENT_MAP, item.department)
    if dept_id not in resolved:
        resolved[dept_id] = await LopService.resolve_responsible(session, project_id, dept_id)
    uid, uid_default = resolved[dept_id]
    due_is_default = False
    if due is None and gate.target_date is not None:
        due, due_is_default = gate.target_date.date(), True
    now = datetime.utcnow()
    line = LopLine(
        project_id=project_id, kind="sep_item", ref_key=str(item.id),
        department_id=dept_id, responsible_id=uid, responsible_is_default=uid_default,
        due_date=due, first_due_date=due, due_is_default=due_is_default,
        status="open" if dept_id is not None and due is not None else "new",
        created_by=user.id, created_at=now, last_update_at=now, last_update_by=user.id)
    if not await _insert_line(session, line):
        return await _existing(session, project_id, "sep_item", str(item.id)), False
    _event(session, line, user.id, "created", None, f"SEP {gate.code} item {item.item_no}")
    return line, True


async def _require_manager(session: AsyncSession, user: User, project_id: int) -> None:
    await LopService.get_project(session, project_id, user)
    if not await LopService.can_manage(session, user, project_id):
        raise LopForbidden("Only the Project Manager adds lines")


async def add_sep_item(session: AsyncSession, user: User, project_id: int, item_id: int,
                       due_date: Optional[date] = None) -> tuple[LopLine, bool]:
    """(line, created). An item that is already a line returns that line."""
    await _require_manager(session, user, project_id)
    item = await session.get(SepWorkItem, item_id)
    if item is None or item.project_id != project_id:
        raise LopNotFound("SEP item not found")
    existing = await _line_for_item(session, item)
    if existing is not None:
        return existing, False
    if item.status != "open":
        raise LopError("Only an open SEP item can be added")
    gate = await session.get(SepGate, item.gate_id)
    if gate.status == "closed":
        raise LopConflict("The SEP gate is closed; its items are locked")
    line, created = await _new_sep_line(session, user, project_id, item, gate, due_date, {})
    await session.commit()
    return line, created


async def add_sep_gate(session: AsyncSession, user: User, project_id: int,
                       gate_id: int) -> list[LopLine]:
    """Add every open item of the gate that is not a line yet; returns the new lines."""
    await _require_manager(session, user, project_id)
    gate = await session.get(SepGate, gate_id)
    if gate is None or gate.project_id != project_id:
        raise LopNotFound("SEP gate not found")
    if gate.status == "closed":
        raise LopConflict("The SEP gate is closed; its items are locked")
    items = (await session.execute(select(SepWorkItem).where(
        SepWorkItem.gate_id == gate.id, SepWorkItem.status == "open")
        .order_by(SepWorkItem.item_no))).scalars().all()
    have = set((await session.execute(select(LopLine.ref_key).where(
        LopLine.project_id == project_id, LopLine.kind == "sep_item"))).scalars().all())
    resolved: dict[int, tuple] = {}
    out = []
    for i in items:
        if str(i.id) in have:
            continue
        line, created = await _new_sep_line(session, user, project_id, i, gate, None, resolved)
        if created:
            out.append(line)
    await session.commit()
    return out


async def sep_candidates(session: AsyncSession, project_id: int) -> list[dict]:
    """Open SEP items not yet in the LOP, by gate (closed gates left out)."""
    have = set((await session.execute(select(LopLine.ref_key).where(
        LopLine.project_id == project_id, LopLine.kind == "sep_item"))).scalars().all())
    rows = (await session.execute(
        select(SepGate, SepWorkItem).join(SepWorkItem, SepWorkItem.gate_id == SepGate.id)
        .where(SepGate.project_id == project_id, SepGate.status != "closed",
               SepWorkItem.status == "open")
        .order_by(SepGate.seq, SepWorkItem.item_no))).all()
    gates: dict[int, dict] = {}
    for gate, item in rows:
        if str(item.id) in have:
            continue
        g = gates.setdefault(gate.id, {
            "gate_id": gate.id, "code": gate.code, "status": gate.status,
            "target_date": gate.target_date.date().isoformat() if gate.target_date else None,
            "items": []})
        g["items"].append({"id": item.id, "item_no": item.item_no,
                           "title": item.title_en or item.title_de,
                           "department": item.department})
    return list(gates.values())


# ---------------------------------------------------------------- risks in
def _date(v) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _uid(v) -> Optional[int]:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


RISK_ROW_REASON = "SEP risk row changed"


async def sync_project_lines(session: AsyncSession, project_id: int, reader_id: int,
                             *, full: bool = True) -> None:
    """Idempotent; writes only when something changed, never deletes.
    full: 1. every risk row gets a `lop_key` (own form event); 2. a row with a
    countermeasure and a due date becomes a line; 3. a line the PM never gave
    another date follows its row's due date. Always: lines follow their source,
    closed when it closed (SEP item done / gate closed / row finished or
    removed), open again when it reopened. SEP items are never added here.
    System writes are attributed to the project's PM, else to the reader."""
    pm = await ProjectTeamService.responsible_user_id(
        session, project_id, PM_DEPARTMENT, backup=True)
    actor_id = pm or reader_id
    changed = False
    if full:
        changed = bool(await ensure_risk_keys(session, project_id, actor_id))
    rows = await risk_rows_by_key(session, project_id) or {}
    lines = list((await session.execute(select(LopLine).where(
        LopLine.project_id == project_id, LopLine.kind.in_(SOURCE_KINDS)))).scalars().all())

    if full:
        by_key = {ln.ref_key: ln for ln in lines if ln.kind == "risk"}
        team = await LopService.team_user_ids(session, project_id) if any(
            k not in by_key for k in rows) else set()
        pm_moved = set((await session.execute(select(LopEvent.line_id).where(
            LopEvent.line_id.in_([ln.id for ln in by_key.values()] or [0]),
            LopEvent.field == "due_date",
            (LopEvent.reason.is_(None)) | (LopEvent.reason != RISK_ROW_REASON)))).scalars().all())
        for key, row in rows.items():
            due = _date(row.get("due"))
            ln = by_key.get(key)
            if ln is not None:
                if (due is not None and ln.status != "closed" and due != ln.due_date
                        and ln.id not in pm_moved):
                    _event(session, ln, None, "due_date", ln.due_date, due, RISK_ROW_REASON)
                    ln.due_date = ln.first_due_date = due
                    ln.due_is_default = False
                    changed = True
                continue
            if row.get("status") == "finished":
                continue
            if not (row.get("countermeasure") or "").strip() or due is None:
                continue
            uid, is_default = _uid(row.get("responsible")), False
            if uid is None or uid not in team:
                uid, is_default = pm, bool(pm)
            now = datetime.utcnow()
            line = LopLine(
                project_id=project_id, kind="risk", ref_key=key, responsible_id=uid,
                responsible_is_default=is_default, due_date=due, first_due_date=due,
                status="open", created_by=actor_id, created_at=now,
                last_update_at=now, last_update_by=actor_id)
            if await _insert_line(session, line):
                _event(session, line, actor_id, "created", None, "SEP risk")
                lines.append(line)
                changed = True

    sources = await load_sources(session, lines)
    for ln in lines:
        src = sources[ln.id]
        if src["closed"] and ln.status != "closed":
            _close_line(session, ln, None, src["closed_at"], "source closed")
            changed = True
        elif not src["closed"] and ln.status == "closed":
            _reopen_line(session, ln, None, "source reopened")
            changed = True
    if changed:
        await session.commit()
