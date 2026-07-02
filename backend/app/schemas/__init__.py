"""Pydantic schemas for API requests and responses."""
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, RefreshTokenRequest, ChangePasswordRequest
from app.schemas.user import UserResponse, UserCreateRequest, UserUpdateRequest

__all__ = [
    "RegisterRequest",
    "LoginRequest",
    "TokenResponse",
    "RefreshTokenRequest",
    "ChangePasswordRequest",
    "UserResponse",
    "UserCreateRequest",
    "UserUpdateRequest",
]

# Project schemas
from app.schemas.project import (
    ProjectCreateRequest, ProjectUpdateRequest, ProjectResponse,
)

# BOM schemas
from app.schemas.bom import (
    CatalogPartCreateRequest, CatalogPartUpdateRequest, CatalogPartResponse,
    DuplicateCheckResponse,
    BOMItemCreateRequest, BOMItemUpdateRequest, BOMItemResponse, BOMResponse,
    ProjectBOMResponse, ProjectBOMLineResponse, ProjectBOMSourceResponse,
    PartTypeEnum,
)
