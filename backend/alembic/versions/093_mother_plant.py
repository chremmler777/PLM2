"""093: mother-plant changes (spec 2026-09-25 §14).

change_requests gains `origin` (customer | internal | mother_plant),
backfilled from customer_relevant, plus the mother plant's name, reference
and SOP date. New table change_info_receipts: one row per department
informed of a mother-plant change ("Read and understood").

Dialect-neutral (portable Core update, no raw SQL): same file on Postgres
and SQLite.

Revision ID: 093
Revises: 092
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "093"
down_revision = "092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("change_requests")}
    with op.batch_alter_table("change_requests") as b:
        if "origin" not in cols:
            b.add_column(sa.Column("origin", sa.String(20), nullable=False,
                                   server_default="customer"))
        if "mother_plant_name" not in cols:
            b.add_column(sa.Column("mother_plant_name", sa.String(120), nullable=True))
        if "mother_plant_ref" not in cols:
            b.add_column(sa.Column("mother_plant_ref", sa.String(120), nullable=True))
        if "mother_plant_sop" not in cols:
            b.add_column(sa.Column("mother_plant_sop", sa.Date(), nullable=True))

    # Backfill: every existing change is customer or internal, by its flag.
    cr = sa.table("change_requests",
                  sa.column("origin", sa.String),
                  sa.column("customer_relevant", sa.Boolean))
    op.execute(cr.update()
               .where(cr.c.customer_relevant.is_(sa.true()))
               .values(origin="customer"))
    op.execute(cr.update()
               .where(sa.or_(cr.c.customer_relevant.is_(sa.false()),
                             cr.c.customer_relevant.is_(None)))
               .values(origin="internal"))

    if "change_info_receipts" not in set(insp.get_table_names()):
        op.create_table(
            "change_info_receipts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(),
                      sa.ForeignKey("change_requests.id"), nullable=False),
            sa.Column("department_id", sa.Integer(),
                      sa.ForeignKey("wf_departments.id"), nullable=False),
            sa.Column("sent_by", sa.Integer(), sa.ForeignKey("users.id"),
                      nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("acknowledged_by", sa.Integer(), sa.ForeignKey("users.id"),
                      nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.UniqueConstraint("change_id", "department_id",
                                name="uq_change_info_receipt"),
        )
        op.create_index("ix_change_info_receipts_change_id",
                        "change_info_receipts", ["change_id"])


def downgrade() -> None:
    op.drop_index("ix_change_info_receipts_change_id",
                  table_name="change_info_receipts")
    op.drop_table("change_info_receipts")
    with op.batch_alter_table("change_requests") as b:
        b.drop_column("mother_plant_sop")
        b.drop_column("mother_plant_ref")
        b.drop_column("mother_plant_name")
        b.drop_column("origin")
