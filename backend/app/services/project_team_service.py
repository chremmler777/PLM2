"""The project team (spec 2026-09-25): one responsible (main owner) user per
department per project. Everyone else active in that department, in the
project's organization, is a backup for that role -- they still see and can
act on the department's work there, but it does not count as theirs.

D2b (DECIDED BY CHRISTOPH 2026-10-19): plus a NAMED backup per department
per project. The department's tasks go to the responsible; to the named
backup when the responsible is inactive, left the department or is not set
(the backup is then the main owner); and to the named backup too once a task
is overdue (TeamRoles.covering, the late sweep). Project Management (or an
admin) sets both and so reassigns.

No row for a department on a project -> today's behaviour: every active
member of the department counts as main (nobody is a backup)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Plant, Project, User
from app.models.workflow import Department, ProjectResponsible, UserDepartment


class ProjectTeamError(Exception):
    """400: the target user cannot be set for this role."""


def _name(u: User) -> str:
    return u.full_name or u.username


async def _project_org_id(session: AsyncSession, project_id: int) -> Optional[int]:
    return (await session.execute(
        select(Plant.organization_id).join(Project, Project.plant_id == Plant.id)
        .where(Project.id == project_id)
    )).scalar_one_or_none()


async def is_live_member(session: AsyncSession, user_id: Optional[int],
                         department_name: str) -> bool:
    """An active user with a real (not acting-as) membership of the named
    department. The one test for a named owner (C10 Sales owner, a project
    responsible): an inactive user, one who left the department, or a member
    of a retired department owns nothing, and the department's work falls back to all of its members."""
    if user_id is None:
        return False
    return (await session.execute(
        select(UserDepartment.user_id)
        .join(Department, Department.id == UserDepartment.department_id)
        .join(User, User.id == UserDepartment.user_id)
        .where(UserDepartment.user_id == user_id,
               Department.name == department_name,
               # a retired department grants nothing (R25)
               Department.is_active.is_(True),
               User.is_active.is_(True))
    )).first() is not None


