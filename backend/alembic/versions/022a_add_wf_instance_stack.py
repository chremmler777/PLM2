"""Create wf_instances and wf_instance_tasks (workflow instance execution,
"Phase 3c" in app/models/workflow.py).

Like the wf_template stack (see migration 009a), these tables have existed
in the model layer for a long time but were never created by any migration
— only exercised via Base.metadata.create_all() in SQLite dev. Migration 024
ALTERs wf_instance_tasks and migration 027 ALTERs both tables, so both must
already exist by then; this is inserted here (after change_requests exists,
from migration 019) using the pre-024/pre-027 column shapes so those later
migrations' guarded add_column/alter_column steps still apply on top.

Revision ID: 022a
Revises: 022
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = '022a'
down_revision = '022'
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(inspect(op.get_bind()).get_table_names())

    if "wf_instances" not in existing:
        op.create_table(
            'wf_instances',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('template_id', sa.Integer(), sa.ForeignKey('wf_templates.id'), nullable=False),
            sa.Column('part_revision_id', sa.Integer(), sa.ForeignKey('part_revisions.id'), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='active'),
            sa.Column('current_stage_order', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('started_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('started_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('canceled_at', sa.DateTime(), nullable=True),
            sa.Column('canceled_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('cancel_reason', sa.Text(), nullable=True),
        )

    if "wf_instance_tasks" not in existing:
        op.create_table(
            'wf_instance_tasks',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('instance_id', sa.Integer(), sa.ForeignKey('wf_instances.id'), nullable=False),
            sa.Column('stage_order', sa.Integer(), nullable=False),
            sa.Column('step_id', sa.Integer(), sa.ForeignKey('wf_steps.id'), nullable=False),
            sa.Column('department_id', sa.Integer(), sa.ForeignKey('wf_departments.id'), nullable=False),
            sa.Column('rasic_letter', sa.String(1), nullable=False),
            sa.Column('status', sa.String(20), nullable=False),
            sa.Column('is_actionable', sa.Boolean(), nullable=False),
            sa.Column('completed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('decision', sa.String(20), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table('wf_instance_tasks')
    op.drop_table('wf_instances')
