"""Pydantic schemas for Change Management."""
import json
from datetime import date, datetime
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    # Mother-plant side track (spec §14): origin 'mother_plant' carries the
    # plant (one of app/services/mother_plants.MOTHER_PLANTS, default
    # Weissenburg), their reference and the SOP date (required).
    origin: Optional[str] = None
    mother_plant_name: Optional[str] = Field(None, max_length=120)
    mother_plant_ref: Optional[str] = Field(None, max_length=120)
    mother_plant_sop: Optional[date] = None
    # Atomic capture (spec §16): the impacted items in the same request.
    # The first id is the lead unless lead_part_id says otherwise; with
    # title_auto (default) the server composes the title from the lead.
    impacted_part_ids: Optional[List[int]] = None
    lead_part_id: Optional[int] = None
    title_auto: Optional[bool] = None


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
    # The generic one, for hops whose reason has no dedicated field. Currently
    # mandatory for exactly one: in_validation -> in_implementation, where it
    # says what failed validation and what has to be replanned or renegotiated
    # (recorded as 'validation_escalated'). escalation_reason is accepted as
    # its alias so an older client keeps working.
    reason: Optional[str] = None
    escalation_reason: Optional[str] = None
    # Final walk P2-3: when a soft guard refuses the hop and an approved
    # deviation would lift it, the endpoint files the deviation request with
    # this reason (or reuses the pending one) and answers 202 with it,
    # instead of a bare 400. Ignored when the hop goes through.
    deviation_reason: Optional[str] = None


class CustomerResponseRequest(BaseModel):
    response: str  # accepted | declined | negotiating
    # Mandatory when response == 'accepted' (enforced in the service)
    release_due_date: Optional[NaiveUtcDatetime] = None
    release_due_reason: Optional[str] = None
    # Required to accept when the latest sent offer version has expired.
    expired_override_reason: Optional[str] = None


class SignOffRequest(BaseModel):
    role: str  # pm | quality


