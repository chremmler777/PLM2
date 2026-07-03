"""Task 20: English seed names + idempotent rename repair for existing DBs.

Standards match templates BY NAME at several fallback sites (see
change_routing_service.build_routing and assessment_instance_repair), so a
rename must be atomic across the seed literals, the repair map, and every
name-based resolution site. These tests cover:
  1. A fresh seed produces English-only names.
  2. `repair_seed_names` heals a pre-Phase-E ("German") DB in place, and a
     ChangeRoutingStandard row still resolves to the (renamed) template
     afterwards.
  3. Running the repair BEFORE `seed_change_workflows` is the trick that
     avoids duplicate English templates being created alongside stale
     German rows on an old DB.
  4. The repair is idempotent.
"""
import re

import pytest
from sqlalchemy import select, func

from app.models.change import ChangeRoutingStandard
from app.models.workflow import WfTemplate, WfStage, WfStep
from app.services.wf_seed_service import (
    seed_change_workflows, repair_seed_names, RENAMES,
)

pytestmark = pytest.mark.asyncio

GERMAN_RE = re.compile(r"Bewertung|Umsetzung")


async def test_fresh_seed_is_english_only(session_factory, seed):
    async with session_factory() as s:
        await seed_change_workflows(s)
        await s.commit()

    async with session_factory() as s:
        tmpl_names = [n for (n,) in (await s.execute(select(WfTemplate.name))).all()]
        stage_names = [n for (n,) in (await s.execute(select(WfStage.name))).all()]
        step_names = [n for (n,) in (await s.execute(select(WfStep.step_name))).all()]

    for name in (*tmpl_names, *stage_names, *step_names):
        assert not GERMAN_RE.search(name), f"German literal leaked into seed name: {name!r}"

    assert "ECM Assessment" in tmpl_names
    assert "ECN Implementation (Tool)" in tmpl_names
    assert "ECN Implementation (Article)" in tmpl_names


async def _seed_german_style_rows(session, uid: int):
    """Simulate a pre-Phase-E DB: templates/stages/steps under the OLD German
    names, plus a ChangeRoutingStandard pointing at the German ECM template by
    id (standards always match by id — only the fallback-by-name sites and
    the create-if-absent seed functions match by literal name)."""
    tmpl = WfTemplate(name="ECM Bewertung", description="x", version=1,
                       is_active=True, created_by=uid)
    session.add(tmpl)
    await session.flush()
    stage = WfStage(template_id=tmpl.id, stage_order=1, name="Machbarkeit & Bewertung")
    session.add(stage)
    await session.flush()
    step = WfStep(stage_id=stage.id, step_name="Fachbereichsbewertung", position_in_stage=1)
    session.add(step)
    await session.flush()

    session.add(ChangeRoutingStandard(
        change_type="physical_part", template_id=tmpl.id,
        template_version=tmpl.version, updated_by=uid,
    ))
    await session.flush()
    return tmpl.id


async def test_repair_renames_german_rows_and_standard_still_resolves(session_factory, seed):
    uid = seed["admin_id"]
    async with session_factory() as s:
        tmpl_id = await _seed_german_style_rows(s, uid)
        await s.commit()

    async with session_factory() as s:
        renamed = await repair_seed_names(s)
        await s.commit()
    assert renamed == 3  # template + stage + step

    async with session_factory() as s:
        tmpl = await s.get(WfTemplate, tmpl_id)
        assert tmpl.name == "ECM Assessment"
        stage = (await s.execute(select(WfStage).where(
            WfStage.template_id == tmpl_id))).scalar_one()
        assert stage.name == "Feasibility & Assessment"
        step = (await s.execute(select(WfStep).where(
            WfStep.stage_id == stage.id))).scalar_one()
        assert step.step_name == "Department assessment"

        std = (await s.execute(select(ChangeRoutingStandard).where(
            ChangeRoutingStandard.change_type == "physical_part"))).scalar_one()
        assert std.template_id == tmpl_id
        resolved = await s.get(WfTemplate, std.template_id)
        assert resolved.name == "ECM Assessment"


