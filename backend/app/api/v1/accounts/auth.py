"""Authentication endpoints (shared-cookie SSO). Local login/refresh/change-password retired."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from app.core.config import get_settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_user, plm2_roles
from app.models import get_db
from app.models.entities import User
from app.models.workflow import Department
from app.services.cost_sheet_service import can_read as cost_sheet_can_read
from app.services.tool_rights import can_edit_tools
from app.version import SOFTWARE_VERSION

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


async def _price_view(db: AsyncSession, user) -> str:
    from app.models.change import ChangeRequest
    from app.services.change_people import is_acting
    from app.services.price_redaction import PriceViewer
    if await PriceViewer(db, user)._base():
        return "all"
    if is_acting(user):
        return "none"   # acting as a department drops the personal lead right (C32)
    leads = (await db.execute(select(ChangeRequest.id).where(
        ChangeRequest.lead_id == user.id).limit(1))).first()
    return "led" if leads else "none"


@router.get("/me")
async def me(request: Request, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
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
        # Act as a person: this response is that person's (user_id, role,
        # rights); the switcher and the banner read these two.
        "acting_as_user": ({"id": user.id, "name": user.full_name or user.username}
                           if getattr(request.state, "acts_as_user", None) is not None else None),
        "real_user": ({"id": request.state.acts_as_real_user.id,
                       "name": request.state.acts_as_real_user.full_name
                       or request.state.acts_as_real_user.username}
                      if getattr(request.state, "acts_as_user", None) is not None else None),
        "is_real_admin": user.is_real_admin,
        # admin | engineer (member of an active department: may write) | viewer
        "role": user.role,
        "effective_role": user.effective_role,
        # Tool data (tool fields, produces links, shrinkage, DFM): Tool Engineer or admin
        "can_edit_tools": await can_edit_tools(db, user),
        # Which prices the viewer reads (R23): "all" (admin, PM, Sales,
        # Management), "led" (only the changes they lead), "none". The P&L
        # link and page go by it instead of showing someone zeros.
        "price_view": await _price_view(db, user),
        # D-cost: the Cost sheet page and nav item (admin, Project Manager,
        # Sales, Finance, Management; acts-as aware).
        "can_read_cost_sheet": await cost_sheet_can_read(db, user),
        # The user-facing version the training record is stamped with.
        "software_version": SOFTWARE_VERSION,
    }


@router.get("/acts-as/options")
async def acts_as_options(request: Request, user=Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)) -> dict:
    """The active departments and people an admin may act as. 403 for
    everyone else — the dropdown must not render for anyone who cannot use
    it. People: active hub accounts with an active department (the ones
    whose view differs), by name."""
    real = getattr(request.state, "acts_as_real_user", None) or user
    if not real.is_real_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only an admin may act as another department")
    rows = (await db.execute(
        select(Department).where(Department.is_active.is_(True))
        .order_by(Department.sort_order, Department.name))).scalars().all()
    from app.services.hub_departments import member_clause
    from app.models.workflow import UserDepartment
    people = (await db.execute(
        select(User).join(UserDepartment, UserDepartment.user_id == User.id)
        .join(Department, Department.id == UserDepartment.department_id)
        .where(User.is_active.is_(True), Department.is_active.is_(True),
               User.id != real.id, member_clause())
        .distinct().order_by(User.full_name, User.username))).scalars().all()
    return {"departments": [{"id": d.id, "name": d.name} for d in rows],
            "people": [{"id": u.id, "name": u.full_name or u.username} for u in people]}


@router.post("/logout")
async def logout():
    """Logout - client discards the shared cookie (no server-side session state)."""
    return {"status": "success", "message": "Logged out"}
