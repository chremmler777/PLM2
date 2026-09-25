"""101: currency on actual costs; one standing effort row per department;
Toccoa in USD.

- plants.currency: the Toccoa plant is relabelled USD. 094's whole-word
  US/USA match on name/location/code misses a plant whose location reads
  "Toccoa, GA". Matched on the name or location containing "Toccoa" (any
  case); idempotent; a relabel only, no rate is converted (Finance confirms
  the numbers). Runs first, so the actual costs below backfill in USD there.
  The downgrade leaves the currency as it is.

- change_actual_costs.currency: the currency the amount is in. Backfilled
  with the change's costing currency (the costing plant's: the change's only
  affected plant, else its project's plant; EUR when the plant names none),
  which is what every existing row was entered in. New rows get it from the
  service (ActualCostService.add).
- costing_positions: the standing answers (internal_effort, support_effort)
  exist once per change, department and kind. A double save (blur + click)
  left duplicates (final walk P2-1). Existing duplicates are merged into the
  oldest row, which takes the values of the most recently updated one (what
  the user typed last); the others are deleted with their offers (standing
  rows carry none). Then a partial unique index keeps it that way.

Dialect-neutral: plain SQL that runs on Postgres and on SQLite.

Revision ID: 101
Revises: 100
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "101"
down_revision = "100"
branch_labels = None
depends_on = None

STANDING = ("internal_effort", "support_effort")
INDEX = "uq_costing_positions_standing"
WHERE = "kind IN ('internal_effort', 'support_effort')"
# Fields a merged standing row takes from its most recently updated duplicate.
MERGED_FIELDS = ("label", "hours", "est_cost", "notes", "labour_position",
                 "tag", "lead_time_days", "lead_time_unit")


def _cols(bind, table):
    return {c["name"] for c in inspect(bind).get_columns(table)}


def _toccoa_usd(bind) -> None:
    if "currency" not in _cols(bind, "plants"):
        return
    op.execute("""
        UPDATE plants SET currency = 'USD'
         WHERE (LOWER(COALESCE(name, '')) LIKE '%toccoa%'
                OR LOWER(COALESCE(location, '')) LIKE '%toccoa%')
           AND (currency IS NULL OR currency <> 'USD')
    """)


def _backfill_currency(bind) -> None:
    op.execute("""
        UPDATE change_actual_costs SET currency = COALESCE((
            SELECT p.currency FROM plants p WHERE p.id = COALESCE(
                (SELECT MIN(cap.plant_id) FROM change_affected_plants cap
                  WHERE cap.change_id = change_actual_costs.change_id
                 HAVING COUNT(*) = 1),
                (SELECT pr.plant_id FROM projects pr
                   JOIN change_requests cr ON cr.project_id = pr.id
                  WHERE cr.id = change_actual_costs.change_id))
        ), 'EUR')
        WHERE currency IS NULL
    """)


def _merge_standing_duplicates(bind) -> None:
    cols = _cols(bind, "costing_positions")
    fields = [f for f in MERGED_FIELDS if f in cols]
    groups = bind.execute(sa.text(
        "SELECT change_id, department_id, kind FROM costing_positions "
        f"WHERE {WHERE} GROUP BY change_id, department_id, kind "
        "HAVING COUNT(*) > 1")).all()
    for change_id, department_id, kind in groups:
        rows = bind.execute(sa.text(
            "SELECT id, updated_at FROM costing_positions "
            "WHERE change_id = :c AND department_id = :d AND kind = :k "
            "ORDER BY id"), {"c": change_id, "d": department_id, "k": kind}).all()
        keep = rows[0][0]
        latest = max(rows, key=lambda r: (r[1] is not None, r[1], r[0]))[0]
        if latest != keep and fields:
            sets = ", ".join(
                f"{f} = (SELECT {f} FROM costing_positions WHERE id = :latest)"
                for f in fields)
            bind.execute(sa.text(
                f"UPDATE costing_positions SET {sets} WHERE id = :keep"),
                {"latest": latest, "keep": keep})
        for rid, _ in rows[1:]:
            bind.execute(sa.text(
                "DELETE FROM costing_offers WHERE position_id = :p"), {"p": rid})
            bind.execute(sa.text(
                "DELETE FROM costing_positions WHERE id = :p"), {"p": rid})


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "plants" in tables:
        _toccoa_usd(bind)
    if "change_actual_costs" in tables:
        if "currency" not in _cols(bind, "change_actual_costs"):
            op.add_column("change_actual_costs",
                          sa.Column("currency", sa.String(3), nullable=True))
        _backfill_currency(bind)
    if "costing_positions" in tables:
        _merge_standing_duplicates(bind)
        names = {i["name"] for i in inspect(bind).get_indexes("costing_positions")}
        if INDEX not in names:
            op.create_index(
                INDEX, "costing_positions", ["change_id", "department_id", "kind"],
                unique=True, postgresql_where=sa.text(WHERE),
                sqlite_where=sa.text(WHERE))


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "costing_positions" in tables:
        names = {i["name"] for i in inspect(bind).get_indexes("costing_positions")}
        if INDEX in names:
            op.drop_index(INDEX, table_name="costing_positions")
    if "change_actual_costs" in tables and \
            "currency" in _cols(bind, "change_actual_costs"):
        with op.batch_alter_table("change_actual_costs") as batch:
            batch.drop_column("currency")
