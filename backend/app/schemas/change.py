"""Pydantic schemas for Change Management."""
from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field, model_validator

from app.schemas.common import NaiveUtcDatetime

# The reason is a short description of the problem — one line, readable in a
# list. Anything longer is a scoping attachment, not a reason.
REASON_MAX_LENGTH = 100


class ChangeCreate(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=255)
    change_type: str = "physical_part"
    # A one-line "what is wrong", not an essay. The long form belongs in the
    # scoping attachments and the assessments.
    reason: Optional[str] = Field(None, max_length=REASON_MAX_LENGTH)
    description: Optional[str] = None
    priority: str = "medium"
    lead_id: Optional[int] = None
    data_classification: str = "confidential"
    customer_relevant: Optional[bool] = None


class ChangeUpdate(BaseModel):
    title: Optional[str] = None
    reason: Optional[str] = Field(None, max_length=REASON_MAX_LENGTH)
    description: Optional[str] = None
    priority: Optional[str] = None
    change_type: Optional[str] = None
    lead_id: Optional[int] = None
    estimated_cost: Optional[float] = None
    quoted_price: Optional[float] = None
    pnl_note: Optional[str] = None
    timing_milestone_id: Optional[int] = None
    issuer: Optional[str] = None
    is_series: Optional[bool] = None
    cm_internal: Optional[bool] = None
    cm_external: Optional[bool] = None
    implementation_mode: Optional[str] = None
    customer_relevant: Optional[bool] = None
    car_line: Optional[str] = None
    affected_plant_ids: Optional[List[int]] = None
    required_by_date: Optional[NaiveUtcDatetime] = None
    required_by_reason: Optional[str] = None
    release_due_date: Optional[NaiveUtcDatetime] = None
    release_due_reason: Optional[str] = None


class TransitionRequest(BaseModel):
    to_status: str
    cancellation_reason: Optional[str] = None
    rejection_reason: Optional[str] = None
    reopen_reason: Optional[str] = None


class CustomerResponseRequest(BaseModel):
    response: str  # accepted | declined | negotiating
    # Mandatory when response == 'accepted' (enforced in the service)
    release_due_date: Optional[NaiveUtcDatetime] = None
    release_due_reason: Optional[str] = None


class SignOffRequest(BaseModel):
    role: str  # pm | quality


class ImpactedItemCreate(BaseModel):
    part_id: int
    impact_note: Optional[str] = None
    eng_level_before: Optional[str] = None
    is_lead: bool = False


class AssessmentSubmit(BaseModel):
    department_id: int
    verdict: str
    cost_impact: Optional[float] = None
    lead_time_impact_days: Optional[int] = None
    conditions: Optional[str] = None
    notes: Optional[str] = None
    responsible_id: Optional[int] = None
    effort_hours: Optional[float] = Field(None, ge=0)
    # Free-form per-department questionnaire answers (e.g. Packaging's
    # packaging_impacted / change kinds). Stored as JSON; omit to leave the
    # stored answers untouched.
    details: Optional[dict] = None


class ImpactedItemResponse(BaseModel):
    id: int
    part_id: int
    impact_note: Optional[str] = None
    eng_level_before: Optional[str] = None
    eng_level_after: Optional[str] = None
    is_lead: bool = False
    resulting_revision_id: Optional[int] = None

    class Config:
        from_attributes = True


