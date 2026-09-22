"""API endpoints for parts and revisions - Phase 1 Redesign."""
import logging
import os
import uuid
from typing import List
from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_current_user
from app.models import get_db
from app.models import User
from app.models.part import PartFile
from app.services.part_service import PartService, RevisionService, ChangelogService
from app.services.project_structure_service import project_structure
from app.utils.cad_converter import convert_step_to_gltf
from app.schemas.part import (
    PartCreate, PartUpdate, PartResponse, PartDetailResponse,
    PartRevisionResponse, PartRevisionDetailResponse,
    ChangelogEntryResponse, RevisionTreeNode,
    CustomerDataReceivedRequest, CreateProposalRequest, PromoteRevisionRequest,
    RejectMajorRevisionRequest, SetLifecyclePhaseRequest,
)
from app.services.revision_naming import RevisionRuleViolation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parts", tags=["parts"])


# Part CRUD Endpoints
@router.post("", response_model=PartResponse)
async def create_part(
    body: PartCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new part in a project."""
    try:
        part = await PartService.create_part(
            session=db,
            project_id=body.project_id,
            part_number=body.part_number,
            name=body.name,
            part_type=body.part_type,
            description=body.description,
            supplier=body.supplier,
            created_by=current_user.id,
            data_classification=body.data_classification,
            parent_part_id=body.parent_part_id,
            item_category=body.item_category,
            calibration_interval_months=body.calibration_interval_months,
            last_calibrated_at=body.last_calibrated_at,
            supplier_id=body.supplier_id,
            customer_part_number=body.customer_part_number,
        )
        await db.commit()
        return part
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create part: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{part_id}", response_model=PartDetailResponse)
async def get_part(
    part_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get part details with revisions."""
    part = await PartService.get_part(db, part_id)
    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
    return part


@router.get("/project/{project_id}", response_model=List[PartResponse])
async def get_project_parts(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all parts in a project."""
    parts = await PartService.get_parts_by_project(db, project_id)
    return parts


@router.get("/project/{project_id}/structure", response_model=dict)
async def get_project_structure(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Articles with revisions, related tools/gauges/equipment and mirror links, in one call."""
    return await project_structure(db, project_id)


@router.put("/{part_id}", response_model=PartResponse)
async def update_part(
    part_id: int,
    body: PartUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update part information."""
    try:
        part = await PartService.update_part(
            session=db,
            part_id=part_id,
            name=body.name,
            description=body.description,
            part_type=body.part_type,
            supplier=body.supplier,
            updated_by=current_user.id,
            parent_part_id=body.parent_part_id,
            update_parent='parent_part_id' in body.model_fields_set,
            item_category=body.item_category,
            calibration_interval_months=body.calibration_interval_months,
            last_calibrated_at=body.last_calibrated_at,
            supplier_id=body.supplier_id,
            update_supplier='supplier_id' in body.model_fields_set,
            customer_part_number=body.customer_part_number,
            update_customer_part_number='customer_part_number' in body.model_fields_set,
        )
        if not part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
        await db.commit()
        return part
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update part: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{part_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_part(
    part_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a part."""
    try:
        success = await PartService.delete_part(db, part_id)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete part: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Revision Endpoints
@router.get("/{part_id}/revisions", response_model=List[PartRevisionResponse])
async def get_part_revisions(
    part_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all revisions for a part."""
    revisions = await RevisionService.get_part_revisions(db, part_id)
    return revisions


@router.get("/revisions/{revision_id}", response_model=PartRevisionDetailResponse)
async def get_revision(
    revision_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific revision with details."""
    revision = await RevisionService.get_revision(db, revision_id)
    if not revision:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found")
    return revision


# Customer data (the only way a major revision is created)
@router.post("/{part_id}/revisions/customer-data", response_model=PartRevisionResponse,
             status_code=status.HTTP_201_CREATED)
async def receive_customer_data(
    part_id: int,
    body: CustomerDataReceivedRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record customer data as the next major: E<n> for review, <n> for official."""
    try:
        revision = await RevisionService.receive_customer_data(
            db, part_id, body.statement, body.received_at,
            customer_index=body.customer_index, summary=body.summary, created_by=current_user.id,
            major=body.major)
        await db.commit()
        return revision
    except RevisionRuleViolation as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{part_id}/revisions/proposals", response_model=PartRevisionResponse,
             status_code=status.HTTP_201_CREATED)
async def create_proposal(
    part_id: int,
    body: CreateProposalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Our internal iteration under a customer major (E1 → E1.1, 1 → 1.1)."""
    try:
        proposal = await RevisionService.create_proposal(
            db, part_id, body.parent_revision_id, summary=body.summary, created_by=current_user.id)
        await db.commit()
        return proposal
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{part_id}/revisions/{revision_id}/promote", response_model=PartRevisionResponse)
async def promote_revision(
    part_id: int,
    revision_id: int,
    body: PromoteRevisionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The customer adopted this proposal as their next data state."""
    try:
        new_revision = await RevisionService.promote_revision(
            db, revision_id, body.statement, body.received_at,
            customer_index=body.customer_index, created_by=current_user.id, major=body.major)
        await db.commit()
        return new_revision
    except RevisionRuleViolation as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{part_id}/lifecycle-phase", response_model=PartResponse)
async def set_lifecycle_phase(
    part_id: int,
    body: SetLifecyclePhaseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """rfq → nominated (sets nominated_at) → series (sets sop_at). Admin only."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    try:
        part = await RevisionService.set_lifecycle_phase(
            db, part_id, body.phase, body.effective, created_by=current_user.id)
        await db.commit()
        return part
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{part_id}/revisions/{revision_id}/reject", response_model=PartRevisionResponse)
async def reject_revision(
    part_id: int,
    revision_id: int,
    body: RejectMajorRevisionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject a major revision so you can go back to a previous version."""
    try:
        revision = await RevisionService.reject_revision(
            session=db,
            revision_id=revision_id,
            created_by=current_user.id,
        )
        await db.commit()
        return revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to reject revision: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{part_id}/revisions/{revision_id}/unreject", response_model=PartRevisionResponse)
async def unreject_revision(
    part_id: int,
    revision_id: int,
    body: RejectMajorRevisionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Restore a rejected/archived revision back to draft (for proposals) or available status."""
    try:
        revision = await RevisionService.unreject_revision(
            session=db,
            revision_id=revision_id,
            created_by=current_user.id,
        )
        await db.commit()
        return revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to unreject revision: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{part_id}/changelog", response_model=List[ChangelogEntryResponse])
async def get_part_changelog(
    part_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get changelog for a part."""
    entries = await ChangelogService.get_part_changelog(db, part_id)
    # Convert to response with username populated
    result = []
    for entry in entries:
        entry_dict = {
            'id': entry.id,
            'part_id': entry.part_id,
            'revision_id': entry.revision_id,
            'action': entry.action,
            'action_description': entry.action_description,
            'field_name': entry.field_name,
            'old_value': entry.old_value,
            'new_value': entry.new_value,
            'file_id': entry.file_id,
            'performed_by': entry.performed_by,
            'performed_by_user': entry.performed_by_user.username if entry.performed_by_user else None,
            'performed_at': entry.performed_at,
            'notes': entry.notes,
            'ip_address': entry.ip_address,
        }
        result.append(ChangelogEntryResponse(**entry_dict))
    return result


@router.get("/revisions/{revision_id}/changelog", response_model=List[ChangelogEntryResponse])
async def get_revision_changelog(
    revision_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get changelog for a specific revision."""
    entries = await ChangelogService.get_revision_changelog(db, revision_id)
    # Convert to response with username populated
    result = []
    for entry in entries:
        entry_dict = {
            'id': entry.id,
            'part_id': entry.part_id,
            'revision_id': entry.revision_id,
            'action': entry.action,
            'action_description': entry.action_description,
            'field_name': entry.field_name,
            'old_value': entry.old_value,
            'new_value': entry.new_value,
            'file_id': entry.file_id,
            'performed_by': entry.performed_by,
            'performed_by_user': entry.performed_by_user.username if entry.performed_by_user else None,
            'performed_at': entry.performed_at,
            'notes': entry.notes,
            'ip_address': entry.ip_address,
        }
        result.append(ChangelogEntryResponse(**entry_dict))
    return result


# File Upload Endpoints
@router.post("/{part_id}/files", response_model=dict, status_code=status.HTTP_201_CREATED)
async def upload_part_file(
    part_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a 3D CAD file (STEP or CATIA format) for a part."""
    try:
        # Validate file type
        valid_extensions = ['.step', '.stp', '.catpart', '.catproduct']
        file_lower = file.filename.lower() if file.filename else ""
        has_valid_ext = any(file_lower.endswith(ext) for ext in valid_extensions)

        if not has_valid_ext:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only STEP (.step, .stp) and CATIA (.catpart, .catproduct) files are supported"
            )

        # Check file size (100MB limit)
        max_size = 100 * 1024 * 1024
        if file.size and file.size > max_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File size must be under 100MB"
            )

        # Verify part exists
        part = await PartService.get_part(db, part_id)
        if not part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")

        # Create uploads directory if it doesn't exist
        uploads_dir = os.path.join(os.getcwd(), "uploads", "parts")
        os.makedirs(uploads_dir, exist_ok=True)

        # Save file with unique name
        file_ext = os.path.splitext(file.filename)[1]
        unique_filename = f"{part_id}_{uuid.uuid4().hex}{file_ext}"
        file_path = os.path.join(uploads_dir, unique_filename)

        # Write file to disk
        contents = await file.read()
        with open(file_path, 'wb') as f:
            f.write(contents)

        # Extract file type (step or catia)
        file_type = 'step' if file_ext in ['.step', '.stp'] else 'catia'

        # Convert to glTF for web viewing
        gltf_filename = None
        conversion_failed = False
        if file_type == 'step':  # Only convert STEP files
            try:
                gltf_name = f"{part_id}_{uuid.uuid4().hex}.glb"
                gltf_path = os.path.join(uploads_dir, gltf_name)

                logger.info(f"Starting conversion for {unique_filename}")
                # Run conversion
                success = await convert_step_to_gltf(file_path, gltf_path)
                if success:
                    gltf_filename = gltf_name
                    logger.info(f"Converted {unique_filename} to {gltf_name}")
                else:
                    logger.warning(f"Failed to convert {unique_filename} to glTF - conversion returned False")
                    conversion_failed = True
            except Exception as e:
                logger.error(f"Conversion error for {unique_filename}: {e}", exc_info=True)
                conversion_failed = True

        # Create PartFile record in database
        part_file = PartFile(
            part_id=part_id,
            original_filename=file.filename,
            saved_filename=unique_filename,
            file_size=len(contents),
            file_type=file_type,
            gltf_filename=gltf_filename,
            conversion_status="processing" if file_type == "step" else "completed",
            created_by=current_user.id
        )
        db.add(part_file)
        await db.commit()

        # Update status after conversion (async, non-blocking)
        if file_type == "step" and gltf_filename:
            part_file.conversion_status = "completed"
        elif file_type == "step":
            part_file.conversion_status = "failed"
        else:
            part_file.conversion_status = "completed"

        await db.commit()

        logger.info(f"File uploaded for part {part_id}: {unique_filename}")

        return {
            "status": "success",
            "file_id": part_file.id,
            "filename": file.filename,
            "saved_as": unique_filename,
            "part_id": part_id,
            "size": len(contents)
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to upload file for part {part_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/files/{file_id}/status")
async def get_file_conversion_status(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get conversion status for a file."""
    try:
        result = await db.execute(
            select(PartFile).where(PartFile.id == file_id)
        )
        part_file = result.scalar_one_or_none()

        if not part_file:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

        return {
            "id": part_file.id,
            "status": part_file.conversion_status,
            "has_viewer": part_file.conversion_status == "completed" and part_file.gltf_filename is not None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get file status {file_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{part_id}/files", response_model=List[dict])
async def get_part_files(
    part_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all files for a part."""
    try:
        # Verify part exists
        part = await PartService.get_part(db, part_id)
        if not part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")

        # Get all files for this part
        result = await db.execute(
            select(PartFile).where(PartFile.part_id == part_id)
        )
        files = result.scalars().all()

        return [
            {
                "id": f.id,
                "original_filename": f.original_filename,
                "file_type": f.file_type,
                "file_size": f.file_size,
                "created_at": f.created_at.isoformat(),
            }
            for f in files
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get files for part {part_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/files/{file_id}/viewer")
async def view_part_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get the glTF viewer file for a part."""
    try:
        # Get the file record
        result = await db.execute(
            select(PartFile).where(PartFile.id == file_id)
        )
        part_file = result.scalar_one_or_none()

        if not part_file:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

        # Use glTF if available, otherwise serve raw file
        file_to_serve = part_file.gltf_filename if part_file.gltf_filename else part_file.saved_filename
        file_path = os.path.join(os.getcwd(), "uploads", "parts", file_to_serve)

        # Check if file exists
        if not os.path.exists(file_path):
            logger.error(f"File not found on disk: {file_path}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")

        # Return glTF file for 3D viewer
        return FileResponse(
            path=file_path,
            filename=part_file.original_filename.rsplit('.', 1)[0] + '.glb',
            media_type="model/gltf-binary" if file_to_serve.endswith('.glb') else "application/json"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to view file {file_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/files/{file_id}/download")
async def download_part_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Download a part file."""
    try:
        # Get the file record
        result = await db.execute(
            select(PartFile).where(PartFile.id == file_id)
        )
        part_file = result.scalar_one_or_none()

        if not part_file:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

        # Construct file path
        file_path = os.path.join(os.getcwd(), "uploads", "parts", part_file.saved_filename)

        # Check if file exists
        if not os.path.exists(file_path):
            logger.error(f"File not found on disk: {file_path}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")

        return FileResponse(
            path=file_path,
            filename=part_file.original_filename,
            media_type="application/octet-stream"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download file {file_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/files/{file_id}")
async def delete_part_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a part file."""
    try:
        # Get the file record
        result = await db.execute(
            select(PartFile).where(PartFile.id == file_id)
        )
        part_file = result.scalar_one_or_none()

        if not part_file:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

        # Construct file paths
        file_path = os.path.join(os.getcwd(), "uploads", "parts", part_file.saved_filename)
        gltf_path = None
        if part_file.gltf_filename:
            gltf_path = os.path.join(os.getcwd(), "uploads", "parts", part_file.gltf_filename)

        # Delete files from disk if they exist
        for path in [file_path, gltf_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as e:
                    logger.error(f"Failed to delete file from disk: {e}")

        # Delete record from database
        await db.delete(part_file)
        await db.commit()

        logger.info(f"File deleted: {part_file.saved_filename}")

        return {"status": "success", "message": "File deleted"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete file {file_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
