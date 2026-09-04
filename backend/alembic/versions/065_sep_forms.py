"""SEP forms engine: form_definitions, form_instances, form_events.

Also seeds the form definitions. The legacy sep_risks rows are copied into the
risk_assessment form by scripts/migrate_sep_risks.py, run after this upgrade.

Revision ID: 065
Revises: 064
Create Date: 2026-09-03
"""
from alembic import op
import sqlalchemy as sa

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    existing = inspect(op.get_bind()).get_table_names()

    if "form_definitions" not in existing:
        op.create_table(
            "form_definitions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(60), nullable=False, index=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("implements", sa.String(60), nullable=True),
            sa.Column("cardinality", sa.String(10), nullable=False, server_default="single"),
            sa.Column("gate_items", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("body", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("key", "version", name="uq_form_definition_key_version"),
        )
    if "form_instances" not in existing:
        op.create_table(
            "form_instances",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False, index=True),
            sa.Column("definition_id", sa.Integer(), sa.ForeignKey("form_definitions.id"), nullable=False, index=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft", index=True),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True, index=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
        )
    if "form_events" not in existing:
        op.create_table(
            "form_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("instance_id", sa.Integer(), sa.ForeignKey("form_instances.id"), nullable=False, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("event", sa.String(20), nullable=False),
            sa.Column("role", sa.String(20), nullable=True),
            sa.Column("diff", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    # Seed the form definitions on the migration's own connection.
    from app.forms.loader import read_definition_files

    bind = op.get_bind()
    defs = sa.table("form_definitions", sa.column("key"), sa.column("version"), sa.column("title"),
                    sa.column("implements"), sa.column("cardinality"), sa.column("gate_items"),
                    sa.column("body", sa.JSON()))  # typed: the body dict must serialize as JSON
    existing = {(k, v) for k, v in bind.execute(sa.select(defs.c.key, defs.c.version)).all()}
    for body in read_definition_files():
        if (body["key"], body["version"]) not in existing:
            bind.execute(defs.insert().values(key=body["key"], version=body["version"], title=body["title"],
                                              implements=body.get("implements"),
                                              cardinality=body.get("cardinality", "single"),
                                              gate_items=bool(body.get("gate_items", False)), body=body))

    # The legacy sep_risks -> risk_assessment row copy needs ORM sessions, and a
    # second (async) connection cannot see this migration's uncommitted DDL.
    # Run it after the upgrade as a deploy step:
    #     python scripts/migrate_sep_risks.py


def downgrade() -> None:
    op.drop_table("form_events")
    op.drop_table("form_instances")
    op.drop_table("form_definitions")
