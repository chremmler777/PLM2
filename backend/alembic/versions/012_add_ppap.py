"""Add PPAP submission and element tables (Quality module).

Revision ID: 012
Revises: 011
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa


revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())
    tables = inspector.get_table_names()

    if 'ppap_submissions' not in tables:
        op.create_table(
            'ppap_submissions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('revision_id', sa.Integer(), sa.ForeignKey('part_revisions.id'), nullable=False, index=True),
            sa.Column('level', sa.Integer(), nullable=False, server_default='3'),
            sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
            sa.Column('customer', sa.String(255), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('submitted_at', sa.DateTime(), nullable=True),
            sa.Column('decided_at', sa.DateTime(), nullable=True),
            sa.Column('decided_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('decision_notes', sa.Text(), nullable=True),
        )

    if 'ppap_elements' not in tables:
        op.create_table(
            'ppap_elements',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('submission_id', sa.Integer(), sa.ForeignKey('ppap_submissions.id'), nullable=False, index=True),
            sa.Column('position', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(120), nullable=False),
            sa.Column('required', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
            sa.Column('file_id', sa.Integer(), sa.ForeignKey('revision_files.id'), nullable=True),
            sa.Column('comment', sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table('ppap_elements')
    op.drop_table('ppap_submissions')
