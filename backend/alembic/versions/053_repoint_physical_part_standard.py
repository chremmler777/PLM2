"""053: point physical_part at its own assessment template, deterministically.

052 unmapped physical_part by matching the SHARED template by name — and this
database carries two rows both named "ECM Assessment" (leftovers of the German
-> English rename). The mapping pointed at the other one, so the delete missed
and physical-part changes kept routing assessment tasks to PM, Sales and
Quality.

This repoints the mapping straight at "ECM Assessment (Physical Part)" when it
exists (the seeder creates it), and otherwise unmaps ANY shared template so the
seeder installs it on the next startup. Matching by id from a name lookup that
can return several rows is the bug being fixed, so both branches use IN.

Revision ID: 053
Revises: 052
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None

PHYSICAL = "ECM Assessment (Physical Part)"
SHARED = "ECM Assessment"

_std = sa.table(
    "change_routing_standards",
    sa.column("change_type", sa.String),
    sa.column("template_id", sa.Integer),
    sa.column("template_version", sa.Integer),
)
_tmpl = sa.table(
    "wf_templates",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("version", sa.Integer),
)


def upgrade() -> None:
    bind = op.get_bind()
    if not {"change_routing_standards", "wf_templates"} <= set(
            inspect(bind).get_table_names()):
        return

    dedicated = bind.execute(
        sa.select(_tmpl.c.id, _tmpl.c.version)
        .where(_tmpl.c.name == PHYSICAL)
        .order_by(_tmpl.c.id.desc())).first()
    if dedicated is not None:
        tmpl_id, version = dedicated
        bind.execute(_std.update()
                     .where(_std.c.change_type == "physical_part")
                     .values(template_id=tmpl_id, template_version=version or 1))
        return

    # Not seeded yet: drop the mapping to ANY shared template so the seeder
    # installs the dedicated one. Until then the resolver falls back to
    # TYPE_DISCIPLINES, which lists the same five departments.
    bind.execute(_std.delete().where(
        _std.c.change_type == "physical_part",
        _std.c.template_id.in_(sa.select(_tmpl.c.id).where(_tmpl.c.name == SHARED)),
    ))


def downgrade() -> None:
    pass  # forward-only; the seeder owns the mapping
