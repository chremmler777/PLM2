"""Moldflow timing per tool: one row per tool, Moldflow version ("V1", "V2", ...)
and, when the toolmaker runs both, cavity layout ("2" / "2+2"). It tracks the
inputs (geometry, gate, UDB), the dates of each step (requested, received,
KTX review, sent to customer, customer feedback, final) and an explicit status.

The findings/review tree of a Moldflow report hangs off these rows later
(by tool_moldflow.id). Rows are soft deleted (deleted_at), never removed;
every write is in the audit log (entity_type "tool_moldflow")."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

MF_INPUT_STATUSES = ("open", "in_progress", "ready", "n/a")
MF_STATUSES = ("not_started", "inputs_open", "ready_for_mf", "running", "received", "in_review",
               "sent_to_customer", "customer_feedback", "rework", "final")
# The step dates in process order: (column, label)
MF_DATES = (
    ("mf_requested_on", "MF requested"),
    ("received_on", "Received"),
    ("ktx_review_on", "KTX review"),
    ("sent_customer_on", "Sent to customer"),
    ("customer_feedback_on", "Customer feedback"),
    ("final_on", "Final"),
)
MF_INPUTS = ("geometry_status", "gate_status", "udb_status")


class ToolMoldflow(Base):
    __tablename__ = "tool_moldflow"
    __table_args__ = (
        # One live row per tool, version and layout. NULL layout counts as one value
        # (coalesce), a soft-deleted row does not block a new one.
        Index("uq_tool_moldflow_tool_version_layout", "tool_part_id", "version",
              func.coalesce(text("cavity_layout"), ""), unique=True,
              sqlite_where=text("deleted_at IS NULL"), postgresql_where=text("deleted_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tool_part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), index=True)
    version: Mapped[str] = mapped_column(String(10), default="V1", server_default="V1")
    cavity_layout: Mapped[str | None] = mapped_column(String(40), nullable=True)

    geometry_status: Mapped[str] = mapped_column(String(12), default="open", server_default="open")
    gate_status: Mapped[str] = mapped_column(String(12), default="open", server_default="open")
    udb_status: Mapped[str] = mapped_column(String(12), default="open", server_default="open")
    material_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    udb_source: Mapped[str | None] = mapped_column(String(255), nullable=True)

    mf_requested_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    received_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ktx_review_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    sent_customer_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    customer_feedback_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    final_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    customer_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="not_started", server_default="not_started")
    blockers: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
