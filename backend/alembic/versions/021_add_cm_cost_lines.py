"""CM cost digitization: department_rate, assessment_activity, assessment_cost_line,
change_gate, change_affected_plants; D1 columns on change_requests; cost columns on
change_assessments; is_lead on change_impacted_items.

Revision ID: 021
Revises: 020
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = '021'
down_revision = '020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    insp = inspect(op.get_bind())
    existing = set(insp.get_table_names())

    if 'department_rate' not in existing:
        op.create_table(
            'department_rate',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('department_id', sa.Integer(), sa.ForeignKey('wf_departments.id'), nullable=False, index=True),
            sa.Column('plant_id', sa.Integer(), sa.ForeignKey('plants.id'), nullable=False, index=True),
            sa.Column('hourly_rate', sa.Float(), nullable=False),
            sa.Column('min_factor', sa.Float(), nullable=False, server_default='1.0'),
            sa.Column('effective_from', sa.Date(), nullable=True),
        )
    if 'assessment_activity' not in existing:
        op.create_table(
            'assessment_activity',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('department_id', sa.Integer(), sa.ForeignKey('wf_departments.id'), nullable=False, index=True),
            sa.Column('label', sa.String(200), nullable=False),
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if 'assessment_cost_line' not in existing:
        op.create_table(
            'assessment_cost_line',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('assessment_id', sa.Integer(), sa.ForeignKey('change_assessments.id'), nullable=False, index=True),
            sa.Column('plant_id', sa.Integer(), sa.ForeignKey('plants.id'), nullable=False, index=True),
            sa.Column('activity_id', sa.Integer(), sa.ForeignKey('assessment_activity.id'), nullable=True),
            sa.Column('activity_label', sa.String(200), nullable=True),
            sa.Column('cost_kind', sa.String(20), nullable=False, server_default='one_time'),
            sa.Column('demand_hours', sa.Float(), nullable=False, server_default='0'),
            sa.Column('rate_snapshot', sa.Float(), nullable=False, server_default='0'),
            sa.Column('internal_cost', sa.Float(), nullable=False, server_default='0'),
            sa.Column('external_cost', sa.Float(), nullable=False, server_default='0'),
            sa.Column('note', sa.Text(), nullable=True),
        )
    if 'change_gate' not in existing:
        op.create_table(
            'change_gate',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), nullable=False, index=True),
            sa.Column('gate_key', sa.String(20), nullable=False),
            sa.Column('decision', sa.String(10), nullable=False, server_default='na'),
            sa.Column('decided_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('decided_at', sa.DateTime(), nullable=True),
            sa.Column('remark', sa.Text(), nullable=True),
        )
    if 'change_affected_plants' not in existing:
        op.create_table(
            'change_affected_plants',
            sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), primary_key=True),
            sa.Column('plant_id', sa.Integer(), sa.ForeignKey('plants.id'), primary_key=True),
        )

    a_cols = {c['name'] for c in insp.get_columns('change_assessments')}
    for name, col in [
        ('producibility', sa.Column('producibility', sa.String(10), nullable=False, server_default='na')),
        ('contact_person', sa.Column('contact_person', sa.String(120), nullable=True)),
        ('approval_comment', sa.Column('approval_comment', sa.Text(), nullable=True)),
        ('lifecycle_cost', sa.Column('lifecycle_cost', sa.Float(), nullable=True)),
    ]:
        if name not in a_cols:
            op.add_column('change_assessments', col)

    r_cols = {c['name'] for c in insp.get_columns('change_requests')}
    for name, col in [
        ('issuer', sa.Column('issuer', sa.String(120), nullable=True)),
        ('is_series', sa.Column('is_series', sa.Boolean(), nullable=False, server_default=sa.false())),
        ('cm_internal', sa.Column('cm_internal', sa.Boolean(), nullable=False, server_default=sa.false())),
        ('cm_external', sa.Column('cm_external', sa.Boolean(), nullable=False, server_default=sa.false())),
        ('implementation_mode', sa.Column('implementation_mode', sa.String(20), nullable=True)),
        ('customer_relevant', sa.Column('customer_relevant', sa.Boolean(), nullable=False, server_default=sa.false())),
        ('car_line', sa.Column('car_line', sa.String(120), nullable=True)),
    ]:
        if name not in r_cols:
            op.add_column('change_requests', col)

    i_cols = {c['name'] for c in insp.get_columns('change_impacted_items')}
    if 'is_lead' not in i_cols:
        op.add_column('change_impacted_items',
                      sa.Column('is_lead', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    from sqlalchemy import inspect
    insp = inspect(op.get_bind())
    existing = set(insp.get_table_names())
    for t in ('change_affected_plants', 'assessment_cost_line', 'change_gate',
              'assessment_activity', 'department_rate'):
        if t in existing:
            op.drop_table(t)
    i_cols = {c['name'] for c in insp.get_columns('change_impacted_items')}
    if 'is_lead' in i_cols:
        op.drop_column('change_impacted_items', 'is_lead')
    r_cols = {c['name'] for c in insp.get_columns('change_requests')}
    for name in ('car_line', 'customer_relevant', 'implementation_mode',
                 'cm_external', 'cm_internal', 'is_series', 'issuer'):
        if name in r_cols:
            op.drop_column('change_requests', name)
    a_cols = {c['name'] for c in insp.get_columns('change_assessments')}
    for name in ('lifecycle_cost', 'approval_comment', 'contact_person', 'producibility'):
        if name in a_cols:
            op.drop_column('change_assessments', name)