class ProjectTeamService:
    @staticmethod
    async def user_can_manage(session: AsyncSession, user: User) -> bool:
        """PM members or admin -- the same right that manages the project
        team and picks an explicit change lead."""
        from app.services.meeting_service import MeetingService
        return await MeetingService.user_is_pm(session, user)

    @staticmethod
    async def department_members(session: AsyncSession, department_id: int,
                                 org_id: Optional[int]) -> list[User]:
        q = (select(User).join(UserDepartment, UserDepartment.user_id == User.id)
             .where(UserDepartment.department_id == department_id,
                    User.is_active.is_(True)))
        if org_id is not None:
            q = q.where(User.organization_id == org_id)
        return list((await session.execute(q)).scalars().all())

    @staticmethod
    async def list_team(session: AsyncSession, project_id: int) -> list[dict]:
        """[{department_id, department_name, responsible: {id,name}|None,
        members: [{id, name, role: "main"|"backup"}]}] for every active
        department. `responsible` is null when nobody was set for the role
        (legacy: every member below reads role "main"); `members` is every
        active department member of the project's organization, candidates
        for the picker."""
        org_id = await _project_org_id(session, project_id)
        depts = list((await session.execute(
            select(Department).where(Department.is_active.is_(True))
            .order_by(Department.sort_order, Department.name)
        )).scalars().all())
        rows = {r.department_id: r for r in (await session.execute(
            select(ProjectResponsible).where(ProjectResponsible.project_id == project_id)
        )).scalars().all()}
        out = []
        for d in depts:
            members = await ProjectTeamService.department_members(session, d.id, org_id)
            names = {m.id: _name(m) for m in members}
            row = rows.get(d.id)
            # A responsible / backup who left the department or the org (or
            # is inactive) is not listed: the slot reads unassigned.
            main_id = row.user_id if row is not None and row.user_id in names else None
            backup_id = (row.backup_user_id if row is not None
                         and row.backup_user_id in names else None)
            # D2b: the named backup owns the work while nobody is responsible
            owner_id = main_id if main_id is not None else backup_id
            member_rows = [
                {"id": m.id, "name": names[m.id],
                 "role": "main" if owner_id is None or m.id == owner_id else "backup",
                 **({"named_backup": True} if m.id == backup_id else {})}
                for m in members
            ]
            out.append({
                "department_id": d.id,
                "department_name": d.name,
                "responsible": ({"id": main_id, "name": names[main_id]}
                                if main_id is not None else None),
                "backup": ({"id": backup_id, "name": names[backup_id]}
                           if backup_id is not None else None),
                "members": member_rows,
            })
        return out

    @staticmethod
    async def _check_member(session: AsyncSession, project_id: int,
                            department_id: int, user_id: int, word: str) -> Department:
        org_id = await _project_org_id(session, project_id)
        dept = await session.get(Department, department_id)
        if dept is None:
            raise ProjectTeamError("Department not found")
        candidate = await session.get(User, user_id)
        if (candidate is None or not candidate.is_active
                or (org_id is not None and candidate.organization_id != org_id)):
            raise ProjectTeamError(
                f"The {word} must be an active user of this organization")
        is_member = (await session.execute(
            select(UserDepartment.user_id).where(
                UserDepartment.user_id == user_id,
                UserDepartment.department_id == department_id)
        )).scalar_one_or_none() is not None
        if not is_member:
            raise ProjectTeamError(
                f"The {word} must be an active member of the {dept.name} department")
        return dept

    @staticmethod
    async def _row(session: AsyncSession, project_id: int,
                   department_id: int) -> Optional[ProjectResponsible]:
        return (await session.execute(
            select(ProjectResponsible).where(
                ProjectResponsible.project_id == project_id,
                ProjectResponsible.department_id == department_id)
        )).scalar_one_or_none()

    @staticmethod
    async def set_responsible(session: AsyncSession, project_id: int,
                              department_id: int, user_id: int, actor: User,
                              slot: str = "responsible") -> None:
        """Set the responsible (slot "responsible") or the named backup
        (slot "backup", D2b) of one department on this project. Both are
        active members of the department, and two different people."""
        word = "backup" if slot == "backup" else "responsible"
        await ProjectTeamService._check_member(
            session, project_id, department_id, user_id, word)
        row = await ProjectTeamService._row(session, project_id, department_id)
        other = (None if row is None else
                 row.user_id if slot == "backup" else row.backup_user_id)
        if other == user_id:
            raise ProjectTeamError(
                "The responsible and the backup must be two different people")
        if row is None:
            row = ProjectResponsible(project_id=project_id, department_id=department_id)
            session.add(row)
        if slot == "backup":
            row.backup_user_id = user_id
        else:
            row.user_id = user_id
        row.set_by = actor.id
        row.set_at = datetime.utcnow()
        await session.flush()

    @staticmethod
    async def clear_responsible(session: AsyncSession, project_id: int,
                                department_id: int, slot: str = "responsible") -> None:
        """Clear one slot; the row goes once neither is set (legacy)."""
        row = await ProjectTeamService._row(session, project_id, department_id)
        if row is None:
            return
        if slot == "backup":
            row.backup_user_id = None
        else:
            row.user_id = None
        if row.user_id is None and row.backup_user_id is None:
            await session.delete(row)
        await session.flush()

    @staticmethod
    async def responsible_user_id(session: AsyncSession, project_id: Optional[int],
                                  department_name: str) -> Optional[int]:
        """The project's responsible for this department, or None (unset, or
        no project / department)."""
        if project_id is None:
            return None
        dept_id = (await session.execute(
            select(Department.id).where(Department.name == department_name)
        )).scalar_one_or_none()
        if dept_id is None:
            return None
        row = await ProjectTeamService._row(session, project_id, dept_id)
        if row is None or row.user_id is None:
            return None
        # A responsible who is inactive or left the department no longer
        # counts. (The named backup is not a default: a change's lead or
        # Sales contact is the responsible or nobody.)
        return (row.user_id if await is_live_member(
            session, row.user_id, department_name) else None)

    @staticmethod
    async def role_for_user(session: AsyncSession, project_id: Optional[int],
                            department_id: int, user_id: int) -> str:
        """"main" or "backup" for this user's standing on this department's
        work for this project. No project, no row, a stale row (the
        responsible left the department), or the row points at this user ->
        "main" (legacy / actual owner)."""
        resp = await _responsible(session, project_id, department_id)
        return "main" if resp is None or resp[0] == user_id else "backup"

    @staticmethod
    async def main_name(session: AsyncSession, project_id: Optional[int],
                        department_id: int) -> Optional[str]:
        resp = await _responsible(session, project_id, department_id)
        return resp[1] if resp else None

    # ------------------------------------------------------------------
    # Audit: a backup acting for the responsible
    # ------------------------------------------------------------------
    @staticmethod
    async def stand_in(session: AsyncSession, project_id: Optional[int],
                       department_id: Optional[int], user_id: int) -> Optional[dict]:
        """{"user_id", "name"} of the responsible this user stands in for when
        they act on the department's work on this project, or None (no
        responsible, the user IS the responsible, or the user is not a member
        of the department at all: an admin, the PM or the change lead acting
        from outside is nobody's backup)."""
        if department_id is None:
            return None
        resp = await _responsible(session, project_id, department_id)
        if resp is None or resp[0] == user_id:
            return None
        member = (await session.execute(
            select(UserDepartment.user_id).where(
                UserDepartment.user_id == user_id,
                UserDepartment.department_id == department_id))).first() is not None
        if not member:
            return None
        return {"user_id": resp[0], "name": resp[1], "department_id": department_id}

    @staticmethod
    async def stand_in_note(session: AsyncSession, stand_in: dict, user_id: int) -> str:
        """"<backup> for <main>", the audit line of a stand-in act."""
        actor = await session.get(User, user_id)
        who = _name(actor) if actor is not None else f"user {user_id}"
        return f"{who} for {stand_in['name']}"

    # ------------------------------------------------------------------
    # Notifications: the responsible first, backups as info
    # ------------------------------------------------------------------
    @staticmethod
    async def split_recipients(session: AsyncSession, project_id: Optional[int],
                               department_ids, user_ids) -> tuple[list[int], dict[int, str]]:
        """Split the members notified for these departments on this project
        into mains (the responsible, or everybody where no responsible is
        set) and backups ({user_id: main name}). A user who is main for any
        of the departments counts as main."""
        dept_ids = sorted({int(d) for d in department_ids or []})
        users = sorted({int(u) for u in user_ids or []})
        if project_id is None or not dept_ids or not users:
            return users, {}
        member_of: dict[int, set[int]] = {}
        for uid, did in (await session.execute(
                select(UserDepartment.user_id, UserDepartment.department_id).where(
                    UserDepartment.user_id.in_(users),
                    UserDepartment.department_id.in_(dept_ids)))).all():
            member_of.setdefault(uid, set()).add(did)
        resp = {d: await _responsible(session, project_id, d) for d in dept_ids}
        mains: list[int] = []
        backups: dict[int, str] = {}
        for uid in users:
            depts = member_of.get(uid) or set()
            if not depts:
                mains.append(uid)  # not a member (e.g. named personally)
                continue
            backup_of = [resp[d][1] for d in sorted(depts)
                         if resp[d] is not None and resp[d][0] != uid]
            if len(backup_of) == len(depts):
                backups[uid] = backup_of[0]
            else:
                mains.append(uid)
        return mains, backups