class ImpactedItemCreate(BaseModel):
    part_id: int
    impact_note: Optional[str] = None
    eng_level_before: Optional[str] = None
    is_lead: bool = False
    # Required from 'quoted' on: the offer no longer covers the scope.
    reason: Optional[str] = None


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
    # The article itself, so a list of impacted items reads without a lookup
    # per row. Filled in one batch by the endpoints (fill_part_labels).
    part_number: Optional[str] = None
    part_name: Optional[str] = None

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
    # "Not our responsibility" pending the lead's decision (spec §16): the
    # letter asked for; the row keeps rasic_letter until approval.
    pending_rasic_letter: Optional[str] = None
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
                "pending_rasic_letter": getattr(data, "pending_rasic_letter", None),
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
    validation_issue_id: Optional[int] = None
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
    # Which field changed, and its before/after (e.g. field_name="status",
    # old_value="on_hold", new_value="in_assessment"). Absent on rows that
    # don't carry a single before/after (most actions), and blanked by
    # price_redaction.redact_changelog_row for a money-carrying field_name
    # when the viewer may not read prices.
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None

    @field_validator("old_value", "new_value", mode="before")
    @classmethod
    def _decode_json_string(cls, v: Any) -> Any:
        """The changelog stores its values as JSON text, so a status reads
        '"on_hold"' in the column. A JSON string goes out as its plain value
        ('on_hold'); JSON objects, numbers and non-JSON text stay as stored."""
        if isinstance(v, str) and v.startswith('"'):
            try:
                decoded = json.loads(v)
            except ValueError:
                return v
            if isinstance(decoded, str):
                return decoded
        return v

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
    # Spec §16: the title follows the lead item; an impact edit after the
    # quote leaves the offer short of the scope.
    title_auto: bool = False
    scope_changed_after_quote: bool = False
    # Set by the list endpoint: the caller leads or raised the change.
    is_mine: bool = False
    # customer | internal | mother_plant (migration 093, spec §14) |
    # engineering_review (spec §17, the light track of a new index).
    origin: str = "customer"
    # Spec §17: the change was started by (or took) a revision intake.
    from_intake: bool = False
    mother_plant_name: Optional[str] = None
    mother_plant_ref: Optional[str] = None
    mother_plant_sop: Optional[date] = None
    # The team informed (mother plant): first send, and the departments
    # that have not confirmed "Read and understood" yet (Blocked by, info).
    info_sent_at: Optional[datetime] = None
    info_department_ids: List[int] = []
    info_open_department_ids: List[int] = []
    car_line: Optional[str] = None
    affected_plant_ids: List[int] = []
    required_by_date: Optional[datetime] = None
    required_by_reason: Optional[str] = None
    # Costing to close (087).
    plan_revision: int = 0
    timing_validated_at: Optional[datetime] = None
    timing_validated_by: Optional[int] = None
    accepted_offer_id: Optional[int] = None
    lessons_done_at: Optional[datetime] = None
    lessons_none_reason: Optional[str] = None
    deadline_state: Optional[str] = None
    quoted_at: Optional[datetime] = None
    quoted_on_time: Optional[bool] = None
    active_deadline: Optional[str] = None  # quote | release | None
    # Departments soft-held by an open assessment concern (badge source).
    blocked_department_ids: List[int] = []
    # Departments that found the change feasible but have priced nothing yet.
    # Populated only while the change is in costing (see the endpoint).
    costing_pending_department_ids: List[int] = []
    # Departments with costing lines the cost sheet cannot price (no rate):
    # [{department_id, department_name, count, message}], message = "No cost
    # sheet rate for <department>: hours unpriced". In costing and quoting.
    costing_unpriced: List[dict] = []
    release_due_date: Optional[datetime] = None
    release_due_reason: Optional[str] = None
    impact_confirmed_by: Optional[int] = None
    impact_confirmed_by_name: Optional[str] = None
    impact_confirmed_at: Optional[datetime] = None
    # The part weight, quoted at costing and weighed at validation. Both halves
    # ride on every change response: the estimate is what Sales priced, the
    # validated number is what the tool actually makes, and the delta between
    # them is a quote update.
    estimated_part_weight_g: Optional[float] = None
    estimated_weight_by: Optional[int] = None
    estimated_weight_by_name: Optional[str] = None
    estimated_weight_at: Optional[datetime] = None
    validated_part_weight_g: Optional[float] = None
    validated_weight_by: Optional[int] = None
    validated_weight_by_name: Optional[str] = None
    validated_weight_at: Optional[datetime] = None
    # The commercial answer to a validated weight that missed the estimate:
    # the quote was updated, or the delta was absorbed. Null while the
    # question is still open.
    weight_delta_ack_at: Optional[datetime] = None
    weight_delta_ack_by: Optional[int] = None
    weight_delta_ack_note: Optional[str] = None
    # The scheduling block: how the changeover runs (running change vs planned
    # scrap), what the scrap costs the customer, and whether Sales has put the
    # plan in front of them yet. The frontend derives its wait states from the
    # gaps here — mode unset means Scheduling still owes a decision, an
    # unpublished mode means Sales still owes the customer the plan.
    bank_build_mode: Optional[str] = None
    bank_build_note: Optional[str] = None
    scrap_quote_price: Optional[float] = None
    # Whether a scrap quote price is on record. Never redacted: a viewer who
    # may not read the price still needs to know one exists (reads "set").
    scrap_price_set: bool = False
    bank_build_set_by: Optional[int] = None
    bank_build_set_by_name: Optional[str] = None
    bank_build_set_at: Optional[datetime] = None
    plan_published_by: Optional[int] = None
    plan_published_by_name: Optional[str] = None
    plan_published_at: Optional[datetime] = None
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
            row["estimated_weight_by_name"] = data.estimated_weight_by_name
            row["validated_weight_by_name"] = data.validated_weight_by_name
            row["bank_build_set_by_name"] = data.bank_build_set_by_name
            row["plan_published_by_name"] = data.plan_published_by_name
            # Model properties (not in __dict__) must be injected explicitly.
            row["active_deadline"] = data.active_deadline
            row["quoted_on_time"] = data.quoted_on_time
            row["blocked_department_ids"] = data.blocked_department_ids
            row["negotiated_final_price"] = data.negotiated_final_price
            row["scrap_price_set"] = data.scrap_quote_price is not None
            row["info_sent_at"] = getattr(data, "info_sent_at", None)
            row["info_department_ids"] = getattr(data, "info_department_ids", [])
            row["info_open_department_ids"] = getattr(
                data, "info_open_department_ids", [])
            row["project_number"] = data.project_number
            row["project_name"] = data.project_name
            row["project_plant_id"] = (data.project.plant_id
                                       if data.project is not None else None)
            return row
        return data

    class Config:
        from_attributes = True


