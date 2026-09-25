"""Revision intake (spec 2026-09-25 §17, migration 096).

Every new customer index that arrives through a gated path (customer
package, customer data, upload, promote) is captured as one intake. The
revision stays pending (status in_review, never the part's active one) until
Development decides the route and the route activates it:

- full_ecr / attach_ecr: the change's release activates it;
- engineering_review: the light review activates it when every department
  answered "no impact" (or it is escalated to a full ECR);
- administrative: activated at once, reason required.

ChangeReviewAnswer holds the engineering review's department answers.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

INTAKE_SOURCES = ("package", "customer_data", "upload", "promote")
INTAKE_STATUSES = ("pending", "decided", "superseded")
ROUTES = ("full_ecr", "attach_ecr", "engineering_review", "administrative")
REVIEW_ANSWERS = ("no_impact", "impact")


class RevisionIntake(Base):
    __tablename__ = "revision_intakes"
    __table_args__ = (
        UniqueConstraint("revision_id", name="uq_revision_intake_revision"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("part_revisions.id"))
    source: Mapped[str] = mapped_column(String(20))
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    received_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    received_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending",
                                        server_default="pending", index=True)
    # Snapshot at receipt: the customer's statement (review | official) and
    # the part's lifecycle phase (rfq | nominated | series).
    revision_phase: Mapped[str | None] = mapped_column(String(20), nullable=True)
    part_phase: Mapped[str | None] = mapped_column(String(20), nullable=True)
    suggested_route: Mapped[str | None] = mapped_column(String(30), nullable=True)
    route: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    change_id: Mapped[int | None] = mapped_column(
        ForeignKey("change_requests.id"), nullable=True, index=True)
    # promote_revision: the proposal the customer adopted. Its "approved" and
    # its siblings' "rejected" happen when this revision is activated.
    promoted_from_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("part_revisions.id"), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    escalated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("revision_intakes.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    received_by_user: Mapped["User | None"] = relationship(
        foreign_keys=[received_by], lazy="selectin")
    decided_by_user: Mapped["User | None"] = relationship(
        foreign_keys=[decided_by], lazy="selectin")

    @property
    def received_by_name(self) -> Optional[str]:
        u = self.received_by_user
        return u.full_name if u is not None else None

    @property
    def decided_by_name(self) -> Optional[str]:
        u = self.decided_by_user
        return u.full_name if u is not None else None

    @property
    def is_waiting(self) -> bool:
        """The revision is still pending: not activated, not superseded."""
        return self.activated_at is None and self.status != "superseded"


def waiting_revision_ids():
    """Subquery: revision ids still pending behind an intake. Everything that
    shows or builds on "the current revision" skips these."""
    return select(RevisionIntake.revision_id).where(
        RevisionIntake.activated_at.is_(None),
        RevisionIntake.status != "superseded")


class ChangeReviewAnswer(Base):
    """Engineering review (origin engineering_review): one department's
    answer, "no impact" or "impact", with a note."""
    __tablename__ = "change_review_answers"
    __table_args__ = (
        UniqueConstraint("change_id", "department_id", name="uq_change_review_answer"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"))
    answer: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    answered_by_user: Mapped["User | None"] = relationship(
        foreign_keys=[answered_by], lazy="selectin")

    @property
    def answered_by_name(self) -> Optional[str]:
        u = self.answered_by_user
        return u.full_name if u is not None else None