# ----------------------------------------------------------------------
# Task lists: which department a row belongs to, and the viewer's role on it
# ----------------------------------------------------------------------
PM = "Project Manager"
SALES = "Sales"
DEVELOPMENT = "Development"
SCHEDULING = "Scheduling"

# Rows that carry the owing department in department_id.
DEPARTMENT_ROW_KINDS = frozenset({
    "assessment", "costing_input", "costing_update", "plan_feedback", "info_ack",
    "release_check", "progress_report", "review_answer", "validation_check",
})

# Rows owed by a fixed role (the department does not ride on the row).
KIND_DEPARTMENT: dict[str, str] = {
    # D2 (2026-10-19): Project Management owns the process from capture on
    "kickoff": PM, "escalate_risk": PM,
    "scoping_wrapup": PM, "close_question": PM, "info_send": PM,
    "inform_mother_plant": PM, "timing_validate": PM, "lessons_step": PM,
    "validation_issue_route": PM, "validation_issue_close": PM,
    "impact_confirm": DEVELOPMENT, "review_escalate": DEVELOPMENT,
    "intake_triage": DEVELOPMENT,
    "send_rejection": SALES, "create_quote": SALES, "customer_response": SALES,
    "publish_plan": SALES, "offer_expiring": SALES,
    # obtain_info is not here (2026-10-14): a question is the ASKING
    # department's task and the row carries it in role_department_id.
    "update_quote": SALES, "offer_build": SALES,
    "needs_info": SALES, "validation_issue_customer": SALES,
    "validation_issue_quote": SALES,
    "bank_build": SCHEDULING,
}


