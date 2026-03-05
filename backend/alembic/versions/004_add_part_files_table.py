"""Add part_files table for tracking uploaded CAD files.

Revision ID: 004
Revises: 003
Create Date: 2026-03-04 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create part_files table."""
    op.create_table(
        'part_files',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('part_id', sa.Integer(), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('saved_filename', sa.String(255), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('file_type', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['part_id'], ['parts.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    )
    op.create_index('ix_part_files_part_id', 'part_files', ['part_id'])


def downgrade() -> None:
    """Drop part_files table."""
    op.drop_index('ix_part_files_part_id', 'part_files')
    op.drop_table('part_files')
