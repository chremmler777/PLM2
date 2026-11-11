"""161: Project LOP, the list of open points per project.

Five tables (lines, comments, events, meetings, meeting marks) and
projects.lop_enabled. The four projects that run the LOP first are switched
on by project number: 1748, 1864, 1994, 2277.

A line references its source (SEP item, risk row, PDB topic) by text key, or
is a PM task with ref_key NULL; unique per (project_id, kind, ref_key), and
NULLs never collide.

Revision ID: 161
Revises: 160
"""
import sqlalchemy as sa
from alembic import op

revision = "161"
down_revision = "160"
branch_labels = None
depends_on = None

ENABLED_CODES = ("1748", "1864", "1994", "2277")


def _user_fk(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), sa.ForeignKey("users.id"), nullable=True)


def upgrade() -> None:
    op.add_column("projects", sa.Column(
        "lop_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "lop_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("ref_key", sa.String(100), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"), nullable=True),
        _user_fk("responsible_id"),
        sa.Column("responsible_is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("first_due_date", sa.Date(), nullable=True),
        sa.Column("due_is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("next_check_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(15), nullable=False, server_default="new"),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        _user_fk("closed_by"),
        sa.Column("last_update_at", sa.DateTime(), nullable=True),
        _user_fk("last_update_by"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        _user_fk("created_by"),
        sa.UniqueConstraint("project_id", "kind", "ref_key", name="uq_lop_line_source"),
    )
    op.create_index("ix_lop_lines_project_id", "lop_lines", ["project_id"])

    op.create_table(
        "lop_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("line_id", sa.Integer(), sa.ForeignKey("lop_lines.id"), nullable=False),
        _user_fk("user_id"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_lop_comments_line_id", "lop_comments", ["line_id"])

    op.create_table(
        "lop_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("line_id", sa.Integer(), sa.ForeignKey("lop_lines.id"), nullable=False),
        _user_fk("user_id"),
        sa.Column("field", sa.String(50), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_lop_events_line_id", "lop_events", ["line_id"])

    op.create_table(
        "lop_meetings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("held_on", sa.Date(), nullable=False),
        _user_fk("started_by"),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("minutes_sent_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_lop_meetings_project_id", "lop_meetings", ["project_id"])

    op.create_table(
        "lop_meeting_marks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meeting_id", sa.Integer(), sa.ForeignKey("lop_meetings.id"), nullable=False),
        sa.Column("line_id", sa.Integer(), sa.ForeignKey("lop_lines.id"), nullable=False),
        sa.Column("mark", sa.String(15), nullable=False, server_default="none"),
        sa.Column("was_late", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("was_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("meeting_id", "line_id", name="uq_lop_meeting_mark"),
    )
    op.create_index("ix_lop_meeting_marks_meeting_id", "lop_meeting_marks", ["meeting_id"])
    op.create_index("ix_lop_meeting_marks_line_id", "lop_meeting_marks", ["line_id"])

    codes = ", ".join(f"'{c}'" for c in ENABLED_CODES)
    op.execute(sa.text(f"UPDATE projects SET lop_enabled = {sa.true().compile(dialect=op.get_bind().dialect)} "
                       f"WHERE code IN ({codes})"))


def downgrade() -> None:
    op.drop_table("lop_meeting_marks")
    op.drop_table("lop_meetings")
    op.drop_table("lop_events")
    op.drop_table("lop_comments")
    op.drop_table("lop_lines")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("lop_enabled")
