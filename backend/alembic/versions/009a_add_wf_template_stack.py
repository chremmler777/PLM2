"""Create the stage-based workflow template stack (wf_departments,
wf_templates, wf_stages, wf_steps, wf_step_rasic, wf_template_history).

These tables back the RASIC-driven workflow templates (app/models/workflow.py)
and have existed in the model layer since before this migration chain began,
but no prior migration ever created them — SQLite dev environments only ever
exercised them via Base.metadata.create_all(), never through the alembic
chain, so this was never caught until a from-scratch run against an
enforcing backend (Postgres). user_departments (migration 010) is the first
migration to reference wf_departments, so this is inserted immediately
before it.

Revision ID: 009a
Revises: 009
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = '009a'
down_revision = '009'
branch_labels = None
depends_on = None

_TABLES = (
    "wf_departments", "wf_templates", "wf_stages", "wf_steps",
    "wf_step_rasic", "wf_template_history",
)


def upgrade() -> None:
    existing = set(inspect(op.get_bind()).get_table_names())

    if "wf_departments" not in existing:
        op.create_table(
            'wf_departments',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(50), nullable=False, unique=True),
            sa.Column('flow_type', sa.String(20), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if "wf_templates" not in existing:
        op.create_table(
            'wf_templates',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )

    if "wf_stages" not in existing:
        op.create_table(
            'wf_stages',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('template_id', sa.Integer(), sa.ForeignKey('wf_templates.id'), nullable=False),
            sa.Column('stage_order', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(100), nullable=True),
        )

    if "wf_steps" not in existing:
        op.create_table(
            'wf_steps',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('stage_id', sa.Integer(), sa.ForeignKey('wf_stages.id'), nullable=False),
            sa.Column('step_name', sa.String(100), nullable=False),
            sa.Column('position_in_stage', sa.Integer(), nullable=False),
        )

    if "wf_step_rasic" not in existing:
        op.create_table(
            'wf_step_rasic',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('step_id', sa.Integer(), sa.ForeignKey('wf_steps.id'), nullable=False),
            sa.Column('department_id', sa.Integer(), sa.ForeignKey('wf_departments.id'), nullable=False),
            sa.Column('rasic_letter', sa.String(1), nullable=False),
        )

    if "wf_template_history" not in existing:
        op.create_table(
            'wf_template_history',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('template_id', sa.Integer(), sa.ForeignKey('wf_templates.id'), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('snapshot', sa.JSON(), nullable=False),
            sa.Column('changed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('changed_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('change_note', sa.Text(), nullable=True),
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table)
