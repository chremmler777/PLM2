"""Lessons governance: effectiveness verification, reminders, reuse references.

Revision ID: 016
Revises: 015
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa


revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())

    lesson_cols = {c['name'] for c in inspector.get_columns('lessons_learned')}
    if 'approved_at' not in lesson_cols:
        op.add_column('lessons_learned', sa.Column('approved_at', sa.DateTime(), nullable=True))
    if 'effectiveness_note' not in lesson_cols:
        op.add_column('lessons_learned', sa.Column('effectiveness_note', sa.Text(), nullable=True))
    if 'effectiveness_verified_by' not in lesson_cols:
        # No FK constraint in ADD COLUMN — SQLite cannot add FKs to existing tables
        op.add_column('lessons_learned', sa.Column('effectiveness_verified_by', sa.Integer(), nullable=True))
    if 'effectiveness_verified_at' not in lesson_cols:
        op.add_column('lessons_learned', sa.Column('effectiveness_verified_at', sa.DateTime(), nullable=True))

    action_cols = {c['name'] for c in inspector.get_columns('lesson_actions')}
    if 'last_reminded_at' not in action_cols:
        op.add_column('lesson_actions', sa.Column('last_reminded_at', sa.DateTime(), nullable=True))

    if 'lesson_references' not in inspector.get_table_names():
        op.create_table(
            'lesson_references',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('lesson_id', sa.Integer(), sa.ForeignKey('lessons_learned.id'), nullable=False, index=True),
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False, index=True),
            sa.Column('milestone_id', sa.Integer(), sa.ForeignKey('project_milestones.id'), nullable=True),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table('lesson_references')
    op.drop_column('lesson_actions', 'last_reminded_at')
    op.drop_column('lessons_learned', 'effectiveness_verified_at')
    op.drop_column('lessons_learned', 'effectiveness_verified_by')
    op.drop_column('lessons_learned', 'effectiveness_note')
    op.drop_column('lessons_learned', 'approved_at')
