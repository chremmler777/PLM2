"""Files on SEP work items: upload, list, download, soft delete.

Every work item is a file slot, so the forms that exist today as xlsx/pdf/docx
can be collected against the item they belong to before those forms get
rebuilt in the UI. Storage and querying live in SepFileService; this module
only does auth, org scoping, HTTP mapping and the audit rows.

Org scoping: a SEP item belongs to the caller's org through
SepWorkItem.project_id -> Project.plant_id -> Plant.organization_id, the same
hop part_paint.py makes. An item outside the org is a 404, not a 403.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.timing.sep import _audit, _user_names as _uploader_names
from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.entities import Plant, Project
from app.models.sep import SepWorkItem
from app.schemas.sep import SepItemFileOut, SepProjectFileGateOut
from app.services.sep_file_service import (
    EmptyFilename, FileTooLarge, SepFileService, TooManyFiles,
)

router = APIRouter(prefix="/sep", tags=["sep"])

# Starlette renamed the constant; keep working on both.
HTTP_413 = getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413)


async def _item_in_org(db: AsyncSession, item_id: int, org_id: int) -> SepWorkItem:
    """The work item, if its project belongs to the caller's org; else 404."""
    row = (await db.execute(
        select(SepWorkItem)
        .join(Project, SepWorkItem.project_id == Project.id)
        .join(Plant, Project.plant_id == Plant.id)
        .where(SepWorkItem.id == item_id, Plant.organization_id == org_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
    return row


async def _project_in_org(db: AsyncSession, project_id: int, org_id: int) -> int:
    row = (await db.execute(
        select(Project.id)
        .join(Plant, Project.plant_id == Plant.id)
        .where(Project.id == project_id, Plant.organization_id == org_id)
    )).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project_id


def _out(f, uploader_name: str | None) -> SepItemFileOut:
    return SepItemFileOut(
        id=f.id, item_id=f.item_id, filename=f.filename, content_type=f.content_type,
        size_bytes=f.size_bytes, sha256=f.sha256, uploaded_by=f.uploaded_by,
        uploaded_by_name=uploader_name, uploaded_at=f.uploaded_at,
    )


async def _with_names(db: AsyncSession, files: list) -> list[SepItemFileOut]:
    names = await _uploader_names(db, {f.uploaded_by for f in files})
    return [_out(f, names.get(f.uploaded_by)) for f in files]


@router.post("/items/{item_id}/files", response_model=list[SepItemFileOut],
             status_code=status.HTTP_201_CREATED)
async def upload_item_files(
    item_id: int,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Attach one or more files of any type to a work item. Audited."""
    item = await _item_in_org(db, item_id, current_user.organization_id)
    try:
        rows = await SepFileService.store_files(
            db, item=item, files=files, user_id=current_user.id)
    except (FileTooLarge, TooManyFiles) as e:
        raise HTTPException(status_code=HTTP_413, detail=str(e))
    except EmptyFilename as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    for row in rows:
        db.add(_audit(item, current_user.id, "file", None, row.filename))
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return await _with_names(db, rows)


@router.get("/items/{item_id}/files", response_model=list[SepItemFileOut])
async def list_item_files(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Files on a work item, newest first; soft-deleted ones stay hidden."""
    await _item_in_org(db, item_id, current_user.organization_id)
    files = await SepFileService.list_item_files(db, item_id=item_id)
    return await _with_names(db, files)


@router.get("/items/{item_id}/files/{file_id}/download")
async def download_item_file(
    item_id: int,
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream one file back under its original name and content type."""
    await _item_in_org(db, item_id, current_user.organization_id)
    f = await SepFileService.get_file(db, item_id=item_id, file_id=file_id)
    if f is None or not os.path.exists(f.stored_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(f.stored_path, filename=f.filename,
                        media_type=f.content_type or "application/octet-stream")


@router.delete("/items/{item_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item_file(
    item_id: int,
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft delete: the row is flagged, the blob stays. Audited."""
    item = await _item_in_org(db, item_id, current_user.organization_id)
    f = await SepFileService.get_file(db, item_id=item_id, file_id=file_id)
    if f is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    filename = f.filename
    await SepFileService.soft_delete(db, file=f, user_id=current_user.id)
    db.add(_audit(item, current_user.id, "file", filename, None))
    await db.commit()


@router.get("/projects/{project_id}/files", response_model=list[SepProjectFileGateOut])
async def project_files(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every file in the project, grouped by gate and work item."""
    await _project_in_org(db, project_id, current_user.organization_id)
    groups = await SepFileService.project_files(db, project_id=project_id)
    all_files = [f for g in groups for i in g["items"] for f in i["files"]]
    names = await _uploader_names(db, {f.uploaded_by for f in all_files})
    return [
        {
            **{k: v for k, v in g.items() if k != "items"},
            "items": [
                {
                    **{k: v for k, v in i.items() if k != "files"},
                    "files": [_out(f, names.get(f.uploaded_by)) for f in i["files"]],
                }
                for i in g["items"]
            ],
        }
        for g in groups
    ]
