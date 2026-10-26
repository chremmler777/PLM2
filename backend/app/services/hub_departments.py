"""Department membership from AdminPanel (migration 150, Christoph
2026-10-26): a hub account is a member of exactly the active departments
whose hub_role its token carries (plm2_Sales, plm2_ToolEngineer, ...).
get_current_user syncs user_departments to that set on every request,
writing only when it differs. Local (non-hub) accounts keep what is stored;
placeholder accounts have no memberships (migration 150 deleted them) and
the per-user PUT refuses hub accounts (409). plm2_Admin stays admin and is
a member only through department roles; plm2_Viewer alone is no member.

settings.hub_department_sync (env HUB_DEPARTMENT_SYNC) switches the sync
off: memberships then stay as stored."""
from __future__ import annotations

from sqlalchemy import delete, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import Department, UserDepartment

#: The hashed_password sentinel of a hub-provisioned account.
HUB_MANAGED = "!"


def is_hub_account(user) -> bool:
    return getattr(user, "hashed_password", None) == HUB_MANAGED


def member_clause():
    """A WHERE clause on User for "may count as a department member": hub
    accounts only, unless settings.local_users_as_members (the tests)."""
    from app.core.config import get_settings
    from app.models.entities import User
    if get_settings().local_users_as_members:
        return true()
    return User.hashed_password == HUB_MANAGED


async def wanted_department_ids(session: AsyncSession, hub_roles: list[str]) -> set[int]:
    """The active departments whose hub role is among the token's roles."""
    roles = [r for r in hub_roles if r]
    if not roles:
        return set()
    return set((await session.execute(select(Department.id).where(
        Department.hub_role.in_(roles), Department.is_active.is_(True)))).scalars().all())


async def sync_memberships(session: AsyncSession, user_id: int,
                           hub_roles: list[str]) -> tuple[set[int], bool]:
    """Make the user's user_departments exactly the token's departments.
    Returns (department ids, changed); commits only when it changed."""
    wanted = await wanted_department_ids(session, hub_roles)
    have = set((await session.execute(select(UserDepartment.department_id).where(
        UserDepartment.user_id == user_id))).scalars().all())
    if have == wanted:
        return wanted, False
    gone = have - wanted
    if gone:
        await session.execute(delete(UserDepartment).where(
            UserDepartment.user_id == user_id, UserDepartment.department_id.in_(gone)))
    for dept_id in sorted(wanted - have):
        session.add(UserDepartment(user_id=user_id, department_id=dept_id))
    await session.commit()
    return wanted, True
