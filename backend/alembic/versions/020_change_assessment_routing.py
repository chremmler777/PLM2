"""Change assessment routing: ChangeAssessment stage/letter/status columns,
change_routings, change_routing_standards.

Revision ID: 020
Revises: 019
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = '020'
down_revision = '019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())
    existing = inspector.get_table_names()

    cols = {c['name'] for c in inspector.get_columns('change_assessments')}
    if 'stage_order' not in cols:
        op.add_column('change_assessments', sa.Column('stage_order', sa.Integer(), nullable=False, server_default='1'))
    if 'rasic_letter' not in cols:
        op.add_column('change_assessments', sa.Column('rasic_letter', sa.String(1), nullable=False, server_default='R'))
    if 'status' not in cols:
        op.add_column('change_assessments', sa.Column('status', sa.String(20), nullable=False, server_default='active'))

    if 'change_routings' not in existing:
        op.create_table(
            'change_routings',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), nullable=False, unique=True, index=True),
            sa.Column('template_id', sa.Integer(), sa.ForeignKey('wf_templates.id'), nullable=True),
            sa.Column('template_version', sa.Integer(), nullable=True),
            sa.Column('standard_snapshot', sa.JSON(), nullable=False, server_default='{}'),
            sa.Column('has_deviation', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('deviation_status', sa.String(20), nullable=False, server_default='none'),
            sa.Column('deviation_note', sa.Text(), nullable=True),
            sa.Column('deviation_proposed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('deviation_approved_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('deviation_approved_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if 'change_routing_standards' not in existing:
        op.create_table(
            'change_routing_standards',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_type', sa.String(30), nullable=False, unique=True, index=True),
            sa.Column('template_id', sa.Integer(), sa.ForeignKey('wf_templates.id'), nullable=False),
            sa.Column('template_version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('updated_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())
    existing = inspector.get_table_names()

    if 'change_routing_standards' in existing:
        op.drop_table('change_routing_standards')
    if 'change_routings' in existing:
        op.drop_table('change_routings')

    cols = {c['name'] for c in inspector.get_columns('change_assessments')}
    for col in ('status', 'rasic_letter', 'stage_order'):
        if col in cols:
            op.drop_column('change_assessments', col)
