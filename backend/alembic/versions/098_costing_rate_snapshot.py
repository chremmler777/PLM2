"""098: costing priced from the cost sheet (spec §15 phase 2).

- costing_positions: the rate snapshot a line was priced with
  (rate, currency, rate_source cost_sheet|department_rate,
  cost_sheet_version_id + cost_sheet_version, rate_match, rate_on,
  rate_detail JSON), the labour position that picked the rate
  (labour_position), and the inputs of the new kinds machine_time
  (hours x machine class rate: machine_class_id) and sampling
  (trials x sampling price of the class: trials).
- assessment_cost_line: currency, cost_sheet_version_id, rate_source
  (rate_snapshot already exists).
- change_requests.machine_class_id: the change's machine class (default
  from the impacted tool's tonnage; set in costing).
- implementation_bookings: labour_position, machine_class_id,
  machine_hours (P&L actuals price them on the booking date).
- Data fix for 094: an organisation whose department_rate rows had no
  effective_from lost its migrated version there (094 deleted 092's single
  version and built one per dated effective_from; with no dates, none).
  Here: an org with department_rate rows and no cost sheet version at all
  gets version 1, published, valid from the earliest effective_from over ALL
  of the org's rows (so every booking since the first rate is priced;
  2020-01-01 when no row carries a date), with the latest row per
  department x plant, in the currency of the plant.
  Safe on a DB where 094 went fine: orgs that have any version are skipped.

Dialect-neutral; FK columns via batch mode (SQLite recreates the table).

Downgrade drops the columns. The version created by the data fix stays
(it is Finance's data from then on).

Revision ID: 098
Revises: 097
"""
from datetime import date, datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "098"
down_revision = "097"
branch_labels = None
depends_on = None

MIGRATED_NOTE = "Migrated from the department rates"
UNDATED_VALID_FROM = date(2020, 1, 1)


