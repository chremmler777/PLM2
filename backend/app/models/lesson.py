"""Lessons learned models - project knowledge capture with actions and comments."""
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

LESSON_CATEGORIES = (
    "design", "manufacturing", "quality", "supplier",
    "logistics", "project_management", "tooling", "other",
)
LESSON_TYPES = ("success", "problem", "improvement")
LESSON_SEVERITIES = ("low", "medium", "high", "critical")

# Server-enforced status lifecycle
LESSON_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("submitted",),
    "submitted": ("in_review", "draft"),
    "in_review": ("approved", "rejected"),
    "approved": ("implemented",),
    "implemented": ("closed",),
    "rejected": ("draft",),
    "closed": (),
}


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

    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("wf_departments.id"), nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
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
