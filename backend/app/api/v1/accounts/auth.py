"""Authentication endpoints (shared-cookie SSO). Local login/refresh/change-password retired."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from app.core.config import get_settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_user, plm2_roles
from app.models import get_db
from app.models.workflow import Department

router = APIRouter(prefix="/auth", tags=["auth"])

_GONE = "Local login is disabled; authenticate via the AdminPanel hub."


@router.post("/login", status_code=status.HTTP_410_GONE)
async def login_gone():
    raise HTTPException(status.HTTP_410_GONE, _GONE)


@router.post("/refresh", status_code=status.HTTP_410_GONE)
async def refresh_gone():
    raise HTTPException(status.HTTP_410_GONE, _GONE)


@router.post("/change-password", status_code=status.HTTP_410_GONE)
async def change_password_gone():
    raise HTTPException(status.HTTP_410_GONE, _GONE)


@router.get("/me")
async def me(request: Request, user=Depends(get_current_user)) -> dict:
    payload = getattr(request.state, "hub_payload", {})
    dept = getattr(request.state, "acts_as_department", None)
    return {
        "sub": payload.get("sub"),
        "user_id": user.id,
        "username": user.username,
        "roles": payload.get("roles", []),
        "plm2_roles": plm2_roles(payload),
        "system": get_settings().role_system,
        "exp": payload.get("exp"),
        # Acts-as: enough to render the banner and decide whether the
        # switcher shows at all, without a second round-trip.
        "acting_as": ({"id": dept.id, "name": dept.name} if dept else None),
        "is_real_admin": user.is_real_admin,
        "effective_role": user.effective_role,
    }


@router.get("/acts-as/options")
async def acts_as_options(user=Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)) -> dict:
    """The active departments an admin may act as. 403 for everyone else —
    the dropdown must not render for anyone who cannot use it."""
    if not user.is_real_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only an admin may act as another department")
    rows = (await db.execute(
        select(Department).where(Department.is_active.is_(True))
        .order_by(Department.sort_order, Department.name))).scalars().all()
    return {"departments": [{"id": d.id, "name": d.name} for d in rows]}


@router.post("/logout")
async def logout():
    """Logout - client discards the shared cookie (no server-side session state)."""
    return {"status": "success", "message": "Logged out"}
