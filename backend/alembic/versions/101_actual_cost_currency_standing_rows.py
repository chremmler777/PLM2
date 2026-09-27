"""101: currency on actual costs; one standing effort row per department;
Toccoa in USD.

- plants.currency: the Toccoa plant is relabelled USD. 094's whole-word
  US/USA match on name/location/code misses a plant whose location reads
  "Toccoa, GA". Matched on "toccoa" as a whole word (any case) in the name
  or location; idempotent; a relabel only, no rate is converted (Finance
  confirms the numbers). Runs first, so the actual costs below backfill in
  USD there. The downgrade leaves the currency as it is.

- change_actual_costs.currency: the currency the amount is in. Backfilled
  with the change's costing currency (the costing plant's: the change's only
  affected plant, else its project's plant; EUR when the plant names none,
  NULL or '', as cost_sheet_service.plant_currency does), which is what every
  existing row was entered in. New rows get it from the service
  (ActualCostService.add).
- costing_positions: the standing answers (internal_effort, support_effort)
  exist once per change, department and kind. A double save (blur + click)
  left duplicates (final walk P2-1). Of each duplicate group the most
  recently updated row (updated_at, else the highest id) is kept whole: what
  the user typed last together with the price snapshot it was priced with
  (rate, currencies, cost sheet version, ...), never a mix of two rows. The
  others' references are re-pointed to it (costing_offers.position_id, the
  only FK; change_plan_tasks.source_position_id, informational) and they are
  deleted. Then a partial unique index keeps it that way.

Dialect-neutral: plain SQL that runs on Postgres and on SQLite (also SQLite
< 3.39: no aggregate HAVING without GROUP BY).

Revision ID: 101
Revises: 100
"""
import re

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
TOCCOA = re.compile(r"\btoccoa\b", re.IGNORECASE)


def _cols(bind, table):
    return {c["name"] for c in inspect(bind).get_columns(table)}


def _toccoa_usd(bind) -> None:
    # Open question for the org owner: the match is not scoped by
    # organization_id, so a second organization's plant in Toccoa would be
    # relabelled too. Today there is one Toccoa plant; revisit if the
    # tenancy grows.
    if "currency" not in _cols(bind, "plants"):
        return
    rows = bind.execute(sa.text(
        "SELECT id, name, location, currency FROM plants")).all()
    for pid, name, location, currency in rows:
        if currency == "USD":
            continue
        if TOCCOA.search(name or "") or TOCCOA.search(location or ""):
            bind.execute(sa.text(
                "UPDATE plants SET currency = 'USD' WHERE id = :p"), {"p": pid})


def _backfill_currency(bind) -> None:
    op.execute("""
        UPDATE change_actual_costs SET currency = COALESCE((
            SELECT NULLIF(p.currency, '') FROM plants p WHERE p.id = COALESCE(
                (SELECT CASE WHEN COUNT(*) = 1 THEN MIN(cap.plant_id) END
                   FROM change_affected_plants cap
                  WHERE cap.change_id = change_actual_costs.change_id),
                (SELECT pr.plant_id FROM projects pr
                   JOIN change_requests cr ON cr.project_id = pr.id
                  WHERE cr.id = change_actual_costs.change_id))
        ), 'EUR')
        WHERE currency IS NULL
    """)


def _merge_standing_duplicates(bind) -> None:
    tables = set(inspect(bind).get_table_names())
    plan_ref = "change_plan_tasks" in tables and \
        "source_position_id" in _cols(bind, "change_plan_tasks")
    groups = bind.execute(sa.text(
        "SELECT change_id, department_id, kind FROM costing_positions "
        f"WHERE {WHERE} GROUP BY change_id, department_id, kind "
        "HAVING COUNT(*) > 1")).all()
    for change_id, department_id, kind in groups:
        rows = bind.execute(sa.text(
            "SELECT id, updated_at FROM costing_positions "
            "WHERE change_id = :c AND department_id = :d AND kind = :k"),
            {"c": change_id, "d": department_id, "k": kind}).all()
        keep = max(rows, key=lambda r: (r[1] is not None, r[1], r[0]))[0]
        for rid, _ in rows:
            if rid == keep:
                continue
            ref = {"p": rid, "keep": keep}
            if "costing_offers" in tables:
                bind.execute(sa.text(
                    "UPDATE costing_offers SET position_id = :keep "
                    "WHERE position_id = :p"), ref)
            if plan_ref:
                bind.execute(sa.text(
                    "UPDATE change_plan_tasks SET source_position_id = :keep "
                    "WHERE source_position_id = :p"), ref)
            bind.execute(sa.text(
                "DELETE FROM costing_positions WHERE id = :p"), ref)


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
