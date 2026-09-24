"""Comments and a flag on one field of one part (article or tool).

A field is addressed by (part_id, field_key); field_key is the stable key of
the worksheet column registry (frontend/src/components/worksheet/worksheetColumns.ts),
e.g. tool.cavities, part.material, paint.colour. Tool fields live on the tool,
so a flag on tool.cavities shows on every article row that tool makes.
Comments are append only: a correction is a new comment.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

FIELD_FLAG_STATUSES = ("open", "confirmed", "rejected")


class FieldNote(Base):
    __tablename__ = "field_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"), index=True)
    field_key: Mapped[str] = mapped_column(String(64))
    flag_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    flag_set_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    flag_set_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    comments: Mapped[list["FieldNoteComment"]] = relationship(
        back_populates="note", cascade="all, delete-orphan",
        order_by="FieldNoteComment.created_at, FieldNoteComment.id", lazy="selectin")

    __table_args__ = (UniqueConstraint("part_id", "field_key", name="uq_field_note_part_field"),)


class FieldNoteComment(Base):
    __tablename__ = "field_note_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("field_notes.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    note: Mapped[FieldNote] = relationship(back_populates="comments")
