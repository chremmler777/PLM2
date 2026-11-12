"""Control KPIs of the project LOPs: per project, per department, in total.

Read-only: nothing here writes form data. Lines are the LopLines (tasks, SEP
items, risks, pinned PDB topics). Unpinned PDB topics are not lines; they only
show up in the project's `pdb` block and as `pdb_without_name_and_date`.
Business dates (LOP time zone) everywhere; datetimes are stored naive UTC.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import Plant, Project, User
from app.models.lop import LopEvent, LopLine, LopMeeting, LopMeetingMark
from app.models.sep import SepGate
from app.services import lop_rules as rules
from app.services import lop_sources, pdb_client
from app.services.lop_meetings import LopMeetings
from app.services.lop_service import LopNotFound, LopService, _today, local_date

logger = logging.getLogger(__name__)

WINDOW_MONTH = 28
WINDOW_WEEK = 7
FLAGS = ("open", "stale", "late", "no_control", "untouched")
NO_DEPARTMENT = "No department"
SEP_ITEM_DONE = ("done", "not_applicable")


def pct(part: int, whole: int) -> Optional[int]:
    """Integer percentage, rounded half up; None without a whole."""
    return None if whole <= 0 else (200 * part + whole) // (2 * whole)


def _code_key(code: str) -> tuple:
    c = (code or "").strip()
    return (0, int(c), "") if c.isascii() and c.isdigit() else (1, 0, c.lower())


@dataclass
class Item:
    line: LopLine
    d: dict
    state: rules.LineState
    project: Project
    untouched: bool = False
    moves_4w: int = 0

    @property
    def open(self) -> bool:
        return self.d["status"] != "closed"


@dataclass
class Scope:
    projects: list[Project]
    items: dict[int, list[Item]]            # project id -> items, in line order
    today: date


# ----------------------------------------------------------------- loading
async def scoped_projects(db: AsyncSession, user: User,
                          project_id: Optional[int] = None) -> list[Project]:
    """LOP projects of the caller's organization, by project number."""
    q = (select(Project).join(Plant, Plant.id == Project.plant_id)
         .where(Plant.organization_id == user.organization_id, Project.lop_enabled.is_(True)))
    if project_id is not None:
        q = q.where(Project.id == project_id)
    projects = list((await db.execute(q)).scalars().all())
    if project_id is not None and not projects:
        raise LopNotFound("Project not found")
    return sorted(projects, key=lambda p: (_code_key(p.code), p.id))


async def _sync_sources(db: AsyncSession, user: User, project_ids: list[int]) -> None:
    """Lines whose source closed or reopened follow it (no form writes)."""
    if not project_ids:
        return
    with_sources = (await db.execute(
        select(LopLine.project_id).where(
            LopLine.project_id.in_(project_ids),
            LopLine.kind.in_(lop_sources.SOURCE_KINDS)).distinct())).scalars().all()
    for pid in sorted(with_sources):
        await lop_sources.sync_project_lines(db, pid, user.id, full=False)


async def _untouched_line_ids(db: AsyncSession, project_ids: list[int]) -> set[int]:
    """Lines marked `none` in their project's newest closed meeting."""
    rn = func.row_number().over(
        partition_by=LopMeeting.project_id,
        order_by=(LopMeeting.held_on.desc(), LopMeeting.id.desc())).label("rn")
    sub = select(LopMeeting.id, rn).where(
        LopMeeting.project_id.in_(project_ids), LopMeeting.closed_at.is_not(None)).subquery()
    return set((await db.execute(
        select(LopMeetingMark.line_id)
        .join(sub, sub.c.id == LopMeetingMark.meeting_id)
        .where(sub.c.rn == 1, LopMeetingMark.mark == "none"))).scalars().all())


async def _moves(db: AsyncSession, project_ids: list[int], today: date) -> dict[int, int]:
    """line id -> date moves in the last 28 days: a due date that replaced an
    earlier one, and every next-check date set after the first one."""
    rows = (await db.execute(
        select(LopEvent.line_id, LopEvent.field, LopEvent.old_value, LopEvent.created_at)
        .join(LopLine, LopLine.id == LopEvent.line_id)
        .where(LopLine.project_id.in_(project_ids),
               LopEvent.field.in_(("due_date", "next_check_date")))
        .order_by(LopEvent.id))).all()
    since = today - timedelta(days=WINDOW_MONTH)
    out: dict[int, int] = {}
    seen_check: set[int] = set()
    for line_id, field, old, created in rows:
        counts = old is not None
        if field == "next_check_date":
            counts = line_id in seen_check
            seen_check.add(line_id)
        if counts and local_date(created) >= since:
            out[line_id] = out.get(line_id, 0) + 1
    return out


