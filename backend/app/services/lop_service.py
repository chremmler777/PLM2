"""Project LOP: PM tasks, assignment by department, comments, history.

Later tasks plug other line kinds (SEP items, risks, PDB topics) into the
small extension points below: `_text_and_label` (what the line says and where
it comes from) and `_state` (the rule inputs, e.g. a source that closed).
Datetimes are naive UTC.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import Plant, Project, User
from app.models.lop import LOP_STATUSES, LopComment, LopEvent, LopLine
from app.models.workflow import Department, ProjectResponsible
from app.services import lop_rules as rules
from app.services.project_team_service import ProjectTeamService, is_live_member

PM_DEPARTMENT = "Project Manager"
_UNSET = object()
FIRST_DATE_REASON = "first date set by the PM"
CONFIRMED_REASON = "confirmed by the PM"
# a reopen made by the sync or follow_pdb, not by a person: not "reopened"
SYSTEM_REOPEN_REASON = "open again at the source"


def reserved_reasons() -> tuple[str, ...]:
    """Reasons the system writes and the KPIs or the sync treat specially; a
    person may not type them (compared trimmed and case-insensitive)."""
    from app.services.lop_sources import GATE_CLOSED_REASON, RISK_ROW_REASON
    return (FIRST_DATE_REASON, RISK_ROW_REASON, SYSTEM_REOPEN_REASON, GATE_CLOSED_REASON)


class LopError(Exception):
    status_code = 400


class LopNotFound(LopError):
    status_code = 404


class LopForbidden(LopError):
    status_code = 403


class LopConflict(LopError):
    status_code = 409


def _zone() -> ZoneInfo:
    return ZoneInfo(get_settings().lop_timezone)


def _today() -> date:
    """The business date: today in the LOP time zone (the one source of
    "today" for the LOP)."""
    return datetime.now(_zone()).date()


def to_local(dt: Optional[datetime]) -> Optional[datetime]:
    """A stored naive UTC datetime as an aware one in the LOP time zone."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(_zone())


def local_date(dt: datetime) -> date:
    """The business date of a stored naive UTC datetime."""
    return to_local(dt).date()


def _iso(v) -> Optional[str]:
    return v.isoformat() if v is not None else None


def _uname(u: Optional[User]) -> Optional[str]:
    return (u.full_name or u.username) if u is not None else None


def pdb_topic_text(topic: dict) -> str:
    """What a PDB topic says: the issue, and the to-do when there is one."""
    issue = (topic.get("issue") or "").strip()
    todo = (topic.get("todo") or "").strip()
    return f"{issue}\nTo do: {todo}" if issue and todo else (issue or todo)


def _pdb_fields(topic: Optional[dict]) -> dict:
    """The live PDB columns of a topic line; empty values when PDB data is not at hand."""
    t = topic or {}
    return {
        "tool_number": t.get("tool_number"),
        "age_days": (t.get("age_days") or 0) if topic else None,
        "escalation_level": t.get("escalation_level"),
        "escalated": bool(t.get("escalated")),
        "committed_until": t.get("committed_until"),
        "last_log_at": t.get("last_log_at"),
        "handover_impact": bool(t.get("handover_impact")),
        "pdb_department": t.get("department"),
        "pdb_live": topic is not None,
    }


@dataclass
class LineContext:
    """Everything line_dict needs besides the line itself, loaded in bulk."""
    user_id: int
    can_manage: bool
    today: date
    users: dict[int, User] = field(default_factory=dict)
    departments: dict[int, str] = field(default_factory=dict)
    last_comments: dict[int, dict] = field(default_factory=dict)
    reopened: set[int] = field(default_factory=set)
    # line id -> what its source says (SEP item, risk row); see lop_sources
    sources: dict[int, dict] = field(default_factory=dict)
    # PDB topic id (str) -> the live topic row; only the /pdb route fills it
    pdb: dict[str, dict] = field(default_factory=dict)
    # project id -> held_on of its newest closed meeting
    last_meeting: dict[int, date] = field(default_factory=dict)
    # project id -> its newest meeting {id, held_on, open}
    meetings: dict[int, dict] = field(default_factory=dict)
    # line id -> mark in the project's open meeting
    marks: dict[int, str] = field(default_factory=dict)


