"""Add parent_part_id for hierarchical sub-assemblies.

Revision ID: 003
Revises: 002
Create Date: 2026-03-04 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add parent_part_id field to parts table."""
    op.add_column('parts', sa.Column('parent_part_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_parts_parent_part_id', 'parts', 'parts', ['parent_part_id'], ['id'])


def downgrade() -> None:
    """Remove parent_part_id field from parts table."""
    op.drop_constraint('fk_parts_parent_part_id', 'parts', type_='foreignkey')
    op.drop_column('parts', 'parent_part_id')