class TeamRoles:
    """Per-request resolver of the viewer's role on task rows. Caches the
    responsible per (project, department) so a long list costs one lookup
    per pair."""

    def __init__(self, session: AsyncSession, user_id: int):
        self.session = session
        self.user_id = user_id
        self._resp: dict[tuple[int, int], Optional[tuple[int, str]]] = {}
        self._dept_by_name: Optional[dict[str, int]] = None
        self._live_sales: dict[int, bool] = {}
        self._pairs: dict[tuple[int, int], tuple] = {}

    async def department_id(self, name: str) -> Optional[int]:
        if self._dept_by_name is None:
            self._dept_by_name = {n: i for i, n in (await self.session.execute(
                select(Department.id, Department.name))).all()}
        return self._dept_by_name.get(name)

    async def responsible(self, project_id: Optional[int],
                          department_id: Optional[int]) -> Optional[tuple[int, str]]:
        if project_id is None or department_id is None:
            return None
        key = (project_id, department_id)
        if key not in self._resp:
            self._resp[key] = await _responsible(self.session, project_id, department_id)
        return self._resp[key]

    async def row_department(self, row: dict) -> Optional[int]:
        """The department that owes this row: its own role_department_id,
        its department_id for per-department kinds, else the kind's role."""
        if row.get("role_department_id") is not None:
            return row["role_department_id"]
        kind = row.get("kind")
        if kind in DEPARTMENT_ROW_KINDS and row.get("department_id") is not None:
            return row["department_id"]
        name = KIND_DEPARTMENT.get(kind or "")
        return await self.department_id(name) if name else None

    async def covering(self, project_id: Optional[int],
                       department_id: Optional[int]) -> Optional[str]:
        """D2b: the responsible's name when the viewer is the department's
        named backup on this project and the responsible is live (an
        overdue task then goes to the viewer too), else None."""
        if project_id is None or department_id is None:
            return None
        key = (project_id, department_id)
        if key not in self._pairs:
            self._pairs[key] = await _pair(self.session, project_id, department_id)
        resp, backup = self._pairs[key]
        if resp is None or backup is None or backup[0] != self.user_id:
            return None
        return resp[1]

    async def role(self, project_id: Optional[int], department_id: Optional[int],
                   owned: bool = False) -> tuple[str, Optional[str]]:
        """("main"|"backup", main name when backup). A row the viewer owns
        (took it, or leads the change) is main whatever the team says."""
        if owned:
            return "main", None
        resp = await self.responsible(project_id, department_id)
        if resp is None or resp[0] == self.user_id:
            return "main", None
        return "backup", resp[1]

    async def annotate(self, row: dict, project_id: Optional[int],
                       owned: bool = False,
                       sales_owner: Optional[tuple[int, str]] = None) -> dict:
        """sales_owner (C10): (id, name) of the change's Sales owner. On a
        Sales row it takes the project responsible's place: the owner sees
        it as main, the rest of Sales as backup with the owner's name."""
        dept = await self.row_department(row)
        # A run-team row names its owner (the change lead): the viewer backs
        # them up unless it is theirs.
        main_user = row.pop("main_user", None)
        if main_user is not None:
            # (None, "Project Management"): a department owns it, never
            # this viewer (A6-04: the lead-less kickoff is PM's)
            mine = main_user[0] is not None and (owned or main_user[0] == self.user_id)
            row["role"] = "main" if mine else "backup"
            row["main_name"] = None if mine else main_user[1]
            return row
        if sales_owner is not None and sales_owner[0] not in self._live_sales:
            self._live_sales[sales_owner[0]] = await is_live_member(
                self.session, sales_owner[0], SALES)
        if sales_owner is not None and not self._live_sales[sales_owner[0]]:
            # a stale owner (inactive, left Sales) owns nothing: the row
            # falls back to the project team / all of Sales as main
            sales_owner = None
        if (sales_owner is not None and dept is not None
                and dept == await self.department_id(SALES)):
            if owned or sales_owner[0] == self.user_id:
                role, main = "main", None
            else:
                role, main = "backup", sales_owner[1]
        else:
            role, main = await self.role(project_id, dept, owned)
            # D2b: the project team decided it; an overdue row may still go
            # to the named backup (promote_overdue, after the due rules)
            row["_team_dept"] = dept
        row["role"] = role
        row["main_name"] = main
        return row

    async def promote_overdue(self, row: dict) -> dict:
        """D2b: an overdue department task goes to the named backup too: the
        backup's row turns main with `covering_for` = the responsible's name.
        Call after due_rules.annotate_tasks (it sets `overdue`)."""
        dept = row.pop("_team_dept", None)
        if row.get("role") != "backup" or not row.get("overdue"):
            return row
        name = await self.covering(row.get("project_id"), dept)
        if name is not None:
            row["role"], row["main_name"], row["covering_for"] = "main", None, name
        return row


