"""Add gltf_filename field to part_files table.

Revision ID: 005
Revises: 004
Create Date: 2026-03-04 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add gltf_filename field to part_files table."""
    op.add_column('part_files', sa.Column('gltf_filename', sa.String(255), nullable=True))


def downgrade() -> None:
    """Remove gltf_filename field from part_files table."""
    op.drop_column('part_files', 'gltf_filename')
