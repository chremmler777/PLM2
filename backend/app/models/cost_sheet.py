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
    JSON, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text,
    UniqueConstraint, Boolean, Index,
)
from sqlalchemy import func
from sqlalchemy import true as sa_true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

VERSION_STATUSES = ("draft", "published")
SAMPLING_MODES = ("flat", "components")
OVERHEAD_KINDS = ("percent", "per_hour")
FINANCE_DEPARTMENT = "Finance"
# Sales changes the rates (it prices the changes for the customer); Finance
# and admins may too.
SALES_DEPARTMENT = "Sales"
EDITOR_DEPARTMENTS = (SALES_DEPARTMENT, FINANCE_DEPARTMENT)
DEFAULT_REVIEW_MONTHS = 12
SETTING_REVIEW_MONTHS = "cost_sheet_review_months"
# org_settings key prefix: Finance confirmed plant <id>'s currency (094 set
# it from the location only).
SETTING_PLANT_CURRENCY_CONFIRMED = "plant_currency_confirmed:"
# ISO 4217 codes the sheet accepts. Short on purpose: a typo'd code would
# silently split a department's rates into two currencies.
CURRENCIES = ("EUR", "USD", "MXN", "RSD", "GBP", "CHF", "CNY", "CZK", "PLN", "HUF",
              "JPY", "INR", "BRL", "CAD", "SEK", "TRY", "ZAR", "KRW")


class CostSheetVersion(Base):
    __tablename__ = "cost_sheet_versions"
    __table_args__ = (
        UniqueConstraint("organization_id", "version", name="uq_cost_sheet_version"),
        # One open draft per org, enforced by the database: draft_lock is 1 on
        # a draft and NULL once published, and NULLs never collide.
        Index("uq_cost_sheet_one_draft", "organization_id", "draft_lock", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    draft_lock: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # The exchange rates this version uses (106): {"USD/MXN": "17.30"} = one
    # USD is 17.30 MXN, decimal text as typed. Frozen with the version.
    fx_rates: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    rates: Mapped[list["CostSheetRate"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="CostSheetRate.id")
    machine_rates: Mapped[list["CostSheetMachineRate"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="CostSheetMachineRate.id")
    sampling_rates: Mapped[list["CostSheetSamplingRate"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="CostSheetSamplingRate.id")
    overheads: Mapped[list["CostSheetOverhead"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="CostSheetOverhead.id")


class CostSheetRate(Base):
    """Hourly rate of a department at a plant (plant None = all plants).
    Exactly one row per department per plant in a version (migration 104,
    uq_cost_sheet_rate_dept_plant). hourly_rate None = no rate entered yet:
    costing shows "No rate in the cost sheet", never 0.

    position is no longer used (104 merged the position rows into their
    department's row); the column stays for the downgrade."""
    __tablename__ = "cost_sheet_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("cost_sheet_versions.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"))
    position: Mapped[str | None] = mapped_column(String(80), nullable=True)
    plant_id: Mapped[int | None] = mapped_column(ForeignKey("plants.id"), nullable=True)
    hourly_rate: Mapped[float | None] = mapped_column(
        Numeric(10, 2, asdecimal=False), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    # The rate as typed when it was typed in the plant's local currency (106):
    # hourly_rate is then computed from it with the version's exchange rate,
    # so the typed number never drifts. None = typed as hourly_rate.
    entered_rate: Mapped[float | None] = mapped_column(
        Numeric(12, 2, asdecimal=False), nullable=True)
    entered_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    # Carried over from department_rate (the Std.-Saetze sheet's factor) so
    # /changes/reference/rates keeps its shape. Not used by the lookups.
    min_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


# One row per department per plant; plant NULL (all plants) collides with
# plant NULL too (plain NULLs never collide in a unique index).
Index("uq_cost_sheet_rate_dept_plant", CostSheetRate.version_id, CostSheetRate.department_id,
      func.coalesce(CostSheetRate.plant_id, 0), unique=True)


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
    # The class this row prices; machine_class keeps its name for display and
    # export and is rewritten when the class is renamed.
    machine_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("cost_sheet_machine_classes.id"), nullable=True)
    machine_class: Mapped[str] = mapped_column(String(40))
    machine_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tonnage_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tonnage_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hourly_rate: Mapped[float] = mapped_column(Numeric(10, 2, asdecimal=False))
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    # As on CostSheetRate (106): the rate typed in the plant's local currency.
    entered_rate: Mapped[float | None] = mapped_column(
        Numeric(12, 2, asdecimal=False), nullable=True)
    entered_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
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
    # The class this row prices; machine_class keeps its name for display and
    # export and is rewritten when the class is renamed.
    machine_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("cost_sheet_machine_classes.id"), nullable=True)
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
    # per_hour only: the currency the amount is in; it must match the rate's.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
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