class ChangeDetailResponse(ChangeResponse):
    # The project's plant (Project.plant_id): the plant the change is made in.
    project_plant_id: Optional[int] = None
    impacted_items: List[ImpactedItemResponse] = []
    assessments: List[AssessmentResponse] = []
    attachments: List[AttachmentResponse] = []
    # Read-through from the final negotiation round (see
    # ChangeRequest.negotiated_final_price) — the number Sales' go-ahead is
    # based on when it is not the quoted one. No column behind it.
    negotiated_final_price: Optional[float] = None


class RoutingDepartment(BaseModel):
    department_id: int
    rasic_letter: str
    tier: str          # blocking | optional | info
    status: Optional[str] = None     # None for info-only
    verdict: Optional[str] = None
    assessment_id: Optional[int] = None
    pending_rasic_letter: Optional[str] = None
    # A pending deviation asks to take this row off the routing; it stays
    # (still owed) until the decision.
    pending_removal: bool = False


class RoutingStage(BaseModel):
    stage_order: int
    departments: List[RoutingDepartment] = []


class RoutingResponse(BaseModel):
    change_id: int
    template_id: Optional[int] = None
    template_version: Optional[int] = None
    has_deviation: bool = False
    deviation_status: str = "none"
    # Why the pending/last deviation was proposed and by whom, so the lead can
    # decide from the routing view alone.
    deviation_note: Optional[str] = None
    deviation_proposed_by: Optional[int] = None
    stages: List[RoutingStage] = []


class DeviationRequest(BaseModel):
    op: str                       # add | remove | reletter
    department_id: int
    rasic_letter: Optional[str] = None
    stage_order: Optional[int] = None
    # Required for op "add" (enforced in the service): the audit reason.
    reason: Optional[str] = None


class RoutingDeviationDecision(BaseModel):
    reason: str


class RiskTemplateCreate(BaseModel):
    department_id: int
    risk_type: str
    severity: int = 2
    note: str


class CostCategoryCreate(BaseModel):
    department_id: int
    label: str
    entry_type: str = "money"   # money | time


class CostCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    department_id: int
    key: str
    label: str
    entry_type: str


class RiskTypeCreate(BaseModel):
    department_id: int
    label: str


class RiskTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    department_id: int
    key: str
    label: str


class RiskTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    department_id: int
    risk_type: str
    severity: int
    note: str
    created_by: int
    created_at: datetime


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
    rate_snapshot: Optional[float] = None
    internal_cost: float
    external_cost: float
    minutes_per_part: Optional[float] = None
    note: Optional[str] = None

    class Config:
        from_attributes = True


class ActualsDeptRow(BaseModel):
    department_id: int
    department_name: Optional[str] = None
    booked_hours: float
    # The rate the hours were valued at, and null when the plant has none for
    # this department — in which case actual_cost is a floor, not a total.
    hourly_rate: Optional[float] = None
    # Every rate the bookings were priced with (the one valid on each
    # booking's date); hourly_rate is None when there is more than one.
    rates: List[float] = []
    machine_hours: float = 0.0
    machine_cost: float = 0.0
    actual_cost: float
    plan_cost: float
    variance: float
    unrated: bool


class ActualsExtra(BaseModel):
    # scrap_quote | weight_delta
    key: str
    label: Optional[str] = None
    # Null where the cost is real but not yet a number anybody may state — the
    # weight delta is a negotiation, not arithmetic.
    amount: Optional[float] = None
    delta_g: Optional[float] = None
    acknowledged: Optional[bool] = None


class ActualsBlock(BaseModel):
    departments: List[ActualsDeptRow] = []
    extras: List[ActualsExtra] = []
    total_actual: float = 0.0
    total_plan: float = 0.0
    total_booked_hours: float = 0.0
    total_extras: float = 0.0
    unrated_hours: bool = False
    rate_plant_id: Optional[int] = None
    variance: float = 0.0
    currency: Optional[str] = None
    other_currency: Dict[str, float] = {}
    total_machine_hours: float = 0.0


class PlantRollup(BaseModel):
    plant_id: int
    one_time_internal: float
    one_time_external: float
    lifecycle_internal: float
    lifecycle_external: float
    currency: Optional[str] = None


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
    currency: Optional[str] = None


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


