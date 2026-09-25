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
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.change import (
    ChangeChangelog, ChangeAttachment, ChangeRequest, ChangeAssessment,
    ChangeImpactedItem, SIGN_OFF_ROLES, BLOCKING_LETTERS,
)
from app.models.workflow import UserDepartment, Department
from app.services.change_service import (
    ALLOWED_TRANSITIONS, ChangeService, ChangeError, DeviationRequired, _org_scope,
)
from app.services.workflow_service import WorkflowService
from app.services.meeting_service import MeetingForbidden, MeetingService
from app.services.validation_issue_service import IssueForbidden, IssueNotFound
from app.services.change_people import is_acting
from app.schemas.change import (
    ChangeCreate, ChangeUpdate, ChangeResponse, ChangeDetailResponse,
    TransitionRequest, ImpactedItemCreate, ImpactedItemResponse,
    AssessmentSubmit, AssessmentResponse, AssessmentAssignIn, AssessmentDueDateIn,
    CustomerResponseRequest, SignOffRequest,
    ChangelogResponse,
    RoutingResponse, RoutingStage, RoutingDepartment, DeviationRequest, RoutingDeviationDecision,
    RiskTemplateCreate, RiskTemplateResponse, RiskTypeCreate, RiskTypeResponse,
    CostCategoryCreate, CostCategoryResponse,
    RoutingStandardUpsert,
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
    VendorChoiceIn,
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


async def _project_org_id(db: AsyncSession, project_id) -> Optional[int]:
    """The organization a project belongs to (project -> plant -> org)."""
    from app.models.entities import Plant, Project
    if project_id is None:
        return None
    project = await db.get(Project, project_id)
    plant = await db.get(Plant, project.plant_id) if project else None
    return plant.organization_id if plant else None


async def _require_org_user(db: AsyncSession, user_id: int,
                            org_id: Optional[int]) -> User:
    """An active user of `org_id` (any org when the change has no project),
    else 400 - a lead from another organization would see nothing of it."""
    u = await db.get(User, user_id)
    if u is None or not u.is_active or (
            org_id is not None and u.organization_id != org_id):
        raise HTTPException(status_code=400, detail="Lead user not found")
    return u


@router.post("", response_model=ChangeResponse)
async def create_change(
    body: ChangeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services import mother_plants as mp
    from app.services.mother_plant_service import MotherPlantService
    mother_plant = body.origin == mp.MOTHER_PLANT
    allowed = (await MotherPlantService.may_start(db, current_user) if mother_plant
               else await ChangeService.user_can_start_change(db, current_user))
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=("Only an admin, Project Management or a member of a "
                    "department allowed to start changes may raise a change "
                    f"from {mp.plant_name(body)}" if mother_plant else
                    "Only an admin or a member of a department allowed to start "
                    "changes (e.g. Sales) may raise a change"))
    # The system currently runs the customer (external) change flow only, so
    # the entry point refuses to create internal ones — half-built internal
    # changes stuck mid-flow are worse than not offering them. The SERVICE
    # stays capable: the internal costing/approval path is real, tested
    # functionality waiting on the decision to switch it on.
    # A change from the mother plant is not customer relevant here either,
    # but it is its own side track (spec §14), not the internal branch.
    if body.customer_relevant is False and not mother_plant:
        raise HTTPException(
            status_code=400,
            detail="Internal changes are not enabled yet — this system "
                   "currently runs the customer (external) change flow")
    # The project must be one the caller can see (their organization; an
    # admin sees all), and the lead a live user of the project's organization.
    project_org = await _project_org_id(db, body.project_id)
    if project_org is None or (current_user.effective_role != "admin"
                               and project_org != current_user.organization_id):
        raise HTTPException(status_code=404, detail="Project not found")
    # Spec §16: the capturer does not make themselves (or anybody) the lead.
    # Naming the lead is Project Management's call (or an admin's); for
    # everybody else lead_id is ignored. Either way, ChangeService.create_change
    # falls back to the project's standard PM (project.pm_user_id) when no
    # explicit lead survives here.
    lead_id = body.lead_id
    if lead_id is not None and not await MeetingService.user_is_pm(db, current_user):
        lead_id = None
    if lead_id is not None:
        await _require_org_user(db, lead_id, project_org)
    try:
        change = await ChangeService.create_change(
            session=db, project_id=body.project_id, title=body.title,
            change_type=body.change_type, raised_by=current_user.id,
            reason=body.reason, description=body.description, priority=body.priority,
            lead_id=lead_id, data_classification=body.data_classification,
            customer_relevant=body.customer_relevant,
            origin=body.origin, mother_plant_name=body.mother_plant_name,
            mother_plant_ref=body.mother_plant_ref,
            mother_plant_sop=body.mother_plant_sop,
        )
        # Spec §16: the impacted items travel with the capture, in the same
        # transaction, so a change never exists half-captured.
        if body.title_auto is not None:
            change.title_auto = body.title_auto
        if body.impacted_part_ids:
            from app.services.early_stage_service import EarlyStageService
            ids = list(dict.fromkeys(body.impacted_part_ids))
            lead = body.lead_part_id if body.lead_part_id in ids else ids[0]
            await db.refresh(change, ["impacted_items"])
            for pid in ids:
                await ChangeService.add_impacted_item(
                    db, change, pid, current_user.id, is_lead=(pid == lead))
                await db.refresh(change, ["impacted_items"])
            await EarlyStageService.recompose_title(db, change, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return await _price_safe(db, change, current_user, ChangeResponse)


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
    from app.services.price_redaction import PriceViewer, redact_change_out
    viewer = PriceViewer(db, current_user)
    out = []
    acting = getattr(current_user, "acts_as_department_id", None) is not None
    from app.models.revision_intake import RevisionIntake
    from_intake = set((await db.execute(
        select(RevisionIntake.change_id).where(
            RevisionIntake.change_id.is_not(None)))).scalars().all())
    for change in changes:
        change.deadline_state = await ChangeService.deadline_state(db, change)
        row = ChangeResponse.model_validate(change)
        row.from_intake = change.id in from_intake
        # "Mine" filter (spec §16): the caller leads or raised it.
        row.is_mine = not acting and current_user.id in (change.lead_id, change.raised_by)
        if not await viewer.may_read(change):
            redact_change_out(row)
        out.append(row)
    return out


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
    from app.services import mother_plants as mp
    from app.services.mother_plant_service import MotherPlantService
    return {
        "can_start_change": await ChangeService.user_can_start_change(db, current_user),
        # Mother-plant side track (spec §14): starters plus Project
        # Management, and the configured plants (default first).
        "can_start_mother_plant": await MotherPlantService.may_start(db, current_user),
        "mother_plants": list(mp.MOTHER_PLANTS),
        "default_mother_plant": mp.DEFAULT_MOTHER_PLANT,
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
      offer_expiring   quoted, and the latest sent offer version expires
                       within 7 days (or already has), for Sales
      plan_feedback    approved with a detailed plan this caller's required
                       department has not confirmed at the current revision
      info_ack         mother-plant change: this caller's department was
                       informed and has not confirmed "Read and understood"
      info_send        mother-plant change at scoping, nobody informed yet,
                       for PM / lead / admin
      inform_mother_plant  mother-plant change with validated timing not yet
                       stamped "Inform mother plant", for PM / lead / admin
      release_check    in_validation with open release-checklist items owned
                       by this caller's department
      validation_issue_* an open validation issue waits on this caller:
                       _contain, _root_cause, _route, _action, _customer,
                       _quote, _close, _escalation (acknowledge); with
                       issue_id, label, target_tab "release"

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
        from app.services.early_stage_service import EarlyStageService
        pairs = rows.all()
        # The assessment is the FIRST routing stage (plus deviation-added
        # departments); later-stage PM/Sales rows are no assessment (§16).
        firsts: dict[int, int] = {}
        if pairs:
            from sqlalchemy import func as _f
            firsts = dict((await db.execute(
                select(ChangeAssessment.change_id, _f.min(ChangeAssessment.stage_order))
                .where(ChangeAssessment.change_id.in_({c.id for _, c in pairs}))
                .group_by(ChangeAssessment.change_id))).all())
        for a, c in pairs:
            if not EarlyStageService.is_assessment_row(a, firsts.get(c.id)):
                continue
            # Execution state lives on the linked engine task; surface a row only
            # when it is *effectively* active (task active, or an unlinked row
            # carrying its own "active" status from a routing deviation).
            if a.effective_status != "active":
                continue
            # Only R/A letters OWE a submit. A Consulted/Support row activates
            # with its stage so the department may chime in, but its 'noted'
            # task gates nothing — queueing it as a task tells a department
            # that already did its Responsible work in an earlier stage that
            # it still owes something. Exception: a non-blocking row somebody
            # explicitly took (owner) is that person's to-do.
            if (a.rasic_letter not in BLOCKING_LETTERS
                    and a.effective_owner_id != current_user.id):
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

    # Batch the per-stage lookups once for the whole list, instead of a few
    # queries per change: departments by name, draft / latest sent offers,
    # detailed-plan presence and feedback, release-check rows.
    from app.models.change_offer import ChangeOffer
    from app.models.change_plan import ChangePlanFeedback, ChangePlanTask
    from app.models.change_validation import ChangeReleaseCheck
    from app.services import release_checklist
    from app.services.offer_service import EXPIRY_WARNING_DAYS, OfferService
    dept_by_name = {n: i for i, n in (await db.execute(
        select(Department.id, Department.name))).all()}

    def _ids(*statuses):
        return [c.id for c in open_changes if c.status in statuses]

    # Changes with an open validation issue (spec §12), once for the list.
    from app.models.change_validation_issue import (
        ISSUE_DONE_STATUSES, ValidationIssue,
    )
    from app.services.validation_issue_service import ValidationIssueService
    vi_ids = _ids("approved", "in_implementation", "in_validation")
    issue_change_ids = set((await db.execute(
        select(ValidationIssue.change_id).where(
            ValidationIssue.change_id.in_(vi_ids),
            ValidationIssue.status.not_in(ISSUE_DONE_STATUSES)).distinct()
    )).scalars().all()) if vi_ids else set()

    drafts: dict = {}
    latest_sent: dict = {}
    offer_ids = _ids("quoting", "quoted") if in_sales else []
    if offer_ids:
        for o in (await db.execute(
                select(ChangeOffer).where(
                    ChangeOffer.change_id.in_(offer_ids),
                    ChangeOffer.status.in_(("draft", "sent")))
                .order_by(ChangeOffer.version))).scalars().all():
            # ordered by version: the last one per change wins
            (drafts if o.status == "draft" else latest_sent)[o.change_id] = o
    planned: set = set()
    feedback: dict = {}
    approved_ids = [c.id for c in open_changes
                    if c.status == "approved" and c.timing_validated_at is None]
    if dep_ids and approved_ids:
        planned = {cid for (cid,) in (await db.execute(
            select(ChangePlanTask.change_id).where(
                ChangePlanTask.change_id.in_(approved_ids),
                ChangePlanTask.plan == "detailed").distinct())).all()}
        if planned:
            for r in (await db.execute(
                    select(ChangePlanFeedback).where(
                        ChangePlanFeedback.change_id.in_(planned))
                    .order_by(ChangePlanFeedback.id))).scalars().all():
                feedback.setdefault(r.change_id, {})[r.department_id] = r
    # Mother-plant side track (spec §14): open "Read and understood"
    # receipts of the caller's departments, and which changes have informed
    # anybody yet (the PM's "Send information" errand).
    from app.models.change_info import ChangeInfoReceipt
    from app.services import mother_plants as mp
    from app.services.mother_plant_service import MotherPlantService
    mp_ids = [c.id for c in open_changes if mp.is_mother_plant(c)]
    info_open = await MotherPlantService.open_receipts_for(db, mp_ids, dep_ids)
    informed_ids = set((await db.execute(
        select(ChangeInfoReceipt.change_id).where(
            ChangeInfoReceipt.change_id.in_(mp_ids)).distinct()
    )).scalars().all()) if mp_ids else set()
    informed_depts: dict = {}
    if mp_ids and approved_ids:
        for cid, did in (await db.execute(
                select(ChangeInfoReceipt.change_id, ChangeInfoReceipt.department_id)
                .where(ChangeInfoReceipt.change_id.in_(
                    [i for i in mp_ids if i in approved_ids])))).all():
            informed_depts.setdefault(cid, set()).add(did)
    release_rows: dict = {}
    validation_ids = _ids("in_validation") if dep_ids else []
    if validation_ids:
        for r in (await db.execute(select(ChangeReleaseCheck).where(
                ChangeReleaseCheck.change_id.in_(validation_ids)))).scalars().all():
            release_rows.setdefault(r.change_id, {})[r.check_key] = r

    for c in open_changes:
        if c.status == "captured" and (
                can_capture or (is_pm and mp.is_mother_plant(c))):
            # a mother-plant change is captured by Project Management
            tasks.append({**await _base(c), "kind": "kickoff",
                          "missing": await ChangeService.kickoff_missing(db, c),
                          # project team: a mother-plant kickoff is PM's role
                          "role_department_id": (dept_by_name.get("Project Manager")
                                                 if mp.is_mother_plant(c) else None)})
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
            draft = drafts.get(c.id)
            tasks.append({
                **await _base(c), "kind": "create_quote",
                "has_price": c.quoted_price is not None,
                # The offer document is the quote now: whether a draft exists
                # says which half of "build and send the offer" is left.
                "has_offer_draft": draft is not None,
                "offer_id": draft.id if draft is not None else None,
                "target_tab": "offer",
                "hint": "Build and send the offer",
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

        # The offer is valid for 30 days from receipt: a week before it runs
        # out (or once it has) the customer has to be chased or a new
        # version sent.
        if c.status == "quoted" and in_sales and c.customer_relevant:
            offer = latest_sent.get(c.id)
            if (offer is not None and offer.valid_until is not None
                    and OfferService.days_left(offer) <= EXPIRY_WARNING_DAYS):
                tasks.append({
                    **await _base(c), "kind": "offer_expiring",
                    "offer_id": offer.id, "version": offer.version,
                    "valid_until": offer.valid_until,
                    "days_left": OfferService.days_left(offer),
                    "target_tab": "offer",
                })

        # Mother plant: "Read and understood" for each informed department
        # of the caller; "Send information" for the PM at scoping until
        # somebody is informed; "Inform the mother plant" once the timing is
        # validated (the customer publish does not exist here).
        if mp.is_mother_plant(c):
            for r in info_open.get(c.id, []):
                tasks.append({
                    **await _base(c), "kind": "info_ack",
                    "department_id": r.department_id, "receipt_id": r.id,
                    "target_tab": "mother",
                    "hint": (f"Read the change from {mp.plant_name(c)} and "
                             "confirm: read and understood"),
                })
            if (c.status == "scoping" and c.id not in informed_ids
                    and await MotherPlantService.may_send(db, c, current_user)):
                tasks.append({
                    **await _base(c), "kind": "info_send",
                    "target_tab": "mother",
                    "hint": "Send information to the team",
                })
            if (c.status in ("approved", "in_implementation")
                    and c.timing_validated_at is not None
                    and c.plan_published_at is None
                    and await MotherPlantService.may_send(db, c, current_user)):
                tasks.append({
                    **await _base(c), "kind": "inform_mother_plant",
                    "target_tab": "timing",
                    "hint": (f"Inform {mp.plant_name(c)} of the validated "
                             "timing"),
                })

        # The detailed plan waits on every responsible team's confirmation;
        # each unconfirmed one is that department's errand.
        # Same rule as ChangePlanService.feedback_state, on preloaded rows.
        if (c.status == "approved" and dep_ids
                and c.timing_validated_at is None and c.id in planned):
            required = {a.department_id for a in c.assessments
                        if a.rasic_letter in BLOCKING_LETTERS}
            if mp.is_mother_plant(c):
                # no assessments: the informed departments and Scheduling
                required |= informed_depts.get(c.id, set())
                required |= {dept_by_name[n] for n in ("Scheduling",)
                             if n in dept_by_name}
            else:
                required |= {dept_by_name[n] for n in ("Scheduling", "Sales")
                             if n in dept_by_name}
            latest = feedback.get(c.id, {})
            revision = int(c.plan_revision or 0)
            for did in sorted(required & dep_ids):
                r = latest.get(did)
                stale = bool(r is not None and r.plan_revision < revision)
                if r is not None and r.verdict == "confirmed" and not stale:
                    continue
                tasks.append({
                    **await _base(c), "kind": "plan_feedback",
                    "department_id": did,
                    "stale": stale, "target_tab": "timing",
                    "hint": "Confirm the detailed plan or raise a concern",
                })

        # Stage 10: open release-checklist items, per owner department.
        if c.status == "in_validation" and dep_ids:
            rows = release_rows.get(c.id, {})
            by_name = dept_by_name
            open_by_dept: dict = {}
            for key in release_checklist.CHECK_KEYS:
                r = rows.get(key)
                if r is not None and r.status in ("done", "na"):
                    continue
                did = (r.department_id if r is not None
                       else by_name.get(release_checklist.owner_for(key)))
                if did in dep_ids:
                    open_by_dept.setdefault(did, []).append(key)
            for did, keys in sorted(open_by_dept.items()):
                tasks.append({
                    **await _base(c), "kind": "release_check",
                    "department_id": did, "check_keys": keys,
                    "open_count": len(keys), "target_tab": "release",
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

        # Validation issues (spec §12): contain / root cause / fix actions for
        # the owner department, the route for PM / lead, the customer
        # decision and "quote the fix" for Sales, and every unacknowledged
        # escalation the caller was notified of. Same rights as the cockpit
        # (ValidationIssueService.my_actions).
        if c.id in issue_change_ids:
            for item in await ValidationIssueService.my_actions(db, c, current_user):
                tasks.append({
                    **await _base(c), **item, "hint": item["label"],
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
        # that asked. Addressed to the person who asked and to Project
        # Management, the standing arbiter — mirroring withdraw_concern's
        # rule. A department only owns the flag (any member may close it)
        # while the change is in assessment; a scoping question's attribution
        # is a label and hands its department nothing. An answered question
        # nobody is told to review stalls exactly like an unanswered one.
        answered = ChangeService.answered_questions(c)
        if answered:
            # Under acts-as the personal requester errand steps aside with the
            # real memberships — the task list shows the department's view.
            am_requester = (getattr(current_user, "acts_as_department_id", None)
                            is None)
            mine = [q for q in answered
                    if is_pm_member
                    or (am_requester and q.raised_by == current_user.id)
                    or (c.status == "in_assessment"
                        and q.department_id is not None
                        and q.department_id in dep_ids)]
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

    # Post-quote scope change (spec §16): costing reopens for the affected
    # departments only, until a newer offer or an approved deviation covers it.
    if dep_ids:
        from app.services.early_stage_service import EarlyStageService as _ES
        for c in open_changes:
            mine_depts = set(c.scope_change_department_ids or []) & dep_ids
            if not (c.scope_changed_after_quote and mine_depts):
                continue
            state = await _ES.scope_change_state(db, c)
            if state and not state["covered"]:
                for d in sorted(mine_depts):
                    tasks.append({**await _base(c), "kind": "costing_update",
                                  "department_id": d,
                                  "reason": c.scope_change_reason})

    # One list (spec §16): no duplicate rows, a human kind label and the
    # stage each row belongs to.
    from app.services import cm_labels
    status_of = {c.id: c.status for c in open_changes}
    lead_of = {c.id: c.lead_id for c in open_changes}
    acting = getattr(current_user, "acts_as_department_id", None) is not None
    # The caller's departments' RASIC letters per change (spec §16 follow-up).
    letters: dict[int, set] = {}
    task_change_ids = {t["change_id"] for t in tasks}
    if dep_ids and task_change_ids:
        for cid, letter in (await db.execute(
                select(ChangeAssessment.change_id, ChangeAssessment.rasic_letter)
                .where(ChangeAssessment.change_id.in_(task_change_ids),
                       ChangeAssessment.department_id.in_(dep_ids)))).all():
            letters.setdefault(cid, set()).add(letter)
    from app.services.project_team_service import TeamRoles
    team = TeamRoles(db, current_user.id)
    seen: set = set()
    unique = []
    for t in tasks:
        key = (t["kind"], t["change_id"], t.get("assessment_id"),
               t.get("concern_id"), t.get("issue_id"), t.get("check_key"),
               t.get("escalation_id"), t.get("action_id"),
               t.get("department_id") if t["kind"] in ("costing_input", "costing_update",
                                                        "plan_feedback", "info_ack",
                                                        "release_check", "progress_report")
               else None)
        if key in seen:
            continue
        seen.add(key)
        t.setdefault("kind_label", cm_labels.TASK_KIND[t["kind"]][0]
                     if t["kind"] in cm_labels.TASK_KIND
                     else t.get("label") or cm_labels.label("task_kind", t["kind"]))
        stage = t.get("stage") or status_of.get(t["change_id"])
        t.setdefault("stage", stage)
        t.setdefault("stage_label", cm_labels.label("status", stage) if stage else None)
        t.setdefault("status", status_of.get(t["change_id"]))
        t["rasic_letters"] = sorted(letters.get(t["change_id"], set()),
                                    key="RASCI".index)
        t["is_mine"] = bool(t.get("mine")) or (
            not acting and lead_of.get(t["change_id"]) == current_user.id)
        # Project team (spec §18): "main" rows count on the badge and the
        # list header; "backup" rows (another responsible leads this role
        # on the project) stay listed, muted, with the main's name.
        await team.annotate(t, t.get("project_id"), owned=t["is_mine"])
        t.pop("role_department_id", None)
        unique.append(t)
    tasks = unique

    # One order across every kind: overdue first, then soonest due (undated
    # last), then change number. Assessment rows keep "mine" as the top tie
    # break — an answer you already accepted outranks one you have not.
    tasks.sort(key=lambda d: (
        d.get("role") == "backup",
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
    # The cost sheet's currently valid version (spec §15); department_rate
    # only until a first version is published.
    from app.services.cost_sheet_service import reference_rates as sheet_rates
    sheet = await sheet_rates(db, current_user.organization_id)
    if sheet is not None:
        return sheet
    from app.services.costing_rates import has_cost_sheet
    if await has_cost_sheet(db, current_user.organization_id):
        return []      # a cost sheet exists but none is valid today: no rates
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


@router.get("/reference/labels")
async def reference_labels(current_user: User = Depends(get_current_user)):
    """Human labels for the module's codes (spec §16): status, verdict,
    change type, priority, concern kind, RASIC letter, cost carrier, how a
    concern was settled and My Tasks kinds. {group: {code: {en, de}}}."""
    from app.services import cm_labels
    return cm_labels.reference()


@router.get("/reference/risk-types")
async def reference_risk_types(
    department_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The vocabulary a risk concern is typed with, resolved per department.

    Same reasoning as the checklist above: the list lives in
    app/services/risk_types.py because that is what the raise endpoint
    validates against, so the frontend is served it rather than keeping its
    own copy. Without a department: the legacy moulding list plus the common
    types.
    """
    from app.services.risk_types import resolved_types
    dept = await db.get(Department, department_id) if department_id is not None else None
    return {"items": await resolved_types(db, dept)}


@router.post("/reference/risk-types", response_model=RiskTypeResponse)
async def create_risk_type(
    body: RiskTypeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A department adds a type to its own dropdown. Same writers as the
    templates: members, Project Management, admin."""
    from app.models.change import DepartmentRiskType
    from app.services.risk_types import custom_key, allowed_keys
    dept = await db.get(Department, body.department_id)
    if dept is None:
        raise HTTPException(404, "Department not found")
    if not await _may_edit_risk_templates(db, current_user, body.department_id):
        raise HTTPException(403, "Only members of this department, Project Management "
                                 "or an admin may add its risk types")
    label = body.label.strip()
    if not label:
        raise HTTPException(400, "A risk type needs a name")
    key = custom_key(body.department_id, label)
    live = (await db.execute(
        select(DepartmentRiskType).where(
            DepartmentRiskType.department_id == body.department_id,
            DepartmentRiskType.key == key,
            DepartmentRiskType.deleted_at.is_(None)))).scalar_one_or_none()
    if live is not None:
        return live  # same name again: hand back the existing one
    if key in await allowed_keys(db, dept):
        # A deleted custom type with this name comes back to life.
        old = (await db.execute(
            select(DepartmentRiskType).where(
                DepartmentRiskType.department_id == body.department_id,
                DepartmentRiskType.key == key))).scalars().first()
        if old is not None:
            old.deleted_at = None
            old.deleted_by = None
            old.label = label
            await db.commit()
            await db.refresh(old)
            return old
        raise HTTPException(400, f"'{label}' is already a standard risk type")
    row = DepartmentRiskType(department_id=body.department_id, key=key, label=label,
                             created_by=current_user.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/reference/risk-types/{type_id}", response_model=RiskTypeResponse)
async def delete_risk_type(
    type_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft delete: off the dropdown, rows raised under it keep their key."""
    from app.models.change import DepartmentRiskType
    row = await db.get(DepartmentRiskType, type_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(404, "Risk type not found")
    if not await _may_edit_risk_templates(db, current_user, row.department_id):
        raise HTTPException(403, "Only members of this department, Project Management "
                                 "or an admin may delete its risk types")
    row.deleted_at = datetime.utcnow()
    row.deleted_by = current_user.id
    await db.commit()
    await db.refresh(row)
    return row


async def _may_edit_risk_templates(db: AsyncSession, user: User, department_id: int) -> bool:
    """The department's own list: its members, Project Management and admins
    (an admin acting as a department counts as that department only)."""
    from app.services.workflow_service import WorkflowService
    if getattr(user, "acts_as_department_id", None) is None and user.role == "admin":
        return True
    ids = await WorkflowService.effective_department_ids(db, user)
    if department_id in ids:
        return True
    pm = (await db.execute(
        select(Department.id).where(Department.name == "Project Manager"))).scalar_one_or_none()
    return pm is not None and pm in ids


@router.get("/reference/risk-templates", response_model=List[RiskTemplateResponse])
async def list_risk_templates(
    department_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A department's pre-written risks, live ones only, newest last."""
    from app.models.change import DepartmentRiskTemplate
    rows = (await db.execute(
        select(DepartmentRiskTemplate)
        .where(DepartmentRiskTemplate.department_id == department_id,
               DepartmentRiskTemplate.deleted_at.is_(None))
        .order_by(DepartmentRiskTemplate.id))).scalars().all()
    return rows


@router.post("/reference/risk-templates", response_model=RiskTemplateResponse)
async def create_risk_template(
    body: RiskTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.change import DepartmentRiskTemplate, RISK_SEVERITIES
    from app.services.risk_types import allowed_keys
    dept = await db.get(Department, body.department_id)
    if dept is None:
        raise HTTPException(404, "Department not found")
    if not await _may_edit_risk_templates(db, current_user, body.department_id):
        raise HTTPException(403, "Only members of this department, Project Management "
                                 "or an admin may write its risk templates")
    if body.risk_type not in await allowed_keys(db, dept):
        raise HTTPException(400, f"Invalid risk type '{body.risk_type}' for {dept.name}")
    if body.severity not in RISK_SEVERITIES:
        raise HTTPException(400, "Risk severity must be 1 (low), 2 (medium) or 3 (high)")
    if not body.note.strip():
        raise HTTPException(400, "A risk template needs the wording of the risk")
    row = DepartmentRiskTemplate(
        department_id=body.department_id, risk_type=body.risk_type,
        severity=body.severity, note=body.note.strip(), created_by=current_user.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/reference/risk-templates/{template_id}", response_model=RiskTemplateResponse)
async def delete_risk_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft delete: gone from the list, kept on the record."""
    from app.models.change import DepartmentRiskTemplate
    row = await db.get(DepartmentRiskTemplate, template_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(404, "Risk template not found")
    if not await _may_edit_risk_templates(db, current_user, row.department_id):
        raise HTTPException(403, "Only members of this department, Project Management "
                                 "or an admin may delete its risk templates")
    row.deleted_at = datetime.utcnow()
    row.deleted_by = current_user.id
    await db.commit()
    await db.refresh(row)
    return row


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
    dept = await db.get(Department, department_id) if department_id is not None else None
    return {"items": await costing_tags.resolved_tags(db, dept)}


@router.post("/reference/costing-tags", response_model=CostCategoryResponse)
async def create_cost_category(
    body: CostCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A department adds a category to its own costing list, typed money or
    time. Same writers as its risk lists: members, Project Management, admin."""
    from app.models.change_cost import DepartmentCostCategory
    from app.services import costing_tags
    dept = await db.get(Department, body.department_id)
    if dept is None:
        raise HTTPException(404, "Department not found")
    if not await _may_edit_risk_templates(db, current_user, body.department_id):
        raise HTTPException(403, "Only members of this department, Project Management "
                                 "or an admin may add its cost categories")
    label = body.label.strip()
    if not label:
        raise HTTPException(400, "A cost category needs a name")
    if body.entry_type not in costing_tags.ENTRY_TYPES:
        raise HTTPException(400, "entry_type must be 'money' or 'time'")
    key = costing_tags.custom_key(body.department_id, label)
    existing = (await db.execute(
        select(DepartmentCostCategory).where(
            DepartmentCostCategory.department_id == body.department_id,
            DepartmentCostCategory.key == key)
        .order_by(DepartmentCostCategory.id))).scalars().first()
    if existing is not None:
        # Same name again hands back the one row, revived if it was removed.
        existing.deleted_at = None
        existing.deleted_by = None
        existing.label = label
        existing.entry_type = body.entry_type
        await db.commit()
        await db.refresh(existing)
        return existing
    if key in {i["key"] for i in costing_tags.tags_for(dept.name)}:
        raise HTTPException(400, f"'{label}' is already a standard category")
    row = DepartmentCostCategory(
        department_id=body.department_id, key=key, label=label,
        entry_type=body.entry_type, created_by=current_user.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/reference/costing-tags/{category_id}", response_model=CostCategoryResponse)
async def delete_cost_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft delete: off the list, positions filed under it keep their key."""
    from app.models.change_cost import DepartmentCostCategory
    row = await db.get(DepartmentCostCategory, category_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(404, "Cost category not found")
    if not await _may_edit_risk_templates(db, current_user, row.department_id):
        raise HTTPException(403, "Only members of this department, Project Management "
                                 "or an admin may delete its cost categories")
    row.deleted_at = datetime.utcnow()
    row.deleted_by = current_user.id
    await db.commit()
    await db.refresh(row)
    return row


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


async def _hide_foreign_drafts(db: AsyncSession, user: User, assessments) -> None:
    """details.draft is a department's unfinished answer: only who may keep
    it (its members, admin; EarlyStageService._draft_row) reads it."""
    if user.effective_role == "admin":
        return
    mine = None
    for a in assessments:
        if not (isinstance(a.details, dict) and "draft" in a.details):
            continue
        if mine is None:
            mine = set(await WorkflowService.effective_department_ids(db, user))
        if a.department_id not in mine:
            a.details = {k: v for k, v in a.details.items() if k != "draft"}


async def _assessment_out(db: AsyncSession, a, user: User) -> AssessmentResponse:
    out = AssessmentResponse.model_validate(a)
    await _hide_foreign_drafts(db, user, [out])
    return out


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
    change.costing_unpriced = []
    if change.status in ("costing", "quoting"):
        from app.services import costing_rates
        change.costing_unpriced = await costing_rates.unpriced_departments(db, change)
    evidence = await ChangeService.assessment_evidence_state(db, change)
    for a in change.assessments:
        state = evidence.get(a.id, {})
        a.has_evidence = state.get("has_evidence", False)
        a.has_change_ppt = state.get("has_change_ppt", False)
        a.has_rfq = state.get("has_rfq", False)
        a.rfq_expected = state.get("rfq_expected", False)
    out = await _price_safe(db, change, current_user, ChangeDetailResponse)
    await _hide_foreign_drafts(db, current_user, out.assessments)
    # Vendor quotes follow their costing position's read rule here too.
    from app.services.costing_position_service import CostingPositionService
    hidden = await CostingPositionService.unreadable_attachment_ids(
        db, change, current_user, change.attachments)
    if hidden:
        out.attachments = [a for a in out.attachments if a.id not in hidden]
    from app.models.revision_intake import RevisionIntake
    out.from_intake = (await db.execute(
        select(RevisionIntake.id).where(RevisionIntake.change_id == change.id)
        .limit(1))).scalar_one_or_none() is not None
    return out


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
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    from app.services.negotiation_service import NegotiationService
    rows = (await db.execute(
        select(ChangeChangelog).where(ChangeChangelog.change_id == change_id)
        .order_by(ChangeChangelog.performed_at, ChangeChangelog.id)
    )).scalars().all()
    if await NegotiationService.may_read(db, change, current_user):
        return rows
    # Everyone on the change reads its history; only the cost roles (admin,
    # lead, PM, Sales) read its prices. Older rows carry amounts in their
    # description, so they are redacted on the way out, never rewritten.
    # A vendor quote's name follows its costing position's read rule.
    from app.services.price_redaction import QuoteReader, blank_quote_changelog
    quotes = QuoteReader(db, current_user)
    out = []
    for r in rows:
        row = _redact_changelog(r)
        if await quotes.hides(change, r.action, r.old_value, r.new_value):
            row = blank_quote_changelog(row)
        out.append(row)
    return out


def _redact_changelog(row) -> dict:
    from app.services.price_redaction import redact_changelog_row
    return redact_changelog_row(row)


async def _price_safe(db, change, user, model):
    """The change header as `model`, its money fields nulled for a viewer
    outside the cost roles (see price_redaction)."""
    from app.services.price_redaction import PriceViewer, redact_change_out
    out = model.model_validate(change)
    if not await PriceViewer(db, user).may_read(change):
        redact_change_out(out)
    return out


@router.get("/{change_id}/implementation")
async def get_implementation_progress(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
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
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if change is None:
        raise HTTPException(404, "Change not found")
    try:
        _, _, stages = await ChangeRoutingService.resolve_standard(db, change.change_type)
    except ChangeError:
        return []
    stage1 = next((s for s in stages if s["stage_order"] == 1), None)
    if not stage1:
        return []
    # Every stage-1 department with the letter the standard gives it: the
    # picker starts from the template's opinion, the room overrules it.
    letters = {d["department_id"]: d["rasic_letter"] for d in stage1["departments"]}
    if not letters:
        return []
    rows = (await db.execute(
        select(Department.id, Department.name)
        .where(Department.id.in_(letters), Department.is_active.is_(True))
        .order_by(Department.sort_order, Department.name))).all()
    return [{"id": i, "name": n, "rasic_letter": letters[i]} for i, n in rows]


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
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if change is None:
        raise HTTPException(404, "Change not found")
    # Self-healing read (final walk P1-1): a stage row without its engine
    # task (room-added department, legacy data) gets it here, idempotently.
    from app.services.change_routing_service import ChangeRoutingService
    if await ChangeRoutingService.repair_stage_tasks(db, change, current_user.id):
        await db.commit()
        change = await ChangeService.get_change(db, change_id, viewer=current_user)
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
                assessment_id=(a.id if a else None),
                pending_rasic_letter=(a.pending_rasic_letter if a else None)))
        stages.append(RoutingStage(stage_order=st["stage_order"], departments=deps))
    return RoutingResponse(
        change_id=change_id,
        template_id=(routing.template_id if routing else None),
        template_version=(routing.template_version if routing else None),
        has_deviation=(routing.has_deviation if routing else False),
        deviation_status=(routing.deviation_status if routing else "none"),
        deviation_note=(routing.deviation_note if routing else None),
        deviation_proposed_by=(routing.deviation_proposed_by if routing else None),
        stages=stages)


@router.post("/{change_id}/routing/repair")
async def repair_routing(change_id: int, db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    """Admin: give every assessment row of a started stage its missing engine
    task (see ChangeRoutingService.repair_stage_tasks). Idempotent; returns
    the repaired assessment ids (empty when nothing was missing)."""
    if current_user.effective_role != "admin":
        raise HTTPException(403, "Only an admin may repair a change's routing")
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if change is None:
        raise HTTPException(404, "Change not found")
    from app.services.change_routing_service import ChangeRoutingService
    repaired = await ChangeRoutingService.repair_stage_tasks(db, change, current_user.id)
    await db.commit()
    return {"change_id": change_id, "repaired_assessment_ids": repaired}


@router.post("/{change_id}/routing/deviation", response_model=RoutingResponse)
async def post_deviation(change_id: int, body: DeviationRequest,
                         db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if change is None:
        raise HTTPException(404, "Change not found")
    from app.services.change_routing_service import ChangeRoutingService
    try:
        await ChangeRoutingService.apply_deviation(
            db, change, current_user.id, op=body.op, department_id=body.department_id,
            rasic_letter=body.rasic_letter, stage_order=body.stage_order,
            reason=body.reason)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    return await get_routing(change_id, db, current_user)


@router.post("/{change_id}/routing/deviation/reject", response_model=RoutingResponse)
async def reject_deviation(change_id: int, body: RoutingDeviationDecision,
                           db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if change is None:
        raise HTTPException(404, "Change not found")
    from app.services.change_routing_service import ChangeRoutingService
    try:
        await ChangeRoutingService.reject_deviation(
            db, change, current_user.id, body.reason,
            acting=is_acting(current_user))
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    return await get_routing(change_id, db, current_user)


@router.post("/{change_id}/routing/deviation/approve", response_model=RoutingResponse)
async def approve_deviation(change_id: int, db: AsyncSession = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if change is None:
        raise HTTPException(404, "Change not found")
    from app.services.change_routing_service import ChangeRoutingService
    try:
        await ChangeRoutingService.approve_deviation(
            db, change, current_user.id,
            acting=is_acting(current_user))
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
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    # Spec §16 P1-4: reject, cancel, hold, recall and closing the assessment
    # are the change lead's, Project Management's or an admin's; kickoff
    # (and a rejection at capture) also Sales'.
    from app.services.early_stage_service import EarlyStageService
    refusal = await EarlyStageService.transition_refusal(
        db, change, current_user, body.to_status)
    if refusal:
        raise HTTPException(status_code=403, detail=refusal)
    # The quote stage is Sales' own: starting the offer and declaring it sent
    # are both statements about the customer relationship, and nobody else is
    # in a position to make them. Enforced here, like every other role gate in
    # this module, so the service stays callable by the flows that drive
    # transitions internally.
    if ((change.status, body.to_status) in ChangeService.QUOTE_STAGE_TRANSITIONS
            and not await ChangeService.user_can_run_quote_stage(
                db, current_user, change, to_status=body.to_status)):
        raise HTTPException(
            status_code=403,
            detail=("Only Project Management, a Sales department member, the "
                    "change lead or an admin may close costing"
                    if body.to_status == "quoting" else
                    "Only a Sales department member, the change lead or an "
                    "admin may create and send the quote"))
    # Pulling the change back into costing reopens numbers that were declared
    # complete: the same people who may close costing may reopen it.
    if ((change.status, body.to_status) == ChangeService.COSTING_REOPEN
            and not await ChangeService.user_can_reopen_costing(db, current_user, change)):
        raise HTTPException(
            status_code=403,
            detail="Only Project Management, a Sales department member, the "
                   "change lead or an admin may reopen costing")
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
    # Releasing and closing a released change are the programme's calls:
    # Project Management, the change lead or an admin (acting-as aware, like
    # the release tab). (Only for a hop that exists: an illegal one keeps its
    # 400.)
    if (body.to_status in ("released", "closed") and body.to_status
            in ALLOWED_TRANSITIONS.get(change.status, set())):
        from app.services.release_service import ReleaseService
        allowed = await ReleaseService.is_pm_or_lead(db, change, current_user)
        # Closing a rejection is the end of the customer conversation (the
        # letter went out): Sales closes it too.
        if (not allowed and change.status == "rejected"
                and body.to_status == "closed"):
            allowed = await ChangeService._user_in_department(
                db, current_user, "Sales")
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail=("Only Sales, Project Management, the change lead or an "
                        "admin may close a rejected change"
                        if change.status == "rejected" else
                        "Only Project Management, the change lead or an admin "
                        f"may move a change to '{body.to_status}'"))
    # Mother plant (spec §14): scoping -> approved is the PM's call, like
    # sending the information that gates it.
    if change.status == "scoping" and body.to_status == "approved":
        from app.services import mother_plants as mp
        from app.services.mother_plant_service import MotherPlantService
        if (mp.is_mother_plant(change)
                and not await MotherPlantService.may_send(db, change, current_user)):
            raise HTTPException(
                status_code=403,
                detail="Only Project Management, the change lead or an admin "
                       f"may approve a change from {mp.plant_name(change)}")
    try:
        await ChangeService.transition(
            db, change, body.to_status, current_user.id,
            cancellation_reason=body.cancellation_reason,
            rejection_reason=body.rejection_reason,
            reopen_reason=body.reopen_reason,
            reason=body.reason or body.escalation_reason,
        )
    except DeviationRequired as e:
        # An approved deviation would lift this refusal. With a
        # deviation_reason the request is filed right here (final walk P2-3):
        # 202 and the deviation, for the lead (or an admin) to decide.
        # Without one: the 400 as before, plus headers saying a deviation
        # would do (and which one is already waiting).
        # The rollback expires every loaded object, the user included: read
        # what the rest needs first, and reload the user afterwards.
        await db.rollback()
        await db.refresh(current_user)
        dev_reason = (body.deviation_reason or "").strip()
        if not dev_reason:
            headers = {"X-Deviation-Required": e.to_status}
            if e.pending_deviation_id is not None:
                headers["X-Deviation-Pending"] = str(e.pending_deviation_id)
            raise HTTPException(status_code=400, detail=str(e), headers=headers)
        change = await ChangeService.get_change(db, change_id, viewer=current_user)
        dev = next((d for d in change.transition_deviations
                    if d.id == e.pending_deviation_id), None)
        created = dev is None
        if created:
            try:
                dev = await ChangeService.propose_transition_deviation(
                    db, change, e.to_status, dev_reason, current_user.id)
            except ChangeError as err:
                raise HTTPException(status_code=400, detail=str(err))
            await db.commit()
            await db.refresh(dev)
        row = (await _deviation_rows(db, change, [dev], current_user))[0]
        return JSONResponse(status_code=202, content=jsonable_encoder({
            "deviation_requested": True,
            "created": created,
            "to_status": e.to_status,
            "blocked_by": e.guard_reason,
            "detail": (f"{e.guard_reason}. Deviation #{dev.id} requested: the "
                       "change lead or an admin decides it"
                       if created else
                       f"{e.guard_reason}. Deviation #{dev.id} is already "
                       "waiting for its decision"),
            "deviation": row,
        }))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return await _price_safe(db, change, current_user, ChangeResponse)


@router.post("/{change_id}/impacted-items", response_model=ImpactedItemResponse)
async def add_impacted_item(
    change_id: int, body: ImpactedItemCreate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    from app.services.early_stage_service import EarlyStageService
    refusal = await EarlyStageService.impact_edit_refusal(db, change, current_user)
    if refusal:
        raise HTTPException(status_code=403, detail=refusal)
    try:
        before = await EarlyStageService.begin_impact_edit(db, change, body.reason)
        item = await ChangeService.add_impacted_item(
            db, change, body.part_id, current_user.id,
            impact_note=body.impact_note, eng_level_before=body.eng_level_before,
            is_lead=body.is_lead,
        )
        await EarlyStageService.finish_impact_edit(
            db, change, current_user.id, body.reason, before, [body.part_id])
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/{change_id}/impacted-items/{item_id}", status_code=204)
async def remove_impacted_item(
    change_id: int, item_id: int,
    reason: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    from app.services.early_stage_service import EarlyStageService
    refusal = await EarlyStageService.impact_edit_refusal(db, change, current_user)
    if refusal:
        raise HTTPException(status_code=403, detail=refusal)
    try:
        item = next((i for i in change.impacted_items if i.id == item_id), None)
        before = await EarlyStageService.begin_impact_edit(db, change, reason)
        await ChangeService.remove_impacted_item(db, change, item_id, current_user.id)
        await EarlyStageService.finish_impact_edit(
            db, change, current_user.id, reason, before,
            [item.part_id] if item else [])
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()


@router.get("/{change_id}/impact-tree")
async def get_impact_tree(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return await ChangeService.get_impact_tree(db, change)


@router.post("/{change_id}/impact-tree/suggest")
async def suggest_impact_rollups(
    change_id: int, body: ImpactSuggestIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
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
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    # Spec §16 P1-5: the change lead, Project Management or an admin.
    from app.services.early_stage_service import EarlyStageService
    refusal = await EarlyStageService.impact_edit_refusal(db, change, current_user)
    if refusal:
        raise HTTPException(status_code=403, detail=refusal)
    try:
        prior = {i.part_id for i in change.impacted_items}
        before = await EarlyStageService.begin_impact_edit(db, change, body.reason)
        await ChangeService.apply_impact_selection(
            db, change, body.part_ids, current_user.id)
        await EarlyStageService.finish_impact_edit(
            db, change, current_user.id, body.reason, before,
            sorted(prior ^ set(body.part_ids)))
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
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    from app.services.early_stage_service import EarlyStageService
    refusal = await EarlyStageService.impact_edit_refusal(db, change, current_user)
    if refusal:
        raise HTTPException(status_code=403, detail=refusal)
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
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
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
    return await _price_safe(db, change, current_user, ChangeResponse)


@router.post("/{change_id}/assessments", response_model=AssessmentResponse)
async def submit_assessment(
    change_id: int, body: AssessmentSubmit,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
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
    return await _assessment_out(db, a, current_user)


@router.post("/{change_id}/assessments/{assessment_id}/accept",
             response_model=AssessmentResponse)
async def accept_assessment(
    change_id: int, assessment_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        a = await ChangeService.accept_assessment(db, change, assessment_id, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(a)
    return await _assessment_out(db, a, current_user)


@router.post("/{change_id}/assessments/{assessment_id}/assign",
             response_model=AssessmentResponse)
async def assign_assessment(
    change_id: int, assessment_id: int, body: AssessmentAssignIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        a = await ChangeService.assign_assessment(
            db, change, assessment_id, body.user_id, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(a)
    return await _assessment_out(db, a, current_user)


@router.put("/{change_id}/assessments/{assessment_id}/due-date",
            response_model=AssessmentResponse)
async def set_assessment_due_date(
    change_id: int, assessment_id: int, body: AssessmentDueDateIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        a = await ChangeService.set_assessment_due_date(
            db, change, assessment_id, body.due_date, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(a)
    return await _assessment_out(db, a, current_user)


# Who may change which header field through PATCH. Mirrors the editors the
# UI offers (PriorityEditor, CustomerRelevantEditor, DescriptionEditor, the
# deadline chips, the D1 panel) so the server enforces what the screen shows.
# Acts-as aware: effective_role drops the admin bypass for an acting admin.
_PATCH_RIGHTS = {
    # the lead hands the change over; PM re-assigns it
    "lead_id": ("lead", "pm"),
    # money: the cost roles
    "estimated_cost": ("lead", "pm", "sales"),
    "pnl_note": ("lead", "pm", "sales"),
    # the lead steers the change
    "priority": ("lead",),
    "customer_relevant": ("lead",),
    # capture fields: Sales writes the request, the lead owns it. PM writes
    # them too where it is who captures (a mother-plant change) or
    # while nobody leads the change yet (captured/scoping): "pm_capture".
    "title": ("lead", "sales", "pm_capture"),
    "reason": ("lead", "sales", "pm_capture"),
    "description": ("lead", "sales", "pm_capture"),
    "change_type": ("lead", "sales"),
    # deadlines: whoever owns the quote / release date
    "required_by_date": ("lead", "sales", "pm"),
    "required_by_reason": ("lead", "sales", "pm"),
    "release_due_date": ("lead", "sales", "pm"),
    "release_due_reason": ("lead", "sales", "pm"),
    # timing anchor: the plan editors
    "timing_milestone_id": ("lead", "sales", "pm", "scheduling"),
    # D1 master data: the governance roles
    "issuer": ("lead", "quality", "pm"),
    "car_line": ("lead", "quality", "pm"),
    "is_series": ("lead", "quality", "pm"),
    "cm_internal": ("lead", "quality", "pm"),
    "cm_external": ("lead", "quality", "pm"),
    "implementation_mode": ("lead", "quality", "pm"),
    "affected_plant_ids": ("lead", "quality", "pm"),
}
_PATCH_ROLE_DEPT = {"sales": "Sales", "quality": "Quality",
                    "scheduling": "Scheduling"}


def _patch_changes_field(change, key, value) -> bool:
    """Does this PATCH value actually move the field? Unchanged values (the
    D1 panel resends every field) need no right."""
    if key == "affected_plant_ids":
        return value is not None and sorted(value) != sorted(
            p.id for p in change.affected_plants)
    if key in ("required_by_date", "release_due_date",
               "required_by_reason", "release_due_reason"):
        # these honor an explicit null (clearing), so None can move them
        return value != getattr(change, key)
    # update_change skips None for the plain fields: a None moves nothing
    return value is not None and value != getattr(change, key, None)


async def _require_patch_rights(db: AsyncSession, change, fields: dict,
                                user: User) -> None:
    moving = [k for k, v in fields.items()
              if k in _PATCH_RIGHTS and _patch_changes_field(change, k, v)]
    if not moving or user.effective_role == "admin":
        return
    held: dict[str, bool] = {}

    async def has(role: str) -> bool:
        if role not in held:
            if role == "lead":
                # acting as a department drops the personal lead privilege
                from app.services.change_people import holds_lead
                held[role] = holds_lead(change, user)
            elif role == "pm":
                held[role] = await MeetingService.user_is_pm_member(db, user)
            elif role == "pm_capture":
                from app.services import mother_plants as mp
                pm_window = mp.is_mother_plant(change) or (
                    change.status in ("captured", "scoping")
                    and change.lead_id is None)
                held[role] = pm_window and await has("pm")
            else:
                held[role] = await ChangeService._user_in_department(
                    db, user, _PATCH_ROLE_DEPT[role])
        return held[role]

    for key in moving:
        allowed = False
        for role in _PATCH_RIGHTS[key]:
            if await has(role):
                allowed = True
                break
        if not allowed:
            who = ", ".join(dict.fromkeys(
                {"lead": "the change lead", "pm": "Project Management",
                 "pm_capture": "Project Management",
                 "sales": "Sales", "quality": "Quality",
                 "scheduling": "Scheduling"}[r]
                for r in _PATCH_RIGHTS[key]))
            raise HTTPException(
                status_code=403,
                detail=f"Only {who} or an admin may change {key}")


@router.patch("/{change_id}", response_model=ChangeResponse)
async def update_change(
    change_id: int, body: ChangeUpdate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    fields = body.model_dump(exclude_unset=True)
    if "quoted_price" in fields and fields["quoted_price"] != change.quoted_price:
        if not await ChangeService.user_can_set_quoted_price(db, current_user, change):
            raise HTTPException(
                status_code=403,
                detail="Only the change lead, a Sales department member, or "
                       "an admin may set the quoted price")
    await _require_patch_rights(db, change, fields, current_user)
    if "lead_id" in fields and fields["lead_id"] is not None \
            and fields["lead_id"] != change.lead_id:
        new_lead = await _require_org_user(
            db, fields["lead_id"], await _project_org_id(db, change.project_id))
        await ChangeService.append_changelog(
            db, change, "lead_changed",
            f"Change lead {change.lead_id} -> {new_lead.id}", current_user.id,
            field_name="lead_id", old_value=change.lead_id, new_value=new_lead.id)
    # A hand-typed title stops following the lead item (spec §16).
    if fields.get("title") is not None and fields["title"] != change.title:
        change.title_auto = False
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
    return await _price_safe(db, change, current_user, ChangeResponse)


@router.post("/{change_id}/customer-response", response_model=ChangeResponse)
async def customer_response(
    change_id: int, body: CustomerResponseRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    from app.services.negotiation_service import NegotiationService
    # The customer's answer to a price is Sales' to record: the same people
    # who may write the price (Sales, the change lead, admin).
    if not await NegotiationService.may_write(db, change, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only Sales, the change lead or an admin may record the "
                   "customer response")
    try:
        await ChangeService.record_customer_response(
            db, change, body.response, current_user.id,
            release_due_date=body.release_due_date,
            release_due_reason=body.release_due_reason,
            expired_override_reason=body.expired_override_reason)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return await _price_safe(db, change, current_user, ChangeResponse)


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
    return await _price_safe(db, change, current_user, ChangeResponse)


@router.post("/{change_id}/sign-off", response_model=ChangeResponse)
async def sign_off(
    change_id: int, body: SignOffRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
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
    return await _price_safe(db, change, current_user, ChangeResponse)


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
    return await _price_safe(db, change, current_user, ChangeResponse)


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
    return await _price_safe(db, change, current_user, ChangeResponse)


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
    return await _price_safe(db, change, current_user, ChangeResponse)


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
    return await _price_safe(db, change, current_user, ChangeResponse)


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
    # The validation issue this evidence or customer mail is filed into
    # (spec §12; kinds general / customer_email; owner department, PM,
    # lead, Sales, admin while the issue is open).
    validation_issue_id: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")
    # The mother plant's timing seeds the detailed plan at approval: refuse
    # a file that could not be imported now, not weeks later.
    from app.services import mother_plants as mp
    if kind == mp.TIMING_ATTACHMENT_KIND:
        from app.services.mother_plant_service import check_timing_file
        if not mp.is_mother_plant(change):
            raise HTTPException(
                status_code=400,
                detail="This timing file belongs to a change from "
                       f"{mp.FALLBACK_NAME}")
        try:
            check_timing_file(contents)
        except ChangeError as e:
            raise HTTPException(status_code=400, detail=str(e))
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
            validation_issue_id=validation_issue_id,
        )
    except ChangeError as e:
        os.remove(stored_path)      # do not leave an orphan on a rejected upload
        raise HTTPException(status_code=400, detail=str(e))
    except (IssueForbidden, IssueNotFound) as e:
        os.remove(stored_path)
        raise HTTPException(
            status_code=403 if isinstance(e, IssueForbidden) else 404, detail=str(e))
    await db.commit()
    return {"id": att.id, "filename": att.filename, "size_bytes": att.size_bytes,
            "kind": att.kind, "responds_to_id": att.responds_to_id,
            "concern_id": att.concern_id, "assessment_id": att.assessment_id,
            "costing_offer_id": att.costing_offer_id,
            "validation_issue_id": att.validation_issue_id}


@router.get("/{change_id}/attachments/{attachment_id}/download")
async def download_attachment(
    change_id: int, attachment_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.costing_position_service import CostingPositionService
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    att = await db.get(ChangeAttachment, attachment_id)
    if not att or att.change_id != change.id or not os.path.exists(att.stored_path):
        raise HTTPException(status_code=404, detail="Attachment not found")
    # A vendor quote is its offer's price on paper: readable by whoever may
    # read that costing position, nobody else.
    if att.id in await CostingPositionService.unreadable_attachment_ids(
            db, change, current_user, [att]):
        raise HTTPException(
            status_code=403,
            detail="Only that department, Project Management, Sales, the "
                   "change lead or an admin may read this vendor quote")
    return FileResponse(att.stored_path, filename=att.filename,
                        media_type=att.content_type or "application/octet-stream")


async def _require_attachment_delete(db: AsyncSession, change, att,
                                     user: User) -> None:
    """Who may remove a (non-quote) document.

    Every kind defaults to: the uploader, the change lead, Project Management
    or an admin. Evidence filed on an (existing) assessment follows the right
    to file it instead (_may_attach_evidence); once that assessment is
    submitted its post-scoping evidence is the record the verdict stands on.
    Decision records freeze the same way: the rejection letter once the
    rejection is sent, anything filed into a concern once it is settled.
    Frozen means 409 for everyone but an admin (not one acting as a
    department). Vendor quotes are checked by the caller (position write)."""
    from app.models.change import ChangeConcern
    is_admin = user.effective_role == "admin"

    def frozen(detail: str):
        if not is_admin:
            raise HTTPException(status_code=409, detail=detail)

    if att.kind == "rejection_letter" and change.rejection_sent_at is not None:
        frozen("The rejection was sent: its letter is the record and cannot "
               "be removed")
    if att.concern_id is not None:
        concern = await db.get(ChangeConcern, att.concern_id)
        if concern is not None and not concern.is_open:
            frozen("That concern is settled: the documents it was settled on "
                   "cannot be removed")
    if att.validation_issue_id is not None:
        from app.services.validation_issue_service import ValidationIssueService
        why = await ValidationIssueService.frozen_attachment(db, att)
        if why:
            frozen(why)
    a = (await db.get(ChangeAssessment, att.assessment_id)
         if att.assessment_id is not None else None)
    if a is not None and a.change_id == change.id:
        if not await ChangeService._may_attach_evidence(db, change, a, user):
            raise HTTPException(
                status_code=403,
                detail="Only a member of the assessed department, the "
                       "change lead, Project Management, Sales or an "
                       "admin may remove that assessment's evidence")
        submitted = (a.submitted_at is not None
                     or a.effective_status == "submitted")
        if submitted and att.phase == "post_scoping":
            frozen("The assessment is submitted: its evidence is the record "
                   "the verdict stands on and cannot be removed")
        return
    if att.kind == "vendor_quote":
        return      # the position write rule, checked by the caller
    # Everything else, and evidence whose assessment is gone: the default.
    if (is_admin or att.uploaded_by == user.id
            or (change.lead_id is not None and change.lead_id == user.id)
            or await MeetingService.user_is_pm_member(db, user)):
        return
    raise HTTPException(
        status_code=403,
        detail="Only the uploader, the change lead, Project Management or "
               "an admin may remove that document")


@router.delete("/{change_id}/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    change_id: int, attachment_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    att = await db.get(ChangeAttachment, attachment_id)
    if not att or att.change_id != change_id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    # A vendor quote goes with its offer: only whoever may write that costing
    # position may remove it (same rule as filing it).
    from app.services.costing_position_service import CostingPositionService
    owners = await CostingPositionService.quote_department_ids(db, [att])
    if att.id in owners and not await CostingPositionService.may_write(
            db, change, owners[att.id] or 0, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only a member of the costing department, Project "
                   "Management or an admin may remove that vendor quote")
    await _require_attachment_delete(db, change, att, current_user)
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
    from app.services.costing_position_service import CostingPositionService
    a = await db.get(ChangeAssessment, aid)
    if not a or a.change_id != change_id:
        raise HTTPException(status_code=404, detail="Assessment not found")
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if change is None:
        raise HTTPException(status_code=404, detail="Change not found")
    # The cost roles read every department's grid; a department member reads
    # their own department's only (same rule as the costing positions).
    visible = await CostingPositionService.readable_department_ids(
        db, change, current_user)
    if visible is not None and a.department_id not in visible:
        raise HTTPException(
            status_code=403,
            detail="Only that department, Project Management, Sales, the "
                   "change lead or an admin may read its cost lines")
    if await CostService.seed_from_checklist(
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
    from app.services.costing_position_service import CostingPositionService
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    a = await db.get(ChangeAssessment, aid)
    if not change or not a or a.change_id != change_id:
        raise HTTPException(status_code=404, detail="Assessment not found")
    # Same write rule as the costing positions: the department itself while
    # the change is in costing, Project Management and admins at any time.
    if not await CostingPositionService.may_write(
            db, change, a.department_id, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only a member of that department while the change is in "
                   "costing, Project Management or an admin may change its "
                   "cost lines")
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


@router.put("/{change_id}/costing/offers/{oid}/choose",
            response_model=CostingOfferResponse)
async def choose_costing_offer(
    change_id: int, oid: int, body: VendorChoiceIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Sales decides which vendor gets the order.

    The department's favorite is a RECOMMENDATION and stays visible as one;
    this is the decision, and it carries a name and a timestamp. Choosing
    against the recommendation needs a reason — refused with 400 otherwise —
    while agreeing with it does not. One chosen offer per position: the
    decision moves rather than accumulating.
    """
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
    if not await CostingPositionService.may_choose_vendor(
            db, change, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only Sales, the change lead or an admin may choose the "
                   "vendor, and only while the change is being quoted — the "
                   "department recommends, Sales decides")
    try:
        offer = await CostingPositionService.choose_offer(
            db, change, offer, body.reason, current_user)
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
    return await _assessment_out(db, a, current_user)


@router.get("/{change_id}/summation", response_model=SummationResponse)
async def get_summation(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.cost_service import CostService
    from app.services.negotiation_service import NegotiationService
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if not await NegotiationService.may_read(db, change, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only Project Management, Sales, the change lead or an "
                   "admin may read the cost summation")
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
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
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
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return await _deviation_rows(db, change, change.transition_deviations, current_user)


async def _deviation_rows(db, change, devs, user) -> list[dict]:
    from app.services.change_plan_service import ChangePlanService
    names = await ChangePlanService._user_names(
        db, [d.proposed_by for d in devs] + [d.decided_by for d in devs])
    return [{
        **TransitionDeviationResponse.model_validate(d).model_dump(),
        "can_decide": (d.status == "pending"
                       and ChangeService.transition_deviation_refusal(
                           change, d, user) is None),
        "proposed_by_name": names.get(d.proposed_by),
        "decided_by_name": names.get(d.decided_by),
    } for d in devs]


@router.post("/{change_id}/deviations", response_model=TransitionDeviationResponse)
async def propose_deviation(
    change_id: int, body: DeviationProposeIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
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
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
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
            channel=body.channel, department_rasic=body.department_rasic,
            cost_carrier=body.cost_carrier)
    except MeetingForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
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
    except MeetingForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
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
            counter_price=body.counter_price, is_final=body.is_final,
            offer_id=body.offer_id)
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
    # Who asks matters as much as what is asked: each row carries the asker's
    # department memberships (their role in the room) and the answerer's name,
    # so the card never shows a bare username — or worse, a '#id'.
    user_ids = ({c.raised_by for c in change.concerns}
                | {c.answered_by for c in change.concerns
                   if c.answered_by is not None}
                | {c.withdrawn_by for c in change.concerns
                   if c.withdrawn_by is not None})
    dept_names: dict[int, list[str]] = {}
    names: dict[int, str] = {}
    if user_ids:
        for uid, dname in await db.execute(
                select(UserDepartment.user_id, Department.name)
                .join(Department, Department.id == UserDepartment.department_id)
                .where(UserDepartment.user_id.in_(user_ids))):
            dept_names.setdefault(uid, []).append(dname)
        for uid, full_name in await db.execute(
                select(User.id, User.full_name).where(User.id.in_(user_ids))):
            names[uid] = full_name
    out = []
    # Risk types read as words, a department's own types included (§16).
    from app.services.risk_types import labels_for_keys
    type_labels = await labels_for_keys(db, {c.risk_type for c in change.concerns})
    # A risk deleted by its raiser is gone from the register; the changelog
    # keeps the record.
    for c in (c for c in change.concerns if c.retracted_at is None):
        row = ConcernResponse.model_validate(c)
        row.raised_by_departments = sorted(dept_names.get(c.raised_by, []))
        if c.answered_by is not None:
            row.answered_by_name = names.get(c.answered_by)
        if c.withdrawn_by is not None:
            row.withdrawn_by_name = names.get(c.withdrawn_by)
        if c.risk_type:
            row.risk_type_label = type_labels.get(c.risk_type)
        out.append(row)
    return out


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
            risk_type=body.risk_type, severity=body.severity,
            checklist_key=body.checklist_key)
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


@router.post("/{change_id}/concerns/{concern_id}/retract",
             response_model=ConcernResponse)
async def retract_concern(
    change_id: int, concern_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Its raiser deletes a risk raised by mistake (hidden, kept on record)."""
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        concern = await MeetingService.retract_concern(
            db, change, concern_id, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(concern)
    return concern


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
    except MeetingForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
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
    from app.services.price_redaction import PriceViewer
    change = await _implementation_change(db, change_id, current_user)
    state = await ValidationService.state(db, change)
    await db.commit()
    # The acknowledgement note is Sales' word on the quote update (often an
    # amount): the cost roles read it, everybody else sees that it happened.
    if not await PriceViewer(db, current_user).may_read(change):
        state["weight_ack_note"] = None
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
    return await _price_safe(db, change, current_user, ChangeResponse)
