"""MachineDB presses in the cost sheet (migration 105).

cost_sheet_machines is the local copy of MachineDB's machine list, refreshed
by a sync (cost_sheet_machines_service.sync_machines). Costing reads this
copy only, so the sheet keeps working on the last synced list when MachineDB
is unreachable. A machine that disappears from MachineDB is never deleted
(rates and costing lines point at it): it is marked retired and inactive.

cost_sheet_machine_item_rates is the per-machine hourly rate, one row per
machine per cost sheet version. It rides the version like every other rate
(copied into a new draft, frozen on publish, part of the diff). Where a
costing line names a machine, its row beats the class rate of the plant.
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy import true as sa_true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.cost_sheet import CostSheetVersion
from app.models.database import Base

# org_settings key: JSON {"usa": <plant id>, "mexico": <plant id>, ...};
# a MachineDB plant maps to null = deliberately not mapped.
SETTING_MACHINEDB_PLANT_MAP = "machinedb_plant_map"
# org_settings key: JSON of the last sync report (counts, the time).
SETTING_MACHINEDB_LAST_SYNC = "machinedb_last_sync"
# org_settings key: "true" = the startup sync copies MachineDB into this
# org. Unset everywhere: only a single org with plants is synced at startup.
SETTING_MACHINEDB_ENABLED = "machinedb_enabled"


class CostSheetMachine(Base):
    __tablename__ = "cost_sheet_machines"
    __table_args__ = (UniqueConstraint("organization_id", "machinedb_id",
                                       name="uq_cost_sheet_machine_machinedb_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True)
    machinedb_id: Mapped[int] = mapped_column(Integer)
    internal_name: Mapped[str] = mapped_column(String(120))
    # MachineDB's plant key (usa, mexico, weissenburg, ...) and the plm2
    # plant it maps to; None = not mapped (listed in the sync report).
    machinedb_plant: Mapped[str | None] = mapped_column(String(40), nullable=True)
    plant_id: Mapped[int | None] = mapped_column(
        ForeignKey("plants.id"), nullable=True, index=True)
    clamping_force_t: Mapped[float | None] = mapped_column(
        Numeric(10, 2, asdecimal=False), nullable=True)
    tonnage_class: Mapped[str | None] = mapped_column(String(20), nullable=True)
    two_k_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    in_service_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    planned_scrap_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Derived at sync: not scrapped (planned_scrap_from not reached) and
    # still listed by MachineDB.
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())
    # Set when MachineDB stopped listing the machine; cleared if it returns.
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CostSheetMachineItemRate(Base):
    """Hourly rate of ONE machine in a cost sheet version."""
    __tablename__ = "cost_sheet_machine_item_rates"
    __table_args__ = (UniqueConstraint("version_id", "machine_id",
                                       name="uq_cost_sheet_machine_item_rate"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("cost_sheet_versions.id", ondelete="CASCADE"), index=True)
    machine_id: Mapped[int] = mapped_column(
        ForeignKey("cost_sheet_machines.id"), index=True)
    hourly_rate: Mapped[float] = mapped_column(Numeric(10, 2, asdecimal=False))
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 107: the rate as typed in the plant's local currency (Silao: MXN);
    # hourly_rate is then computed from it at the version's exchange rate.
    entered_rate: Mapped[float | None] = mapped_column(
        Numeric(12, 2, asdecimal=False), nullable=True)
    entered_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)


# The version carries its machine rows like its other rate rows (loaded with
# it, copied into a draft, deleted with a discarded draft). Declared here so
# the MachineDB part stays in one module.
CostSheetVersion.machine_item_rates = relationship(
    CostSheetMachineItemRate, cascade="all, delete-orphan", lazy="selectin",
    order_by=CostSheetMachineItemRate.id)
