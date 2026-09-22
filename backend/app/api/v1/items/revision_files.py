"""API endpoints for revision-based file management - Phase 5.

Files are attached to a specific PartRevision (not the part), giving each
revision its own document set: CAD models, drawings, pictures, documents,
test results. Uploads are blocked on frozen/cancelled/archived revisions.
"""
import logging
import os
from dataclasses import asdict
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_current_user
from app.models import get_db
from app.models import User
from app.models.entities import Project
from app.models.part import RevisionFile, RevisionStatus
from app.services.customer_naming import CONVENTIONS, parse_filename
from app.services.part_service import PartService, RevisionService, ChangelogService
from app.services.revision_file_service import UnsupportedFile, store_revision_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parts", tags=["revision-files"])

LOCKED_STATUSES = {
    RevisionStatus.FROZEN.value,
    RevisionStatus.CANCELLED.value,
    RevisionStatus.ARCHIVED.value,
}


def _status_value(rev_status) -> str:
    return rev_status.value if hasattr(rev_status, "value") else str(rev_status)


async def _uploader_names(db: AsyncSession, user_ids: set) -> dict:
    """id -> display name, in one query. File lists must never resolve the
    uploader per row."""
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    rows = (await db.execute(
        select(User.id, User.full_name, User.username).where(User.id.in_(ids)))).all()
    return {uid: (full or username) for uid, full, username in rows}


def _file_response_dict(f: RevisionFile, uploader_name: str | None = None) -> dict:
    return {
        "uploaded_by_name": uploader_name,
        "id": f.id,
        "revision_id": f.revision_id,
        "filename": f.filename,
        "file_type": f.file_type,
        "mime_type": f.mime_type,
        "file_size": f.file_size,
        "cad_format": f.cad_format,
        "kind": f.kind,
        "note": f.note,
        "file_hash": f.file_hash,
        "has_viewer": f.has_viewer,
        "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None,
        "uploaded_by": f.uploaded_by,
    }


async def _get_revision_or_404(db: AsyncSession, revision_id: int):
    revision = await RevisionService.get_revision(db, revision_id)
    if not revision:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found")
    return revision


async def _load_revision(
    db: AsyncSession, part_id: int, revision_id: int, *, mismatch_status: int = status.HTTP_404_NOT_FOUND
):
    """Load a revision, 404 on missing; on part mismatch raise `mismatch_status`
    (404 by default, or 400 to preserve the upload endpoint's existing contract)."""
    revision = await RevisionService.get_revision(db, revision_id)
    if not revision:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found")
    if revision.part_id != part_id:
        detail = "Revision not found" if mismatch_status == status.HTTP_404_NOT_FOUND else "Revision does not belong to this part"
        raise HTTPException(status_code=mismatch_status, detail=detail)
    return revision


async def _get_file_or_404(db: AsyncSession, file_id: int) -> RevisionFile:
    result = await db.execute(
        select(RevisionFile).where(RevisionFile.id == file_id, RevisionFile.is_deleted == False)  # noqa: E712
    )
    rev_file = result.scalar_one_or_none()
    if not rev_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return rev_file


