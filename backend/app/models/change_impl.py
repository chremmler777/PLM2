"""Stage 8 — implementation tracking: booked time, progress reports, escalations.

Three small tables that together answer the two questions a change in
'in_implementation' cannot otherwise answer: what is it costing us, and is it
going to be late.

The time booking is hours only. What an hour is worth is the department's rate
at the plant (DepartmentRate), read at the moment the actuals P&L is drawn —
copying a euro amount onto the booking would let the actuals disagree with the
costing they exist to be compared against.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Numeric, String, Text,
)
from sqlalchemy import false as sa_false
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

# Where a flagged risk goes. 'customer' means the customer has to be told —
# the timeline or the scope they agreed to has moved. 'internal' means we
# absorb it and re-plan. Sales makes the call either way, because Sales owns
# the customer relationship; that is a rule of the house, not a preference.
ESCALATION_DIRECTIONS = ("customer", "internal")

# "At least twice a week" as a number the code can compare against. 84 hours is
# three and a half days: the gap between a Monday report and a Thursday one,
# with the slack that keeps a Friday-afternoon report from turning into a
# Monday-morning task. A department that reports Monday and Thursday never
# trips it; one that reports only Monday does, on Thursday evening.
REPORT_CADENCE_HOURS = 84


class ImplementationBooking(Base):
    """Time one department booked against a change during implementation."""
    __tablename__ = "implementation_bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), index=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("wf_departments.id"), index=True)

    # asdecimal=False for the same reason CostingPosition gives: every consumer
    # (the summation, the P&L snapshot, JSON) is float math, and mixing Decimal
    # into it buys nothing but TypeErrors.
    hours: Mapped[float] = mapped_column(Numeric(8, 2, asdecimal=False))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    booked_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    booked_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)


class ImplementationReport(Base):
    """One department's progress report, with the at-risk flag on it.

    risk_note is nullable even when at_risk is true. Requiring a written
    justification before a department may say "this is going sideways" is how
    at-risk flags stop being raised, and a flag with no note still tells Sales
    to go and ask. The API recommends it; nothing gates on it.
    """
    __tablename__ = "implementation_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), index=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("wf_departments.id"), index=True)

    note: Mapped[str] = mapped_column(Text)
    at_risk: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false())
    risk_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    reported_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reported_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)


class ImplementationEscalation(Base):
    """Sales' answer to a flagged risk: out to the customer, or in to us.

    report_id is the flagged report being answered, and is nullable — an
    escalation can start from a corridor conversation, and inventing a report
    to hang it on would put words in a department's mouth.
    """
    __tablename__ = "implementation_escalations"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), index=True)
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("implementation_reports.id"), nullable=True, index=True)

    direction: Mapped[str] = mapped_column(String(10))
    note: Mapped[str] = mapped_column(Text)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None
