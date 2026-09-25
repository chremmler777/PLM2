"""095: early stages polish, capture to assessment (spec 2026-09-25 §16).

- change_assessments.pending_rasic_letter: "Not our responsibility" asks
  for a re-letter; the row keeps its letter until the lead approves.
- change_requests.title_auto: the title follows the lead item (composed).
  Existing changes start with it off: their titles were never promised to
  follow anything.
- change_requests.scope_changed_after_quote / scope_changed_at /
  scope_change_reason / scope_change_department_ids: an impact edit made
  from 'quoted' on, and the departments whose costing reopens.
- change_meetings.cost_carrier: the room re-confirms customer | internal.
- change_concerns.settled_as: author | pm | department, who closed it.
  Backfilled: withdrawn by the raiser reads "author", by anybody else "pm".

Dialect-neutral (Core statements), same file on Postgres and SQLite.

Revision ID: 095
Revises: 094
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "095"
down_revision = "094"
branch_labels = None
depends_on = None


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    cols = _cols(insp, "change_assessments")
    if "pending_rasic_letter" not in cols:
        with op.batch_alter_table("change_assessments") as b:
            b.add_column(sa.Column("pending_rasic_letter", sa.String(1), nullable=True))

    cols = _cols(insp, "change_requests")
    with op.batch_alter_table("change_requests") as b:
        if "title_auto" not in cols:
            b.add_column(sa.Column("title_auto", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
        if "scope_changed_after_quote" not in cols:
            b.add_column(sa.Column("scope_changed_after_quote", sa.Boolean(),
                                   nullable=False, server_default=sa.false()))
        if "scope_changed_at" not in cols:
            b.add_column(sa.Column("scope_changed_at", sa.DateTime(), nullable=True))
        if "scope_change_reason" not in cols:
            b.add_column(sa.Column("scope_change_reason", sa.Text(), nullable=True))
        if "scope_change_department_ids" not in cols:
            b.add_column(sa.Column("scope_change_department_ids", sa.JSON(),
                                   nullable=True))

    cols = _cols(insp, "change_meetings")
    if "cost_carrier" not in cols:
        with op.batch_alter_table("change_meetings") as b:
            b.add_column(sa.Column("cost_carrier", sa.String(20), nullable=True))

    cols = _cols(insp, "change_concerns")
    if "settled_as" not in cols:
        with op.batch_alter_table("change_concerns") as b:
            b.add_column(sa.Column("settled_as", sa.String(20), nullable=True))
    cc = sa.table("change_concerns",
                  sa.column("settled_as", sa.String),
                  sa.column("withdrawn_at", sa.DateTime),
                  sa.column("withdrawn_by", sa.Integer),
                  sa.column("raised_by", sa.Integer))
    op.execute(cc.update()
               .where(cc.c.withdrawn_at.isnot(None),
                      cc.c.settled_as.is_(None),
                      cc.c.withdrawn_by == cc.c.raised_by)
               .values(settled_as="author"))
    op.execute(cc.update()
               .where(cc.c.withdrawn_at.isnot(None),
                      cc.c.settled_as.is_(None))
               .values(settled_as="pm"))


def downgrade() -> None:
    with op.batch_alter_table("change_concerns") as b:
        b.drop_column("settled_as")
    with op.batch_alter_table("change_meetings") as b:
        b.drop_column("cost_carrier")
    with op.batch_alter_table("change_requests") as b:
        b.drop_column("scope_change_department_ids")
        b.drop_column("scope_change_reason")
        b.drop_column("scope_changed_at")
        b.drop_column("scope_changed_after_quote")
        b.drop_column("title_auto")
    with op.batch_alter_table("change_assessments") as b:
        b.drop_column("pending_rasic_letter")
