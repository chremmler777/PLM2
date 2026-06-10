"""User management endpoints - admin-only CRUD for accounts and roles."""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_password_hash
from app.dependencies import get_current_user, require_role
from app.models import User, get_db
from app.models.workflow import Department, UserDepartment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])

VALID_ROLES = {"admin", "engineer", "viewer"}


class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    full_name: Optional[str] = None
    password: str = Field(..., min_length=8)
    role: str = "viewer"


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8)


def _user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "username": u.username,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "organization_id": u.organization_id,
    }


@router.get("", response_model=List[dict])
async def list_users(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all users (admin only)."""
    result = await db.execute(select(User).order_by(User.id))
    return [_user_dict(u) for u in result.scalars().all()]


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Create a user account (admin only). New users join the admin's organization."""
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Valid: {', '.join(sorted(VALID_ROLES))}",
        )

    existing = await db.execute(
        select(User).where((User.email == body.email) | (User.username == body.username))
    )
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email or username already exists",
        )

    user = User(
        organization_id=current_user.organization_id,
        email=body.email,
        username=body.username,
        full_name=body.full_name,
        hashed_password=get_password_hash(body.password),
        role=body.role,
        is_active=True,
        mfa_enabled=False,
    )
    db.add(user)
    await db.commit()
    logger.info(f"Admin {current_user.email} created user {user.email} ({user.role})")
    return _user_dict(user)


class DepartmentAssignment(BaseModel):
    department_ids: List[int]


@router.get("/{user_id}/departments", response_model=List[dict])
async def get_user_departments(
    user_id: int,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Departments a user belongs to (admin only)."""
    result = await db.execute(
        select(Department)
        .join(UserDepartment, UserDepartment.department_id == Department.id)
        .where(UserDepartment.user_id == user_id)
        .order_by(Department.sort_order)
    )
    return [{"id": d.id, "name": d.name} for d in result.scalars().all()]


@router.put("/{user_id}/departments", response_model=List[dict])
async def set_user_departments(
    user_id: int,
    body: DepartmentAssignment,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Replace a user's department memberships (admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if body.department_ids:
        dept_result = await db.execute(
            select(Department.id).where(Department.id.in_(body.department_ids))
        )
        found = {d for (d,) in dept_result.all()}
        missing = set(body.department_ids) - found
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown department ids: {sorted(missing)}",
            )

    existing = await db.execute(select(UserDepartment).where(UserDepartment.user_id == user_id))
    for membership in existing.scalars().all():
        await db.delete(membership)
    for dept_id in set(body.department_ids):
        db.add(UserDepartment(user_id=user_id, department_id=dept_id))
    await db.commit()

    logger.info(f"Admin {current_user.email} set departments {body.department_ids} for user {user_id}")
    result = await db.execute(
        select(Department)
        .join(UserDepartment, UserDepartment.department_id == Department.id)
        .where(UserDepartment.user_id == user_id)
        .order_by(Department.sort_order)
    )
    return [{"id": d.id, "name": d.name} for d in result.scalars().all()]


@router.patch("/{user_id}", response_model=dict)
async def update_user(
    user_id: int,
    body: UserUpdate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update a user's role, name, active state, or reset their password (admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if body.role is not None:
        if body.role not in VALID_ROLES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role. Valid: {', '.join(sorted(VALID_ROLES))}",
            )
        if user.id == current_user.id and body.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot remove your own admin role",
            )
        user.role = body.role

    if body.is_active is not None:
        if user.id == current_user.id and not body.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot deactivate your own account",
            )
        user.is_active = body.is_active

    if body.full_name is not None:
        user.full_name = body.full_name
    if body.password is not None:
        user.hashed_password = get_password_hash(body.password)

    await db.commit()
    logger.info(f"Admin {current_user.email} updated user {user.email}")
    return _user_dict(user)
