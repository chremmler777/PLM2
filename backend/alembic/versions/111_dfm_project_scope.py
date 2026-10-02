"""111: DFM project scope and soft delete.

A DFM topic belongs to exactly one tool (tool_part_id) or to a project
(project_id, the project-wide "general tooling DFM": tooling standards,
material info that apply to every tool of the project).

dfm_topics: project_id (FK projects.id, nullable, indexed), tool_part_id
nullable, deleted_at / deleted_by (soft delete of an empty topic), check
constraint ck_dfm_topics_one_scope (exactly one of the two scopes).
dfm_audit_events: project_id (FK projects.id, nullable, indexed),
tool_part_id nullable.

Guarded (whatever exists already is left alone), dialect-neutral.

Revision ID: 111
Revises: 110
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "111"
down_revision = "110"
branch_labels = None
depends_on = None

CHECK_NAME = "ck_dfm_topics_one_scope"
CHECK_SQL = "(tool_part_id IS NULL) <> (project_id IS NULL)"


def _cols(insp, table: str) -> dict:
    return {c["name"]: c for c in insp.get_columns(table)}


def _indexes(insp, table: str) -> set:
    return {i["name"] for i in insp.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    if "dfm_topics" in tables:
        cols = _cols(insp, "dfm_topics")
        with op.batch_alter_table("dfm_topics") as batch:
            if "project_id" not in cols:
                batch.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
                batch.create_foreign_key("fk_dfm_topics_project_id", "projects", ["project_id"], ["id"])
            if "deleted_at" not in cols:
                batch.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
            if "deleted_by" not in cols:
                batch.add_column(sa.Column("deleted_by", sa.Integer(), nullable=True))
                batch.create_foreign_key("fk_dfm_topics_deleted_by", "users", ["deleted_by"], ["id"])
            if not cols["tool_part_id"]["nullable"]:
                batch.alter_column("tool_part_id", existing_type=sa.Integer(), nullable=True)
        insp = inspect(bind)
        if "ix_dfm_topics_project_id" not in _indexes(insp, "dfm_topics"):
            op.create_index("ix_dfm_topics_project_id", "dfm_topics", ["project_id"])
        checks = {c.get("name") for c in insp.get_check_constraints("dfm_topics")}
        if CHECK_NAME not in checks:
            with op.batch_alter_table("dfm_topics") as batch:
                batch.create_check_constraint(CHECK_NAME, CHECK_SQL)

    if "dfm_audit_events" in tables:
        cols = _cols(insp, "dfm_audit_events")
        with op.batch_alter_table("dfm_audit_events") as batch:
            if "project_id" not in cols:
                batch.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
                batch.create_foreign_key("fk_dfm_audit_events_project_id", "projects", ["project_id"], ["id"])
            if not cols["tool_part_id"]["nullable"]:
                batch.alter_column("tool_part_id", existing_type=sa.Integer(), nullable=True)
        insp = inspect(bind)
        if "ix_dfm_audit_events_project_id" not in _indexes(insp, "dfm_audit_events"):
            op.create_index("ix_dfm_audit_events_project_id", "dfm_audit_events", ["project_id"])


def downgrade() -> None:
    """Drops the project scope. Project topics and their events would break
    tool_part_id NOT NULL, so they are removed first (files stay on disk)."""
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    if "dfm_audit_events" in tables and "project_id" in _cols(insp, "dfm_audit_events"):
        op.execute("DELETE FROM dfm_audit_events WHERE tool_part_id IS NULL")
        if "ix_dfm_audit_events_project_id" in _indexes(insp, "dfm_audit_events"):
            op.drop_index("ix_dfm_audit_events_project_id", table_name="dfm_audit_events")
        with op.batch_alter_table("dfm_audit_events") as batch:
            batch.drop_constraint("fk_dfm_audit_events_project_id", type_="foreignkey")
            batch.drop_column("project_id")
            batch.alter_column("tool_part_id", existing_type=sa.Integer(), nullable=False)

    if "dfm_topics" in tables and "project_id" in _cols(insp, "dfm_topics"):
        op.execute("DELETE FROM dfm_entry_files WHERE entry_id IN (SELECT e.id FROM dfm_entries e "
                   "JOIN dfm_topics t ON t.id = e.topic_id WHERE t.tool_part_id IS NULL)")
        op.execute("DELETE FROM dfm_entries WHERE topic_id IN "
                   "(SELECT id FROM dfm_topics WHERE tool_part_id IS NULL)")
        op.execute("DELETE FROM dfm_topics WHERE tool_part_id IS NULL")
        checks = {c.get("name") for c in insp.get_check_constraints("dfm_topics")}
        if "ix_dfm_topics_project_id" in _indexes(insp, "dfm_topics"):
            op.drop_index("ix_dfm_topics_project_id", table_name="dfm_topics")
        with op.batch_alter_table("dfm_topics") as batch:
            if CHECK_NAME in checks:
                batch.drop_constraint(CHECK_NAME, type_="check")
            batch.drop_constraint("fk_dfm_topics_project_id", type_="foreignkey")
            batch.drop_constraint("fk_dfm_topics_deleted_by", type_="foreignkey")
            batch.drop_column("project_id")
            batch.drop_column("deleted_by")
            batch.drop_column("deleted_at")
            batch.alter_column("tool_part_id", existing_type=sa.Integer(), nullable=False)
