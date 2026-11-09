# backend/app/api/v1/changes/changes.py
"""Change Management endpoints - the change lifecycle spine."""
import hashlib
import logging
import os
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import (
    APIRouter, BackgroundTasks, Depends, HTTPException, Query, File, Form, UploadFile, status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.change import (
    ChangeChangelog, ChangeAttachment, ChangeRequest, ChangeAssessment,
    ChangeImpactedItem, SIGN_OFF_ROLES, BLOCKING_LETTERS,
)
from app.models.workflow import UserDepartment, Department
from app.models.part import Part
from app.services.change_service import (
    ALLOWED_TRANSITIONS, ChangeService, ChangeError, DeviationDecideForbidden, DeviationRequired,
    _org_scope,
)
from app.services.workflow_service import WorkflowService
from app.services.meeting_service import MeetingForbidden, MeetingService
from app.services.validation_issue_service import IssueForbidden, IssueNotFound
from app.services.change_people import holds_lead, is_acting
from app.schemas.change import (
    ChangeCreate, ChangeUpdate, ChangeResponse, ChangeDetailResponse,
    TransitionRequest, HoldReviewRequest, ImpactedItemCreate, ImpactedItemResponse,
    AssessmentSubmit, AssessmentResponse, AssessmentAssignIn, AssessmentDueDateIn,
    CustomerResponseRequest, SignOffRequest,
    ChangelogResponse,
    RoutingResponse, RoutingStage, RoutingDepartment, DeviationRequest, RoutingDeviationDecision,
    RiskTemplateCreate, RiskTemplateResponse, RiskTypeCreate, RiskTypeResponse,
    CostCategoryCreate, CostCategoryResponse,
    RoutingStandardUpsert,
    CostLineReplace, CostLineResponse, SummationResponse,
    GateDecisionIn, GateResponse,
    DeviationProposeIn, DeviationDecideIn, TransitionDeviationResponse, AbsorbIn,
    CheckStandardIn, CheckStandardResponse,
    ImpactSuggestIn, ImpactSelectionIn,
    MeetingCreate, MeetingUpdate, MeetingDecideIn, MeetingResponse,
    NegotiationCreate, NegotiationResponse,
    ConcernCreate, ConcernResponse, ConcernWithdrawIn, ConcernAnswerIn,
    ConcernTypeIn, ConcernJoinIn, ConcernConfirmIn, CheckCloseIn, CheckReopenIn, EstimateCheckIn, PpapDecisionIn, CustomerFlipAnswerIn,
    RecheckAnswerIn, IndexScopeIn, IndexDeadlineIn, NeedByTellIn,
    ScopeDefinitionIn,
    CostLeadTimeIn, WeightEstimateIn, BankBuildIn, ChangeoverOfferIn,
    InternalApprovalIn,
    CostingPositionCreate, CostingPositionUpdate, CostingPositionResponse,
    CostingOfferCreate, CostingOfferUpdate, CostingOfferResponse,
    VendorChoiceIn,
    ImplementationBookingCreate, ImplementationBookingResponse,
    ImplementationReportCreate, ImplementationReportResponse,
    ImplementationEscalationCreate, ImplementationEscalationResolveIn,
    ImplementationEscalationResponse, ImplementationStateResponse,
    ValidationCheckIn, ValidationCheckResponse, ValidationLimitsIn, ValidationStateResponse,
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
                            org_id: Optional[int], role: str = "Lead") -> User:
    """An active user of `org_id` (any org when the change has no project),
    else 400 - a lead from another organization would see nothing of it."""
    u = await db.get(User, user_id)
    if u is None or not u.is_active or (
            org_id is not None and u.organization_id != org_id):
        raise HTTPException(status_code=400, detail=f"{role} user not found")
    return u


@router.post("", response_model=ChangeResponse)
async def create_change(
    body: ChangeCreate,
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services import mother_plants as mp
    from app.services.mother_plant_service import MotherPlantService
    mother_plant = body.origin == mp.MOTHER_PLANT
    if body.customer_relevant is None and not mother_plant:
        # An API caller that leaves the cost carrier out raises what its
        # department starts: Project Management a customer change,
        # everyone else an internal one. The UI always sends it.
        body.customer_relevant = await ChangeService.in_starter_department(
            db, current_user)
    internal = not mother_plant and not body.customer_relevant
    allowed = (await MotherPlantService.may_start(db, current_user) if mother_plant
               else await ChangeService.user_can_start_change(db, current_user))
    # P3 + D1: Development, Process, Tool and Manufacturing Engineer start internal
    # changes (never a customer one) and lead them.
    engineering_raiser = (internal and await ChangeService
                          .in_internal_starter_department(db, current_user))
    if not allowed and engineering_raiser:
        allowed = True
    if not allowed:
        may_internal = (not mother_plant and await ChangeService
                        .in_internal_starter_department(db, current_user))
        raise HTTPException(
            status_code=403,
            detail=("Only Project Management (or an admin) may raise a "
                    f"change from {mp.plant_name(body)}" if mother_plant else
                    "Your department starts internal changes only: a customer "
                    "change is captured by Project Management"
                    if may_internal else
                    await ChangeService.who_starts_changes(db)))
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
    # P3: an internal change raised by engineering is led by its raiser
    # (spec §0), unless Project Management named a lead. An admin acting as
    # an engineering department is not a raiser-lead (C32: acting drops the
    # personal lead right): the project PM default applies, else PM picks.
    if lead_id is None and engineering_raiser and not is_acting(current_user):
        lead_id = current_user.id
    if lead_id is not None:
        await _require_org_user(db, lead_id, project_org)
    # C10 (Christoph 2026-10-26, migration 152): Project Management captures;
    # the Sales contact is the project's Sales responsible, else its backup
    # (ChangeService.default_sales_owner_id), else Project Management picks
    # a Sales member. The raiser is no Sales contact.
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
        # §2 (SCOPING_V2): the urgent need-by, reason and evidence, and the
        # internal problem and target, travel with the capture.
        from app.services import capture_rules
        for k in ("urgent_reason", "urgent_evidence", "problem_value",
                  "problem_unit", "target_value"):
            v = getattr(body, k)
            if v is not None:
                setattr(change, k, v.strip() if isinstance(v, str) else v)
        if (body.release_due_date is not None and body.priority == "critical"
                and capture_rules.v2() and capture_rules._plain(change)):
            await ChangeService._apply_release_deadline(
                db, change, body.release_due_date, "Need-by (urgent)", current_user.id)
        why = capture_rules.urgent_refusal(change)
        if why:
            raise ChangeError(why)
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
    if body.impacted_part_ids:
        _refresh_tool_tonnage(background, change.id)
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
    owing = await ChangeService.owing_change_ids(db, current_user, changes)
    for change in changes:
        change.deadline_state = await ChangeService.deadline_state(db, change)
        row = ChangeResponse.model_validate(change)
        row.from_intake = change.id in from_intake
        # "Mine" filter (spec §16, C10): the caller leads, raised or owns the
        # customer side of it, or one of their departments owes work here.
        row.is_mine = (not acting and current_user.id in (
            change.lead_id, change.raised_by, change.sales_owner_id)) \
            or change.id in owing
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
    from app.services.project_team_service import ProjectTeamService
    return {
        "can_start_change": await ChangeService.user_can_start_change(db, current_user),
        # P3 + D1: internal changes only (Development, Process, Tool, Manufacturing Engineer).
        "can_start_internal_change": await ChangeService.user_can_start_internal_change(
            db, current_user),
        # Mother-plant side track (spec §14): Project Management (and
        # admin) only, and the configured plants (default first).
        "can_start_mother_plant": await MotherPlantService.may_start(db, current_user),
        "mother_plants": list(mp.MOTHER_PLANTS),
        "default_mother_plant": mp.DEFAULT_MOTHER_PLANT,
        # the project team screen (responsible, D2b backup): the PUT's right
        "can_manage_team": (current_user.effective_role != "viewer"
                            and await ProjectTeamService.user_can_manage(db, current_user)),
    }


# Bookkeeping rows the app writes on the side: not "work done" for My Tasks.
_DONE_NOISE = ("title_recomposed", "metadata_updated", "price_opened", "price_closed",
               "plan_seeded", "cost_lines_seeded", "revision_spawned", "four_eyes_fallback")


@router.get("/my-done")
async def my_done(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """My Tasks "Show done" (Christoph 2026-10-28): what the caller did on
    changes in the last `days` days, newest first, from the audit history
    (change tasks are computed from the live state and leave no closed row of
    their own). Under act as person: that person's own entries."""
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(days=days)
    rows = (await db.execute(
        select(ChangeChangelog.id, ChangeChangelog.change_id, ChangeChangelog.action,
               ChangeChangelog.action_description, ChangeChangelog.performed_at,
               ChangeRequest.change_number, ChangeRequest.title)
        .join(ChangeRequest, ChangeRequest.id == ChangeChangelog.change_id)
        .where(ChangeChangelog.performed_by == current_user.id,
               ChangeChangelog.performed_at >= since,
               ChangeChangelog.action.not_in(_DONE_NOISE))
        .order_by(ChangeChangelog.performed_at.desc(), ChangeChangelog.id.desc())
        .limit(200))).all()
    return [{"id": i, "change_id": cid, "change_number": num, "title": title,
             "action": action, "description": desc, "at": at}
            for i, cid, action, desc, at, num, title in rows]


@router.get("/my-tasks")
async def my_change_tasks(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Every open piece of ECR work this caller's role owns — not just pending
    assessments. A change parked in a stage IS the open task of that stage's
    responsible role, so each stage contributes its own row kind:

      kickoff           captured, for a can_start_change department (Project
                        Manager); Sales gets "Supply the customer's facts"
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
      costing_input     this caller's department found the change feasible
                        (something impacted) and has not finalized its
                        costing yet: from its own assessment submit on, in
                        assessment or in costing
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
        from app.models.workflow import WfInstance as _WfI, WfInstanceTask as _WfT
        # Also outside assessment, on a live change: an R/A row somebody
        # added to the routing is still owed. Judged on the row's own task:
        # active, actionable and step-less (a deviation add outside the
        # template and the snapshot, or one added after its stage passed),
        # on an ACTIVE or COMPLETED instance: a late row does not vanish
        # when the instance finishes (it still holds costing -> quoting).
        # A row no task was ever made for carrying its own "active" counts
        # too (ChangeRoutingService.owed_stepless_rows, the cockpit).
        owed_task = ((_WfT.status == "active") & (_WfT.is_actionable.is_(True))
                     & _WfT.step_id.is_(None)
                     & _WfI.status.in_(("active", "completed")))
        unlinked_active = (ChangeAssessment.wf_instance_task_id.is_(None)
                           & (ChangeAssessment.status == "active")
                           & ChangeAssessment.rasic_letter.in_(BLOCKING_LETTERS))
        # A3-06: an answer sent back in costing (its task active again
        # behind the passed stage); the loop keeps only sent-back rows
        sent_back = ((ChangeRequest.status == "costing") & (_WfT.status == "active")
                     & _WfT.is_actionable.is_(True))
        late = ((owed_task | unlinked_active | sent_back)
                & ChangeRequest.status.notin_(
                    ("released", "closed", "rejected", "cancelled")))
        rows = await db.execute(
            select(ChangeAssessment, ChangeRequest)
            .join(ChangeRequest, ChangeRequest.id == ChangeAssessment.change_id)
            .outerjoin(_WfT, _WfT.id == ChangeAssessment.wf_instance_task_id)
            .outerjoin(_WfI, _WfI.id == _WfT.instance_id)
            .where(
                ChangeAssessment.department_id.in_(dep_ids)
                & (ChangeAssessment.verdict == "pending")
                & ((ChangeRequest.status == "in_assessment") | late)
            )
        )
        from app.services.early_stage_service import EarlyStageService
        from app.services import cm_switches as _cms
        checks_v2 = _cms.on("ASSESSMENT_V2")
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
        check_dept_names: dict[int, str] = {}
        for a, c in pairs:
            if not EarlyStageService.is_assessment_row(a, firsts.get(c.id)):
                continue
            # Execution state lives on the linked engine task; surface a row only
            # when it is *effectively* active (task active, or an unlinked row
            # carrying its own "active" status from a routing deviation).
            if a.effective_status != "active":
                continue
            # A3-06: in costing a stepped task is owed only once sent back
            if (c.status == "costing" and a.task is not None
                    and a.task.step_id is not None
                    and "sent_back" not in a.details_dict):
                continue
            # Only R/A letters OWE a submit. A Consulted/Support row activates
            # with its stage so the department may chime in, but its 'noted'
            # task gates nothing — queueing it as a task tells a department
            # that already did its Responsible work in an earlier stage that
            # it still owes something. Exception: a non-blocking row somebody
            # explicitly took (owner) is that person's to-do.
            # R18: so is a C/S department's that owns open check items
            # (spec §4): it closes them in its bucket, and nobody else may
            checks = (len([x for x in c.concerns if x.is_check and x.is_open
                           and a.department_id in x.owner_department_ids])
                      if c.status == "in_assessment" and checks_v2 else 0)
            if (a.rasic_letter not in BLOCKING_LETTERS
                    and a.effective_owner_id != current_user.id and not checks):
                continue
            # R5/R18: a consulted department's check-item row names what it
            # owes (checks_open, rendered by the UI), its department as the
            # owner, and a due date (the change's assessment due)
            check_row = bool(checks) and a.rasic_letter not in BLOCKING_LETTERS
            if check_row and a.department_id not in check_dept_names:
                check_dept_names[a.department_id] = (await db.execute(
                    select(Department.name).where(
                        Department.id == a.department_id))).scalar_one_or_none() or ""
            due = (MeetingService.check_due(c, a.department_id)
                   if check_row else a.effective_due_date)
            tasks.append({
                **({"hint": f"Close your check items ({checks})",
                    "checks_open": checks,
                    "department_name": check_dept_names[a.department_id]}
                   if check_row else {}),
                "kind": "assessment", "change_id": c.id, "change_number": c.change_number,
                "title": c.title,
                "project_id": c.project_id, "project_number": c.project_number,
                "project_name": c.project_name,
                "department_id": a.department_id, "assessment_id": a.id,
                "owner_id": a.effective_owner_id,
                "owner_name": a.effective_owner_name,
                # A6-10: "assigned to X" until X edits, then "X is working on this"
                "owner_started": EarlyStageService.owner_started(a),
                "accepted_at": a.effective_accepted_at,
                "due_date": due,
                "overdue": (due is not None and due < datetime.utcnow()
                            if check_row else a.effective_overdue),
                "mine": a.effective_owner_id == current_user.id,
            })

    # Every change that can still need something done to it. Not simply
    # "not terminal": 'rejected' counts as terminal for the flow, but a
    # rejected customer change still owes the customer a letter (send_rejection
    # below). Closed, released and cancelled owe nobody anything.
    open_changes = (await db.execute(_org_scope(
        select(ChangeRequest).where(
            ChangeRequest.status.not_in(("released", "closed", "cancelled"))),
        current_user,
    ))).scalars().all()

    tasks += await ChangeService.stage_tasks(db, current_user, open_changes, dep_ids)

    # C3: a released change still owes its close (lead / PM): the one row
    # a released change gives, with no other stage builder run on it.
    # Only the caller's own (lead) or lead-less ones (Project Management):
    # advance_tasks decides the rest, never over every released change (R34).
    # Lead-less ones, and those whose lead cannot act (read-only, inactive:
    # no lead, R18), are Project Management's: only its members read them.
    whose = ChangeRequest.lead_id == current_user.id
    if current_user.effective_role != "viewer" and await ChangeService.member_of(
            db, current_user, "Project Manager"):
        placed = (select(UserDepartment.user_id)
                  .join(Department, Department.id == UserDepartment.department_id)
                  .where(Department.is_active.is_(True)))
        idle = select(User.id).where(User.is_active.is_(False)
                                     | ((User.role == "viewer") & User.id.not_in(placed)))
        whose = whose | ChangeRequest.lead_id.is_(None) | ChangeRequest.lead_id.in_(idle)
    released = (await db.execute(_org_scope(
        select(ChangeRequest).where(ChangeRequest.status == "released", whose),
        current_user))).scalars().all()
    if released:
        async def _ident(c):
            return {"change_id": c.id, "change_number": c.change_number,
                    "title": c.title, "project_id": c.project_id,
                    "project_number": c.project_number,
                    "project_name": c.project_name,
                    "due_date": None, "overdue": False}
        tasks += await ChangeService.advance_tasks(db, current_user, released, _ident)
        open_changes = [*open_changes, *released]

    # One list (spec §16): no duplicate rows, a human kind label and the
    # stage each row belongs to.
    from app.services import cm_labels
    status_of = {c.id: c.status for c in open_changes}
    lead_of = {c.id: c.lead_id for c in open_changes}
    sales_owner_of = {c.id: (c.sales_owner_id, c.sales_owner_name or "")
                      for c in open_changes if c.sales_owner_id is not None}
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
               t.get("deviation_id"), t.get("side"),
               t.get("recheck_id"), t.get("intake_id"), t.get("scope_change_id"),
               t.get("department_id") if t["kind"] in ("costing_input", "costing_update",
                                                        "plan_feedback", "info_ack",
                                                        "release_check", "progress_report",
                                                        "validation_check", "estimate_check")
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
        owner = sales_owner_of.get(t["change_id"])
        t["is_mine"] = bool(t.get("mine")) or (
            not acting and lead_of.get(t["change_id"]) == current_user.id)
        # Project team (spec §18): "main" rows count on the badge and the
        # list header; "backup" rows (another responsible leads this role
        # on the project) stay listed, muted, with the main's name. A Sales
        # row names the change's Sales contact instead (C10).
        await team.annotate(t, t.get("project_id"), owned=t["is_mine"],
                            sales_owner=owner)
        if owner is not None and not acting and owner[0] == current_user.id \
                and t["role"] == "main" and await team.row_department(t) \
                == await team.department_id("Sales"):
            t["is_mine"] = True
        t.pop("role_department_id", None)
        unique.append(t)
    tasks = unique

    # C20: each row's due by the two rules (task 2 wd / 1 wd, the
    # assessment's own), its deadline, late (due + 1 wd) and "Needs you".
    from app.services import due_rules
    await due_rules.annotate_tasks(db, tasks, open_changes)
    # D2b: an overdue department task goes to the project's named backup too
    for t in tasks:
        await team.promote_overdue(t)
    # One order across every kind: "Needs you" on top by due; then mine,
    # overdue first, soonest due (undated last), change number.
    tasks.sort(key=due_rules.task_order)
    return tasks


@router.get("/my-escalations")
async def my_escalations(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await ChangeService.lead_escalations(db, current_user.id, current_user)


@router.get("/my-department-escalations")
async def my_department_escalations(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """My Tasks' "Late in my departments" (migration 149, Christoph
    2026-10-26): for a department manager, every escalated item of the
    departments they manage across all open changes (overdue_digest
    late_in_departments, the digest's own late items). Read-only: managing
    grants no write rights. The real user's managed departments, also
    while an admin acts as a department; an admin sees every
    organization. {departments: [] } = not a manager, the group hides."""
    from app.services.overdue_digest import late_in_departments
    depts = (await db.execute(select(Department.id, Department.name).where(
        Department.manager_id == current_user.id, Department.is_active.is_(True))
        .order_by(Department.sort_order, Department.name))).all()
    if not depts:
        return {"departments": [], "items": []}
    items = await late_in_departments(
        db, [d.id for d in depts],
        viewer=None if current_user.is_real_admin else current_user)
    return {"departments": [{"id": d.id, "name": d.name} for d in depts],
            "items": items}


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
    if current_user.effective_role != "admin":
        raise HTTPException(status_code=403, detail="Only an admin may set routing standards")
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
    from app.services.cost_sheet_service import can_read, reference_rates as sheet_rates
    sheet = await sheet_rates(db, current_user.organization_id)
    if sheet is None:
        from app.services.costing_rates import has_cost_sheet
        if await has_cost_sheet(db, current_user.organization_id):
            return []  # a cost sheet exists but none is valid today: no rates
        from app.models.change_cost import DepartmentRate
        rows = (await db.execute(select(DepartmentRate))).scalars().all()
        sheet = [{"department_id": r.department_id, "plant_id": r.plant_id,
                  "hourly_rate": r.hourly_rate, "min_factor": r.min_factor} for r in rows]
    if await can_read(db, current_user):
        return sheet
    # D-cost (Christoph 2026-10-19): the rate table is the cost roles'; a
    # costing department's grid needs its own rows only (acts-as aware)
    from app.services.workflow_service import WorkflowService
    mine = set(await WorkflowService.effective_department_ids(db, current_user))
    return [r for r in sheet if r["department_id"] in mine]


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
    from app.services import early_costing
    _ec = early_costing.state(change)
    change.costing_owed_department_ids = _ec["owed"]
    change.costing_finalized_department_ids = _ec["finalized"]
    change.costing_no_cost = {str(k): v for k, v in _ec["no_cost"].items()}
    # Christoph 2026-11-08: who finalized each department's costing and when,
    # for the PM overview's "Finalized by <name>, <date>"
    _fin: dict[str, dict] = {}
    _by_ids: set[int] = set()
    for _did in _ec["finalized"]:
        _row = early_costing.finalized_row(change, _did)
        if _row is None:
            continue
        _d = _row.details_dict
        _uid = _d.get("costing_finalized_by")
        _fin[str(_did)] = {"at": _d.get("costing_finalized_at"), "by": _uid}
        if isinstance(_uid, int):
            _by_ids.add(_uid)
    if _by_ids:
        _names = dict((await db.execute(
            select(User.id, User.full_name).where(User.id.in_(_by_ids)))).all())
        for _v in _fin.values():
            _v["by_name"] = _names.get(_v["by"])
    change.costing_finalized_info = _fin
    # spec §0/§4: the header's "Waiting on <vendor> since <date>": the
    # waits of the phase the change is in (a costing wait left open says
    # nothing once costing closed; it shows again if costing reopens)
    from app.services import supplier_wait_service as _sw
    change.open_supplier_waits = await _sw.serialize(
        db, await _sw.current_waits(db, [change]))
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
    # Audit P3-15: an unowned row names its project-team responsible
    from app.services.project_team_service import _responsible
    resp_cache: dict = {}
    for row in out.assessments:
        if row.owner_name is None and row.department_id is not None:
            if row.department_id not in resp_cache:
                r = await _responsible(db, change.project_id, row.department_id)
                resp_cache[row.department_id] = r[1] if r else None
            row.responsible_name = resp_cache[row.department_id]
    await fill_part_labels(db, out.impacted_items)
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
    out.next_step = await ChangeService.next_step_missing(db, change)
    if change.status in ("captured", "scoping"):
        from app.services.meeting_service import MeetingService
        out.can_raise_question = await MeetingService.may_raise_question(
            db, change, current_user)
    # §10-§11 (RELEASE_V2): the header shows any concession in force
    from app.services import cm_switches
    if cm_switches.on("RELEASE_V2") and change.status in (
            "in_implementation", "in_validation", "released", "closed"):
        from app.services.validation_issue_service import ValidationIssueService
        out.active_concessions = await ValidationIssueService.active_concessions(db, change)
    return out


class AchievedIn(BaseModel):
    value: float
    ref: str


@router.post("/{change_id}/achieved", response_model=ChangeResponse)
async def record_achieved(
    change_id: int, body: AchievedIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """§11: an internal change closes with what it achieved, beside the
    target (the lead, Project Management or an admin; with its evidence)."""
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await ChangeService.record_achieved(db, change, body.value, body.ref, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return await _price_safe(db, change, current_user, ChangeResponse)


# --- C15: book hours (any open change, until 7 days after close) ------------

class HoursIn(BaseModel):
    department_id: int
    hours: float
    work_date: Optional[str] = None
    booked_for: Optional[str] = None
    coordination: bool = False
    source: Optional[str] = None
    note: Optional[str] = None
    # Christoph 2026-11-09: the PM's 'Scoping effort' Book hours: the hours
    # count on Scoping effort whatever the change's status (before the offer)
    scoping: bool = False


@router.get("/{change_id}/hours")
async def get_hours(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """C15: booked vs estimated hours per department, the bookings, and the
    viewer's prefill ("your estimate: 6 h")."""
    from app.services.hours_service import HoursService
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return await HoursService.state(db, change, current_user)


@router.post("/{change_id}/hours", status_code=status.HTTP_201_CREATED)
async def book_hours(
    change_id: int, body: HoursIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """C15 "Book hours": department, hours, work date (back 21 days),
    optionally for a colleague; the lead's Coordination row."""
    from app.services.hours_service import HoursError, HoursForbidden, HoursService
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await HoursService.book(db, change, body.model_dump(), current_user)
    except HoursForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HoursError as e:
        raise HTTPException(status_code=400, detail=str(e))
    out = await HoursService.state(db, change, current_user)
    await db.commit()
    return out


class HoursPatch(BaseModel):
    hours: Optional[float] = None
    work_date: Optional[str] = None
    note: Optional[str] = None


@router.patch("/{change_id}/hours/{booking_id}")
async def correct_hours(
    change_id: int, booking_id: int, body: HoursPatch,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Christoph 2026-11-08: correct a booking (hours, day worked, note); the
    booker, its department (members, manager) or an admin, while the window
    is open."""
    from app.services.hours_service import HoursError, HoursForbidden, HoursService
    from app.services.implementation_service import (
        ImplementationError, ImplementationService,
    )
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        row = await ImplementationService.get_booking(db, change, booking_id)
    except ImplementationError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        await HoursService.correct(db, change, row, body.model_dump(exclude_unset=True),
                                   current_user)
    except HoursForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HoursError as e:
        raise HTTPException(status_code=400, detail=str(e))
    out = await HoursService.state(db, change, current_user)
    await db.commit()
    return out


@router.delete("/{change_id}/hours/{booking_id}")
async def delete_hours(
    change_id: int, booking_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """C15: take back a booking while the window is open. Christoph
    2026-11-08: the booker's, its department's (members, manager) or an
    admin's correction."""
    from app.services.hours_service import HoursService, window_open
    from app.services.implementation_service import (
        ImplementationError, ImplementationService,
    )
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        row = await ImplementationService.get_booking(db, change, booking_id)
    except ImplementationError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not await HoursService.may_correct(db, current_user, row):
        raise HTTPException(status_code=403, detail=(
            "A booking is corrected by the person who booked it, its department "
            "or an admin"))
    if not window_open(change):
        raise HTTPException(status_code=400, detail="The booking window of this change has ended")
    dept_id = row.department_id
    await ImplementationService.delete_booking(db, change, row, current_user)
    await HoursService.sync_assessment_effort(db, change, dept_id, current_user.id)
    out = await HoursService.state(db, change, current_user)
    await db.commit()
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


async def fill_part_labels(db, items) -> None:
    """Set part_number / part_name on ImpactedItemResponse rows with ONE
    query for the whole list (no lazy load per row)."""
    ids = {i.part_id for i in items}
    if not ids:
        return
    from app.models.part import Part
    parts = {pid: (num, name) for pid, num, name in (await db.execute(
        select(Part.id, Part.part_number, Part.name).where(Part.id.in_(ids)))).all()}
    for i in items:
        i.part_number, i.part_name = parts.get(i.part_id, (None, None))


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
    return await ChangeService.implementation_progress(db, change, viewer=current_user)


@router.get("/{change_id}/recommended-departments")
async def recommended_departments(
    change_id: int, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Departments to pre-mark in the scoping decision: the Responsible/
    Accountable assessors of the change type's stage-1 routing. The lead can
    then narrow the fan-out to those relevant for this specific change.
    optional = offered but not pre-marked (cm_switches.SCOPING_PRESELECT)."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import BLOCKING_LETTERS
    from app.models.workflow import Department
    from app.services import cm_switches
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if change is None:
        raise HTTPException(404, "Change not found")
    try:
        _, _, stages = await ChangeRoutingService.resolve_standard(db, change.change_type)
    except ChangeError:
        stages = []
    stage1 = next((s for s in stages if s["stage_order"] == 1), None)
    # Every stage-1 department with the letter the standard gives it: the
    # picker starts from the template's opinion, the room overrules it.
    letters = ({d["department_id"]: d["rasic_letter"] for d in stage1["departments"]}
               if stage1 else {})
    # §3 internal (SCOPING_V2): the raiser's department is auto-R; the room
    # may leave it out only with a reason (MeetingService)
    raiser = await MeetingService.raiser_department_id(db, change)
    if raiser is not None and letters.get(raiser) not in BLOCKING_LETTERS:
        letters[raiser] = "R"
    if not letters:
        return []
    rows = (await db.execute(
        select(Department.id, Department.name)
        .where(Department.id.in_(letters), Department.is_active.is_(True))
        .order_by(Department.sort_order, Department.name))).all()
    # R25: Management is never pre-marked for a task (Informed only).
    from app.services.cost_sheet_service import NON_ROUTABLE_DEPARTMENTS
    # Christoph 2026-10-28: the room starts from the standard four; the
    # standard's other assessors (Packaging) are offered, not pre-marked
    preselect = cm_switches.SCOPING_PRESELECT.get(change.change_type)

    def _optional(i: int, n: str) -> bool:
        return (preselect is not None and i != raiser and n not in preselect
                and letters[i] in BLOCKING_LETTERS)
    return [{"id": i, "name": n, "rasic_letter": letters[i],
             **({"raiser": True} if i == raiser else {}),
             **({"optional": True} if _optional(i, n) else {})} for i, n in rows
            if n not in NON_ROUTABLE_DEPARTMENTS or letters[i] == "I"]


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
    # A read never repairs (concurrent GETs raced each other into duplicate
    # tasks and forked the changelog chain): the write paths that open the
    # gap repair it, and an admin can POST /routing/repair.
    routing = change.routing
    # Key by (department, stage): departments appear in multiple stages of the
    # seeded templates, and each stage owns its own assessment row.
    # Read the rows fresh: the endpoints that answer with this view (the
    # deviation ops) have just added or re-lettered rows the cached
    # change.assessments collection does not carry yet.
    fresh = (await db.execute(
        select(ChangeAssessment).where(ChangeAssessment.change_id == change_id)
        .order_by(ChangeAssessment.stage_order, ChangeAssessment.id)
        .execution_options(populate_existing=True))).scalars().all()
    assess_by_key = {(a.department_id, a.stage_order): a for a in fresh}
    snapshot = routing.standard_snapshot if routing else {"stages": []}
    from app.services.change_routing_service import ChangeRoutingService
    removals = await ChangeRoutingService.pending_removal_ids(db, change)

    def _dep(department_id: int, snap_letter: str, a) -> RoutingDepartment:
        # The row's letter is the current one: an approved "not our
        # responsibility" re-letters the row, never the snapshot.
        letter = a.rasic_letter if a is not None else snap_letter
        return RoutingDepartment(
            department_id=department_id, rasic_letter=letter, tier=_tier(letter),
            # Execution state lives on the linked engine task; read it through.
            status=(a.effective_status if a else None),
            verdict=(a.verdict if a else None),
            assessment_id=(a.id if a else None),
            pending_rasic_letter=(a.pending_rasic_letter if a else None),
            pending_removal=(a is not None and a.id in removals))

    stages = []
    shown: set = set()
    for st in snapshot.get("stages", []):
        deps = []
        for d in st["departments"]:
            key = (d["department_id"], st["stage_order"])
            if key in shown:
                continue
            shown.add(key)
            deps.append(_dep(d["department_id"], d["rasic_letter"], assess_by_key.get(key)))
        stages.append(RoutingStage(stage_order=st["stage_order"], departments=deps))
    # Rows a deviation added outside the snapshot belong on the routing too.
    by_order = {s.stage_order: s for s in stages}
    for (dept_id, order), a in sorted(assess_by_key.items(), key=lambda kv: (kv[0][1], kv[1].id)):
        if (dept_id, order) in shown:
            continue
        st = by_order.get(order)
        if st is None:
            st = RoutingStage(stage_order=order, departments=[])
            by_order[order] = st
            stages.append(st)
        st.departments.append(_dep(dept_id, a.rasic_letter, a))
    stages.sort(key=lambda s: s.stage_order)
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


async def _deviation_refusal(db: AsyncSession, change, user: User,
                             body: DeviationRequest) -> Optional[str]:
    """Who may propose a routing deviation: the change lead, Project
    Management or an admin (MeetingService.user_is_pm, acts-as aware), for
    any op. A department member speaks for its own department: it may
    decline its row ("not our responsibility", a reletter) or add itself;
    right after its decline it may name the department that should take
    over (the add of NotResponsibleDialog). Removing a department is never
    a department's own call."""
    from app.services.change_people import holds_lead
    if holds_lead(change, user) or await MeetingService.user_is_pm(db, user):
        return None
    if body.op in ("reletter", "add") and await WorkflowService.actor_in_department(
            db, user, body.department_id):
        return None
    if body.op == "add":
        mine = set(await WorkflowService.effective_department_ids(db, user))
        declined = [a for a in change.assessments
                    if a.pending_rasic_letter and a.department_id in mine]
        if declined:
            # While its decline is pending, a department names ONE
            # department (R or A) to take over, in the declined row's stage.
            first = min((a.stage_order for a in change.assessments), default=1)
            target = body.stage_order or first
            if body.rasic_letter in BLOCKING_LETTERS:
                for d in declined:
                    if d.stage_order == target and not await _named_since_decline(
                            db, change.id, user.id, d.department_id):
                        return None
            return ("While your decline is pending you may name one department "
                    "to take over, as R or A, in the declined stage")
    return ("Only the change lead, Project Management, an admin or a member "
            "of the department concerned may request this routing change")


async def _named_since_decline(db: AsyncSession, change_id: int, user_id: int,
                               department_id: int) -> bool:
    """Did ``user_id`` already add a department by deviation since the
    latest decline of ``department_id``? Read off the changelog (the
    routing_deviation entries carry op + department; older entries only
    their text)."""
    import json as _json
    entries = (await db.execute(
        select(ChangeChangelog).where(
            ChangeChangelog.change_id == change_id,
            ChangeChangelog.action == "routing_deviation")
        .order_by(ChangeChangelog.id))).scalars().all()

    def rec(e) -> dict:
        try:
            v = _json.loads(e.new_value) if e.new_value else None
        except ValueError:
            v = None
        return v if isinstance(v, dict) else {}

    def is_decline(e) -> bool:
        r = rec(e)
        if r:
            return r.get("op") == "reletter" and r.get("department_id") == department_id
        return f"dept {department_id} declined:" in (e.action_description or "")

    def is_add(e) -> bool:
        r = rec(e)
        if r:
            return r.get("op") == "add"
        return "added dept" in (e.action_description or "")

    last = max((i for i, e in enumerate(entries) if is_decline(e)), default=None)
    if last is None:
        return False
    return any(e.performed_by == user_id and is_add(e) for e in entries[last + 1:])


@router.post("/{change_id}/routing/deviation", response_model=RoutingResponse)
async def post_deviation(change_id: int, body: DeviationRequest,
                         db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if change is None:
        raise HTTPException(404, "Change not found")
    from app.services.change_routing_service import ChangeRoutingService
    # Christoph 2026-10-28: an assessing department pulls in who it needs
    # (Responsible or Informed), with a reason, no approval; the lead is told.
    pull_in = (body.op == "add" and body.rasic_letter in ("R", "I")
               and not await WorkflowService.actor_in_department(
                   db, current_user, body.department_id)
               and await ChangeRoutingService.may_pull_in(db, change, current_user))
    if pull_in and len((body.reason or "").strip()) < 5:
        raise HTTPException(400, "Say why your department needs them (reason, 5+ characters)")
    refusal = None if pull_in else await _deviation_refusal(db, change, current_user, body)
    if refusal:
        raise HTTPException(403, refusal)
    try:
        await ChangeRoutingService.apply_deviation(
            db, change, current_user.id, op=body.op, department_id=body.department_id,
            rasic_letter=body.rasic_letter, stage_order=body.stage_order,
            reason=body.reason, pull_in=pull_in)
        if pull_in:
            await ChangeRoutingService.approve_deviation(
                db, change, current_user.id, pull_in=True)
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
    from app.services.change_routing_service import ChangeRoutingService, DeviationForbidden
    try:
        await ChangeRoutingService.reject_deviation(
            db, change, current_user.id, body.reason,
            acting=is_acting(current_user),
            pm_ok=await ChangeRoutingService.deviation_pm_ok(db, current_user))
    except DeviationForbidden as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    # Christoph 2026-11-09: assessment & costing runs on its own
    from app.services import auto_advance
    await auto_advance.run_after(db, change_id, current_user)
    return await get_routing(change_id, db, current_user)


@router.post("/{change_id}/routing/deviation/approve", response_model=RoutingResponse)
async def approve_deviation(change_id: int, db: AsyncSession = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if change is None:
        raise HTTPException(404, "Change not found")
    from app.services.change_routing_service import ChangeRoutingService, DeviationForbidden
    try:
        await ChangeRoutingService.approve_deviation(
            db, change, current_user.id,
            acting=is_acting(current_user),
            pm_ok=await ChangeRoutingService.deviation_pm_ok(db, current_user))
    except DeviationForbidden as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    # Christoph 2026-11-09: assessment & costing runs on its own
    from app.services import auto_advance
    await auto_advance.run_after(db, change_id, current_user)
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
    # are the change lead's, Project Management's or an admin's, kickoff
    # and a rejection at capture too (Project Management captures, migration
    # 152); Sales rejects a quoted change the customer declined.
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
    # C1: a hold says why and what it waits for; the run team's "Resume or
    # cancel" task carries it (a hold without one was a dead end).
    from app.services import cm_switches
    if (body.to_status == "on_hold" and cm_switches.on("COMMERCIAL_V2")
            and body.to_status in ALLOWED_TRANSITIONS.get(change.status, set())
            and not (body.reason or "").strip()):
        raise HTTPException(
            status_code=400,
            detail="Say why the change goes on hold and what it waits for: "
                   "the reason is on the record and on the resume task")
    try:
        await ChangeService.transition(
            db, change, body.to_status, current_user.id,
            cancellation_reason=body.cancellation_reason,
            rejection_reason=body.rejection_reason,
            reopen_reason=body.reopen_reason,
            reason=body.reason or body.escalation_reason,
            hold_until=body.hold_until,
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
            if getattr(e.guard_reason, "key", None):
                # C6: the rule an override would have to name
                headers["X-Deviation-Rule"] = e.guard_reason.key
            if e.pending_deviation_id is not None:
                headers["X-Deviation-Pending"] = str(e.pending_deviation_id)
            raise HTTPException(status_code=400, detail=str(e), headers=headers)
        change = await ChangeService.get_change(db, change_id, viewer=current_user)
        dev = next((d for d in change.transition_deviations
                    if d.id == e.pending_deviation_id), None)
        created = dev is None
        if created:
            from app.services.early_stage_service import EarlyStageService
            refusal = await EarlyStageService.override_ask_refusal(
                db, change, current_user, e.to_status)
            if refusal:
                raise HTTPException(status_code=403, detail=refusal)
            try:
                dev = await ChangeService.propose_transition_deviation(
                    db, change, e.to_status, dev_reason, current_user.id,
                    guard_key=getattr(e.guard_reason, "key", None),
                    reason_code=body.deviation_reason_code)
            except ChangeError as err:
                raise HTTPException(status_code=400, detail=str(err))
            await db.commit()
            await db.refresh(dev)
        row = (await _deviation_rows(db, change, [dev], current_user))[0]
        from app.services.cm_rules import DECIDER_WORDS, decider_group
        who = DECIDER_WORDS[decider_group(dev.guard_key, dev.to_status,
                                          change.customer_relevant)]
        return JSONResponse(status_code=202, content=jsonable_encoder({
            "deviation_requested": True,
            "created": created,
            "to_status": e.to_status,
            "blocked_by": e.guard_reason,
            "detail": (f"{e.guard_reason}. Override #{dev.id} asked: it needs "
                       f"the OK of {who}"
                       if created else
                       f"{e.guard_reason}. Override #{dev.id} waits for the "
                       f"OK of {who}"),
            "deviation": row,
        }))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return await _price_safe(db, change, current_user, ChangeResponse)


@router.put("/{change_id}/hold-review", response_model=ChangeResponse)
async def move_hold_review(
    change_id: int, body: HoldReviewRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """A new review date for a change on hold, with a short reason
    (Christoph 2026-11-02): the lead, Project Management or an admin; the
    date and the reason go on the change history."""
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await ChangeService.move_hold_review(
            db, change, current_user, body.review_date, body.reason)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return await _price_safe(db, change, current_user, ChangeResponse)


def _refresh_tool_tonnage(background: BackgroundTasks, change_id: int) -> None:
    """After the impacted items grew: refresh the new tools' press tonnage
    from MachineDB / TWOS after the answer is sent (costing's default
    machine class). Nothing when neither is configured."""
    from app.services import tool_tonnage_service
    if tool_tonnage_service.any_source_configured():
        background.add_task(tool_tonnage_service.refresh_change_in_background, change_id)


@router.post("/{change_id}/impacted-items", response_model=ImpactedItemResponse)
async def add_impacted_item(
    change_id: int, body: ImpactedItemCreate, background: BackgroundTasks,
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
    _refresh_tool_tonnage(background, change_id)
    await db.refresh(item)
    out = ImpactedItemResponse.model_validate(item)
    await fill_part_labels(db, [out])
    return out


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
    change_id: int, body: ImpactSelectionIn, background: BackgroundTasks,
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
    _refresh_tool_tonnage(background, change_id)
    # Read impacted parts fresh: with expire_on_commit=False the cached
    # relationship collection would not reflect the just-applied diff.
    rows = await db.execute(
        select(ChangeImpactedItem.part_id).where(
            ChangeImpactedItem.change_id == change_id))
    return {"impacted_part_ids": sorted(pid for (pid,) in rows)}


@router.post("/{change_id}/impacted-items/seed")
async def seed_impacted_items(
    change_id: int, background: BackgroundTasks,
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
    # A3-03: an impact edit like add/remove/PUT (C16): past the lock it says
    # why, reopens the affected costing and tells the departments
    try:
        prior = {i.part_id for i in change.impacted_items}
        before = await EarlyStageService.begin_impact_edit(db, change, reason)
        added = await ChangeService.seed_impacted_from_relations(
            db, change, current_user.id)
        if added:
            await db.refresh(change, ["impacted_items"])
            await EarlyStageService.finish_impact_edit(
                db, change, current_user.id, reason, before,
                sorted({i.part_id for i in change.impacted_items} - prior))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    if added:
        _refresh_tool_tonnage(background, change_id)
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
        # esc P3-2: another department's submit is a rights refusal: 403
        from app.services.change_service import RightsForbidden
        from app.services.workflow_service import TaskRightsForbidden
        raise HTTPException(
            status_code=403 if isinstance(e, (RightsForbidden, TaskRightsForbidden)) else 400,
            detail=str(e))
    await db.commit()
    # Christoph 2026-11-09: assessment & costing runs on its own
    from app.services import auto_advance
    await auto_advance.run_after(db, change_id, current_user)
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
        from app.services.change_service import AcceptForbidden
        raise HTTPException(status_code=403 if isinstance(e, AcceptForbidden) else 400,
                            detail=str(e))
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
        from app.services.change_service import AssignForbidden
        raise HTTPException(status_code=403 if isinstance(e, AssignForbidden) else 400,
                            detail=str(e))
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
        from app.services.change_service import RightsForbidden
        raise HTTPException(status_code=403 if isinstance(e, RightsForbidden) else 400,
                            detail=str(e))
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
    # C10: Sales hands the customer side over; PM re-assigns it
    "sales_owner_id": ("sales", "pm"),
    # money: the cost roles
    "estimated_cost": ("lead", "pm", "sales"),
    "pnl_note": ("lead", "pm", "sales"),
    # the lead steers the change
    "priority": ("lead",),
    "customer_relevant": ("lead",),
    # capture fields: the lead owns them, Sales supplies the customer's
    # facts. Project Management writes them while it captures (every change
    # in capture, migration 152; a mother-plant change throughout) and in
    # scoping while nobody leads the change yet: "pm_capture".
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
    # §2: why urgent and its evidence (with the priority); what is wrong
    # today and the target of an internal change: capture fields
    "urgent_reason": ("lead", "sales", "pm_capture"),
    "urgent_evidence": ("lead", "sales", "pm_capture"),
    "problem_value": ("lead", "sales", "pm_capture"),
    "problem_unit": ("lead", "sales", "pm_capture"),
    "target_value": ("lead", "sales", "pm_capture"),
}
_PATCH_ROLE_DEPT = {"sales": "Sales", "quality": "Quality",
                    "scheduling": "Logistics"}


def _patch_rights(change, key, value) -> tuple:
    """The roles that may move `key` to `value`. P3/C10: making an internal
    change a customer change is Sales', Project Management's or an admin's
    call (update_change also checks carrier_move_refusal), whether or not
    they lead it; the way back stays the lead's."""
    if key == "customer_relevant" and value is True and not change.customer_relevant:
        return ("lead", "pm", "sales")
    return _PATCH_RIGHTS[key]


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
                pm_window = (mp.is_mother_plant(change)
                             or change.status == "captured"
                             or (change.status == "scoping"
                                 and change.lead_id is None))
                held[role] = pm_window and await has("pm")
            else:
                held[role] = await ChangeService._user_in_department(
                    db, user, _PATCH_ROLE_DEPT[role])
        return held[role]

    for key in moving:
        rights = _patch_rights(change, key, fields[key])
        allowed = False
        for role in rights:
            if await has(role):
                allowed = True
                break
        if not allowed:
            who = ", ".join(dict.fromkeys(
                {"lead": "the change lead", "pm": "Project Management",
                 "pm_capture": "Project Management",
                 "sales": "Sales", "quality": "Quality",
                 "scheduling": "Logistics"}[r]
                for r in rights))
            raise HTTPException(
                status_code=403,
                detail=f"Only {who} or an admin may change {key}")


async def _require_sales_owner(db: AsyncSession, change, user_id: int,
                               actor: User, customer: bool) -> None:
    """C10: the owner is an active Sales member of the change's organization,
    on a customer change (`customer`: the change's state after this PATCH);
    the move is in the changelog."""
    from app.services import mother_plants as mp
    if not customer or mp.is_mother_plant(change):
        raise HTTPException(status_code=400,
                            detail="An internal change has no Sales contact")
    owner = await _require_org_user(db, user_id,
                                    await _project_org_id(db, change.project_id),
                                    role="Sales contact")
    from app.services.project_team_service import is_live_member
    if not await is_live_member(db, owner.id, "Sales"):
        raise HTTPException(status_code=400,
                            detail="The Sales contact must be a member of Sales")
    old = await db.get(User, change.sales_owner_id) if change.sales_owner_id else None
    await ChangeService.append_changelog(
        db, change, "sales_owner_changed",
        # esc P3-6: names, not ids
        f"Sales contact {(old.full_name or old.username) if old else 'none'} -> "
        f"{owner.full_name or owner.username}", actor.id,
        field_name="sales_owner_id", old_value=change.sales_owner_id,
        new_value=owner.id)


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
    from app.services.change_service import D1_FIELDS, D1_LOCKED_STATUSES
    if change.status in D1_LOCKED_STATUSES:
        moving_d1 = [k for k in D1_FIELDS
                     if k in fields and _patch_changes_field(change, k, fields[k])]
        if moving_d1:
            raise HTTPException(
                status_code=400,
                detail=f"The change is {change.status}: its D1 data "
                       f"({', '.join(moving_d1)}) is read only")
    # P3 / [R4]: an engineering lead starts internal changes only; making
    # one a customer change is Sales', Project Management's or an admin's
    # call, lead or not; the way back drops the Sales contact, so it needs
    # those rights too. Asked first, so the
    # engineering lead hears who can do it. The scoping room's cost carrier
    # follows the same rule (MeetingService).
    if fields.get("customer_relevant") is not None:
        why = await ChangeService.carrier_move_refusal(
            db, change, current_user, bool(fields["customer_relevant"]))
        if why:
            raise HTTPException(status_code=403, detail=why)
    await _require_patch_rights(db, change, fields, current_user)
    if "lead_id" in fields and fields["lead_id"] is not None \
            and fields["lead_id"] != change.lead_id:
        new_lead = await _require_org_user(
            db, fields["lead_id"], await _project_org_id(db, change.project_id))
        await ChangeService.append_changelog(
            db, change, "lead_changed",
            f"Change lead {change.lead_id} -> {new_lead.id}", current_user.id,
            field_name="lead_id", old_value=change.lead_id, new_value=new_lead.id)
    if "sales_owner_id" in fields and fields["sales_owner_id"] is not None \
            and fields["sales_owner_id"] != change.sales_owner_id:
        await _require_sales_owner(
            db, change, fields["sales_owner_id"], current_user,
            customer=bool(change.customer_relevant
                          if fields.get("customer_relevant") is None
                          else fields["customer_relevant"]))
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
            expired_override_reason=body.expired_override_reason,
            answer=body.model_dump(include={
                "attachment_id", "from_customer", "ref", "po_match", "differs", "confirm_total",
                "next_contact", "note", "price_drop_code", "price_drop_note"}),
            actor=current_user)
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
    if body.role in SIGN_OFF_ROLES and not await ChangeService.user_can_sign_change(
            db, current_user, body.role):
        dept_name = "Quality" if body.role == "quality" else "Project Manager"
        raise HTTPException(
            status_code=403,
            detail=f"Only a {dept_name} department member may sign off as "
                   f"{body.role} (an admin acts as the department)")
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
    if not await ChangeService.user_can_approve_internal_costs(
            db, current_user, change):
        raise HTTPException(
            status_code=403,
            detail=("The raiser does not approve their own change's spend: "
                    "an engineering approver does"
                    if change.raised_by == current_user.id else
                    "Only an engineering approver may approve internal costs"))
    try:
        await ChangeService.approve_internal_costs(
            db, change, current_user, note=body.note,
            release_due_date=body.release_due_date,
            release_due_reason=body.release_due_reason,
            rationale=body.rationale, volume=body.volume, saving=body.saving,
            saving_basis=body.saving_basis)
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
            detail="Only a Logistics or Project Manager department member, "
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


@router.put("/{change_id}/changeover-offer", response_model=ChangeResponse)
async def put_changeover_offer(
    change_id: int, body: ChangeoverOfferIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """What Sales offers the customer for the old stock (Christoph
    2026-11-09): running_change | customer_scrap, optional parts left,
    changeover date and note. Sales, Project Management, the change lead or
    an admin; until the customer answered the offer."""
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    if not (await ChangeService.user_can_set_quoted_price(db, current_user, change)
            or await ChangeService._user_in_department(db, current_user, "Project Manager")):
        raise HTTPException(
            status_code=403,
            detail="Only Sales, Project Management, the change lead or an "
                   "admin may set the offered changeover")
    try:
        await ChangeService.set_changeover_offer(
            db, change, current_user, body.mode,
            old_stock_parts=body.old_stock_parts,
            changeover_date=body.changeover_date, note=body.note)
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
    # 156: the modification case this document belongs to (Christoph 2026-11-08)
    case_ref: Optional[str] = Form(None),
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
            case_ref=(case_ref or "").strip()[:40] or None,
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
            "case_ref": att.case_ref,
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
    # R4/R17: the customer's file a decision stands on (an acceptance, a
    # decline, a supplement's answer, a scope change card) is its record
    from app.models.change_offer import ChangeOffer
    from app.models.change_scope import ChangeScopeChange
    answered = (await db.execute(
        select(ChangeOffer.accept_evidence).where(
            ChangeOffer.change_id == change.id,
            ChangeOffer.accept_evidence.isnot(None)))).scalars().all()
    if any(isinstance(e, dict) and e.get("attachment_id") == att.id for e in answered):
        frozen("The customer's answer stands on this file: it is the record "
               "and cannot be removed")
    if getattr(change, "start_at_risk_attachment_id", None) == att.id:
        # A4-06: the approval without a PO stands on the customer's go-ahead
        frozen("The start at risk stands on this file (the customer's "
               "go-ahead): it is the record and cannot be removed")
    for card_att, question in (await db.execute(
            select(ChangeScopeChange.attachment_id, ChangeScopeChange.question).where(
                ChangeScopeChange.change_id == change.id))).all():
        if card_att == att.id or (isinstance(question, dict)
                                  and question.get("attachment_id") == att.id):
            frozen("A scope change card stands on this file (the customer's "
                   "wish or answer): it is the record and cannot be removed")
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
        # Christoph 2026-11-08: an assessment's document is removed only by
        # the owner of that assessment (assigned / responsible; the uploader
        # while nobody owns it) or an admin
        owners = {x for x in (a.owner_id, a.responsible_id) if x is not None}
        if not (is_admin or user.id in owners
                or (not owners and att.uploaded_by == user.id)):
            raise HTTPException(
                status_code=403,
                detail="Only the owner of this assessment, or an admin, may "
                       "remove its documents")
        submitted = (a.submitted_at is not None
                     or a.effective_status == "submitted")
        # Christoph 2026-11-08: a wrong change PPT / RFQ may be removed while
        # the change is still assessed or costed; the department's assessment
        # then reopens if the document is owed (delete_attachment)
        from app.services.early_stage_service import SEND_BACK_STATUSES
        reopenable = (att.kind in ("change_ppt", "rfq")
                      and change.status in SEND_BACK_STATUSES)
        if submitted and att.phase == "post_scoping" and not reopenable:
            frozen("The assessment is submitted: its evidence is the record "
                   "the verdict stands on and cannot be removed")
        return
    if att.kind == "vendor_quote":
        return      # the position write rule, checked by the caller
    # Everything else, and evidence whose assessment is gone: the default.
    if (is_admin or att.uploaded_by == user.id
            or holds_lead(change, user)
            or await MeetingService.user_is_pm_member(db, user)):
        return
    raise HTTPException(
        status_code=403,
        detail="Only the uploader, the change lead, Project Management or "
               "an admin may remove that document")


async def _reopen_if_document_owed(db: AsyncSession, change, gone: dict,
                                   user_id: int) -> None:
    """Christoph 2026-11-08: a required document (change PPT / RFQ, per case
    or per row) removed from a SUBMITTED assessment reopens that department's
    assessment (send-back, its task active again) and, in costing, its
    costing finalization: the answer is missing a document now."""
    if gone["kind"] not in ("change_ppt", "rfq") or gone["assessment_id"] is None:
        return
    a = await db.get(ChangeAssessment, gone["assessment_id"])
    if a is None or a.submitted_at is None:
        return
    from app.services import assessment_checklist as checklist
    from app.models.workflow import Department
    filed: set = set()
    by_case: dict = {}
    for k, ref in (await db.execute(
            select(ChangeAttachment.kind, ChangeAttachment.case_ref).where(
                ChangeAttachment.change_id == change.id,
                ChangeAttachment.assessment_id == a.id))).all():
        filed.add(k)
        if ref:
            by_case.setdefault(ref, set()).add(k)
    dept = await db.get(Department, a.department_id)
    owed = checklist.missing_documents(a.details_dict.get("impacts"), filed,
                                       dept.name if dept else None,
                                       filed_by_case=by_case)
    if not owed:
        return
    from app.services.early_stage_service import EarlyStageService
    from app.services import early_costing
    reason = f"Document removed ({gone['filename']}): " + "; ".join(owed)
    await db.refresh(change, ["assessments"])
    sent = await EarlyStageService._send_back_assessments(
        db, change, [a.department_id], user_id, reason)
    if sent and change.status == "costing":
        await early_costing.clear_finalization(db, change, a.department_id, user_id, reason)


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
    gone = {"assessment_id": att.assessment_id, "kind": att.kind,
            "filename": att.filename}
    stored_path = await ChangeService.delete_attachment(db, change, att, current_user.id)
    await _reopen_if_document_owed(db, change, gone, current_user.id)
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
    refusal = await _costing_write_refusal(db, change, a.department_id, current_user,
                                           "cost lines")
    if refusal:
        raise HTTPException(status_code=403, detail=refusal)
    try:
        lines = await CostService.replace_cost_lines(
            db, change, a, [l.model_dump() for l in body.lines], current_user.id)
    except CostError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await _after_cost_write(db, change, current_user)
    await db.commit()
    return lines


# --- costing positions ------------------------------------------------------
# The other half of costing: what hours × rate cannot express. Permissions
# mirror the cost grid — the department writes its own rows while the change is
# in costing, PM and admins write anyone's, and the people accountable for the
# change as a whole read everything.

async def _after_cost_write(db: AsyncSession, change, current_user: User) -> None:
    """A3-04 (HARD #8): PM and admin may write costs at any time; a write
    that lifts an internal change's total above the approved amount
    withdraws the approval, as a finalize does, so the approver is told and
    owes it again (never a silent dead end)."""
    await db.flush()
    await ChangeService.withdraw_outgrown_internal_approval(
        db, change, current_user.id)


async def _costing_change(db: AsyncSession, change_id: int, current_user: User):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


async def _costing_write_refusal(db: AsyncSession, change, department_id: int,
                                 current_user: User, what: str) -> Optional[str]:
    """Why the caller may not write this department's costs, or None. A3-12
    (R5): a member whose department finalized reads that cause, not the
    generic rule."""
    from app.services import early_costing
    from app.services.costing_position_service import CostingPositionService
    from app.services.workflow_service import WorkflowService
    if await CostingPositionService.may_write(db, change, department_id, current_user):
        return None
    if (early_costing.costing_open_for(change, department_id)
            and early_costing.is_finalized(change, department_id)
            and await WorkflowService.actor_in_department(
                db, current_user, department_id)):
        return "Your costing is finalized: reopen it first"
    return ("Only a member of that department while the change is in "
            f"costing, Project Management or an admin may change its {what}")


async def _require_costing_write(db: AsyncSession, change, department_id: int,
                                 current_user: User) -> None:
    refusal = await _costing_write_refusal(db, change, department_id, current_user,
                                           "costing positions")
    if refusal:
        raise HTTPException(status_code=403, detail=refusal)


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
    out = await CostingPositionService.serialize(db, rows)
    checkable = await CostingPositionService.checkable_position_ids(
        db, change, rows, current_user)
    for row in out:
        row["can_check_estimate"] = row["id"] in checkable
    return out


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
    await _after_cost_write(db, change, current_user)
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
    await _after_cost_write(db, change, current_user)
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
    await _after_cost_write(db, change, current_user)
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
    await _after_cost_write(db, change, current_user)
    await db.commit()
    await db.refresh(position)
    return _offer_row(
        (await CostingPositionService.serialize(db, [position]))[0], offer.id)


@router.post("/{change_id}/costing/positions/{pid}/estimate-check",
             response_model=CostingPositionResponse)
async def check_quote_against_estimate(
    change_id: int, pid: int, body: EstimateCheckIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Spec §4 [R4]: the quote that came in after an offer or approval on
    the estimate: within +5 % / above by x (the department, PM, admin)."""
    from app.services.costing_position_service import (
        CostingPositionError, CostingPositionForbidden, CostingPositionService,
    )
    change = await _costing_change(db, change_id, current_user)
    try:
        position = await CostingPositionService.get_position(db, change, pid)
    except CostingPositionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        await CostingPositionService.estimate_check(
            db, change, position, current_user, body.verdict, body.over,
            quote=body.model_dump(include={"vendor_name", "quote_ref", "cost",
                                           "quoted_on"}))
    except CostingPositionForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except CostingPositionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await _after_cost_write(db, change, current_user)
    await db.commit()
    await db.refresh(position)
    return (await CostingPositionService.serialize(db, [position]))[0]


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
    await _after_cost_write(db, change, current_user)
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
    await _after_cost_write(db, change, current_user)
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
    await _after_cost_write(db, change, current_user)
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
            detail="Only Project Management, Sales, Finance, Management, the "
                   "change lead or an admin may read the cost summation")
    return await CostService.summation(db, change)


@router.get("/{change_id}/gates", response_model=List[GateResponse])
async def get_gates(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return await _gate_rows(db, change.gates)


async def _gate_rows(db, gates) -> list[GateResponse]:
    """Gates with the decider's name, one user query for the list."""
    ids = {g.decided_by for g in gates if g.decided_by is not None}
    names = dict((await db.execute(
        select(User.id, User.full_name).where(User.id.in_(ids)))).all()) if ids else {}
    out = []
    for g in gates:
        row = GateResponse.model_validate(g)
        row.decided_by_name = names.get(g.decided_by)
        out.append(row)
    return out


@router.put("/{change_id}/gates/{gate_key}", response_model=GateResponse)
async def put_gate(
    change_id: int, gate_key: str, body: GateDecisionIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    # Acting as a department is being that department: the admin bypass and
    # the personal lead right both step aside (holds_lead), as everywhere.
    from app.services.change_people import holds_lead
    if current_user.effective_role != "admin" and not holds_lead(change, current_user):
        raise HTTPException(status_code=403,
                            detail="Only the change lead or an admin may decide gates")
    try:
        gate = await ChangeService.decide_gate(
            db, change, gate_key, body.decision, current_user.id, remark=body.remark)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return (await _gate_rows(db, [gate]))[0]


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
    from app.services.cm_rules import rule_label
    from app.services.price_redaction import PRICE_RULES, PriceViewer
    names = await ChangePlanService._user_names(
        db, [d.proposed_by for d in devs] + [d.decided_by for d in devs])
    # An Absorb note or a price-drop reason is money talk (R23): blanked
    # for a viewer outside the price rule, the rule and the people stay.
    hide = (any(d.guard_key in PRICE_RULES for d in devs)
            and not await PriceViewer(db, user).may_read(change))
    out = []
    for d in devs:
        pending = d.status == "pending"
        row = TransitionDeviationResponse.model_validate(d).model_dump()
        if hide and d.guard_key in PRICE_RULES:
            # guard_reason: an older binding kept the refusal text verbatim
            row.update(reason="", decision_note=None,
                       guard_reason=rule_label(d.guard_key))
        out.append({
            **row,
            "can_decide": (pending and await ChangeService.deviation_decide_refusal(
                db, change, d, user) is None),
            "proposed_by_name": names.get(d.proposed_by),
            "decided_by_name": names.get(d.decided_by),
            "rule_label": rule_label(d.guard_key) if d.guard_key else None,
            "deciders": (await ChangeService.override_deciders(
                db, change, d.guard_key, d.to_status) if pending else None),
        })
    return out


@router.post("/{change_id}/deviations", response_model=TransitionDeviationResponse)
async def propose_deviation(
    change_id: int, body: DeviationProposeIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    # R33: the ask notifies whole departments; who may not take the step
    # and is not on the run team may not ask (checked before 'already
    # pending', so a refusal never leaks what others asked)
    from app.services.early_stage_service import EarlyStageService
    refusal = await EarlyStageService.override_ask_refusal(
        db, change, current_user, body.to_status)
    if refusal:
        raise HTTPException(status_code=403, detail=refusal)
    try:
        dev = await ChangeService.propose_transition_deviation(
            db, change, body.to_status, body.reason, current_user.id,
            guard_key=body.guard_key, reason_code=body.reason_code)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(dev)
    return (await _deviation_rows(db, change, [dev], current_user))[0]


@router.post("/{change_id}/absorb", response_model=TransitionDeviationResponse)
async def propose_absorb(
    change_id: int, body: AbsorbIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """HARD #9's exit (spec §0): absorb the open price. Asked by Sales or
    the run team with a reason pick + note; a Project Management or
    Management member gives the OK (internal: the approver) on the
    deviation it files; the OK clears price_open."""
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    refusal = await ChangeService.absorb_refusal(db, change, current_user)
    if refusal:
        raise HTTPException(status_code=403, detail=refusal)
    try:
        dev = await ChangeService.propose_absorb(
            db, change, body.reason_code, body.note, current_user)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(dev)
    return (await _deviation_rows(db, change, [dev], current_user))[0]


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
    except DeviationDecideForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    # Christoph 2026-11-09: assessment & costing runs on its own
    from app.services import auto_advance
    await auto_advance.run_after(db, change_id, current_user)
    return (await _deviation_rows(db, change, [dev], current_user))[0]


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
            cost_carrier=body.cost_carrier, raiser_waive_reason=body.raiser_waive_reason)
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
    concern_dept_ids = {c.department_id for c in change.concerns if c.department_id}
    concern_depts = dict((await db.execute(
        select(Department.id, Department.name).where(
            Department.id.in_(concern_dept_ids)))).all()) if concern_dept_ids else {}
    # A risk deleted by its raiser is gone from the register; the changelog
    # keeps the record.
    # C33: owners by name, a check item's due (its department's assessment
    # due), the part, the person named to confirm an assumption. One query
    # each, never one per row.
    owner_ids = {d for c in change.concerns for d in c.owner_department_ids}
    if owner_ids - set(concern_depts):
        concern_depts.update(dict((await db.execute(
            select(Department.id, Department.name).where(
                Department.id.in_(owner_ids - set(concern_depts))))).all()))
    # C8/R5: a check item is due with its department's assessment (a
    # consulted department: the change's assessment due)
    due_by_dept = {d: MeetingService.check_due(change, d)
                   for d in {d for c in change.concerns if c.is_check
                             for d in c.owner_department_ids}}
    part_ids = {c.part_id for c in change.concerns if c.part_id}
    part_numbers = dict((await db.execute(
        select(Part.id, Part.part_number).where(Part.id.in_(part_ids)))).all()) \
        if part_ids else {}
    # F9: the customer copy names the customer's part number, never ours
    customer_pns = dict((await db.execute(
        select(Part.id, Part.customer_part_number).where(Part.id.in_(part_ids)))).all()) \
        if part_ids else {}
    confirm_ids = {c.confirm_by_id for c in change.concerns if c.confirm_by_id}
    if confirm_ids - set(names):
        for uid, full_name in await db.execute(
                select(User.id, User.full_name).where(
                    User.id.in_(confirm_ids - set(names)))):
            names[uid] = full_name
    is_pm_member = await MeetingService.user_is_pm_member(db, current_user)
    acting = getattr(current_user, "acts_as_department_id", None) is not None
    # spec §4 check items in the assessment: who closes them (an owning
    # department's member, PM, admin), from one membership lookup (R34)
    from app.services import cm_switches
    checks_v2 = (change.status in ("in_assessment", "costing")
                 and cm_switches.on("ASSESSMENT_V2"))
    # the caller's departments once for every row's checks (R34, A2-10)
    viewer = await MeetingService.viewer_departments(db, current_user)
    my_dept_ids = viewer[0] if checks_v2 else set()
    if cm_switches.on("ASSESSMENT_V2") and change.status not in ("captured", "scoping"):
        from app.services import due_rules as _dr
        await _dr.load_clock_floor(db)      # A6-01: the answer due's floor
    # Audit P3-16: when the change first entered assessment (a concern
    # raised before it is scoping's)
    import json
    from sqlalchemy import func
    from app.models.change import ChangeChangelog as _CL
    assessed_at = (await db.execute(
        select(func.min(_CL.performed_at)).where(
            _CL.change_id == change.id, _CL.field_name == "status",
            _CL.new_value == json.dumps("in_assessment")))).scalar()
    for c in (c for c in change.concerns if c.retracted_at is None):
        row = ConcernResponse.model_validate(c)
        row.raised_in_scoping = (c.raised_at < assessed_at if assessed_at and c.raised_at
                                 else change.status in ("captured", "scoping"))
        if c.kind == "needs_info":
            # The question is the asking side's (2026-10-14): who that is, and
            # whether the caller may answer it (same check as POST .../answer).
            row.asking_department_name = concern_depts.get(c.department_id)
            # a check item in the assessment is closed by its department,
            # never answered (POST .../answer refuses it, R24)
            row.can_answer = (c.is_open and not (checks_v2 and c.is_check)
                              and await MeetingService.can_answer_question(
                                  db, change, c, current_user, viewer))
            # the confirm item of an Assumed answer: open in any live status,
            # the question open or closed (its named confirmer, or whoever
            # may answer it)
            row.can_confirm = await MeetingService.can_confirm(
                db, change, c, current_user, viewer)
            row.customer_copy = MeetingService.customer_copy(
                change, c, customer_pns.get(c.part_id))
            row.owner_department_names = [concern_depts.get(d, f"#{d}")
                                          for d in c.owner_department_ids]
            if c.is_check:
                dues = [due_by_dept[d] for d in c.owner_department_ids
                        if due_by_dept.get(d) is not None]
                row.owner_due = min(dues) if dues else None
            elif (c.is_open and c.answered_at is None and c.flag_type == "question"
                  and change.status not in ("captured", "scoping")
                  and cm_switches.on("ASSESSMENT_V2")):
                from app.services import due_rules
                now = datetime.utcnow()
                row.answer_due = due_rules.task_due(
                    due_rules.start_of("obtain_info", c.raised_at, None, None, now),
                    change, "obtain_info")
            row.part_number = part_numbers.get(c.part_id)
            row.confirm_by_name = names.get(c.confirm_by_id)
            row.can_switch = c.is_open and (
                (c.raised_by == current_user.id and not acting) or is_pm_member)
            row.can_add_to = await MeetingService.may_add_to(
                db, change, c, current_user, viewer)
            if c.is_check and checks_v2:
                # same rules as POST .../check and .../reopen
                row.can_check = c.is_open and bool(c.owner_department_ids) and (
                    current_user.effective_role == "admin" or is_pm_member
                    or bool(my_dept_ids & set(c.owner_department_ids)))
                row.can_reopen = MeetingService.reopen_check_refusal(
                    change, c, current_user) is None
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
            checklist_key=body.checklist_key,
            flag_type=body.flag_type, check_what=body.check_what,
            part_id=body.part_id, answer_from=body.answer_from,
            scope_effect=body.scope_effect)
    except MeetingForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(concern)
    return concern


async def _concern_act(change_id: int, current_user: User, db: AsyncSession, act):
    """Run a C33 act on a concern: 404 without the change, 403 for a
    MeetingForbidden, 400 for any other refusal; commit and return it."""
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        concern = await act(change)
    except MeetingForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    # Christoph 2026-11-09: assessment & costing runs on its own
    from app.services import auto_advance
    await auto_advance.run_after(db, change_id, current_user)
    await db.refresh(concern)
    return concern


@router.post("/{change_id}/need-by/tell", response_model=ChangeResponse)
async def post_need_by_tell(
    change_id: int, body: NeedByTellIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """§3 urgent: Sales told the customer the need-by is not realistic (new
    date or start at risk), with the filed mail or a reference."""
    from app.services import capture_rules
    from app.services.index_followup_service import FollowupForbidden
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await capture_rules.tell_customer(db, change, current_user, ref=body.ref,
                                          mail_id=body.mail_id)
    except FollowupForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    change.deadline_state = await ChangeService.deadline_state(db, change)
    return await _price_safe(db, change, current_user, ChangeResponse)


@router.post("/{change_id}/ppap-decision", response_model=ChangeResponse)
async def post_ppap_decision(
    change_id: int, body: PpapDecisionIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """HARD #7: Quality answers "parameters / tool / material / cycle time
    changed on any part?" on an internal change in capture or scoping. A
    'yes' flips it to a customer change."""
    from app.services.ppap_decision_service import PpapDecisionService, PpapForbidden
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await PpapDecisionService.decide(
            db, change, current_user, body.answer, basis=body.basis, ref=body.ref,
            part_ids=body.part_ids)
    except PpapForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    change.deadline_state = await ChangeService.deadline_state(db, change)
    return await _price_safe(db, change, current_user, ChangeResponse)


@router.post("/{change_id}/customer-flip/answer", response_model=ChangeResponse)
async def post_customer_flip_answer(
    change_id: int, body: CustomerFlipAnswerIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """The Sales contact's answer to a customer flip: notification only (a
    filed customer mail or a reference) or offer needed (quote deadline)."""
    from app.services.ppap_decision_service import PpapDecisionService, PpapForbidden
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await PpapDecisionService.answer_flip(
            db, change, current_user, body.answer, ref=body.ref,
            mail_id=body.mail_id, quote_deadline=body.quote_deadline)
    except PpapForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    change.deadline_state = await ChangeService.deadline_state(db, change)
    return await _price_safe(db, change, current_user, ChangeResponse)


@router.get("/{change_id}/index-followups")
async def get_index_followups(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """§1: the new customer indices on parts this change carried, with the
    departments' rechecks, the lead's and Sales' questions."""
    from app.services.index_followup_service import IndexFollowupService
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return await IndexFollowupService.for_change(db, change)


async def _followup_act(change_id: int, current_user: User, db: AsyncSession, act):
    from app.services.index_followup_service import FollowupForbidden, IndexFollowupService
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await act(change)
    except FollowupForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    # Christoph 2026-11-09: assessment & costing runs on its own
    from app.services import auto_advance
    await auto_advance.run_after(db, change_id, current_user)
    return await IndexFollowupService.for_change(db, change)


async def _intake_of(db: AsyncSession, change, intake_id: int):
    from app.models.revision_intake import RevisionIntake
    intake = await db.get(RevisionIntake, intake_id)
    if intake is None or intake.change_id != change.id:
        raise HTTPException(status_code=404, detail="Index follow-up not found")
    return intake


@router.post("/{change_id}/rechecks/{recheck_id}/answer")
async def answer_recheck(
    change_id: int, recheck_id: int, body: RecheckAnswerIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """§1: per changed area 'no effect' (ref) or 'effect' (what + evidence)."""
    from app.models.revision_intake import ChangeRecheck
    from app.services.index_followup_service import IndexFollowupService

    async def act(change):
        recheck = await db.get(ChangeRecheck, recheck_id)
        if recheck is None or recheck.change_id != change.id:
            raise HTTPException(status_code=404, detail="Recheck not found")
        await IndexFollowupService.answer_recheck(
            db, change, recheck, current_user, [a.model_dump() for a in body.answers],
            body.something_else.model_dump() if body.something_else else None)
    return await _followup_act(change_id, current_user, db, act)


@router.post("/{change_id}/index-followups/{intake_id}/scope")
async def answer_index_scope(
    change_id: int, intake_id: int, body: IndexScopeIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """§1: the lead: does the new index add parts or departments?"""
    from app.services.index_followup_service import IndexFollowupService

    async def act(change):
        await IndexFollowupService.answer_scope(
            db, change, await _intake_of(db, change, intake_id), current_user,
            body.answer, body.note)
    return await _followup_act(change_id, current_user, db, act)


@router.post("/{change_id}/index-followups/{intake_id}/deadline")
async def answer_index_deadline(
    change_id: int, intake_id: int, body: IndexDeadlineIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """§1: Sales: does the quote deadline hold with the new index?"""
    from app.services.index_followup_service import IndexFollowupService

    async def act(change):
        await IndexFollowupService.answer_deadline(
            db, change, await _intake_of(db, change, intake_id), current_user,
            body.answer, ref=body.ref, mail_id=body.mail_id, new_date=body.new_date,
            confirm_by=body.confirm_by)
    return await _followup_act(change_id, current_user, db, act)


@router.post("/{change_id}/concerns/{concern_id}/type", response_model=ConcernResponse)
async def set_concern_type(
    change_id: int, concern_id: int, body: ConcernTypeIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """C33: make it a question or a check item (the asker or Project
    Management, during capture and scoping)."""
    return await _concern_act(change_id, current_user, db, lambda change: (
        MeetingService.set_flag_type(
            db, change, concern_id, current_user, body.flag_type,
            answer_from=body.answer_from, scope_effect=body.scope_effect,
            department_id=body.department_id, check_what=body.check_what)))


@router.post("/{change_id}/concerns/{concern_id}/join", response_model=ConcernResponse)
async def join_concern(
    change_id: int, concern_id: int, body: ConcernJoinIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """C33: 'same as #n' (your department co-owns it) and/or 'add to #n'."""
    return await _concern_act(change_id, current_user, db, lambda change: (
        MeetingService.join_flag(db, change, concern_id, current_user,
                                 department_id=body.department_id, note=body.note)))


@router.post("/{change_id}/concerns/{concern_id}/confirm", response_model=ConcernResponse)
async def confirm_concern_assumption(
    change_id: int, concern_id: int, body: ConcernConfirmIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """C33: confirm an Assumed answer with evidence (the named confirmer,
    the asking department, Sales or Project Management)."""
    return await _concern_act(change_id, current_user, db, lambda change: (
        MeetingService.confirm_assumption(db, change, concern_id, current_user,
                                          ref=body.ref, mail_id=body.mail_id)))


@router.post("/{change_id}/concerns/{concern_id}/check", response_model=ConcernResponse)
async def close_check_item(
    change_id: int, concern_id: int, body: CheckCloseIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Spec §4: the owning department closes its check item in its
    assessment: Answered / Not relevant / Assumed, each with its evidence."""
    return await _concern_act(change_id, current_user, db, lambda change: (
        MeetingService.close_check(
            db, change, concern_id, current_user, outcome=body.outcome,
            value=body.value, unit=body.unit, ref=body.ref, basis=body.basis,
            checklist_key=body.checklist_key, who=body.who,
            same_as_id=body.same_as_id, assumed_risk=body.assumed_risk,
            confirm_by_id=body.confirm_by_id, confirm_due=body.confirm_due)))


@router.post("/{change_id}/concerns/{concern_id}/reopen", response_model=ConcernResponse)
async def reopen_check_item(
    change_id: int, concern_id: int, body: CheckReopenIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Spec §4: the raiser or the lead reopens a closed check item (reason)."""
    return await _concern_act(change_id, current_user, db, lambda change: (
        MeetingService.reopen_check(db, change, concern_id, current_user,
                                    body.reason)))


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
    # Christoph 2026-11-09: assessment & costing runs on its own
    from app.services import auto_advance
    await auto_advance.run_after(db, change_id, current_user)
    await db.refresh(concern)
    return concern


@router.put("/{change_id}/scope-definition", response_model=ChangeResponse)
async def put_scope_definition(
    change_id: int, body: ScopeDefinitionIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """The scope of the change in the project manager's words (2026-10-14).
    Project Management members, the change lead or an admin, while the change
    is captured or in scoping; audited, read-only afterwards. No gate."""
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        await ChangeService.set_scope_definition(
            db, change, current_user, body.scope_definition)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    change.deadline_state = await ChangeService.deadline_state(db, change)
    return await _price_safe(db, change, current_user, ChangeResponse)


@router.post("/{change_id}/concerns/{concern_id}/answer",
             response_model=ConcernResponse)
async def answer_concern(
    change_id: int, concern_id: int, body: ConcernAnswerIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Answer an open question: the asking department (or the author), Sales
    or Project Management. The concern stays OPEN, the side that asked
    decides whether the answer settles it (POST .../withdraw)."""
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    try:
        concern = await MeetingService.answer_concern(
            db, change, concern_id, current_user, note=body.note,
            answer_kind=body.answer_kind, ref=body.ref, mail_id=body.mail_id,
            assumed_value=body.assumed_value, assumed_unit=body.assumed_unit,
            assumed_risk=body.assumed_risk, confirm_by_id=body.confirm_by_id,
            confirm_due=body.confirm_due)
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
            reason=body.reason, need_by_check=body.need_by_check,
            need_by_proposed=body.need_by_proposed)
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
    """The stage-8 booking (labour position, machine hours) under the one
    Book hours rule (C15): your own department, at most 24 h per booking,
    dated and sourced like POST /hours."""
    from app.services.hours_service import HoursError, HoursForbidden
    from app.services.implementation_service import (
        ImplementationError, ImplementationService,
    )
    change = await _implementation_change(db, change_id, current_user)
    try:
        booking = await ImplementationService.create_booking(
            db, change, body.model_dump(), current_user)
    except HoursForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (HoursError, ImplementationError) as e:
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
    than an edit, so the changelog carries both halves of the fix. The one
    rule of DELETE /hours (C15): your own booking (an admin any) while the
    booking window is open; somebody else's hours are their statement about
    their day."""
    from app.services.hours_service import window_open
    from app.services.implementation_service import (
        ImplementationError, ImplementationService,
    )
    change = await _implementation_change(db, change_id, current_user)
    try:
        booking = await ImplementationService.get_booking(db, change, bid)
    except ImplementationError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if booking.booked_by != current_user.id and current_user.effective_role != "admin":
        raise HTTPException(status_code=403,
                            detail="Only your own booking is yours to take back")
    if not window_open(change):
        raise HTTPException(status_code=400,
                            detail="The booking window of this change has ended")
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
    # the backend's write rule per department, so the form shows exactly
    # where a measurement is accepted (C7: own department; the run team
    # only for a department with no member here)
    rights = await ValidationService.write_rights(
        db, change, [d["department_id"] for d in state["departments"]], current_user)
    for d in state["departments"]:
        d["can_write"] = rights.get(d["department_id"], False)
    from app.services import cm_switches
    if cm_switches.on("RELEASE_V2") and state["departments"]:
        # A5-04 d: a department with no real member here says who answers
        from app.services.change_people import (
            coordinator_name, no_member_words, staffed_department_ids,
        )
        ids = [d["department_id"] for d in state["departments"]]
        staffed = await staffed_department_ids(db, change, ids)
        if set(ids) - staffed:
            who = await coordinator_name(db, change)
            for d in state["departments"]:
                if d["department_id"] not in staffed:
                    d["no_member_hint"] = no_member_words(d["department_name"], who)
    # A5-02: the confirm button follows the backend rule
    pending = [c for d in state["departments"] for c in d["checks"]
               if c.get("limits_pending") and c.get("check_id")]
    if pending:
        from app.models.change_validation import ValidationCheck
        for c in pending:
            row = await db.get(ValidationCheck, c["check_id"])
            c["can_confirm_limits"] = await ValidationService.limits_confirm_refusal(
                db, change, row, current_user) is None
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
        from app.services import cm_switches
        raise HTTPException(
            status_code=403,
            detail=("A department's validation checks are recorded by its own "
                    "members while the change is in validation; Project "
                    "Management or the lead only for a department with no "
                    "member here (an admin acts as the department)"
                    if cm_switches.on("RELEASE_V2") else
                    "Only a member of that department while the change is in "
                    "validation, Project Management or an admin may sign off "
                    "its validation checks"))
    try:
        row = await ValidationService.record_check(
            db, change, body.model_dump(), current_user)
    except VError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/{change_id}/validation/checks/{check_id}/limits",
             response_model=ValidationCheckResponse)
async def confirm_validation_limits(
    change_id: int, check_id: int, body: ValidationLimitsIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """A5-02 / D5: APQP confirms (or corrects) the limits a measurer set with
    the first measurement; a PASS against them counts from then on."""
    from app.services.validation_service import (
        ValidationError as VError, ValidationService,
    )
    change = await _implementation_change(db, change_id, current_user)
    try:
        row = await ValidationService.confirm_limits(
            db, change, check_id, body.model_dump(), current_user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
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