class PositionVendorDetail(BaseModel):
    """One position's vendor story: what the department recommended, what
    Sales chose, and why when the two differ. `cost` is what the summation
    counted — the chosen offer once there is one."""
    position_id: int
    label: str
    kind: str
    cost: float = 0.0
    currency: Optional[str] = None
    # hours (trials) x the line's rate; None = no rate in the cost sheet
    line_value: Optional[float] = None
    rate: Optional[float] = None
    recommended_vendor: Optional[str] = None
    recommended_cost: Optional[float] = None
    chosen_vendor: Optional[str] = None
    chosen_cost: Optional[float] = None
    chosen_reason: Optional[str] = None
    choice_diverges: bool = False


class PositionRollup(BaseModel):
    """The position half of a department's costs. Already inside
    by_department and totals; broken out so "how much of this is supplier
    money" is answerable without re-adding it."""
    department_id: int
    position_cost: float = 0.0
    hours: float = 0.0
    # hours × the department's rate at the costing plant, the same valuation a
    # cost line gives demand_hours. Counted in one_time_internal.
    hours_cost: float = 0.0
    machine_hours: float = 0.0
    trials: int = 0
    unpriced_count: int = 0
    position_count: int = 0
    # Hours were declared but no rate is configured for this department at the
    # costing plant, so they are valued at zero. Flagged rather than guessed.
    unrated_hours: bool = False
    # Per position, so the wrap-up can name the vendor decisions rather than
    # only their sum.
    positions: List[PositionVendorDetail] = []


class UnpricedLine(BaseModel):
    position_id: int
    department_id: int
    label: str
    kind: str
    quantity: float = 0.0
    unit: str = "h"
    reason: Optional[str] = None
    message: str = "No rate in the cost sheet"


class SummationWarning(BaseModel):
    code: str
    message: str


class SummationResponse(BaseModel):
    # Spec §15 phase 2: totals, by_department and the position margins are
    # in `currency` (the costing plant's); totals_by_currency holds every
    # currency's own sums. Currencies are never added or converted.
    currency: Optional[str] = None
    # the revenue's currency (basis offer's, else `currency`): no margin when it differs
    revenue_currency: Optional[str] = None
    totals_by_currency: Dict[str, SummationTotals] = {}
    mixed_currency: bool = False
    unpriced_lines: List[UnpricedLine] = []
    warnings: List[SummationWarning] = []
    cost_sheet_versions_used: List[int] = []
    cost_sheet_current_version: Optional[int] = None
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
    total_position_hours_cost: float = 0.0
    # Not money, but it belongs to the same wrap-up: Sales prices the weight
    # change into the quote off this number, and looking it up on a different
    # screen than the costs is how it gets forgotten. Grams; None until the
    # Tooling Engineer states it.
    part_weight_estimate_g: Optional[float] = None
    # Stage 9: what the change ACTUALLY cost, next to the plan above. Booked
    # implementation hours × the departments' current rates, plus the costs
    # that are not hours. Additive — a caller that only wants the plan reads
    # exactly what it always read.
    actuals: Optional[ActualsBlock] = None


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
    # Partial quote: part of the line, always counted. Default: a full quote,
    # one alternative among others.
    is_partial: bool = False


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
    is_partial: Optional[bool] = None


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
    # The DEPARTMENT's recommendation.
    favorite: bool = False
    is_partial: bool = False
    # cost plus shipping, unless the vendor already included it.
    total_cost: float = 0.0
    # SALES' decision, with the accountability on it. chosen_reason is
    # mandatory (enforced in the service) only when the decision goes against
    # the recommendation above.
    chosen: bool = False
    chosen_reason: Optional[str] = None
    chosen_by: Optional[int] = None
    chosen_by_name: Optional[str] = None
    chosen_at: Optional[datetime] = None
    created_by: int
    created_at: datetime
    attachments: List[CostingOfferAttachment] = []


class VendorChoiceIn(BaseModel):
    # Required when the chosen offer is not the department's favorite —
    # refused with 400 naming the accountability. Optional when it agrees.
    reason: Optional[str] = None


