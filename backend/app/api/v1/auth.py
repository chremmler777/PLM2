"""Authentication endpoints - Phase 1 testing version."""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from app.core.config import get_settings
from app.auth.security import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: int

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """Login endpoint - accepts test credentials for Phase 1."""
    # Phase 1: Hardcoded test credentials
    # Phase 6: Will use actual user database
    if request.email == "test@example.com" and request.password == "password":
        # Create JWT token using the security module
        token = create_access_token(data={"sub": "1", "email": request.email})

        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": 1
        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials"
    )

@router.post("/logout")
async def logout():
    """Logout endpoint - Phase 1 placeholder."""
    return {"message": "Logged out successfully"}
