"""Phase D: drop legacy Article-stack tables.

These tables belong to the retired Article model stack (superseded by the
Part stack). Data in them is legacy-only; parts/part_bom_items never
reference them. catalog_parts is SHARED with the Part stack and is KEPT.

Revision ID: 026
Revises: 025
"""
from alembic import op
from sqlalchemy import inspect

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None

# child-before-parent drop order
_LEGACY_TABLES = (
    "bom_items", "boms", "article_documents",
    "workflow_tasks", "workflow_steps", "workflow_instances",
    "workflow_templates", "article_revisions", "articles",
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if bind.dialect.name == "postgresql":
        # articles <-> article_revisions have a circular FK
        # (articles.active_revision_id), so a plain ordered drop cannot
        # succeed on an enforcing backend. CASCADE is safe here: nothing
        # outside this legacy set references these tables (verified at
        # retirement), so it only severs intra-legacy constraints.
        for table in _LEGACY_TABLES:
            if table in existing:
                op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
        return
    for table in _LEGACY_TABLES:
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    # Irreversible by design: the legacy schema lives in migration 001 and
    # the data is retired. Recreate from 001 if ever needed.
    pass
