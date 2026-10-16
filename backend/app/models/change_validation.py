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

from sqlalchemy import (
    DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
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

    # ECR-solid §10 computed checks (migration 136): the limits a measurement
    # is held against, fixed by the first measurement (a retest never moves
    # them: a different spec is a concession, not a retest), and where they
    # come from (drawing, customer spec, process sheet + reference).
    lower_limit: Mapped[float | None] = mapped_column(
        Numeric(12, 3, asdecimal=False), nullable=True)
    upper_limit: Mapped[float | None] = mapped_column(
        Numeric(12, 3, asdecimal=False), nullable=True)
    spec_source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # A5-02 (migration 142): the measurer's own limits make a PASS count
    # only once Quality (never the setter) confirms them; a FAIL counts at
    # once. Quality correcting the limits sets and confirms them.
    limits_set_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    limits_confirmed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    limits_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True)

    @property
    def limits_pending(self) -> bool:
        """A PASS against limits nobody but the setter has confirmed."""
        return (self.status == "passed" and self.lower_limit is not None
                and self.limits_confirmed_at is None)

    @property
    def is_answered(self) -> bool:
        return self.status in VALIDATION_WRITE_STATUSES


# What a retest names as changed since the failure (spec §10).
RETEST_CHANGE_KINDS = ("parameter", "tool", "material", "method")


class ValidationMeasurement(Base):
    """One measurement of a computed check (weight, cycle time, dimensions):
    sample size, the smallest and largest value, and the measuring report or
    device. PASS only if both lie inside the check's limits. A retest adds a
    row and keeps the failed one, with what changed since (spec §10)."""
    __tablename__ = "validation_measurements"

    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int] = mapped_column(
        ForeignKey("validation_checks.id"), index=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), index=True)
    sample_size: Mapped[int] = mapped_column(Integer)
    min_value: Mapped[float] = mapped_column(Numeric(12, 3, asdecimal=False))
    max_value: Mapped[float] = mapped_column(Numeric(12, 3, asdecimal=False))
    measuring_ref: Mapped[str] = mapped_column(String(200))
    # cycle time: the lot the N cycles ran on
    lot_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # a retest: what changed since the failure (RETEST_CHANGE_KINDS) + ref
    what_changed_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    what_changed_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # passed | failed, computed against the limits at the time
    result: Mapped[str] = mapped_column(String(10))
    measured_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    measured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# Stage 10 — the release checklist. Validation proved the part is right; the
# release checklist proves the paperwork around it moved with it (index,
# drawings, ERP, packaging, the customer told). 'na' is an answer, not a skip:
# it needs a note saying why the item does not apply to this change.
RELEASE_CHECK_STATUSES = ("open", "done", "na")


class ChangeReleaseCheck(Base):
    """One item of the release checklist on one change (written on its first answer)."""
    __tablename__ = "change_release_checks"
    __table_args__ = (
        UniqueConstraint("change_id", "check_key", name="uq_change_release_check"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), index=True)
    check_key: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(
        String(10), default="open", server_default="open")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Owner, resolved from the catalog's department name at seeding time.
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_departments.id"), nullable=True)
    checked_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
