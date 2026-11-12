"""Project LOP: one daily digest per person, the weekly escalation summary.

The digest says what needs a person today, read from the lines as they are
when it is built (no history of what was true earlier). It never writes form
data and never calls PDB: an unpinned PDB topic has no LopLine and so is in
nobody's digest. Both notices are mailed only while settings.lop_mail_enabled
is on (ecr_mail.mailable); otherwise they are badges. Datetimes are naive UTC.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import Plant, Project, User
from app.models.lop import LopEvent, LopLine
from app.models.notification import Notification
from app.models.workflow import Department, ProjectResponsible
from app.services import lop_rules as rules
from app.services.lop_service import PM_DEPARTMENT, LopService, _uname, _zone

logger = logging.getLogger(__name__)

DIGEST_KIND = "lop_digest"
ESCALATION_KIND = "lop_escalation"
DIGEST_LINK = "/my-tasks"
SECTIONS = ("New for you", "Due within 3 days", "Overdue", "No update for 14 days",
            "Waiting for your check")
_TEXT_CAP = 140


def _local(now_utc: datetime) -> datetime:
    return now_utc.replace(tzinfo=timezone.utc).astimezone(_zone())


_WINDOW_HOURS = 2


def _in_window(local: datetime) -> bool:
    """Only the morning window [lop_digest_hour, +2 h) sends; the two hours
    cover a restart. Outside it nothing is sent, so a change during the day
    never turns into mail."""
    start = get_settings().lop_digest_hour
    return start <= local.hour < start + _WINDOW_HOURS


def _one_line(text: Optional[str]) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= _TEXT_CAP else t[:_TEXT_CAP - 1].rstrip() + "…"


def _when(line: LopLine) -> str:
    if line.due_date is not None:
        return f"due {line.due_date.isoformat()}"
    if line.next_check_date is not None:
        return f"next check {line.next_check_date.isoformat()}"
    return "no date"


async def _managed_project_ids(session: AsyncSession, user: User) -> set[int]:
    """Projects (LOP on, the user's organization) whose Project Manager the user is."""
    rows = (await session.execute(
        select(ProjectResponsible.project_id)
        .join(Department, Department.id == ProjectResponsible.department_id)
        .join(Project, Project.id == ProjectResponsible.project_id)
        .join(Plant, Plant.id == Project.plant_id)
        .where(Department.name == PM_DEPARTMENT, Project.lop_enabled.is_(True),
               Plant.organization_id == user.organization_id,
               or_(ProjectResponsible.user_id == user.id,
                   ProjectResponsible.backup_user_id == user.id)))).scalars().all()
    return set(rows)


async def _since(session: AsyncSession, user: User, now: datetime) -> datetime:
    """The user's previous digest, else 24 hours back."""
    last = (await session.execute(select(func.max(Notification.created_at)).where(
        Notification.user_id == user.id, Notification.kind == DIGEST_KIND))).scalar_one_or_none()
    return last or now - timedelta(hours=24)


async def digest_for(session: AsyncSession, user: User, today: date,
                     now: Optional[datetime] = None) -> Optional[tuple[str, str]]:
    """(title, body) of the user's digest as the lines stand now, or None when
    nothing needs them. A line shows in the first section it fits; only "New
    for you" may repeat a line from a later section. Lines of a project the
    user is no longer on the team of do not count."""
    now = now or datetime.utcnow()
    settings = get_settings()
    managed = await _managed_project_ids(session, user)
    q = (select(LopLine).join(Project, Project.id == LopLine.project_id)
         .join(Plant, Plant.id == Project.plant_id)
         .where(Project.lop_enabled.is_(True), Plant.organization_id == user.organization_id,
                LopLine.status != "closed")
         .order_by(LopLine.due_date.is_(None), LopLine.due_date, LopLine.id))
    cond = LopLine.responsible_id == user.id
    if managed:
        cond = or_(cond, (LopLine.project_id.in_(managed)) & (LopLine.status == "done_check"))
    lines = list((await session.execute(q.where(cond))).scalars().all())
    if not lines:
        return None
    team: dict[int, set[int]] = {}
    for pid in {ln.project_id for ln in lines if ln.responsible_id == user.id}:
        team[pid] = await LopService.team_user_ids(session, pid)
    ctx = await LopService.context(session, user, lines, can_manage=False)
    codes = dict((await session.execute(select(Project.id, Project.code).where(
        Project.id.in_({ln.project_id for ln in lines})))).all())
    since = await _since(session, user, now)
    my_name = _uname(user)
    became_mine = set((await session.execute(
        select(LopEvent.line_id).where(
            LopEvent.line_id.in_([ln.id for ln in lines]), LopEvent.field == "responsible",
            LopEvent.new_value == my_name, LopEvent.created_at > since))).scalars().all())

    out: dict[str, list[tuple[str, int, str]]] = {s: [] for s in SECTIONS}
    shown: set[int] = set()

    def add(section: str, ln: LopLine, extra: str = "") -> None:
        text, _ = LopService._text_and_label(ln, ctx)
        out[section].append((codes[ln.project_id], ln.id, f"#{ln.id} {_one_line(text)} | {_when(ln)}{extra}"))
        shown.add(ln.id)

    for ln in lines:
        s = LopService._state(ln, ctx)
        if s.status == "closed":
            continue
        mine = ln.responsible_id == user.id and user.id in team.get(ln.project_id, set())
        if mine and ln.status != "done_check":
            if ln.id in became_mine or (ln.created_at and ln.created_at > since):
                add("New for you", ln)
        if ln.status == "done_check":
            if ln.project_id in managed:
                add("Waiting for your check", ln)
            continue
        if not mine:
            continue
        late = rules.is_late(s, today)
        if rules.due_soon(s, today, settings.lop_due_soon_days) and not late:
            add("Due within 3 days", ln)
        elif late:
            n = rules.days_late(s, today)
            add("Overdue", ln, f" ({n} days late)" if n else " (check missed)")
        elif rules.is_stale(s, today, settings.lop_stale_days):
            add("No update for 14 days", ln)
    ids = {i for rows in out.values() for _, i, _ in rows}
    if not ids:
        return None
    parts: list[str] = []
    for section in SECTIONS:
        rows = out[section]
        if not rows:
            continue
        parts.append(section)
        last_code = None
        for code, _id, text in sorted(rows, key=lambda r: (r[0], r[1])):
            if code != last_code:
                parts.append(f" {code}")
                last_code = code
            parts.append(f"   {text}")
        parts.append("")
    return f"LOP: {len(ids)} lines need you", "\n".join(parts).rstrip()


async def _digest_candidates(session: AsyncSession) -> list[User]:
    """Active users who are responsible for an open line, or the Project
    Manager (responsible or backup) of a project with a line to check."""
    open_lines = (select(LopLine).join(Project, Project.id == LopLine.project_id)
                  .where(Project.lop_enabled.is_(True), LopLine.status != "closed"))
    ids = set((await session.execute(
        open_lines.with_only_columns(LopLine.responsible_id)
        .where(LopLine.responsible_id.is_not(None)))).scalars().all())
    waiting = open_lines.where(LopLine.status == "done_check").with_only_columns(LopLine.project_id)
    for col in (ProjectResponsible.user_id, ProjectResponsible.backup_user_id):
        ids |= set((await session.execute(
            select(col).join(Department, Department.id == ProjectResponsible.department_id)
            .where(Department.name == PM_DEPARTMENT, col.is_not(None),
                   ProjectResponsible.project_id.in_(waiting)))).scalars().all())
    if not ids:
        return []
    return list((await session.execute(select(User).where(
        User.id.in_(ids), User.is_active.is_(True)).order_by(User.id))).scalars().all())


async def send_daily_digests(session: AsyncSession, now_utc: datetime) -> int:
    """Monday to Friday in the morning window from lop_digest_hour (local
    time): one digest per person and local date. Returns how many were created."""
    from app.services.notification_service import NotificationService
    local = _local(now_utc)
    if local.weekday() > 4 or not _in_window(local):
        return 0
    key = f"lop_digest:{local.date()}"
    had = set((await session.execute(select(Notification.user_id).where(
        Notification.kind == DIGEST_KIND, Notification.subject_key == key))).scalars().all())
    sent = 0
    for user in await _digest_candidates(session):
        if user.id in had:
            continue
        d = await digest_for(session, user, local.date(), now=now_utc)
        if d is None:
            continue
        sent += await NotificationService.notify_once(
            session, [user.id], kind=DIGEST_KIND, subject_key=key, include_read=True,
            title=d[0], body=d[1], link=DIGEST_LINK)
    if sent:
        await session.commit()
    return sent


async def escalation_recipients(session: AsyncSession) -> list[User]:
    wanted = {x.strip().lower() for x in
              (get_settings().lop_escalation_recipients or "").split(",") if x.strip()}
    if not wanted:
        return []
    return list((await session.execute(select(User).where(
        User.is_active.is_(True),
        func.lower(User.username).in_(wanted) | func.lower(User.email).in_(wanted)
    ).order_by(User.id))).scalars().all())


def _escalation_text(entries: list[dict]) -> str:
    lines = [e for e in entries if e["kind"] == "line"]
    gaps = [e for e in entries if e["kind"] == "no_meeting"]
    parts: list[str] = []
    if lines:
        parts.append("Late or stale at two meetings in a row, or escalated by hand")
        for e in sorted(lines, key=lambda e: (e["project_code"], e["line"]["id"])):
            ln = e["line"]
            who = ln.get("responsible_name") or "no name"
            parts.append(f"  {e['project_code']} #{ln['id']} {_one_line(ln.get('text'))} "
                         f"| {who} | since {e['since']}")
        parts.append("")
    if gaps:
        parts.append("No LOP meeting for more than "
                     f"{get_settings().lop_meeting_gap_days} days")
        for e in sorted(gaps, key=lambda e: e["project_code"]):
            parts.append(f"  {e['project_code']}: no LOP meeting since {e['since']} "
                         f"| Project Manager {e['pm_name'] or 'not named'}")
    return "\n".join(parts).rstrip()


async def send_escalation_summary(session: AsyncSession, now_utc: datetime) -> int:
    """Mondays in the morning window from lop_digest_hour (local time): the
    escalation list to each configured recipient, once per ISO week. Nothing
    when the list is empty or nobody is configured. Returns how many were created."""
    from app.services.lop_meetings import LopMeetings
    from app.services.notification_service import NotificationService
    local = _local(now_utc)
    if local.weekday() != 0 or not _in_window(local):
        return 0
    recipients = await escalation_recipients(session)
    if not recipients:
        return 0
    iso = local.isocalendar()
    key = f"lop_escalation:{iso.year}-W{iso.week}"
    by_org: dict[int, list[dict]] = {}
    sent = 0
    for user in recipients:
        if user.organization_id not in by_org:
            ids = list((await session.execute(
                select(Project.id).join(Plant, Plant.id == Project.plant_id)
                .where(Plant.organization_id == user.organization_id))).scalars().all())
            by_org[user.organization_id] = (
                await LopMeetings.escalations(session, ids) if ids else [])
        entries = by_org[user.organization_id]
        if not entries:
            continue
        sent += await NotificationService.notify_once(
            session, [user.id], kind=ESCALATION_KIND, subject_key=key, include_read=True,
            title=f"LOP escalations: {len(entries)}", body=_escalation_text(entries),
            link=DIGEST_LINK)
    if sent:
        await session.commit()
    return sent
