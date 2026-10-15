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

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint, select,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

INTAKE_SOURCES = ("package", "customer_data", "upload", "promote")
INTAKE_STATUSES = ("pending", "decided", "superseded", "rejected")
# Closed without activation: a newer index replaced it, or the pending
# revision itself was rejected. Neither waits nor can be triaged any more.
CLOSED_STATUSES = ("superseded", "rejected")
ROUTES = ("full_ecr", "attach_ecr", "engineering_review", "administrative")
REVIEW_ANSWERS = ("no_impact", "impact")
# ECR-solid §1 (migration 123): "what changed" at triage. 'none' = no visible
# change (needs a reason, makes no rechecks).
WHAT_CHANGED_AREAS = ("geometry", "tolerance", "material", "colour_grain", "other")
NO_VISIBLE_CHANGE = "none"
# full_ecr although a live change carries the part: the reason pick.
LIVE_CHANGE_REASONS = ("separate_topic", "customer_separate_ec", "live_change_too_far",
                       "other")
# Sales: "D replaces C; deadline holds?"
DEADLINE_ANSWERS = ("holds", "new_date", "not_asked")
RECHECK_STATUSES = ("open", "answered")


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
    # ECR-solid §1 (migration 123). What changed (required at triage, switch
    # SCOPING_V2): areas + a compare reference, or ['none'] + a reason.
    what_changed: Mapped[list | None] = mapped_column(JSON, nullable=True)
    what_changed_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    no_change_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # full_ecr although a live change carries the part (LIVE_CHANGE_REASONS)
    live_change_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # attach to an internal change: customer-driven? (yes flips it)
    customer_driven: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # The index it replaced inside the change (C for C -> D): set when the
    # new index lands on a part the change already carried; the follow-ups
    # (rechecks, the lead's and Sales' questions) hang off it.
    replaced_revision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The lead: "Index D adds parts or departments?" (no | yes + note)
    scope_answer: Mapped[str | None] = mapped_column(String(5), nullable=True)
    scope_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scope_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    scope_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Sales (open quote): "D replaces C; deadline holds?"
    deadline_needed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    deadline_answer: Mapped[str | None] = mapped_column(String(10), nullable=True)
    deadline_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deadline_confirm_by: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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
        """The revision is still pending: not activated, not superseded or
        rejected."""
        return self.activated_at is None and self.status not in CLOSED_STATUSES


def waiting_revision_ids():
    """Subquery: revision ids still pending behind an intake. Everything that
    shows or builds on "the current revision" skips these."""
    return select(RevisionIntake.revision_id).where(
        RevisionIntake.activated_at.is_(None),
        RevisionIntake.status.notin_(CLOSED_STATUSES))


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


class ChangeRecheck(Base):
    """ECR-solid §1 (migration 123): a new index landed on a part the change
    already carried; each routed department that had submitted rechecks its
    assessment per changed area: 'no effect' (drawing ref / checklist row) or
    'effect' (what + evidence), plus anything else that changed."""
    __tablename__ = "change_rechecks"
    __table_args__ = (
        UniqueConstraint("intake_id", "department_id",
                         name="uq_change_recheck_intake_department"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)
    intake_id: Mapped[int] = mapped_column(ForeignKey("revision_intakes.id"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"))
    part_id: Mapped[int | None] = mapped_column(ForeignKey("parts.id"), nullable=True)
    from_revision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_revision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    areas: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # [{area, effect: bool, ref | what + evidence}]
    answers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    something_else: Mapped[str | None] = mapped_column(Text, nullable=True)
    effect: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    answered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