class CostingPositionCreate(BaseModel):
    department_id: int
    label: str
    kind: str = "external"          # internal_effort|support_effort|own_time|external
    tag: Optional[str] = None       # free text; the reference list only suggests
    pricing: str = "estimate"       # estimate|quote — external positions only
    est_cost: Optional[float] = None
    # Who gave the house number on an estimated line; quoted lines name their
    # vendors on the offers.
    vendor_name: Optional[str] = None
    # Accepted on every kind, external included: the department's own time
    # around a supplier's work is effort too.
    hours: Optional[float] = None
    lead_time_days: Optional[int] = None
    lead_time_unit: str = "calendar_days"
    notes: Optional[str] = None
    # Cost sheet pricing (spec §15 phase 2): the labour position that picks
    # the rate (own time), the machine class (machine_time, sampling; default
    # the change's class) and the number of trials (sampling).
    labour_position: Optional[str] = Field(default=None, max_length=80)
    machine_class_id: Optional[int] = None
    trials: Optional[int] = Field(default=None, ge=0, le=10000)
    # A named MachineDB press (machine_time, sampling): its own cost sheet
    # rate beats the class rate.
    machine_id: Optional[int] = None


class CostingPositionUpdate(BaseModel):
    """Partial. department_id is absent on purpose: moving a position between
    departments would move money between budgets with no record."""
    label: Optional[str] = None
    kind: Optional[str] = None
    tag: Optional[str] = None
    pricing: Optional[str] = None
    est_cost: Optional[float] = None
    vendor_name: Optional[str] = None
    hours: Optional[float] = None
    lead_time_days: Optional[int] = None
    lead_time_unit: Optional[str] = None
    notes: Optional[str] = None
    labour_position: Optional[str] = Field(default=None, max_length=80)
    machine_class_id: Optional[int] = None
    trials: Optional[int] = Field(default=None, ge=0, le=10000)
    # A named MachineDB press (machine_time, sampling): its own cost sheet
    # rate beats the class rate.
    machine_id: Optional[int] = None


class CostingPositionResponse(BaseModel):
    id: int
    change_id: int
    department_id: int
    label: str
    tag: Optional[str] = None
    kind: str
    pricing: str
    est_cost: Optional[float] = None
    vendor_name: Optional[str] = None
    hours: Optional[float] = None
    lead_time_days: Optional[int] = None
    lead_time_unit: str = "calendar_days"
    notes: Optional[str] = None
    labour_position: Optional[str] = None
    machine_class_id: Optional[int] = None
    # The class the line is priced on: its own, or the change's
    # (machine_class_from_change) which it follows when the change's moves.
    machine_class: Optional[str] = None
    machine_class_used_id: Optional[int] = None
    machine_class_from_change: bool = False
    trials: Optional[int] = None
    machine_id: Optional[int] = None
    machine_name: Optional[str] = None
    machine_rate_own: bool = False
    # The rate the line is priced with (spec §15 phase 2): the snapshot taken
    # when it was costed. rate None + rate_missing = "No rate in the cost
    # sheet" (not counted, never 0). rate_label reads e.g. "Cost sheet v2,
    # Tool Engineer, Engineer, 21.50 USD/h". line_value = hours (trials) x
    # rate, in rate_currency; currency is the money currency of est_cost and
    # the offers (the costing plant's).
    rate: Optional[float] = None
    rate_currency: Optional[str] = None
    currency: Optional[str] = None
    rate_unit: Optional[str] = None
    rate_source: Optional[str] = None
    cost_sheet_version_id: Optional[int] = None
    cost_sheet_version: Optional[int] = None
    rate_match: Optional[str] = None
    rate_on: Optional[date] = None
    rate_label: Optional[str] = None
    rate_missing: bool = False
    rate_missing_reason: Optional[str] = None
    rate_is_snapshot: bool = False
    line_value: Optional[float] = None
    created_by: int
    created_at: datetime
    updated_at: datetime
    # What the position is worth however it is priced: the favorite offer
    # (plus shipping when stated separately) for a quoted external position,
    # the estimate otherwise. None means nobody has said yet.
    effective_cost: Optional[float] = None
    # The summed partial quotes on a quoted line (0 when none).
    parts_cost: float = 0.0
    # The favorite offer's dates when a supplier set them, this position's
    # own otherwise — in its own unit, and converted for the roll-ups.
    effective_lead_time_days: Optional[int] = None
    effective_lead_time_unit: str = "calendar_days"
    effective_lead_time_calendar_days: Optional[int] = None
    favorite_offer_id: Optional[int] = None
    # Both sides of the vendor decision, flattened onto the position so a
    # wrap-up line reads "recommended: A · chosen: B (reason)" with no joins.
    recommended_vendor: Optional[str] = None
    recommended_cost: Optional[float] = None
    chosen_offer_id: Optional[int] = None
    chosen_vendor: Optional[str] = None
    chosen_cost: Optional[float] = None
    chosen_reason: Optional[str] = None
    chosen_by_name: Optional[str] = None
    chosen_at: Optional[datetime] = None
    # True when Sales went against the department's recommendation.
    choice_diverges: bool = False
    # The money in the OFFER: the chosen vendor's price once Sales has
    # decided, effective_cost (the department's own number) until then. The
    # summation totals this one.
    quoted_cost: Optional[float] = None
    offers: List[CostingOfferResponse] = []


