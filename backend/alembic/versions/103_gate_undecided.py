"""103: a D1 gate nobody has decided is undecided (NULL), not 'n/a'.

The release gate is seeded when a change is created so it guards the
release from day one. It used to be seeded with decision 'na', so a new
change read "Technical release not answered Yes (it is n/a)" as if someone
had set it n/a. The column becomes nullable without a server default and
the seeded rows nobody ever touched (no decider, no decision time) are set
to NULL. A gate with no 'yes' still holds its transition, whatever it reads.

Revision ID: 103
Revises: 102
"""
from alembic import op
import sqlalchemy as sa

revision = "103"
down_revision = "102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("change_gate") as b:
        b.alter_column("decision", existing_type=sa.String(10),
                       nullable=True, server_default=None)
    op.execute("UPDATE change_gate SET decision = NULL "
               "WHERE decision = 'na' AND decided_by IS NULL AND decided_at IS NULL")


def downgrade() -> None:
    op.execute("UPDATE change_gate SET decision = 'na' WHERE decision IS NULL")
    with op.batch_alter_table("change_gate") as b:
        b.alter_column("decision", existing_type=sa.String(10),
                       nullable=False, server_default="na")
