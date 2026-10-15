"""121: scoping flags are questions or check items (ECR-solid C33, spec §3).

Schema
  change_concerns.flag_type          'question' | 'check'; NULL = legacy (a question)
  change_concerns.check_what         what to check (drawing, volume, ...)
  change_concerns.part_id            the part it is about; NULL = whole change
  change_concerns.answer_from        a question: customer | our_team | supplier
  change_concerns.scope_effect       a question: what the answer changes in the scope
  change_concerns.co_department_ids  "same as #n": co-owning departments
  change_concerns.answer_kind        confirmed | assumed (the answer form)
  change_concerns.answer_ref         the evidence reference of an answer
  change_concerns.assumed_value / assumed_unit / assumed_risk
  change_concerns.confirm_by_id / confirm_due     who confirms an Assumed answer, by when
  change_concerns.confirmed_at / confirmed_by     ... and when it was confirmed
  change_meetings.go_conditions      the check items open at 'proceed' (Go with conditions)

Data
  every existing needs_info flag becomes a question (flag_type 'question'):
  in-flight changes keep exactly today's blocking behaviour.

Repeatable: columns are added once; the backfill only fills NULLs.

Revision ID: 121
Revises: 120
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "121"
down_revision = "120"
branch_labels = None
depends_on = None

CONCERN_COLUMNS = (
    ("flag_type", lambda: sa.String(10)),
    ("check_what", lambda: sa.String(20)),
    ("part_id", lambda: sa.Integer()),
    ("answer_from", lambda: sa.String(12)),
    ("scope_effect", lambda: sa.Text()),
    ("co_department_ids", lambda: sa.JSON()),
    ("answer_kind", lambda: sa.String(10)),
    ("answer_ref", lambda: sa.String(255)),
    ("assumed_value", lambda: sa.String(60)),
    ("assumed_unit", lambda: sa.String(20)),
    ("assumed_risk", lambda: sa.Text()),
    ("confirm_by_id", lambda: sa.Integer()),
    ("confirm_due", lambda: sa.Date()),
    ("confirmed_at", lambda: sa.DateTime()),
    ("confirmed_by", lambda: sa.Integer()),
)
FKS = {"part_id": "parts", "confirm_by_id": "users", "confirmed_by": "users"}


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    have = _columns("change_concerns")
    for name, typ in CONCERN_COLUMNS:
        if name in have:
            continue
        if name in FKS:
            op.add_column("change_concerns", sa.Column(
                name, typ(), sa.ForeignKey(f"{FKS[name]}.id"), nullable=True))
        else:
            op.add_column("change_concerns", sa.Column(name, typ(), nullable=True))
    if "go_conditions" not in _columns("change_meetings"):
        op.add_column("change_meetings",
                      sa.Column("go_conditions", sa.JSON(), nullable=True))
    op.execute("UPDATE change_concerns SET flag_type = 'question' "
               "WHERE kind = 'needs_info' AND flag_type IS NULL")


def downgrade() -> None:
    have = _columns("change_concerns")
    for name, _ in reversed(CONCERN_COLUMNS):
        if name in have:
            op.drop_column("change_concerns", name)
    if "go_conditions" in _columns("change_meetings"):
        op.drop_column("change_meetings", "go_conditions")
