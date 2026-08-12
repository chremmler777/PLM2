"""064: the vendor decision — a recommendation, and the person accountable for it.

The costing module let a department mark one offer per position as its
FAVORITE, and everything downstream quietly treated that vote as the answer.
The rule book's stage 5 says something different and sharper: the favorite is a
RECOMMENDATION. It is the department's technical opinion about which supplier
to use, and it is visible precisely so it can be argued with. The decision
belongs to Sales, who owns the customer, the margin, and the consequences of a
supplier that misses its date.

That makes two facts where there used to be one, and both have to survive
separately — collapsing them back into a single flag would destroy the only
question anybody asks afterwards, which is whether the buyer went with the
engineers or over their heads:

  favorite      the department's recommendation (existing column, untouched)
  chosen        Sales' decision

  chosen_reason is what makes divergence answerable rather than merely
  visible. It is REQUIRED by the service when the chosen offer is not the
  favorite and optional when it agrees — "we took the tool shop's advice"
  needs no defence, "we overruled it" does. Storing it nullable and enforcing
  the condition in code is deliberate: the rule is about the relationship
  between two rows, which no column constraint can express.

  chosen_by / chosen_at are the accountability. A decision to spend the
  customer's money against your own engineers' advice with nobody's name on it
  is exactly the record this table exists to prevent.

Cost consequence, decided in the service and pinned by a test: the SUMMATION
values a position from the chosen offer once one exists, because that is the
money Sales is actually quoting. The department's own recommendation stays
visible next to it (positions_by_department carries both vendors and both
numbers) so the wrap-up can read "recommended: A · chosen: B (reason)".

FKs are ORM-level only — SQLite cannot ADD COLUMN with a constraint, the same
call 049/051/055/057/059/061/063 made.

Revision ID: 064
Revises: 063
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("chosen", lambda: sa.Column(
        "chosen", sa.Boolean(), nullable=False, server_default=sa.false())),
    ("chosen_reason", lambda: sa.Column(
        "chosen_reason", sa.Text(), nullable=True)),
    ("chosen_by", lambda: sa.Column(
        "chosen_by", sa.Integer(), nullable=True)),
    ("chosen_at", lambda: sa.Column(
        "chosen_at", sa.DateTime(), nullable=True)),
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "costing_offers" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("costing_offers")}
    for name, make in _COLUMNS:
        if name not in cols:
            op.add_column("costing_offers", make())


def downgrade() -> None:
    pass  # forward-only
