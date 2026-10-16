"""139: the customer flip's reason in plain words (close-out A2-09, R37).

Data only: a flip from Quality's PPAP 'yes' stored the raw key
"ppap_decision yes: the customer must be told", which the flip card and the
refusals showed as is. It now reads "Quality answered yes to the PPAP
question", the words new flips are stored with.

Repeatable: only rows still carrying the raw key change.

Revision ID: 139
Revises: 138
"""
from alembic import op

revision = "139"
down_revision = "138"
branch_labels = None
depends_on = None

OLD = "ppap_decision yes: the customer must be told"
NEW = "Quality answered yes to the PPAP question"


def upgrade() -> None:
    op.execute(f"UPDATE change_requests SET customer_flip_reason = '{NEW}' "
               f"WHERE customer_flip_reason = '{OLD}'")


def downgrade() -> None:
    op.execute(f"UPDATE change_requests SET customer_flip_reason = '{OLD}' "
               f"WHERE customer_flip_reason = '{NEW}'")
