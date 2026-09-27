"""108: the tool's press tonnage from MachineDB and TWOS.

parts gets six nullable columns the tool tonnage sync fills
(tool_tonnage_service): the MachineDB tonnage with its basis ("assigned"
press, else "qualified_min"), the assigned press's name and when it was
fetched, and the TWOS press tonnage with when it was fetched. Costing
derives a change's default machine class from them (MachineDB first, then
TWOS, then the tonnage typed in plm2). No data is written here: the sync
fills them.

Guarded (a column that exists already is left alone), dialect-neutral.
Downgrade drops the six columns.

Revision ID: 108
Revises: 107
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "108"
down_revision = "107"
branch_labels = None
depends_on = None

TABLE = "parts"
COLUMNS = (
    ("tool_tonnage_mdb_t", sa.Float()),
    ("tool_tonnage_mdb_basis", sa.String(20)),
    ("tool_tonnage_mdb_machine", sa.String(120)),
    ("tool_tonnage_mdb_at", sa.DateTime()),
    ("tool_tonnage_twos_t", sa.Float()),
    ("tool_tonnage_twos_at", sa.DateTime()),
)


def _cols(bind):
    return {c["name"] for c in inspect(bind).get_columns(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    if TABLE not in set(inspect(bind).get_table_names()):
        return
    have = _cols(bind)
    for name, type_ in COLUMNS:
        if name not in have:
            op.add_column(TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if TABLE not in set(inspect(bind).get_table_names()):
        return
    have = [name for name, _ in COLUMNS if name in _cols(bind)]
    if not have:
        return
    with op.batch_alter_table(TABLE) as batch:
        for name in have:
            batch.drop_column(name)