async def _pair(session: AsyncSession, project_id: Optional[int],
                department_id: Optional[int]) -> tuple:
    """(responsible, backup) of the department on the project, each
    (user_id, name) or None: not set, inactive, or no longer a member of the
    department (stale: it counts as not set)."""
    if project_id is None or department_id is None:
        return None, None
    row = (await session.execute(
        select(ProjectResponsible.user_id, ProjectResponsible.backup_user_id)
        .where(ProjectResponsible.project_id == project_id,
               ProjectResponsible.department_id == department_id)
    )).first()
    if row is None:
        return None, None
    ids = [i for i in (row.user_id, row.backup_user_id) if i is not None]
    if not ids:
        return None, None
    live = {u.id: (u.full_name or u.username) for u in (await session.execute(
        select(User).join(UserDepartment, UserDepartment.user_id == User.id)
        .where(User.id.in_(ids), User.is_active.is_(True),
               UserDepartment.department_id == department_id))).scalars().all()}

    def one(uid):
        return (uid, live[uid]) if uid in live else None
    return one(row.user_id), one(row.backup_user_id)


async def _responsible(session: AsyncSession, project_id: Optional[int],
                       department_id: Optional[int]) -> Optional[tuple[int, str]]:
    """(user_id, name) of who owns the department's work on the project:
    the responsible; D2b: the named backup when the responsible is not set,
    inactive or left the department; None when neither is live (legacy
    behaviour applies then: the whole department)."""
    resp, backup = await _pair(session, project_id, department_id)
    return resp or backup
