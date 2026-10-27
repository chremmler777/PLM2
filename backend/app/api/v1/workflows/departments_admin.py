"""The Departments page's API (Christoph 2026-10-26: "We need managers for an
escalation overview").

Membership comes from AdminPanel (migration 150: a department's hub_role
on the token, synced at login, app/services/hub_departments.py), so the
page lists members read-only. Everyone logged in reads it; only a real
admin writes (the authenticated row's role, as the per-user PUT /users/{id}
/departments: acting as a department does not lock an admin out).

- GET  /departments/overview          every department: hub role, head,
                                       manager, members, warnings
- PUT  /departments/{id}/head         {"user_id": int | null}: name / clear
- PUT  /departments/{id}/manager      {"user_id": int | null}: name / clear
- POST /departments/{id}/activate     a retired department back in use
- POST /departments/{id}/deactivate   retire it (grants nothing, its members
                                       drop out at their next login)

The manager (migration 149) must be an active member of the department
(Christoph 2026-10-26; whether admins may be offered without membership is
open); one person may manage several departments. Managing grants no
write rights: it routes the overdue digest and My Tasks' "Late in my
departments" group.

The head (migration 151, Christoph 2026-10-26) is the senior member who
leads the department day to day (Russ: Manufacturing Engineer), shown as
the card's headline; it routes nothing and grants nothing. It too must be
an active member when named. No head is no warning (most departments have
none).

Warnings (read by everyone): the head inactive or no longer a member; no
manager; the manager inactive or no longer
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
    """null clears the manager (or the head)."""
    user_id: Optional[int] = None


def _person(u: User) -> dict:
    from app.services.ecr_mail import display_address
    return {"id": u.id, "name": u.full_name or u.username, "username": u.username,
            # esc P3-7: a bare hub username reads as a mail address
            "email": display_address(u.email),
            "is_active": u.is_active}


async def _department(db: AsyncSession, department_id: int) -> Department:
    dept = await db.get(Department, department_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")
    return dept


def _name(u: User) -> str:
    return u.full_name or u.username


def _warnings(d: Department, manager: Optional[User], head: Optional[User],
              members: list[dict]) -> list[dict]:
    """[{code, level, text}] for the page; level amber or red."""
    out = []
    if not d.is_active:
        return out
    member_ids = {m["id"] for m in members}
    if d.head_id is not None:
        if head is None or not head.is_active:
            name = _name(head) if head else f"user {d.head_id}"
            out.append({"code": "head_inactive", "level": "red",
                        "text": f"Head {name} is inactive or deleted"})
        elif d.head_id not in member_ids:
            out.append({"code": "head_not_member", "level": "red",
                        "text": f"Head {_name(head)} is no longer a member"})
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
    people_ids = ({d.manager_id for d in depts} | {d.head_id for d in depts}) - {None}
    people = {u.id: u for u in (await db.execute(
        select(User).where(User.id.in_(people_ids)))).scalars().all()} if people_ids else {}
    out = []
    for d in depts:
        m = people.get(d.manager_id)
        h = people.get(d.head_id)
        out.append({"id": d.id, "name": d.name, "is_active": d.is_active,
                    "sort_order": d.sort_order, "hub_role": d.hub_role,
                    "head_id": d.head_id,
                    "head_name": _name(h) if h else None,
                    "head_email": h.email if h else None,
                    "head_active": h.is_active if h else None,
                    "manager_id": d.manager_id,
                    "manager_name": _name(m) if m else None,
                    "manager_email": m.email if m else None,
                    "manager_active": m.is_active if m else None,
                    "members": members[d.id],
                    "warnings": _warnings(d, m, h, members[d.id])})
    return out


@router.get("/overview")
async def departments_overview(current_user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    """Every department (retired ones too, flagged is_active false), with
    its hub role, manager, members and warnings. Read by everyone."""
    depts = (await db.execute(select(Department).order_by(
        Department.sort_order, Department.name))).scalars().all()
    return await _out(db, list(depts))


async def _set_person(db: AsyncSession, dept: Department, field: str, label: str,
                      user_id: Optional[int], actor: User) -> dict:
    """Name or clear the head / manager (field head_id / manager_id): an
    active member of the department, or None."""
    if user_id is not None:
        ok = (await db.execute(
            select(User.id).join(UserDepartment, UserDepartment.user_id == User.id)
            .where(User.id == user_id, User.is_active.is_(True),
                   UserDepartment.department_id == dept.id, member_clause()))).first()
        if ok is None:
            raise HTTPException(
                status_code=400,
                detail=f"The {label} must be an active member of {dept.name}")
    old = getattr(dept, field)
    setattr(dept, field, user_id)
    await AuditService.record(
        db, entity_type="department", entity_id=dept.id, action=f"{label}_set",
        user_id=actor.id, old_values={field: old}, new_values={field: user_id})
    await db.commit()
    return (await _out(db, [dept]))[0]


@router.put("/{department_id}/head")
async def set_department_head(department_id: int, body: ManagerSet,
                              current_user: User = Depends(_admin),
                              db: AsyncSession = Depends(get_db)):
    """Name or clear the department's head: an active member of it."""
    return await _set_person(db, await _department(db, department_id), "head_id", "head",
                             body.user_id, current_user)


@router.put("/{department_id}/manager")
async def set_department_manager(department_id: int, body: ManagerSet,
                                 current_user: User = Depends(_admin),
                                 db: AsyncSession = Depends(get_db)):
    """Name or clear the department's manager: an active member of it."""
    return await _set_person(db, await _department(db, department_id), "manager_id",
                             "manager", body.user_id, current_user)


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
