"""Lessons learned models - project knowledge capture with actions and comments."""
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

LESSON_CATEGORIES = (
    "design", "manufacturing", "quality", "supplier",
    "logistics", "project_management", "tooling", "other",
)
LESSON_TYPES = ("success", "problem", "improvement")
LESSON_SEVERITIES = ("low", "medium", "high", "critical")
REJECT_CATEGORIES = ("duplicate", "not_actionable", "out_of_scope", "insufficient_info")

# Strict server-enforced lifecycle. Creation lands in in_review (no draft/submit step):
# in_review -accept-> in_work -owner sends-> verification -verified-> closed
#     `-reject-> rejected          ^---- send back with feedback ----'
LESSON_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "in_review": ("in_work", "rejected"),
    "in_work": ("verification",),
    "verification": ("closed", "in_work"),
    "rejected": (),
    "closed": (),
}

# Days in state before a lesson is flagged stale (in_work uses target_date instead)
STALE_AFTER_DAYS = {"in_review": 14, "verification": 7}


class LessonLearned(Base):
    """A captured lesson; optionally linked to a PLM project (link-later supported)."""
    __tablename__ = "lessons_learned"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))

    # Capture-first, link-later: FK is optional, free-text ref keeps the project name
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    project_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)

    category: Mapped[str] = mapped_column(String(30), default="other")
    lesson_type: Mapped[str] = mapped_column(String(20), default="problem")
    severity: Mapped[str] = mapped_column(String(10), default="medium")

    description: Mapped[str] = mapped_column(Text)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[str | None] = mapped_column(String(300), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="in_review", index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("wf_departments.id"), nullable=True)
    target_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # required to accept

    # Rejection (terminal), categorized for KPI analysis
    reject_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # legacy (pre-v3)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # legacy (pre-v3)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # in_review -> in_work
    verification_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Effectiveness verification, required to close ("did the recommendation work?")
    effectiveness_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    effectiveness_verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    effectiveness_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LessonAction(Base):
    """Follow-up action on a lesson; a lesson cannot close while actions are open."""
    __tablename__ = "lesson_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons_learned.id"), index=True)

    description: Mapped[str] = mapped_column(Text)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open, done
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LessonReference(Base):
    """Records that a lesson was reviewed/applied for a project (reuse tracking)."""
    __tablename__ = "lesson_references"

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons_learned.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    milestone_id: Mapped[int | None] = mapped_column(ForeignKey("project_milestones.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LessonFile(Base):
    """Evidence attachment on a lesson (photos, reports, 8D sheets)."""
    __tablename__ = "lesson_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons_learned.id"), index=True)

    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LessonComment(Base):
    """Discussion thread; system comments record status transitions for auditability."""
    __tablename__ = "lesson_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons_learned.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
