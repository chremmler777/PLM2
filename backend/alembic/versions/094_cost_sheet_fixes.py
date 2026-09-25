"""094: cost sheet review fixes.

- plants.currency (ISO 4217, default EUR; USD where the location says USA).
  Finance confirms it on the cost sheet page.
- cost_sheet_versions.draft_lock + unique (organization_id, draft_lock):
  one open draft per org, enforced by the database.
- machine_class_id on machine and sampling rows (backfilled by name, a
  missing class is created) so a class can be renamed.
- cost_sheet_overheads.currency (per_hour overheads).
- Row currencies follow their plant (Toccoa rows become USD; values stay).
- The single version 092 migrated from department_rate is rebuilt as a
  chain: one published version per effective_from date at which the rates
  actually changed, so validity follows the real history. Only done while
  that version is still the org's only one and untouched.

Dialect-neutral (Core statements), same file on Postgres and SQLite.

Revision ID: 094
Revises: 093
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "094"
down_revision = "093"
branch_labels = None
depends_on = None

MIGRATED_NOTE = "Migrated from the department rates"

VERSIONS = sa.table("cost_sheet_versions", sa.column("id", sa.Integer),
                    sa.column("organization_id", sa.Integer),
                    sa.column("version", sa.Integer), sa.column("status", sa.String),
                    sa.column("valid_from", sa.Date), sa.column("note", sa.Text),
                    sa.column("created_at", sa.DateTime),
                    sa.column("published_at", sa.DateTime),
                    sa.column("draft_lock", sa.Integer))


def _cols(bind, table):
    return {c["name"] for c in inspect(bind).get_columns(table)}


def _is_usa(location, name, code) -> bool:
    """USD when the plant's location, name or code says USA."""
    text = " ".join(x for x in (location, name, code) if x).upper()
    words = text.replace(",", " ").replace("-", " ").split()
    return "US" in words or "USA" in words or "UNITED STATES" in text


def upgrade() -> None:
    bind = op.get_bind()

    # --- plants.currency -------------------------------------------------
    if "currency" not in _cols(bind, "plants"):
        op.add_column("plants", sa.Column("currency", sa.String(3), nullable=False,
                                          server_default="EUR"))
    plants = sa.table("plants", sa.column("id", sa.Integer),
                      sa.column("organization_id", sa.Integer),
                      sa.column("name", sa.String), sa.column("code", sa.String),
                      sa.column("location", sa.String), sa.column("currency", sa.String))
    plant_cur: dict[int, str] = {}
    for p in bind.execute(sa.select(plants.c.id, plants.c.name, plants.c.code,
                                    plants.c.location)).all():
        cur = "USD" if _is_usa(p.location, p.name, p.code) else "EUR"
        plant_cur[p.id] = cur
        bind.execute(plants.update().where(plants.c.id == p.id).values(currency=cur))

    # --- versions.draft_lock ---------------------------------------------
    if "draft_lock" not in _cols(bind, "cost_sheet_versions"):
        op.add_column("cost_sheet_versions", sa.Column("draft_lock", sa.Integer(), nullable=True))
    versions = VERSIONS
    bind.execute(versions.update().where(versions.c.status == "draft").values(draft_lock=1))
    existing_ix = {ix["name"] for ix in inspect(bind).get_indexes("cost_sheet_versions")}
    if "uq_cost_sheet_one_draft" not in existing_ix:
        op.create_index("uq_cost_sheet_one_draft", "cost_sheet_versions",
                        ["organization_id", "draft_lock"], unique=True)

    # --- machine_class_id ------------------------------------------------
    classes = sa.table("cost_sheet_machine_classes", sa.column("id", sa.Integer),
                       sa.column("organization_id", sa.Integer), sa.column("name", sa.String),
                       sa.column("sort_order", sa.Integer), sa.column("is_active", sa.Boolean))
    for table in ("cost_sheet_machine_rates", "cost_sheet_sampling_rates"):
        if "machine_class_id" not in _cols(bind, table):
            op.add_column(table, sa.Column(
                "machine_class_id", sa.Integer(),
                sa.ForeignKey("cost_sheet_machine_classes.id"), nullable=True))
        rows_t = sa.table(table, sa.column("id", sa.Integer), sa.column("version_id", sa.Integer),
                          sa.column("machine_class", sa.String),
                          sa.column("machine_class_id", sa.Integer))
        rows = bind.execute(
            sa.select(rows_t.c.id, rows_t.c.machine_class, versions.c.organization_id)
            .select_from(rows_t.join(versions, versions.c.id == rows_t.c.version_id))
            .where(rows_t.c.machine_class_id.is_(None))).all()
        for r in rows:
            name = (r.machine_class or "").strip()
            cid = bind.execute(sa.select(classes.c.id).where(
                classes.c.organization_id == r.organization_id,
                sa.func.lower(classes.c.name) == name.lower())).scalar()
            if cid is None:
                bind.execute(classes.insert().values(organization_id=r.organization_id,
                                                     name=name, sort_order=0, is_active=True))
                cid = bind.execute(sa.select(classes.c.id).where(
                    classes.c.organization_id == r.organization_id,
                    classes.c.name == name)).scalar()
            bind.execute(rows_t.update().where(rows_t.c.id == r.id).values(machine_class_id=cid))

    # --- overheads.currency ----------------------------------------------
    if "currency" not in _cols(bind, "cost_sheet_overheads"):
        op.add_column("cost_sheet_overheads", sa.Column("currency", sa.String(3), nullable=True))
    oh = sa.table("cost_sheet_overheads", sa.column("id", sa.Integer),
                  sa.column("plant_id", sa.Integer), sa.column("kind", sa.String),
                  sa.column("currency", sa.String))
    for r in bind.execute(sa.select(oh.c.id, oh.c.plant_id).where(
            oh.c.kind == "per_hour", oh.c.currency.is_(None))).all():
        bind.execute(oh.update().where(oh.c.id == r.id).values(
            currency=plant_cur.get(r.plant_id, "EUR")))

    # --- row currencies follow the plant -----------------------------------
    for table in ("cost_sheet_rates", "cost_sheet_machine_rates", "cost_sheet_sampling_rates"):
        t = sa.table(table, sa.column("plant_id", sa.Integer), sa.column("currency", sa.String))
        for pid, cur in plant_cur.items():
            bind.execute(t.update().where(t.c.plant_id == pid).values(currency=cur))

    _rebuild_migrated_chain(bind, versions, plant_cur)


