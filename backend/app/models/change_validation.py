"""Stage 9 — validation: the checks each implementing department signs off.

One table, one row per (change, department, check). The row is the signature:
who ticked it, when, and — for the checks that are a measurement rather than a
yes/no — the number they measured.

`value` carries its unit in the check key rather than in the column: seconds
for 'cycle_time', grams for 'weight'. The catalog
(app/services/validation_checklist.py) is the single place that says which key
expects a value and in what unit; two typed columns that are NULL for every
other check would be the same fact stored twice.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

# 'open' is the seeded state — the row exists because the catalog says the
# department owes this check, and nobody has answered it yet. 'failed' is a
# real answer, not an absence: it sends the change back to implementation.
VALIDATION_CHECK_STATUSES = ("open", "passed", "failed")
# What a caller may WRITE. Nobody un-answers a check by posting 'open'; a
# wrong answer is corrected by posting the right one, and the changelog keeps
# both.
VALIDATION_WRITE_STATUSES = ("passed", "failed")


class ValidationCheck(Base):
    """One department's answer to one validation check on one change."""
    __tablename__ = "validation_checks"
    __table_args__ = (
        UniqueConstraint("change_id", "department_id", "check_key",
                         name="uq_validation_check"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), index=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("wf_departments.id"), index=True)

    check_key: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(
        String(10), default="open", server_default="open")

    # asdecimal=False for the same reason every other money/quantity column in
    # this module gives: every consumer (the delta math, the P&L, JSON) is
    # float math, and mixing Decimal into it buys nothing but TypeErrors.
    value: Mapped[float | None] = mapped_column(
        Numeric(12, 3, asdecimal=False), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Null while the row is merely seeded: an unanswered check is nobody's
    # statement, and stamping the person who happened to open the page would
    # put a name against a claim they never made.
    checked_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def is_answered(self) -> bool:
        return self.status in VALIDATION_WRITE_STATUSES
