"""User schemas."""
from datetime import datetime
from pydantic import BaseModel, EmailStr


class UserResponse(BaseModel):
    """User response model."""
    id: int
    email: EmailStr
    username: str
    full_name: str
    role: str
    is_active: bool
    mfa_enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserCreateRequest(BaseModel):
    """Create user request."""
    email: EmailStr
    username: str
    full_name: str
    password: str
    role: str = "viewer"


class UserUpdateRequest(BaseModel):
    """Update user request."""
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
