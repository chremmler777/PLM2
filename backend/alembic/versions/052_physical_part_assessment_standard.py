"""052: physical-part changes get their own assessment template.

Every change_type pointed at the one shared "ECM Assessment" template, so a
physical-part change routed an assessment task to Quality, Process
Engineering, Sales, PM and Logistics — departments with nothing to assess
about a physical part. A queue full of nothing to do is how the real work gets
lost.

This unmaps physical_part where it still points at the SHARED template, so the
seeder (wf_seed_service.seed_assessment_standard, create-if-absent, runs on
startup) installs the dedicated "ECM Assessment (Physical Part)" template and
maps it. Until that runs the resolver falls back to TYPE_DISCIPLINES, which
carries the same five departments — so both paths agree in the meantime.

A mapping an admin has pointed at some OTHER template is left alone: that is a
deliberate configuration, not the default this is correcting.

Revision ID: 052
Revises: 051
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None

_std = sa.table(
    "change_routing_standards",
    sa.column("change_type", sa.String),
    sa.column("template_id", sa.Integer),
)
_tmpl = sa.table(
    "wf_templates",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if not {"change_routing_standards", "wf_templates"} <= tables:
        return
    shared_id = bind.execute(
        sa.select(_tmpl.c.id).where(_tmpl.c.name == "ECM Assessment")).scalar()
    if shared_id is None:
        return
    bind.execute(_std.delete().where(
        _std.c.change_type == "physical_part",
        _std.c.template_id == shared_id,
    ))


def downgrade() -> None:
    pass  # forward-only; the seeder owns the mapping
