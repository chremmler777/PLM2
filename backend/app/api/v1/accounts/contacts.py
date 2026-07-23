"""Contact directory for attendee/participant autofill.

Primary source is the AdminPanel hub's /api/v1/contacts, which serves the
signed-in user's Entra "relevant people" (delegated People.Read on the user's
own token — no directory-wide admin permission). We proxy it server-to-server,
forwarding the caller's SSO cookie, so PLM2 needs no credential of its own.

When the hub base is not configured (local dev) or the hub call fails, we fall
back to PLM2's own user table so the feature still works — degraded but usable.
"""
from typing import List

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.dependencies.auth import get_current_user
from app.models import get_db
from app.models.entities import User

router = APIRouter(prefix="/contacts", tags=["contacts"])


async def _local_contacts(db: AsyncSession) -> List[dict]:
    rows = (await db.execute(
        select(User.full_name, User.username, User.email)
        .where(User.is_active.is_(True))
        .order_by(User.full_name, User.username)
    )).all()
    return [
        {"name": full_name or username, "email": email, "source": "local"}
        for full_name, username, email in rows
    ]


@router.get("", response_model=List[dict])
async def list_contacts(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """[{name, email, source}] for attendee autofill. Hub directory when
    configured, else local users."""
    settings = get_settings()
    base = settings.hub_api_base.rstrip("/")
    if not base:
        return await _local_contacts(db)

    cookie = request.cookies.get(settings.jwt_cookie_name)
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{base}/api/v1/contacts",
                cookies={settings.jwt_cookie_name: cookie} if cookie else None,
            )
        if resp.status_code == 200:
            return resp.json()
    except httpx.HTTPError:
        pass
    # Hub unreachable or errored — degrade to local rather than 500 the picker.
    return await _local_contacts(db)