def _cols(bind, table):
    return {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    if "costing_positions" in tables:
        have = _cols(bind, "costing_positions")
        plain = [
            ("labour_position", sa.String(80)),
            ("trials", sa.Integer()),
            ("rate", sa.Numeric(12, 2)),
            ("currency", sa.String(3)),
            ("rate_source", sa.String(20)),
            ("cost_sheet_version", sa.Integer()),
            ("rate_match", sa.String(40)),
            ("rate_on", sa.Date()),
            ("rate_detail", sa.JSON()),
        ]
        for name, typ in plain:
            if name not in have:
                op.add_column("costing_positions", sa.Column(name, typ, nullable=True))
        fks = [c for c in ("machine_class_id", "cost_sheet_version_id") if c not in have]
        if fks:
            with op.batch_alter_table("costing_positions") as batch:
                if "machine_class_id" in fks:
                    batch.add_column(sa.Column("machine_class_id", sa.Integer(), nullable=True))
                    batch.create_foreign_key("fk_costing_positions_machine_class",
                                             "cost_sheet_machine_classes",
                                             ["machine_class_id"], ["id"])
                if "cost_sheet_version_id" in fks:
                    batch.add_column(sa.Column("cost_sheet_version_id", sa.Integer(),
                                               nullable=True))
                    batch.create_foreign_key("fk_costing_positions_cs_version",
                                             "cost_sheet_versions",
                                             ["cost_sheet_version_id"], ["id"])

    if "assessment_cost_line" in tables:
        have = _cols(bind, "assessment_cost_line")
        for name, typ in (("currency", sa.String(3)), ("rate_source", sa.String(20))):
            if name not in have:
                op.add_column("assessment_cost_line", sa.Column(name, typ, nullable=True))
        if "cost_sheet_version_id" not in have:
            with op.batch_alter_table("assessment_cost_line") as batch:
                batch.add_column(sa.Column("cost_sheet_version_id", sa.Integer(), nullable=True))
                batch.create_foreign_key("fk_cost_line_cs_version", "cost_sheet_versions",
                                         ["cost_sheet_version_id"], ["id"])

    if "change_requests" in tables and "machine_class_id" not in _cols(bind, "change_requests"):
        with op.batch_alter_table("change_requests") as batch:
            batch.add_column(sa.Column("machine_class_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_change_requests_machine_class",
                                     "cost_sheet_machine_classes",
                                     ["machine_class_id"], ["id"])

    if "implementation_bookings" in tables:
        have = _cols(bind, "implementation_bookings")
        for name, typ in (("labour_position", sa.String(80)),
                          ("machine_hours", sa.Numeric(8, 2))):
            if name not in have:
                op.add_column("implementation_bookings", sa.Column(name, typ, nullable=True))
        if "machine_class_id" not in have:
            with op.batch_alter_table("implementation_bookings") as batch:
                batch.add_column(sa.Column("machine_class_id", sa.Integer(), nullable=True))
                batch.create_foreign_key("fk_impl_bookings_machine_class",
                                         "cost_sheet_machine_classes",
                                         ["machine_class_id"], ["id"])

    _version_for_undated_orgs(bind)


def _version_for_undated_orgs(bind) -> None:
    tables = set(inspect(bind).get_table_names())
    if not {"department_rate", "cost_sheet_versions", "cost_sheet_rates"} <= tables:
        return
    versions = sa.table("cost_sheet_versions", sa.column("id", sa.Integer),
                        sa.column("organization_id", sa.Integer),
                        sa.column("version", sa.Integer), sa.column("status", sa.String),
                        sa.column("valid_from", sa.Date), sa.column("note", sa.Text),
                        sa.column("created_at", sa.DateTime),
                        sa.column("published_at", sa.DateTime))
    rates = sa.table("cost_sheet_rates", sa.column("version_id", sa.Integer),
                     sa.column("department_id", sa.Integer), sa.column("position", sa.String),
                     sa.column("plant_id", sa.Integer), sa.column("hourly_rate", sa.Numeric),
                     sa.column("currency", sa.String), sa.column("min_factor", sa.Float),
                     sa.column("note", sa.Text))
    dr = sa.table("department_rate", sa.column("id", sa.Integer),
                  sa.column("department_id", sa.Integer), sa.column("plant_id", sa.Integer),
                  sa.column("hourly_rate", sa.Float), sa.column("min_factor", sa.Float),
                  sa.column("effective_from", sa.Date))
    plant_cols = _cols(bind, "plants")
    plants = sa.table("plants", sa.column("id", sa.Integer),
                      sa.column("organization_id", sa.Integer),
                      *([sa.column("currency", sa.String)] if "currency" in plant_cols else []))
    rows = bind.execute(
        sa.select(dr.c.id, dr.c.department_id, dr.c.plant_id, dr.c.hourly_rate,
                  dr.c.min_factor, dr.c.effective_from, plants.c.organization_id)
        .select_from(dr.join(plants, plants.c.id == dr.c.plant_id))).all()
    plant_cur = ({pid: cur for pid, cur in bind.execute(
        sa.select(plants.c.id, plants.c.currency)).all()}
        if "currency" in plant_cols else {})
    now = datetime.utcnow()
    for org_id in sorted({r.organization_id for r in rows}):
        if bind.execute(sa.select(versions.c.id).where(
                versions.c.organization_id == org_id)).first() is not None:
            continue          # has a cost sheet: Finance's (or 094's), untouched
        picked: dict[tuple, object] = {}
        for r in rows:
            if r.organization_id != org_id:
                continue
            key = (r.department_id, r.plant_id)
            rank = (r.effective_from or date.min, r.id)
            cur = picked.get(key)
            if cur is None or rank > (cur.effective_from or date.min, cur.id):
                picked[key] = r
        # valid from the org's EARLIEST rate, not the earliest of the rows
        # kept: a rate superseded later still priced the time before it.
        dates = [r.effective_from for r in rows
                 if r.organization_id == org_id and r.effective_from]
        valid_from = min(dates) if dates else UNDATED_VALID_FROM
        bind.execute(versions.insert().values(
            organization_id=org_id, version=1, status="published", valid_from=valid_from,
            note=MIGRATED_NOTE, created_at=now, published_at=now))
        vid = bind.execute(sa.select(versions.c.id).where(
            versions.c.organization_id == org_id, versions.c.version == 1)).scalar()
        bind.execute(rates.insert(), [
            {"version_id": vid, "department_id": r.department_id, "position": None,
             "plant_id": r.plant_id, "hourly_rate": r.hourly_rate,
             "currency": plant_cur.get(r.plant_id) or "EUR",
             "min_factor": r.min_factor, "note": None}
            for _, r in sorted(picked.items())])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    def drop(table, plain, fks):
        if table not in tables:
            return
        have = _cols(bind, table)
        for name in plain:
            if name in have:
                op.drop_column(table, name)
        present = [(c, n) for c, n in fks if c in have]
        if present:
            with op.batch_alter_table(table) as batch:
                for col, fk in present:
                    batch.drop_constraint(fk, type_="foreignkey")
                    batch.drop_column(col)

    drop("implementation_bookings", ("labour_position", "machine_hours"),
         (("machine_class_id", "fk_impl_bookings_machine_class"),))
    drop("change_requests", (), (("machine_class_id", "fk_change_requests_machine_class"),))
    drop("assessment_cost_line", ("currency", "rate_source"),
         (("cost_sheet_version_id", "fk_cost_line_cs_version"),))
    drop("costing_positions",
         ("labour_position", "trials", "rate", "currency", "rate_source",
          "cost_sheet_version", "rate_match", "rate_on", "rate_detail"),
         (("machine_class_id", "fk_costing_positions_machine_class"),
          ("cost_sheet_version_id", "fk_costing_positions_cs_version")))
