"""Paint master data and the per-article paint setup.

A paint is org-scoped master data (like catalog_parts). An article's paint
setup hangs off the part, not the revision, and lists paints in layer order.
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.database import Base  # match the import the other models use

PAINT_TYPES = ("primer", "basecoat", "clearcoat", "one_coat", "other")


class Paint(Base):
    __tablename__ = "paints"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    paint_type: Mapped[str] = mapped_column(String(20), default="basecoat")
    colour_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    colour_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    colour_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    supplier_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    spec_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_paint_org_name"),)


class PartPaint(Base):
    __tablename__ = "part_paints"
    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"), unique=True)
    paint_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    process: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    layers: Mapped[list["PartPaintLayer"]] = relationship(
        back_populates="setup", cascade="all, delete-orphan", order_by="PartPaintLayer.layer_order", lazy="selectin")


class PartPaintLayer(Base):
    __tablename__ = "part_paint_layers"
    id: Mapped[int] = mapped_column(primary_key=True)
    part_paint_id: Mapped[int] = mapped_column(ForeignKey("part_paints.id", ondelete="CASCADE"), index=True)
    paint_id: Mapped[int] = mapped_column(ForeignKey("paints.id"), index=True)
    layer_order: Mapped[int] = mapped_column(Integer)
    area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    setup: Mapped[PartPaint] = relationship(back_populates="layers")
    paint: Mapped[Paint] = relationship(lazy="selectin")
    __table_args__ = (UniqueConstraint("part_paint_id", "layer_order", name="uq_part_paint_layer_order"),)
