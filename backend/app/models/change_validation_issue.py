"""Validation issues: the failure branch of stage 9 (spec §12, §12a).

A failed validation does not just bounce the change back. Each failure is an
issue with a light 8D shape (containment, root cause, a decided route to the
fix, fix actions, re-validation) and a customer side (inform, decision,
concession). Release is refused while any issue is open.

Three tables:
  change_validation_issues            the issue itself (one row per VI-n)
  change_validation_issue_actions     its fix actions
  change_validation_issue_escalations its escalation history (level 1..3)

Evidence and customer mails are ordinary change attachments filed into the
issue through change_attachments.validation_issue_id (migration 090).
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text,
    UniqueConstraint, false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

ISSUE_CATEGORIES = ("tool", "equipment_assembly", "dimensional",
                    "material_weight", "cycle_time", "cosmetic", "packaging",
                    "documentation", "other")
ISSUE_SEVERITIES = (1, 2, 3)
ISSUE_ROUTES = ("internal_rework", "supplier_rework", "design_change",
                "customer_concession", "follow_up_change")
# The routes that fix the part in this change (loop back, recovery group).
FIX_ROUTES = ("internal_rework", "supplier_rework", "design_change")
CUSTOMER_DECISIONS = ("accept_deviation", "require_fix", "new_timing", "pending")
COST_BEARERS = ("internal", "supplier", "customer")
ISSUE_STATUSES = ("open", "contained", "route_decided", "fixing",
                  "revalidation", "closed", "accepted", "transferred")
# An issue in one of these no longer holds the release.
ISSUE_DONE_STATUSES = ("closed", "accepted", "transferred")
ACTION_STATUSES = ("open", "done")


class ValidationIssue(Base):
    """One validation failure on one change (shown "VI-<number>")."""
    __tablename__ = "change_validation_issues"
    __table_args__ = (
        UniqueConstraint("change_id", "number", name="uq_validation_issue_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(30), default="other")
    severity: Mapped[int] = mapped_column(Integer, default=2)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_departments.id"), nullable=True)
    check_id: Mapped[int | None] = mapped_column(
        ForeignKey("validation_checks.id"), nullable=True, index=True)
    affected_part_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    affected_tool_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(Text)

    containment: Mapped[str | None] = mapped_column(Text, nullable=True)
    contained_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    contained_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    root_cause_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)

    route: Mapped[str | None] = mapped_column(String(30), nullable=True)
    route_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    route_decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    route_decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    chargeback: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false())

    customer_inform: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false())
    customer_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    customer_decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    concession_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    # new_timing: the date the customer agreed (it moved release_due_date)
    new_timing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # the one customer escalation that carries this issue's recovery slips
    customer_escalation_id: Mapped[int | None] = mapped_column(
        ForeignKey("implementation_escalations.id"), nullable=True)

    # asdecimal=False like every other money column of the change module.
    extra_cost: Mapped[float | None] = mapped_column(
        Numeric(12, 2, asdecimal=False), nullable=True)
    cost_bearer: Mapped[str | None] = mapped_column(String(12), nullable=True)
    # customer bearer: Sales quoted the fix to the customer (P&L revenue)
    fix_quoted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fix_quoted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)

    follow_up_change_id: Mapped[int | None] = mapped_column(
        ForeignKey("change_requests.id"), nullable=True)

    # Recovery group in the detailed plan (§12a). Plain ids, no FK: a plan
    # block may be deleted by a plan editor, the issue then shows no group.
    recovery_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revalidation_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Current escalation level (history in change_validation_issue_escalations).
    escalation_level: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1")

    status: Mapped[str] = mapped_column(
        String(20), default="open", server_default="open")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    closure_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def is_open(self) -> bool:
        return self.status not in ISSUE_DONE_STATUSES

    @property
    def ref(self) -> str:
        return f"VI-{self.number}"


class ValidationIssueAction(Base):
    """One fix action of an issue."""
    __tablename__ = "change_validation_issue_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("change_validation_issues.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_departments.id"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(10), default="open", server_default="open")
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    done_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    # the recovery block this action became in the detailed plan (no FK)
    plan_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ValidationIssueEscalation(Base):
    """One escalation level change of an issue (history, newest last)."""
    __tablename__ = "change_validation_issue_escalations"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("change_validation_issues.id"), index=True)
    level: Mapped[int] = mapped_column(Integer)
    # machine code of the trigger: raised, severity, action_overdue,
    # plan_slip, no_route, release_deadline, unacknowledged, require_fix,
    # manual, deescalate
    trigger: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    notified: Mapped[str | None] = mapped_column(Text, nullable=True)
    # null when the sweep raised it
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    acknowledged_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
