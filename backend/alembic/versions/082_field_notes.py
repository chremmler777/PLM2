"""082: field notes (comments and a flag per part and field) for the project worksheet.

field_notes: one row per (part_id, field_key), flag null | open | confirmed | rejected.
field_note_comments: append-only comments of a note.

Revision ID: 082
Revises: 081
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "082"
down_revision = "081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "field_notes" not in tables:
        op.create_table(
            "field_notes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("field_key", sa.String(64), nullable=False),
            sa.Column("flag_status", sa.String(20), nullable=True),
            sa.Column("flag_set_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("flag_set_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("part_id", "field_key", name="uq_field_note_part_field"),
        )
    if "field_note_comments" not in tables:
        op.create_table(
            "field_note_comments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("note_id", sa.Integer(), sa.ForeignKey("field_notes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    insp = inspect(bind)
    if "ix_field_notes_part_id" not in {i["name"] for i in insp.get_indexes("field_notes")}:
        op.create_index("ix_field_notes_part_id", "field_notes", ["part_id"])
    if "ix_field_note_comments_note_id" not in {i["name"] for i in insp.get_indexes("field_note_comments")}:
        op.create_index("ix_field_note_comments_note_id", "field_note_comments", ["note_id"])


def downgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "field_note_comments" in tables:
        op.drop_table("field_note_comments")
    if "field_notes" in tables:
        op.drop_table("field_notes")
