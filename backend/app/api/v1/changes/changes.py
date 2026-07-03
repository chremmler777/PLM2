# backend/app/api/v1/changes/changes.py
"""Change Management endpoints - the change lifecycle spine."""
import hashlib
import logging
import os
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.change import (
    ChangeChangelog, ChangeAttachment, ChangeRequest, ChangeAssessment,
    ChangeImpactedItem,
)
from app.models.workflow import UserDepartment
from app.services.change_service import ChangeService, ChangeError
from app.schemas.change import (
    ChangeCreate, ChangeUpdate, ChangeResponse, ChangeDetailResponse,
    TransitionRequest, ImpactedItemCreate, ImpactedItemResponse,
    AssessmentSubmit, AssessmentResponse, AssessmentAssignIn, AssessmentDueDateIn,
    CustomerResponseRequest, SignOffRequest,
    ChangelogResponse,
    RoutingResponse, RoutingStage, RoutingDepartment, DeviationRequest, RoutingStandardUpsert,
    CostLineReplace, CostLineResponse, SummationResponse,
    GateDecisionIn, GateResponse,
    DeviationProposeIn, DeviationDecideIn, TransitionDeviationResponse,
    CheckStandardIn, CheckStandardResponse,
    ImpactSuggestIn, ImpactSelectionIn,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/changes", tags=["changes"])


def _tier(letter: str) -> str:
    if letter in ("R", "A"):
        return "blocking"
    if letter in ("S", "C"):
        return "optional"
    return "info"


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
    changes = await ChangeService.list_changes(
        db, viewer=current_user, project_id=project_id, status=status,
        change_type=change_type, lead_id=lead_id,
    )
    for change in changes:
        change.deadline_state = await ChangeService.deadline_state(db, change)
    return changes


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
            # Execution state lives on the linked engine task; surface a row only
            # when it is *effectively* active (task active, or an unlinked row
            # carrying its own "active" status from a routing deviation).
            if a.effective_status != "active":
                continue
            tasks.append({
                "kind": "assessment", "change_id": c.id, "change_number": c.change_number,
                "title": c.title, "department_id": a.department_id, "assessment_id": a.id,
                "owner_id": a.effective_owner_id,
                "owner_name": a.effective_owner_name,
                "accepted_at": a.effective_accepted_at,
                "due_date": a.effective_due_date,
                "overdue": a.effective_overdue,
                "mine": a.effective_owner_id == current_user.id,
            })

        tasks.sort(key=lambda d: (
            not d["mine"], not d["overdue"],
            d["due_date"] is None, d["due_date"] or datetime.max, d["assessment_id"]))
    return tasks


@router.get("/my-escalations")
async def my_escalations(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await ChangeService.lead_escalations(db, current_user.id)


@router.get("/routing-standards")
async def list_routing_standards(db: AsyncSession = Depends(get_db),
                                 current_user: User = Depends(get_current_user)):
    from app.models.change import ChangeRoutingStandard
    rows = (await db.execute(select(ChangeRoutingStandard))).scalars().all()
    return [{"change_type": r.change_type, "template_id": r.template_id,
             "template_version": r.template_version} for r in rows]


@router.put("/routing-standards")
async def upsert_routing_standard(body: RoutingStandardUpsert,
                                  db: AsyncSession = Depends(get_db),
                                  current_user: User = Depends(get_current_user)):
    from app.models.change import ChangeRoutingStandard
    row = (await db.execute(select(ChangeRoutingStandard).where(
        ChangeRoutingStandard.change_type == body.change_type))).scalar_one_or_none()
    if row is None:
        row = ChangeRoutingStandard(change_type=body.change_type, template_id=body.template_id,
                                    template_version=body.template_version, updated_by=current_user.id)
        db.add(row)
    else:
        row.template_id = body.template_id
        row.template_version = body.template_version
        row.updated_by = current_user.id
    await db.commit()
    return {"change_type": body.change_type, "template_id": body.template_id,
            "template_version": body.template_version}


@router.get("/check-standards", response_model=List[CheckStandardResponse])
async def list_check_standards(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.models.workflow import CheckWorkflowStandard
    rows = (await db.execute(select(CheckWorkflowStandard))).scalars().all()
    return rows


@router.put("/check-standards", response_model=CheckStandardResponse)
async def put_check_standard(
    body: CheckStandardIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.models.workflow import CheckWorkflowStandard, CHECK_WF_ITEM_CATEGORIES, WfTemplate
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    if body.item_category not in CHECK_WF_ITEM_CATEGORIES:
        raise HTTPException(status_code=400, detail="Unknown item_category")
    tmpl = await db.get(WfTemplate, body.template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    row = (await db.execute(select(CheckWorkflowStandard).where(
        CheckWorkflowStandard.item_category == body.item_category))).scalar_one_or_none()
    if row is None:
        row = CheckWorkflowStandard(item_category=body.item_category,
                                    template_id=tmpl.id)
        db.add(row)
    row.template_id = tmpl.id
    row.template_version = tmpl.version
    row.updated_by = current_user.id
    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/reference/rates")
async def reference_rates(db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    from app.models.change_cost import DepartmentRate
    rows = (await db.execute(select(DepartmentRate))).scalars().all()
    return [{"department_id": r.department_id, "plant_id": r.plant_id,
             "hourly_rate": r.hourly_rate, "min_factor": r.min_factor} for r in rows]


@router.get("/reference/activities")
async def reference_activities(department_id: Optional[int] = Query(None),
                               db: AsyncSession = Depends(get_db),
                               current_user: User = Depends(get_current_user)):
    from app.models.change_cost import AssessmentActivity
    q = select(AssessmentActivity).where(AssessmentActivity.is_active == True)  # noqa: E712
    if department_id is not None:
        q = q.where(AssessmentActivity.department_id == department_id)
    q = q.order_by(AssessmentActivity.sort_order)
    rows = (await db.execute(q)).scalars().all()
    return [{"id": r.id, "department_id": r.department_id, "label": r.label,
             "sort_order": r.sort_order} for r in rows]


@router.get("/{change_id}", response_model=ChangeDetailResponse)
async def get_change(
    change_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    change.deadline_state = await ChangeService.deadline_state(db, change)
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


@router.get("/{change_id}/implementation")
async def get_implementation_progress(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return await ChangeService.implementation_progress(db, change)


@router.get("/{change_id}/routing", response_model=RoutingResponse)
async def get_routing(change_id: int, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    change = await ChangeService.get_change(db, change_id)
    if change is None:
        raise HTTPException(404, "Change not found")
    routing = change.routing
    # Key by (department, stage): departments appear in multiple stages of the
    # seeded templates, and each stage owns its own assessment row.
    assess_by_key = {(a.department_id, a.stage_order): a for a in change.assessments}
    snapshot = routing.standard_snapshot if routing else {"stages": []}
    stages = []
    for st in snapshot.get("stages", []):
        deps = []
        for d in st["departments"]:
            a = assess_by_key.get((d["department_id"], st["stage_order"]))
            deps.append(RoutingDepartment(
                department_id=d["department_id"], rasic_letter=d["rasic_letter"],
                tier=_tier(d["rasic_letter"]),
                # Execution state lives on the linked engine task; read it through.
                status=(a.effective_status if a else None),
                verdict=(a.verdict if a else None),
                assessment_id=(a.id if a else None)))
        stages.append(RoutingStage(stage_order=st["stage_order"], departments=deps))
    return RoutingResponse(
        change_id=change_id,
        template_id=(routing.template_id if routing else None),
        template_version=(routing.template_version if routing else None),
        has_deviation=(routing.has_deviation if routing else False),
        deviation_status=(routing.deviation_status if routing else "none"),
        stages=stages)


@router.post("/{change_id}/routing/deviation", response_model=RoutingResponse)
async def post_deviation(change_id: int, body: DeviationRequest,
                         db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    change = await ChangeService.get_change(db, change_id)
    if change is None:
        raise HTTPException(404, "Change not found")
    from app.services.change_routing_service import ChangeRoutingService
    try:
        await ChangeRoutingService.apply_deviation(
            db, change, current_user.id, op=body.op, department_id=body.department_id,
            rasic_letter=body.rasic_letter, stage_order=body.stage_order)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    return await get_routing(change_id, db, current_user)


@router.post("/{change_id}/routing/deviation/approve", response_model=RoutingResponse)
async def approve_deviation(change_id: int, db: AsyncSession = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    change = await ChangeService.get_change(db, change_id)
    if change is None:
        raise HTTPException(404, "Change not found")
    from app.services.change_routing_service import ChangeRoutingService
    try:
        await ChangeRoutingService.approve_deviation(db, change, current_user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    return await get_routing(change_id, db, current_user)


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
            cancellation_reason=body.cancellation_reason,
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
            is_lead=body.is_lead,
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


@router.get("/{change_id}/impact-tree")
async def get_impact_tree(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return await ChangeService.get_impact_tree(db, change)


@router.post("/{change_id}/impact-tree/suggest")
async def suggest_impact_rollups(
    change_id: int, body: ImpactSuggestIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    suggested = await ChangeService.suggest_rollups(
        db, change.project_id, set(body.part_ids))
    return {"suggested_part_ids": sorted(suggested)}


@router.put("/{change_id}/impacted-items")
async def apply_impact_selection(
    change_id: int, body: ImpactSelectionIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if current_user.role != "admin" and change.lead_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the change lead or an admin may edit the impact selection")
    try:
        await ChangeService.apply_impact_selection(
            db, change, body.part_ids, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    # Read impacted parts fresh: with expire_on_commit=False the cached
    # relationship collection would not reflect the just-applied diff.
    rows = await db.execute(
        select(ChangeImpactedItem.part_id).where(
            ChangeImpactedItem.change_id == change_id))
    return {"impacted_part_ids": sorted(pid for (pid,) in rows)}


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


@router.post("/{change_id}/assessments/{assessment_id}/accept",
             response_model=AssessmentResponse)
async def accept_assessment(
    change_id: int, assessment_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        a = await ChangeService.accept_assessment(db, change, assessment_id, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(a)
    return a


@router.post("/{change_id}/assessments/{assessment_id}/assign",
             response_model=AssessmentResponse)
async def assign_assessment(
    change_id: int, assessment_id: int, body: AssessmentAssignIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        a = await ChangeService.assign_assessment(
            db, change, assessment_id, body.user_id, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(a)
    return a


@router.put("/{change_id}/assessments/{assessment_id}/due-date",
            response_model=AssessmentResponse)
async def set_assessment_due_date(
    change_id: int, assessment_id: int, body: AssessmentDueDateIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        a = await ChangeService.set_assessment_due_date(
            db, change, assessment_id, body.due_date, current_user)
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
    try:
        await ChangeService.update_change(db, change, current_user.id,
                                          **body.model_dump(exclude_unset=True))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    # Evict from identity map so the re-query hits the DB fresh (M2M not cached).
    db.expunge(change)
    result = await db.execute(
        select(ChangeRequest)
        .where(ChangeRequest.id == change_id)
        .options(selectinload(ChangeRequest.affected_plants))
    )
    change = result.scalar_one()
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


@router.get("/{change_id}/assessments/{aid}/cost-lines", response_model=List[CostLineResponse])
async def get_cost_lines(
    change_id: int, aid: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    a = await db.get(ChangeAssessment, aid)
    if not a or a.change_id != change_id:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return a.cost_lines


@router.put("/{change_id}/assessments/{aid}/cost-lines", response_model=List[CostLineResponse])
async def put_cost_lines(
    change_id: int, aid: int, body: CostLineReplace,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.cost_service import CostService, CostError
    change = await ChangeService.get_change(db, change_id)
    a = await db.get(ChangeAssessment, aid)
    if not change or not a or a.change_id != change_id:
        raise HTTPException(status_code=404, detail="Assessment not found")
    try:
        lines = await CostService.replace_cost_lines(
            db, change, a, [l.model_dump() for l in body.lines], current_user.id)
    except CostError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return lines


@router.get("/{change_id}/summation", response_model=SummationResponse)
async def get_summation(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.cost_service import CostService
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return await CostService.summation(db, change)


@router.get("/{change_id}/gates", response_model=List[GateResponse])
async def get_gates(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change.gates


@router.put("/{change_id}/gates/{gate_key}", response_model=GateResponse)
async def put_gate(
    change_id: int, gate_key: str, body: GateDecisionIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if current_user.role != "admin" and change.lead_id != current_user.id:
        raise HTTPException(status_code=403,
                            detail="Only the change lead or an admin may decide gates")
    try:
        gate = await ChangeService.decide_gate(
            db, change, gate_key, body.decision, current_user.id, remark=body.remark)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return gate


@router.get("/{change_id}/deviations", response_model=List[TransitionDeviationResponse])
async def list_deviations(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change.transition_deviations


@router.post("/{change_id}/deviations", response_model=TransitionDeviationResponse)
async def propose_deviation(
    change_id: int, body: DeviationProposeIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        dev = await ChangeService.propose_transition_deviation(
            db, change, body.to_status, body.reason, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return dev


@router.post("/{change_id}/deviations/{dev_id}/decide",
             response_model=TransitionDeviationResponse)
async def decide_deviation(
    change_id: int, dev_id: int, body: DeviationDecideIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        dev = await ChangeService.decide_transition_deviation(
            db, change, dev_id, body.decision, current_user, note=body.note)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return dev
