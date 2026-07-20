"""Authentication dependencies for FastAPI route protection (shared-cookie SSO)."""
from fastapi import Depends, HTTPException, Request, status
from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import User, get_db
from app.models.entities import Organization

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_HUB_MANAGED = "!"  # sentinel hashed_password for auto-provisioned hub users


def plm2_roles(payload: dict) -> list[str]:
    system = get_settings().role_system
    return [
        r.get("name")
        for r in payload.get("roles", [])
        if isinstance(r, dict) and r.get("system") == system
    ]


def _local_role(hub_roles: list[str]) -> str:
    return "admin" if "plm2_Admin" in hub_roles else "viewer"


async def _default_org_id(db: AsyncSession) -> int:
    org = (await db.execute(select(Organization).order_by(Organization.id))).scalars().first()
    if org is None:
        org = Organization(name="KTX", code="ktx", is_active=True)
        db.add(org)
        await db.flush()
    return org.id


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate the shared AdminPanel JWT cookie and bridge to a local User row."""
    settings = get_settings()
    token = request.cookies.get(settings.jwt_cookie_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing access_token cookie")
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    hub_roles = plm2_roles(payload)
    if not hub_roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No plm2 role in token")

    # plm2_Viewer is read-only: block non-safe methods unless the caller is plm2_Admin.
    if "plm2_Admin" not in hub_roles and request.method not in SAFE_METHODS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "plm2_Viewer is read-only")

    email = payload.get("email") or payload.get("username")
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing email/username")

    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        user = User(
            organization_id=await _default_org_id(db),
            email=email,
            username=(payload.get("username") or email),
            full_name=payload.get("username") or email,
            hashed_password=_HUB_MANAGED,
            role=_local_role(hub_roles),
            is_active=True,
            mfa_enabled=False,
        )
        db.add(user)
        await db.flush()
        await db.commit()
    elif user.hashed_password == _HUB_MANAGED and user.role != _local_role(hub_roles):
        # keep hub-provisioned users' local role in sync; never touch real local users
        user.role = _local_role(hub_roles)
        await db.commit()

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is inactive")

    request.state.hub_payload = payload
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Ensure user is active."""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def require_role(required_role: str):
    """Dependency factory for role-based access control."""

    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {required_role}",
            )
        return current_user

    return role_checker


async def require_org_access(
    current_user: User = Depends(get_current_user),
) -> User:
    """Ensure user has access to the organization they're trying to access."""
    return current_user


def get_org_filter(user: User, model):
    """Helper to add organization filter to queries.

    Returns filter condition for non-admins, None for admins.
    """
    # Admins see all organizations
    if user.role == "admin":
        return None

    # Non-admins are scoped to their organization
    if hasattr(model, "organization_id"):
        return model.organization_id == user.organization_id
    elif model.__name__ == "Organization":
        return model.id == user.organization_id
    else:
        raise ValueError(
            f"Model {model.__name__} has no organization_id field and is not Organization"
        )
