"""Catalog parts endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.models import CatalogPart, User, get_db
from app.dependencies import get_current_user
from app.schemas.bom import (
    CatalogPartCreateRequest, CatalogPartUpdateRequest,
    CatalogPartResponse, DuplicateCheckResponse,
)

router = APIRouter(prefix="/catalog-parts", tags=["catalog-parts"])


@router.get("/check-duplicate", response_model=DuplicateCheckResponse)
async def check_duplicate(
    part_number: str | None = Query(None),
    name: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check for duplicate part_number (exact) or similar name (fuzzy)."""
    org_id = current_user.organization_id
    exact_match = False
    similar_parts: list[CatalogPart] = []

    if part_number:
        result = await db.execute(
            select(CatalogPart).where(
                and_(
                    CatalogPart.organization_id == org_id,
                    func.lower(CatalogPart.part_number) == func.lower(part_number),
                    CatalogPart.is_active == True,
                )
            )
        )
        if result.scalar_one_or_none():
            exact_match = True

    if name:
        result = await db.execute(
            select(CatalogPart).where(
                and_(
                    CatalogPart.organization_id == org_id,
                    CatalogPart.name.ilike(f"%{name}%"),
                    CatalogPart.is_active == True,
                )
            ).limit(5)
        )
        similar_parts = list(result.scalars().all())

    return DuplicateCheckResponse(
        exact_match=exact_match,
        similar_parts=[CatalogPartResponse.from_orm(p) for p in similar_parts],
    )


@router.get("", response_model=list[CatalogPartResponse])
async def list_catalog_parts(
    search: str | None = Query(None),
    part_type: str | None = Query(None),
    is_active: bool | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List catalog parts for the current organization."""
    query = select(CatalogPart).where(
        CatalogPart.organization_id == current_user.organization_id
    )

    if search:
        query = query.where(
            CatalogPart.name.ilike(f"%{search}%") |
            CatalogPart.part_number.ilike(f"%{search}%")
        )

    if part_type:
        query = query.where(CatalogPart.part_type == part_type)

    if is_active is not None:
        query = query.where(CatalogPart.is_active == is_active)

    result = await db.execute(query.order_by(CatalogPart.part_number))
    parts = result.scalars().all()
    return [CatalogPartResponse.from_orm(p) for p in parts]


@router.post("", response_model=CatalogPartResponse, status_code=status.HTTP_201_CREATED)
async def create_catalog_part(
    request: CatalogPartCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new catalog part. 409 on duplicate part_number within org."""
    result = await db.execute(
        select(CatalogPart).where(
            and_(
                CatalogPart.organization_id == current_user.organization_id,
                func.lower(CatalogPart.part_number) == func.lower(request.part_number),
            )
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Part number '{request.part_number}' already exists in this organization",
        )

    part = CatalogPart(
        organization_id=current_user.organization_id,
        part_number=request.part_number,
        name=request.name,
        description=request.description,
        part_type=request.part_type.value,
        supplier=request.supplier,
        unit=request.unit,
        created_by=current_user.id,
    )
    db.add(part)
    await db.commit()
    await db.refresh(part)
    return CatalogPartResponse.from_orm(part)


@router.get("/{part_id}", response_model=CatalogPartResponse)
async def get_catalog_part(
    part_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single catalog part."""
    result = await db.execute(
        select(CatalogPart).where(
            and_(
                CatalogPart.id == part_id,
                CatalogPart.organization_id == current_user.organization_id,
            )
        )
    )
    part = result.scalar_one_or_none()
    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
    return CatalogPartResponse.from_orm(part)


@router.put("/{part_id}", response_model=CatalogPartResponse)
async def update_catalog_part(
    part_id: int,
    request: CatalogPartUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a catalog part."""
    result = await db.execute(
        select(CatalogPart).where(
            and_(
                CatalogPart.id == part_id,
                CatalogPart.organization_id == current_user.organization_id,
            )
        )
    )
    part = result.scalar_one_or_none()
    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")

    if request.name is not None:
        part.name = request.name
    if request.description is not None:
        part.description = request.description
    if request.part_type is not None:
        part.part_type = request.part_type.value
    if request.supplier is not None:
        part.supplier = request.supplier
    if request.unit is not None:
        part.unit = request.unit

    await db.commit()
    await db.refresh(part)
    return CatalogPartResponse.from_orm(part)


@router.delete("/{part_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_catalog_part(
    part_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a catalog part (soft delete)."""
    result = await db.execute(
        select(CatalogPart).where(
            and_(
                CatalogPart.id == part_id,
                CatalogPart.organization_id == current_user.organization_id,
            )
        )
    )
    part = result.scalar_one_or_none()
    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")

    part.is_active = False
    await db.commit()