class AssessmentResponse(BaseModel):
    id: int
    department_id: int
    verdict: str
    cost_impact: Optional[float] = None
    lead_time_impact_days: Optional[int] = None
    conditions: Optional[str] = None
    notes: Optional[str] = None
    responsible_id: Optional[int] = None
    effort_hours: Optional[float] = None
    submitted_at: Optional[datetime] = None
    # Evidence filed against this assessment, and whether its checklist implies
    # an RFQ is owed (modification_external). Advisory — except has_change_ppt,
    # which is the thing "not feasible" is actually gated on.
    has_evidence: bool = False
    has_change_ppt: bool = False
    has_rfq: bool = False
    rfq_expected: bool = False
    stage_order: int = 1
    rasic_letter: str = "R"
    status: str = "active"
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    accepted_at: Optional[datetime] = None
    due_date: Optional[datetime] = None
    overdue: bool = False
    details: dict = {}

    @model_validator(mode="before")
    @classmethod
    def _read_through(cls, data: Any) -> Any:
        """Map the ORM's execution-state columns through effective_* so the
        linked WfInstanceTask (Phase E) is the source of truth for status/
        owner/acceptance/due-date/overdue, while all other fields are copied
        verbatim from the assessment row itself."""
        if hasattr(data, "effective_status"):
            return {
                **{f: getattr(data, f) for f in (
                    "id", "department_id", "verdict", "cost_impact",
                    "lead_time_impact_days", "conditions", "notes",
                    "responsible_id", "effort_hours", "submitted_at",
                    "stage_order", "rasic_letter")},
                "status": data.effective_status,
                "owner_id": data.effective_owner_id,
                "owner_name": data.effective_owner_name,
                "accepted_at": data.effective_accepted_at,
                "due_date": data.effective_due_date,
                "overdue": data.effective_overdue,
                "details": data.details_dict,
                # Set by the detail endpoint; absent elsewhere, hence getattr.
                "has_evidence": getattr(data, "has_evidence", False),
                "has_change_ppt": getattr(data, "has_change_ppt", False),
                "has_rfq": getattr(data, "has_rfq", False),
                "rfq_expected": getattr(data, "rfq_expected", False),
            }
        return data

    class Config:
        from_attributes = True


class AssessmentAssignIn(BaseModel):
    user_id: int


class AssessmentDueDateIn(BaseModel):
    due_date: NaiveUtcDatetime


