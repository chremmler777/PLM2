# backend/app/api/v1/changes/changes.py
"""Change Management endpoints - the change lifecycle spine."""
import hashlib
import logging
import os
import uuid
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.change import ChangeChangelog, ChangeAttachment, ChangeRequest, ChangeAssessment
from app.models.workflow import UserDepartment
from app.services.change_service import ChangeService, ChangeError
from app.schemas.change import (
    ChangeCreate, ChangeUpdate, ChangeResponse, ChangeDetailResponse,
    TransitionRequest, ImpactedItemCreate, ImpactedItemResponse,
    AssessmentSubmit, AssessmentResponse, CustomerResponseRequest, SignOffRequest,
    ChangelogResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/changes", tags=["changes"])


@router.post("", response_model=ChangeResponse)
async def create_change(
    body: ChangeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        change = await ChangeService.create_change(
            session=db, project_id=body.project_id, title=body.title,
            change_type=body.change_type, raised_by=current_user.id,
            reason=body.reason, description=body.description, priority=body.priority,
            lead_id=body.lead_id, data_classification=body.data_classification,
        )
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return change


@router.get("", response_model=List[ChangeResponse])
async def list_changes(
    project_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    change_type: Optional[str] = Query(None),
    lead_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ChangeService.list_changes(
        db, project_id=project_id, status=status, change_type=change_type, lead_id=lead_id,
    )


@router.get("/my-tasks")
async def my_change_tasks(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    # departments the user belongs to
    dep_rows = await db.execute(
        select(UserDepartment.department_id).where(UserDepartment.user_id == current_user.id)
    )
    dep_ids = {r[0] for r in dep_rows.all()}
    tasks = []
    if dep_ids:
        rows = await db.execute(
            select(ChangeAssessment, ChangeRequest)
            .join(ChangeRequest, ChangeRequest.id == ChangeAssessment.change_id)
            .where(
                ChangeAssessment.department_id.in_(dep_ids)
                & (ChangeAssessment.verdict == "pending")
                & (ChangeRequest.status == "in_assessment")
            )
        )
        for a, c in rows.all():
            tasks.append({
                "kind": "assessment", "change_id": c.id, "change_number": c.change_number,
                "title": c.title, "department_id": a.department_id, "assessment_id": a.id,
            })
    return tasks


@router.get("/{change_id}", response_model=ChangeDetailResponse)
async def get_change(
    change_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


@router.get("/{change_id}/changelog", response_model=List[ChangelogResponse])
async def get_changelog(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChangeChangelog).where(ChangeChangelog.change_id == change_id)
        .order_by(ChangeChangelog.performed_at, ChangeChangelog.id)
    )
    return result.scalars().all()


@router.post("/{change_id}/transition", response_model=ChangeResponse)
async def transition_change(
    change_id: int,
    body: TransitionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await ChangeService.transition(
            db, change, body.to_status, current_user.id,
            justification=body.justification, cancellation_reason=body.cancellation_reason,
        )
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return change


@router.post("/{change_id}/impacted-items", response_model=ImpactedItemResponse)
async def add_impacted_item(
    change_id: int, body: ImpactedItemCreate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        item = await ChangeService.add_impacted_item(
            db, change, body.part_id, current_user.id,
            impact_note=body.impact_note, eng_level_before=body.eng_level_before,
        )
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/{change_id}/impacted-items/{item_id}", status_code=204)
async def remove_impacted_item(
    change_id: int, item_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await ChangeService.remove_impacted_item(db, change, item_id, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()


@router.post("/{change_id}/impacted-items/seed")
async def seed_impacted_items(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    added = await ChangeService.seed_impacted_from_relations(db, change, current_user.id)
    await db.commit()
    return {"added": added}


@router.post("/{change_id}/assessments", response_model=AssessmentResponse)
async def submit_assessment(
    change_id: int, body: AssessmentSubmit,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        a = await ChangeService.submit_assessment(
            db, change, body.department_id, body.verdict, current_user.id,
            cost_impact=body.cost_impact, lead_time_impact_days=body.lead_time_impact_days,
            conditions=body.conditions, notes=body.notes, responsible_id=body.responsible_id,
        )
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(a)
    return a


@router.patch("/{change_id}", response_model=ChangeResponse)
async def update_change(
    change_id: int, body: ChangeUpdate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    await ChangeService.update_change(db, change, current_user.id,
                                      **body.model_dump(exclude_unset=True))
    await db.commit()
    await db.refresh(change)
    return change


@router.post("/{change_id}/customer-response", response_model=ChangeResponse)
async def customer_response(
    change_id: int, body: CustomerResponseRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await ChangeService.record_customer_response(db, change, body.response, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return change


@router.post("/{change_id}/sign-off", response_model=ChangeResponse)
async def sign_off(
    change_id: int, body: SignOffRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await ChangeService.sign_off(db, change, body.role, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return change


@router.post("/{change_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    change_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")
    uploads_dir = os.path.join(os.getcwd(), "uploads", "changes", str(change_id))
    os.makedirs(uploads_dir, exist_ok=True)
    safe_name = os.path.basename(file.filename or "attachment.bin")
    stored_path = os.path.join(uploads_dir, f"{uuid.uuid4().hex}_{safe_name}")
    with open(stored_path, "wb") as fh:
        fh.write(contents)
    att = await ChangeService.add_attachment(
        db, change, filename=safe_name, stored_path=stored_path,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(contents), sha256=hashlib.sha256(contents).hexdigest(),
        user_id=current_user.id,
    )
    await db.commit()
    return {"id": att.id, "filename": att.filename, "size_bytes": att.size_bytes}


@router.get("/{change_id}/attachments/{attachment_id}/download")
async def download_attachment(
    change_id: int, attachment_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    att = await db.get(ChangeAttachment, attachment_id)
    if not att or att.change_id != change_id or not os.path.exists(att.stored_path):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(att.stored_path, filename=att.filename,
                        media_type=att.content_type or "application/octet-stream")
