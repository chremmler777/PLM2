"""Project LOP: the list of open points of one project.

A line is either a PM task (`task`, owns its title) or a reference to an
existing record (`sep_item`, `risk`, `pdb_topic`), identified by `ref_key`
(the source id as text). References are never copied: closing a line and
closing its source are the same record. Datetimes are naive UTC; dates
without a time are Date columns.
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

LOP_KINDS = ("task", "sep_item", "risk", "pdb_topic")
LOP_STATUSES = ("new", "open", "in_work", "done_check", "closed")
LOP_MARKS = ("updated", "moved", "escalated", "none")


class LopLine(Base):
    __tablename__ = "lop_lines"
    __table_args__ = (
        # NULL ref_key (tasks) never collides: SQL treats NULLs as distinct.
        UniqueConstraint("project_id", "kind", "ref_key", name="uq_lop_line_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    ref_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_departments.id"), nullable=True)
    responsible_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    responsible_is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0")
    next_check_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(15), default="new", server_default="new")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_update_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_update_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class LopComment(Base):
    __tablename__ = "lop_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("lop_lines.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LopEvent(Base):
    """History of one field change on a line (who, what, why)."""
    __tablename__ = "lop_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("lop_lines.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    field: Mapped[str] = mapped_column(String(50))
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LopMeeting(Base):
    __tablename__ = "lop_meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    held_on: Mapped[date] = mapped_column(Date)
    started_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    minutes_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LopMeetingMark(Base):
    __tablename__ = "lop_meeting_marks"
    __table_args__ = (
        UniqueConstraint("meeting_id", "line_id", name="uq_lop_meeting_mark"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("lop_meetings.id"), index=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("lop_lines.id"), index=True)
    mark: Mapped[str] = mapped_column(String(15), default="none", server_default="none")
    was_late: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    was_stale: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
