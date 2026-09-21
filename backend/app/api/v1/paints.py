"""Paint catalog endpoints (org-scoped master data)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.schemas.paint import PaintIn, PaintOut, PaintUpdate, UsedInOut
from app.services.paint_service import DuplicatePaint, PaintService, UnknownSupplier

router = APIRouter(prefix="/paints", tags=["paints"])


@router.get("", response_model=list[PaintOut])
async def list_paints(
    active_only: bool = Query(True),
    q: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List paints of the current organization."""
    return await PaintService.list_paints(
        db, org_id=current_user.organization_id, active_only=active_only, q=q)


@router.post("", response_model=PaintOut, status_code=status.HTTP_201_CREATED)
async def create_paint(
    body: PaintIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a paint. 409 if a paint with that name already exists in the org."""
    try:
        paint = await PaintService.create_paint(
            db, org_id=current_user.organization_id, created_by=current_user.id,
            **body.model_dump())
        # Inside the try: a concurrent insert of the same name only trips the
        # unique constraint here, and that must roll back into a 409, not a 500.
        await db.commit()
    except DuplicatePaint as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except UnknownSupplier as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="A paint named '%s' already exists" % body.name)
    await db.refresh(paint)
    return paint


@router.get("/{paint_id}", response_model=PaintOut)
async def get_paint(
    paint_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get one paint."""
    try:
        return await PaintService.get_paint(db, org_id=current_user.organization_id, paint_id=paint_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paint not found")


@router.put("/{paint_id}", response_model=PaintOut)
async def update_paint(
    paint_id: int,
    body: PaintUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a paint (all fields optional, incl. is_active)."""
    fields = body.model_dump(exclude_unset=True)
    try:
        paint = await PaintService.update_paint(
            db, org_id=current_user.organization_id, paint_id=paint_id, **fields)
        # Inside the try, so a constraint violation at flush/commit time rolls
        # back into a 409 instead of escaping the handler as a 500.
        await db.commit()
    except DuplicatePaint as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except UnknownSupplier as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="That paint could not be saved")
    await db.refresh(paint)
    return paint


@router.get("/{paint_id}/used-in", response_model=list[UsedInOut])
async def paint_used_in(
    paint_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Articles across projects using this paint."""
    try:
        await PaintService.get_paint(db, org_id=current_user.organization_id, paint_id=paint_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paint not found")
    return await PaintService.used_in(db, org_id=current_user.organization_id, paint_id=paint_id)
