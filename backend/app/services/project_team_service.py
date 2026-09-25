"""The project team (spec 2026-09-25): one responsible (main owner) user per
department per project. Everyone else active in that department, in the
project's organization, is a backup for that role -- they still see and can
act on the department's work there, but it does not count as theirs.

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
            row = rows.get(d.id)
            main_id = row.user_id if row is not None else None
            if main_id is not None and not any(m.id == main_id for m in members):
                # The responsible left the department/org: fall back to legacy
                # (everyone main) rather than pointing at a stale user.
                main_id = None
            responsible = ({"id": main_id, "name": next(
                (_name(m) for m in members if m.id == main_id), None)}
                if main_id is not None else None)
            member_rows = [
                {"id": m.id, "name": _name(m),
                 "role": "main" if main_id is None or m.id == main_id else "backup"}
                for m in members
            ]
            out.append({
                "department_id": d.id,
                "department_name": d.name,
                "responsible": responsible,
                "members": member_rows,
            })
        return out

    @staticmethod
    async def set_responsible(session: AsyncSession, project_id: int,
                              department_id: int, user_id: int, actor: User) -> None:
        org_id = await _project_org_id(session, project_id)
        dept = await session.get(Department, department_id)
        if dept is None:
            raise ProjectTeamError("Department not found")
        candidate = await session.get(User, user_id)
        if (candidate is None or not candidate.is_active
                or (org_id is not None and candidate.organization_id != org_id)):
            raise ProjectTeamError(
                "The responsible must be an active user of this organization")
        is_member = (await session.execute(
            select(UserDepartment.user_id).where(
                UserDepartment.user_id == user_id,
                UserDepartment.department_id == department_id)
        )).scalar_one_or_none() is not None
        if not is_member:
            raise ProjectTeamError(
                f"The responsible must be an active member of the {dept.name} department")
        row = (await session.execute(
            select(ProjectResponsible).where(
                ProjectResponsible.project_id == project_id,
                ProjectResponsible.department_id == department_id)
        )).scalar_one_or_none()
        if row is None:
            row = ProjectResponsible(project_id=project_id, department_id=department_id)
            session.add(row)
        row.user_id = user_id
        row.set_by = actor.id
        row.set_at = datetime.utcnow()
        await session.flush()

    @staticmethod
    async def clear_responsible(session: AsyncSession, project_id: int,
                                department_id: int) -> None:
        row = (await session.execute(
            select(ProjectResponsible).where(
                ProjectResponsible.project_id == project_id,
                ProjectResponsible.department_id == department_id)
        )).scalar_one_or_none()
        if row is not None:
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
        row = (await session.execute(
            select(ProjectResponsible).where(
                ProjectResponsible.project_id == project_id,
                ProjectResponsible.department_id == dept_id)
        )).scalar_one_or_none()
        if row is None:
            return None
        # A responsible who left the department no longer counts.
        is_member = (await session.execute(
            select(UserDepartment.user_id).where(
                UserDepartment.user_id == row.user_id,
                UserDepartment.department_id == dept_id)
        )).scalar_one_or_none() is not None
        return row.user_id if is_member else None

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
        responsible, or the user IS the responsible)."""
        if department_id is None:
            return None
        resp = await _responsible(session, project_id, department_id)
        if resp is None or resp[0] == user_id:
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
    "kickoff": SALES,
    "scoping_wrapup": PM, "close_question": PM, "info_send": PM,
    "inform_mother_plant": PM, "timing_validate": PM, "lessons_step": PM,
    "validation_issue_route": PM, "validation_issue_close": PM,
    "impact_confirm": DEVELOPMENT, "review_escalate": DEVELOPMENT,
    "intake_triage": DEVELOPMENT,
    "send_rejection": SALES, "create_quote": SALES, "customer_response": SALES,
    "publish_plan": SALES, "offer_expiring": SALES, "escalate_risk": SALES,
    "update_quote": SALES, "obtain_info": SALES, "offer_build": SALES,
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
                       owned: bool = False) -> dict:
        role, main = await self.role(project_id, await self.row_department(row), owned)
        row["role"] = role
        row["main_name"] = main
        return row


async def _responsible(session: AsyncSession, project_id: Optional[int],
                       department_id: Optional[int]) -> Optional[tuple[int, str]]:
    """(user_id, name) of the project's responsible for the department, or
    None: no project, no row, or a stale row (the responsible is inactive or
    left the department -- legacy behaviour applies then)."""
    if project_id is None or department_id is None:
        return None
    row = (await session.execute(
        select(ProjectResponsible.user_id, User.full_name, User.username, User.is_active)
        .join(User, User.id == ProjectResponsible.user_id)
        .where(ProjectResponsible.project_id == project_id,
               ProjectResponsible.department_id == department_id)
    )).first()
    if row is None or not row.is_active:
        return None
    is_member = (await session.execute(
        select(UserDepartment.user_id).where(
            UserDepartment.user_id == row.user_id,
            UserDepartment.department_id == department_id)
    )).first() is not None
    if not is_member:
        return None
    return row.user_id, (row.full_name or row.username)
