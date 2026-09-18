"""Customer package receive: the assembly file plus one file per part, in
one step. Preview matches and decides; confirm stores."""
import json
from dataclasses import asdict
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db
from app.models import User
from app.schemas.part import PackagePreviewResponse, PackageRowIn, PackageRowOut
from app.services.customer_package_service import CustomerPackageService, PackageError, PackageRow
from app.services.revision_naming import STATEMENTS, RevisionRuleViolation

router = APIRouter(prefix="/parts", tags=["customer-package"])


def _statement(value: str) -> str:
    if value not in STATEMENTS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"statement must be one of {STATEMENTS}")
    return value


def _reject_duplicate_filenames(files: List[UploadFile]) -> None:
    seen: set[str] = set()
    for f in files:
        name = f.filename or ""
        if name in seen:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"Duplicate filename in package: {name}")
        seen.add(name)


@router.post("/{assembly_id}/revisions/customer-package/preview", response_model=PackagePreviewResponse)
async def preview_customer_package(
    assembly_id: int,
    statement: str = Form(...),
    received_at: date = Form(...),
    package_index: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _reject_duplicate_filenames(files)
    try:
        rows = await CustomerPackageService.preview(
            db, assembly_id, _statement(statement), received_at, (package_index or "").strip() or None,
            [f.filename or "" for f in files])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"rows": [PackageRowOut(**asdict(r)) for r in rows]}


@router.post("/{assembly_id}/revisions/customer-package", status_code=status.HTTP_201_CREATED)
async def confirm_customer_package(
    assembly_id: int,
    statement: str = Form(...),
    received_at: date = Form(...),
    rows: str = Form(...),
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _reject_duplicate_filenames(files)
    try:
        parsed = TypeAdapter(List[PackageRowIn]).validate_python(json.loads(rows))
    except (ValueError, ValidationError) as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"rows: {e}")
    blobs = {}
    for f in files:
        blobs[f.filename or ""] = (await f.read(), f.content_type)
    package_rows = [PackageRow(filename=r.filename, part_id=r.part_id, customer_index=r.customer_index,
                               action=r.action, major=r.major) for r in parsed]
    try:
        out = await CustomerPackageService.confirm(
            db, assembly_id, _statement(statement), received_at, package_rows, blobs, current_user.id)
        await db.commit()
        return out
    except PackageError as e:
        await db.rollback()
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={
            "detail": "Some rows cannot be stored", "rows": [asdict(r) for r in e.rows]})
    except RevisionRuleViolation as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
