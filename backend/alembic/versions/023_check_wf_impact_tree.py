"""Phase B: check_workflow_standards, WfStep evidence/4-eyes flags,
PartRevision change back-link + no-geometry-change sign-off.

Revision ID: 023
Revises: 022a
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "023"
down_revision = "022a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    if "check_workflow_standards" not in tables:
        op.create_table(
            "check_workflow_standards",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("item_category", sa.String(30), nullable=False, unique=True),
            sa.Column("template_id", sa.Integer(),
                      sa.ForeignKey("wf_templates.id"), nullable=False),
            sa.Column("template_version", sa.Integer(), nullable=False,
                      server_default="1"),
            sa.Column("updated_by", sa.Integer(),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    step_cols = {c["name"] for c in insp.get_columns("wf_steps")}
    if "requires_cad_evidence" not in step_cols:
        op.add_column("wf_steps", sa.Column(
            "requires_cad_evidence", sa.Boolean(), nullable=False,
            server_default=sa.false()))
    if "four_eyes" not in step_cols:
        op.add_column("wf_steps", sa.Column(
            "four_eyes", sa.Boolean(), nullable=False, server_default=sa.false()))

    rev_cols = {c["name"] for c in insp.get_columns("part_revisions")}
    if "originating_change_id" not in rev_cols:
        # Note: SQLite cannot ALTER TABLE ADD COLUMN with a FK constraint
        # (only supported inside CREATE TABLE / batch mode), so the FK is
        # enforced at the ORM level only (see PartRevision.originating_change_id).
        op.add_column("part_revisions", sa.Column(
            "originating_change_id", sa.Integer(), nullable=True))
        # Create the index to match the ORM model declaration (index=True).
        rev_indexes = {ix["name"] for ix in inspect(op.get_bind()).get_indexes("part_revisions")}
        if "ix_part_revisions_originating_change_id" not in rev_indexes:
            op.create_index("ix_part_revisions_originating_change_id",
                            "part_revisions", ["originating_change_id"])
    if "no_geometry_change" not in rev_cols:
        op.add_column("part_revisions", sa.Column(
            "no_geometry_change", sa.Boolean(), nullable=False,
            server_default=sa.false()))
    if "no_geometry_change_by" not in rev_cols:
        # Note: SQLite FK limitation (see originating_change_id comment above).
        op.add_column("part_revisions", sa.Column(
            "no_geometry_change_by", sa.Integer(), nullable=True))
    if "no_geometry_change_at" not in rev_cols:
        op.add_column("part_revisions", sa.Column(
            "no_geometry_change_at", sa.DateTime(), nullable=True))
    if "no_geometry_change_reason" not in rev_cols:
        op.add_column("part_revisions", sa.Column(
            "no_geometry_change_reason", sa.Text(), nullable=True))

    # Backfill back-links for revisions already spawned by in-flight changes.
    bind.execute(sa.text("""
        UPDATE part_revisions
           SET originating_change_id = (
               SELECT cii.change_id FROM change_impacted_items cii
                WHERE cii.resulting_revision_id = part_revisions.id
                LIMIT 1)
         WHERE originating_change_id IS NULL
           AND id IN (SELECT resulting_revision_id FROM change_impacted_items
                       WHERE resulting_revision_id IS NOT NULL)
    """))


def downgrade() -> None:
    op.drop_table("check_workflow_standards")
    op.drop_column("wf_steps", "requires_cad_evidence")
    op.drop_column("wf_steps", "four_eyes")
    # Drop the index before dropping the column (guarded idempotently).
    bind = op.get_bind()
    rev_indexes = {ix["name"] for ix in inspect(bind).get_indexes("part_revisions")}
    if "ix_part_revisions_originating_change_id" in rev_indexes:
        op.drop_index("ix_part_revisions_originating_change_id", table_name="part_revisions")
    op.drop_column("part_revisions", "originating_change_id")
    op.drop_column("part_revisions", "no_geometry_change")
    op.drop_column("part_revisions", "no_geometry_change_by")
    op.drop_column("part_revisions", "no_geometry_change_at")
    op.drop_column("part_revisions", "no_geometry_change_reason")
