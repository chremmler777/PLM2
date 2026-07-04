"""Add suppliers master table and parts.supplier_id; backfill from free text.

Revision ID: 013
Revises: 012
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa


revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)

    if 'suppliers' not in inspector.get_table_names():
        op.create_table(
            'suppliers',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=True),
            sa.Column('name', sa.String(255), nullable=False, unique=True, index=True),
            sa.Column('code', sa.String(50), nullable=True),
            sa.Column('contact_name', sa.String(255), nullable=True),
            sa.Column('contact_email', sa.String(255), nullable=True),
            sa.Column('phone', sa.String(50), nullable=True),
            sa.Column('address', sa.Text(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        )

    parts_columns = [c['name'] for c in inspector.get_columns('parts')]
    if 'supplier_id' not in parts_columns:
        # Plain integer: SQLite cannot ALTER-add a column with an FK constraint
        op.add_column('parts', sa.Column('supplier_id', sa.Integer(), nullable=True))

    # Backfill: distinct free-text supplier names become master records
    bind.execute(sa.text(
        "INSERT INTO suppliers (name, is_active, created_at) "
        "SELECT DISTINCT TRIM(supplier), TRUE, CURRENT_TIMESTAMP FROM parts "
        "WHERE supplier IS NOT NULL AND TRIM(supplier) != '' "
        "AND TRIM(supplier) NOT IN (SELECT name FROM suppliers)"
    ))
    bind.execute(sa.text(
        "UPDATE parts SET supplier_id = "
        "(SELECT s.id FROM suppliers s WHERE s.name = TRIM(parts.supplier)) "
        "WHERE supplier IS NOT NULL AND TRIM(supplier) != ''"
    ))


def downgrade() -> None:
    op.drop_column('parts', 'supplier_id')
    op.drop_table('suppliers')