async def test_repair_is_idempotent(session_factory, seed):
    uid = seed["admin_id"]
    async with session_factory() as s:
        await _seed_german_style_rows(s, uid)
        await s.commit()

    async with session_factory() as s:
        first = await repair_seed_names(s)
        await s.commit()
    assert first == 3

    async with session_factory() as s:
        second = await repair_seed_names(s)
        await s.commit()
    assert second == 0


async def test_repair_before_seed_prevents_duplicate_templates(session_factory, seed):
    """The whole trick: on an old DB the German rows must be renamed BEFORE
    seed_change_workflows runs, else the create-if-absent seed (which matches
    by the new English name) won't find them and will create a second,
    duplicate English template."""
    uid = seed["admin_id"]
    async with session_factory() as s:
        await _seed_german_style_rows(s, uid)
        await s.commit()

    # Correct order: repair, then seed.
    async with session_factory() as s:
        await repair_seed_names(s)
        await s.commit()
    async with session_factory() as s:
        await seed_change_workflows(s)
        await s.commit()

    async with session_factory() as s:
        n_ecm = (await s.execute(select(func.count()).select_from(WfTemplate).where(
            WfTemplate.name == "ECM Assessment"))).scalar()
        assert n_ecm == 1, "repair-then-seed must not duplicate the ECM template"
        n_german = (await s.execute(select(func.count()).select_from(WfTemplate).where(
            WfTemplate.name == "ECM Bewertung"))).scalar()
        assert n_german == 0

        std = (await s.execute(select(ChangeRoutingStandard).where(
            ChangeRoutingStandard.change_type == "physical_part"))).scalar_one()
        tmpl = await s.get(WfTemplate, std.template_id)
        assert tmpl.name == "ECM Assessment"


async def test_seed_then_repair_without_running_first_would_duplicate(session_factory, seed):
    """Negative control proving the ordering matters: seeding BEFORE repair on
    an old (German) DB creates a second English ECM template, since the
    create-if-absent lookup by "ECM Assessment" finds nothing and the old
    "ECM Bewertung" row is left untouched until repair runs afterwards."""
    uid = seed["admin_id"]
    async with session_factory() as s:
        await _seed_german_style_rows(s, uid)
        await s.commit()

    # Wrong order: seed first (creates a new "ECM Assessment" template
    # because "ECM Bewertung" doesn't match the create-if-absent lookup).
    async with session_factory() as s:
        await seed_change_workflows(s)
        await s.commit()

    async with session_factory() as s:
        n_ecm = (await s.execute(select(func.count()).select_from(WfTemplate).where(
            WfTemplate.name == "ECM Assessment"))).scalar()
        n_german = (await s.execute(select(func.count()).select_from(WfTemplate).where(
            WfTemplate.name == "ECM Bewertung"))).scalar()
        assert n_ecm == 1
        assert n_german == 1  # the stale German row is still there, unrepaired

    # Repair afterwards renames the stale German row onto the SAME name as
    # the already-seeded English template — demonstrating the duplicate the
    # correct ordering (repair-then-seed) avoids.
    async with session_factory() as s:
        await repair_seed_names(s)
        await s.commit()

    async with session_factory() as s:
        n_ecm = (await s.execute(select(func.count()).select_from(WfTemplate).where(
            WfTemplate.name == "ECM Assessment"))).scalar()
        assert n_ecm == 2, "wrong ordering leaves two 'ECM Assessment' templates"


async def test_renames_map_covers_only_old_literals():
    """Sanity: every RENAMES value is a "new" English name, and none of the
    new names collide with an old name (which would make repair ambiguous)."""
    assert set(RENAMES.keys()).isdisjoint(set(RENAMES.values()))
    for new_name in RENAMES.values():
        assert not GERMAN_RE.search(new_name)