class GateDecisionIn(BaseModel):
    decision: str  # yes | no | na
    remark: Optional[str] = None


class GateResponse(BaseModel):
    gate_key: str
    decision: Optional[str] = None  # None: nobody has decided it yet
    decided_by: Optional[int] = None
    decided_by_name: Optional[str] = None
    decided_at: Optional[datetime] = None
    remark: Optional[str] = None

    class Config:
        from_attributes = True


class MeetingParticipant(BaseModel):
    name: str
    user_id: Optional[int] = None
    # From the contact picker: used to find the PLM2 user behind a name
    # when user_id is missing (the backend resolves and stores user_id).
    username: Optional[str] = None
    email: Optional[str] = None


class MeetingCreate(BaseModel):
    meeting_date: Optional[NaiveUtcDatetime] = None
    channel: str = "meeting"  # meeting | chat | email
    participants: List[MeetingParticipant] = []
    notes: Optional[str] = None
    selected_department_ids: List[int] = []
    # {department_id: "R"|"A"|"S"|"C"} — the room's call. When given, it is
    # authoritative and selected_department_ids follows its keys.
    department_rasic: Optional[Dict[int, str]] = None
    # The room re-confirms the cost carrier: customer | internal (§16).
    # Proceed is refused until it is set.
    cost_carrier: Optional[str] = None


class MeetingUpdate(BaseModel):
    meeting_date: Optional[NaiveUtcDatetime] = None
    participants: Optional[List[MeetingParticipant]] = None
    notes: Optional[str] = None
    selected_department_ids: Optional[List[int]] = None
    department_rasic: Optional[Dict[int, str]] = None
    cost_carrier: Optional[str] = None


class NegotiationCreate(BaseModel):
    channel: str = "call"  # meeting | call | email
    # The round's result — the whole point of the record.
    note: str = Field(min_length=1)
    # The customer's counter, when they named one. Not every round has a
    # number in it.
    counter_price: Optional[float] = Field(default=None, ge=0)
    is_final: bool = False
    # The offer version the round is about; defaults to the latest sent one.
    offer_id: Optional[int] = None


class NegotiationResponse(BaseModel):
    id: int
    change_id: int
    channel: str
    note: str
    counter_price: Optional[float] = None
    is_final: bool = False
    offer_id: Optional[int] = None
    created_by: int
    created_by_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConcernCreate(BaseModel):
    # Phase-split kinds: during scoping the team raises needs_info (a
    # question) or reject_proposal (a cancel vote); during assessment only
    # risks are raisable by hand.
    kind: str = "needs_info"
    note: str = Field(min_length=1)
    # Required while the change is in assessment (the raiser's own
    # department); optional attribution during scoping.
    department_id: Optional[int] = None
    # Required for kind "risk" — see RISK_TYPES / severity 1-3 in models.
    risk_type: Optional[str] = None
    severity: Optional[int] = None
    # Set when the risk is raised from an assessment checklist row.
    checklist_key: Optional[str] = Field(default=None, max_length=120)


class CostLeadTimeIn(BaseModel):
    department_id: int
    lead_time_days: int = Field(ge=0)


class WeightEstimateIn(BaseModel):
    # Grams, strictly positive: a part that weighs nothing is a typo, and the
    # validation delta computed against a zero would be meaningless. null is
    # the erase — the estimate was wrong and there is no replacement yet, which
    # is a different statement from "0 g" and must not be storable as one.
    weight_g: Optional[float] = None

    @field_validator("weight_g")
    @classmethod
    def _positive_or_absent(cls, v):
        if v is not None and v <= 0:
            raise ValueError("Part weight must be greater than zero")
        return v


