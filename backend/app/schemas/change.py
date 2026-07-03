"""Pydantic schemas for Change Management."""
from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field, model_validator


class ChangeCreate(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=255)
    change_type: str = "physical_part"
    reason: Optional[str] = None
    description: Optional[str] = None
    priority: str = "medium"
    lead_id: Optional[int] = None
    data_classification: str = "confidential"


class ChangeUpdate(BaseModel):
    title: Optional[str] = None
    reason: Optional[str] = None
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


class TransitionRequest(BaseModel):
    to_status: str
    cancellation_reason: Optional[str] = None


class CustomerResponseRequest(BaseModel):
    response: str  # accepted | declined | negotiating


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
    submitted_at: Optional[datetime] = None
    stage_order: int = 1
    rasic_letter: str = "R"
    status: str = "active"
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    accepted_at: Optional[datetime] = None
    due_date: Optional[datetime] = None
    overdue: bool = False

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
                    "responsible_id", "submitted_at", "stage_order",
                    "rasic_letter")},
                "status": data.effective_status,
                "owner_id": data.effective_owner_id,
                "owner_name": data.effective_owner_name,
                "accepted_at": data.effective_accepted_at,
                "due_date": data.effective_due_date,
                "overdue": data.effective_overdue,
            }
        return data

    class Config:
        from_attributes = True


class AssessmentAssignIn(BaseModel):
    user_id: int


class AssessmentDueDateIn(BaseModel):
    due_date: datetime


class AttachmentResponse(BaseModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime

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


class ChangeResponse(BaseModel):
    id: int
    change_number: str
    project_id: int
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


class SummationTotals(BaseModel):
    one_time_internal: float
    one_time_external: float
    lifecycle_internal: float
    lifecycle_external: float
    grand_total: float


class SummationResponse(BaseModel):
    by_plant: List[PlantRollup] = []
    by_department: List[DeptRollup] = []
    totals: SummationTotals


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