async def collect(db: AsyncSession, user: User, projects: list[Project]) -> Scope:
    """Every line of the projects with its rule state, in a fixed number of queries
    (plus one reconcile per project that has SEP or risk lines)."""
    ids = [p.id for p in projects]
    today = _today()
    scope = Scope(projects=projects, items={p.id: [] for p in projects}, today=today)
    if not ids:
        return scope
    await _sync_sources(db, user, ids)
    lines = list((await db.execute(
        select(LopLine).where(LopLine.project_id.in_(ids))
        .order_by(LopLine.due_date.is_(None), LopLine.due_date, LopLine.id))).scalars().all())
    ctx = await LopService.context(db, user, lines, can_manage=False)
    untouched = await _untouched_line_ids(db, ids)
    moves = await _moves(db, ids, today)
    by_project = {p.id: p for p in projects}
    for ln in lines:
        scope.items[ln.project_id].append(Item(
            line=ln, d=LopService.line_dict(ln, ctx), state=LopService._state(ln, ctx),
            project=by_project[ln.project_id], untouched=ln.id in untouched,
            moves_4w=moves.get(ln.id, 0)))
    return scope


# --------------------------------------------------------------------- KPI
def kpi(items: list[Item], today: date) -> dict:
    month = today - timedelta(days=WINDOW_MONTH)
    week = today - timedelta(days=WINDOW_WEEK)
    open_items = [i for i in items if i.open]
    controlled = sum(1 for i in open_items if i.d["under_control"])
    late_dated = [i.d["days_late"] for i in open_items if i.d["late"] and i.d["due_date"]]
    closed_recent = [i for i in items if not i.open and i.line.closed_at is not None
                     and local_date(i.line.closed_at) >= month and i.line.first_due_date]
    on_time = sum(1 for i in closed_recent if rules.closed_on_time(i.state) is True)
    return {
        "open": len(open_items),
        "no_control": len(open_items) - controlled,
        "with_name_and_date_pct": pct(controlled, len(open_items)),
        "stale": sum(1 for i in items if i.d["stale"]),
        "late": sum(1 for i in items if i.d["late"]),
        "avg_days_late": round(sum(late_dated) / len(late_dated), 1) if late_dated else 0,
        "untouched_last_meeting": sum(1 for i in items if i.untouched),
        "on_time_pct_4w": pct(on_time, len(closed_recent)),
        "dates_moved_4w": sum(i.moves_4w for i in items),
        "opened_week": sum(1 for i in items if i.line.created_at is not None
                           and local_date(i.line.created_at) >= week),
        "closed_week": sum(1 for i in items if not i.open and i.line.closed_at is not None
                           and local_date(i.line.closed_at) >= week),
    }


def department_rows(scope: Scope) -> list[dict]:
    groups: dict[Optional[int], list[Item]] = {}
    names: dict[Optional[int], str] = {None: NO_DEPARTMENT}
    for items in scope.items.values():
        for i in items:
            groups.setdefault(i.line.department_id, []).append(i)
            if i.line.department_id is not None:
                names[i.line.department_id] = i.d["department_name"] or f"Department {i.line.department_id}"
    order = sorted(groups, key=lambda k: (k is None, names[k].lower()))
    return [{"department_id": k, "name": names[k], **kpi(groups[k], scope.today)} for k in order]


# --------------------------------------------------------------------- SEP
async def _gates(db: AsyncSession, project_ids: list[int]) -> dict[int, dict]:
    """project id -> the first gate (by seq) that is not closed, with its progress."""
    out: dict[int, dict] = {}
    if not project_ids:
        return out
    gates = (await db.execute(
        select(SepGate).options(selectinload(SepGate.items))
        .where(SepGate.project_id.in_(project_ids), SepGate.status != "closed")
        .order_by(SepGate.project_id, SepGate.seq))).scalars().all()
    for g in gates:
        if g.project_id in out:
            continue
        done = sum(1 for it in g.items if it.status in SEP_ITEM_DONE)
        out[g.project_id] = {
            "code": g.code, "done_pct": pct(done, len(g.items)),
            "target_date": g.target_date.date().isoformat() if g.target_date else None}
    return out


