"""036: parts.customer_part_number + backfill for VW426 Atlas (project 1864).

The customer's own number is what every customer-facing conversation runs on
(change requests, PPAP, deviations), so it belongs on the part rather than in a
sheet. VW's numbers are written dotted: 3CR.919.491.A.

The Atlas backfill comes from import_atlas.py's TOOLS table, where the codes
were parked on the producing tool. Each article maps 1:1 — the leading letter
in that table (I_, C_, G_, ...) is a variant index, not part of the number, and
is dropped. Tools themselves keep no customer number; the customer buys parts.

Revision ID: 036
Revises: 035
"""
from alembic import op
import sqlalchemy as sa

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None

# internal part number -> customer number, VW426 Atlas (TWOS project 1864)
ATLAS_CUSTOMER_NUMBERS = {
    "10-3457-001-0": "3CR.919.491.A",   # PDC Inner Bracket LH
    "10-3457-001-1": "3CR.919.491.C",   # PDC Inner Bracket (Peak) LH
    "10-3457-002-0": "3CR.919.492.A",   # PDC Inner Bracket RH
    "10-3457-002-1": "3CR.919.492.C",   # PDC Inner Bracket (Peak) RH
    "20-3450-001-0": "3CR.853.653",     # Grill Carrier
    "20-3451-001-0": "3CS.807.643",     # Lat Lower Cover LH
    "20-3451-002-0": "3CS.807.644",     # Lat Lower Cover RH
    "20-3452-001-0": "3CR.807.531.A",   # Upper Cladding
    "20-3453-001-0": "3CR.807.532.A",   # Lower Cladding
    "20-3454-001-0": "3CR.807.425",     # RR Cladding (Basis)
    "20-3455-001-0": "3CR.807.425.B",   # RR Cladding (Peak)
    "20-3456-001-0": "3CS.807.425",     # RR Undertray (Cross)
}


def upgrade() -> None:
    op.add_column("parts", sa.Column("customer_part_number", sa.String(100), nullable=True))
    op.create_index("ix_parts_customer_part_number", "parts", ["customer_part_number"])

    bind = op.get_bind()
    project_id = bind.execute(
        sa.text("SELECT id FROM projects WHERE code = '1864'")).scalar()
    if project_id is None:
        return  # Atlas not seeded in this database; nothing to backfill.
    for part_number, customer_number in ATLAS_CUSTOMER_NUMBERS.items():
        bind.execute(
            sa.text("UPDATE parts SET customer_part_number = :c "
                    "WHERE project_id = :p AND part_number = :n"),
            {"c": customer_number, "p": project_id, "n": part_number},
        )


def downgrade() -> None:
    op.drop_index("ix_parts_customer_part_number", table_name="parts")
    op.drop_column("parts", "customer_part_number")
