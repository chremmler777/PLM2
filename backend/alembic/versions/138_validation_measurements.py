"""138: computed validation checks (ECR-solid §10, lane L7, switch RELEASE_V2).

Schema
  validation_checks.lower_limit / upper_limit   the limits a measurement is
                                                held against, fixed by the
                                                first measurement
  validation_checks.spec_source                 where the limits come from
  validation_measurements                       one row per measurement of a
                                                computed check (n, min, max,
                                                measuring report or device,
                                                lot ref, what changed since a
                                                failure, computed result)

Data: none. A check answered before this migration keeps its answer and its
value; its next measurement sets the limits.

Repeatable: every column and the table are added once.

Revision ID: 138
Revises: 137
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "138"
down_revision = "137"
branch_labels = None
depends_on = None

COLUMNS = (
    ("lower_limit", lambda: sa.Numeric(12, 3)),
    ("upper_limit", lambda: sa.Numeric(12, 3)),
    ("spec_source", lambda: sa.String(200)),
)


def _cols(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    have = _cols("validation_checks")
    for name, kind in COLUMNS:
        if name not in have:
            op.add_column("validation_checks", sa.Column(name, kind(), nullable=True))
    if "validation_measurements" not in _tables():
        op.create_table(
            "validation_measurements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("check_id", sa.Integer(),
                      sa.ForeignKey("validation_checks.id"), nullable=False),
            sa.Column("change_id", sa.Integer(),
                      sa.ForeignKey("change_requests.id"), nullable=False),
            sa.Column("sample_size", sa.Integer(), nullable=False),
            sa.Column("min_value", sa.Numeric(12, 3), nullable=False),
            sa.Column("max_value", sa.Numeric(12, 3), nullable=False),
            sa.Column("measuring_ref", sa.String(200), nullable=False),
            sa.Column("lot_ref", sa.String(120), nullable=True),
            sa.Column("what_changed_kind", sa.String(20), nullable=True),
            sa.Column("what_changed_ref", sa.String(200), nullable=True),
            sa.Column("result", sa.String(10), nullable=False),
            sa.Column("measured_by", sa.Integer(), sa.ForeignKey("users.id"),
                      nullable=False),
            sa.Column("measured_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_validation_measurements_check_id",
                        "validation_measurements", ["check_id"])
        op.create_index("ix_validation_measurements_change_id",
                        "validation_measurements", ["change_id"])


def downgrade() -> None:
    if "validation_measurements" in _tables():
        op.drop_index("ix_validation_measurements_change_id",
                      table_name="validation_measurements")
        op.drop_index("ix_validation_measurements_check_id",
                      table_name="validation_measurements")
        op.drop_table("validation_measurements")
    have = _cols("validation_checks")
    with op.batch_alter_table("validation_checks") as batch:
        for name, _ in COLUMNS:
            if name in have:
                batch.drop_column(name)
