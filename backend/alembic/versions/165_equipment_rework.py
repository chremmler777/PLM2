"""165: equipment amounts, obsolete items and a kind on the history log.

part_relations.quantity: how many of the article an assembly station or EOAT
takes in per cycle (assembles links; checks and produces leave it empty).
parts.obsolete_at / obsolete_by: an obsolete gauge or equipment stays in PLM,
greyed, and is no longer offered for new links.
revision_changelogs.change_kind: correction | change | obsolete | reactivated,
so the existing log says what kind of change an equipment entry was.

Existing rows keep NULL everywhere: nothing is obsolete, old log rows have no
kind, and the existing assembles links are set to quantity 1.

Revision ID: 165
Revises: 164
"""
import sqlalchemy as sa
from alembic import op

revision = "165"
down_revision = "164"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("part_relations", sa.Column("quantity", sa.Numeric(10, 3), nullable=True))
    op.execute("UPDATE part_relations SET quantity = 1 WHERE relation_type = 'assembles'")
    op.add_column("parts", sa.Column("obsolete_at", sa.DateTime(), nullable=True))
    op.add_column("parts", sa.Column("obsolete_by", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_parts_obsolete_by_users", "parts", "users", ["obsolete_by"], ["id"])
    op.add_column("revision_changelogs", sa.Column("change_kind", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("revision_changelogs", "change_kind")
    op.drop_constraint("fk_parts_obsolete_by_users", "parts", type_="foreignkey")
    op.drop_column("parts", "obsolete_by")
    op.drop_column("parts", "obsolete_at")
    op.drop_column("part_relations", "quantity")
