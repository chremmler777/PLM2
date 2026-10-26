"""The Departments page's API (Christoph 2026-10-26: "We need managers for an
escalation overview").

Membership comes from AdminPanel (migration 150: a department's hub_role
on the token, synced at login, app/services/hub_departments.py), so the
page lists members read-only. Everyone logged in reads it; only a real
admin writes (the authenticated row's role, as the per-user PUT /users/{id}
/departments: acting as a department does not lock an admin out).

- GET  /departments/overview          every department: hub role, manager,
                                       members, warnings
- PUT  /departments/{id}/manager      {"user_id": int | null}: name / clear
- POST /departments/{id}/activate     a retired department back in use
- POST /departments/{id}/deactivate   retire it (grants nothing, its members
                                       drop out at their next login)

The manager (migration 149) must be an active member of the department
(Christoph 2026-10-26; whether admins may be offered without membership is
open); one person may manage several departments. Managing grants no
write rights: it routes the overdue digest and My Tasks' "Late in my
departments" group.

Warnings (read by everyone): no manager; the manager inactive or no longer
a member; a member inactive; no members; no hub role mapped. Placeholder /
local accounts are never listed as members (member_clause)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_role
from app.models import Department, User
from app.models.workflow import UserDepartment
from app.services.audit_service import AuditService
from app.services.hub_departments import member_clause

router = APIRouter(prefix="/departments", tags=["departments"])

_admin = require_role("admin")


class ManagerSet(BaseModel):
    """null clears the manager."""
    user_id: Optional[int] = None


def _person(u: User) -> dict:
    return {"id": u.id, "name": u.full_name or u.username, "username": u.username,
            "email": u.email, "is_active": u.is_active}


async def _department(db: AsyncSession, department_id: int) -> Department:
    dept = await db.get(Department, department_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")
    return dept


def _warnings(d: Department, manager: Optional[User], members: list[dict]) -> list[dict]:
    """[{code, level, text}] for the page; level amber or red."""
    out = []
    if not d.is_active:
        return out
    if d.hub_role is None:
        out.append({"code": "no_hub_role", "level": "red",
                    "text": "No AdminPanel role mapped: nobody can become a member"})
    if not members:
        out.append({"code": "no_members", "level": "red", "text": "No members"})
    if d.manager_id is None:
        out.append({"code": "no_manager", "level": "amber", "text": "No manager defined"})
    elif manager is None or not manager.is_active:
        name = (manager.full_name or manager.username) if manager else f"user {d.manager_id}"
        out.append({"code": "manager_inactive", "level": "red",
                    "text": f"Manager {name} is inactive or deleted"})
    elif d.manager_id not in {m["id"] for m in members}:
        out.append({"code": "manager_not_member", "level": "red",
                    "text": f"Manager {manager.full_name or manager.username} is no longer a member"})
    for m in members:
        if not m["is_active"]:
            out.append({"code": "member_inactive", "level": "amber",
                        "text": f"Member {m['name']} is inactive"})
    return out


async def _out(db: AsyncSession, depts: list[Department]) -> list[dict]:
    ids = [d.id for d in depts]
    members: dict[int, list[dict]] = {i: [] for i in ids}
    for dept_id, u in (await db.execute(
            select(UserDepartment.department_id, User)
            .join(User, User.id == UserDepartment.user_id)
            .where(UserDepartment.department_id.in_(ids), member_clause())
            .order_by(User.full_name, User.username))).all():
        members[dept_id].append(_person(u))
    mgr_ids = {d.manager_id for d in depts if d.manager_id is not None}
    managers = {u.id: u for u in (await db.execute(
        select(User).where(User.id.in_(mgr_ids)))).scalars().all()} if mgr_ids else {}
    out = []
    for d in depts:
        m = managers.get(d.manager_id)
        out.append({"id": d.id, "name": d.name, "is_active": d.is_active,
                    "sort_order": d.sort_order, "hub_role": d.hub_role,
                    "manager_id": d.manager_id,
                    "manager_name": (m.full_name or m.username) if m else None,
                    "manager_active": m.is_active if m else None,
                    "members": members[d.id],
                    "warnings": _warnings(d, m, members[d.id])})
    return out


@router.get("/overview")
async def departments_overview(current_user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    """Every department (retired ones too, flagged is_active false), with
    its hub role, manager, members and warnings. Read by everyone."""
    depts = (await db.execute(select(Department).order_by(
        Department.sort_order, Department.name))).scalars().all()
    return await _out(db, list(depts))


@router.put("/{department_id}/manager")
async def set_department_manager(department_id: int, body: ManagerSet,
                                 current_user: User = Depends(_admin),
                                 db: AsyncSession = Depends(get_db)):
    """Name or clear the department's manager: an active member of it."""
    dept = await _department(db, department_id)
    if body.user_id is not None:
        ok = (await db.execute(
            select(User.id).join(UserDepartment, UserDepartment.user_id == User.id)
            .where(User.id == body.user_id, User.is_active.is_(True),
                   UserDepartment.department_id == dept.id, member_clause()))).first()
        if ok is None:
            raise HTTPException(
                status_code=400,
                detail=f"The manager must be an active member of {dept.name}")
    old = dept.manager_id
    dept.manager_id = body.user_id
    await AuditService.record(
        db, entity_type="department", entity_id=dept.id, action="manager_set",
        user_id=current_user.id, old_values={"manager_id": old},
        new_values={"manager_id": body.user_id})
    await db.commit()
    return (await _out(db, [dept]))[0]


async def _set_active(db: AsyncSession, dept: Department, active: bool, actor: User) -> dict:
    if dept.is_active != active:
        dept.is_active = active
        await AuditService.record(
            db, entity_type="department", entity_id=dept.id,
            action="activated" if active else "deactivated", user_id=actor.id,
            old_values={"is_active": not active}, new_values={"is_active": active})
        await db.commit()
    return (await _out(db, [dept]))[0]


@router.post("/{department_id}/activate")
async def activate_department(department_id: int,
                              current_user: User = Depends(_admin),
                              db: AsyncSession = Depends(get_db)):
    """Bring a retired department back into use (pickers, routing)."""
    return await _set_active(db, await _department(db, department_id), True, current_user)


@router.post("/{department_id}/deactivate")
async def deactivate_department(department_id: int,
                                current_user: User = Depends(_admin),
                                db: AsyncSession = Depends(get_db)):
    """Retire a department: it grants nothing and is no pick any more
    (R25); its members drop out of it at their next login."""
    return await _set_active(db, await _department(db, department_id), False, current_user)
