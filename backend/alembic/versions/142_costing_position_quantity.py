"""142: quantity + unit on a costing position (close-out A3-07, spec §4
[R3] "Each: quantity + unit + basis pick").

Nullable: positions entered before this migration keep NULL (in-flight
changes progress as they are); a new money position names how many of what
(ASSESSMENT_V2, costing_position_service.create_position).

Revision ID: 142
Revises: 141
"""
import sqlalchemy as sa
from alembic import op

revision = "142"
down_revision = "141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("costing_positions", sa.Column("quantity", sa.Float(), nullable=True))
    op.add_column("costing_positions",
                  sa.Column("quantity_unit", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("costing_positions", "quantity_unit")
    op.drop_column("costing_positions", "quantity")
