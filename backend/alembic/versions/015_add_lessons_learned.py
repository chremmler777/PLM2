"""Add lessons learned tables (lessons_learned, lesson_actions, lesson_comments).

Revision ID: 015
Revises: 014
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa


revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())
    existing = inspector.get_table_names()

    if 'lessons_learned' not in existing:
        op.create_table(
            'lessons_learned',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('title', sa.String(200), nullable=False),
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=True, index=True),
            sa.Column('project_ref', sa.String(200), nullable=True),
            sa.Column('category', sa.String(30), nullable=False, server_default='other'),
            sa.Column('lesson_type', sa.String(20), nullable=False, server_default='problem'),
            sa.Column('severity', sa.String(10), nullable=False, server_default='medium'),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('root_cause', sa.Text(), nullable=True),
            sa.Column('recommendation', sa.Text(), nullable=True),
            sa.Column('tags', sa.String(300), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='draft', index=True),
            sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('department_id', sa.Integer(), sa.ForeignKey('wf_departments.id'), nullable=True),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('submitted_at', sa.DateTime(), nullable=True),
            sa.Column('closed_at', sa.DateTime(), nullable=True),
        )

    if 'lesson_actions' not in existing:
        op.create_table(
            'lesson_actions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('lesson_id', sa.Integer(), sa.ForeignKey('lessons_learned.id'), nullable=False, index=True),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('assignee_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('due_date', sa.DateTime(), nullable=True),
            sa.Column('status', sa.String(10), nullable=False, server_default='open'),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if 'lesson_comments' not in existing:
        op.create_table(
            'lesson_comments',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('lesson_id', sa.Integer(), sa.ForeignKey('lessons_learned.id'), nullable=False, index=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('body', sa.Text(), nullable=False),
            sa.Column('is_system', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table('lesson_comments')
    op.drop_table('lesson_actions')
    op.drop_table('lessons_learned')
