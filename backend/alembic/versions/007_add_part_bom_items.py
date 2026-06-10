"""Add part_bom_items table for revision-scoped part BOMs.

Revision ID: 007
Revises: 006
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa


revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create part_bom_items table."""
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())
    if 'part_bom_items' in inspector.get_table_names():
        return

    op.create_table(
        'part_bom_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('revision_id', sa.Integer(), sa.ForeignKey('part_revisions.id'), nullable=False, index=True),
        sa.Column('child_part_id', sa.Integer(), sa.ForeignKey('parts.id'), nullable=True),
        sa.Column('catalog_part_id', sa.Integer(), sa.ForeignKey('catalog_parts.id'), nullable=True),
        sa.Column('item_number', sa.String(50), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('unit', sa.String(20), nullable=False, server_default='pcs'),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('part_bom_items')
