"""Add part_relations table - tool/gauge/equipment to article cross-links.

Revision ID: 009
Revises: 008
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa


revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())
    if 'part_relations' in inspector.get_table_names():
        return

    op.create_table(
        'part_relations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('from_part_id', sa.Integer(), sa.ForeignKey('parts.id'), nullable=False, index=True),
        sa.Column('to_part_id', sa.Integer(), sa.ForeignKey('parts.id'), nullable=False, index=True),
        sa.Column('relation_type', sa.String(30), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.UniqueConstraint('from_part_id', 'to_part_id', 'relation_type', name='uq_part_relation'),
    )


def downgrade() -> None:
    op.drop_table('part_relations')
