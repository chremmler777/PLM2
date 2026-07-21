"""Strict lessons lifecycle: in_review -> in_work -> verification -> closed.

Adds target_date, accepted_at, verification_requested_at, reject fields,
escalation tracking, lesson_files evidence table. Migrates old statuses:
draft/submitted -> in_review, approved -> in_work, implemented -> verification.

Revision ID: 017
Revises: 016
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa


revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    inspector = inspect(op.get_bind())

    lesson_cols = {c['name'] for c in inspector.get_columns('lessons_learned')}
    new_cols = {
        'target_date': sa.Column('target_date', sa.DateTime(), nullable=True),
        'accepted_at': sa.Column('accepted_at', sa.DateTime(), nullable=True),
        'verification_requested_at': sa.Column('verification_requested_at', sa.DateTime(), nullable=True),
        'reject_category': sa.Column('reject_category', sa.String(30), nullable=True),
        'reject_reason': sa.Column('reject_reason', sa.Text(), nullable=True),
        'last_escalated_at': sa.Column('last_escalated_at', sa.DateTime(), nullable=True),
    }
    for name, col in new_cols.items():
        if name not in lesson_cols:
            op.add_column('lessons_learned', col)

    if 'lesson_files' not in inspector.get_table_names():
        op.create_table(
            'lesson_files',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('lesson_id', sa.Integer(), sa.ForeignKey('lessons_learned.id'), nullable=False, index=True),
            sa.Column('filename', sa.String(255), nullable=False),
            sa.Column('stored_path', sa.String(500), nullable=False),
            sa.Column('content_type', sa.String(100), nullable=True),
            sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('sha256', sa.String(64), nullable=True),
            sa.Column('uploaded_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    # Data migration to the new state machine
    conn = op.get_bind()
    # +30 days date arithmetic isn't portable: SQLite uses datetime(x, '+30 days'),
    # Postgres uses interval arithmetic.
    if conn.dialect.name == "postgresql":
        plus_30_days = "(COALESCE(approved_at, created_at) + INTERVAL '30 days')"
    else:
        plus_30_days = "datetime(COALESCE(approved_at, created_at), '+30 days')"

    conn.execute(sa.text(
        "UPDATE lessons_learned SET status = 'in_review' WHERE status IN ('draft', 'submitted')"
    ))
    # approved lessons were accepted into work; keep the accept timestamp,
    # default a target 30 days after acceptance so the in_work invariant holds
    conn.execute(sa.text(
        "UPDATE lessons_learned SET status = 'in_work', "
        "accepted_at = COALESCE(approved_at, created_at), "
        f"target_date = COALESCE(target_date, {plus_30_days}) "
        "WHERE status = 'approved'"
    ))
    # implemented = work finished, awaiting verification under the new flow
    conn.execute(sa.text(
        "UPDATE lessons_learned SET status = 'verification', "
        "accepted_at = COALESCE(approved_at, created_at), "
        f"target_date = COALESCE(target_date, {plus_30_days}), "
        "verification_requested_at = CURRENT_TIMESTAMP "
        "WHERE status = 'implemented'"
    ))


def downgrade() -> None:
    op.drop_table('lesson_files')
    op.drop_column('lessons_learned', 'last_escalated_at')
    op.drop_column('lessons_learned', 'reject_reason')
    op.drop_column('lessons_learned', 'reject_category')
    op.drop_column('lessons_learned', 'verification_requested_at')
    op.drop_column('lessons_learned', 'accepted_at')
    op.drop_column('lessons_learned', 'target_date')
