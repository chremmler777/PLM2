"""115: part data mail.

mail_recipients: a fixed recipient list per project (list_key "part_data" for
now), unique per project, list and address.
mail_outbox: one row per part data / status event, written in the same
transaction as the changelog entry; the 5-minute digest sends one mail per
project and stamps sent_at / mail_status / error.

Guarded (a table that exists already is left alone), dialect-neutral.

Revision ID: 115
Revises: 114
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "115"
down_revision = "114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "mail_recipients" not in tables:
        op.create_table(
            "mail_recipients",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("list_key", sa.String(40), nullable=False, server_default="part_data"),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("project_id", "list_key", "email",
                                name="uq_mail_recipients_project_list_email"),
        )
        op.create_index("ix_mail_recipients_project_id", "mail_recipients", ["project_id"])
    if "mail_outbox" not in tables:
        op.create_table(
            "mail_outbox",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
            sa.Column("revision_id", sa.Integer(), sa.ForeignKey("part_revisions.id"), nullable=True),
            sa.Column("event", sa.String(50), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("performed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("mail_status", sa.String(10), nullable=False, server_default="pending"),
            sa.Column("error", sa.Text(), nullable=True),
        )
        op.create_index("ix_mail_outbox_project_id", "mail_outbox", ["project_id"])
        op.create_index("ix_mail_outbox_created_at", "mail_outbox", ["created_at"])
        op.create_index("ix_mail_outbox_mail_status", "mail_outbox", ["mail_status"])


def downgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "mail_outbox" in tables:
        op.drop_table("mail_outbox")
    if "mail_recipients" in tables:
        op.drop_table("mail_recipients")
