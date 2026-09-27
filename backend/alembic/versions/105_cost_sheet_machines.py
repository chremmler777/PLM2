"""105: MachineDB presses in the cost sheet.

- cost_sheet_machines: the local copy of MachineDB's machine list (synced by
  POST /cost-sheet/machines/sync), one row per MachineDB id per org, mapped
  to a plm2 plant (plant_id NULL = unmapped). Never deleted: a machine that
  leaves MachineDB is retired (retired_at) and inactive.
- cost_sheet_machine_item_rates: the hourly rate of one machine in a cost
  sheet version (one row per machine per version), versioned like the other
  rate rows.
- costing_positions.machine_id: the machine a machine_time / sampling line
  names; its own rate beats the class rate.

Guarded like 098: a table or column that exists already is left alone.

Revision ID: 105
Revises: 104
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "105"
down_revision = "104"
branch_labels = None
depends_on = None


def _cols(bind, table):
    return {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    if "cost_sheet_machines" not in tables:
        op.create_table(
            "cost_sheet_machines",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"),
                      nullable=False),
            sa.Column("machinedb_id", sa.Integer(), nullable=False),
            sa.Column("internal_name", sa.String(120), nullable=False),
            sa.Column("machinedb_plant", sa.String(40), nullable=True),
            sa.Column("plant_id", sa.Integer(), sa.ForeignKey("plants.id"), nullable=True),
            sa.Column("clamping_force_t", sa.Numeric(10, 2), nullable=True),
            sa.Column("tonnage_class", sa.String(20), nullable=True),
            sa.Column("two_k_type", sa.String(40), nullable=True),
            sa.Column("manufacturer", sa.String(120), nullable=True),
            sa.Column("model", sa.String(120), nullable=True),
            sa.Column("in_service_from", sa.Date(), nullable=True),
            sa.Column("planned_scrap_from", sa.Date(), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("retired_at", sa.DateTime(), nullable=True),
            sa.Column("source_updated_at", sa.String(40), nullable=True),
            sa.Column("synced_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("organization_id", "machinedb_id",
                                name="uq_cost_sheet_machine_machinedb_id"),
        )
        op.create_index("ix_cost_sheet_machines_organization_id", "cost_sheet_machines",
                        ["organization_id"])
        op.create_index("ix_cost_sheet_machines_plant_id", "cost_sheet_machines",
                        ["plant_id"])

    if "cost_sheet_machine_item_rates" not in tables:
        op.create_table(
            "cost_sheet_machine_item_rates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("version_id", sa.Integer(),
                      sa.ForeignKey("cost_sheet_versions.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("machine_id", sa.Integer(), sa.ForeignKey("cost_sheet_machines.id"),
                      nullable=False),
            sa.Column("hourly_rate", sa.Numeric(10, 2), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.UniqueConstraint("version_id", "machine_id",
                                name="uq_cost_sheet_machine_item_rate"),
        )
        op.create_index("ix_cost_sheet_machine_item_rates_version_id",
                        "cost_sheet_machine_item_rates", ["version_id"])
        op.create_index("ix_cost_sheet_machine_item_rates_machine_id",
                        "cost_sheet_machine_item_rates", ["machine_id"])

    if "costing_positions" in tables and "machine_id" not in _cols(bind, "costing_positions"):
        with op.batch_alter_table("costing_positions") as batch:
            batch.add_column(sa.Column("machine_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_costing_positions_machine", "cost_sheet_machines",
                                     ["machine_id"], ["id"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "costing_positions" in tables and "machine_id" in _cols(bind, "costing_positions"):
        # the FK by the name the database gave it (an unnamed SQLite FK, or a
        # name a DBA changed), never a fixed name that may not exist
        fks = [fk.get("name") for fk in inspect(bind).get_foreign_keys("costing_positions")
               if fk.get("constrained_columns") == ["machine_id"]]
        with op.batch_alter_table("costing_positions") as batch:
            for name in fks:
                if name:
                    batch.drop_constraint(name, type_="foreignkey")
            batch.drop_column("machine_id")
    if "cost_sheet_machine_item_rates" in tables:
        op.drop_table("cost_sheet_machine_item_rates")
    if "cost_sheet_machines" in tables:
        op.drop_table("cost_sheet_machines")
