"""Add conversion_status field to part_files table.

Revision ID: 006
Revises: 005
Create Date: 2026-03-05 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add conversion_status field to part_files table."""
    # Check if column already exists
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())
    columns = [c['name'] for c in inspector.get_columns('part_files')]
    if 'conversion_status' not in columns:
        op.add_column('part_files', sa.Column('conversion_status', sa.String(20), nullable=False, server_default='pending'))


def downgrade() -> None:
    """Remove conversion_status field from part_files table."""
    op.drop_column('part_files', 'conversion_status')