# --------------------------------------------------------------------- PDB
async def _pdb_for(code: str) -> Optional[tuple[dict, list[dict]]]:
    """(status, topics), or None when PDB cannot answer for this project."""
    try:
        topics = await pdb_client.project_topics(code)
        status = await pdb_client.project_status(code)
    except pdb_client.PdbUnavailable:
        return None
    except Exception:                       # never a 5xx for a PDB problem
        logger.exception("PDB lookup failed for project %s", code)
        return None
    return status, topics


def _pdb_block(answer: Optional[tuple[dict, list[dict]]], items: list[Item]) -> dict:
    pinned_open = {i.line.ref_key for i in items if i.line.kind == "pdb_topic" and i.open}
    block = {"available": answer is not None, "tools_c": None, "tools_b": None,
             "tools_a": None, "open_topics": None, "escalated": None,
             "pinned": len(pinned_open), "pdb_without_name_and_date": None}
    if answer is None:
        return block
    status, topics = answer
    letters = [str(t.get("ps") or "").strip().upper()
               for t in (status.get("tools") or []) if isinstance(t, dict)]
    block.update(
        tools_c=letters.count("C"), tools_b=letters.count("B"), tools_a=letters.count("A"),
        open_topics=len(topics), escalated=sum(1 for t in topics if t.get("escalated")),
        pdb_without_name_and_date=sum(1 for t in topics if str(t["id"]) not in pinned_open))
    return block


# ---------------------------------------------------------------- overview
async def overview(db: AsyncSession, user: User) -> dict:
    projects = await scoped_projects(db, user)
    answers = await asyncio.gather(*(_pdb_for(p.code) for p in projects))
    pdb_by_project = dict(zip((p.id for p in projects), answers))
    for p in projects:                      # pins follow PDB's open list (LOP rows only)
        if pdb_by_project[p.id] is not None:
            await LopService.follow_pdb(
                db, p.id, {str(t["id"]) for t in pdb_by_project[p.id][1]})
    scope = await collect(db, user, projects)
    gates = await _gates(db, [p.id for p in projects])
    rows, all_items = [], []
    for p in projects:
        items = scope.items[p.id]
        all_items += items
        row = {"project_id": p.id, "code": p.code, "name": p.name, **kpi(items, scope.today)}
        row["untouched_last_meeting"] = await LopMeetings.untouched_count(db, p.id)
        row["gate"] = gates.get(p.id)
        row["pdb"] = _pdb_block(pdb_by_project[p.id], items)
        rows.append(row)
    totals = kpi(all_items, scope.today)
    totals["untouched_last_meeting"] = sum(r["untouched_last_meeting"] for r in rows)
    totals["pdb_without_name_and_date"] = sum(
        r["pdb"]["pdb_without_name_and_date"] or 0 for r in rows)
    return {"totals": totals, "projects": rows,
            "departments": department_rows(scope),
            "escalations": await LopMeetings.escalations(db, [p.id for p in projects])}


# ------------------------------------------------------------------- lines
def matches(i: Item, flag: Optional[str]) -> bool:
    if flag is None:
        return True
    return {"open": i.open, "stale": i.d["stale"], "late": i.d["late"],
            "no_control": i.open and not i.d["under_control"],
            "untouched": i.untouched}[flag]


async def lines(db: AsyncSession, user: User, project_id: Optional[int] = None,
                department_id: Optional[int] = None, flag: Optional[str] = None) -> list[dict]:
    """The lines behind a number of the overview. department_id 0 = no department."""
    scope = await collect(db, user, await scoped_projects(db, user, project_id))
    can_manage: dict[int, bool] = {}
    out = []
    for p in scope.projects:
        for i in scope.items[p.id]:
            if department_id is not None and (i.line.department_id or 0) != department_id:
                continue
            if not matches(i, flag):
                continue
            if p.id not in can_manage:
                can_manage[p.id] = await LopService.can_manage(db, user, p.id)
            out.append({**i.d, "can_manage": can_manage[p.id], "project_code": p.code})
    return out
