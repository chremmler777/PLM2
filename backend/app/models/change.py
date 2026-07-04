"""Change Management models - the spine of the engineering change process.

A single ChangeRequest flows through one flexible, audited lifecycle. Impacted
controlled items, per-discipline assessments, informal attachments (the PPT-only
start), and a hash-chained changelog hang off it. On approval the change spawns
ECN PartRevisions on each impacted part; on release those become active.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, Float, Integer, ForeignKey, JSON, Boolean, Table, Column
from sqlalchemy import false as sa_false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

change_affected_plants = Table(
    "change_affected_plants", Base.metadata,
    Column("change_id", ForeignKey("change_requests.id"), primary_key=True),
    Column("plant_id", ForeignKey("plants.id"), primary_key=True),
)

CHANGE_TYPES = ("physical_part", "tooling", "document_spec", "process_im", "packaging")
CHANGE_PRIORITIES = ("low", "medium", "high", "critical")
CHANGE_STATUSES = (
    "captured", "scoping", "in_assessment", "costing", "quoted", "approved",
    "in_implementation", "in_validation", "released", "closed",
    "on_hold", "rejected", "cancelled",
)
ASSESSMENT_VERDICTS = ("pending", "feasible", "feasible_with_conditions", "not_feasible")
CUSTOMER_RESPONSES = ("pending", "accepted", "declined", "negotiating")
SIGN_OFF_ROLES = ("pm", "quality")
TERMINAL_STATUSES = ("released", "closed", "rejected", "cancelled")

BLOCKING_LETTERS = ("R", "A")
TASK_LETTERS = ("R", "A", "S", "C")
ASSESSMENT_STATUSES = ("pending", "active", "submitted", "waived")

# Maps a WfInstanceTask.status onto the assessment status vocabulary, so a
# task-linked R/A assessment reads its execution state through from the task.
_TASK_TO_ASSESSMENT_STATUS = {
    "pending": "pending", "active": "active", "approved": "submitted",
    "waived": "waived", "rejected": "submitted", "noted": "active",
}
ROUTING_DEVIATION_STATUSES = ("none", "pending_approval", "approved")
IMPLEMENTATION_MODES = ("integrated", "separational")
MEETING_DECISIONS = ("proceed", "reject", "needs_info")


class ChangeRequest(Base):
    """One engineering change, flowing through the lifecycle state machine."""
    __tablename__ = "change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)  # CR-2026-0042
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)

    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    change_type: Mapped[str] = mapped_column(String(30), default="physical_part")
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    data_classification: Mapped[str] = mapped_column(String(20), default="confidential")

    # D1 master fields
    issuer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_series: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    cm_internal: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    cm_external: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    implementation_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_relevant: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    car_line: Mapped[str | None] = mapped_column(String(120), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="captured", index=True)

    lead_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    raised_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    raised_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Decision gate
    customer_response: Mapped[str] = mapped_column(String(20), default="pending")
    customer_response_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    customer_response_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    pm_signed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    pm_signed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    quality_signed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    quality_signed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Commercial stubs (sub-project #3)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    quoted_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Timing stub (sub-project #7)
    timing_milestone_id: Mapped[int | None] = mapped_column(ForeignKey("project_milestones.id"), nullable=True)

    # Sales-settable deadline (sub-project #9)
    required_by_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    required_by_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_by_set_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    required_by_set_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Internal branch of the costing path split: PM approves the summation
    # total for non-customer-relevant changes (no quote step). Amount is a
    # snapshot of the summation grand total at approval time (P&L hook).
    internal_approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    internal_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    internal_approved_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    internal_approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Task 18: Engineering (R&D) owns the affected-items decision. Set together
    # by POST /impact/confirm; cleared together whenever the impacted-item set
    # changes afterwards (re-confirmation required). in_implementation's soft
    # guard reads impact_confirmed_at.
    impact_confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    impact_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project: Mapped["Project"] = relationship(foreign_keys=[project_id])
    lead: Mapped["User | None"] = relationship(
        foreign_keys=[lead_id], lazy="selectin")
    raised_by_user: Mapped["User"] = relationship(foreign_keys=[raised_by])
    impact_confirmed_by_user: Mapped["User | None"] = relationship(
        foreign_keys=[impact_confirmed_by], lazy="selectin")

    @property
    def lead_name(self) -> Optional[str]:
        return self.lead.full_name if self.lead is not None else None

    @property
    def impact_confirmed_by_name(self) -> Optional[str]:
        return self.impact_confirmed_by_user.full_name if self.impact_confirmed_by_user is not None else None

    impacted_items: Mapped[list["ChangeImpactedItem"]] = relationship(
        back_populates="change", cascade="all, delete-orphan", lazy="selectin"
    )
    assessments: Mapped[list["ChangeAssessment"]] = relationship(
        back_populates="change", cascade="all, delete-orphan", lazy="selectin"
    )
    attachments: Mapped[list["ChangeAttachment"]] = relationship(
        back_populates="change", cascade="all, delete-orphan", lazy="selectin"
    )
    changelog_entries: Mapped[list["ChangeChangelog"]] = relationship(
        back_populates="change", cascade="all, delete-orphan",
        order_by="ChangeChangelog.performed_at, ChangeChangelog.id",
    )
    routing: Mapped["ChangeRouting | None"] = relationship(
        back_populates="change", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    gates: Mapped[list["ChangeGate"]] = relationship(
        back_populates="change", cascade="all, delete-orphan", lazy="selectin",
    )
    transition_deviations: Mapped[list["ChangeTransitionDeviation"]] = relationship(
        back_populates="change", cascade="all, delete-orphan", lazy="selectin",
    )
    affected_plants: Mapped[list["Plant"]] = relationship(
        secondary=change_affected_plants, lazy="selectin",
    )
    meetings: Mapped[list["ChangeMeeting"]] = relationship(
        back_populates="change", cascade="all, delete-orphan", lazy="selectin",
        order_by="ChangeMeeting.id",
    )


class ChangeImpactedItem(Base):
    """A controlled item (article/tool/assembly_equipment/eoat/gauge) affected by a change."""
    __tablename__ = "change_impacted_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), index=True)

    impact_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    eng_level_before: Mapped[str | None] = mapped_column(String(50), nullable=True)
    eng_level_after: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_lead: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    resulting_revision_id: Mapped[int | None] = mapped_column(ForeignKey("part_revisions.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))

    change: Mapped["ChangeRequest"] = relationship(back_populates="impacted_items", foreign_keys=[change_id])
    part: Mapped["Part"] = relationship(foreign_keys=[part_id])
    resulting_revision: Mapped["PartRevision | None"] = relationship(foreign_keys=[resulting_revision_id])


class ChangeAssessment(Base):
    """A feasibility verdict from one impacted discipline."""
    __tablename__ = "change_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"), index=True)

    verdict: Mapped[str] = mapped_column(String(30), default="pending")
    cost_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    lead_time_impact_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    producibility: Mapped[str] = mapped_column(String(10), default="na", server_default="na")  # yes|no|na
    contact_person: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approval_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle_cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Time the assessor spent on the feasibility check itself (effort tracking).
    effort_hours: Mapped[float | None] = mapped_column(Float, nullable=True)

    stage_order: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    rasic_letter: Mapped[str] = mapped_column(String(1), default="R", server_default="R")
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")  # pending|active|submitted|waived

    responsible_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Phase C: named ownership + due dates (owner = accountable person; distinct
    # from responsible_id, a free-form contact declared at submission)
    owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Phase E: 1:1 link to the workflow task that executes this R/A assignment.
    # When linked, the task is the source of truth for execution state; the
    # read-through properties below expose it without duplicating writes.
    wf_instance_task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("wf_instance_tasks.id"), nullable=True, unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    change: Mapped["ChangeRequest"] = relationship(back_populates="assessments", foreign_keys=[change_id])
    department: Mapped["Department"] = relationship(foreign_keys=[department_id])
    cost_lines: Mapped[list["AssessmentCostLine"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", lazy="selectin",
    )
    owner: Mapped["User | None"] = relationship(
        foreign_keys=[owner_id], lazy="selectin")
    task: Mapped["WfInstanceTask | None"] = relationship(
        "WfInstanceTask", foreign_keys=[wf_instance_task_id], lazy="selectin")

    @property
    def owner_name(self) -> Optional[str]:
        return self.owner.full_name if self.owner is not None else None

    @property
    def overdue(self) -> bool:
        return (self.due_date is not None and self.status == "active"
                and self.due_date < datetime.utcnow())

    # ------------------------------------------------------------------
    # Read-through execution state (Phase E unification)
    # For R/A rows linked to a workflow task, the task is authoritative;
    # S/C and unlinked rows fall back to this assessment's own columns.
    # ------------------------------------------------------------------
    @property
    def effective_status(self) -> str:
        if self.rasic_letter in BLOCKING_LETTERS and self.task is not None:
            return _TASK_TO_ASSESSMENT_STATUS.get(self.task.status, self.status)
        if self.rasic_letter not in BLOCKING_LETTERS:
            if self.submitted_at is not None:
                return "submitted"
            if self.task is not None:      # its stage has started
                return "active"
        return self.status

    @property
    def effective_owner_id(self):
        if self.rasic_letter in BLOCKING_LETTERS and self.task is not None:
            return self.task.owner_id
        return self.owner_id

    @property
    def effective_owner_name(self):
        if self.rasic_letter in BLOCKING_LETTERS and self.task is not None:
            return self.task.owner_name
        return self.owner.full_name if getattr(self, "owner", None) else None

    @property
    def effective_due_date(self):
        if self.rasic_letter in BLOCKING_LETTERS and self.task is not None:
            return self.task.due_date
        return self.due_date

    @property
    def effective_accepted_at(self):
        if self.rasic_letter in BLOCKING_LETTERS and self.task is not None:
            return self.task.accepted_at
        return self.accepted_at

    @property
    def effective_overdue(self) -> bool:
        if self.rasic_letter in BLOCKING_LETTERS and self.task is not None:
            return self.task.overdue
        return self.overdue


class ChangeAttachment(Base):
    """An informal document attached to a change (PPT, PDF, email, sketch)."""
    __tablename__ = "change_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)

    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))

    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    change: Mapped["ChangeRequest"] = relationship(back_populates="attachments", foreign_keys=[change_id])


class ChangeMeeting(Base):
    """A pre-determination (scoping) meeting record. The 'proceed' decision is
    what kicks off assessment; its selected_department_ids scope the stage-1
    fan-out. A change may hold several meetings (needs_info -> follow-up)."""
    __tablename__ = "change_meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)

    meeting_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    participants: Mapped[list] = mapped_column(JSON, default=list)   # [{"name": str, "user_id": int|None}]
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)  # proceed|reject|needs_info
    selected_department_ids: Mapped[list] = mapped_column(JSON, default=list)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    change: Mapped["ChangeRequest"] = relationship(back_populates="meetings", foreign_keys=[change_id])


class ChangeChangelog(Base):
    """Hash-chained audit trail for a change (mirrors RevisionChangelog)."""
    __tablename__ = "change_changelog"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)

    action: Mapped[str] = mapped_column(String(50))
    action_description: Mapped[str] = mapped_column(Text)
    field_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    performed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    performed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    change: Mapped["ChangeRequest"] = relationship(back_populates="changelog_entries", foreign_keys=[change_id])
    performed_by_user: Mapped["User"] = relationship(foreign_keys=[performed_by])


class ChangeRouting(Base):
    """Per-change snapshot of the standard RASIC routing + deviation governance state."""
    __tablename__ = "change_routings"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), unique=True, index=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("wf_templates.id"), nullable=True)
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    standard_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)

    has_deviation: Mapped[bool] = mapped_column(default=False)
    deviation_status: Mapped[str] = mapped_column(String(20), default="none")
    deviation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    deviation_proposed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deviation_approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deviation_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    change: Mapped["ChangeRequest"] = relationship(back_populates="routing", foreign_keys=[change_id])


class ChangeRoutingStandard(Base):
    """Maps a change_type to the standard ECR WfTemplate it routes through."""
    __tablename__ = "change_routing_standards"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_type: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("wf_templates.id"))
    template_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


TRANSITION_DEVIATION_STATUSES = ("pending", "approved", "rejected", "consumed")


class ChangeTransitionDeviation(Base):
    """Formal 4-eyes bypass for a soft-blocked transition (replaces the old
    free-text justification override). Lifecycle: pending -> approved|rejected;
    an approved deviation is consumed by the transition that uses it."""
    __tablename__ = "change_transition_deviations"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)
    to_status: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="pending")
    proposed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    proposed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    change: Mapped["ChangeRequest"] = relationship(back_populates="transition_deviations")


# Import related models for relationship resolution
from app.models.entities import Project, User, Plant  # noqa: E402,F811
from app.models.part import Part, PartRevision  # noqa: E402
from app.models.workflow import Department, WfInstanceTask  # noqa: E402
from app.models.change_cost import AssessmentCostLine, ChangeGate  # noqa: E402
