"""DFM archive: per-tool topics, each a three-column ledger (toolmaker | KTX |
Tier 1) of append-only entries with files. Nothing here is deleted; an update
is a new entry that supersedes the old one, and the old one stays as history."""
from datetime import date, datetime

from sqlalchemy import String, Text, Date, DateTime, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

DFM_PARTIES = ("toolmaker", "ktx", "tier1")
DFM_TOPIC_OPEN = "open"
DFM_TOPIC_FINISHED = "finished_confirmed"
DFM_TOPIC_STATUSES = (DFM_TOPIC_OPEN, DFM_TOPIC_FINISHED)


class DfmTopic(Base):
    """One DFM question on one tool, closed by 'finished confirmed'."""
    __tablename__ = "dfm_topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    tool_part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default=DFM_TOPIC_OPEN, server_default=DFM_TOPIC_OPEN)

    opened_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    entries: Mapped[list["DfmEntry"]] = relationship(
        back_populates="topic", cascade="all, delete-orphan",
        order_by="DfmEntry.recorded_at, DfmEntry.id", lazy="selectin")


class DfmEntry(Base):
    """One row of the ledger, in its author's column (party)."""
    __tablename__ = "dfm_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("dfm_topics.id"), index=True)
    party: Mapped[str] = mapped_column(String(20))  # toolmaker | ktx | tier1
    addressed_to: Mapped[list] = mapped_column(JSON, default=list)  # one or two of the other parties
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # unique so an entry can only be superseded once; NULL stays allowed (multiple
    # entries may have no successor)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("dfm_entries.id"), nullable=True, unique=True)

    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))  # the KTX user who put it in
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sent_at: Mapped[date | None] = mapped_column(Date, nullable=True)  # mail date if different

    topic: Mapped["DfmTopic"] = relationship(back_populates="entries")
    files: Mapped[list["DfmEntryFile"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="DfmEntryFile.id", lazy="selectin")


class DfmEntryFile(Base):
    """A file attached to an entry. Kept forever with uploader and time."""
    __tablename__ = "dfm_entry_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("dfm_entries.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    saved_filename: Mapped[str] = mapped_column(String(255))  # <uuid><ext> under uploads/dfm/<tool>/<entry>/
    file_size: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(100))
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    entry: Mapped["DfmEntry"] = relationship(back_populates="files")
