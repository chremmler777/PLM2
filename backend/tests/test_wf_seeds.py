import pytest
from sqlalchemy import select, func

pytestmark = pytest.mark.asyncio


async def test_seed_check_standards_creates_templates_and_mappings(session_factory, seed):
    from app.models.workflow import (
        CheckWorkflowStandard, WfTemplate, WfStage, WfStep,
        CHECK_WF_ITEM_CATEGORIES,
    )
    from app.services.wf_seed_service import seed_check_standards

    async with session_factory() as s:
        await seed_check_standards(s)
        await s.commit()

    async with session_factory() as s:
        cats = {c for (c,) in await s.execute(
            select(CheckWorkflowStandard.item_category))}
        assert cats == set(CHECK_WF_ITEM_CATEGORIES)

        tmpl = (await s.execute(select(WfTemplate).where(
            WfTemplate.name == "ECN Umsetzung (Werkzeug)"))).scalar_one()
        stages = (await s.execute(select(WfStage).where(
            WfStage.template_id == tmpl.id))).scalars().all()
        assert len(stages) == 4

        steps = (await s.execute(
            select(WfStep).join(WfStage, WfStep.stage_id == WfStage.id)
            .where(WfStage.template_id == tmpl.id))).scalars().all()
        evidence = [st for st in steps if st.requires_cad_evidence]
        assert [st.step_name for st in evidence] == ["3D-Daten aktualisieren"]
        four_eyes = [st for st in steps if st.four_eyes]
        assert [st.step_name for st in four_eyes] == ["Konstruktionsprüfung"]


async def test_seed_is_idempotent(session_factory, seed):
    from app.models.workflow import WfTemplate
    from app.services.wf_seed_service import seed_change_workflows

    async with session_factory() as s:
        await seed_change_workflows(s)
        await s.commit()
    async with session_factory() as s:
        n1 = (await s.execute(select(func.count()).select_from(WfTemplate))).scalar()
        await seed_change_workflows(s)
        await s.commit()
        n2 = (await s.execute(select(func.count()).select_from(WfTemplate))).scalar()
    assert n1 == n2


async def test_seed_assessment_standard_maps_all_change_types(session_factory, seed):
    from app.models.change import ChangeRoutingStandard, CHANGE_TYPES
    from app.models.workflow import WfTemplate, WfStage
    from app.services.wf_seed_service import seed_assessment_standard

    async with session_factory() as s:
        await seed_assessment_standard(s)
        await s.commit()

    async with session_factory() as s:
        rows = (await s.execute(select(ChangeRoutingStandard))).scalars().all()
        assert {r.change_type for r in rows} == set(CHANGE_TYPES)
        tmpl = (await s.execute(select(WfTemplate).where(
            WfTemplate.name == "ECM Bewertung"))).scalar_one()
        assert all(r.template_id == tmpl.id for r in rows)
        stages = (await s.execute(select(WfStage).where(
            WfStage.template_id == tmpl.id))).scalars().all()
        assert len(stages) == 3


async def test_repair_inflight_backfills_check_workflow(session_factory, seed, part):
    """A change already in_implementation at deploy time (ECN revision spawned
    but no check-WF instance) gets self-healed by the startup repair."""
    from app.models.change import ChangeRequest, ChangeImpactedItem
    from app.models.part import PartRevision
    from app.models.workflow import WfInstance
    from app.services.wf_seed_service import (
        seed_check_standards, repair_inflight_check_workflows)
    from tests.test_change_kickoff import _approved_change

    cid = await _approved_change(session_factory, seed, part["part_id"])

    # Simulate mid-flight state: in_implementation, ECN revision on the impacted
    # item, but no WfInstance (kickoff side-effects never fired pre-Phase B).
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        change.status = "in_implementation"
        item = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == cid))).scalar_one()
        rev = PartRevision(
            part_id=part["part_id"], revision_name="ECR1.1", phase="ecn",
            status="draft", originating_change_id=cid,
            created_by=seed["engineer_id"])
        s.add(rev)
        await s.flush()
        item.resulting_revision_id = rev.id
        rev_id = rev.id
        await s.commit()

    # Now seed the check standards (as a redeploy would), then run repair.
    async with session_factory() as s:
        await seed_check_standards(s)
        await s.commit()

    async with session_factory() as s:
        examined = await repair_inflight_check_workflows(s)
        await s.commit()
        assert examined == 1

    async with session_factory() as s:
        insts = (await s.execute(select(WfInstance).where(
            WfInstance.part_revision_id == rev_id))).scalars().all()
        assert len(insts) == 1
        assert insts[0].status == "active"

    # Idempotency: a second run creates no duplicate instance.
    async with session_factory() as s:
        await repair_inflight_check_workflows(s)
        await s.commit()
    async with session_factory() as s:
        n = (await s.execute(select(func.count()).select_from(WfInstance).where(
            WfInstance.part_revision_id == rev_id))).scalar()
        assert n == 1


async def test_check_standards_api_roundtrip(client, admin_auth, eng_auth, session_factory, seed):
    from app.services.wf_seed_service import seed_check_standards
    from app.models.workflow import WfTemplate
    from sqlalchemy import select
    async with session_factory() as s:
        await seed_check_standards(s)
        await s.commit()
        artikel = (await s.execute(select(WfTemplate).where(
            WfTemplate.name == "ECN Umsetzung (Artikel)"))).scalar_one()

    res = await client.get("/api/v1/changes/check-standards", headers=eng_auth)
    assert res.status_code == 200, res.text
    assert len(res.json()) == 5

    res = await client.put("/api/v1/changes/check-standards",
                           json={"item_category": "tool", "template_id": artikel.id},
                           headers=eng_auth)
    assert res.status_code == 403
    res = await client.put("/api/v1/changes/check-standards",
                           json={"item_category": "tool", "template_id": artikel.id},
                           headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["template_id"] == artikel.id
