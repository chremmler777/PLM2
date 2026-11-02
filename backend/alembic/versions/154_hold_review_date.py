"""154: a hold has a review date (Christoph 2026-11-02).

Schema
  change_requests.hold_review_date   the day the lead / PM checks the hold
                                     again ("check again on"); the resume
                                     task is due then, the lead is reminded
                                     (mailed) that day, and 3 working days
                                     later it escalates to the manager of
                                     Project Management (overdue digest)
  change_requests.hold_reason        why it is on hold (the reason of the
                                     latest hop to on_hold, also on its
                                     changelog row), for the header line
                                     "On hold until <date>: <reason>"

Data: a change on hold today gets the latest hold's reason and a review
date 2 weeks after that hold (the default of the hold dialog), at the
earliest today, so no held change starts out escalated.

Repeatable: every column is added once; the data step only fills rows that
have no review date yet.

Downgrade: drops both columns (the dates are on the changelog).

Revision ID: 154
Revises: 153
"""
from datetime import date, timedelta

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "154"
down_revision = "153"
branch_labels = None
depends_on = None

TABLE = "change_requests"
COLUMNS = (
    ("hold_review_date", lambda: sa.Date()),
    ("hold_reason", lambda: sa.Text()),
)
DEFAULT_DAYS = 14


def _have() -> set[str]:
    insp = inspect(op.get_bind())
    if TABLE not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(TABLE)}


def upgrade() -> None:
    have = _have()
    if not have:
        return
    for name, kind in COLUMNS:
        if name not in have:
            op.add_column(TABLE, sa.Column(name, kind(), nullable=True))
    bind = op.get_bind()
    held = bind.execute(sa.text(
        "SELECT id FROM change_requests WHERE status = 'on_hold' "
        "AND hold_review_date IS NULL")).scalars().all()
    if not held:
        return
    insp = inspect(bind)
    log = "change_changelog" in insp.get_table_names()
    today = date.today()
    for cid in held:
        row = bind.execute(sa.text(
            "SELECT performed_at, notes FROM change_changelog "
            "WHERE change_id = :c AND field_name = 'status' "
            "AND new_value = '\"on_hold\"' ORDER BY id DESC LIMIT 1"),
            {"c": cid}).first() if log else None
        since = row[0] if row is not None and row[0] is not None else None
        if since is not None and not isinstance(since, date):
            since = date.fromisoformat(str(since)[:10])
        review = max(today, (since or today) + timedelta(days=DEFAULT_DAYS))
        bind.execute(sa.text(
            "UPDATE change_requests SET hold_review_date = :d, "
            "hold_reason = COALESCE(hold_reason, :r) WHERE id = :c"),
            {"d": review, "r": row[1] if row is not None else None, "c": cid})


def downgrade() -> None:
    have = _have()
    for name, _ in reversed(COLUMNS):
        if name in have:
            with op.batch_alter_table(TABLE) as batch:
                batch.drop_column(name)
