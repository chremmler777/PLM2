"""Authentication schemas."""
from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    """User registration request."""
    email: EmailStr
    username: str
    full_name: str
    password: str
    organization_name: str | None = None


class LoginRequest(BaseModel):
    """User login request."""
    email: str
    password: str


class TokenResponse(BaseModel):
    """Token response after login."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: int
    username: str


class RefreshTokenRequest(BaseModel):
    """Refresh token request."""
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    """Change password request."""
    current_password: str
    new_password: str
