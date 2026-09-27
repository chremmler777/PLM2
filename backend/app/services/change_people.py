"""Who someone is on a change, shared by the change services.

- Acting as a department (an admin's acts-as) is being exactly that
  department: the personal change-lead privilege steps aside, like the admin
  bypass does (effective_role). Every lead check that grants a right goes
  through holds_lead so the rule is the same everywhere.
- Notifications about a change reach only people of the change's
  organization (its project's plant), never a namesake department elsewhere.
"""
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def is_acting(user) -> bool:
    """An admin acting as a department."""
    return getattr(user, "acts_as_department_id", None) is not None


def holds_lead(change, user) -> bool:
    """The user is the change lead AND not acting as a department."""
    return (not is_acting(user) and change.lead_id is not None
            and change.lead_id == user.id)


async def change_org_id(session: AsyncSession, change) -> Optional[int]:
    """The organization of the change's project; None without a project."""
    if getattr(change, "project_id", None) is None:
        return None
    from app.models.entities import Plant, Project
    return (await session.execute(
        select(Plant.organization_id).join(Project, Project.plant_id == Plant.id)
        .where(Project.id == change.project_id))).scalar_one_or_none()


async def department_members_of_change_org(
        session: AsyncSession, change, department_ids: Iterable[int]) -> list[int]:
    """Active members of these departments in the change's organization (every
    member when the change has no organization)."""
    from app.models.entities import User
    from app.models.workflow import UserDepartment
    ids = sorted({int(d) for d in department_ids or []})
    if not ids:
        return []
    q = (select(UserDepartment.user_id)
         .join(User, User.id == UserDepartment.user_id)
         .where(UserDepartment.department_id.in_(ids), User.is_active.is_(True)))
    org_id = await change_org_id(session, change)
    if org_id is not None:
        q = q.where(User.organization_id == org_id)
    return sorted(set((await session.execute(q)).scalars().all()))
