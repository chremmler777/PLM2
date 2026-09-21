"""073: paint catalog — org-scoped paints and per-article paint layers.

Paints are org-scoped master data, like catalog_parts. An article's paint
setup (part_paints) hangs off the part, not the revision, and its layers
(part_paint_layers) list the paints in application order.

Revision ID: 073
Revises: 072
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    if "paints" not in tables:
        op.create_table(
            "paints",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("paint_type", sa.String(20), nullable=False, server_default="basecoat"),
            sa.Column("colour_code", sa.String(50), nullable=True),
            sa.Column("colour_name", sa.String(100), nullable=True),
            sa.Column("colour_hex", sa.String(7), nullable=True),
            sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=True),
            sa.Column("supplier_text", sa.String(255), nullable=True),
            sa.Column("spec_reference", sa.String(255), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("organization_id", "name", name="uq_paint_org_name"),
        )

    if "part_paints" not in tables:
        op.create_table(
            "part_paints",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("part_id", sa.Integer(),
                      sa.ForeignKey("parts.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("paint_required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("process", sa.String(255), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if "part_paint_layers" not in tables:
        op.create_table(
            "part_paint_layers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("part_paint_id", sa.Integer(),
                      sa.ForeignKey("part_paints.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("paint_id", sa.Integer(), sa.ForeignKey("paints.id"), nullable=False, index=True),
            sa.Column("layer_order", sa.Integer(), nullable=False),
            sa.Column("area", sa.String(255), nullable=True),
            sa.Column("notes", sa.String(500), nullable=True),
            sa.UniqueConstraint("part_paint_id", "layer_order", name="uq_part_paint_layer_order"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())
    if "part_paint_layers" in tables:
        op.drop_table("part_paint_layers")
    if "part_paints" in tables:
        op.drop_table("part_paints")
    if "paints" in tables:
        op.drop_table("paints")
