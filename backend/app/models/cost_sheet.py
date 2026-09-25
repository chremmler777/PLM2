"""The cost sheet (spec §15 / §15a): Finance's versioned price list for hours.

One VERSION per publish covers every part of the sheet: position rates,
machine rates, sampling prices and personnel overheads. A draft is edited in
place; publishing freezes it and gives it a valid_from. The published
versions form a chain ordered by valid_from, and a version is valid until the
day before the next one starts, so "the rate on 2026-03-14" always has
exactly one answer.

Machine classes are the org's own vocabulary (tonnage bands) and are not
versioned: renaming a class is housekeeping, not a price change. Rows in a
version store the class NAME, so a published version never changes meaning
when the class list is edited later.
"""
from datetime import date, datetime

from sqlalchemy import (
    Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text,
    UniqueConstraint, Boolean,
)
from sqlalchemy import true as sa_true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

VERSION_STATUSES = ("draft", "published")
SAMPLING_MODES = ("flat", "components")
OVERHEAD_KINDS = ("percent", "per_hour")
FINANCE_DEPARTMENT = "Finance"
DEFAULT_REVIEW_MONTHS = 12
SETTING_REVIEW_MONTHS = "cost_sheet_review_months"


class CostSheetVersion(Base):
    __tablename__ = "cost_sheet_versions"
    __table_args__ = (UniqueConstraint("organization_id", "version",
                                       name="uq_cost_sheet_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="draft",
                                        server_default="draft")
    # A draft may carry the date Finance intends; it is only binding once
    # published.
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    based_on_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    rates: Mapped[list["CostSheetRate"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="CostSheetRate.id")
    machine_rates: Mapped[list["CostSheetMachineRate"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="CostSheetMachineRate.id")
    sampling_rates: Mapped[list["CostSheetSamplingRate"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="CostSheetSamplingRate.id")
    overheads: Mapped[list["CostSheetOverhead"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="CostSheetOverhead.id")


class CostSheetRate(Base):
    """Hourly rate of a department, optionally narrowed to a position and a
    plant. position None = the department's default; plant None = all plants."""
    __tablename__ = "cost_sheet_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("cost_sheet_versions.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"))
    position: Mapped[str | None] = mapped_column(String(80), nullable=True)
    plant_id: Mapped[int | None] = mapped_column(ForeignKey("plants.id"), nullable=True)
    hourly_rate: Mapped[float] = mapped_column(Numeric(10, 2, asdecimal=False))
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    # Carried over from department_rate (the Std.-Saetze sheet's factor) so
    # /changes/reference/rates keeps its shape. Not used by the lookups.
    min_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class CostSheetMachineClass(Base):
    """An org's machine class vocabulary, e.g. tonnage bands."""
    __tablename__ = "cost_sheet_machine_classes"
    __table_args__ = (UniqueConstraint("organization_id", "name",
                                       name="uq_cost_sheet_machine_class"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    tonnage_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tonnage_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())


class CostSheetMachineRate(Base):
    """Hourly machine rate of a class (or one named press) at a plant."""
    __tablename__ = "cost_sheet_machine_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("cost_sheet_versions.id", ondelete="CASCADE"), index=True)
    plant_id: Mapped[int | None] = mapped_column(ForeignKey("plants.id"), nullable=True)
    machine_class: Mapped[str] = mapped_column(String(40))
    machine_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tonnage_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tonnage_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hourly_rate: Mapped[float] = mapped_column(Numeric(10, 2, asdecimal=False))
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class CostSheetSamplingRate(Base):
    """Price of one sampling trial on a machine class.

    flat: flat_price per trial. components: (setup_hours + run_hours_default)
    x the class's machine rate + labour_hours x the effective labour rate of
    labour_department_id (and labour_position) + handling_cost.
    """
    __tablename__ = "cost_sheet_sampling_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("cost_sheet_versions.id", ondelete="CASCADE"), index=True)
    plant_id: Mapped[int | None] = mapped_column(ForeignKey("plants.id"), nullable=True)
    machine_class: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(12), default="flat", server_default="flat")
    flat_price: Mapped[float | None] = mapped_column(
        Numeric(12, 2, asdecimal=False), nullable=True)
    setup_hours: Mapped[float | None] = mapped_column(
        Numeric(8, 2, asdecimal=False), nullable=True)
    run_hours_default: Mapped[float | None] = mapped_column(
        Numeric(8, 2, asdecimal=False), nullable=True)
    labour_hours: Mapped[float | None] = mapped_column(
        Numeric(8, 2, asdecimal=False), nullable=True)
    labour_department_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_departments.id"), nullable=True)
    labour_position: Mapped[str | None] = mapped_column(String(80), nullable=True)
    handling_cost: Mapped[float | None] = mapped_column(
        Numeric(12, 2, asdecimal=False), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class CostSheetOverhead(Base):
    """Personnel overhead on top of a position rate. kind percent: value is a
    percentage (25 = +25 %); kind per_hour: value is added per hour."""
    __tablename__ = "cost_sheet_overheads"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("cost_sheet_versions.id", ondelete="CASCADE"), index=True)
    plant_id: Mapped[int | None] = mapped_column(ForeignKey("plants.id"), nullable=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_departments.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(12), default="percent", server_default="percent")
    value: Mapped[float] = mapped_column(Numeric(10, 4, asdecimal=False))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class OrgSetting(Base):
    """Small key/value settings per organization (e.g. cost_sheet_review_months).
    Values are strings; the reader owns the parsing and the default."""
    __tablename__ = "org_settings"
    __table_args__ = (UniqueConstraint("organization_id", "key",
                                       name="uq_org_setting_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True)
    key: Mapped[str] = mapped_column(String(80))
    value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
