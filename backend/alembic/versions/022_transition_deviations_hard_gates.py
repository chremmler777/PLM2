"""Transition deviations table + seed gate rows for in-flight changes.

Revision ID: 022
Revises: 021
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None

GATE_TARGETS = {"feasibility": "in_assessment", "budget": "costing",
                "release": "in_implementation"}
STATUS_ORDER = ["captured", "in_assessment", "costing", "quoted", "approved",
                "in_implementation", "in_validation", "released", "closed"]


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = insp.get_table_names()

    if "change_transition_deviations" not in tables:
        op.create_table(
            "change_transition_deviations",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("change_id", sa.Integer,
                      sa.ForeignKey("change_requests.id"), nullable=False, index=True),
            sa.Column("to_status", sa.String(30), nullable=False),
            sa.Column("reason", sa.Text, nullable=False),
            sa.Column("status", sa.String(15), nullable=False, server_default="pending"),
            sa.Column("proposed_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("proposed_at", sa.DateTime, nullable=True),
            sa.Column("decided_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
            sa.Column("decided_at", sa.DateTime, nullable=True),
            sa.Column("decision_note", sa.Text, nullable=True),
        )

    # Seed gate rows for in-flight changes at their current effective state:
    # a gate whose target status was already reached (per changelog, or implied
    # by the current status on the linear path) is seeded "yes", else "na".
    if "change_gate" in tables and "change_requests" in tables:
        changes = bind.execute(
            sa.text("SELECT id, status FROM change_requests")).fetchall()
        have = {(r[0], r[1]) for r in bind.execute(
            sa.text("SELECT change_id, gate_key FROM change_gate")).fetchall()}
        reached: dict = {}
        for cid, nv in bind.execute(sa.text(
                "SELECT change_id, new_value FROM change_changelog "
                "WHERE field_name = 'status'")).fetchall():
            reached.setdefault(cid, set()).add((nv or "").strip('"'))
        for cid, status in changes:
            seen = reached.get(cid, set())
            for key, target in GATE_TARGETS.items():
                if (cid, key) in have:
                    continue
                passed = target in seen or (
                    status in STATUS_ORDER
                    and STATUS_ORDER.index(status) >= STATUS_ORDER.index(target))
                bind.execute(sa.text(
                    "INSERT INTO change_gate (change_id, gate_key, decision) "
                    "VALUES (:c, :k, :d)"),
                    {"c": cid, "k": key, "d": "yes" if passed else "na"})


def downgrade() -> None:
    op.drop_table("change_transition_deviations")
