"""Add user_departments membership table (My Tasks scoping).

Revision ID: 010
Revises: 009
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa


revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())
    if 'user_departments' in inspector.get_table_names():
        return

    op.create_table(
        'user_departments',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('department_id', sa.Integer(), sa.ForeignKey('wf_departments.id'), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table('user_departments')
