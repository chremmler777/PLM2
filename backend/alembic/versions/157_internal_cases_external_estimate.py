"""157: internal modification cases are external estimates (Christoph 2026-11-08).

Data only: "I don't have internal change in there so this needs to be as
external estimate". A case carried from the assessment's 'Internal
modification' row was an own-time line (hours); it is now costed exactly like
an external change estimate: kind external, pricing estimate, 1 job, vendor
KTX Toolshop (if none), hours cleared (a carried external line has none).
The notes keep the row label, which tells internal from external cases.

Repeatable: only own_time lines whose notes start with the carried row label
change. Downgrade is a no-op (a converted line cannot be told from a new one).

Revision ID: 157
Revises: 156
"""
from alembic import op

revision = "157"
down_revision = "156"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE costing_positions SET kind = 'external', pricing = 'estimate', "
        "quantity = 1, quantity_unit = 'job', "
        "vendor_name = COALESCE(vendor_name, 'KTX Toolshop'), hours = NULL "
        "WHERE kind = 'own_time' AND ("
        "notes LIKE 'From the assessment: Internal modification%' OR "
        "notes LIKE 'From the assessment: Interne Änderung%')")


def downgrade() -> None:
    pass