class BankBuildIn(BaseModel):
    # running_change | planned_scrap (BANK_BUILD_MODES). Validated in the
    # service against the model's tuple so the vocabulary has one home.
    mode: str
    # The plan itself, or the reference to wherever it was built. Optional:
    # the decision is the thing that unblocks Sales, and a scheduler who has
    # decided but not yet written the summary should be able to say so.
    note: Optional[str] = None
    # Mandatory for planned_scrap and refused for running_change — the service
    # states the rule (the customer bears the scrap cost). Strictly positive:
    # a scrap quote of zero is not a quote.
    scrap_quote_price: Optional[float] = None

    @field_validator("scrap_quote_price")
    @classmethod
    def _positive_or_absent(cls, v):
        if v is not None and v <= 0:
            raise ValueError("Scrap quote price must be greater than zero")
        return v


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
    # The asker's department memberships — who is asking matters as much as
    # what is asked, and a bare name says nothing about the hat. Served by the
    # list endpoint; single-concern responses leave it empty and the UI
    # re-fetches the list anyway.
    raised_by_departments: List[str] = []
    raised_at: datetime
    department_id: Optional[int] = None
    # Set on kind "risk" only; null on legacy kinds.
    risk_type: Optional[str] = None
    # Human label of risk_type ("Tolerance stack"), spec §16.
    risk_type_label: Optional[str] = None
    severity: Optional[int] = None
    checklist_key: Optional[str] = None
    raised_by_meeting_id: Optional[int] = None
    answer_note: Optional[str] = None
    answered_at: Optional[datetime] = None
    answered_by: Optional[int] = None
    # The answerer's name, same deal as the asker's — the UI already renders
    # it and fell back to '#id' while nothing served it.
    answered_by_name: Optional[str] = None
    withdrawn_at: Optional[datetime] = None
    withdrawn_by: Optional[int] = None
    # author | pm | department, and its words ("Withdrawn by author",
    # "Settled by Project Management"), spec §16.
    settled_as: Optional[str] = None
    settled_label: Optional[str] = None
    withdrawn_by_name: Optional[str] = None
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
    department_rasic: Optional[Dict[int, str]] = None
    cost_carrier: Optional[str] = None
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
    # Required from 'quoted' on (spec §16).
    reason: Optional[str] = None


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
    # Viewer-relative (GET /deviations): may this caller approve/reject it
    # (4-eyes, engineer/admin, lead-or-admin), and the names to show.
    can_decide: bool = False
    proposed_by_name: Optional[str] = None
    decided_by_name: Optional[str] = None

    class Config:
        from_attributes = True


# --- stage 8: implementation tracking ---------------------------------------

class ImplementationBookingCreate(BaseModel):
    department_id: int
    # Strictly positive: a zero booking says nothing and a negative one is a
    # correction, which is DELETE plus a fresh booking.
    hours: float = Field(gt=0)
    note: Optional[str] = None
    # Optional pricing detail (spec §15 phase 2): the position whose cost
    # sheet rate prices the hours, and machine hours on a machine class.
    labour_position: Optional[str] = Field(default=None, max_length=80)
    machine_class_id: Optional[int] = None
    machine_hours: Optional[float] = Field(default=None, ge=0, lt=1e6)


class ImplementationBookingResponse(BaseModel):
    id: int
    change_id: int
    department_id: int
    hours: float
    note: Optional[str] = None
    labour_position: Optional[str] = None
    machine_class_id: Optional[int] = None
    machine_hours: Optional[float] = None
    # The stored columns. Kept in the payload because "booked" is what the
    # act is called on the shop floor.
    booked_by: int
    booked_at: datetime
    # The same two facts under the naming every other change child uses, plus
    # the author's name so a list renders without a user lookup.
    created_by: int
    created_by_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ImplementationReportCreate(BaseModel):
    department_id: int
    note: str = Field(min_length=1)
    at_risk: bool = False
    # Recommended when at_risk is true, never required: demanding a written
    # justification before a department may raise its hand is how at-risk
    # flags stop being raised.
    risk_note: Optional[str] = None


class ImplementationReportResponse(BaseModel):
    id: int
    change_id: int
    department_id: int
    note: str
    at_risk: bool
    risk_note: Optional[str] = None
    reported_by: int
    reported_by_name: Optional[str] = None
    reported_at: datetime

    class Config:
        from_attributes = True


class ImplementationEscalationCreate(BaseModel):
    # customer | internal (ESCALATION_DIRECTIONS). Validated in the service
    # against the model's tuple so the vocabulary has one home.
    direction: str
    note: str = Field(min_length=1)
    # The flagged report this answers, when there is one.
    report_id: Optional[int] = None