def _rebuild_migrated_chain(bind, versions, plant_cur) -> None:
    if "department_rate" not in set(inspect(bind).get_table_names()):
        return
    rates = sa.table("cost_sheet_rates", sa.column("version_id", sa.Integer),
                     sa.column("department_id", sa.Integer), sa.column("position", sa.String),
                     sa.column("plant_id", sa.Integer), sa.column("hourly_rate", sa.Numeric),
                     sa.column("currency", sa.String), sa.column("min_factor", sa.Float),
                     sa.column("note", sa.Text))
    dr = sa.table("department_rate", sa.column("id", sa.Integer),
                  sa.column("department_id", sa.Integer), sa.column("plant_id", sa.Integer),
                  sa.column("hourly_rate", sa.Float), sa.column("min_factor", sa.Float),
                  sa.column("effective_from", sa.Date))
    plants = sa.table("plants", sa.column("id", sa.Integer),
                      sa.column("organization_id", sa.Integer))
    history = bind.execute(
        sa.select(dr.c.id, dr.c.department_id, dr.c.plant_id, dr.c.hourly_rate,
                  dr.c.min_factor, dr.c.effective_from, plants.c.organization_id)
        .select_from(dr.join(plants, plants.c.id == dr.c.plant_id))
        .order_by(dr.c.effective_from, dr.c.id)).all()
    orgs = sorted({r.organization_id for r in history})
    now = datetime.utcnow()
    for org_id in orgs:
        existing = bind.execute(sa.select(versions.c.id, versions.c.note, versions.c.status)
                                .where(versions.c.organization_id == org_id)).all()
        # Rebuild only the untouched 092 result: exactly one published
        # version carrying the migration note. Anything else is Finance's.
        if len(existing) != 1 or existing[0].note != MIGRATED_NOTE \
                or existing[0].status != "published":
            continue
        old_id = existing[0].id
        bind.execute(rates.delete().where(rates.c.version_id == old_id))
        bind.execute(versions.delete().where(versions.c.id == old_id))

        state: dict[tuple, tuple] = {}
        published: dict[tuple, tuple] = {}
        number = 0
        rows = [r for r in history if r.organization_id == org_id]
        dates = sorted({r.effective_from for r in rows if r.effective_from})
        undated = [r for r in rows if not r.effective_from]
        for r in undated:        # no date: part of the first version
            state[(r.department_id, r.plant_id)] = (float(r.hourly_rate), r.min_factor)
        for d in dates:
            for r in rows:
                if r.effective_from == d:
                    state[(r.department_id, r.plant_id)] = (float(r.hourly_rate), r.min_factor)
            if state == published:
                continue          # a re-entry of the same numbers is no new version
            number += 1
            bind.execute(versions.insert().values(
                organization_id=org_id, version=number, status="published", valid_from=d,
                note=MIGRATED_NOTE + (f" (as of {d.isoformat()})" if number > 1 else ""),
                created_at=now, published_at=now, draft_lock=None))
            vid = bind.execute(sa.select(versions.c.id).where(
                versions.c.organization_id == org_id, versions.c.version == number)).scalar()
            bind.execute(rates.insert(), [
                {"version_id": vid, "department_id": dep, "position": None, "plant_id": pid,
                 "hourly_rate": rate, "currency": plant_cur.get(pid, "EUR"),
                 "min_factor": factor, "note": None}
                for (dep, pid), (rate, factor) in sorted(state.items())])
            published = dict(state)


def downgrade() -> None:
    bind = op.get_bind()
    if "currency" in _cols(bind, "cost_sheet_overheads"):
        op.drop_column("cost_sheet_overheads", "currency")
    for table in ("cost_sheet_sampling_rates", "cost_sheet_machine_rates"):
        if "machine_class_id" in _cols(bind, table):
            op.drop_column(table, "machine_class_id")
    existing_ix = {ix["name"] for ix in inspect(bind).get_indexes("cost_sheet_versions")}
    if "uq_cost_sheet_one_draft" in existing_ix:
        op.drop_index("uq_cost_sheet_one_draft", table_name="cost_sheet_versions")
    if "draft_lock" in _cols(bind, "cost_sheet_versions"):
        op.drop_column("cost_sheet_versions", "draft_lock")
    if "currency" in _cols(bind, "plants"):
        op.drop_column("plants", "currency")
