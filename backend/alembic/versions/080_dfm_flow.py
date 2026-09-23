"""080: DFM flow, message kind and reply link on dfm_entries.

kind: original | forward | answer | question (existing rows become original).
reply_to_id: the message a forward, answer or question refers to.

Revision ID: 080
Revises: 079
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None

INDEX = "ix_dfm_entries_reply_to_id"


def _cols(insp):
    return {c["name"] for c in insp.get_columns("dfm_entries")}


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "dfm_entries" not in set(insp.get_table_names()):
        return
    existing = _cols(insp)
    # batch mode: adding reply_to_id (an FK column) needs a table rebuild on SQLite
    with op.batch_alter_table("dfm_entries") as batch:
        if "kind" not in existing:
            batch.add_column(sa.Column("kind", sa.String(20), nullable=False, server_default="original"))
        if "reply_to_id" not in existing:
            batch.add_column(sa.Column(
                "reply_to_id", sa.Integer(),
                sa.ForeignKey("dfm_entries.id", name="fk_dfm_entries_reply_to_id_dfm_entries"), nullable=True))
    indexes = {i["name"] for i in inspect(op.get_bind()).get_indexes("dfm_entries")}
    if INDEX not in indexes:
        op.create_index(INDEX, "dfm_entries", ["reply_to_id"])


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if "dfm_entries" not in set(insp.get_table_names()):
        return
    existing = _cols(insp)
    if INDEX in {i["name"] for i in insp.get_indexes("dfm_entries")}:
        op.drop_index(INDEX, table_name="dfm_entries")
    # batch mode: dropping reply_to_id (an FK column) needs a table rebuild on SQLite
    with op.batch_alter_table("dfm_entries") as batch:
        if "reply_to_id" in existing:
            batch.drop_column("reply_to_id")
        if "kind" in existing:
            batch.drop_column("kind")
