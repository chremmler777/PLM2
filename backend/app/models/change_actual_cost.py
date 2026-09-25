"""Actual costs of a change that are not booked hours: supplier invoice lines,
scrap that really happened, anything else that left the building as money.

The P&L compares the offer (what we planned when the customer said yes) with
what the change really cost. Booked implementation hours already give the
internal half; this table is the external half. One row per invoice line,
entered by the cost roles or by the department that ordered the work.
"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

ACTUAL_COST_CATEGORIES = ("external", "scrap", "other")


class ChangeActualCost(Base):
    __tablename__ = "change_actual_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), index=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_departments.id"), nullable=True)
    category: Mapped[str] = mapped_column(
        String(12), default="external", server_default="external")
    vendor_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False))
    # The amount's currency (migration 101): the change's costing currency
    # when it was entered, unless the invoice says otherwise. Sums never mix
    # currencies (no FX); a row in another currency is reported beside them.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    cost_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
