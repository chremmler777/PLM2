"""Contact directory for attendee/participant autofill.

Primary source is the AdminPanel hub's /api/v1/contacts, which serves the
signed-in user's Entra "relevant people" (delegated People.Read on the user's
own token — no directory-wide admin permission). We proxy it server-to-server,
forwarding the caller's SSO cookie, so PLM2 needs no credential of its own.

When the hub base is not configured (local dev) or the hub call fails, we fall
back to PLM2's own user table so the feature still works — degraded but usable.
"""
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.dependencies.auth import get_current_user
from app.models import get_db
from app.models.entities import User

router = APIRouter(prefix="/contacts", tags=["contacts"])


async def _departments_by_user(db: AsyncSession, user_ids) -> dict:
    """user_id -> "Dept A, Dept B" (active departments), so two people of
    the same name can be told apart in the picker."""
    from app.models.workflow import Department, UserDepartment
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    out: dict = {}
    for uid, name in (await db.execute(
            select(UserDepartment.user_id, Department.name)
            .join(Department, Department.id == UserDepartment.department_id)
            .where(UserDepartment.user_id.in_(ids),
                   Department.is_active.is_(True))
            .order_by(Department.name))).all():
        out.setdefault(uid, []).append(name)
    return {k: ", ".join(dict.fromkeys(v)) for k, v in out.items()}


async def _local_contacts(db: AsyncSession, org_id: int) -> List[dict]:
    rows = (await db.execute(
        select(User.id, User.full_name, User.username, User.email)
        .where(User.is_active.is_(True), User.organization_id == org_id)
        .order_by(User.full_name, User.username)
    )).all()
    depts = await _departments_by_user(db, [r[0] for r in rows])
    return _people([
        {"name": full_name or username, "email": email, "source": "local",
         "user_id": uid, "username": username, "department": depts.get(uid)}
        for uid, full_name, username, email in rows
    ])


async def _resolve_hub(db: AsyncSession, entries: List[dict],
                       org_id: Optional[int] = None) -> List[dict]:
    """Hub entries carry no PLM2 identity: match each to the User with the
    same email (case-insensitive) in the caller's organization, so an
    attendee picked from the hub is stored as that user. Unmatched entries
    keep user_id None."""
    emails = {(e.get("email") or "").strip().lower()
              for e in entries if isinstance(e, dict) and e.get("email")}
    by_email: dict = {}
    if emails:
        q = select(User.id, User.username, User.email).where(
            func.lower(User.email).in_(emails), User.is_active.is_(True))
        if org_id is not None:
            q = q.where(User.organization_id == org_id)
        for uid, username, email in (await db.execute(q)).all():
            by_email.setdefault((email or "").strip().lower(), (uid, username))
    depts = await _departments_by_user(db, [v[0] for v in by_email.values()])
    out = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        hit = by_email.get((e.get("email") or "").strip().lower())
        out.append({**e, "user_id": hit[0] if hit else None,
                    "username": hit[1] if hit else None,
                    "department": (depts.get(hit[0]) if hit else None)
                    or e.get("department")})
    return out


def _people(entries: List[dict]) -> List[dict]:
    """Only people (spec §16): no service tokens, smoke-test or admin
    accounts, no entry without a real mailbox. An entry that IS a PLM2 user
    (user_id set) is a person whatever its mail domain.

    One row per person, not per name: the same PLM2 user (or, unresolved,
    the same mailbox) comes once; two different people who share a name
    both stay, told apart by their email and department. The username only
    serves the person filter and is not sent out."""
    from app.services.early_stage_service import EarlyStageService
    seen, out = set(), []
    for e in entries:
        if not isinstance(e, dict) or not EarlyStageService.is_person_contact(
                e, is_user=e.get("user_id") is not None):
            continue
        email = (e.get("email") or "").strip().lower()
        if e.get("user_id") is not None:
            key = ("u", e["user_id"])
        elif email:
            key = ("e", email)
        else:
            key = ("n", (e.get("name") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({k: v for k, v in e.items() if k != "username"})
    return out


@router.get("", response_model=List[dict])
async def list_contacts(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """[{name, email, source, user_id, department}] for attendee autofill,
    the caller's organization only. Hub directory when configured (entries
    resolved to PLM2 users by email), else local users."""
    settings = get_settings()
    base = settings.hub_api_base.rstrip("/")
    if not base:
        return await _local_contacts(db, current_user.organization_id)

    cookie = request.cookies.get(settings.jwt_cookie_name)
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{base}/api/v1/contacts",
                cookies={settings.jwt_cookie_name: cookie} if cookie else None,
            )
        if resp.status_code == 200:
            data = resp.json()
            return (_people(await _resolve_hub(db, data, current_user.organization_id))
                    if isinstance(data, list) else data)
    except httpx.HTTPError:
        pass
    # Hub unreachable or errored — degrade to local rather than 500 the picker.
    return await _local_contacts(db, current_user.organization_id)
