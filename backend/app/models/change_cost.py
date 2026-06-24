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
