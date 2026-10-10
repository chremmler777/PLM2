"""114: tool cavities as a layout ("2+2"), not a summed number.

parts.tool_cavities becomes text. A family tool with 2 cavities per article is
"2+2", never 4. Existing totals move over as text; where the tool's description
still carries the layout it was imported from, the layout is restored:
- BR167 import: "Cavities: 1+1."
- Brose import: "4 cavities: 206.882.251 x2, 206.882.252 x2." -> "2+2"
Only when that layout adds up to the stored total, so nothing else changes.

Revision ID: 114
Revises: 113
"""
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "114"
down_revision = "113"
branch_labels = None
depends_on = None

BR167 = re.compile(r"Cavities:\s*(\d+(?:\s*\+\s*\d+)+)\.")
BROSE = re.compile(r"\d+ cavities: ((?:[^,]+? x\d+, )+[^,]+? x\d+)\.")


def _layout(description):
    if not description:
        return None
    m = BR167.search(description)
    if m:
        return re.sub(r"\s+", "", m.group(1))
    m = BROSE.search(description)
    if m:
        return "+".join(re.findall(r" x(\d+)", " " + m.group(1)))
    return None


def _col(bind):
    return {c["name"]: c for c in inspect(bind).get_columns("parts")}.get("tool_cavities")


def upgrade() -> None:
    bind = op.get_bind()
    col = _col(bind)
    if col is None or isinstance(col["type"], sa.String):
        return
    with op.batch_alter_table("parts") as batch:
        batch.alter_column("tool_cavities", existing_type=sa.Integer(), type_=sa.String(40),
                           existing_nullable=True, postgresql_using="tool_cavities::text")
    rows = bind.execute(sa.text("SELECT id, tool_cavities, description FROM parts "
                                "WHERE tool_cavities IS NOT NULL")).all()
    for pid, total, description in rows:
        layout = _layout(description)
        if layout and sum(int(n) for n in layout.split("+")) == int(total) and layout != total:
            bind.execute(sa.text("UPDATE parts SET tool_cavities = :v WHERE id = :id"), {"v": layout, "id": pid})


def downgrade() -> None:
    bind = op.get_bind()
    col = _col(bind)
    if col is None or not isinstance(col["type"], sa.String):
        return
    rows = bind.execute(sa.text("SELECT id, tool_cavities FROM parts WHERE tool_cavities LIKE '%+%'")).all()
    for pid, layout in rows:
        bind.execute(sa.text("UPDATE parts SET tool_cavities = :v WHERE id = :id"),
                     {"v": str(sum(int(n) for n in layout.split("+"))), "id": pid})
    with op.batch_alter_table("parts") as batch:
        batch.alter_column("tool_cavities", existing_type=sa.String(40), type_=sa.Integer(),
                           existing_nullable=True, postgresql_using="tool_cavities::integer")
