"""059: the part weight, estimated at costing and validated later.

A change to a tool changes the part it makes, and the part's WEIGHT is one of
the numbers the customer is billed on. The Tooling Engineer is the only person
who can say what the reworked tool will produce, and they can only say it as an
ESTIMATE — the real number comes off a scale at validation, after the tool has
been sampled. The delta between the two is a commercial event: Sales updates
the quote with it.

So the number is stamped twice, by two different people at two different
stages, and both stampings have to survive as separate facts — a single
part_weight_g column overwritten at validation would destroy exactly the
comparison the process exists to make. Hence two triples (value, by, at).

The validated_* half is laid here and filled later (process map build order
item 6): a column added in the same breath as its estimate counterpart cannot
drift from it, and adding it costs nothing while it stays NULL.

Weight in GRAMS, Numeric(10,2): parts in this system are trim and brackets, and
the argument at validation is about tens of grams, not kilos.

FKs are ORM-level only (SQLite cannot ADD COLUMN with a foreign key) — same
call as 049/055/057.

Revision ID: 059
Revises: 058
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("estimated_part_weight_g", lambda: sa.Column(
        "estimated_part_weight_g", sa.Numeric(10, 2), nullable=True)),
    ("estimated_weight_by", lambda: sa.Column(
        "estimated_weight_by", sa.Integer(), nullable=True)),
    ("estimated_weight_at", lambda: sa.Column(
        "estimated_weight_at", sa.DateTime(), nullable=True)),
    ("validated_part_weight_g", lambda: sa.Column(
        "validated_part_weight_g", sa.Numeric(10, 2), nullable=True)),
    ("validated_weight_by", lambda: sa.Column(
        "validated_weight_by", sa.Integer(), nullable=True)),
    ("validated_weight_at", lambda: sa.Column(
        "validated_weight_at", sa.DateTime(), nullable=True)),
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "change_requests" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("change_requests")}
    for name, make in _COLUMNS:
        if name not in cols:
            op.add_column("change_requests", make())


def downgrade() -> None:
    pass  # forward-only
