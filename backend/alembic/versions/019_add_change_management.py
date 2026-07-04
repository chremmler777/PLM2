"""Change Management: change_requests, change_impacted_items, change_assessments,
change_attachments, change_changelog.

Revision ID: 019
Revises: 018
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = '019'
down_revision = '018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())
    existing = inspector.get_table_names()

    if 'change_requests' not in existing:
        op.create_table(
            'change_requests',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_number', sa.String(30), nullable=False, unique=True, index=True),
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False, index=True),
            sa.Column('title', sa.String(255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('reason', sa.Text(), nullable=True),
            sa.Column('change_type', sa.String(30), nullable=False, server_default='physical_part'),
            sa.Column('priority', sa.String(20), nullable=False, server_default='medium'),
            sa.Column('data_classification', sa.String(20), nullable=False, server_default='confidential'),
            sa.Column('status', sa.String(20), nullable=False, server_default='captured', index=True),
            sa.Column('lead_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('raised_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('raised_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('customer_response', sa.String(20), nullable=False, server_default='pending'),
            sa.Column('customer_response_at', sa.DateTime(), nullable=True),
            sa.Column('customer_response_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('pm_signed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('pm_signed_at', sa.DateTime(), nullable=True),
            sa.Column('quality_signed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('quality_signed_at', sa.DateTime(), nullable=True),
            sa.Column('estimated_cost', sa.Float(), nullable=True),
            sa.Column('quoted_price', sa.Float(), nullable=True),
            sa.Column('pnl_note', sa.Text(), nullable=True),
            sa.Column('timing_milestone_id', sa.Integer(), sa.ForeignKey('project_milestones.id'), nullable=True),
            sa.Column('released_at', sa.DateTime(), nullable=True),
            sa.Column('released_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('closed_at', sa.DateTime(), nullable=True),
            sa.Column('cancelled_at', sa.DateTime(), nullable=True),
            sa.Column('cancellation_reason', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if 'change_impacted_items' not in existing:
        op.create_table(
            'change_impacted_items',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), nullable=False, index=True),
            sa.Column('part_id', sa.Integer(), sa.ForeignKey('parts.id'), nullable=False, index=True),
            sa.Column('impact_note', sa.Text(), nullable=True),
            sa.Column('eng_level_before', sa.String(50), nullable=True),
            sa.Column('eng_level_after', sa.String(50), nullable=True),
            sa.Column('resulting_revision_id', sa.Integer(), sa.ForeignKey('part_revisions.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        )

    if 'change_assessments' not in existing:
        op.create_table(
            'change_assessments',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), nullable=False, index=True),
            sa.Column('department_id', sa.Integer(), sa.ForeignKey('wf_departments.id'), nullable=False, index=True),
            sa.Column('verdict', sa.String(30), nullable=False, server_default='pending'),
            sa.Column('cost_impact', sa.Float(), nullable=True),
            sa.Column('lead_time_impact_days', sa.Integer(), nullable=True),
            sa.Column('conditions', sa.Text(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('responsible_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('submitted_at', sa.DateTime(), nullable=True),
            sa.Column('submitted_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if 'change_attachments' not in existing:
        op.create_table(
            'change_attachments',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), nullable=False, index=True),
            sa.Column('filename', sa.String(255), nullable=False),
            sa.Column('stored_path', sa.String(500), nullable=False),
            sa.Column('content_type', sa.String(100), nullable=False),
            sa.Column('size_bytes', sa.Integer(), nullable=False),
            sa.Column('sha256', sa.String(64), nullable=False),
            sa.Column('uploaded_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if 'change_changelog' not in existing:
        op.create_table(
            'change_changelog',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('change_id', sa.Integer(), sa.ForeignKey('change_requests.id'), nullable=False, index=True),
            sa.Column('action', sa.String(50), nullable=False),
            sa.Column('action_description', sa.Text(), nullable=False),
            sa.Column('field_name', sa.String(100), nullable=True),
            sa.Column('old_value', sa.Text(), nullable=True),
            sa.Column('new_value', sa.Text(), nullable=True),
            sa.Column('performed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('performed_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('previous_hash', sa.String(64), nullable=True),
            sa.Column('entry_hash', sa.String(64), nullable=True),
        )


def downgrade() -> None:
    for t in ('change_changelog', 'change_attachments', 'change_assessments',
              'change_impacted_items', 'change_requests'):
        op.drop_table(t)
