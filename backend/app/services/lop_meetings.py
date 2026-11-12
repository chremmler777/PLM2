"""Project LOP: the weekly meeting, its marks, the escalation list, the minutes.

A meeting snapshots every open line of the project with a mark row
(`was_late`, `was_stale` at the start, business date). While the meeting is
open, changes to a line set its mark (`auto_mark`); the PM can set a mark by
hand and that always wins. The escalation list and the minutes read the
closed meetings. Datetimes are naive UTC.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import Project, User
from app.models.lop import LOP_MARKS, LopEvent, LopLine, LopMeeting, LopMeetingMark
from app.services import lop_rules as rules
from app.services.lop_service import (
    PM_DEPARTMENT, LopConflict, LopError, LopForbidden, LopNotFound, LopService, _today, _uname, local_date)
from app.services.project_team_service import ProjectTeamService

MINUTES_KIND = "lop_minutes"
SECTION_CAP = 50


def lop_link(project_id: int) -> str:
    return f"/projects/{project_id}/lop"


def meeting_dict(m: LopMeeting) -> dict:
    return {"id": m.id, "held_on": m.held_on.isoformat(), "open": m.closed_at is None}


async def _open_meeting(session: AsyncSession, project_id: int) -> Optional[LopMeeting]:
    return (await session.execute(
        select(LopMeeting).where(LopMeeting.project_id == project_id,
                                 LopMeeting.closed_at.is_(None))
        .order_by(LopMeeting.id.desc()))).scalars().first()


async def _closed_meetings(session: AsyncSession, project_id: int, limit: Optional[int] = None):
    q = (select(LopMeeting).where(LopMeeting.project_id == project_id,
                                  LopMeeting.closed_at.is_not(None))
         .order_by(LopMeeting.held_on.desc(), LopMeeting.id.desc()))
    if limit:
        q = q.limit(limit)
    return list((await session.execute(q)).scalars().all())


async def _ensure_mark(session: AsyncSession, meeting_id: int, line_id: int, mark: str,
                       was_late: bool = False, was_stale: bool = False) -> tuple[LopMeetingMark, bool]:
    """(row, created). Inserts in a savepoint; when the (meeting, line) row
    exists already (another request was first) that row comes back as
    (existing, False). Any other integrity error is re-raised."""
    row = LopMeetingMark(meeting_id=meeting_id, line_id=line_id, mark=mark,
                         was_late=was_late, was_stale=was_stale)
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        existing = (await session.execute(select(LopMeetingMark).where(
            LopMeetingMark.meeting_id == meeting_id,
            LopMeetingMark.line_id == line_id))).scalar_one_or_none()
        if existing is None:
            raise
        return existing, False
    return row, True


def _stub_user() -> User:
    return SimpleNamespace(id=0)        # context() only reads .id


async def _open_line_states(session: AsyncSession, project_id: int):
    """(lines, ctx): every line still open in the display logic of the
    project list (a closed source counts as closed)."""
    lines = await LopService.lines_for_project(session, project_id, "open")
    ctx = await LopService.context(session, _stub_user(), lines, can_manage=False)
    return [ln for ln in lines if LopService._display_status(ln, ctx) != "closed"], ctx


def _escalation_reason(marks: list) -> str:
    """Why a line is late or stale at the two newest closed meetings:
    "late" at both, "stale" at both (not late at both), else "late_or_stale"."""
    if all(m.was_late for m in marks):
        return "late"
    if all(m.was_stale for m in marks):
        return "stale"
    return "late_or_stale"


class LopMeetings:
    # ------------------------------------------------------------------ read
    @staticmethod
    async def summary(session: AsyncSession, project_id: int) -> tuple[Optional[dict], Optional[date]]:
        """(newest meeting as {id, held_on, open} or None, held_on of the
        newest closed meeting or None)."""
        newest = (await session.execute(
            select(LopMeeting).where(LopMeeting.project_id == project_id)
            .order_by(LopMeeting.held_on.desc(), LopMeeting.id.desc()))).scalars().first()
        closed = await _closed_meetings(session, project_id, 1)
        return (meeting_dict(newest) if newest else None,
                closed[0].held_on if closed else None)

    @staticmethod
    async def get(session: AsyncSession, user: User, meeting_id: int) -> LopMeeting:
        m = await session.get(LopMeeting, meeting_id)
        if m is None:
            raise LopNotFound("Meeting not found")
        await LopService.get_project(session, m.project_id, user)
        return m

    @staticmethod
    async def marks(session: AsyncSession, meeting_id: int) -> list[dict]:
        rows = (await session.execute(
            select(LopMeetingMark).where(LopMeetingMark.meeting_id == meeting_id)
            .order_by(LopMeetingMark.line_id))).scalars().all()
        return [{"line_id": r.line_id, "mark": r.mark, "was_late": r.was_late,
                 "was_stale": r.was_stale} for r in rows]

    @staticmethod
    async def detail(session: AsyncSession, meeting: LopMeeting) -> dict:
        d = meeting_dict(meeting)
        d.update(project_id=meeting.project_id, closed_at=meeting.closed_at and meeting.closed_at.isoformat(),
                 minutes_sent_at=meeting.minutes_sent_at and meeting.minutes_sent_at.isoformat(),
                 marks=await LopMeetings.marks(session, meeting.id))
        return d

    # ----------------------------------------------------------------- write
    @staticmethod
    async def start(session: AsyncSession, user: User, project_id: int) -> tuple[LopMeeting, bool]:
        """(meeting, created). One open meeting per project: a second start returns it."""
        await LopService.get_project(session, project_id, user)
        if not await LopService.can_manage(session, user, project_id):
            raise LopForbidden("Only the Project Manager runs the meeting")
        # serialize starts of one project: lock its row (a no-op on sqlite)
        await session.execute(select(Project.id).where(Project.id == project_id).with_for_update())
        existing = await _open_meeting(session, project_id)
        if existing is not None:
            return existing, False
        m = LopMeeting(project_id=project_id, held_on=_today(), started_by=user.id)
        session.add(m)
        await session.flush()
        states, ctx = await _open_line_states(session, project_id)
        stale_days = get_settings().lop_stale_days
        for ln in states:
            s = LopService._state(ln, ctx)
            await _ensure_mark(session, m.id, ln.id, "none",
                               rules.is_late(s, ctx.today),
                               rules.is_stale(s, ctx.today, stale_days))
        await session.commit()
        return m, True

    @staticmethod
    async def _managed(session: AsyncSession, user: User, meeting_id: int) -> LopMeeting:
        m = await LopMeetings.get(session, user, meeting_id)
        if not await LopService.can_manage(session, user, m.project_id):
            raise LopForbidden("Only the Project Manager runs the meeting")
        return m

    @staticmethod
    async def set_mark(session: AsyncSession, user: User, meeting_id: int, line_id: int,
                       mark: str) -> LopMeetingMark:
        m = await LopMeetings._managed(session, user, meeting_id)
        if mark not in LOP_MARKS:
            raise LopError("Unknown mark")
        if m.closed_at is not None:
            raise LopConflict("The meeting is closed")
        row = (await session.execute(select(LopMeetingMark).where(
            LopMeetingMark.meeting_id == m.id, LopMeetingMark.line_id == line_id))).scalar_one_or_none()
        if row is None:
            raise LopNotFound("This line is not in the meeting")
        row.mark = mark                      # a hand-set mark always wins
        await session.commit()
        return row

    @staticmethod
    async def close(session: AsyncSession, user: User, meeting_id: int) -> LopMeeting:
        m = await LopMeetings._managed(session, user, meeting_id)
        if m.closed_at is not None:
            raise LopConflict("The meeting is already closed")
        m.closed_at = datetime.utcnow()
        await session.commit()
        return m

    @staticmethod
    async def auto_mark(session: AsyncSession, line: LopLine, *, moved: bool = False) -> None:
        """While the project's meeting is open: the line was worked on. Moved
        beats updated; a hand-set or automatic `escalated` stays. The caller
        commits."""
        m = await _open_meeting(session, line.project_id)
        if m is None:
            return
        new = "moved" if moved else "updated"
        # a line created during the meeting gets its row here
        row, created = await _ensure_mark(session, m.id, line.id, new)
        if not created and row.mark not in ("escalated", "moved"):
            row.mark = new

    @staticmethod
    async def untouched_count(session: AsyncSession, project_id: int) -> int:
        """Lines with mark `none` in the last closed meeting."""
        closed = await _closed_meetings(session, project_id, 1)
        if not closed:
            return 0
        return (await session.execute(
            select(func.count()).select_from(LopMeetingMark).where(
                LopMeetingMark.meeting_id == closed[0].id, LopMeetingMark.mark == "none"))).scalar_one()

    # ------------------------------------------------------------ escalation
    @staticmethod
    async def escalations(session: AsyncSession, project_ids: Optional[list[int]] = None) -> list[dict]:
        """Lines late or stale at each of the project's two newest closed
        meetings, plus lines hand-marked `escalated` in the newest one
        (`kind: "line"`); and projects with no meeting for too long
        (`kind: "no_meeting"`, the PM is told)."""
        q = select(Project).where(Project.lop_enabled.is_(True))
        if project_ids is not None:
            q = q.where(Project.id.in_(project_ids))
        projects = list((await session.execute(q.order_by(Project.id))).scalars().all())
        today, gap = _today(), get_settings().lop_meeting_gap_days
        out: list[dict] = []
        for p in projects:
            closed = await _closed_meetings(session, p.id, 2)
            if not closed:
                raw = await LopService.lines_for_project(session, p.id, "open")
                # nothing to compare yet and not past the gap: no need to build the context
                if not raw or (today - min(local_date(ln.created_at) for ln in raw)).days <= gap:
                    continue
            states, ctx = await _open_line_states(session, p.id)
            if not states:
                continue
            if closed:
                marks: dict[int, dict[int, LopMeetingMark]] = {}
                rows = (await session.execute(select(LopMeetingMark).where(
                    LopMeetingMark.meeting_id.in_([m.id for m in closed])))).scalars().all()
                for r in rows:
                    marks.setdefault(r.meeting_id, {})[r.line_id] = r
                newest = closed[0]
                for ln in states:
                    hist = [marks.get(m.id, {}).get(ln.id) for m in closed]
                    since, reason = None, None
                    if hist[0] is not None and hist[0].mark == "escalated":
                        since, reason = newest.held_on, "hand"
                    elif len(closed) == 2 and all(h is not None for h in hist) and \
                            rules.needs_escalation([(h.was_late, h.was_stale) for h in hist]):
                        since, reason = closed[1].held_on, _escalation_reason(hist)
                    if since is not None:
                        out.append({"kind": "line", "line": LopService.line_dict(ln, ctx),
                                    "project_code": p.code, "project_id": p.id,
                                    "since": since.isoformat(), "reason": reason})
            since = closed[0].held_on if closed else min(
                local_date(ln.created_at) for ln in states)
            if (today - since).days > gap:
                pm_id = await ProjectTeamService.responsible_user_id(
                    session, p.id, PM_DEPARTMENT, backup=False)
                pm = await session.get(User, pm_id) if pm_id else None
                out.append({"kind": "no_meeting", "project_code": p.code, "project_id": p.id,
                            "pm_name": _uname(pm), "since": since.isoformat()})
        return out

    # --------------------------------------------------------------- minutes
    @staticmethod
    async def send_minutes(session: AsyncSession, user: User, meeting_id: int) -> int:
        """One lop_minutes notification per live team member. Returns how many."""
        from app.services.notification_service import NotificationService
        m = await LopMeetings._managed(session, user, meeting_id)
        if m.closed_at is None:
            raise LopError("Close the meeting before sending the minutes")
        if m.minutes_sent_at is not None:
            raise LopConflict("The minutes were already sent")
        team = sorted(await LopService.team_user_ids(session, m.project_id))
        if not team:
            raise LopError("No project team to send to")
        # claim first, atomically: only one of two simultaneous sends wins
        claimed = await session.execute(
            update(LopMeeting).where(LopMeeting.id == m.id, LopMeeting.minutes_sent_at.is_(None))
            .values(minutes_sent_at=datetime.utcnow()))
        if claimed.rowcount == 0:
            await session.rollback()
            raise LopConflict("The minutes were already sent")
        title, body = await minutes_text(session, m.id)
        n = await NotificationService.notify_users(
            session, team, title, body, lop_link(m.project_id), kind=MINUTES_KIND)
        await session.commit()
        return n


def _row(d: dict) -> str:
    text = " ".join((d.get("text") or d.get("title") or "").split())
    return (f"#{d['id']} {text} | {d.get('department_name') or '-'} | "
            f"{d.get('responsible_name') or '-'} | {d.get('due_date') or '-'}")


async def minutes_text(session: AsyncSession, meeting_id: int) -> tuple[str, str]:
    """(title, body): Closed, New, Moved since the previous closed meeting's
    start (or the project's first line), Overdue and Stale as of now."""
    m = await session.get(LopMeeting, meeting_id)
    if m is None:
        raise LopNotFound("Meeting not found")
    project = await session.get(Project, m.project_id)
    prev = (await session.execute(
        select(LopMeeting).where(
            LopMeeting.project_id == m.project_id, LopMeeting.closed_at.is_not(None),
            LopMeeting.id != m.id,
            (LopMeeting.held_on < m.held_on) | ((LopMeeting.held_on == m.held_on) & (LopMeeting.id < m.id)))
        .order_by(LopMeeting.held_on.desc(), LopMeeting.id.desc()))).scalars().first()
    since = prev.held_on if prev else None

    def in_window(dt: Optional[datetime]) -> bool:
        return dt is not None and (since is None or local_date(dt) >= since)

    lines = list((await session.execute(
        select(LopLine).where(LopLine.project_id == m.project_id)
        .order_by(LopLine.id))).scalars().all())
    ctx = await LopService.context(session, _stub_user(), lines, can_manage=False)
    dicts = {ln.id: LopService.line_dict(ln, ctx) for ln in lines}
    ids = [ln.id for ln in lines]
    moved_ids: set[int] = set()
    if ids:
        ev = (await session.execute(select(LopEvent).where(
            LopEvent.line_id.in_(ids), LopEvent.field.in_(("due_date", "next_check_date"))))).scalars().all()
        moved_ids = {e.line_id for e in ev if in_window(e.created_at)}
    sections = {"Closed": [], "New": [], "Moved": [], "Overdue": [], "Stale": []}
    for ln in lines:
        d = dicts[ln.id]
        if d["status"] == "closed":
            if in_window(ln.closed_at):
                sections["Closed"].append(d)
            continue
        if in_window(ln.created_at):
            sections["New"].append(d)
        if ln.id in moved_ids:
            sections["Moved"].append(d)
        if d["late"]:
            sections["Overdue"].append(d)
        if d["stale"]:
            sections["Stale"].append(d)
    title = f"LOP minutes {project.code} {m.held_on.isoformat()}"
    from app.services.ecr_mail import plm2_url
    parts = [title + (f" (since {since.isoformat()})" if since else "")]
    for name, items in sections.items():
        parts.append(f"\n{name} ({len(items)})")
        if not items:
            parts.append("none")
        parts.extend(_row(d) for d in items[:SECTION_CAP])
        if len(items) > SECTION_CAP:
            parts.append(f"... and {len(items) - SECTION_CAP} more")
    parts.append("\n" + plm2_url(lop_link(m.project_id)))
    return title, "\n".join(parts)
