"""106: plants with two currencies and the exchange rate of a cost sheet version.

- plants.local_currency: a plant's second currency next to plants.currency
  (the quote currency, which costing and offers use). Silao quotes in USD
  and pays in MXN; Toccoa is USD only, Weissenburg EUR only (NULL).
- cost_sheet_versions.fx_rates (JSON): the exchange rates a version uses,
  {"USD/MXN": "17.30"} = 1 USD is 17.30 MXN, stored as decimal text so the
  number typed is the number kept. Entered on the draft by Sales or Finance
  and frozen on publish with the rates: an old change keeps its version's
  exchange rate like it keeps its rates.
- cost_sheet_rates and cost_sheet_machine_rates: entered_rate +
  entered_currency, the rate exactly as typed and its currency when it was
  typed in the plant's local currency. hourly_rate stays the rate in the
  row's currency (the quote currency) and is computed from the entered value
  and the version's exchange rate, so a round trip never drifts.
- Data: a plant named, coded or located Silao (the MX plant) gets quote
  currency USD and local currency MXN (the user's decision), once: a plant
  that already has a local currency is left alone. Empty rows of an open
  draft at that plant follow it to USD. Published versions keep their rows
  and currencies (frozen): the next version carries Silao's USD rates.

Dialect-neutral (Core statements; batch mode for the drops on SQLite).
Repeatable.

Downgrade drops the columns. Silao's quote currency stays USD.

Revision ID: 106
Revises: 105
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "106"
down_revision = "105"
branch_labels = None
depends_on = None

ROW_TABLES = ("cost_sheet_rates", "cost_sheet_machine_rates")


def _cols(bind, table):
    return {c["name"] for c in inspect(bind).get_columns(table)}


def _is_silao(name, code, location) -> bool:
    words = " ".join(x for x in (name, code, location) if x).upper() \
        .replace(",", " ").replace("-", " ").split()
    return "SILAO" in words or (code or "").strip().upper() == "SIL"


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "plants" in tables and "local_currency" not in _cols(bind, "plants"):
        op.add_column("plants", sa.Column("local_currency", sa.String(3), nullable=True))
    if ("cost_sheet_versions" in tables
            and "fx_rates" not in _cols(bind, "cost_sheet_versions")):
        op.add_column("cost_sheet_versions", sa.Column("fx_rates", sa.JSON(), nullable=True))
    for table in ROW_TABLES:
        if table not in tables:
            continue
        have = _cols(bind, table)
        if "entered_rate" not in have:
            op.add_column(table, sa.Column("entered_rate", sa.Numeric(12, 2), nullable=True))
        if "entered_currency" not in have:
            op.add_column(table, sa.Column("entered_currency", sa.String(3), nullable=True))
    if "plants" in tables:
        _silao(bind, tables)


def _silao(bind, tables) -> None:
    plants = sa.table("plants", sa.column("id", sa.Integer), sa.column("name", sa.String),
                      sa.column("code", sa.String), sa.column("location", sa.String),
                      sa.column("currency", sa.String),
                      sa.column("local_currency", sa.String))
    ids = [p.id for p in bind.execute(
        sa.select(plants.c.id, plants.c.name, plants.c.code, plants.c.location)
        .where(plants.c.local_currency.is_(None))).all()
        if _is_silao(p.name, p.code, p.location)]
    if not ids:
        return
    bind.execute(plants.update().where(plants.c.id.in_(ids))
                 .values(currency="USD", local_currency="MXN"))
    if not {"cost_sheet_rates", "cost_sheet_versions"} <= tables:
        return
    versions = sa.table("cost_sheet_versions", sa.column("id", sa.Integer),
                        sa.column("status", sa.String))
    rates = sa.table("cost_sheet_rates", sa.column("version_id", sa.Integer),
                     sa.column("plant_id", sa.Integer), sa.column("hourly_rate", sa.Numeric),
                     sa.column("currency", sa.String))
    drafts = [v for (v,) in bind.execute(
        sa.select(versions.c.id).where(versions.c.status == "draft")).all()]
    if drafts:
        bind.execute(rates.update().where(
            rates.c.version_id.in_(drafts), rates.c.plant_id.in_(ids),
            rates.c.hourly_rate.is_(None)).values(currency="USD"))


# 104's unique index on cost_sheet_rates: SQLite's batch mode rebuilds the
# table from reflection, which skips expression indexes, so it is dropped
# before and created again after.
RATE_INDEX = "uq_cost_sheet_rate_dept_plant"


def _has_rate_index(bind) -> bool:
    if bind.dialect.name == "sqlite":
        q = sa.text("SELECT name FROM sqlite_master WHERE type = 'index' AND name = :n")
    else:
        q = sa.text("SELECT indexname FROM pg_indexes WHERE indexname = :n")
    return bind.execute(q, {"n": RATE_INDEX}).first() is not None


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    for table in ROW_TABLES:
        if table not in tables:
            continue
        have = [c for c in ("entered_rate", "entered_currency") if c in _cols(bind, table)]
        if not have:
            continue
        index = table == "cost_sheet_rates" and _has_rate_index(bind)
        if index:
            op.drop_index(RATE_INDEX, table_name=table)
        with op.batch_alter_table(table) as batch:
            for c in have:
                batch.drop_column(c)
        if index:
            op.create_index(RATE_INDEX, table,
                            ["version_id", "department_id", sa.text("coalesce(plant_id, 0)")],
                            unique=True)
    if "cost_sheet_versions" in tables and "fx_rates" in _cols(bind, "cost_sheet_versions"):
        with op.batch_alter_table("cost_sheet_versions") as batch:
            batch.drop_column("fx_rates")
    if "plants" in tables and "local_currency" in _cols(bind, "plants"):
        with op.batch_alter_table("plants") as batch:
            batch.drop_column("local_currency")
