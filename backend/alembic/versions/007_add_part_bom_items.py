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
    """Create catalog_parts and part_bom_items tables."""
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())
    existing = inspector.get_table_names()

    # catalog_parts predates this migration in the model layer (it's the
    # shared global parts catalog referenced by part_bom_items below), but
    # no earlier migration ever created it — SQLite dev environments only
    # ever exercised it via Base.metadata.create_all(), never through the
    # alembic chain. Create it here, guarded, so a from-scratch run on an
    # enforcing backend (Postgres) succeeds instead of failing on the
    # part_bom_items FK to a nonexistent table.
    if 'catalog_parts' not in existing:
        op.create_table(
            'catalog_parts',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
            sa.Column('part_number', sa.String(100), nullable=False),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('part_type', sa.String(20), nullable=False),
            sa.Column('supplier', sa.String(255), nullable=True),
            sa.Column('unit', sa.String(20), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('organization_id', 'part_number', name='uq_catalog_part_org_number'),
        )

    if 'part_bom_items' in existing:
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
