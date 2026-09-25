"""092: cost sheet (spec §15 / §15a), Finance department, org settings.

Tables: cost_sheet_versions, cost_sheet_rates, cost_sheet_machine_classes,
cost_sheet_machine_rates, cost_sheet_sampling_rates, cost_sheet_overheads,
org_settings. Creates the "Finance" department if missing and migrates
department_rate into version 1 (published, valid from the earliest
effective_from) per organization, taking the latest row per
department x plant. department_rate itself stays untouched.

Dialect-neutral (Core inserts, no raw booleans), same file on Postgres and
SQLite.

Revision ID: 092
Revises: 091
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "092"
down_revision = "091"
branch_labels = None
depends_on = None

TABLES = ("cost_sheet_overheads", "cost_sheet_sampling_rates", "cost_sheet_machine_rates",
          "cost_sheet_machine_classes", "cost_sheet_rates", "cost_sheet_versions",
          "org_settings")


def _money(p=10, s=2):
    return sa.Numeric(p, s)


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())

    if "cost_sheet_versions" not in existing:
        op.create_table(
            "cost_sheet_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"),
                      nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
            sa.Column("valid_from", sa.Date(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("based_on_version_id", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("published_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.UniqueConstraint("organization_id", "version", name="uq_cost_sheet_version"),
        )
        op.create_index("ix_cost_sheet_versions_organization_id", "cost_sheet_versions",
                        ["organization_id"])

    def version_fk():
        return sa.Column("version_id", sa.Integer(),
                         sa.ForeignKey("cost_sheet_versions.id", ondelete="CASCADE"),
                         nullable=False)

    if "cost_sheet_rates" not in existing:
        op.create_table(
            "cost_sheet_rates",
            sa.Column("id", sa.Integer(), primary_key=True),
            version_fk(),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"),
                      nullable=False),
            sa.Column("position", sa.String(80), nullable=True),
            sa.Column("plant_id", sa.Integer(), sa.ForeignKey("plants.id"), nullable=True),
            sa.Column("hourly_rate", _money(), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
            sa.Column("min_factor", sa.Float(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
        )
        op.create_index("ix_cost_sheet_rates_version_id", "cost_sheet_rates", ["version_id"])

    if "cost_sheet_machine_classes" not in existing:
        op.create_table(
            "cost_sheet_machine_classes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"),
                      nullable=False),
            sa.Column("name", sa.String(40), nullable=False),
            sa.Column("tonnage_min", sa.Integer(), nullable=True),
            sa.Column("tonnage_max", sa.Integer(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.UniqueConstraint("organization_id", "name", name="uq_cost_sheet_machine_class"),
        )
        op.create_index("ix_cost_sheet_machine_classes_organization_id",
                        "cost_sheet_machine_classes", ["organization_id"])

    if "cost_sheet_machine_rates" not in existing:
        op.create_table(
            "cost_sheet_machine_rates",
            sa.Column("id", sa.Integer(), primary_key=True),
            version_fk(),
            sa.Column("plant_id", sa.Integer(), sa.ForeignKey("plants.id"), nullable=True),
            sa.Column("machine_class", sa.String(40), nullable=False),
            sa.Column("machine_ref", sa.String(80), nullable=True),
            sa.Column("tonnage_min", sa.Integer(), nullable=True),
            sa.Column("tonnage_max", sa.Integer(), nullable=True),
            sa.Column("hourly_rate", _money(), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
            sa.Column("note", sa.Text(), nullable=True),
        )
        op.create_index("ix_cost_sheet_machine_rates_version_id", "cost_sheet_machine_rates",
                        ["version_id"])

    if "cost_sheet_sampling_rates" not in existing:
        op.create_table(
            "cost_sheet_sampling_rates",
            sa.Column("id", sa.Integer(), primary_key=True),
            version_fk(),
            sa.Column("plant_id", sa.Integer(), sa.ForeignKey("plants.id"), nullable=True),
            sa.Column("machine_class", sa.String(40), nullable=False),
            sa.Column("mode", sa.String(12), nullable=False, server_default="flat"),
            sa.Column("flat_price", _money(12), nullable=True),
            sa.Column("setup_hours", _money(8), nullable=True),
            sa.Column("run_hours_default", _money(8), nullable=True),
            sa.Column("labour_hours", _money(8), nullable=True),
            sa.Column("labour_department_id", sa.Integer(),
                      sa.ForeignKey("wf_departments.id"), nullable=True),
            sa.Column("labour_position", sa.String(80), nullable=True),
            sa.Column("handling_cost", _money(12), nullable=True),
            sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
            sa.Column("note", sa.Text(), nullable=True),
        )
        op.create_index("ix_cost_sheet_sampling_rates_version_id",
                        "cost_sheet_sampling_rates", ["version_id"])

    if "cost_sheet_overheads" not in existing:
        op.create_table(
            "cost_sheet_overheads",
            sa.Column("id", sa.Integer(), primary_key=True),
            version_fk(),
            sa.Column("plant_id", sa.Integer(), sa.ForeignKey("plants.id"), nullable=True),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"),
                      nullable=True),
            sa.Column("kind", sa.String(12), nullable=False, server_default="percent"),
            sa.Column("value", sa.Numeric(10, 4), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
        )
        op.create_index("ix_cost_sheet_overheads_version_id", "cost_sheet_overheads",
                        ["version_id"])

    if "org_settings" not in existing:
        op.create_table(
            "org_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"),
                      nullable=False),
            sa.Column("key", sa.String(80), nullable=False),
            sa.Column("value", sa.String(255), nullable=True),
            sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("organization_id", "key", name="uq_org_setting_key"),
        )
        op.create_index("ix_org_settings_organization_id", "org_settings",
                        ["organization_id"])

    _ensure_finance(bind)
    _migrate_department_rates(bind)


def _ensure_finance(bind) -> None:
    deps = sa.table("wf_departments", sa.column("id", sa.Integer),
                    sa.column("name", sa.String), sa.column("flow_type", sa.String),
                    sa.column("is_active", sa.Boolean),
                    sa.column("can_start_change", sa.Boolean),
                    sa.column("sort_order", sa.Integer),
                    sa.column("created_at", sa.DateTime))
    if bind.execute(sa.select(deps.c.id).where(deps.c.name == "Finance")).scalar() is not None:
        return
    nxt = bind.execute(sa.select(sa.func.coalesce(sa.func.max(deps.c.sort_order), 0) + 1)).scalar()
    bind.execute(deps.insert().values(
        name="Finance", flow_type="info", is_active=True, can_start_change=False,
        sort_order=nxt, created_at=datetime.utcnow()))


def _migrate_department_rates(bind) -> None:
    if "department_rate" not in set(inspect(bind).get_table_names()):
        return
    versions = sa.table("cost_sheet_versions", sa.column("id", sa.Integer),
                        sa.column("organization_id", sa.Integer),
                        sa.column("version", sa.Integer), sa.column("status", sa.String),
                        sa.column("valid_from", sa.Date), sa.column("note", sa.Text),
                        sa.column("created_at", sa.DateTime),
                        sa.column("published_at", sa.DateTime))
    rates = sa.table("cost_sheet_rates", sa.column("version_id", sa.Integer),
                     sa.column("department_id", sa.Integer),
                     sa.column("plant_id", sa.Integer),
                     sa.column("hourly_rate", sa.Numeric),
                     sa.column("currency", sa.String), sa.column("min_factor", sa.Float),
                     sa.column("note", sa.Text))
    dr = sa.table("department_rate", sa.column("id", sa.Integer),
                  sa.column("department_id", sa.Integer), sa.column("plant_id", sa.Integer),
                  sa.column("hourly_rate", sa.Float), sa.column("min_factor", sa.Float),
                  sa.column("effective_from", sa.Date))
    plants = sa.table("plants", sa.column("id", sa.Integer),
                      sa.column("organization_id", sa.Integer))
    rows = bind.execute(
        sa.select(dr.c.id, dr.c.department_id, dr.c.plant_id, dr.c.hourly_rate,
                  dr.c.min_factor, dr.c.effective_from, plants.c.organization_id)
        .select_from(dr.join(plants, plants.c.id == dr.c.plant_id))).all()

    by_org: dict[int, dict[tuple[int, int], tuple]] = {}
    for r in rows:
        key = (r.department_id, r.plant_id)
        cur = by_org.setdefault(r.organization_id, {}).get(key)
        # the latest effective_from wins; ties go to the newest row
        rank = (r.effective_from or datetime.min.date(), r.id)
        if cur is None or rank > (cur.effective_from or datetime.min.date(), cur.id):
            by_org[r.organization_id][key] = r

    now = datetime.utcnow()
    for org_id, picked in by_org.items():
        if bind.execute(sa.select(versions.c.id).where(
                versions.c.organization_id == org_id)).first() is not None:
            continue   # the org already has a cost sheet: never overwrite it
        dates = [r.effective_from for r in rows
                 if r.organization_id == org_id and r.effective_from]
        valid_from = min(dates) if dates else now.date()
        bind.execute(versions.insert().values(
            organization_id=org_id, version=1, status="published", valid_from=valid_from,
            note="Migrated from the department rates", created_at=now, published_at=now))
        vid = bind.execute(sa.select(versions.c.id).where(
            versions.c.organization_id == org_id, versions.c.version == 1)).scalar()
        bind.execute(rates.insert(), [
            {"version_id": vid, "department_id": r.department_id, "plant_id": r.plant_id,
             "hourly_rate": r.hourly_rate, "currency": "EUR", "min_factor": r.min_factor,
             "note": None}
            for r in picked.values()])


def downgrade() -> None:
    existing = set(inspect(op.get_bind()).get_table_names())
    for t in TABLES:
        if t in existing:
            op.drop_table(t)
