"""Pydantic schemas for workflow templates."""
from datetime import datetime
from pydantic import BaseModel, Field


class DepartmentResponse(BaseModel):
    """Department/role in workflow."""
    id: int
    name: str
    flow_type: str  # action | info
    is_active: bool
    sort_order: int

    class Config:
        from_attributes = True


class WfStepRasicResponse(BaseModel):
    """RASIC assignment for a step."""
    id: int
    step_id: int
    department_id: int
    department: DepartmentResponse
    rasic_letter: str  # R|A|S|I|C

    class Config:
        from_attributes = True


class WfStepResponse(BaseModel):
    """Step within a stage."""
    id: int
    stage_id: int
    step_name: str
    position_in_stage: int
    rasic_assignments: list[WfStepRasicResponse] = []

    class Config:
        from_attributes = True


class WfStageResponse(BaseModel):
    """Sequential stage in workflow."""
    id: int
    template_id: int
    stage_order: int
    name: str | None
    steps: list[WfStepResponse] = []

    class Config:
        from_attributes = True


class WfTemplateResponse(BaseModel):
    """Full workflow template with stages and RASIC."""
    id: int
    name: str
    description: str | None
    version: int
    is_active: bool
    created_at: datetime
    created_by: int
    updated_at: datetime | None
    updated_by: int | None
    stages: list[WfStageResponse] = []

    class Config:
        from_attributes = True


class WfTemplateListResponse(BaseModel):
    """Template summary for list view."""
    id: int
    name: str
    description: str | None
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime | None

    class Config:
        from_attributes = True


# Request schemas for creating/updating
class WfStepRasicCreate(BaseModel):
    """Create/update RASIC assignment."""
    department_id: int
    rasic_letter: str  # R|A|S|I|C


class WfStepCreate(BaseModel):
    """Create/update step."""
    step_name: str
    position_in_stage: int
    rasic_assignments: list[WfStepRasicCreate] = []


class WfStageCreate(BaseModel):
    """Create/update stage."""
    stage_order: int
    name: str | None = None
    steps: list[WfStepCreate] = []


class WfTemplateCreate(BaseModel):
    """Create workflow template."""
    name: str
    description: str | None = None
    stages: list[WfStageCreate] = []


class WfTemplateSave(BaseModel):
    """Save workflow template (bumps version, saves history)."""
    name: str
    description: str | None = None
    stages: list[WfStageCreate] = []
    change_note: str | None = None


# ============================================================================
# Phase 3c: Workflow Instance schemas
# ============================================================================

class StartWorkflowRequest(BaseModel):
    """Start a workflow instance for a revision."""
    template_id: int


class CompleteTaskRequest(BaseModel):
    """Complete an actionable task with a decision."""
    decision: str  # approved | rejected
    notes: str | None = None


class CancelWorkflowRequest(BaseModel):
    """Cancel a running workflow instance."""
    reason: str | None = None


class WfInstanceTaskResponse(BaseModel):
    """Task within a workflow instance."""
    id: int
    instance_id: int
    stage_order: int
    step_id: int
    step_name: str
    department_id: int
    department_name: str
    rasic_letter: str
    status: str
    is_actionable: bool
    completed_by: int | None
    completed_at: datetime | None
    decision: str | None
    notes: str | None

    class Config:
        from_attributes = True


class WfInstanceResponse(BaseModel):
    """Full workflow instance with tasks."""
    id: int
    template_id: int
    template_name: str
    revision_id: int
    status: str
    current_stage_order: int
    started_by: int
    started_at: datetime
    completed_at: datetime | None
    canceled_at: datetime | None
    cancel_reason: str | None
    tasks: list[WfInstanceTaskResponse] = []

    class Config:
        from_attributes = True


class MyTaskResponse(BaseModel):
    """A task from the current user's department perspective."""
    task_id: int
    instance_id: int
    status: str
    is_actionable: bool
    rasic_letter: str
    department_name: str
    step_name: str
    stage_order: int
    stage_name: str | None
    article_id: int
    article_number: str
    article_name: str
    revision_id: int
    revision_label: str
    instance_started_at: datetime
