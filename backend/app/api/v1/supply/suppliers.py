"""Supplier master data endpoints."""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.part import Part
from app.models.supplier import Supplier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


class SupplierCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    code: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None


class SupplierUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    code: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


def _dict(s: Supplier, part_count: int | None = None) -> dict:
    d = {
        "id": s.id,
        "name": s.name,
        "code": s.code,
        "contact_name": s.contact_name,
        "contact_email": s.contact_email,
        "phone": s.phone,
        "address": s.address,
        "notes": s.notes,
        "is_active": s.is_active,
    }
    if part_count is not None:
        d["part_count"] = part_count
    return d


@router.get("", response_model=List[dict])
async def list_suppliers(
    include_inactive: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Suppliers with the number of parts sourced from each."""
    stmt = (
        select(Supplier, func.count(Part.id))
        .outerjoin(Part, Part.supplier_id == Supplier.id)
        .group_by(Supplier.id)
        .order_by(Supplier.name)
    )
    if not include_inactive:
        stmt = stmt.where(Supplier.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    return [_dict(s, count) for s, count in result.all()]


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    body: SupplierCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(Supplier).where(Supplier.name == body.name.strip()))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A supplier with this name already exists",
        )
    supplier = Supplier(
        name=body.name.strip(),
        code=body.code,
        contact_name=body.contact_name,
        contact_email=body.contact_email,
        phone=body.phone,
        address=body.address,
        notes=body.notes,
        organization_id=current_user.organization_id,
        created_by=current_user.id,
    )
    db.add(supplier)
    await db.commit()
    logger.info(f"Supplier '{supplier.name}' created by {current_user.email}")
    return _dict(supplier, 0)


@router.patch("/{supplier_id}", response_model=dict)
async def update_supplier(
    supplier_id: int,
    body: SupplierUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    supplier = result.scalar_one_or_none()
    if not supplier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")

    if body.name is not None and body.name.strip() != supplier.name:
        dup = await db.execute(select(Supplier).where(Supplier.name == body.name.strip()))
        if dup.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A supplier with this name already exists",
            )
        supplier.name = body.name.strip()

    for field in ("code", "contact_name", "contact_email", "phone", "address", "notes", "is_active"):
        value = getattr(body, field)
        if value is not None:
            setattr(supplier, field, value)

    await db.commit()
    return _dict(supplier)


@router.get("/{supplier_id}/parts", response_model=List[dict])
async def supplier_parts(
    supplier_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Parts sourced from this supplier."""
    result = await db.execute(
        select(Part).where(Part.supplier_id == supplier_id).order_by(Part.part_number)
    )
    return [
        {
            "id": p.id,
            "part_number": p.part_number,
            "name": p.name,
            "item_category": p.item_category,
            "project_id": p.project_id,
        }
        for p in result.scalars().all()
    ]
