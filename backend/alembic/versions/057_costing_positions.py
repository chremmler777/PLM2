"""057: costing positions — either a direct quote or an estimate.

The cost grid (assessment_cost_line) prices hours against a department rate at a
plant. That is the right shape for internal work and the wrong shape for the
half of costing that is a supplier's number: a tool shop's offer is a price, a
shipping line and a delivery date, not hours × rate. Departments were forcing
those into external_cost on an hours line and losing WHO quoted, HOW MANY
quotes came in, and WHICH one the department would actually take.

A costing position is one thing that has to be paid for, owned by one
department: internal effort (the time this assessment itself cost),
support effort (time this department will spend during implementation), or
external work. An external position is priced EITHER as an estimate (est_cost —
nobody has asked a supplier yet) OR as a quote, in which case the number comes
from the vendor offers hanging off it. One of those offers may be flagged
favorite: the department's vote for which supplier it wants. Choosing for real
is Sales' job at quoting time and is deliberately NOT modelled here yet.

change_attachments gains costing_offer_id so the quote PDF files against the
offer it IS, alongside the existing concern/assessment containers (kind
'vendor_quote'). Nullable, ORM-level FK only, same as 049/055 — SQLite cannot
ADD COLUMN with a foreign key.

Revision ID: 057
Revises: 056
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    if "costing_positions" not in tables:
        op.create_table(
            "costing_positions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(),
                      sa.ForeignKey("change_requests.id"), nullable=False,
                      index=True),
            sa.Column("department_id", sa.Integer(),
                      sa.ForeignKey("wf_departments.id"), nullable=False,
                      index=True),
            # Free text: the catalog of tags below it is a suggestion list, not
            # a cage — the same call the activity catalog makes.
            sa.Column("label", sa.String(200), nullable=False),
            sa.Column("tag", sa.String(40), nullable=True),
            # internal_effort | support_effort | external
            sa.Column("kind", sa.String(30), nullable=False,
                      server_default="external"),
            # estimate | quote — meaningful for external positions only.
            sa.Column("pricing", sa.String(20), nullable=False,
                      server_default="estimate"),
            sa.Column("est_cost", sa.Numeric(14, 2), nullable=True),
            sa.Column("hours", sa.Numeric(10, 2), nullable=True),
            sa.Column("lead_time_days", sa.Integer(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"),
                      nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
        )

    if "costing_offers" not in tables:
        op.create_table(
            "costing_offers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("position_id", sa.Integer(),
                      sa.ForeignKey("costing_positions.id"), nullable=False,
                      index=True),
            sa.Column("vendor_name", sa.String(120), nullable=False),
            sa.Column("cost", sa.Numeric(14, 2), nullable=False,
                      server_default="0"),
            # Shipping is either stated separately (shipping_cost) or declared
            # part of the price (shipping_included) — quotes come both ways and
            # comparing them needs to know which.
            sa.Column("shipping_cost", sa.Numeric(14, 2), nullable=True),
            sa.Column("shipping_included", sa.Boolean(), nullable=False,
                      server_default=sa.false()),
            sa.Column("lead_time_days", sa.Integer(), nullable=True),
            # The department's vote, not a decision: at most one per position.
            sa.Column("favorite", sa.Boolean(), nullable=False,
                      server_default=sa.false()),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"),
                      nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
        )

    if "change_attachments" in tables:
        cols = {c["name"] for c in insp.get_columns("change_attachments")}
        if "costing_offer_id" not in cols:
            op.add_column("change_attachments",
                          sa.Column("costing_offer_id", sa.Integer(),
                                    nullable=True))
            op.create_index("ix_change_attachments_costing_offer_id",
                            "change_attachments", ["costing_offer_id"])


def downgrade() -> None:
    pass  # forward-only
