"""ECR training: the record that says a person was taught the change process.

Modelled 1:1 on the TWOS training sign-off (TWOS docs/training.md). Three
tables, and the split between them is the whole design:

  training_versions   what is currently required of a training role. Published
                      deliberately (admin, Quality or Project Management),
                      never as a side effect of a deploy.
  training_signoffs   one row per (user, role, version): who trained them, when
                      the training was held, when they passed the practical
                      tasks, and on which software version. Superseded, never
                      rewritten.
  training_attempts   append-only, one row per attempt at one task. Retries are
                      unlimited and every one of them is kept.

Training roles are not departments. One role covers several departments
(Engineers: Development, Tool Engineer, Manufacturing Engineer, Process
Engineer, APQP, Packaging Engineer); the mapping lives in
app/services/training.py.

Nothing here is ever deleted or edited in place, apart from the status and
the stamps the service sets. Timestamps are naive UTC like the rest of PLM2.

Unlike TWOS, the record does not gate anything by default (ruling
2026-09-25): see TRAINING_GATE in app/services/training.py.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base


class SignoffStatus:
    """Where a sign-off sits between "I was trained" and "I am signed off".

        pending_tasks  attested, practical tasks not all passed yet
        active         every task passed at this version
        superseded     a newer version of this role's material was published

    Stored as a plain string (portable across Postgres and the SQLite test
    database); svc.recompute_status is the only place it is decided.
    """
    pending_tasks = "pending_tasks"
    active = "active"
    superseded = "superseded"
    ALL = (pending_tasks, active, superseded)


class TrainerSource:
    """How the trainer's name got onto the record.

    self_declared  the person named their trainer themselves (normal path)
    roster         somebody entitled to keep the records entered attendance
                   they witnessed (admin, Quality or Project Management)
    """
    self_declared = "self_declared"
    roster = "roster"


class AttemptResult:
    passed = "passed"
    failed = "failed"
    ALL = (passed, failed)


class TrainingVersion(Base):
    """One published (role, version). The highest published version is required.

    Version 1 is implicit: it is required whether or not a row exists for it,
    so an installation that never opens the publish screen still has a
    complete record to fill.
    """

    __tablename__ = "training_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: What changed, shown to everyone this publication asks to re-train.
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    #: The software version the material was published for (app/version.py).
    software_version: Mapped[str | None] = mapped_column(String(40))
    published_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow)
    published_by: Mapped[str] = mapped_column(String(255), nullable=False)
    published_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint("role", "version", name="uq_training_version_role_version"),
        Index("ix_training_versions_role", "role", "version"),
    )


class TrainingSignoff(Base):
    """One (user, role, version). The auditable unit."""

    __tablename__ = "training_signoffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: Identity as it read at sign-off. Snapshotted: a person can be renamed
    #: or leave, and the record must still say who it was about.
    email_snapshot: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    display_name: Mapped[str | None] = mapped_column(String(255))

    role: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    #: The day the training session was actually held. Distinct from
    #: attested_at (the moment the person clicked).
    training_date: Mapped[date | None] = mapped_column(Date)
    attested_at: Mapped[datetime | None] = mapped_column(DateTime)

    trainer_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    trainer_name: Mapped[str | None] = mapped_column(String(255))
    trainer_source: Mapped[str | None] = mapped_column(String(20))

    #: Set once every task in this version has a passing attempt. Never moves
    #: afterwards, even if the person retakes a task.
    tasks_passed_at: Mapped[datetime | None] = mapped_column(DateTime)
    #: The software version the tasks were passed on (app/version.py).
    #: Snapshotted at the pass, never recomputed.
    software_version: Mapped[str | None] = mapped_column(String(40))

    #: Who entered this row when it came from the attendance roster.
    recorded_by: Mapped[str | None] = mapped_column(String(255))
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SignoffStatus.pending_tasks)

    superseded_at: Mapped[datetime | None] = mapped_column(DateTime)
    #: The row this one carried its attestation forward from.
    carried_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_signoffs.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow)

    attempts: Mapped[list["TrainingAttempt"]] = relationship(
        back_populates="signoff",
        cascade="all",
        order_by="TrainingAttempt.id",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "role", "version",
                         name="uq_training_signoff_user_role_version"),
        Index("ix_training_signoffs_user", "user_id", "status"),
        Index("ix_training_signoffs_role", "role", "version"),
    )


class TrainingAttempt(Base):
    """One go at one task. Append-only; never updated, never deleted."""

    __tablename__ = "training_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signoff_id: Mapped[int] = mapped_column(
        ForeignKey("training_signoffs.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    task_key: Mapped[str] = mapped_column(String(80), nullable=False)
    #: Per (user, role, version, task). 1-based.
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(10), nullable=False)
    #: Which check failed and what the sandbox held at the time.
    detail: Mapped[dict | None] = mapped_column(JSON)
    #: Wall-clock seconds, reported by the browser. Advisory only.
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow)

    signoff: Mapped[TrainingSignoff] = relationship(back_populates="attempts")

    __table_args__ = (
        Index("ix_training_attempts_signoff", "signoff_id", "task_key"),
        Index("ix_training_attempts_user", "user_id", "created_at"),
    )
