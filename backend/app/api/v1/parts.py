"""API endpoints for parts and revisions - Phase 1 Redesign."""
import logging
from typing import List
from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db
from app.models import User
from app.services.part_service import PartService, RevisionService, ChangelogService
from app.schemas.part import (
    PartCreate, PartUpdate, PartResponse, PartDetailResponse,
    PartRevisionResponse, PartRevisionDetailResponse,
    ChangelogEntryResponse, RevisionTreeNode,
    CreateRFQRequest, CreateRFQProposalRequest, PromoteRevisionRequest,
    RejectMajorRevisionRequest,
    TransitionToEngineeringRequest, CreateEngineeringProposalRequest,
    ApproveProposalRequest, RejectProposalRequest, CreateDesignFreezeRequest,
    CreateECRRequest
)

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


# RFQ Phase Endpoints
@router.post("/{part_id}/revisions/rfq", response_model=PartRevisionResponse)
async def create_rfq_revision(
    part_id: int,
    body: CreateRFQRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new major RFQ revision (RFQ1, RFQ2, etc) - auto-increments."""
    try:
        revision = await RevisionService.create_rfq_revision(
            session=db,
            part_id=part_id,
            summary=body.summary,
            created_by=current_user.id,
            reject_drafts=body.reject_drafts,
        )
        await db.commit()
        return revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create RFQ revision: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{part_id}/revisions/rfq-proposal", response_model=PartRevisionResponse)
async def create_rfq_proposal(
    part_id: int,
    body: CreateRFQProposalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an RFQ proposal (minor iteration like RFQ1.1, RFQ1.2)."""
    try:
        proposal = await RevisionService.create_rfq_proposal(
            session=db,
            part_id=part_id,
            parent_revision_id=body.parent_revision_id,
            summary=body.summary,
            created_by=current_user.id,
        )
        await db.commit()
        return proposal
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create RFQ proposal: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{part_id}/revisions/{revision_id}/promote", response_model=PartRevisionResponse)
async def promote_revision(
    part_id: int,
    revision_id: int,
    body: PromoteRevisionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Promote a revision to the next major version (e.g., RFQ1.2 → RFQ2)."""
    try:
        new_revision = await RevisionService.promote_revision(
            session=db,
            revision_id=revision_id,
            created_by=current_user.id,
        )
        await db.commit()
        return new_revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to promote revision: {e}")
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


@router.post("/{part_id}/revisions/{rfq_revision_id}/to-engineering", response_model=PartRevisionResponse)
async def transition_rfq_to_engineering(
    part_id: int,
    rfq_revision_id: int,
    body: TransitionToEngineeringRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Transition from RFQ to Engineering (award and start ENG1)."""
    try:
        revision = await RevisionService.transition_rfq_to_engineering(
            session=db,
            rfq_revision_id=rfq_revision_id,
            summary=body.summary,
            created_by=current_user.id,
        )
        await db.commit()
        return revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to transition to engineering: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{part_id}/revisions/engineering-proposal", response_model=PartRevisionResponse)
async def create_engineering_proposal_endpoint(
    part_id: int,
    body: CreateRFQProposalRequest,  # Reuse RFQ proposal schema structure
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an engineering proposal (ENG1.1, ENG1.2, etc) - auto-increments minor version."""
    try:
        revision = await RevisionService.create_engineering_proposal_simple(
            session=db,
            part_id=part_id,
            parent_revision_id=body.parent_revision_id,
            summary=body.summary,
            created_by=current_user.id,
        )
        await db.commit()
        return revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create engineering proposal: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{part_id}/revisions/{revision_id}/advance-engineering", response_model=PartRevisionResponse)
async def advance_engineering_proposal(
    part_id: int,
    revision_id: int,
    body: PromoteRevisionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Advance (promote) an engineering proposal to next major version (ENG1.2 → ENG2)."""
    try:
        revision = await RevisionService.advance_engineering_proposal(
            session=db,
            part_id=part_id,
            proposal_revision_id=revision_id,
            created_by=current_user.id,
        )
        await db.commit()
        return revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to advance engineering proposal: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{part_id}/revisions/{revision_id}/to-freeze", response_model=PartRevisionResponse)
async def transition_engineering_to_freeze(
    part_id: int,
    revision_id: int,
    body: CreateDesignFreezeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Transition from Engineering to Design Freeze (IND1, IND2, etc)."""
    try:
        revision = await RevisionService.transition_engineering_to_freeze(
            session=db,
            eng_revision_id=revision_id,
            summary=body.summary,
            created_by=current_user.id,
        )
        await db.commit()
        return revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to transition to freeze: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Engineering Phase Endpoints (legacy)
@router.post("/revisions/{parent_revision_id}/propose-engineering", response_model=PartRevisionResponse)
async def create_engineering_proposal(
    parent_revision_id: int,
    body: CreateEngineeringProposalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an engineering proposal (ENG1.1, ENG1.2, ENG2.1, etc)."""
    try:
        parent = await RevisionService.get_revision(db, parent_revision_id)
        if not parent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent revision not found")

        revision = await RevisionService.create_engineering_proposal(
            session=db,
            part_id=parent.part_id,
            parent_revision_id=parent_revision_id,
            major_version=body.major_version,
            proposal_number=body.proposal_number,
            summary=body.summary,
            change_reason=body.change_reason,
            created_by=current_user.id,
        )
        await db.commit()
        return revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create engineering proposal: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/revisions/{proposal_revision_id}/approve", response_model=PartRevisionResponse)
async def approve_engineering_proposal(
    proposal_revision_id: int,
    body: ApproveProposalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve an engineering proposal."""
    try:
        revision = await RevisionService.approve_engineering_proposal(
            session=db,
            proposal_revision_id=proposal_revision_id,
            next_major_version=body.next_major_version,
            approved_by=current_user.id,
            approval_notes=body.approval_notes,
        )
        await db.commit()
        return revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to approve proposal: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/revisions/{proposal_revision_id}/reject", response_model=PartRevisionResponse)
async def reject_engineering_proposal(
    proposal_revision_id: int,
    body: RejectProposalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject an engineering proposal."""
    try:
        revision = await RevisionService.reject_engineering_proposal(
            session=db,
            proposal_revision_id=proposal_revision_id,
            rejected_by=current_user.id,
        )
        await db.commit()
        return revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to reject proposal: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Design Freeze Endpoints
@router.post("/revisions/{parent_revision_id}/freeze", response_model=PartRevisionResponse)
async def create_design_freeze(
    parent_revision_id: int,
    body: CreateDesignFreezeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a design freeze (IND1, IND2, etc)."""
    try:
        parent = await RevisionService.get_revision(db, parent_revision_id)
        if not parent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent revision not found")

        revision = await RevisionService.create_design_freeze(
            session=db,
            part_id=parent.part_id,
            parent_revision_id=parent_revision_id,
            created_by=current_user.id,
        )
        await db.commit()
        return revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create design freeze: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ECR Phase Endpoints
@router.post("/revisions/{parent_revision_id}/propose-ecr", response_model=PartRevisionResponse)
async def create_ecr_proposal(
    parent_revision_id: int,
    body: CreateECRRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an ECR proposal (ECR1.1, ECR1.2, ECR2.1, etc)."""
    try:
        parent = await RevisionService.get_revision(db, parent_revision_id)
        if not parent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent revision not found")

        revision = await RevisionService.create_ecr_proposal(
            session=db,
            part_id=parent.part_id,
            parent_freeze_id=parent_revision_id,
            freeze_major_version=body.freeze_major_version,
            proposal_number=body.proposal_number,
            summary=body.summary,
            change_reason=body.change_reason,
            created_by=current_user.id,
        )
        await db.commit()
        return revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create ECR proposal: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/revisions/{ecr_revision_id}/approve-ecr", response_model=PartRevisionResponse)
async def approve_ecr_proposal(
    ecr_revision_id: int,
    body: ApproveProposalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve an ECR proposal."""
    try:
        revision = await RevisionService.approve_ecr_proposal(
            session=db,
            ecr_revision_id=ecr_revision_id,
            next_freeze_major_version=body.next_major_version,
            approved_by=current_user.id,
            approval_notes=body.approval_notes,
        )
        await db.commit()
        return revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to approve ECR: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/revisions/{ecr_revision_id}/reject-ecr", response_model=PartRevisionResponse)
async def reject_ecr_proposal(
    ecr_revision_id: int,
    body: RejectProposalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject an ECR proposal."""
    try:
        revision = await RevisionService.reject_ecr_proposal(
            session=db,
            ecr_revision_id=ecr_revision_id,
            rejected_by=current_user.id,
        )
        await db.commit()
        return revision
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to reject ECR: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Changelog Endpoints
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