class ImplementationEscalationResolveIn(BaseModel):
    resolution_note: str = Field(min_length=1)


class ImplementationEscalationResponse(BaseModel):
    id: int
    change_id: int
    report_id: Optional[int] = None
    direction: str
    note: str
    created_by: int
    created_by_name: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[int] = None
    resolved_by_name: Optional[str] = None
    resolution_note: Optional[str] = None
    is_open: bool

    class Config:
        from_attributes = True


class ImplementationDepartmentState(BaseModel):
    department_id: int
    department_name: Optional[str] = None
    booked_hours: float
    report_count: int
    last_report_at: Optional[datetime] = None
    at_risk_open: bool
    owes_report: bool


class ImplementationStateResponse(BaseModel):
    change_id: int
    status: str
    cadence_hours: int
    departments: List[ImplementationDepartmentState]
    total_booked_hours: float
    open_escalations: int


# --- stage 9: validation checks ---------------------------------------------

class ValidationCheckIn(BaseModel):
    department_id: int
    # A key from the department's catalog (validation_checklist.items_for);
    # validated in the service so the vocabulary has one home.
    check_key: str
    # passed | failed. 'open' is not writable: a check is un-answered only
    # before anybody touched it, and a wrong answer is corrected by posting
    # the right one.
    status: str
    # Seconds for cycle_time, grams for weight. Required to PASS a check the
    # catalog marks as a measurement — refused in the service with the unit in
    # the message.
    value: Optional[float] = None
    note: Optional[str] = None


class WeightDeltaAckIn(BaseModel):
    # Optional: the act is the decision ("re-quoted", "absorbed"), and forcing
    # a sentence out of Sales before they may clear the task is how the task
    # gets ignored instead of cleared.
    note: Optional[str] = None


class ValidationCheckState(BaseModel):
    check_key: str
    label_de: str
    label_en: str
    expects_value: bool
    unit: Optional[str] = None
    status: str
    # Seconds for cycle_time, grams for weight — stored exactly as recorded.
    value: Optional[float] = None
    note: Optional[str] = None
    checked_by: Optional[int] = None
    checked_by_name: Optional[str] = None
    checked_at: Optional[datetime] = None
    # cycle_time only: the seconds per part this department's costing assumed
    # the change would add. A delta, not an absolute cycle time — the costing
    # never stated one.
    planned_delta_seconds: Optional[float] = None
    # Where planned_delta_seconds comes from: "change_lifecycle_total" (the
    # Tool Engineer's row: every department's lifecycle minutes summed) or
    # "department_lifecycle" (that department's own lines). None with no number.
    planned_delta_source: Optional[str] = None
    # weight only: what the quote was built on, and the gap to the weighed part.
    estimated_part_weight_g: Optional[float] = None
    delta_g: Optional[float] = None
    # An answered row an older catalog seeded; shown, never counted.
    retired: bool = False


class ValidationDepartmentState(BaseModel):
    department_id: int
    department_name: Optional[str] = None
    checks: List[ValidationCheckState]
    open_count: int
    failed_count: int
    all_passed: bool


class ValidationStateResponse(BaseModel):
    change_id: int
    status: str
    departments: List[ValidationDepartmentState]
    check_count: int
    open_count: int
    failed_count: int
    all_passed: bool
    # The costing's lifecycle assumption for the whole change, in the unit the
    # costing states it. Measured cycle times are recorded in SECONDS; both
    # units are named so a bare number is never ambiguous.
    planned_cycle_time_min_per_part: Optional[float] = None
    # The weight story, flat: quoted, weighed, and the delta between them —
    # always computed backend-side so two screens cannot disagree about it.
    weight_estimate_g: Optional[float] = None
    validated_weight_g: Optional[float] = None
    weight_delta_g: Optional[float] = None
    weight_ack_at: Optional[datetime] = None
    weight_ack_by: Optional[int] = None
    weight_ack_by_name: Optional[str] = None
    weight_ack_note: Optional[str] = None
    weight_quote_update_open: bool = False
    # Exactly the string the -> released guard would refuse with, or null. The
    # badge and the block read the same sentence.
    release_blocker: Optional[str] = None


class ValidationCheckResponse(BaseModel):
    id: int
    change_id: int
    department_id: int
    check_key: str
    status: str
    value: Optional[float] = None
    note: Optional[str] = None
    checked_by: Optional[int] = None
    checked_at: Optional[datetime] = None

    class Config:
        from_attributes = True
