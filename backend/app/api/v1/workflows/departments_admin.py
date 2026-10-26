"""The Departments admin page's API (Christoph 2026-10-26: "We need managers
for an escalation overview"; the page also places people in departments,
which PLM had no screen for).

Department-centric, admin only (the authenticated row's role, as the
per-user PUT /users/{id}/departments: acting as a department does not lock
an admin out of the admin page). Membership is the one UserDepartment
table both endpoints write; the per-user endpoint keeps working.

- GET  /departments/admin            every department, manager and members
- PUT  /departments/{id}/manager     {"user_id": int | null}: name / clear
- PUT  /departments/{id}/members     {"user_ids": [...]}: replace members
- POST /departments/{id}/activate    a retired department back in use

The manager (migration 149) need not be a member and may manage several
departments; managing grants no write rights (it routes the overdue
digest and My Tasks' "Late in my departments" group). Retiring a
department is not offered here: it ends open work (migration 146)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_role
from app.models import Department, User
from app.models.workflow import UserDepartment
from app.services.audit_service import AuditService

router = APIRouter(prefix="/departments", tags=["departments"])

_admin = require_role("admin")


class ManagerSet(BaseModel):
    """null clears the manager."""
    user_id: Optional[int] = None


class MembersSet(BaseModel):
    user_ids: list[int]


def _person(u: User) -> dict:
    return {"id": u.id, "name": u.full_name or u.username, "username": u.username,
            "email": u.email, "is_active": u.is_active}


async def _department(db: AsyncSession, department_id: int) -> Department:
    dept = await db.get(Department, department_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")
    return dept


async def _out(db: AsyncSession, depts: list[Department]) -> list[dict]:
    ids = [d.id for d in depts]
    members: dict[int, list[dict]] = {i: [] for i in ids}
    for dept_id, u in (await db.execute(
            select(UserDepartment.department_id, User)
            .join(User, User.id == UserDepartment.user_id)
            .where(UserDepartment.department_id.in_(ids))
            .order_by(User.full_name, User.username))).all():
        members[dept_id].append(_person(u))
    mgr_ids = {d.manager_id for d in depts if d.manager_id is not None}
    managers = {u.id: u for u in (await db.execute(
        select(User).where(User.id.in_(mgr_ids)))).scalars().all()} if mgr_ids else {}
    out = []
    for d in depts:
        m = managers.get(d.manager_id)
        out.append({"id": d.id, "name": d.name, "is_active": d.is_active,
                    "sort_order": d.sort_order, "manager_id": d.manager_id,
                    "manager_name": (m.full_name or m.username) if m else None,
                    "manager_active": m.is_active if m else None,
                    "members": members[d.id]})
    return out


@router.get("/admin")
async def list_departments_admin(current_user: User = Depends(_admin),
                                 db: AsyncSession = Depends(get_db)):
    """Every department (retired ones too, flagged is_active false), with
    its manager and members, for the Departments admin page."""
    depts = (await db.execute(select(Department).order_by(
        Department.sort_order, Department.name))).scalars().all()
    return await _out(db, list(depts))


@router.put("/{department_id}/manager")
async def set_department_manager(department_id: int, body: ManagerSet,
                                 current_user: User = Depends(_admin),
                                 db: AsyncSession = Depends(get_db)):
    """Name or clear the department's manager. Must be an active user;
    membership is not required."""
    dept = await _department(db, department_id)
    if body.user_id is not None:
        user = await db.get(User, body.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=400, detail="The manager must be an active user")
    old = dept.manager_id
    dept.manager_id = body.user_id
    await AuditService.record(
        db, entity_type="department", entity_id=dept.id, action="manager_set",
        user_id=current_user.id, old_values={"manager_id": old},
        new_values={"manager_id": body.user_id})
    await db.commit()
    return (await _out(db, [dept]))[0]


@router.put("/{department_id}/members")
async def set_department_members(department_id: int, body: MembersSet,
                                 current_user: User = Depends(_admin),
                                 db: AsyncSession = Depends(get_db)):
    """Replace the department's members. A person added must be an active
    user; one already a member stays even when inactive (removing is the
    admin's call)."""
    dept = await _department(db, department_id)
    rows = (await db.execute(select(UserDepartment).where(
        UserDepartment.department_id == dept.id))).scalars().all()
    old = sorted({r.user_id for r in rows})
    new = sorted(set(body.user_ids))
    added = set(new) - set(old)
    if added:
        ok = set((await db.execute(select(User.id).where(
            User.id.in_(added), User.is_active.is_(True)))).scalars().all())
        if added - ok:
            raise HTTPException(status_code=400,
                                detail=f"Unknown or inactive users: {sorted(added - ok)}")
    for r in rows:
        if r.user_id not in new:
            await db.delete(r)
    for uid in sorted(added):
        db.add(UserDepartment(user_id=uid, department_id=dept.id))
    await AuditService.record(
        db, entity_type="department", entity_id=dept.id, action="members_set",
        user_id=current_user.id, old_values={"user_ids": old},
        new_values={"user_ids": new})
    await db.commit()
    return (await _out(db, [dept]))[0]


@router.post("/{department_id}/activate")
async def activate_department(department_id: int,
                              current_user: User = Depends(_admin),
                              db: AsyncSession = Depends(get_db)):
    """Bring a retired department back into use (pickers, routing)."""
    dept = await _department(db, department_id)
    if not dept.is_active:
        dept.is_active = True
        await AuditService.record(
            db, entity_type="department", entity_id=dept.id, action="activated",
            user_id=current_user.id, old_values={"is_active": False},
            new_values={"is_active": True})
        await db.commit()
    return (await _out(db, [dept]))[0]