class AttachmentResponse(BaseModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    phase: str = "baseline"
    kind: str = "general"          # general | info_request | info_response
    responds_to_id: Optional[int] = None
    concern_id: Optional[int] = None
    assessment_id: Optional[int] = None
    created_at: datetime
    uploaded_by: int
    uploaded_by_name: Optional[str] = None

    class Config:
        from_attributes = True


class ChangelogResponse(BaseModel):
    id: int
    action: str
    action_description: str
    performed_by: int
    performed_at: datetime
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class InternalApprovalIn(BaseModel):
    note: Optional[str] = None
    # Mandatory — internal approval sets the release deadline (service enforces)
    release_due_date: Optional[NaiveUtcDatetime] = None
    release_due_reason: Optional[str] = None


class ChangeResponse(BaseModel):
    id: int
    change_number: str
    project_id: int
    # Project.code + name: no change response should force a second call to
    # say which project it belongs to.
    project_number: Optional[str] = None
    project_name: Optional[str] = None
    title: str
    description: Optional[str] = None
    reason: Optional[str] = None
    change_type: str
    priority: str
    status: str
    lead_id: Optional[int] = None
    lead_name: Optional[str] = None
    raised_by: int
    customer_response: str
    pm_signed_by: Optional[int] = None
    quality_signed_by: Optional[int] = None
    estimated_cost: Optional[float] = None
    quoted_price: Optional[float] = None
    issuer: Optional[str] = None
    is_series: bool = False
    cm_internal: bool = False
    cm_external: bool = False
    implementation_mode: Optional[str] = None
    customer_relevant: bool = False
    car_line: Optional[str] = None
    affected_plant_ids: List[int] = []
    required_by_date: Optional[datetime] = None
    required_by_reason: Optional[str] = None
    deadline_state: Optional[str] = None
    quoted_at: Optional[datetime] = None
    quoted_on_time: Optional[bool] = None
    active_deadline: Optional[str] = None  # quote | release | None
    # Departments soft-held by an open assessment concern (badge source).
    blocked_department_ids: List[int] = []
    # Departments that found the change feasible but have priced nothing yet.
    # Populated only while the change is in costing (see the endpoint).
    costing_pending_department_ids: List[int] = []
    release_due_date: Optional[datetime] = None
    release_due_reason: Optional[str] = None
    impact_confirmed_by: Optional[int] = None
    impact_confirmed_by_name: Optional[str] = None
    impact_confirmed_at: Optional[datetime] = None
    internal_approved_by: Optional[int] = None
    internal_approved_at: Optional[datetime] = None
    internal_approved_amount: Optional[float] = None
    internal_approval_note: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejection_sent_at: Optional[datetime] = None
    rejection_sent_by: Optional[int] = None
    rejected_by: Optional[int] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def extract_affected_plant_ids(cls, data: Any) -> Any:
        """When building from an ORM ChangeRequest, map affected_plants → affected_plant_ids.

        Pydantic from_attributes reads obj.affected_plant_ids which doesn't exist on the
        ORM model (the relationship is named affected_plants). We inject it here.
        """
        if hasattr(data, "affected_plants"):
            # ORM object: extract plant ids and return a dict for Pydantic to validate.
            # We use __dict__ as a base so subclasses (ChangeDetailResponse) also get
            # their extra ORM relationships (impacted_items, assessments, attachments).
            plants = data.affected_plants or []
            plant_ids = [p.id for p in plants]
            # Build a plain dict from the ORM instance's loaded state
            row = {k: v for k, v in vars(data).items() if not k.startswith("_")}
            row["affected_plant_ids"] = plant_ids
            row["lead_name"] = data.lead_name
            row["impact_confirmed_by_name"] = data.impact_confirmed_by_name
            # Model properties (not in __dict__) must be injected explicitly.
            row["active_deadline"] = data.active_deadline
            row["quoted_on_time"] = data.quoted_on_time
            row["blocked_department_ids"] = data.blocked_department_ids
            row["project_number"] = data.project_number
            row["project_name"] = data.project_name
            return row
        return data

    class Config:
        from_attributes = True


class ChangeDetailResponse(ChangeResponse):
    impacted_items: List[ImpactedItemResponse] = []
    assessments: List[AssessmentResponse] = []
    attachments: List[AttachmentResponse] = []


class RoutingDepartment(BaseModel):
    department_id: int
    rasic_letter: str
    tier: str          # blocking | optional | info
    status: Optional[str] = None     # None for info-only
    verdict: Optional[str] = None
    assessment_id: Optional[int] = None


class RoutingStage(BaseModel):
    stage_order: int
    departments: List[RoutingDepartment] = []


class RoutingResponse(BaseModel):
    change_id: int
    template_id: Optional[int] = None
    template_version: Optional[int] = None
    has_deviation: bool = False
    deviation_status: str = "none"
    stages: List[RoutingStage] = []


class DeviationRequest(BaseModel):
    op: str                       # add | remove | reletter
    department_id: int
    rasic_letter: Optional[str] = None
    stage_order: Optional[int] = None


class RoutingStandardUpsert(BaseModel):
    change_type: str
    template_id: int
    template_version: int = 1


class CheckStandardIn(BaseModel):
    item_category: str
    template_id: int


class CheckStandardResponse(BaseModel):
    id: int
    item_category: str
    template_id: int
    template_version: int

    class Config:
        from_attributes = True


class CostLineIn(BaseModel):
    plant_id: int
    cost_kind: str = "one_time"
    demand_hours: float = 0.0
    external_cost: float = 0.0
    activity_id: Optional[int] = None
    activity_label: Optional[str] = None
    # Lifecycle cost per part. Negative means the change SAVES cycle time, so
    # no ge= constraint here on purpose.
    minutes_per_part: Optional[float] = None
    note: Optional[str] = None


class CostLineReplace(BaseModel):
    lines: List[CostLineIn] = []


class CostLineResponse(BaseModel):
    id: int
    plant_id: int
    activity_id: Optional[int] = None
    activity_label: Optional[str] = None
    cost_kind: str
    demand_hours: float
    rate_snapshot: float
    internal_cost: float
    external_cost: float
    minutes_per_part: Optional[float] = None
    note: Optional[str] = None

    class Config:
        from_attributes = True


class PlantRollup(BaseModel):
    plant_id: int
    one_time_internal: float
    one_time_external: float
    lifecycle_internal: float
    lifecycle_external: float


class DeptRollup(BaseModel):
    department_id: int
    one_time_internal: float
    one_time_external: float
    lifecycle_internal: float
    lifecycle_external: float


class DeptPlantRollup(BaseModel):
    """One cell of the workbook matrix: a department's costs at one plant."""
    department_id: int
    plant_id: int
    one_time_internal: float
    one_time_external: float
    lifecycle_internal: float
    lifecycle_external: float
    demand_hours: float = 0.0
    minutes_per_part: float = 0.0


class SummationTotals(BaseModel):
    one_time_internal: float
    one_time_external: float
    lifecycle_internal: float
    lifecycle_external: float
    grand_total: float


class EffortRollup(BaseModel):
    department_id: int
    effort_hours: float


class LeadTimeRollup(BaseModel):
    department_id: int
    lead_time_days: int


class PlantMinutesRollup(BaseModel):
    plant_id: int
    minutes_per_part: float


class PositionRollup(BaseModel):
    """The position half of a department's costs. Already inside
    by_department and totals; broken out so "how much of this is supplier
    money" is answerable without re-adding it."""
    department_id: int
    position_cost: float = 0.0
    hours: float = 0.0
    position_count: int = 0


class SummationResponse(BaseModel):
    by_plant: List[PlantRollup] = []
    by_department: List[DeptRollup] = []
    by_department_plant: List[DeptPlantRollup] = []
    totals: SummationTotals
    effort_by_department: List[EffortRollup] = []
    total_effort_hours: float = 0.0
    # Always CALENDAR days: a position quoted in business days is converted
    # (7/5, rounded up) before it joins the max.
    lead_time_by_department: List[LeadTimeRollup] = []
    # The slowest department, not the sum: they wait in parallel.
    max_lead_time_days: int = 0
    lifecycle_minutes_by_plant: List[PlantMinutesRollup] = []
    total_minutes_per_part: float = 0.0
    positions_by_department: List[PositionRollup] = []
    total_position_cost: float = 0.0


# --- costing positions ------------------------------------------------------

class CostingOfferCreate(BaseModel):
    vendor_name: str
    cost: float
    # Either stated separately, or declared part of the price. Quotes come
    # both ways and comparing them needs to know which.
    shipping_cost: Optional[float] = None
    shipping_included: bool = False
    lead_time_days: Optional[int] = None
    # business_days | calendar_days. A tool shop quotes working days; the plan
    # runs on the calendar. Roll-ups convert before comparing.
    lead_time_unit: str = "calendar_days"
    favorite: bool = False


class CostingOfferUpdate(BaseModel):
    """Partial: only the fields actually sent are written, so clearing
    shipping_cost to null is distinguishable from not mentioning it."""
    vendor_name: Optional[str] = None
    cost: Optional[float] = None
    shipping_cost: Optional[float] = None
    shipping_included: Optional[bool] = None
    lead_time_days: Optional[int] = None
    lead_time_unit: Optional[str] = None
    favorite: Optional[bool] = None


class CostingOfferAttachment(BaseModel):
    id: int
    filename: str
    size_bytes: int
    kind: str
    uploaded_by: int
    uploaded_by_name: Optional[str] = None
    created_at: datetime


class CostingOfferResponse(BaseModel):
    id: int
    position_id: int
    vendor_name: str
    cost: float
    shipping_cost: Optional[float] = None
    shipping_included: bool = False
    lead_time_days: Optional[int] = None
    lead_time_unit: str = "calendar_days"
    # The same promise on the calendar, for comparing offers quoted in
    # different units (business days scale by 7/5, rounded up).
    lead_time_calendar_days: Optional[int] = None
    favorite: bool = False
    # cost plus shipping, unless the vendor already included it.
    total_cost: float = 0.0
    created_by: int
    created_at: datetime
    attachments: List[CostingOfferAttachment] = []


class CostingPositionCreate(BaseModel):
    department_id: int
    label: str
    kind: str = "external"          # internal_effort|support_effort|external
    tag: Optional[str] = None       # free text; the reference list only suggests
    pricing: str = "estimate"       # estimate|quote — external positions only
    est_cost: Optional[float] = None
    # Accepted on every kind, external included: the department's own time
    # around a supplier's work is effort too.
    hours: Optional[float] = None
    lead_time_days: Optional[int] = None
    lead_time_unit: str = "calendar_days"
    notes: Optional[str] = None


class CostingPositionUpdate(BaseModel):
    """Partial. department_id is absent on purpose: moving a position between
    departments would move money between budgets with no record."""
    label: Optional[str] = None
    kind: Optional[str] = None
    tag: Optional[str] = None
    pricing: Optional[str] = None
    est_cost: Optional[float] = None
    hours: Optional[float] = None
    lead_time_days: Optional[int] = None
    lead_time_unit: Optional[str] = None
    notes: Optional[str] = None


class CostingPositionResponse(BaseModel):
    id: int
    change_id: int
    department_id: int
    label: str
    tag: Optional[str] = None
    kind: str
    pricing: str
    est_cost: Optional[float] = None
    hours: Optional[float] = None
    lead_time_days: Optional[int] = None
    lead_time_unit: str = "calendar_days"
    notes: Optional[str] = None
    created_by: int
    created_at: datetime
    updated_at: datetime
    # What the position is worth however it is priced: the favorite offer
    # (plus shipping when stated separately) for a quoted external position,
    # the estimate otherwise. None means nobody has said yet.
    effective_cost: Optional[float] = None
    # The favorite offer's dates when a supplier set them, this position's
    # own otherwise — in its own unit, and converted for the roll-ups.
    effective_lead_time_days: Optional[int] = None
    effective_lead_time_unit: str = "calendar_days"
    effective_lead_time_calendar_days: Optional[int] = None
    favorite_offer_id: Optional[int] = None
    offers: List[CostingOfferResponse] = []


class GateDecisionIn(BaseModel):
    decision: str  # yes | no | na
    remark: Optional[str] = None


class GateResponse(BaseModel):
    gate_key: str
    decision: str
    decided_by: Optional[int] = None
    decided_at: Optional[datetime] = None
    remark: Optional[str] = None

    class Config:
        from_attributes = True


class MeetingParticipant(BaseModel):
    name: str
    user_id: Optional[int] = None


class MeetingCreate(BaseModel):
    meeting_date: Optional[NaiveUtcDatetime] = None
    channel: str = "meeting"  # meeting | chat | email
    participants: List[MeetingParticipant] = []
    notes: Optional[str] = None
    selected_department_ids: List[int] = []


class MeetingUpdate(BaseModel):
    meeting_date: Optional[NaiveUtcDatetime] = None
    participants: Optional[List[MeetingParticipant]] = None
    notes: Optional[str] = None
    selected_department_ids: Optional[List[int]] = None


class ConcernCreate(BaseModel):
    # Direct raises are risks only; reject_proposal/needs_info are written by
    # the scoping decision that produced them.
    kind: str = "risk"
    note: str = Field(min_length=1)
    # Required while the change is in assessment (the raiser's own
    # department); must stay unset during scoping.
    department_id: Optional[int] = None
    # Required for kind "risk" — see RISK_TYPES / severity 1-3 in models.
    risk_type: Optional[str] = None
    severity: Optional[int] = None


class CostLeadTimeIn(BaseModel):
    department_id: int
    lead_time_days: int = Field(ge=0)


class ConcernAnswerIn(BaseModel):
    # Optional: a response document filed into the concern counts as content.
    note: Optional[str] = None


class ConcernWithdrawIn(BaseModel):
    # Required to withdraw a department-scoped (assessment-phase) concern.
    resolution_note: Optional[str] = None


class ConcernResponse(BaseModel):
    id: int
    change_id: int
    kind: str
    note: str
    raised_by: int
    raised_by_name: Optional[str] = None
    raised_at: datetime
    department_id: Optional[int] = None
    # Set on kind "risk" only; null on legacy kinds.
    risk_type: Optional[str] = None
    severity: Optional[int] = None
    raised_by_meeting_id: Optional[int] = None
    answer_note: Optional[str] = None
    answered_at: Optional[datetime] = None
    answered_by: Optional[int] = None
    withdrawn_at: Optional[datetime] = None
    resolution_note: Optional[str] = None
    resolved_by_meeting_id: Optional[int] = None
    is_open: bool = True

    class Config:
        from_attributes = True


class MeetingDecideIn(BaseModel):
    decision: str  # proceed | reject | needs_info
    # Required for reject and needs_info; ignored for proceed.
    reason: Optional[str] = None


class MeetingResponse(BaseModel):
    id: int
    change_id: int
    decision_reason: Optional[str] = None
    meeting_date: datetime
    channel: str = "meeting"
    participants: List[MeetingParticipant] = []
    notes: Optional[str] = None
    decision: Optional[str] = None
    selected_department_ids: List[int] = []
    created_by: int
    created_at: datetime
    decided_by: Optional[int] = None
    decided_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ImpactSuggestIn(BaseModel):
    part_ids: List[int]


class ImpactSelectionIn(BaseModel):
    part_ids: List[int]


class DeviationProposeIn(BaseModel):
    to_status: str
    reason: str


class DeviationDecideIn(BaseModel):
    decision: str  # approved | rejected
    note: Optional[str] = None


class TransitionDeviationResponse(BaseModel):
    id: int
    to_status: str
    reason: str
    status: str
    proposed_by: int
    proposed_at: datetime
    decided_by: Optional[int] = None
    decided_at: Optional[datetime] = None
    decision_note: Optional[str] = None

    class Config:
        from_attributes = True
