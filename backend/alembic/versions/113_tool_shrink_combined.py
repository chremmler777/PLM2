"""113: tool shrinkage as one combined value OR parallel + normal.

parts.tool_shrink_combined_pct: the single value an unfilled resin's tool is cut
with. A tool holds either combined or parallel + normal, never both.
tool_shrink_decisions: combined_pct and measured_combined_pct; parallel_pct and
normal_pct become nullable (a combined decision has none).

Combined or parallel + normal is a choice made per tool on its Shrinkage card,
so no data moves: equal parallel/normal values stay as they were entered.

Guarded (what exists already is left alone), dialect-neutral.

Revision ID: 113
Revises: 112
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "113"
down_revision = "112"
branch_labels = None
depends_on = None

PCT = sa.Numeric(5, 3)


def _cols(bind, table):
    return {c["name"]: c for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "parts" in tables and "tool_shrink_combined_pct" not in _cols(bind, "parts"):
        op.add_column("parts", sa.Column("tool_shrink_combined_pct", PCT, nullable=True))
    if "tool_shrink_decisions" in tables:
        have = _cols(bind, "tool_shrink_decisions")
        with op.batch_alter_table("tool_shrink_decisions") as batch:
            if "combined_pct" not in have:
                batch.add_column(sa.Column("combined_pct", PCT, nullable=True))
            if "measured_combined_pct" not in have:
                batch.add_column(sa.Column("measured_combined_pct", PCT, nullable=True))
            if not have["parallel_pct"]["nullable"]:
                batch.alter_column("parallel_pct", existing_type=PCT, nullable=True)
            if not have["normal_pct"]["nullable"]:
                batch.alter_column("normal_pct", existing_type=PCT, nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "parts" in tables and "tool_shrink_combined_pct" in _cols(bind, "parts"):
        op.execute("UPDATE parts SET tool_shrink_parallel_pct = tool_shrink_combined_pct, "
                   "tool_shrink_normal_pct = tool_shrink_combined_pct WHERE tool_shrink_combined_pct IS NOT NULL")
        with op.batch_alter_table("parts") as batch:
            batch.drop_column("tool_shrink_combined_pct")
    if "tool_shrink_decisions" in tables:
        have = _cols(bind, "tool_shrink_decisions")
        if "combined_pct" in have:
            op.execute("UPDATE tool_shrink_decisions SET parallel_pct = combined_pct, normal_pct = combined_pct "
                       "WHERE combined_pct IS NOT NULL")
            op.execute("UPDATE tool_shrink_decisions SET measured_parallel_pct = measured_combined_pct, "
                       "measured_normal_pct = measured_combined_pct WHERE measured_combined_pct IS NOT NULL")
            with op.batch_alter_table("tool_shrink_decisions") as batch:
                batch.drop_column("combined_pct")
                batch.drop_column("measured_combined_pct")
