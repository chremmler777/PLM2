"""Authentication endpoints (shared-cookie SSO). Local login/refresh/change-password retired."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from app.core.config import get_settings
from app.dependencies.auth import get_current_user, plm2_roles

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
    return {
        "sub": payload.get("sub"),
        "username": user.username,
        "roles": payload.get("roles", []),
        "plm2_roles": plm2_roles(payload),
        "system": get_settings().role_system,
        "exp": payload.get("exp"),
    }


@router.post("/logout")
async def logout():
    """Logout - client discards the shared cookie (no server-side session state)."""
    return {"status": "success", "message": "Logged out"}
