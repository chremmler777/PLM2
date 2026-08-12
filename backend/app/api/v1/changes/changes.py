# backend/app/api/v1/changes/changes.py
"""Change Management endpoints - the change lifecycle spine."""
import hashlib
import logging
import os
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import (
    APIRouter, Depends, HTTPException, Query, File, Form, UploadFile, status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.change import (
    ChangeChangelog, ChangeAttachment, ChangeRequest, ChangeAssessment,
    ChangeImpactedItem, SIGN_OFF_ROLES,
)
from app.models.workflow import UserDepartment, Department
from app.services.change_service import ChangeService, ChangeError, _org_scope
from app.services.workflow_service import WorkflowService
from app.services.meeting_service import MeetingService
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
    MeetingCreate, MeetingUpdate, MeetingDecideIn, MeetingResponse,
    NegotiationCreate, NegotiationResponse,
    ConcernCreate, ConcernResponse, ConcernWithdrawIn, ConcernAnswerIn,
    CostLeadTimeIn, WeightEstimateIn, BankBuildIn,
    InternalApprovalIn,
    CostingPositionCreate, CostingPositionUpdate, CostingPositionResponse,
    CostingOfferCreate, CostingOfferUpdate, CostingOfferResponse,
    ImplementationBookingCreate, ImplementationBookingResponse,
    ImplementationReportCreate, ImplementationReportResponse,
    ImplementationEscalationCreate, ImplementationEscalationResolveIn,
    ImplementationEscalationResponse, ImplementationStateResponse,
    ValidationCheckIn, ValidationCheckResponse, ValidationStateResponse,
    WeightDeltaAckIn,
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
    if not await ChangeService.user_can_start_change(db, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only an admin or a member of a department allowed to start "
                   "changes (e.g. Sales) may raise a change")
    # The system currently runs the customer (external) change flow only, so
    # the entry point refuses to create internal ones — half-built internal
    # changes stuck mid-flow are worse than not offering them. The SERVICE
    # stays capable: the internal costing/approval path is real, tested
    # functionality waiting on the decision to switch it on.
    if body.customer_relevant is False:
        raise HTTPException(
            status_code=400,
            detail="Internal changes are not enabled yet — this system "
                   "currently runs the customer (external) change flow")
    try:
        change = await ChangeService.create_change(
            session=db, project_id=body.project_id, title=body.title,
            change_type=body.change_type, raised_by=current_user.id,
            reason=body.reason, description=body.description, priority=body.priority,
            lead_id=body.lead_id, data_classification=body.data_classification,
            customer_relevant=body.customer_relevant,
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


@router.get("/permissions")
async def change_permissions(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """What the caller may do in the change module, for gating buttons.

    Answers for the EFFECTIVE actor, so an admin acting as a department sees
    what that department can do — the same answer the endpoints themselves
    will give. Declared before /{change_id} so "permissions" is not eaten as
    a change id (same trap as my-tasks).
    """
    return {
        "can_start_change": await ChangeService.user_can_start_change(db, current_user),
    }


@router.get("/my-tasks")
async def my_change_tasks(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Every open piece of ECR work this caller's role owns — not just pending
    assessments. A change parked in a stage IS the open task of that stage's
    responsible role, so each stage contributes its own row kind:

      kickoff           captured, for a can_start_change department (Sales)
      scoping_wrapup    scoping, for Project Manager — drive it to a decision
      impact_confirm    scoping and unlocked, for Development
      assessment        in_assessment, the department's own pending answer
      obtain_info       ANY open, unanswered needs_info question on a live
                        change — raised by the scoping meeting or by a single
                        department alike — for Sales, who owns the customer
                        relationship. One row per change; answering the
                        question clears it, settling stays with the asker
      send_rejection    rejected and customer-relevant, not yet sent, for
                        Sales — with has_letter saying what is still missing
      costing_input     the change is in costing and this caller's department
                        found it feasible but has priced nothing yet
      create_quote      quoting, for Sales — build the offer out of the
                        costing wrap-up, price it, then send it
      close_question    an ANSWERED question still open, for the department
                        that raised it and always for Project Management —
                        somebody has to say whether the answer settles it
      customer_response quoted and unanswered, for Sales
      bank_build       approved with no bank-build decision yet, for
                       Scheduling — running change or planned scrap, plus the
                       outline of the plan
      publish_plan     approved with a decided but unpublished plan, for
                       Sales, on customer-relevant changes
      progress_report  in_implementation and this caller's implementing
                       department has not reported inside the cadence
                       (REPORT_CADENCE_HOURS) — or has never reported at all
      escalate_risk    in_implementation with an at-risk flag nobody has
                       answered yet, for Sales — customer or internal
      update_quote     the validated part weight missed the estimate and
                       nobody has settled the difference, for Sales — the
                       delta rides on the row

    Departments come from the EFFECTIVE actor, so an admin acting as Sales
    sees Sales' queue rather than everything.
    """
    dep_ids = set(await WorkflowService.effective_department_ids(db, current_user))
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
                "title": c.title,
                "project_id": c.project_id, "project_number": c.project_number,
                "project_name": c.project_name,
                "department_id": a.department_id, "assessment_id": a.id,
                "owner_id": a.effective_owner_id,
                "owner_name": a.effective_owner_name,
                "accepted_at": a.effective_accepted_at,
                "due_date": a.effective_due_date,
                "overdue": a.effective_overdue,
                "mine": a.effective_owner_id == current_user.id,
            })

    # --- stage-responsibility rows --------------------------------------
    async def _base(c) -> dict:
        """Shared shape: identity plus the ACTIVE deadline's context, computed
        by the service so the badge here and the badge on the change agree."""
        kind = c.active_deadline
        due = (c.release_due_date if kind == "release"
               else c.required_by_date if kind == "quote" else None)
        state = await ChangeService.deadline_state(db, c)
        return {
            "change_id": c.id, "change_number": c.change_number, "title": c.title,
            "project_id": c.project_id, "project_number": c.project_number,
            "project_name": c.project_name,
            "due_date": due, "overdue": state == "overdue",
        }

    # Every change that can still need something done to it. Not simply
    # "not terminal": 'rejected' counts as terminal for the flow, but a
    # rejected customer change still owes the customer a letter (send_rejection
    # below). Closed, released and cancelled owe nobody anything.
    open_changes = (await db.execute(_org_scope(
        select(ChangeRequest).where(
            ChangeRequest.status.not_in(("released", "closed", "cancelled"))),
        current_user,
    ))).scalars().all()

    can_capture = await ChangeService.user_can_start_change(db, current_user)
    is_pm = await MeetingService.user_is_pm(db, current_user)
    # Settling a concern has no admin shortcut, so the task that asks for it
    # follows membership too (MeetingService.user_is_pm_member).
    is_pm_member = await MeetingService.user_is_pm_member(db, current_user)
    can_confirm = await ChangeService.user_can_confirm_impact(db, current_user)
    in_sales = await ChangeService._user_in_department(db, current_user, "Sales")
    in_scheduling = await ChangeService._user_in_department(
        db, current_user, ChangeService.SCHEDULING_DEPARTMENT)

    for c in open_changes:
        if c.status == "captured" and can_capture:
            tasks.append({**await _base(c), "kind": "kickoff",
                          "missing": await ChangeService.kickoff_missing(db, c)})
        elif c.status == "scoping":
            if is_pm:
                tasks.append({
                    **await _base(c), "kind": "scoping_wrapup",
                    "impact_confirmed": c.impact_confirmed_at is not None,
                    "has_decision": any(m.decision in ("proceed", "reject")
                                        for m in c.meetings),
                })
            if can_confirm and c.impact_confirmed_at is None:
                tasks.append({**await _base(c), "kind": "impact_confirm"})

        elif (c.status == "rejected" and in_sales and c.customer_relevant
                and c.rejection_sent_at is None):
            tasks.append({
                **await _base(c), "kind": "send_rejection",
                # Tells the UI which half of the job is left: write the
                # explanation, or confirm it went out.
                "has_letter": await ChangeService.has_rejection_letter(db, c),
            })
        # The quoting stage IS Sales' open task: costing is wrapped up and the
        # offer has to be written from it. has_price says which half is left —
        # put a number on it, then send it (-> quoted).
        elif c.status == "quoting" and in_sales and c.customer_relevant:
            tasks.append({
                **await _base(c), "kind": "create_quote",
                "has_price": c.quoted_price is not None,
            })
        elif (c.status == "quoted" and in_sales and c.customer_relevant
                and c.customer_response in (None, "pending")):
            tasks.append({**await _base(c), "kind": "customer_response"})

        # The scheduling block. Acceptance leaves two errands in sequence:
        # Scheduling decides how the change reaches the line, then Sales tells
        # the customer what was planned. Neither is a transition gate — the
        # row IS the pressure.
        elif c.status == "approved":
            if in_scheduling and c.bank_build_mode is None:
                tasks.append({
                    **await _base(c), "kind": "bank_build",
                    "hint": "Decide running change vs planned scrap and "
                            "outline the plan",
                })
            if (in_sales and c.customer_relevant
                    and c.bank_build_mode is not None
                    and c.plan_published_at is None):
                tasks.append({
                    **await _base(c), "kind": "publish_plan",
                    "mode": c.bank_build_mode,
                    "scrap_quote_price": c.scrap_quote_price,
                })

        # Costing is a queue too: a department that called the change feasible
        # owes a number, and "no lines at all" is silence rather than a zero.
        if c.status == "costing" and dep_ids:
            pending = await ChangeService.costing_pending_department_ids(db, c)
            for dept_id in sorted(set(pending) & dep_ids):
                tasks.append({
                    **await _base(c), "kind": "costing_input",
                    "department_id": dept_id,
                })

        # Stage 8 is a cadence, not a milestone: while the change is being
        # implemented, every implementing department owes a progress report
        # at least twice a week, and a flag raised in one of those reports is
        # Sales' errand until they take it somewhere.
        if c.status == "in_implementation":
            from app.services.implementation_service import ImplementationService
            impl = await ImplementationService.state(db, c, current_user)
            for row in impl["departments"]:
                if row["owes_report"] and row["department_id"] in dep_ids:
                    tasks.append({
                        **await _base(c), "kind": "progress_report",
                        "department_id": row["department_id"],
                        "last_report_at": row["last_report_at"],
                        "hint": "Report progress at least twice a week",
                    })
            # "No unresolved escalation for it yet" needs no separate check:
            # at_risk_open is already false once ANY escalation (open or
            # resolved) answers the flag, so a row here means nobody has taken
            # this risk anywhere.
            flagged = [row["department_id"] for row in impl["departments"]
                       if row["at_risk_open"]]
            if in_sales and flagged:
                tasks.append({
                    **await _base(c), "kind": "escalate_risk",
                    "department_ids": flagged,
                    "hint": "Take it to the customer, or escalate internally",
                })

        # Stage 9's one commercial errand: the sampled part came off the scale
        # at a different weight than the quote was built on. Not tied to a
        # status — the delta stays owed whether the change is still validating
        # or went back round to implementation — and cleared by the explicit
        # acknowledgement (POST /validation/weight-ack), never by guessing at a
        # quoted_price edit that may have happened for another reason.
        if in_sales:
            from app.services.validation_service import ValidationService
            if ValidationService.weight_delta_open(c):
                delta = ValidationService.weight_delta(c)
                tasks.append({
                    **await _base(c), "kind": "update_quote",
                    "delta_g": delta,
                    "estimated_part_weight_g": c.estimated_part_weight_g,
                    "validated_part_weight_g": c.validated_part_weight_g,
                    "hint": f"Validated part weight is {delta:+g} g against the "
                            "estimate — update the quote or record the decision",
                })

        # Independent of the stage chain: a question can be waiting on Sales at
        # any live status, and it is one errand per change however many people
        # asked. Cleared per question by answering it.
        if in_sales:
            questions = ChangeService.unanswered_questions(c)
            if questions:
                newest = questions[-1]
                tasks.append({
                    **await _base(c), "kind": "obtain_info",
                    "reason": newest.note,
                    "question_count": len(questions),
                    "concern_id": newest.id,
                    "department_id": newest.department_id,
                })

        # The other half of the same loop: an answer is waiting on the side
        # that asked. Addressed to the department that raised it (any member —
        # the flag is the department's), and always to Project Management, the
        # standing arbiter who can settle either kind. An answered question
        # nobody is told to review stalls exactly like an unanswered one.
        answered = ChangeService.answered_questions(c)
        if answered:
            mine = [q for q in answered
                    if is_pm_member
                    or (q.department_id is not None and q.department_id in dep_ids)]
            if mine:
                newest = mine[-1]
                tasks.append({
                    **await _base(c), "kind": "close_question",
                    "reason": newest.answer_note,
                    "question_count": len(mine),
                    "concern_id": newest.id,
                    "department_id": newest.department_id,
                    "question_note": newest.note,
                })

    # One order across every kind: overdue first, then soonest due (undated
    # last), then change number. Assessment rows keep "mine" as the top tie
    # break — an answer you already accepted outranks one you have not.
    tasks.sort(key=lambda d: (
        not d.get("mine", False), not d["overdue"],
        d["due_date"] is None, d["due_date"] or datetime.max, d["change_number"]))
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


@router.get("/reference/assessment-checklist")
async def reference_assessment_checklist(
    department_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The questions a department answers at assessment.

    Config, not data (app/services/assessment_checklist.py) — served so the
    frontend renders the same list the backend validates against, instead of
    keeping its own copy that drifts.
    """
    from app.services import assessment_checklist as checklist
    name = None
    if department_id is not None:
        dept = await db.get(Department, department_id)
        name = dept.name if dept is not None else None
    return checklist.items_for(name)


@router.get("/reference/risk-types")
async def reference_risk_types(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The vocabulary a risk concern is typed with.

    Same reasoning as the checklist above: the list lives in
    app/models/change.py because that is what the raise endpoint validates
    against, so the frontend is served it rather than keeping its own copy.
    Shaped as objects so a label can be added later without a breaking change.
    """
    from app.models.change import RISK_TYPES
    return {"items": [{"key": k} for k in RISK_TYPES]}


@router.get("/reference/costing-tags")
async def reference_costing_tags(
    department_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Suggested tags for a costing position.

    Suggestions, not a vocabulary: CostingPosition.tag is free text and the
    write endpoints accept anything. The list exists so the common cases are
    one click and positions stay countable across changes — see
    app/services/costing_tags.py, where it is reviewed in a diff rather than
    edited per department in the database.
    """
    from app.services import costing_tags
    name = None
    if department_id is not None:
        dept = await db.get(Department, department_id)
        name = dept.name if dept is not None else None
    return {"items": costing_tags.tags_for(name)}


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
    change.costing_pending_department_ids = (
        await ChangeService.costing_pending_department_ids(db, change))
    evidence = await ChangeService.assessment_evidence_state(db, change)
    for a in change.assessments:
        state = evidence.get(a.id, {})
        a.has_evidence = state.get("has_evidence", False)
        a.has_change_ppt = state.get("has_change_ppt", False)
        a.has_rfq = state.get("has_rfq", False)
        a.rfq_expected = state.get("rfq_expected", False)
    return change


@router.get("/{change_id}/my-actions")
async def get_my_actions(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Task 19: 'Your actions' — the current user's open, actionable items on
    this one change, plus their department memberships (so the frontend can
    grey out actions that belong to someone else's department)."""
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    actions = await ChangeService.my_actions(db, change, current_user)
    memberships = await WorkflowService.effective_department_ids(db, current_user)
    return {"actions": actions, "memberships": memberships}


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


@router.get("/{change_id}/recommended-departments")
async def recommended_departments(
    change_id: int, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Departments to pre-mark in the scoping decision: the Responsible/
    Accountable assessors of the change type's stage-1 routing. The lead can
    then narrow the fan-out to those relevant for this specific change."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import BLOCKING_LETTERS
    from app.models.workflow import Department
    change = await ChangeService.get_change(db, change_id)
    if change is None:
        raise HTTPException(404, "Change not found")
    try:
        _, _, stages = await ChangeRoutingService.resolve_standard(db, change.change_type)
    except ChangeError:
        return []
    stage1 = next((s for s in stages if s["stage_order"] == 1), None)
    if not stage1:
        return []
    rec = {d["department_id"] for d in stage1["departments"]
           if d["rasic_letter"] in BLOCKING_LETTERS}
    if not rec:
        return []
    rows = (await db.execute(
        select(Department.id, Department.name)
        .where(Department.id.in_(rec), Department.is_active.is_(True))
        .order_by(Department.sort_order, Department.name))).all()
    return [{"id": i, "name": n} for i, n in rows]


@router.get("/{change_id}/assessment-objects")
async def assessment_objects(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """What each routed department is actually being asked to assess.

    Derived from the impacted set through the existing part relations — the
    tools that produce the impacted articles, the equipment that assembles
    them, the gauges that check them — so nobody re-lists what the data
    already knows. No cost fields: cost belongs to the costing phase.
    """
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return {"departments": await ChangeService.assessment_objects(db, change)}


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
    # The quote stage is Sales' own: starting the offer and declaring it sent
    # are both statements about the customer relationship, and nobody else is
    # in a position to make them. Enforced here, like every other role gate in
    # this module, so the service stays callable by the flows that drive
    # transitions internally.
    if ((change.status, body.to_status) in ChangeService.QUOTE_STAGE_TRANSITIONS
            and not await ChangeService.user_can_run_quote_stage(
                db, current_user, change)):
        raise HTTPException(
            status_code=403,
            detail="Only a Sales department member, the change lead or an "
                   "admin may create and send the quote")
    # Sending a change back out of validation replans the timing and reopens
    # the commercial terms — PM owns the first, Sales the second. A department
    # whose own check failed says so on the check; it does not get to move the
    # whole change on its own.
    if change.status == "in_validation" and body.to_status == "in_implementation":
        from app.services.validation_service import ValidationService
        if not await ValidationService.may_escalate(db, change, current_user):
            raise HTTPException(
                status_code=403,
                detail="Only Project Management, Sales, the change lead or an "
                       "admin may send a change back from validation to "
                       "implementation")
    try:
        await ChangeService.transition(
            db, change, body.to_status, current_user.id,
            cancellation_reason=body.cancellation_reason,
            rejection_reason=body.rejection_reason,
            reopen_reason=body.reopen_reason,
            reason=body.reason or body.escalation_reason,
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
    if current_user.effective_role != "admin" and change.lead_id != current_user.id:
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


@router.post("/{change_id}/impact/confirm", response_model=ChangeResponse)
async def confirm_impact(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Task 18: Development confirms the lead-proposed impacted-item set.
    Development membership only — an admin does it via acts-as."""
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if not await ChangeService.user_can_confirm_impact(db, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only a Development department member may confirm impact "
                   "(admins: act as Development)")
    if not change.impacted_items:
        raise HTTPException(status_code=409, detail="No impacted items to confirm")
    try:
        await ChangeService.confirm_impact(db, change, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    change.deadline_state = await ChangeService.deadline_state(db, change)
    return change


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
            effort_hours=body.effort_hours, details=body.details,
        )
    except ValueError as e:
        # Blocking (R/A) submissions delegate to WorkflowService.complete_task,
        # which raises plain ValueError (not ChangeError) for its gates —
        # e.g. the department-membership guard. Catch broadly so those map to
        # 400 instead of leaking as an unhandled 500. ChangeError is itself a
        # ValueError subclass, so existing behaviour is unchanged.
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
    fields = body.model_dump(exclude_unset=True)
    if "quoted_price" in fields and fields["quoted_price"] != change.quoted_price:
        if not await ChangeService.user_can_set_quoted_price(db, current_user, change):
            raise HTTPException(
                status_code=403,
                detail="Only the change lead, a Sales department member, or "
                       "an admin may set the quoted price")
    try:
        await ChangeService.update_change(db, change, current_user.id, **fields)
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
    change.deadline_state = await ChangeService.deadline_state(db, change)
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
        await ChangeService.record_customer_response(
            db, change, body.response, current_user.id,
            release_due_date=body.release_due_date,
            release_due_reason=body.release_due_reason)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return change


@router.post("/{change_id}/rejection-sent", response_model=ChangeResponse)
async def confirm_rejection_sent(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Sales confirms the rejection reached the customer — the last open step
    of a rejection — which also closes the change.

    Sales membership only, no plain-admin shortcut: whoever owns the customer
    relationship is the only one who can honestly say it was sent. An admin
    does it through acts-as.
    """
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if not await ChangeService._user_in_department(db, current_user, "Sales"):
        raise HTTPException(
            status_code=403,
            detail="Only a Sales department member may confirm the rejection "
                   "was sent (admins: act as Sales)")
    try:
        await ChangeService.confirm_rejection_sent(db, change, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    change.deadline_state = await ChangeService.deadline_state(db, change)
    return change


@router.post("/{change_id}/sign-off", response_model=ChangeResponse)
async def sign_off(
    change_id: int, body: SignOffRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if body.role in SIGN_OFF_ROLES and not await ChangeService.user_can_sign_off(
            db, current_user, body.role):
        dept_name = "Quality" if body.role == "quality" else "Project Manager"
        raise HTTPException(
            status_code=403,
            detail=f"Only a {dept_name} department member or an admin may "
                   f"sign off as {body.role}")
    try:
        await ChangeService.sign_off(db, change, body.role, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return change


@router.post("/{change_id}/internal-approval", response_model=ChangeResponse)
async def approve_internal_costs(
    change_id: int, body: InternalApprovalIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if not await ChangeService.user_can_approve_internal_costs(db, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only a Project Manager department member or an admin "
                   "may approve internal costs")
    try:
        await ChangeService.approve_internal_costs(
            db, change, current_user, note=body.note,
            release_due_date=body.release_due_date,
            release_due_reason=body.release_due_reason)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    change.deadline_state = await ChangeService.deadline_state(db, change)
    return change


@router.put("/{change_id}/weight-estimate", response_model=ChangeResponse)
async def put_weight_estimate(
    change_id: int, body: WeightEstimateIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """The Tooling Engineer quotes the part weight during costing.

    An estimate, and flagged as one everywhere it is shown: the tool has not
    been reworked yet. Validation weighs the sampled part and Sales prices the
    delta into a quote update. Editable — re-stating it overwrites, with the
    previous value kept in the changelog.
    """
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if not await ChangeService.user_can_quote_part_weight(db, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only a Tool Engineer department member or an admin may "
                   "quote the part weight")
    try:
        await ChangeService.set_weight_estimate(
            db, change, body.weight_g, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    change.deadline_state = await ChangeService.deadline_state(db, change)
    return change


@router.put("/{change_id}/bank-build", response_model=ChangeResponse)
async def put_bank_build(
    change_id: int, body: BankBuildIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """The scheduling block: how the accepted change reaches the line.

    Running change (consume the bank) or planned scrap (throw it away) — and
    scrap is the customer's cost, so that half only exists with an additional
    scrap quote behind it. Re-deciding overwrites; the changelog keeps every
    round.
    """
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if not await ChangeService.user_can_decide_bank_build(db, current_user, change):
        raise HTTPException(
            status_code=403,
            detail="Only a Scheduling or Project Manager department member, "
                   "the change lead, or an admin may decide the bank build")
    try:
        await ChangeService.set_bank_build(
            db, change, body.mode, current_user, note=body.note,
            scrap_quote_price=body.scrap_quote_price)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    change.deadline_state = await ChangeService.deadline_state(db, change)
    return change


@router.post("/{change_id}/bank-build/publish", response_model=ChangeResponse)
async def publish_bank_build(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Sales puts the bank-build plan in front of the customer.

    Requires a decided plan. Republishing refreshes the stamp — the customer
    got a newer plan — and every publication is in the changelog.
    """
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if not await ChangeService.user_can_publish_bank_build(db, current_user, change):
        raise HTTPException(
            status_code=403,
            detail="Only a Sales department member, the change lead, or an "
                   "admin may publish the plan to the customer")
    try:
        await ChangeService.publish_bank_build_plan(db, change, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    change.deadline_state = await ChangeService.deadline_state(db, change)
    return change


@router.post("/{change_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    change_id: int,
    file: UploadFile = File(...),
    # Multipart, so the classification rides as form fields alongside the file.
    kind: str = Form("general"),
    responds_to_id: Optional[int] = Form(None),
    # Files the document into one concern's container (any authenticated user
    # may add to an open concern: the asker explains, Sales answers).
    concern_id: Optional[int] = Form(None),
    # Evidence for one department's assessment. Mutually exclusive with
    # concern_id — a document belongs to one container.
    assessment_id: Optional[int] = Form(None),
    # The vendor offer this document IS (kind='vendor_quote'). Third container,
    # exclusive with the other two; written by whoever may write the position.
    costing_offer_id: Optional[int] = Form(None),
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
    try:
        att = await ChangeService.add_attachment(
            db, change, filename=safe_name, stored_path=stored_path,
            content_type=file.content_type or "application/octet-stream",
            size_bytes=len(contents), sha256=hashlib.sha256(contents).hexdigest(),
            user_id=current_user.id, kind=kind, responds_to_id=responds_to_id,
            concern_id=concern_id, assessment_id=assessment_id,
            costing_offer_id=costing_offer_id, actor=current_user,
        )
    except ChangeError as e:
        os.remove(stored_path)      # do not leave an orphan on a rejected upload
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return {"id": att.id, "filename": att.filename, "size_bytes": att.size_bytes,
            "kind": att.kind, "responds_to_id": att.responds_to_id,
            "concern_id": att.concern_id, "assessment_id": att.assessment_id,
            "costing_offer_id": att.costing_offer_id}


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


@router.delete("/{change_id}/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    change_id: int, attachment_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    att = await db.get(ChangeAttachment, attachment_id)
    if not att or att.change_id != change_id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    # Baseline documents freeze once scoping ends — the record a decision was
    # made on can't be removed afterwards (VDA/IATF traceability).
    from app.models.change import SCOPING_STATUSES
    if att.phase == "baseline" and change.status not in SCOPING_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Baseline documents are frozen once scoping ends and cannot be deleted.")
    stored_path = await ChangeService.delete_attachment(db, change, att, current_user.id)
    await db.commit()
    if stored_path and os.path.exists(stored_path):
        try:
            os.remove(stored_path)
        except OSError:
            pass


@router.get("/{change_id}/assessments/{aid}/cost-lines", response_model=List[CostLineResponse])
async def get_cost_lines(
    change_id: int, aid: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """The department's cost grid, seeded from its own assessment checklist on
    first view.

    Seeding lazily here rather than on the -> costing transition means it also
    reaches changes that were already in costing, and a department that
    answered its checklist late still gets its grid. It happens once per
    assessment (recorded in details.cost_seeded_at), so nothing duplicates and
    a deleted line stays deleted.
    """
    from app.services.cost_service import CostService
    a = await db.get(ChangeAssessment, aid)
    if not a or a.change_id != change_id:
        raise HTTPException(status_code=404, detail="Assessment not found")
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if change is not None and await CostService.seed_from_checklist(
            db, change, a, current_user.id):
        await db.commit()
        await db.refresh(a, ["cost_lines"])
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


# --- costing positions ------------------------------------------------------
# The other half of costing: what hours × rate cannot express. Permissions
# mirror the cost grid — the department writes its own rows while the change is
# in costing, PM and admins write anyone's, and the people accountable for the
# change as a whole read everything.

async def _costing_change(db: AsyncSession, change_id: int, current_user: User):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


async def _require_costing_write(db: AsyncSession, change, department_id: int,
                                 current_user: User) -> None:
    from app.services.costing_position_service import CostingPositionService
    if not await CostingPositionService.may_write(
            db, change, department_id, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only a member of that department while the change is in "
                   "costing, Project Management or an admin may change its "
                   "costing positions")


@router.get("/{change_id}/costing/positions",
            response_model=List[CostingPositionResponse])
async def list_costing_positions(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Every costing position this caller may see, with its vendor offers and
    the quote documents filed against them."""
    from app.services.costing_position_service import CostingPositionService
    change = await _costing_change(db, change_id, current_user)
    visible = await CostingPositionService.readable_department_ids(
        db, change, current_user)
    rows = await CostingPositionService.list_positions(db, change, visible)
    return await CostingPositionService.serialize(db, rows)


@router.post("/{change_id}/costing/positions",
             response_model=CostingPositionResponse,
             status_code=status.HTTP_201_CREATED)
async def create_costing_position(
    change_id: int, body: CostingPositionCreate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.costing_position_service import (
        CostingPositionError, CostingPositionService,
    )
    change = await _costing_change(db, change_id, current_user)
    await _require_costing_write(db, change, body.department_id, current_user)
    try:
        position = await CostingPositionService.create_position(
            db, change, body.model_dump(), current_user)
    except CostingPositionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(position)
    return (await CostingPositionService.serialize(db, [position]))[0]


@router.put("/{change_id}/costing/positions/{pid}",
            response_model=CostingPositionResponse)
async def update_costing_position(
    change_id: int, pid: int, body: CostingPositionUpdate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.costing_position_service import (
        CostingPositionError, CostingPositionService,
    )
    change = await _costing_change(db, change_id, current_user)
    try:
        position = await CostingPositionService.get_position(db, change, pid)
    except CostingPositionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await _require_costing_write(db, change, position.department_id, current_user)
    try:
        position = await CostingPositionService.update_position(
            db, change, position, body.model_dump(exclude_unset=True),
            current_user)
    except CostingPositionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(position)
    return (await CostingPositionService.serialize(db, [position]))[0]


@router.delete("/{change_id}/costing/positions/{pid}", status_code=204)
async def delete_costing_position(
    change_id: int, pid: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.costing_position_service import (
        CostingPositionError, CostingPositionService,
    )
    change = await _costing_change(db, change_id, current_user)
    try:
        position = await CostingPositionService.get_position(db, change, pid)
    except CostingPositionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await _require_costing_write(db, change, position.department_id, current_user)
    paths = await CostingPositionService.delete_position(
        db, change, position, current_user)
    await db.commit()
    _unlink_all(paths)


@router.post("/{change_id}/costing/positions/{pid}/offers",
             response_model=CostingOfferResponse,
             status_code=status.HTTP_201_CREATED)
async def create_costing_offer(
    change_id: int, pid: int, body: CostingOfferCreate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.costing_position_service import (
        CostingPositionError, CostingPositionService,
    )
    change = await _costing_change(db, change_id, current_user)
    try:
        position = await CostingPositionService.get_position(db, change, pid)
    except CostingPositionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await _require_costing_write(db, change, position.department_id, current_user)
    try:
        offer = await CostingPositionService.create_offer(
            db, change, position, body.model_dump(), current_user)
    except CostingPositionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(position)
    return _offer_row(
        (await CostingPositionService.serialize(db, [position]))[0], offer.id)


@router.put("/{change_id}/costing/offers/{oid}",
            response_model=CostingOfferResponse)
async def update_costing_offer(
    change_id: int, oid: int, body: CostingOfferUpdate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.costing_position_service import (
        CostingPositionError, CostingPositionService,
    )
    change = await _costing_change(db, change_id, current_user)
    try:
        offer = await CostingPositionService.get_offer(db, change, oid)
        position = await CostingPositionService.get_position(
            db, change, offer.position_id)
    except CostingPositionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await _require_costing_write(db, change, position.department_id, current_user)
    try:
        offer = await CostingPositionService.update_offer(
            db, change, offer, body.model_dump(exclude_unset=True), current_user)
    except CostingPositionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(position)
    return _offer_row(
        (await CostingPositionService.serialize(db, [position]))[0], offer.id)


@router.delete("/{change_id}/costing/offers/{oid}", status_code=204)
async def delete_costing_offer(
    change_id: int, oid: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.costing_position_service import (
        CostingPositionError, CostingPositionService,
    )
    change = await _costing_change(db, change_id, current_user)
    try:
        offer = await CostingPositionService.get_offer(db, change, oid)
        position = await CostingPositionService.get_position(
            db, change, offer.position_id)
    except CostingPositionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await _require_costing_write(db, change, position.department_id, current_user)
    paths = await CostingPositionService.delete_offer(
        db, change, offer, current_user)
    await db.commit()
    _unlink_all(paths)


def _offer_row(position_payload: dict, offer_id: int) -> dict:
    """The one offer out of a serialized position — so a single-offer response
    carries the same shape (attachments included) the list endpoint gives."""
    for offer in position_payload["offers"]:
        if offer["id"] == offer_id:
            return offer
    raise HTTPException(status_code=404, detail="Offer not found")


def _unlink_all(paths: List[str]) -> None:
    """Files whose only container is gone. Best effort: a missing file must not
    fail a delete that already committed."""
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


@router.post("/{change_id}/cost-lead-time", response_model=AssessmentResponse)
async def set_cost_lead_time(
    change_id: int, body: CostLeadTimeIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """How many days this department's work adds to the timeline."""
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        a = await ChangeService.set_cost_lead_time(
            db, change, body.department_id, body.lead_time_days, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(a)
    return a


@router.get("/{change_id}/summation", response_model=SummationResponse)
async def get_summation(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.cost_service import CostService
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return await CostService.summation(db, change)


@router.get("/{change_id}/gates", response_model=List[GateResponse])
async def get_gates(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
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
    if current_user.effective_role != "admin" and change.lead_id != current_user.id:
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


@router.get("/{change_id}/meetings", response_model=List[MeetingResponse])
async def list_meetings(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change.meetings


@router.post("/{change_id}/meetings", response_model=MeetingResponse)
async def create_meeting(
    change_id: int, body: MeetingCreate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        meeting = await MeetingService.create_meeting(
            db, change, current_user, meeting_date=body.meeting_date,
            participants=[p.model_dump() for p in body.participants],
            notes=body.notes, selected_department_ids=body.selected_department_ids,
            channel=body.channel)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(meeting)
    return meeting


@router.patch("/{change_id}/meetings/{meeting_id}", response_model=MeetingResponse)
async def update_meeting(
    change_id: int, meeting_id: int, body: MeetingUpdate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    fields = body.model_dump(exclude_unset=True)
    if "participants" in fields and fields["participants"] is not None:
        fields["participants"] = [
            p if isinstance(p, dict) else p.model_dump() for p in fields["participants"]]
    try:
        meeting = await MeetingService.update_meeting(
            db, change, meeting_id, current_user, **fields)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(meeting)
    return meeting


# --- the negotiation loop at 'quoted' ---------------------------------------
# The quote is out; what comes back is a sequence of rounds ending in one final
# result. Sales' go-ahead (the existing acceptance mechanics, with its
# mandatory release deadline) is decided on that result and stays where it is.

@router.get("/{change_id}/negotiations", response_model=List[NegotiationResponse])
async def list_negotiations(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Every recorded round. Commercial read: admin, the change lead, Project
    Management, Sales — the crowd that sees the costing numbers."""
    from app.services.negotiation_service import NegotiationService
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if not await NegotiationService.may_read(db, change, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only Sales, Project Management, the change lead or an "
                   "admin may see the negotiation record")
    return await NegotiationService.list_rounds(db, change)


@router.post("/{change_id}/negotiations", response_model=NegotiationResponse,
             status_code=status.HTTP_201_CREATED)
async def record_negotiation(
    change_id: int, body: NegotiationCreate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.negotiation_service import NegotiationService
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if not await NegotiationService.may_write(db, change, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only Sales, the change lead or an admin may record a "
                   "negotiation round")
    try:
        row = await NegotiationService.record_round(
            db, change, current_user, channel=body.channel, note=body.note,
            counter_price=body.counter_price, is_final=body.is_final)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{change_id}/negotiations/{nid}", status_code=204)
async def delete_negotiation(
    change_id: int, nid: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.negotiation_service import NegotiationService
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        row = await NegotiationService.get_round(db, change, nid)
    except ChangeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not NegotiationService.may_delete(row, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only the author of a negotiation round or an admin may "
                   "remove it")
    try:
        await NegotiationService.delete_round(db, change, row, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()


@router.get("/{change_id}/concerns", response_model=List[ConcernResponse])
async def list_concerns(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change.concerns


@router.post("/{change_id}/concerns", response_model=ConcernResponse)
async def raise_concern(
    change_id: int, body: ConcernCreate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        concern = await MeetingService.raise_concern(
            db, change, current_user, body.kind, body.note,
            department_id=body.department_id,
            risk_type=body.risk_type, severity=body.severity)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(concern)
    return concern


async def _withdraw_concern(
    change_id: int, concern_id: int, resolution_note: Optional[str],
    current_user: User, db: AsyncSession,
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        concern = await MeetingService.withdraw_concern(
            db, change, concern_id, current_user, resolution_note=resolution_note)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(concern)
    return concern


@router.post("/{change_id}/concerns/{concern_id}/answer",
             response_model=ConcernResponse)
async def answer_concern(
    change_id: int, concern_id: int, body: ConcernAnswerIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Sales answers an open question. The concern stays OPEN — the side that
    asked decides whether the answer settles it (POST .../withdraw)."""
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        concern = await MeetingService.answer_concern(
            db, change, concern_id, current_user, note=body.note)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(concern)
    return concern


@router.post("/{change_id}/concerns/{concern_id}/withdraw",
             response_model=ConcernResponse)
async def withdraw_concern_with_note(
    change_id: int, concern_id: int, body: ConcernWithdrawIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Withdraw a concern. Department-scoped (assessment-phase) concerns must
    carry a resolution_note; DELETE below stays for note-less scoping ones."""
    return await _withdraw_concern(
        change_id, concern_id, body.resolution_note, current_user, db)


@router.delete("/{change_id}/concerns/{concern_id}", response_model=ConcernResponse)
async def withdraw_concern(
    change_id: int, concern_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Back-compat: note-less withdrawal. Rejected (400) for department-scoped
    concerns — use POST .../withdraw with a resolution_note."""
    return await _withdraw_concern(
        change_id, concern_id, None, current_user, db)


@router.post("/{change_id}/meetings/{meeting_id}/decide", response_model=MeetingResponse)
async def decide_meeting(
    change_id: int, meeting_id: int, body: MeetingDecideIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        meeting = await MeetingService.decide_meeting(
            db, change, meeting_id, body.decision, current_user,
            reason=body.reason)
    except ValueError as e:
        # transition side effects raise ChangeError (a ValueError subclass);
        # WorkflowService kick-off gates raise plain ValueError.
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(meeting)
    return meeting


# --- stage 8: implementation tracking ---------------------------------------
# Bookings and reports follow the costing scoping rules with the status window
# moved to 'in_implementation': a department writes its own while the change is
# in the stage, PM and admins write anyone's, and the people accountable for
# the change as a whole read everything. Escalations are Sales' — the customer
# relationship has one owner.

async def _implementation_change(db: AsyncSession, change_id: int,
                                 current_user: User):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


async def _require_implementation_write(db: AsyncSession, change,
                                        department_id: int,
                                        current_user: User) -> None:
    from app.services.implementation_service import ImplementationService
    if not await ImplementationService.may_write(
            db, change, department_id, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only a member of that department while the change is in "
                   "implementation, Project Management or an admin may book "
                   "time or report progress for it")


async def _require_escalation_right(db: AsyncSession, change,
                                    current_user: User) -> None:
    from app.services.implementation_service import ImplementationService
    if not await ImplementationService.may_escalate(db, change, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only Sales, the change lead or an admin may escalate an "
                   "implementation risk — the customer relationship has one "
                   "owner")


@router.get("/{change_id}/implementation/state",
            response_model=ImplementationStateResponse)
async def implementation_state(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Per implementing department: booked hours, report cadence, risk.

    "Implementing" is derived — the departments that put a costing position or
    a cost line on this change. The booked-hours totals live here because the
    actuals P&L at validation reads exactly them.
    """
    from app.services.implementation_service import ImplementationService
    change = await _implementation_change(db, change_id, current_user)
    return await ImplementationService.state(db, change, current_user)


@router.get("/{change_id}/implementation/bookings",
            response_model=List[ImplementationBookingResponse])
async def list_implementation_bookings(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.implementation_service import ImplementationService
    change = await _implementation_change(db, change_id, current_user)
    visible = await ImplementationService.readable_department_ids(
        db, change, current_user)
    rows = await ImplementationService.list_bookings(db, change, visible)
    return await ImplementationService.serialize_bookings(db, rows)


@router.post("/{change_id}/implementation/bookings",
             response_model=ImplementationBookingResponse,
             status_code=status.HTTP_201_CREATED)
async def create_implementation_booking(
    change_id: int, body: ImplementationBookingCreate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.implementation_service import (
        ImplementationError, ImplementationService,
    )
    change = await _implementation_change(db, change_id, current_user)
    await _require_implementation_write(
        db, change, body.department_id, current_user)
    try:
        booking = await ImplementationService.create_booking(
            db, change, body.model_dump(), current_user)
    except ImplementationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(booking)
    return (await ImplementationService.serialize_bookings(db, [booking]))[0]


@router.delete("/{change_id}/implementation/bookings/{bid}", status_code=204)
async def delete_implementation_booking(
    change_id: int, bid: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Remove a booking you entered. Corrections are delete-and-rebook rather
    than an edit, so the changelog carries both halves of the fix."""
    from app.services.implementation_service import (
        ImplementationError, ImplementationService,
    )
    change = await _implementation_change(db, change_id, current_user)
    try:
        booking = await ImplementationService.get_booking(db, change, bid)
    except ImplementationError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await _require_implementation_write(
        db, change, booking.department_id, current_user)
    # Membership is not enough: somebody else's hours are their statement
    # about their day. PM and admins clean up regardless.
    from app.services.meeting_service import MeetingService
    if (booking.booked_by != current_user.id
            and current_user.effective_role != "admin"
            and not await MeetingService.user_is_pm_member(db, current_user)):
        raise HTTPException(
            status_code=403,
            detail="Only the person who booked that time (or Project "
                   "Management) may remove it")
    await ImplementationService.delete_booking(db, change, booking, current_user)
    await db.commit()


@router.get("/{change_id}/implementation/reports",
            response_model=List[ImplementationReportResponse])
async def list_implementation_reports(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.implementation_service import ImplementationService
    change = await _implementation_change(db, change_id, current_user)
    visible = await ImplementationService.readable_department_ids(
        db, change, current_user)
    rows = await ImplementationService.list_reports(db, change, visible)
    return await ImplementationService.serialize_reports(db, rows)


@router.post("/{change_id}/implementation/reports",
             response_model=ImplementationReportResponse,
             status_code=status.HTTP_201_CREATED)
async def create_implementation_report(
    change_id: int, body: ImplementationReportCreate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """A progress report. at_risk=true without a risk_note is accepted — the
    flag matters more than the paperwork behind it."""
    from app.services.implementation_service import (
        ImplementationError, ImplementationService,
    )
    change = await _implementation_change(db, change_id, current_user)
    await _require_implementation_write(
        db, change, body.department_id, current_user)
    try:
        report = await ImplementationService.create_report(
            db, change, body.model_dump(), current_user)
    except ImplementationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(report)
    return (await ImplementationService.serialize_reports(db, [report]))[0]


@router.get("/{change_id}/implementation/escalations",
            response_model=List[ImplementationEscalationResponse])
async def list_implementation_escalations(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Not department-scoped: an escalation is a statement about the change."""
    from app.services.implementation_service import ImplementationService
    change = await _implementation_change(db, change_id, current_user)
    rows = await ImplementationService.list_escalations(db, change)
    return await ImplementationService.serialize_escalations(db, rows)


@router.post("/{change_id}/implementation/escalations",
             response_model=ImplementationEscalationResponse,
             status_code=status.HTTP_201_CREATED)
async def create_implementation_escalation(
    change_id: int, body: ImplementationEscalationCreate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.implementation_service import (
        ImplementationError, ImplementationService,
    )
    change = await _implementation_change(db, change_id, current_user)
    await _require_escalation_right(db, change, current_user)
    try:
        escalation = await ImplementationService.create_escalation(
            db, change, body.model_dump(), current_user)
    except ImplementationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(escalation)
    return (await ImplementationService.serialize_escalations(db, [escalation]))[0]


@router.put("/{change_id}/implementation/escalations/{eid}/resolve",
            response_model=ImplementationEscalationResponse)
async def resolve_implementation_escalation(
    change_id: int, eid: int, body: ImplementationEscalationResolveIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.implementation_service import (
        ImplementationError, ImplementationService,
    )
    change = await _implementation_change(db, change_id, current_user)
    await _require_escalation_right(db, change, current_user)
    try:
        escalation = await ImplementationService.get_escalation(db, change, eid)
    except ImplementationError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        escalation = await ImplementationService.resolve_escalation(
            db, change, escalation, body.resolution_note, current_user)
    except ImplementationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(escalation)
    return (await ImplementationService.serialize_escalations(db, [escalation]))[0]


# --- stage 9: validation checks ---------------------------------------------
# Each implementing department fulfils its own checks; the rows are seeded from
# the catalog the first time anybody looks. Reading is NOT department-scoped —
# a validation verdict is a statement about the change, and the release meeting
# argues over one picture — while writing follows the stage-8 rule with the
# window moved to 'in_validation'.

@router.get("/{change_id}/validation/state",
            response_model=ValidationStateResponse)
async def validation_state(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Per implementing department: its checks, their answers, and what still
    blocks the release.

    The cycle-time check carries the costing's lifecycle assumption
    (planned_delta_seconds) so the measurement can be argued against the
    number the change was priced on, and the weight check carries the estimate
    and the delta for the same reason.

    Seeds the catalog rows on first read: from then on the release guard has
    something to hold the change to. Changes nobody ever opened this on keep
    releasing exactly as before.
    """
    from app.services.validation_service import ValidationService
    change = await _implementation_change(db, change_id, current_user)
    state = await ValidationService.state(db, change)
    await db.commit()
    return state


@router.post("/{change_id}/validation/checks",
             response_model=ValidationCheckResponse,
             status_code=status.HTTP_201_CREATED)
async def record_validation_check(
    change_id: int, body: ValidationCheckIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Tick (or fail) one of your department's validation checks.

    Passing a measurement check without its number is refused: a cycle time
    nobody wrote down cannot be compared to the lifecycle assumption, and a
    weight nobody wrote down produces no delta for Sales to re-quote.
    """
    from app.services.validation_service import (
        ValidationError as VError, ValidationService,
    )
    change = await _implementation_change(db, change_id, current_user)
    if not await ValidationService.may_write(
            db, change, body.department_id, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only a member of that department while the change is in "
                   "validation, Project Management or an admin may sign off "
                   "its validation checks")
    try:
        row = await ValidationService.record_check(
            db, change, body.model_dump(), current_user)
    except VError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/{change_id}/validation/weight-ack", response_model=ChangeResponse)
async def acknowledge_weight_delta(
    change_id: int, body: WeightDeltaAckIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Sales closes the loop the weight delta opened: the quote was updated,
    or the difference was absorbed. Clears the 'update_quote' task."""
    from app.services.validation_service import (
        ValidationError as VError, ValidationService,
    )
    change = await _implementation_change(db, change_id, current_user)
    if not await ValidationService.may_acknowledge_weight_delta(
            db, change, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only Sales, the change lead or an admin may settle the "
                   "weight delta against the quote")
    try:
        await ValidationService.acknowledge_weight_delta(
            db, change, body.note, current_user)
    except VError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return change