class LopService:
    # ---------------------------------------------------------------- access
    @staticmethod
    async def get_project(session: AsyncSession, project_id: int, user: User,
                          *, need_lop: bool = True) -> Project:
        """The project within the caller's organization; 404 when it does not
        exist or (need_lop) has not switched LOP on."""
        p = (await session.execute(
            select(Project).join(Plant, Plant.id == Project.plant_id).where(
                Project.id == project_id,
                Plant.organization_id == user.organization_id))).scalar_one_or_none()
        if p is None or (need_lop and not p.lop_enabled):
            raise LopNotFound("Project not found")
        return p

    @staticmethod
    async def _pm_department_id(session: AsyncSession) -> Optional[int]:
        return (await session.execute(
            select(Department.id).where(Department.name == PM_DEPARTMENT))).scalar_one_or_none()

    @staticmethod
    async def can_manage(session: AsyncSession, user: User, project_id: int) -> bool:
        """Admin, or the project's Project Manager (responsible or backup)."""
        if user.effective_role == "admin":
            return True
        pm_dept = await LopService._pm_department_id(session)
        if pm_dept is None:
            return False
        row = (await session.execute(select(ProjectResponsible).where(
            ProjectResponsible.project_id == project_id,
            ProjectResponsible.department_id == pm_dept))).scalar_one_or_none()
        return row is not None and user.id in (row.user_id, row.backup_user_id)

    @staticmethod
    async def team_user_ids(session: AsyncSession, project_id: int) -> set[int]:
        """Live members of the project team (responsible or named backup)."""
        rows = (await session.execute(
            select(ProjectResponsible, Department.name)
            .join(Department, Department.id == ProjectResponsible.department_id)
            .where(ProjectResponsible.project_id == project_id))).all()
        out: set[int] = set()
        for row, dept_name in rows:
            for uid in (row.user_id, row.backup_user_id):
                if uid is not None and await is_live_member(session, uid, dept_name):
                    out.add(uid)
        return out

    @staticmethod
    async def is_team_member(session: AsyncSession, user: User, project_id: int) -> bool:
        return user.id in await LopService.team_user_ids(session, project_id)

    # ------------------------------------------------------------ assignment
    @staticmethod
    async def resolve_responsible(session: AsyncSession, project_id: int,
                                  department_id: Optional[int]) -> tuple[Optional[int], bool]:
        """(user id, is_default). The department's team responsible; else the
        project's Project Manager (default); else nobody. No department, no one."""
        if department_id is None:
            return None, False              # no department: nothing to resolve
        name = (await session.get(Department, department_id)).name
        uid = await ProjectTeamService.responsible_user_id(
            session, project_id, name, backup=True)
        if uid is not None:
            return uid, False
        pm = await ProjectTeamService.responsible_user_id(
            session, project_id, PM_DEPARTMENT, backup=True)
        return (pm, True) if pm is not None else (None, False)

    @staticmethod
    async def _check_department(session: AsyncSession, department_id: int) -> Department:
        d = await session.get(Department, department_id)
        if d is None or not d.is_active:
            raise LopError("Department not found")
        return d

    @staticmethod
    async def _check_responsible(session: AsyncSession, project_id: int, uid: int) -> None:
        if uid not in await LopService.team_user_ids(session, project_id):
            raise LopError("The responsible person must be in the project team")

    # ---------------------------------------------------------------- badges
    @staticmethod
    async def _line_text(session: AsyncSession, line: LopLine) -> str:
        from app.services import lop_sources
        src = (await lop_sources.load_sources(session, [line])).get(line.id)
        text = src["text"] if src is not None else line.title
        return (text or "").strip()

    @staticmethod
    async def _badge(session: AsyncSession, recipient_id: Optional[int], actor_id: Optional[int],
                     project_id: int, title: str, body: str) -> None:
        """An in-app notice (kind lop_event, never mailed) about a change on a
        project's LOP; nothing when nobody is named or the actor is the recipient."""
        if recipient_id is None or recipient_id == actor_id:
            return
        from app.services.lop_meetings import lop_link
        from app.services.notification_service import NotificationService
        code = (await session.get(Project, project_id)).code
        await NotificationService.notify_users(
            session, [recipient_id], f"LOP {code}: {title}", body, lop_link(project_id),
            kind="lop_event")

    @staticmethod
    async def notify_assigned(session: AsyncSession, actor: User, lines: list[LopLine]) -> None:
        """Tell each responsible person that lines were given to them: one
        badge per person (one line: its text; several: the count and the first
        few texts). The caller commits."""
        by_person: dict[int, list[LopLine]] = {}
        for ln in lines:
            if ln.responsible_id is not None and ln.responsible_id != actor.id:
                by_person.setdefault(ln.responsible_id, []).append(ln)
        for uid, mine in by_person.items():
            texts = [await LopService._line_text(session, ln) for ln in mine[:5]]
            if len(mine) == 1:
                title, body = "new line for you", texts[0]
            else:
                title = f"{len(mine)} new lines for you"
                body = "\n".join(f"- {t}" for t in texts) + (
                    f"\n... and {len(mine) - 5} more" if len(mine) > 5 else "")
            await LopService._badge(session, uid, actor.id, mine[0].project_id, title, body)

    @staticmethod
    async def notify_done_check(session: AsyncSession, actor_id: Optional[int], line: LopLine) -> None:
        pm = await ProjectTeamService.responsible_user_id(
            session, line.project_id, PM_DEPARTMENT, backup=True)
        await LopService._badge(session, pm, actor_id, line.project_id, "reported as done, please check",
                                await LopService._line_text(session, line))

    @staticmethod
    async def notify_reopened(session: AsyncSession, actor_id: Optional[int], line: LopLine) -> None:
        await LopService._badge(session, line.responsible_id, actor_id, line.project_id,
                                "line open again", await LopService._line_text(session, line))

    # ----------------------------------------------------------------- write
    @staticmethod
    def _event(session: AsyncSession, line: LopLine, user: User, field_: str,
               old, new, reason: Optional[str] = None) -> None:
        session.add(LopEvent(
            line_id=line.id, user_id=user.id, field=field_, reason=reason,
            old_value=None if old is None else str(old),
            new_value=None if new is None else str(new)))

    @staticmethod
    def _touch(line: LopLine, user: User) -> None:
        line.last_update_at = datetime.utcnow()
        line.last_update_by = user.id

    @staticmethod
    async def create_task(session: AsyncSession, user: User, project_id: int, *,
                          title: str, department_id: Optional[int] = None,
                          due_date: Optional[date] = None,
                          next_check_date: Optional[date] = None,
                          responsible_id: Optional[int] = None) -> LopLine:
        await LopService.get_project(session, project_id, user)
        if not await LopService.can_manage(session, user, project_id):
            raise LopForbidden("Only the Project Manager creates lines")
        title = (title or "").strip()
        if not title:
            raise LopError("A title is required")
        if department_id is not None:
            await LopService._check_department(session, department_id)
        if responsible_id is not None:
            await LopService._check_responsible(session, project_id, responsible_id)
            is_default = False
        else:
            responsible_id, is_default = await LopService.resolve_responsible(
                session, project_id, department_id)
        has_date = due_date is not None or next_check_date is not None
        line = LopLine(
            project_id=project_id, kind="task", title=title,
            department_id=department_id, responsible_id=responsible_id,
            responsible_is_default=is_default, due_date=due_date,
            first_due_date=due_date, next_check_date=next_check_date,
            status="open" if department_id is not None and has_date else "new",
            created_by=user.id)
        LopService._touch(line, user)
        line.created_at = line.last_update_at
        session.add(line)
        await session.flush()
        LopService._event(session, line, user, "created", None, title)
        await LopService.mark_in_meeting(session, line)
        await LopService.notify_assigned(session, user, [line])
        await session.commit()
        return line

    @staticmethod
    async def mark_in_meeting(session: AsyncSession, line: LopLine, *, moved: bool = False) -> None:
        """While the project's LOP meeting is open, record that the line was
        worked on (lop_meetings.auto_mark). The caller commits."""
        from app.services import lop_meetings
        await lop_meetings.LopMeetings.auto_mark(session, line, moved=moved)

    @staticmethod
    async def update_line(session: AsyncSession, user: User, line_id: int, body: dict,
                          reason: Optional[str] = None) -> LopLine:
        """body holds only the fields the caller sent. The Project Manager
        (or an admin) changes anything; the responsible person may only set
        done_check."""
        line = await LopService.get_line(session, user, line_id)
        manage = await LopService.can_manage(session, user, line.project_id)
        if not manage:
            only_done = set(body) == {"status"} and body["status"] == "done_check"
            if not (only_done and line.responsible_id == user.id and line.status != "closed"):
                raise LopForbidden("Only the Project Manager changes a line; "
                                   "the responsible person can report it as done")
        if body.get("clear_responsible") and body.get("responsible_id") is not None:
            raise LopError("Clear the responsible or name one, not both")
        from app.services import lop_sources
        await lop_sources.assert_editable(session, line)        # 409 when the SEP gate is closed
        reason = (reason or "").strip() or None
        if reason and reason.lower() in {r.lower() for r in reserved_reasons()}:
            raise LopError(f'"{reason}" is a reserved reason; please say in your own words why')
        old_status = line.status
        changed = False
        old_dates = (line.due_date, line.next_check_date)
        old_responsible = line.responsible_id

        if "title" in body:
            if line.kind != "task":
                raise LopError("Only a PM task has its own title")
            title = (body["title"] or "").strip()
            if not title:
                raise LopError("A title is required")
            if title != line.title:
                LopService._event(session, line, user, "title", line.title, title, reason)
                line.title, changed = title, True

        if "department_id" in body:
            new_dept = body["department_id"]
            if new_dept is not None:
                await LopService._check_department(session, new_dept)
            if new_dept != line.department_id:
                LopService._event(session, line, user, "department",
                                  await LopService._dept_name(session, line.department_id),
                                  await LopService._dept_name(session, new_dept), reason)
                line.department_id, changed = new_dept, True
                if (new_dept is not None and body.get("responsible_id") is None
                        and not body.get("clear_responsible")):
                    uid, dflt = await LopService.resolve_responsible(
                        session, line.project_id, new_dept)
                    await LopService._set_responsible(session, line, user, uid, dflt, reason)

        if body.get("clear_responsible"):
            changed |= await LopService._set_responsible(session, line, user, None, False, reason)
        elif body.get("responsible_id") is not None:
            await LopService._check_responsible(session, line.project_id, body["responsible_id"])
            changed |= await LopService._set_responsible(
                session, line, user, body["responsible_id"], False, reason)

        if "due_date" in body:
            new_due = body["due_date"]
            if line.due_is_default:
                # the first date the PM sets is the baseline, not a move
                if line.due_date is not None or new_due is not None:
                    LopService._event(session, line, user, "due_date", line.due_date,
                                      new_due, FIRST_DATE_REASON)
                line.due_date = line.first_due_date = new_due
                line.due_is_default, changed = False, True
            elif new_due != line.due_date:
                if line.first_due_date is None:
                    line.first_due_date = new_due       # the first date, no reason
                elif not reason:
                    raise LopError("Moving a due date needs a reason")
                LopService._event(session, line, user, "due_date", line.due_date, new_due, reason)
                line.due_date, line.due_is_default, changed = new_due, False, True

        if "next_check_date" in body:
            # allowed without a reason; the event is written even for the same
            # date so that every re-set can be counted later
            LopService._event(session, line, user, "next_check_date",
                              line.next_check_date, body["next_check_date"], reason)
            line.next_check_date, changed = body["next_check_date"], True

        if "status" in body:
            new_status = body["status"]
            if new_status not in LOP_STATUSES:
                raise LopError("Unknown status")
            if new_status == "closed" and line.kind == "pdb_topic":
                raise LopError("A pinned PDB topic cannot be closed here: it is closed in PDB and closes here by itself")
            if new_status != line.status:
                LopService._apply_status(line, user, new_status)
                await lop_sources.push_status(session, line, user, old_status, new_status)
                LopService._event(session, line, user, "status", old_status, new_status, reason)
                changed = True
                if new_status == "done_check":
                    await LopService.notify_done_check(session, user.id, line)
                elif old_status in ("done_check", "closed") and new_status != "closed" and (
                        old_status == "closed" or new_status in ("open", "in_work")):
                    await LopService.notify_reopened(session, user.id, line)
        elif (line.status == "new" and line.department_id is not None
              and (line.due_date is not None or line.next_check_date is not None)):
            line.status = "open"                        # now it has a department and a date
            LopService._event(session, line, user, "status", "new", "open", reason)

        if line.responsible_id != old_responsible:
            await LopService.notify_assigned(session, user, [line])
        if changed or line.status != old_status:
            LopService._touch(line, user)
            await LopService.mark_in_meeting(
                session, line,
                moved=(line.due_date, line.next_check_date) != old_dates or "next_check_date" in body)
        await session.commit()
        return line

    @staticmethod
    def _apply_status(line: LopLine, user: User, new_status: str) -> None:
        line.status = new_status
        if new_status == "closed":
            line.closed_at, line.closed_by = datetime.utcnow(), user.id
        else:
            line.closed_at = line.closed_by = None      # a reopened line keeps dates and history

    @staticmethod
    async def _set_responsible(session: AsyncSession, line: LopLine, user: User,
                               uid: Optional[int], is_default: bool, reason) -> bool:
        """True when the responsible person really changed, or the PM confirmed
        the default name (the same person sent again)."""
        differs = uid != line.responsible_id
        if differs:
            old = await session.get(User, line.responsible_id) if line.responsible_id else None
            new = await session.get(User, uid) if uid else None
            LopService._event(session, line, user, "responsible", _uname(old), _uname(new), reason)
        confirmed = (not differs and uid is not None and line.responsible_is_default
                     and not is_default)
        if confirmed:
            name = _uname(await session.get(User, uid))
            LopService._event(session, line, user, "responsible_id", name, name, CONFIRMED_REASON)
        line.responsible_id, line.responsible_is_default = uid, is_default
        return differs or confirmed

    @staticmethod
    async def _dept_name(session: AsyncSession, department_id: Optional[int]) -> Optional[str]:
        if department_id is None:
            return None
        d = await session.get(Department, department_id)
        return d.name if d else None

    @staticmethod
    async def add_comment(session: AsyncSession, user: User, line_id: int, text: str) -> LopComment:
        line = await LopService.get_line(session, user, line_id)
        if not (await LopService.can_manage(session, user, line.project_id)
                or await LopService.is_team_member(session, user, line.project_id)):
            raise LopForbidden("Only the project team comments on a line")
        text = (text or "").strip()
        if not text:
            raise LopError("A comment needs text")
        c = LopComment(line_id=line.id, user_id=user.id, text=text)
        session.add(c)
        LopService._touch(line, user)
        await LopService.mark_in_meeting(session, line)
        await session.commit()
        return c

    # ------------------------------------------------------------ PDB topics
    @staticmethod
    async def pinned_topic_lines(session: AsyncSession, project_id: int) -> list[LopLine]:
        return list((await session.execute(select(LopLine).where(
            LopLine.project_id == project_id, LopLine.kind == "pdb_topic")
            .order_by(LopLine.id))).scalars().all())

    @staticmethod
    async def pin_pdb_topic(session: AsyncSession, user: User, project_id: int, topic: dict, *,
                            responsible_id: Optional[int] = None,
                            due_date: Optional[date] = None,
                            next_check_date: Optional[date] = None) -> tuple[LopLine, bool]:
        """(line, created). The Project Manager gives an open PDB topic a
        responsible person (given, else the team member of its PDB department,
        else the project's PM as default) and a due or next-check date. The line keeps the issue
        text as a snapshot; PDB stays the source of the topic."""
        from app.services import lop_sources
        from app.services.lop_departments import PDB_DEPARTMENT_MAP, department_id_for
        dept_id = await department_id_for(session, PDB_DEPARTMENT_MAP, topic.get("department"))
        if responsible_id is not None:
            await LopService._check_responsible(session, project_id, responsible_id)
            is_default = False
        else:
            responsible_id, is_default = await LopService.resolve_responsible(
                session, project_id, dept_id)
        if responsible_id is None:
            pm = await ProjectTeamService.responsible_user_id(
                session, project_id, PM_DEPARTMENT, backup=True)
            if pm is None:
                raise LopError("The topic needs a responsible person: name one "
                               "(the project has no Project Manager to fall back on)")
            responsible_id, is_default = pm, True
        now = datetime.utcnow()
        line = LopLine(
            project_id=project_id, kind="pdb_topic", ref_key=str(topic["id"]),
            title=(str(topic.get("issue") or topic.get("todo") or "").strip() or "PDB topic")[:500],
            department_id=dept_id, responsible_id=responsible_id,
            responsible_is_default=is_default, due_date=due_date, first_due_date=due_date,
            next_check_date=next_check_date, status="open",
            created_by=user.id, created_at=now, last_update_at=now, last_update_by=user.id)
        line, created = await lop_sources._insert_line(session, line)
        if created:
            LopService._event(session, line, user, "created", None, f"PDB topic {topic['id']}")
            await LopService.notify_assigned(session, user, [line])
        await session.commit()
        return line, created

    @staticmethod
    async def follow_pdb(session: AsyncSession, project_id: int, open_ids: set[str]) -> list[LopLine]:
        """Pins follow PDB's full open list (only call it after PDB answered):
        a pin whose topic left the list closes ("closed in PDB"), one whose
        topic is back reopens. Returns all pinned lines."""
        lines = await LopService.pinned_topic_lines(session, project_id)
        now = datetime.utcnow()
        changed = False
        for ln in lines:
            gone = ln.ref_key not in open_ids
            if gone and ln.status != "closed":
                session.add(LopEvent(line_id=ln.id, user_id=None, field="status",
                                     old_value=ln.status, new_value="closed in PDB"))
                ln.status, ln.closed_at, ln.closed_by = "closed", now, None
            elif not gone and ln.status == "closed":
                session.add(LopEvent(line_id=ln.id, user_id=None, field="status",
                                     old_value="closed", new_value="open",
                                     reason=SYSTEM_REOPEN_REASON))
                ln.status, ln.closed_at, ln.closed_by = "open", None, None
            else:
                continue
            ln.last_update_at, ln.last_update_by = now, None
            changed = True
        if changed:
            await session.commit()
        return lines

    # ------------------------------------------------------------------ read
    @staticmethod
    async def get_line(session: AsyncSession, user: User, line_id: int) -> LopLine:
        line = await session.get(LopLine, line_id)
        if line is None:
            raise LopNotFound("Line not found")
        await LopService.get_project(session, line.project_id, user)
        return line

    @staticmethod
    async def history(session: AsyncSession, user: User, line_id: int) -> list[dict]:
        """Comments and events, newest first."""
        line = await LopService.get_line(session, user, line_id)
        comments = (await session.execute(
            select(LopComment).where(LopComment.line_id == line.id))).scalars().all()
        events = (await session.execute(
            select(LopEvent).where(LopEvent.line_id == line.id))).scalars().all()
        uids = {x.user_id for x in (*comments, *events) if x.user_id}
        users = {u.id: u for u in (await session.execute(
            select(User).where(User.id.in_(uids)))).scalars().all()} if uids else {}
        items = [{"type": "comment", "id": c.id, "user_id": c.user_id,
                  "user_name": _uname(users.get(c.user_id)), "text": c.text,
                  "created_at": _iso(c.created_at)} for c in comments]
        items += [{"type": "event", "id": e.id, "user_id": e.user_id,
                   "user_name": _uname(users.get(e.user_id)), "field": e.field,
                   "old_value": e.old_value, "new_value": e.new_value, "reason": e.reason,
                   "created_at": _iso(e.created_at)} for e in events]
        items.sort(key=lambda i: (i["created_at"], i["type"] == "event", i["id"]), reverse=True)
        return items

    @staticmethod
    async def lines_for_project(session: AsyncSession, project_id: int, view: str) -> list[LopLine]:
        q = select(LopLine).where(LopLine.project_id == project_id)
        q = q.where(LopLine.status == "closed") if view == "closed" else q.where(LopLine.status != "closed")
        return list((await session.execute(
            q.order_by(LopLine.due_date.is_(None), LopLine.due_date, LopLine.id))).scalars().all())

    @staticmethod
    async def my_open_lines(session: AsyncSession, user: User) -> list[tuple[LopLine, Project]]:
        rows = (await session.execute(
            select(LopLine, Project).join(Project, Project.id == LopLine.project_id)
            .join(Plant, Plant.id == Project.plant_id)
            .where(LopLine.responsible_id == user.id, LopLine.status != "closed",
                   Project.lop_enabled.is_(True),
                   Plant.organization_id == user.organization_id)
            .order_by(LopLine.due_date.is_(None), LopLine.due_date, LopLine.id))).all()
        return [(line, p) for line, p in rows]

    @staticmethod
    async def context(session: AsyncSession, user: User, lines: list[LopLine],
                      *, can_manage: bool) -> LineContext:
        ctx = LineContext(user_id=user.id, can_manage=can_manage, today=_today())
        if not lines:
            return ctx
        ids = [ln.id for ln in lines]
        uids = {x for ln in lines for x in (ln.responsible_id, ln.last_update_by, ln.closed_by) if x}
        comments = (await session.execute(
            select(LopComment).where(LopComment.line_id.in_(ids))
            .order_by(LopComment.created_at, LopComment.id))).scalars().all()
        for c in comments:                                # last one per line wins
            ctx.last_comments[c.line_id] = {"id": c.id, "text": c.text, "user_id": c.user_id,
                                            "created_at": _iso(c.created_at)}
            if c.user_id:
                uids.add(c.user_id)
        if uids:
            ctx.users = {u.id: u for u in (await session.execute(
                select(User).where(User.id.in_(uids)))).scalars().all()}
        for c in ctx.last_comments.values():
            c["user_name"] = _uname(ctx.users.get(c["user_id"]))
        dept_ids = {ln.department_id for ln in lines if ln.department_id}
        if dept_ids:
            ctx.departments = dict((await session.execute(
                select(Department.id, Department.name).where(Department.id.in_(dept_ids)))).all())
        from app.services import lop_sources
        ctx.sources = await lop_sources.load_sources(session, lines)
        ctx.reopened = set((await session.execute(
            select(LopEvent.line_id).where(
                LopEvent.line_id.in_(ids), LopEvent.field == "status",
                LopEvent.old_value == "closed", LopEvent.new_value != "closed",
                or_(LopEvent.reason.is_(None),
                    LopEvent.reason != SYSTEM_REOPEN_REASON)))).scalars().all())
        from app.models.lop import LopMeeting, LopMeetingMark
        pids = {ln.project_id for ln in lines}
        # only the newest meeting and the newest closed meeting per project
        def newest(*where):
            rn = func.row_number().over(
                partition_by=LopMeeting.project_id,
                order_by=(LopMeeting.held_on.desc(), LopMeeting.id.desc())).label("rn")
            sub = select(LopMeeting.id, rn).where(LopMeeting.project_id.in_(pids), *where).subquery()
            return select(LopMeeting).join(sub, sub.c.id == LopMeeting.id).where(sub.c.rn == 1)
        for m in (await session.execute(newest())).scalars().all():
            ctx.meetings[m.project_id] = {"id": m.id, "held_on": m.held_on.isoformat(),
                                          "open": m.closed_at is None}
        for m in (await session.execute(
                newest(LopMeeting.closed_at.is_not(None)))).scalars().all():
            ctx.last_meeting[m.project_id] = m.held_on
        open_ids = [d["id"] for d in ctx.meetings.values() if d["open"]]
        if open_ids:
            ctx.marks = dict((await session.execute(
                select(LopMeetingMark.line_id, LopMeetingMark.mark)
                .where(LopMeetingMark.meeting_id.in_(open_ids)))).all())
        return ctx

    # ----------------------------------------------------------- line_dict
    @staticmethod
    def _text_and_label(line: LopLine, ctx: Optional[LineContext] = None) -> tuple[Optional[str], str]:
        """What the line says and where it comes from. SEP items and risks
        read their source (lop_sources). A pinned PDB topic says what PDB says
        now, or the text kept at pin time when PDB data is not at hand."""
        src = ctx.sources.get(line.id) if ctx is not None else None
        if src is not None:
            return src["text"], src["label"]
        if line.kind == "pdb_topic":
            live = ctx.pdb.get(line.ref_key) if ctx is not None else None
            return (pdb_topic_text(live) if live else line.title), "PDB topic"
        return line.title, "PM"

    @staticmethod
    def _display_status(line: LopLine, ctx: LineContext) -> str:
        """The line's status, or closed when its source closed (SEP item done,
        gate closed, risk finished or removed) and a sync has not caught up."""
        src = ctx.sources.get(line.id)
        return "closed" if src is not None and src["closed"] else line.status

    @staticmethod
    def _state(line: LopLine, ctx: LineContext) -> rules.LineState:
        """The rule inputs. Task 5/6 read a source's own closed state here."""
        resp = ctx.users.get(line.responsible_id) if line.responsible_id else None
        return rules.LineState(
            kind=line.kind, status=LopService._display_status(line, ctx), responsible_id=line.responsible_id,
            responsible_active=bool(resp and resp.is_active), due_date=line.due_date,
            first_due_date=line.first_due_date, next_check_date=line.next_check_date,
            last_update_at=to_local(line.last_update_at), closed_at=to_local(line.closed_at),
            pinned=line.kind == "pdb_topic",
            reopened=line.id in ctx.reopened)

    @staticmethod
    def line_dict(line: LopLine, ctx: LineContext) -> dict:
        s = LopService._state(line, ctx)
        today, stale_days = ctx.today, get_settings().lop_stale_days
        text, label = LopService._text_and_label(line, ctx)
        src = ctx.sources.get(line.id) or {}
        status = LopService._display_status(line, ctx)
        created_on = local_date(line.created_at or datetime.utcnow())
        d = {
            "id": line.id, "project_id": line.project_id, "kind": line.kind,
            "ref_key": line.ref_key, "title": line.title,
            "department_id": line.department_id, "responsible_id": line.responsible_id,
            "responsible_is_default": line.responsible_is_default,
            "due_date": _iso(line.due_date), "first_due_date": _iso(line.first_due_date),
            "due_is_default": line.due_is_default, "next_check_date": _iso(line.next_check_date),
            "status": status, "closed_at": _iso(line.closed_at), "closed_by": line.closed_by,
            "last_update_at": _iso(line.last_update_at), "last_update_by": line.last_update_by,
            "created_at": _iso(line.created_at), "created_by": line.created_by,
            "source_label": label, "text": text, "source_context": src.get("context"),
            "source_closed": bool(src.get("closed")),
            "department_name": ctx.departments.get(line.department_id),
            "responsible_name": _uname(ctx.users.get(line.responsible_id)),
            "days_late": rules.days_late(s, today),
            "late": rules.is_late(s, today),
            "stale": rules.is_stale(s, today, stale_days),
            "under_control": rules.under_control(s),
            "group": rules.group_of(s, today, stale_days,
                                   ctx.last_meeting.get(line.project_id), created_on),
            "moved": line.due_date != line.first_due_date,
            "reopened": s.reopened,
            "meeting": ctx.meetings.get(line.project_id),
            "meeting_mark": ctx.marks.get(line.id),
            "last_comment": ctx.last_comments.get(line.id),
            "can_manage": ctx.can_manage,
            "can_report": (line.responsible_id == ctx.user_id and status != "closed"
                           and not ctx.can_manage),
        }
        if line.kind == "pdb_topic":
            d.update(pinned=True, **_pdb_fields(ctx.pdb.get(line.ref_key)))
        return d

    @staticmethod
    def pdb_topic_dict(topic: dict, ctx: LineContext) -> dict:
        """An open PDB topic nobody pinned: a reference with no name and no
        date. Never late, never stale, group "pdb"."""
        s = rules.LineState(
            kind="pdb_topic", status="open", responsible_id=None, responsible_active=False,
            due_date=None, first_due_date=None, next_check_date=None,
            last_update_at=None, closed_at=None, pinned=False)
        stale_days = get_settings().lop_stale_days
        return {
            "id": None, "project_id": None, "kind": "pdb_topic", "ref_key": str(topic["id"]),
            "title": None, "department_id": None, "responsible_id": None,
            "responsible_is_default": False, "due_date": None, "first_due_date": None,
            "due_is_default": False, "next_check_date": None, "status": "open",
            "closed_at": None, "closed_by": None, "last_update_at": None, "last_update_by": None,
            "created_at": None, "created_by": None, "source_label": "PDB topic",
            "text": pdb_topic_text(topic), "source_context": None, "source_closed": False,
            "department_name": topic.get("department"), "responsible_name": None,
            "days_late": 0, "late": rules.is_late(s, ctx.today),
            "stale": rules.is_stale(s, ctx.today, stale_days),
            "under_control": rules.under_control(s),
            "group": rules.group_of(s, ctx.today, stale_days, None, ctx.today),
            "moved": False, "reopened": False, "last_comment": None,
            "can_manage": ctx.can_manage, "can_report": False, "pinned": False,
            **_pdb_fields(topic),
        }
