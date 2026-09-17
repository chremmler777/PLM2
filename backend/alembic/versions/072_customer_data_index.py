"""072: customer data index — E<n>/<n> names, part lifecycle phase.

Adds the customer-statement columns on part_revisions, the lifecycle phase on
parts, then renames every legacy RFQ/ENG/IND/ECR revision per part in
creation order (see app.services.revision_naming.legacy_rename). Ids and
foreign keys are untouched. Forward-only.

Revision ID: 072
Revises: 071
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app.services.revision_naming import WINCARAT_BASELINE, legacy_rename

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None


def rename_legacy_revisions(conn) -> None:
    rows = conn.execute(sa.text(
        "SELECT id, part_id, revision_name, phase, parent_revision_id, created_at "
        "FROM part_revisions ORDER BY part_id, created_at, id")).fetchall()
    by_part: dict[int, list] = {}
    for rid, part_id, name, phase, parent_id, created_at in rows:
        by_part.setdefault(part_id, []).append((rid, name, phase, parent_id, created_at))
    for part_id, part_rows in by_part.items():
        renamed = legacy_rename(part_rows)
        old_names = {rid: name for rid, name, _, _, _ in part_rows}
        for rid, (new_name, new_phase) in renamed.items():
            is_minor = "." in new_name
            if old_names[rid] == WINCARAT_BASELINE:
                source = "import"
            else:
                source = "internal" if is_minor else "customer"
            conn.execute(sa.text(
                "UPDATE part_revisions SET revision_name = :n, phase = :p, source = :s "
                "WHERE id = :id"),
                {"n": new_name, "p": new_phase, "id": rid, "s": source})
        # A part whose data came in as a WinCarat baseline is already running
        # series production.
        if any(name == WINCARAT_BASELINE for name in old_names.values()):
            conn.execute(sa.text(
                "UPDATE parts SET lifecycle_phase = 'series' WHERE id = :pid"), {"pid": part_id})
        # The old change engine spawned ECR proposals without a parent link.
        # Point every orphan minor at the major it now belongs to, if that
        # major exists on the part.
        major_ids = {name: rid for rid, (name, _) in renamed.items() if "." not in name}
        for rid, name, _phase, parent_id, _ in part_rows:
            new_name = renamed[rid][0]
            if "." in new_name and parent_id is None:
                major_id = major_ids.get(new_name.split(".")[0])
                if major_id is not None:
                    conn.execute(sa.text(
                        "UPDATE part_revisions SET parent_revision_id = :pid WHERE id = :id"),
                        {"pid": major_id, "id": rid})


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = insp.get_table_names()
    if "part_revisions" in tables:
        cols = {c["name"] for c in insp.get_columns("part_revisions")}
        for name, col in [
            ("customer_index", sa.Column("customer_index", sa.String(20), nullable=True)),
            ("customer_statement", sa.Column("customer_statement", sa.String(20), nullable=True)),
            ("customer_received_at", sa.Column("customer_received_at", sa.Date(), nullable=True)),
            ("source", sa.Column("source", sa.String(20), nullable=False, server_default="internal")),
            ("part_phase_at_receipt", sa.Column("part_phase_at_receipt", sa.String(20), nullable=False, server_default="rfq")),
        ]:
            if name not in cols:
                op.add_column("part_revisions", col)
    if "parts" in tables:
        cols = {c["name"] for c in insp.get_columns("parts")}
        if "lifecycle_phase" not in cols:
            op.add_column("parts", sa.Column("lifecycle_phase", sa.String(20), nullable=False, server_default="rfq"))
        if "nominated_at" not in cols:
            op.add_column("parts", sa.Column("nominated_at", sa.Date(), nullable=True))
        if "sop_at" not in cols:
            op.add_column("parts", sa.Column("sop_at", sa.Date(), nullable=True))
    if "part_revisions" in tables:
        rename_legacy_revisions(bind)


def downgrade() -> None:
    pass  # forward-only
