"""075: project customer file naming + note on revision files.

projects.customer_naming: "vw" | "scout" | NULL, the filename convention used
to read the customer index and data kind on upload.
revision_files.kind: data kind from the filename (PCA, DMU, DRW, G02 ...).
revision_files.note: free text shown under the filename.

Revision ID: 075
Revises: 074
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "customer_naming" not in _cols(insp, "projects"):
        op.add_column("projects", sa.Column("customer_naming", sa.String(20), nullable=True))
    if "kind" not in _cols(insp, "revision_files"):
        op.add_column("revision_files", sa.Column("kind", sa.String(10), nullable=True))
    if "note" not in _cols(insp, "revision_files"):
        op.add_column("revision_files", sa.Column("note", sa.String(500), nullable=True))


def downgrade() -> None:
    insp = inspect(op.get_bind())
    for col in ("note", "kind"):
        if col in _cols(insp, "revision_files"):
            op.drop_column("revision_files", col)
    if "customer_naming" in _cols(insp, "projects"):
        op.drop_column("projects", "customer_naming")
