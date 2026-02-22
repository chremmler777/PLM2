"""Workflow system models - templates, instances, and tasks."""
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.database import Base


# ============================================================================
# NEW: Stage-based workflow template design with RASIC matrix
# ============================================================================

class Department(Base):
    """Workflow departments (roles) - system configurable."""
    __tablename__ = "wf_departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)  # Developer, Tool Engineer, APQP, etc.
    flow_type: Mapped[str] = mapped_column(String(20))  # action | info
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WfTemplate(Base):
    """Workflow template - stage-based with RASIC matrix."""
    __tablename__ = "wf_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    stages: Mapped[list["WfStage"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="WfStage.stage_order"
    )
    history: Mapped[list["WfTemplateHistory"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan"
    )
    created_by_user: Mapped["User"] = relationship(foreign_keys=[created_by])
    updated_by_user: Mapped["User | None"] = relationship(foreign_keys=[updated_by])


class WfStage(Base):
    """Sequential stage in a workflow template."""
    __tablename__ = "wf_stages"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("wf_templates.id"))
    stage_order: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)  # Optional stage label

    template: Mapped["WfTemplate"] = relationship(back_populates="stages")
    steps: Mapped[list["WfStep"]] = relationship(
        back_populates="stage",
        cascade="all, delete-orphan",
        order_by="WfStep.position_in_stage"
    )


class WfStep(Base):
    """Step within a stage (parallel if multiple in same stage)."""
    __tablename__ = "wf_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("wf_stages.id"))
    step_name: Mapped[str] = mapped_column(String(100))
    position_in_stage: Mapped[int] = mapped_column(Integer)  # For ordering within parallel group

    stage: Mapped["WfStage"] = relationship(back_populates="steps")
    rasic_assignments: Mapped[list["WfStepRasic"]] = relationship(
        back_populates="step",
        cascade="all, delete-orphan"
    )


class WfStepRasic(Base):
    """RASIC assignment for a department in a step."""
    __tablename__ = "wf_step_rasic"

    id: Mapped[int] = mapped_column(primary_key=True)
    step_id: Mapped[int] = mapped_column(ForeignKey("wf_steps.id"))
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"))
    rasic_letter: Mapped[str] = mapped_column(String(1))  # R|A|S|I|C

    step: Mapped["WfStep"] = relationship(back_populates="rasic_assignments")
    department: Mapped["Department"] = relationship()


class WfTemplateHistory(Base):
    """Version history of workflow templates."""
    __tablename__ = "wf_template_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("wf_templates.id"))
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)  # Full template structure snapshot
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    template: Mapped["WfTemplate"] = relationship(back_populates="history")
    changed_by_user: Mapped["User"] = relationship(foreign_keys=[changed_by])


# ============================================================================
# LEGACY: Old workflow models (kept for compatibility, not used in new design)
# ============================================================================

class WorkflowTemplate(Base):
    """Reusable workflow template for article reviews."""
    __tablename__ = "workflow_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    article_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    steps: Mapped[list["WorkflowStep"]] = relationship(
        back_populates="template",
        order_by="WorkflowStep.order",
        cascade="all, delete-orphan"
    )
    organization: Mapped["Organization | None"] = relationship(foreign_keys=[organization_id])


class WorkflowStep(Base):
    """Step within a workflow template."""
    __tablename__ = "workflow_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("workflow_templates.id"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    order: Mapped[int] = mapped_column(Integer)
    parallel_group: Mapped[int | None] = mapped_column(Integer, nullable=True)
    role_required: Mapped[str] = mapped_column(String(50))
    default_duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)

    template: Mapped["WorkflowTemplate"] = relationship(back_populates="steps")


class WorkflowInstance(Base):
    """Running workflow instance for a specific article revision."""
    __tablename__ = "workflow_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("workflow_templates.id"))
    article_revision_id: Mapped[int] = mapped_column(ForeignKey("article_revisions.id"))
    status: Mapped[str] = mapped_column(String(30))  # pending, in_progress, completed, canceled
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)  # approved, rejected
    outcome_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    template: Mapped["WorkflowTemplate"] = relationship()
    article_revision: Mapped["ArticleRevision"] = relationship(
        back_populates="workflow_instances",
        foreign_keys=[article_revision_id]
    )
    started_by_user: Mapped["User"] = relationship(foreign_keys=[started_by])
    tasks: Mapped[list["WorkflowTask"]] = relationship(
        back_populates="instance",
        cascade="all, delete-orphan"
    )


class WorkflowTask(Base):
    """Task assigned to a user or role in a workflow."""
    __tablename__ = "workflow_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("workflow_instances.id"))
    step_id: Mapped[int] = mapped_column(ForeignKey("workflow_steps.id"))
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_role: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30))  # pending, active, in_progress, completed, approved, rejected, skipped
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(30), nullable=True)  # approved, rejected
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Escalation tracking
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)  # 0=normal, 1=warning, 2=overdue, 3=critical
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    escalated_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    instance: Mapped["WorkflowInstance"] = relationship(back_populates="tasks")
    step: Mapped["WorkflowStep"] = relationship()
    assigned_user: Mapped["User | None"] = relationship(foreign_keys=[assigned_to])
    completed_by_user: Mapped["User | None"] = relationship(foreign_keys=[completed_by])
    escalated_to_user: Mapped["User | None"] = relationship(foreign_keys=[escalated_to])


# Forward references for type hints
from app.models.entities import Organization, User
from app.models.article import ArticleRevision

__all__ = [
    "Department",
    "WfTemplate",
    "WfStage",
    "WfStep",
    "WfStepRasic",
    "WfTemplateHistory",
    "WorkflowTemplate",
    "WorkflowStep",
    "WorkflowInstance",
    "WorkflowTask",
]
