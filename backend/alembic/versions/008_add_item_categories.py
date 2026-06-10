"""Add item_category and gauge calibration fields to parts.

Automotive PLM controls more than articles: tools, assembly equipment, and
gauges are revision-controlled items too. Gauges additionally carry
calibration tracking.

Revision ID: 008
Revises: 007
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa


revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())
    columns = [c['name'] for c in inspector.get_columns('parts')]

    if 'item_category' not in columns:
        op.add_column('parts', sa.Column('item_category', sa.String(30), nullable=False, server_default='article'))
        op.create_index('ix_parts_item_category', 'parts', ['item_category'])
    if 'calibration_interval_months' not in columns:
        op.add_column('parts', sa.Column('calibration_interval_months', sa.Integer(), nullable=True))
    if 'last_calibrated_at' not in columns:
        op.add_column('parts', sa.Column('last_calibrated_at', sa.DateTime(), nullable=True))
    if 'next_calibration_due' not in columns:
        op.add_column('parts', sa.Column('next_calibration_due', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_index('ix_parts_item_category', 'parts')
    op.drop_column('parts', 'item_category')
    op.drop_column('parts', 'calibration_interval_months')
    op.drop_column('parts', 'last_calibrated_at')
    op.drop_column('parts', 'next_calibration_due')
