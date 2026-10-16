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


async def staffed_department_ids(
        session: AsyncSession, change, department_ids: Iterable[int]) -> set[int]:
    """The departments among these that someone can actually answer for on
    this change: active, with at least one active member in the change's
    organization who is not an admin account. An admin belongs to every
    department in a small plant's set-up; counting the admin would leave a
    row nobody else is asked to answer (C7 fallback: PM or the lead answer
    for a department with no real member)."""
    from app.models.entities import User
    from app.models.workflow import Department, UserDepartment
    ids = sorted({int(d) for d in department_ids or [] if d is not None})
    if not ids:
        return set()
    q = (select(UserDepartment.department_id)
         .join(User, User.id == UserDepartment.user_id)
         .join(Department, Department.id == UserDepartment.department_id)
         .where(UserDepartment.department_id.in_(ids), User.is_active.is_(True),
                User.role != "admin", Department.is_active.is_(True)))
    org_id = await change_org_id(session, change)
    if org_id is not None:
        q = q.where(User.organization_id == org_id)
    return set((await session.execute(q.distinct())).scalars().all())


async def department_is_active(session: AsyncSession, department_id) -> bool:
    """The department exists and is active (a pick of an inactive one would
    reach nobody: effective_department_ids drops it)."""
    if department_id is None:
        return False
    from app.models.workflow import Department
    d = await session.get(Department, department_id)
    return d is not None and bool(d.is_active)


async def staffed_pairs(session: AsyncSession, department_ids: Iterable[int]
                        ) -> set[tuple[int, int]]:
    """(department_id, organization_id) pairs with a real member (the rule of
    staffed_department_ids), for many changes in one query."""
    from app.models.entities import User
    from app.models.workflow import Department, UserDepartment
    ids = sorted({int(d) for d in department_ids or [] if d is not None})
    if not ids:
        return set()
    return set((await session.execute(
        select(UserDepartment.department_id, User.organization_id)
        .join(User, User.id == UserDepartment.user_id)
        .join(Department, Department.id == UserDepartment.department_id)
        .where(UserDepartment.department_id.in_(ids), User.is_active.is_(True),
               User.role != "admin", Department.is_active.is_(True))
        .distinct())).all())


async def change_org_ids(session: AsyncSession, change_ids: Iterable[int]
                         ) -> dict[int, Optional[int]]:
    """change id -> organization of its project (one query)."""
    ids = sorted({int(i) for i in change_ids or []})
    if not ids:
        return {}
    from app.models.change import ChangeRequest
    from app.models.entities import Plant, Project
    out = {i: None for i in ids}
    out.update(dict((await session.execute(
        select(ChangeRequest.id, Plant.organization_id)
        .join(Project, Project.id == ChangeRequest.project_id)
        .join(Plant, Plant.id == Project.plant_id)
        .where(ChangeRequest.id.in_(ids)))).all()))
    return out
