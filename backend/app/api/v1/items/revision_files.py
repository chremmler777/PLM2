"""API endpoints for revision-based file management - Phase 5.

Files are attached to a specific PartRevision (not the part), giving each
revision its own document set: CAD models, drawings, pictures, documents,
test results. Uploads are blocked on frozen/cancelled/archived revisions.
"""
import hashlib
import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_current_user
from app.models import get_db
from app.models import User
from app.models.part import RevisionFile, RevisionStatus
from app.services.part_service import PartService, RevisionService, ChangelogService
from app.utils.cad_converter import convert_step_to_gltf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parts", tags=["revision-files"])

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

# Extension -> (file_type, cad_format) mapping. PDFs default to "document";
# callers can override with the file_type form field (e.g. "drawing").
EXTENSION_MAP = {
    ".step": ("cad", "step"),
    ".stp": ("cad", "step"),
    ".iges": ("cad", "iges"),
    ".igs": ("cad", "iges"),
    ".stl": ("cad", "stl"),
    ".jt": ("cad", "jt"),
    ".catpart": ("cad", "catia"),
    ".catproduct": ("cad", "catia"),
    ".dxf": ("drawing", None),
    ".dwg": ("drawing", None),
    ".pdf": ("document", None),
    ".png": ("picture", None),
    ".jpg": ("picture", None),
    ".jpeg": ("picture", None),
    ".gif": ("picture", None),
    ".webp": ("picture", None),
    ".docx": ("document", None),
    ".xlsx": ("document", None),
    ".pptx": ("document", None),
    ".txt": ("document", None),
    ".md": ("document", None),
    ".csv": ("document", None),
}

VALID_FILE_TYPES = {"cad", "drawing", "picture", "document", "test_result"}

MIME_MAP = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

LOCKED_STATUSES = {
    RevisionStatus.FROZEN.value,
    RevisionStatus.CANCELLED.value,
    RevisionStatus.ARCHIVED.value,
}


def _status_value(rev_status) -> str:
    return rev_status.value if hasattr(rev_status, "value") else str(rev_status)


def _uploads_dir(revision_id: int) -> str:
    return os.path.join(os.getcwd(), "uploads", "revisions", str(revision_id))


def _file_response_dict(f: RevisionFile) -> dict:
    return {
        "id": f.id,
        "revision_id": f.revision_id,
        "filename": f.filename,
        "file_type": f.file_type,
        "mime_type": f.mime_type,
        "file_size": f.file_size,
        "cad_format": f.cad_format,
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file (CAD, drawing, picture, document, test result) to a revision."""
    try:
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in EXTENSION_MAP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file extension '{ext}'. Supported: {', '.join(sorted(EXTENSION_MAP))}",
            )

        inferred_type, cad_format = EXTENSION_MAP[ext]
        resolved_type = file_type or inferred_type
        if resolved_type not in VALID_FILE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file_type '{resolved_type}'. Valid: {', '.join(sorted(VALID_FILE_TYPES))}",
            )

        part = await PartService.get_part(db, part_id)
        if not part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")

        revision = await _get_revision_or_404(db, revision_id)
        if revision.part_id != part_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Revision does not belong to this part",
            )
        if _status_value(revision.status) in LOCKED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Revision {revision.revision_name} is {_status_value(revision.status)} and cannot accept new files",
            )

        contents = await file.read()
        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File size must be under 100MB",
            )

        uploads_dir = _uploads_dir(revision_id)
        os.makedirs(uploads_dir, exist_ok=True)
        saved_filename = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(uploads_dir, saved_filename)
        with open(file_path, "wb") as fh:
            fh.write(contents)

        file_hash = hashlib.sha256(contents).hexdigest()

        # Convert STEP CAD files to glTF for the web viewer
        viewer_file_path = None
        if cad_format == "step":
            gltf_path = os.path.join(uploads_dir, f"{uuid.uuid4().hex}.glb")
            try:
                if await convert_step_to_gltf(file_path, gltf_path):
                    viewer_file_path = gltf_path
                else:
                    logger.warning(f"glTF conversion failed for {file.filename}")
            except Exception as e:
                logger.error(f"glTF conversion error for {file.filename}: {e}", exc_info=True)

        rev_file = RevisionFile(
            revision_id=revision_id,
            filename=file.filename,
            file_type=resolved_type,
            mime_type=file.content_type or MIME_MAP.get(ext, "application/octet-stream"),
            file_size=len(contents),
            file_path=file_path,
            cad_format=cad_format,
            file_hash=file_hash,
            viewer_file_path=viewer_file_path,
            has_viewer=viewer_file_path is not None,
            uploaded_by=current_user.id,
        )
        db.add(rev_file)
        await db.flush()

        await ChangelogService.log_action(
            db,
            part_id=part_id,
            revision_id=revision_id,
            action="file_uploaded",
            action_description=f"Uploaded {resolved_type} file '{file.filename}' to {revision.revision_name}",
            performed_by=current_user.id,
            file_id=rev_file.id,
        )
        await db.commit()

        logger.info(f"File uploaded to revision {revision_id}: {file.filename}")
        return {"status": "success", **_file_response_dict(rev_file)}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to upload file to revision {revision_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


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
        })

    return entries


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
    return [_file_response_dict(f) for f in result.scalars().all()]


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
