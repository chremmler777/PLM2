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


def hard3_blind(user) -> bool:
    """A real admin account not acting as a department. For HARD #3 (C7)
    decisions (recording or retesting a validation check, Quality's Fix pick
    and concession) its own department rows do not count, the same rule as
    staffed_department_ids: an admin belongs to every department in a small
    plant's set-up and would otherwise lift HARD #3 alone. An admin who
    stands in for a department acts as it (acts-as puts it on the record)."""
    return getattr(user, "effective_role", None) == "admin"


async def change_org_id(session: AsyncSession, change) -> Optional[int]:
    """The organization of the change's project; None without a project."""
    if getattr(change, "project_id", None) is None:
        return None
    from app.models.entities import Plant, Project
    return (await session.execute(
        select(Plant.organization_id).join(Project, Project.plant_id == Plant.id)
        .where(Project.id == change.project_id))).scalar_one_or_none()


async def department_members_of_change_org(
        session: AsyncSession, change, department_ids: Iterable[int],
        *, real_only: bool = False) -> list[int]:
    """Active members of these departments in the change's organization (every
    member when the change has no organization). real_only: without admin
    accounts (the rule of staffed_department_ids)."""
    from app.models.entities import User
    from app.models.workflow import UserDepartment
    ids = sorted({int(d) for d in department_ids or []})
    if not ids:
        return []
    q = (select(UserDepartment.user_id)
         .join(User, User.id == UserDepartment.user_id)
         .where(UserDepartment.department_id.in_(ids), User.is_active.is_(True)))
    if real_only:
        q = q.where(User.role != "admin")
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


async def real_member_names(session: AsyncSession, change,
                            department_ids: Iterable[int]) -> dict[int, list[str]]:
    """department id -> full names of its real members on this change (the
    rule of staffed_department_ids); a department missing from the result
    has nobody here."""
    from app.models.entities import User
    from app.models.workflow import Department, UserDepartment
    ids = sorted({int(d) for d in department_ids or [] if d is not None})
    if not ids:
        return {}
    q = (select(UserDepartment.department_id, User.full_name, User.username)
         .join(User, User.id == UserDepartment.user_id)
         .join(Department, Department.id == UserDepartment.department_id)
         .where(UserDepartment.department_id.in_(ids), User.is_active.is_(True),
                User.role != "admin", Department.is_active.is_(True)))
    org_id = await change_org_id(session, change)
    if org_id is not None:
        q = q.where(User.organization_id == org_id)
    out: dict[int, list[str]] = {}
    for did, full, user in (await session.execute(q.distinct())).all():
        out.setdefault(did, []).append(full or user)
    return out


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



def _lead_acts(lead) -> bool:
    """A lead who can coordinate: active and not an admin account (an admin
    does not decide HARD #3 alone, hard3_blind)."""
    return lead is not None and bool(lead.is_active) and lead.role != "admin"


async def coordinator(session: AsyncSession, change) -> tuple[Optional[int], str]:
    """Who coordinates a department with no real member here (R37): the
    change lead (id, name), else Project Management (None, its name)."""
    if getattr(change, "lead_id", None) is not None:
        from app.models.entities import User
        lead = await session.get(User, change.lead_id)
        if _lead_acts(lead):
            return lead.id, lead.full_name or lead.username
    return None, "Project Management"


async def coordinator_name(session: AsyncSession, change) -> str:
    return (await coordinator(session, change))[1]


async def coordinates(session: AsyncSession, change, user,
                      is_pm_member: Optional[bool] = None) -> bool:
    """Is `user` the one who coordinates member-less departments on this
    change: the lead, or with no lead who can act a Project Management
    member (never an admin account, never acting as a department)."""
    if is_acting(user) or getattr(user, "effective_role", None) == "admin":
        return False
    lead_id, _ = await coordinator(session, change)
    if lead_id is not None:
        return lead_id == user.id
    if is_pm_member is None:
        from app.services.meeting_service import MeetingService
        is_pm_member = await MeetingService.user_is_pm_member(session, user)
    return bool(is_pm_member)


def no_member_words(department_name: Optional[str], coordinator: str) -> str:
    """The one phrase of the fallback (A5-04 d): '<X> has no member here:
    <lead name|Project Management> coordinates'."""
    return f"{department_name or 'This department'} has no member here: {coordinator} coordinates"
