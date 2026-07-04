"""Cost-assessment models digitizing the GB-CM-0001 department tabs:
per-department×plant rates, the seeded activity catalog, per-line costs, and
the three D1 gates."""
from datetime import date, datetime

from sqlalchemy import String, Text, DateTime, Date, Float, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

COST_KINDS = ("one_time", "lifecycle")
GATE_KEYS = ("feasibility", "budget", "release")
GATE_DECISIONS = ("yes", "no", "na")
# Which transition each gate guards (additive; see Global Constraints).
GATE_TARGET_STATUS = {"feasibility": "in_assessment", "budget": "costing", "release": "in_implementation"}


class DepartmentRate(Base):
    """Hourly rate for a department at a plant (from the Std.-Sätze sheet)."""
    __tablename__ = "department_rate"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"), index=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), index=True)
    hourly_rate: Mapped[float] = mapped_column(Float)
    min_factor: Mapped[float] = mapped_column(Float, default=1.0)
    effective_from: Mapped[date] = mapped_column(Date, default=date.today)


class AssessmentActivity(Base):
    """A predefined cost-line activity offered to a department (its selection list)."""
    __tablename__ = "assessment_activity"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AssessmentCostLine(Base):
    """One cost line on a department's assessment tab (per plant, one-time or lifecycle)."""
    __tablename__ = "assessment_cost_line"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("change_assessments.id"), index=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), index=True)
    activity_id: Mapped[int | None] = mapped_column(ForeignKey("assessment_activity.id"), nullable=True)
    activity_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cost_kind: Mapped[str] = mapped_column(String(20), default="one_time")
    demand_hours: Mapped[float] = mapped_column(Float, default=0.0)
    rate_snapshot: Mapped[float] = mapped_column(Float, default=0.0)
    internal_cost: Mapped[float] = mapped_column(Float, default=0.0)
    external_cost: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessment: Mapped["ChangeAssessment"] = relationship(back_populates="cost_lines")


class ChangeGate(Base):
    """One of the three D1 'Final assessment' gates on a change."""
    __tablename__ = "change_gate"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)
    gate_key: Mapped[str] = mapped_column(String(20))  # feasibility|budget|release
    decision: Mapped[str] = mapped_column(String(10), default="na")  # yes|no|na
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    change: Mapped["ChangeRequest"] = relationship(back_populates="gates")
