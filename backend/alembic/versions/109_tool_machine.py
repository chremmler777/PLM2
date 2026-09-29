"""109: the press chosen for a tool.

parts.tool_machine: free text naming the press (or presses) the tool is
planned on, e.g. "KM 350-1 (KM 350/2000 CX)" as picked in the RFQ2 Tool
Layout Designer. Tools only. Not the MachineDB assigned press
(tool_tonnage_mdb_machine), which the tonnage sync keeps.

Guarded (a column that exists already is left alone), dialect-neutral.

Revision ID: 109
Revises: 108
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "109"
down_revision = "108"
branch_labels = None
depends_on = None

TABLE = "parts"


def _cols(bind):
    return {c["name"] for c in inspect(bind).get_columns(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    if TABLE not in set(inspect(bind).get_table_names()):
        return
    if "tool_machine" not in _cols(bind):
        op.add_column(TABLE, sa.Column("tool_machine", sa.String(255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if TABLE not in set(inspect(bind).get_table_names()):
        return
    if "tool_machine" in _cols(bind):
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_column("tool_machine")
