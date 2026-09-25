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
        work for this project. No project, no row, or the row points at this
        user -> "main" (legacy / actual owner)."""
        if project_id is None:
            return "main"
        row = (await session.execute(
            select(ProjectResponsible).where(
                ProjectResponsible.project_id == project_id,
                ProjectResponsible.department_id == department_id)
        )).scalar_one_or_none()
        if row is None or row.user_id == user_id:
            return "main"
        # A stale responsible (no longer a department member) falls back to
        # legacy behaviour: everyone active in the department is main.
        is_member = (await session.execute(
            select(UserDepartment.user_id).where(
                UserDepartment.user_id == row.user_id,
                UserDepartment.department_id == department_id)
        )).scalar_one_or_none() is not None
        return "main" if not is_member else "backup"

    @staticmethod
    async def main_name(session: AsyncSession, project_id: Optional[int],
                        department_id: int) -> Optional[str]:
        if project_id is None:
            return None
        row = (await session.execute(
            select(ProjectResponsible).where(
                ProjectResponsible.project_id == project_id,
                ProjectResponsible.department_id == department_id)
        )).scalar_one_or_none()
        if row is None:
            return None
        u = await session.get(User, row.user_id)
        return _name(u) if u else None
