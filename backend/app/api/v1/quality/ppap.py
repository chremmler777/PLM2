"""PPAP endpoints - quality submissions per part revision."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.part import RevisionFile
from app.models.quality import (
    PPAPSubmission,
    PPAPElement,
    PPAP_ELEMENTS,
    PPAP_REQUIRED_BY_LEVEL,
)
from app.services.part_service import PartService, RevisionService, ChangelogService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quality", tags=["quality"])

ELEMENT_STATUSES = {"pending", "attached", "approved", "rejected", "na"}


class PPAPCreate(BaseModel):
    level: int = Field(3, ge=1, le=5)
    customer: Optional[str] = None
    notes: Optional[str] = None


class ElementUpdate(BaseModel):
    status: Optional[str] = None
    file_id: Optional[int] = None
    comment: Optional[str] = None


class DecisionRequest(BaseModel):
    notes: Optional[str] = None


def _element_dict(e: PPAPElement) -> dict:
    return {
        "id": e.id,
        "position": e.position,
        "name": e.name,
        "required": e.required,
        "status": e.status,
        "file_id": e.file_id,
        "comment": e.comment,
    }


def _submission_dict(s: PPAPSubmission) -> dict:
    elements = [_element_dict(e) for e in s.elements]
    required = [e for e in elements if e["required"]]
    done = [e for e in required if e["status"] in ("attached", "approved", "na")]
    return {
        "id": s.id,
        "revision_id": s.revision_id,
        "level": s.level,
        "status": s.status,
        "customer": s.customer,
        "notes": s.notes,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
        "decided_at": s.decided_at.isoformat() if s.decided_at else None,
        "decision_notes": s.decision_notes,
        "progress": {"done": len(done), "required": len(required)},
        "elements": elements,
    }


async def _load_submission(db: AsyncSession, submission_id: int) -> PPAPSubmission:
    result = await db.execute(
        select(PPAPSubmission)
        .where(PPAPSubmission.id == submission_id)
        .options(selectinload(PPAPSubmission.elements))
    )
    submission = result.scalar_one_or_none()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PPAP submission not found")
    return submission


@router.post("/revisions/{revision_id}/ppap", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_ppap(
    revision_id: int,
    body: PPAPCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a PPAP submission with the standard 18-element checklist."""
    try:
        revision = await RevisionService.get_revision(db, revision_id)
        if not revision:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found")

        existing = await db.execute(
            select(PPAPSubmission).where(
                PPAPSubmission.revision_id == revision_id,
                PPAPSubmission.status.in_(["draft", "submitted"]),
            )
        )
        if existing.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An open PPAP submission already exists for this revision",
            )

        submission = PPAPSubmission(
            revision_id=revision_id,
            level=body.level,
            customer=body.customer,
            notes=body.notes,
            created_by=current_user.id,
        )
        db.add(submission)
        await db.flush()

        required_set = PPAP_REQUIRED_BY_LEVEL.get(body.level, set(range(18)))
        for idx, name in enumerate(PPAP_ELEMENTS):
            db.add(PPAPElement(
                submission_id=submission.id,
                position=idx + 1,
                name=name,
                required=idx in required_set,
            ))
        await db.flush()

        await ChangelogService.log_action(
            db,
            part_id=revision.part_id,
            revision_id=revision_id,
            action="ppap_created",
            action_description=f"Created PPAP level {body.level} submission for {revision.revision_name}",
            performed_by=current_user.id,
        )
        await db.commit()
        return _submission_dict(await _load_submission(db, submission.id))
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create PPAP for revision {revision_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/revisions/{revision_id}/ppap", response_model=Optional[dict])
async def get_ppap(
    revision_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Latest PPAP submission for a revision (null if none)."""
    result = await db.execute(
        select(PPAPSubmission)
        .where(PPAPSubmission.revision_id == revision_id)
        .options(selectinload(PPAPSubmission.elements))
        .order_by(PPAPSubmission.id.desc())
        .limit(1)
    )
    submission = result.scalar_one_or_none()
    return _submission_dict(submission) if submission else None


@router.patch("/ppap/elements/{element_id}", response_model=dict)
async def update_element(
    element_id: int,
    body: ElementUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update one checklist element (status, evidence file, comment)."""
    try:
        result = await db.execute(select(PPAPElement).where(PPAPElement.id == element_id))
        element = result.scalar_one_or_none()
        if not element:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Element not found")

        submission = await _load_submission(db, element.submission_id)
        if submission.status not in ("draft", "submitted"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"PPAP is {submission.status}; elements are read-only",
            )

        if body.status is not None:
            if body.status not in ELEMENT_STATUSES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status. Valid: {', '.join(sorted(ELEMENT_STATUSES))}",
                )
            element.status = body.status
        if body.file_id is not None:
            file_result = await db.execute(
                select(RevisionFile).where(
                    RevisionFile.id == body.file_id,
                    RevisionFile.revision_id == submission.revision_id,
                    RevisionFile.is_deleted == False,  # noqa: E712
                )
            )
            if not file_result.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="file_id must reference a file of the same revision",
                )
            element.file_id = body.file_id
            if element.status == "pending":
                element.status = "attached"
        if body.comment is not None:
            element.comment = body.comment

        await db.commit()
        return _element_dict(element)
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update PPAP element {element_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


async def _transition(
    db: AsyncSession,
    submission_id: int,
    current_user: User,
    new_status: str,
    notes: Optional[str],
) -> dict:
    submission = await _load_submission(db, submission_id)
    revision = await RevisionService.get_revision(db, submission.revision_id)

    if new_status == "submitted":
        if submission.status != "draft":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft PPAPs can be submitted")
        incomplete = [
            e.name for e in submission.elements
            if e.required and e.status not in ("attached", "approved", "na")
        ]
        if incomplete:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Required elements incomplete: {', '.join(incomplete[:5])}"
                + (f" (+{len(incomplete) - 5} more)" if len(incomplete) > 5 else ""),
            )
        submission.submitted_at = datetime.utcnow()
    else:  # approved / rejected
        if submission.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only submitted PPAPs can be approved or rejected",
            )
        submission.decided_at = datetime.utcnow()
        submission.decided_by = current_user.id
        submission.decision_notes = notes

    submission.status = new_status
    await ChangelogService.log_action(
        db,
        part_id=revision.part_id,
        revision_id=revision.id,
        action=f"ppap_{new_status}",
        action_description=f"PPAP level {submission.level} {new_status} for {revision.revision_name}",
        performed_by=current_user.id,
        notes=notes,
    )
    await db.commit()
    return _submission_dict(await _load_submission(db, submission_id))


@router.post("/ppap/{submission_id}/submit", response_model=dict)
async def submit_ppap(
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a draft PPAP (requires all required elements complete)."""
    return await _transition(db, submission_id, current_user, "submitted", None)


@router.post("/ppap/{submission_id}/approve", response_model=dict)
async def approve_ppap(
    submission_id: int,
    body: DecisionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _transition(db, submission_id, current_user, "approved", body.notes)


@router.post("/ppap/{submission_id}/reject", response_model=dict)
async def reject_ppap(
    submission_id: int,
    body: DecisionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _transition(db, submission_id, current_user, "rejected", body.notes)
