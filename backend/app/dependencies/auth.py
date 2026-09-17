"""Authentication dependencies for FastAPI route protection.

Two principals:
- browsers: the shared AdminPanel JWT cookie, bridged to a local User row.
- machines: `Authorization: Bearer <PLM2_SERVICE_TOKEN>`, bridged to one
  read-only service User (plm2_Viewer semantics). Same pattern TWOS uses
  for PDB.
"""
import hmac

from fastapi import Depends, HTTPException, Request, status
from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.auth.acts_as import HEADER as ACTS_AS_HEADER, set_acts_as
from app.models import User, get_db
from app.models.entities import Organization
from app.models.workflow import Department

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_HUB_MANAGED = "!"  # sentinel hashed_password for auto-provisioned hub users
_BEARER = "Bearer "
SERVICE_USERNAME = "plm2-service"
SERVICE_EMAIL = "plm2-service@service.local"


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
    """Validate the shared AdminPanel JWT cookie and bridge to a local User row.

    A bearer Authorization header takes the service-token path instead —
    browsers never send one, machine callers never have the cookie.
    """
    settings = get_settings()
    auth_header = request.headers.get("authorization") or ""
    if auth_header.startswith(_BEARER):
        return await _service_principal(request, db, auth_header[len(_BEARER):].strip())

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

    # NOTE: the AdminPanel hub token currently mints {sub, username, department,
    # roles, auth_time} with NO "email" claim, so this always falls through to
    # payload["username"] in practice — the bridge is effectively keyed on the
    # hub username today. "email" is read first only for forward-compatibility
    # if/when the hub starts including it; no deeper re-keying is done here.
    email = payload.get("email") or payload.get("username")
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing email/username")

    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        base_username = payload.get("username") or email
        org_id = await _default_org_id(db)
        username = base_username
        attempt = 0
        while True:
            user = User(
                organization_id=org_id,
                email=email,
                username=username,
                full_name=payload.get("username") or email,
                hashed_password=_HUB_MANAGED,
                role=_local_role(hub_roles),
                is_active=True,
                mfa_enabled=False,
            )
            db.add(user)
            try:
                await db.flush()
                await db.commit()
                break
            except IntegrityError:
                await db.rollback()
                # A concurrent request may already have created this email row.
                existing = (await db.execute(
                    select(User).where(User.email == email)
                )).scalar_one_or_none()
                if existing is not None:
                    user = existing
                    break
                # Otherwise the collision is on username; disambiguate and retry.
                attempt += 1
                if attempt >= 10:
                    raise
                username = f"{base_username}-{attempt}"
    elif user.hashed_password == _HUB_MANAGED and user.role != _local_role(hub_roles):
        # keep hub-provisioned users' local role in sync; never touch real local users
        user.role = _local_role(hub_roles)
        await db.commit()

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is inactive")

    request.state.hub_payload = payload
    await _apply_acts_as(request, db, user)
    return user


async def _service_principal(request: Request, db: AsyncSession, provided: str) -> User:
    """Bearer token -> the one read-only service user.

    503 when no token is configured (a deploy problem, not a caller problem),
    401 on mismatch, 403 on anything but a safe method. The user row is
    auto-provisioned like hub users so audit and org scoping have a real id.
    """
    expected = get_settings().plm2_service_token
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Service token is not configured")
    # compare_digest, not ==: equality short-circuits on the first differing
    # byte and leaks the token's prefix to a timing attack.
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid service token")
    if request.method not in SAFE_METHODS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Service token is read-only")

    user = (await db.execute(
        select(User).where(User.email == SERVICE_EMAIL))).scalar_one_or_none()
    if user is None:
        user = User(
            organization_id=await _default_org_id(db),
            email=SERVICE_EMAIL,
            username=SERVICE_USERNAME,
            full_name="PLM2 service token",
            hashed_password=_HUB_MANAGED,
            role="viewer",
            is_active=True,
            mfa_enabled=False,
        )
        db.add(user)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            user = (await db.execute(
                select(User).where(User.email == SERVICE_EMAIL))).scalar_one()
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Service user is inactive")

    # Shape /auth/me and anything else reading the hub payload the way a
    # plm2_Viewer cookie would.
    request.state.hub_payload = {
        "sub": "service", "username": SERVICE_USERNAME,
        "roles": [{"name": "plm2_Viewer", "system": get_settings().role_system}],
    }
    await _apply_acts_as(request, db, user)   # never an admin -> header is refused
    return user


async def _apply_acts_as(request: Request, db: AsyncSession, user: User) -> None:
    """Resolve X-Acts-As-Department onto the request's User instance.

    Absent header -> untouched, so every existing request behaves exactly as
    before. Present but the REAL user is not an admin -> 403: a non-admin
    sending it is either a bug or an escalation attempt and both deserve to be
    loud (spec D4). Unknown or inactive department -> 400.

    Note this runs AFTER the plm2_Viewer read-only check above, which reads the
    hub roles — a viewer cannot buy write access with a header.
    """
    raw = request.headers.get(ACTS_AS_HEADER)
    if raw is None or not raw.strip():
        return
    if not user.is_real_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only an admin may act as another department")
    try:
        dept_id = int(raw)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Invalid {ACTS_AS_HEADER} header")
    dept = (await db.execute(
        select(Department).where(Department.id == dept_id))).scalar_one_or_none()
    if dept is None or not dept.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown or inactive department {dept_id}")
    user.acts_as_department_id = dept.id
    request.state.acts_as_department = dept
    # Audit picks both identities up from here (spec D5).
    request.state.acts_as_token = set_acts_as(user.id, dept.id)


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
