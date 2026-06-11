"""SEP Q-Gate module: sep_gates, sep_work_items, sep_item_audits, sep_risks.

Digitizes the GB-DP-0001 SEP matrix as a strict stage-gate system per project.

Revision ID: 018
Revises: 017
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa


revision = '018'
down_revision = '017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())
    existing = inspector.get_table_names()

    if 'sep_gates' not in existing:
        op.create_table(
            'sep_gates',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False, index=True),
            sa.Column('code', sa.String(20), nullable=False),
            sa.Column('seq', sa.Integer(), nullable=False),
            sa.Column('phase_de', sa.String(200), nullable=False),
            sa.Column('phase_en', sa.String(200), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='pending', index=True),
            sa.Column('target_date', sa.DateTime(), nullable=True),
            sa.Column('milestone_id', sa.Integer(), sa.ForeignKey('project_milestones.id'), nullable=True),
            sa.Column('pm_signed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('pm_signed_at', sa.DateTime(), nullable=True),
            sa.Column('quality_signed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('quality_signed_at', sa.DateTime(), nullable=True),
            sa.Column('closed_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if 'sep_work_items' not in existing:
        op.create_table(
            'sep_work_items',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('gate_id', sa.Integer(), sa.ForeignKey('sep_gates.id'), nullable=False, index=True),
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False, index=True),
            sa.Column('item_no', sa.Integer(), nullable=False),
            sa.Column('title_de', sa.Text(), nullable=False),
            sa.Column('title_en', sa.Text(), nullable=False),
            sa.Column('psp_no', sa.String(40), nullable=True),
            sa.Column('department', sa.String(80), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='open', index=True),
            sa.Column('remark', sa.Text(), nullable=True),
            sa.Column('responsible_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True, index=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if 'sep_item_audits' not in existing:
        op.create_table(
            'sep_item_audits',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('item_id', sa.Integer(), sa.ForeignKey('sep_work_items.id'), nullable=False, index=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('field', sa.String(30), nullable=False),
            sa.Column('old_value', sa.Text(), nullable=True),
            sa.Column('new_value', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if 'sep_risks' not in existing:
        op.create_table(
            'sep_risks',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('gate_id', sa.Integer(), sa.ForeignKey('sep_gates.id'), nullable=False, index=True),
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False, index=True),
            sa.Column('effect', sa.Text(), nullable=False),
            sa.Column('q_impact', sa.Float(), nullable=False, server_default='0'),
            sa.Column('c_impact', sa.Float(), nullable=False, server_default='0'),
            sa.Column('s_impact', sa.Float(), nullable=False, server_default='0'),
            sa.Column('probability', sa.Float(), nullable=False, server_default='0'),
            sa.Column('countermeasure', sa.Text(), nullable=True),
            sa.Column('due_date', sa.DateTime(), nullable=True),
            sa.Column('responsible_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='open'),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table('sep_risks')
    op.drop_table('sep_item_audits')
    op.drop_table('sep_work_items')
    op.drop_table('sep_gates')
