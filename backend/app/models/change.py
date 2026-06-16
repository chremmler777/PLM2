"""Change Management models - the spine of the engineering change process.

A single ChangeRequest flows through one flexible, audited lifecycle. Impacted
controlled items, per-discipline assessments, informal attachments (the PPT-only
start), and a hash-chained changelog hang off it. On approval the change spawns
ECN PartRevisions on each impacted part; on release those become active.
"""
from datetime import datetime

from sqlalchemy import String, Text, DateTime, Float, Integer, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

CHANGE_TYPES = ("physical_part", "tooling", "document_spec", "process_im", "packaging")
CHANGE_PRIORITIES = ("low", "medium", "high", "critical")
CHANGE_STATUSES = (
    "captured", "in_assessment", "costing", "quoted", "approved",
    "in_implementation", "in_validation", "released", "closed",
    "on_hold", "rejected", "cancelled",
)
ASSESSMENT_VERDICTS = ("pending", "feasible", "feasible_with_conditions", "not_feasible")
CUSTOMER_RESPONSES = ("pending", "accepted", "declined", "negotiating")
SIGN_OFF_ROLES = ("pm", "quality")
TERMINAL_STATUSES = ("released", "closed", "rejected", "cancelled")

BLOCKING_LETTERS = ("R", "A")
TASK_LETTERS = ("R", "A", "S", "C")
DEVIATION_STATUSES = ("none", "pending_approval", "approved")


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

    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project: Mapped["Project"] = relationship(foreign_keys=[project_id])
    lead: Mapped["User | None"] = relationship(foreign_keys=[lead_id])
    raised_by_user: Mapped["User"] = relationship(foreign_keys=[raised_by])

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


class ChangeImpactedItem(Base):
    """A controlled item (article/tool/assembly_equipment/eoat/gauge) affected by a change."""
    __tablename__ = "change_impacted_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), index=True)

    impact_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    eng_level_before: Mapped[str | None] = mapped_column(String(50), nullable=True)
    eng_level_after: Mapped[str | None] = mapped_column(String(50), nullable=True)
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

    stage_order: Mapped[int] = mapped_column(Integer, default=1)
    rasic_letter: Mapped[str] = mapped_column(String(1), default="R")
    status: Mapped[str] = mapped_column(String(20), default="active")  # pending|active|submitted|waived

    responsible_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    change: Mapped["ChangeRequest"] = relationship(back_populates="assessments", foreign_keys=[change_id])
    department: Mapped["Department"] = relationship(foreign_keys=[department_id])


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


# Import related models for relationship resolution
from app.models.entities import Project, User  # noqa: E402
from app.models.part import Part, PartRevision  # noqa: E402
from app.models.workflow import Department  # noqa: E402
