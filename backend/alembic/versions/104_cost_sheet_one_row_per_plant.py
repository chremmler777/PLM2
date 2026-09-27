"""104: the cost sheet holds exactly one rate per department per plant.

- cost_sheet_rates: duplicates of (version, department, plant) are merged in
  every version, plant NULL (all plants) counting as a plant of its own. The
  department default row (position NULL) is kept when there is one, else the
  most recent row (highest id); the kept row loses its position. Positions
  (sub-rates of a department) are gone: a costing line that names a labour
  position is priced from its department's row.
- cost_sheet_rates.hourly_rate becomes nullable: an empty rate means "no rate
  yet" (costing shows "No rate in the cost sheet"), it is never a number.
- Unique index uq_cost_sheet_rate_dept_plant on
  (version_id, department_id, coalesce(plant_id, 0)), so plant NULL collides
  with plant NULL too.
- The open draft (if any) of each organization gets a row with an EMPTY rate
  for every active department and active plant that has no row yet (neither
  for that plant nor for all plants). Every active department can be routed
  on an ECR as R/A/S/C (a routing deviation offers each one), so each needs a
  rate. Published versions stay frozen and are not seeded.

Dialect-neutral (Core statements; batch mode for the nullability change, so
SQLite recreates the table). Repeatable.

Downgrade drops the index, deletes the rows without a rate (they carry no
number) and makes hourly_rate NOT NULL again. The merged duplicates and the
dropped positions are not restored.

Revision ID: 104
Revises: 103
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "104"
down_revision = "103"
branch_labels = None
depends_on = None

INDEX = "uq_cost_sheet_rate_dept_plant"

RATES = sa.table("cost_sheet_rates", sa.column("id", sa.Integer),
                 sa.column("version_id", sa.Integer), sa.column("department_id", sa.Integer),
                 sa.column("position", sa.String), sa.column("plant_id", sa.Integer),
                 sa.column("hourly_rate", sa.Numeric), sa.column("currency", sa.String))


def _has_index(bind) -> bool:
    """Asked from the catalog: SQLite's reflection skips expression indexes."""
    if bind.dialect.name == "sqlite":
        q = sa.text("SELECT name FROM sqlite_master WHERE type = 'index' AND name = :n")
    else:
        q = sa.text("SELECT indexname FROM pg_indexes WHERE indexname = :n")
    return bind.execute(q, {"n": INDEX}).first() is not None


def _rate_nullable(bind) -> bool:
    col = next(c for c in inspect(bind).get_columns("cost_sheet_rates")
               if c["name"] == "hourly_rate")
    return bool(col["nullable"])


def _merge_duplicates(bind) -> None:
    rows = bind.execute(sa.select(RATES.c.id, RATES.c.version_id, RATES.c.department_id,
                                  RATES.c.plant_id, RATES.c.position)
                        .order_by(RATES.c.id)).all()
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((r.version_id, r.department_id, r.plant_id), []).append(r)
    for group in groups.values():
        defaults = [r for r in group if r.position is None]
        keep = max(defaults or group, key=lambda r: r.id)
        drop = [r.id for r in group if r.id != keep.id]
        if drop:
            bind.execute(RATES.delete().where(RATES.c.id.in_(drop)))
        if keep.position is not None:
            bind.execute(RATES.update().where(RATES.c.id == keep.id).values(position=None))


def _seed_open_drafts(bind) -> None:
    versions = sa.table("cost_sheet_versions", sa.column("id", sa.Integer),
                        sa.column("organization_id", sa.Integer),
                        sa.column("status", sa.String))
    deps = sa.table("wf_departments", sa.column("id", sa.Integer),
                    sa.column("is_active", sa.Boolean), sa.column("sort_order", sa.Integer))
    plant_cols = {c["name"] for c in inspect(bind).get_columns("plants")}
    plants = sa.table("plants", sa.column("id", sa.Integer),
                      sa.column("organization_id", sa.Integer),
                      sa.column("is_active", sa.Boolean),
                      *([sa.column("currency", sa.String)] if "currency" in plant_cols else []))
    dep_ids = [d for (d,) in bind.execute(
        sa.select(deps.c.id).where(deps.c.is_active == sa.true())
        .order_by(deps.c.sort_order, deps.c.id)).all()]
    for v in bind.execute(sa.select(versions.c.id, versions.c.organization_id)
                          .where(versions.c.status == "draft")).all():
        org_plants = bind.execute(
            sa.select(plants.c.id, *([plants.c.currency] if "currency" in plant_cols else []))
            .where(plants.c.organization_id == v.organization_id,
                   plants.c.is_active == sa.true())
            .order_by(plants.c.id)).all()
        have = {(r.department_id, r.plant_id) for r in bind.execute(
            sa.select(RATES.c.department_id, RATES.c.plant_id)
            .where(RATES.c.version_id == v.id)).all()}
        new = []
        for dep in dep_ids:
            if (dep, None) in have:
                continue          # an all-plants row covers every plant
            for p in org_plants:
                if (dep, p.id) not in have:
                    cur = (p.currency if "currency" in plant_cols else None) or "EUR"
                    new.append({"version_id": v.id, "department_id": dep, "position": None,
                                "plant_id": p.id, "hourly_rate": None, "currency": cur})
        if new:
            bind.execute(RATES.insert(), new)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "cost_sheet_rates" not in tables:
        return
    _merge_duplicates(bind)
    if not _rate_nullable(bind):
        if _has_index(bind):
            op.drop_index(INDEX, table_name="cost_sheet_rates")
        with op.batch_alter_table("cost_sheet_rates") as batch:
            batch.alter_column("hourly_rate", existing_type=sa.Numeric(10, 2), nullable=True)
    if not _has_index(bind):
        op.create_index(INDEX, "cost_sheet_rates",
                        ["version_id", "department_id", sa.text("coalesce(plant_id, 0)")],
                        unique=True)
    if {"cost_sheet_versions", "wf_departments", "plants"} <= tables:
        _seed_open_drafts(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if "cost_sheet_rates" not in set(inspect(bind).get_table_names()):
        return
    if _has_index(bind):
        op.drop_index(INDEX, table_name="cost_sheet_rates")
    bind.execute(RATES.delete().where(RATES.c.hourly_rate.is_(None)))
    if _rate_nullable(bind):
        with op.batch_alter_table("cost_sheet_rates") as batch:
            batch.alter_column("hourly_rate", existing_type=sa.Numeric(10, 2), nullable=False)
