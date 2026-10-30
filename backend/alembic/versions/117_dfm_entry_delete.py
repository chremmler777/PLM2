"""117: DFM entry soft delete.

dfm_entries: deleted_at, deleted_by (FK users.id), delete_reason. A deleted
entry is hidden everywhere; its row, files on disk and audit events stay.

The plain unique constraint on supersedes_id (078) becomes a partial unique
index uq_dfm_entries_supersedes_live (WHERE deleted_at IS NULL): when an
update is deleted, the entry it superseded is current again and can be
updated anew without the deleted row blocking it.

Guarded (whatever exists already is left alone), dialect-neutral. On SQLite
the unique constraint of 078 is unnamed, so the table is rebuilt without it.

Revision ID: 117
Revises: 116
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "117"
down_revision = "116"
branch_labels = None
depends_on = None

TABLE = "dfm_entries"
INDEX = "uq_dfm_entries_supersedes_live"
FK_DELETED_BY = "fk_dfm_entries_deleted_by"


def _supersedes_uniques(insp) -> list:
    return [c for c in insp.get_unique_constraints(TABLE) if list(c.get("column_names") or []) == ["supersedes_id"]]


def _drop_supersedes_unique(bind) -> None:
    insp = inspect(bind)
    uniques = _supersedes_uniques(insp)
    if not uniques:
        return
    if bind.dialect.name == "sqlite":
        # rebuild from a reflected copy without the (possibly unnamed) constraint
        table = sa.Table(TABLE, sa.MetaData(), autoload_with=bind)
        for c in list(table.constraints):
            if isinstance(c, sa.UniqueConstraint) and [col.name for col in c.columns] == ["supersedes_id"]:
                table.constraints.discard(c)
        with op.batch_alter_table(TABLE, copy_from=table, recreate="always"):
            pass
        return
    for c in uniques:
        op.drop_constraint(c["name"], TABLE, type_="unique")


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if TABLE not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns(TABLE)}
    with op.batch_alter_table(TABLE) as batch:
        if "deleted_at" not in cols:
            batch.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        if "deleted_by" not in cols:
            batch.add_column(sa.Column("deleted_by", sa.Integer(), nullable=True))
            batch.create_foreign_key(FK_DELETED_BY, "users", ["deleted_by"], ["id"])
        if "delete_reason" not in cols:
            batch.add_column(sa.Column("delete_reason", sa.String(500), nullable=True))
    _drop_supersedes_unique(bind)
    if INDEX not in {i["name"] for i in inspect(bind).get_indexes(TABLE)}:
        # partial index: plain SQL, the same on PostgreSQL and SQLite
        bind.execute(sa.text(f"CREATE UNIQUE INDEX {INDEX} ON {TABLE} (supersedes_id) WHERE deleted_at IS NULL"))


def downgrade() -> None:
    """Deleted entries come back as live rows (their deleted_* columns go), so
    a deleted update must not collide with a later one: the unique constraint
    is only restored when no two rows share a supersedes_id."""
    bind = op.get_bind()
    insp = inspect(bind)
    if TABLE not in set(insp.get_table_names()):
        return
    if INDEX in {i["name"] for i in insp.get_indexes(TABLE)}:
        op.drop_index(INDEX, table_name=TABLE)
    cols = {c["name"] for c in insp.get_columns(TABLE)}
    with op.batch_alter_table(TABLE) as batch:
        if "deleted_by" in cols:
            batch.drop_column("deleted_by")  # takes its foreign key with it
        if "deleted_at" in cols:
            batch.drop_column("deleted_at")
        if "delete_reason" in cols:
            batch.drop_column("delete_reason")
    dupes = bind.execute(sa.text(
        f"SELECT 1 FROM {TABLE} WHERE supersedes_id IS NOT NULL GROUP BY supersedes_id HAVING COUNT(*) > 1"
    )).first()
    if dupes is None and not _supersedes_uniques(inspect(bind)):
        with op.batch_alter_table(TABLE) as batch:
            batch.create_unique_constraint("uq_dfm_entries_supersedes_id", ["supersedes_id"])
