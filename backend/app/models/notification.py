"""In-app notification model."""
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base


class Notification(Base):
    """A notification for one user (workflow events, calibration, approvals)."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)  # frontend path

    # Dedup key: kind + subject_key identify "the same event" for a user so a
    # repeat emission (e.g. a sweep re-run) doesn't spam an unread notification.
    kind: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    subject_key: Mapped[str | None] = mapped_column(String(120), nullable=True)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