@router.post(
    "/{part_id}/revisions/{revision_id}/files",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
async def upload_revision_file(
    part_id: int,
    revision_id: int,
    file: UploadFile = File(...),
    file_type: Optional[str] = Form(None),
    kind: Optional[str] = Form(None, max_length=10),
    note: Optional[str] = Form(None, max_length=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file (CAD, drawing, picture, document, test result) to a revision."""
    try:
        part = await PartService.get_part(db, part_id)
        if not part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
        revision = await _load_revision(db, part_id, revision_id, mismatch_status=status.HTTP_400_BAD_REQUEST)
        if _status_value(revision.status) in LOCKED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Revision {revision.revision_name} is {_status_value(revision.status)} and cannot accept new files",
            )
        contents = await file.read()
        try:
            rev_file = await store_revision_file(db, revision, file.filename or "", contents, current_user.id,
                                                 content_type=file.content_type, file_type=file_type,
                                                 kind=kind, note=note)
        except UnsupportedFile as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        await db.commit()

        logger.info(f"File uploaded to revision {revision_id}: {file.filename}")
        return {"status": "success", **_file_response_dict(rev_file)}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to upload file to revision {revision_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


class NoGeometryChangeIn(BaseModel):
    reason: str


@router.post("/{part_id}/revisions/{revision_id}/no-geometry-change")
async def sign_no_geometry_change(
    part_id: int,
    revision_id: int,
    body: NoGeometryChangeIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Owner-signed statement that this ECN revision has no geometry change -
    the alternative 3D evidence to a CAD upload (spec: 3D-evidence decision).

    One-way and idempotency-hostile by design: a second sign is rejected.
    """
    revision = await _load_revision(db, part_id, revision_id)
    if _status_value(revision.status) in LOCKED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Revision {revision.revision_name} is {_status_value(revision.status)}; evidence is locked",
        )
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reason is required")
    if revision.no_geometry_change:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already signed")

    revision.no_geometry_change = True
    revision.no_geometry_change_by = current_user.id
    revision.no_geometry_change_at = datetime.utcnow()
    revision.no_geometry_change_reason = reason

    await ChangelogService.log_action(
        db,
        part_id=part_id,
        revision_id=revision_id,
        action="no_geometry_change_signed",
        action_description=f"No-geometry-change signed: {reason}",
        performed_by=current_user.id,
    )

    from app.services.audit_service import AuditService

    correlation = None
    if revision.originating_change_id is not None:
        from app.models.change import ChangeRequest

        change = await db.get(ChangeRequest, revision.originating_change_id)
        correlation = change.change_number if change else None
    await AuditService.record(
        db,
        entity_type="part_revision",
        entity_id=revision_id,
        action="no_geometry_change_signed",
        user_id=current_user.id,
        new_values={"reason": reason},
        correlation_id=correlation,
    )

    await db.commit()
    return {
        "revision_id": revision_id,
        "no_geometry_change": True,
        "no_geometry_change_by": current_user.id,
        "no_geometry_change_at": revision.no_geometry_change_at.isoformat(),
    }


@router.get("/{part_id}/assembly-files", response_model=List[dict])
async def get_assembly_files(
    part_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Viewable CAD files for a part and all its descendants (assembly view).

    For each part in the hierarchy, picks its display revision (active revision
    if set, otherwise the latest) and that revision's first viewable CAD file.
    """
    from app.models.part import Part, PartRevision

    root = await PartService.get_part(db, part_id)
    if not root:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")

    # Collect root + descendants (BFS over parent_part_id)
    parts = [root]
    frontier = [root.id]
    while frontier:
        result = await db.execute(select(Part).where(Part.parent_part_id.in_(frontier)))
        children = result.scalars().all()
        parts.extend(children)
        frontier = [c.id for c in children]

    entries = []
    for part in parts:
        revisions = await RevisionService.get_part_revisions(db, part.id)
        if not revisions:
            continue
        display_rev = next(
            (r for r in revisions if r.id == part.active_revision_id),
            revisions[-1],
        )
        file_result = await db.execute(
            select(RevisionFile)
            .where(
                RevisionFile.revision_id == display_rev.id,
                RevisionFile.has_viewer == True,  # noqa: E712
                RevisionFile.is_deleted == False,  # noqa: E712
            )
            .order_by(RevisionFile.uploaded_at)
            .limit(1)
        )
        rev_file = file_result.scalar_one_or_none()
        if not rev_file:
            continue
        entries.append({
            "part_id": part.id,
            "part_number": part.part_number,
            "part_name": part.name,
            "revision_id": display_rev.id,
            "revision_name": display_rev.revision_name,
            "file_id": rev_file.id,
            # Provenance of the file actually being shown.
            "uploaded_at": (rev_file.uploaded_at.isoformat()
                            if rev_file.uploaded_at else None),
            "uploaded_by": rev_file.uploaded_by,
        })

    names = await _uploader_names(db, {e["uploaded_by"] for e in entries})
    for e in entries:
        e["uploaded_by_name"] = names.get(e["uploaded_by"])
    return entries


@router.get("/{part_id}/files/parse", response_model=dict)
async def parse_upload_filenames(
    part_id: int,
    filenames: List[str] = Query(..., min_length=1, max_length=200),
    convention: Optional[str] = Query(None, description="vw | scout | none; omitted = project default"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read customer index and data kind from filenames before uploading.
    Detection only prefills the dialog; nothing is stored here."""
    part = await PartService.get_part(db, part_id)
    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
    if convention is None:
        project = await db.get(Project, part.project_id)
        effective = project.customer_naming if project else None
    elif convention == "none":
        effective = None
    elif convention in CONVENTIONS:
        effective = convention
    else:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Unknown convention '{convention}'")
    rows = []
    for name in filenames:
        parsed = asdict(parse_filename(name, effective, part.customer_part_number))
        parsed["dated"] = parsed["dated"].isoformat() if parsed["dated"] else None
        rows.append(parsed)
    return {"convention": effective, "conventions": CONVENTIONS, "rows": rows}


@router.get("/revisions/{revision_id}/files", response_model=List[dict])
async def list_revision_files(
    revision_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all (non-deleted) files attached to a revision."""
    await _get_revision_or_404(db, revision_id)
    result = await db.execute(
        select(RevisionFile)
        .where(RevisionFile.revision_id == revision_id, RevisionFile.is_deleted == False)  # noqa: E712
        .order_by(RevisionFile.uploaded_at)
    )
    files = result.scalars().all()
    names = await _uploader_names(db, {f.uploaded_by for f in files})
    return [_file_response_dict(f, names.get(f.uploaded_by)) for f in files]


@router.get("/revision-files/{file_id}/status")
async def get_revision_file_status(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Conversion/viewer status for a revision file."""
    rev_file = await _get_file_or_404(db, file_id)
    if rev_file.has_viewer:
        conversion = "completed"
    elif rev_file.cad_format == "step":
        conversion = "failed"
    else:
        conversion = "not_applicable"
    return {"id": rev_file.id, "status": conversion, "has_viewer": rev_file.has_viewer}


@router.get("/revision-files/{file_id}/viewer")
async def view_revision_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Serve the glTF viewer file for a revision file."""
    rev_file = await _get_file_or_404(db, file_id)
    file_to_serve = rev_file.viewer_file_path or rev_file.file_path
    if not os.path.exists(file_to_serve):
        logger.error(f"File not found on disk: {file_to_serve}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")
    is_glb = file_to_serve.endswith(".glb")
    return FileResponse(
        path=file_to_serve,
        filename=os.path.splitext(rev_file.filename)[0] + ".glb" if is_glb else rev_file.filename,
        media_type="model/gltf-binary" if is_glb else rev_file.mime_type,
    )


@router.get("/revision-files/{file_id}/download")
async def download_revision_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Download the original revision file."""
    rev_file = await _get_file_or_404(db, file_id)
    if not os.path.exists(rev_file.file_path):
        logger.error(f"File not found on disk: {rev_file.file_path}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")
    return FileResponse(
        path=rev_file.file_path,
        filename=rev_file.filename,
        media_type="application/octet-stream",
    )


@router.delete("/revision-files/{file_id}")
async def delete_revision_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a revision file. Files on locked revisions cannot be deleted."""
    try:
        rev_file = await _get_file_or_404(db, file_id)
        revision = await _get_revision_or_404(db, rev_file.revision_id)
        if _status_value(revision.status) in LOCKED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Revision {revision.revision_name} is {_status_value(revision.status)}; its files cannot be deleted",
            )

        rev_file.is_deleted = True
        rev_file.deleted_at = datetime.utcnow()

        await ChangelogService.log_action(
            db,
            part_id=revision.part_id,
            revision_id=revision.id,
            action="file_deleted",
            action_description=f"Deleted file '{rev_file.filename}' from {revision.revision_name}",
            performed_by=current_user.id,
            file_id=rev_file.id,
        )
        await db.commit()
        return {"status": "success", "message": "File deleted"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete revision file {file_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
