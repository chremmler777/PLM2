"""SEP forms engine: JSON-defined forms filled per project.

Definitions are immutable per (key, version); instances hold the filled data as
JSON and point at the version they were created against; events are the audit
trail (created/saved/submitted/reopened/signed).
"""
from datetime import datetime

from sqlalchemy import String, Text, DateTime, Boolean, Integer, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

FORM_STATUSES = ("draft", "submitted", "reopened")
FORM_EVENTS = ("created", "saved", "submitted", "reopened", "signed")
FORM_CARDINALITIES = ("single", "multi")


class FormDefinition(Base):
    __tablename__ = "form_definitions"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_form_definition_key_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    implements: Mapped[str | None] = mapped_column(String(60), nullable=True)
    cardinality: Mapped[str] = mapped_column(String(10), default="single")
    gate_items: Mapped[bool] = mapped_column(Boolean, default=False)
    body: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FormInstance(Base):
    __tablename__ = "form_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("form_definitions.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    definition: Mapped["FormDefinition"] = relationship()
    events: Mapped[list["FormEvent"]] = relationship(
        back_populates="instance", cascade="all, delete-orphan", order_by="FormEvent.id"
    )


class FormEvent(Base):
    __tablename__ = "form_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("form_instances.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    event: Mapped[str] = mapped_column(String(20))
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    diff: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    instance: Mapped["FormInstance"] = relationship(back_populates="events")
