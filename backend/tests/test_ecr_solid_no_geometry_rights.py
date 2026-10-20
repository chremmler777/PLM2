"""Who may sign 'no geometry change' on a revision (review fix 2026-10-19).

The signature is the revision's 3D evidence and, since the ECN decision
(Christoph 2026-10-19), it also drops the Design stages and the release
duplicates of the revision's check workflow. So it is the owner of the 3D
data who signs: the design-responsible department of the ECN template
(Development for an article, Tool Engineer or Development for a tool), the
change lead, or a Project Management member. An admin signs by acting as one
of them (D7: sign-offs need real department members). Everyone else gets 403
and nothing is waived."""
import pytest
from sqlalchemy import select

from tests.conftest import login, make_department_member

pytestmark = pytest.mark.asyncio

HEADER = "X-Acts-As-Department"


async def _start_article_workflow(session_factory, seed, revision_id):
    from app.models.workflow import WfTemplate
    from app.services.wf_seed_service import seed_check_standards
    from app.services.workflow_service import WorkflowService
    async with session_factory() as s:
        await seed_check_standards(s)
        await s.flush()
        tid = (await s.execute(select(WfTemplate.id).where(
            WfTemplate.name == "ECN Implementation (Article)"))).scalars().first()
        inst = await WorkflowService.start_workflow(s, revision_id, tid, seed["admin_id"])
        await s.commit()
        return inst.id


async def _state(session_factory, revision_id, inst_id):
    from app.models.part import PartRevision
    from app.models.workflow import WfInstance, WfInstanceTask
    async with session_factory() as s:
        rev = await s.get(PartRevision, revision_id)
        inst = await s.get(WfInstance, inst_id)
        waived = (await s.execute(select(WfInstanceTask.id).where(
            WfInstanceTask.instance_id == inst_id,
            WfInstanceTask.status == "waived"))).scalars().all()
        return bool(rev.no_geometry_change), inst.current_stage_order, len(waived)


def _url(part):
    return (f"/api/v1/parts/{part['part_id']}/revisions/"
            f"{part['revision_id']}/no-geometry-change")


@pytest.mark.parametrize("dept", ["Sales", "Quality", "Toolshop", "Tool Engineer"])
async def test_other_departments_are_refused_and_nothing_is_waived(
        client, eng_auth, part, seed, session_factory, dept):
    """Negative: a Sales, Quality or Toolshop member (and a Tool Engineer on
    an article) cannot sign; the workflow keeps its Design stage."""
    inst_id = await _start_article_workflow(session_factory, seed, part["revision_id"])
    await make_department_member(session_factory, seed["engineer_id"], dept)
    res = await client.post(_url(part), json={"reason": "texture only"}, headers=eng_auth)
    assert res.status_code == 403, res.text
    signed, stage, waived = await _state(session_factory, part["revision_id"], inst_id)
    assert (signed, stage, waived) == (False, 1, 0)


async def test_development_signs_an_article(client, eng_auth, part, seed, session_factory):
    inst_id = await _start_article_workflow(session_factory, seed, part["revision_id"])
    await make_department_member(session_factory, seed["engineer_id"], "Development")
    res = await client.post(_url(part), json={"reason": "texture only"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    signed, stage, waived = await _state(session_factory, part["revision_id"], inst_id)
    assert signed and stage == 3 and waived > 0


async def test_tool_engineer_signs_a_tool(client, eng_auth, part, seed, session_factory):
    from app.models.part import Part
    async with session_factory() as s:
        (await s.get(Part, part["part_id"])).item_category = "tool"
        await s.commit()
    await make_department_member(session_factory, seed["engineer_id"], "Tool Engineer")
    res = await client.post(_url(part), json={"reason": "insert text only"}, headers=eng_auth)
    assert res.status_code == 200, res.text


async def test_project_management_member_signs(client, eng_auth, part, seed, session_factory):
    await make_department_member(session_factory, seed["engineer_id"], "Project Manager")
    res = await client.post(_url(part), json={"reason": "texture only"}, headers=eng_auth)
    assert res.status_code == 200, res.text


async def test_the_change_lead_signs(client, eng_auth, part, seed, session_factory):
    from app.models.part import PartRevision
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        change = await ChangeService.create_change(
            s, project_id=seed["project_id"], title="lead signs",
            change_type="tooling", raised_by=seed["engineer_id"])
        change.lead_id = seed["engineer_id"]
        (await s.get(PartRevision, part["revision_id"])).originating_change_id = change.id
        await s.commit()
    res = await client.post(_url(part), json={"reason": "texture only"}, headers=eng_auth)
    assert res.status_code == 200, res.text


async def test_plain_admin_is_refused_acting_as_development_signs(
        client, admin_auth, part, seed, session_factory):
    """D7: an admin's own department rows do not count; acting as
    Development puts the department on the record."""
    inst_id = await _start_article_workflow(session_factory, seed, part["revision_id"])
    dev_id = await make_department_member(session_factory, seed["admin_id"], "Development")
    res = await client.post(_url(part), json={"reason": "texture only"}, headers=admin_auth)
    assert res.status_code == 403, res.text
    assert await _state(session_factory, part["revision_id"], inst_id) == (False, 1, 0)
    sales_id = await make_department_member(session_factory, seed["admin_id"], "Sales")
    res = await client.post(_url(part), json={"reason": "texture only"},
                            headers={**admin_auth, HEADER: str(sales_id)})
    assert res.status_code == 403, res.text
    res = await client.post(_url(part), json={"reason": "texture only"},
                            headers={**admin_auth, HEADER: str(dev_id)})
    assert res.status_code == 200, res.text


async def test_implementation_shows_the_sign_button_only_to_signers(
        client, eng_auth, admin_auth, part, seed, session_factory):
    """Frontend = backend gating: the implementation item says whether the
    viewer may sign."""
    from app.models.change import ChangeImpactedItem
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        change = await ChangeService.create_change(
            s, project_id=seed["project_id"], title="button", change_type="tooling",
            raised_by=seed["admin_id"])
        s.add(ChangeImpactedItem(change_id=change.id, part_id=part["part_id"],
                                 resulting_revision_id=part["revision_id"],
                                 created_by=seed["admin_id"]))
        await s.commit()
        change_id = change.id
    await make_department_member(session_factory, seed["engineer_id"], "Sales")
    res = await client.get(f"/api/v1/changes/{change_id}/implementation", headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["items"][0]["may_sign_no_geometry"] is False
    await make_department_member(session_factory, seed["engineer_id"], "Development")
    res = await client.get(f"/api/v1/changes/{change_id}/implementation", headers=eng_auth)
    assert res.json()["items"][0]["may_sign_no_geometry"] is True
