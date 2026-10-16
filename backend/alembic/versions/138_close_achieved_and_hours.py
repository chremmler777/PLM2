"""138: §11 close with the achieved value, C15 book hours (ECR-solid lane L7).

Schema
  change_requests.achieved_value / achieved_ref / achieved_by / achieved_at
      an internal change closes with what it achieved beside target_value
      (SOFT rule achieved_missing, RELEASE_V2)
  implementation_bookings.booked_for         a colleague the hours are for
                                             (Belk for the toolmakers)
  implementation_bookings.activity           'coordination' (the lead's row)
  implementation_bookings.status_at_booking  the change's status then

Data: bookings written before get status_at_booking from nothing (NULL =
"in implementation", the only window they had). No change gets an achieved
value: a released internal change asks for it at close.

Repeatable: every column is added once.

Revision ID: 138
Revises: 137
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "138"
down_revision = "137"
branch_labels = None
depends_on = None

COLUMNS = (
    ("change_requests", "achieved_value", lambda: sa.Float(), None),
    ("change_requests", "achieved_ref", lambda: sa.String(255), None),
    ("change_requests", "achieved_by", lambda: sa.Integer(), "users.id"),
    ("change_requests", "achieved_at", lambda: sa.DateTime(), None),
    ("implementation_bookings", "booked_for", lambda: sa.String(120), None),
    ("implementation_bookings", "activity", lambda: sa.String(20), None),
    ("implementation_bookings", "status_at_booking", lambda: sa.String(30), None),
)


def _have(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    for table, name, kind, fk in COLUMNS:
        if name not in _have(table):
            args = [sa.ForeignKey(fk)] if fk else []
            op.add_column(table, sa.Column(name, kind(), *args, nullable=True))


def downgrade() -> None:
    for table, name, _, _ in reversed(COLUMNS):
        if name in _have(table):
            with op.batch_alter_table(table) as batch:
                batch.drop_column(name)
