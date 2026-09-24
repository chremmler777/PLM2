"""Stages 4-8 timing: the change's plan as blocks on a calendar.

Two plans per change, same table. The QUOTE plan is Sales' rough timeline
while the offer is written — it answers "how many weeks from order" in front
of the customer. The DETAILED plan is seeded from it after acceptance, every
responsible team confirms it, and "Timing validated" freezes a baseline on
each block. From then on a date only moves as a deviation with a reason,
because the baseline is what the customer was told.

Dates are calendar dates, not timestamps: a block starts on a day, and a
timezone shifting it to the day before would move a promise. Durations are
calendar days and end_date is exclusive (start + duration), so a successor may
start on its predecessor's end_date.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, Text,
)
from sqlalchemy import false as sa_false
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

PLAN_KINDS = ("quote", "detailed")
TASK_KINDS = ("work", "supplier", "downtime", "bank_build", "sampling",
              "validation", "customer", "buffer", "milestone")
FEEDBACK_VERDICTS = ("confirmed", "concern")
DEVIATION_STATUSES = ("open", "locked", "escalated")


class ChangePlanTask(Base):
    """One block on a change's quote or detailed plan."""
    __tablename__ = "change_plan_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), index=True)
    plan: Mapped[str] = mapped_column(String(10))

    name: Mapped[str] = mapped_column(String(200))
    # The swimlane: a department name, 'Customer' or 'Supplier'. Free text on
    # purpose — the customer is not a department and still owns blocks.
    lane: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # The owner department, which is who may report progress on the block.
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_departments.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="work")
    # A Sales proposal ("we could build the bank in parallel") rather than a
    # commitment. Ideas are drawn dashed, left out of the critical path and
    # the exports, and must be resolved before timing is validated.
    is_idea: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false())

    start_date: Mapped[date] = mapped_column(Date)
    duration_days: Mapped[int] = mapped_column(Integer, default=0)
    # Finish-to-start links to other tasks of the SAME plan, by id.
    predecessors: Mapped[list] = mapped_column(JSON, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    progress_pct: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0")
    actual_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_finish: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Frozen by "Timing validated". baseline_finish is exclusive, exactly
    # like end_date, so the two can be compared without an off-by-one.
    baseline_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    baseline_finish: Mapped[date | None] = mapped_column(Date, nullable=True)

    # The costing position the block was seeded from. No FK: a position
    # deleted later must not take the plan block with it.
    source_position_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def end_date(self) -> date:
        """Exclusive end: the first day a successor may start."""
        return self.start_date + timedelta(days=int(self.duration_days or 0))


class ChangePlanFeedback(Base):
    """A responsible team's answer to the detailed plan at one revision.

    Append-only: the latest row per department counts, and it goes stale the
    moment the plan changes under it (plan_revision < change.plan_revision).
    A confirmation of a plan that has since moved confirms nothing.
    """
    __tablename__ = "change_plan_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"))
    plan_revision: Mapped[int] = mapped_column(Integer, default=0)
    verdict: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChangePlanDeviation(Base):
    """A date moved on a baselined block, with the reason and its fate.

    slip_days is measured against the block's own baseline end (how late is
    THIS block against what we promised), finish_impact_days against the plan
    finish before the edit (what the move does to the whole change). Both,
    because a block can slip a week inside its slack and move nothing.
    """
    __tablename__ = "change_plan_deviations"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("change_plan_tasks.id"))
    old_start: Mapped[date] = mapped_column(Date)
    old_end: Mapped[date] = mapped_column(Date)
    new_start: Mapped[date] = mapped_column(Date)
    new_end: Mapped[date] = mapped_column(Date)
    slip_days: Mapped[int] = mapped_column(Integer, default=0)
    finish_impact_days: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(15), default="open", server_default="open")
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalation_id: Mapped[int | None] = mapped_column(
        ForeignKey("implementation_escalations.id"), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
