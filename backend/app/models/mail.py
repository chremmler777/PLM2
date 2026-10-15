"""Part data mail (115): a fixed recipient list per project and the outbox the
5-minute digest sends from. See app/services/part_data_mail.py."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

#: The only list for now; role-based lists come later.
LIST_PART_DATA = "part_data"
MAIL_LISTS = (LIST_PART_DATA,)
#: pending -> sending (claimed by one worker) -> sent | failed | skipped
MAIL_STATUSES = ("pending", "sending", "sent", "failed", "skipped")


class MailRecipient(Base):
    __tablename__ = "mail_recipients"
    __table_args__ = (UniqueConstraint("project_id", "list_key", "email",
                                       name="uq_mail_recipients_project_list_email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    list_key: Mapped[str] = mapped_column(String(40), default=LIST_PART_DATA)
    email: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MailOutbox(Base):
    __tablename__ = "mail_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"))
    revision_id: Mapped[int | None] = mapped_column(ForeignKey("part_revisions.id"), nullable=True)
    event: Mapped[str] = mapped_column(String(50))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Who did it (the changelog's performed_by); the mail names them.
    performed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    mail_status: Mapped[str] = mapped_column(String(10), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
