"""Scoping stage: meeting model, gate seeding, and (later tasks) the state machine."""
import pytest
from sqlalchemy import select

from tests.conftest import login, ADMIN_PASSWORD
from tests.conftest import record_proceed_meeting, advance_to_assessment


async def create_change(client, auth, project_id, **overrides):
    body = {"project_id": project_id, "title": "Scoped change",
            "change_type": "physical_part", **overrides}
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.asyncio
async def test_create_seeds_only_release_gate(client, admin_auth, seed):
    change = await create_change(client, admin_auth, seed["project_id"])
    res = await client.get(f"/api/v1/changes/{change['id']}/gates", headers=admin_auth)
    assert res.status_code == 200
    assert [g["gate_key"] for g in res.json()] == ["release"]


@pytest.mark.asyncio
async def test_meeting_model_roundtrip(session_factory, client, admin_auth, seed):
    from datetime import datetime
    from app.models.change import ChangeMeeting
    change = await create_change(client, admin_auth, seed["project_id"])
    async with session_factory() as s:
        s.add(ChangeMeeting(
            change_id=change["id"], meeting_date=datetime.utcnow(),
            participants=[{"name": "PM Jane"}], notes="scope clarified",
            decision=None, selected_department_ids=[1, 2],
            created_by=seed["admin_id"]))
        await s.commit()
    async with session_factory() as s:
        row = (await s.execute(select(ChangeMeeting).where(
            ChangeMeeting.change_id == change["id"]))).scalar_one()
        assert row.participants == [{"name": "PM Jane"}]
        assert row.selected_department_ids == [1, 2]
        assert row.decision is None


async def add_item_and_lead(client, auth, change_id, part_id):
    res = await client.post(f"/api/v1/changes/{change_id}/impacted-items",
                            json={"part_id": part_id, "is_lead": True}, headers=auth)
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_captured_goes_to_scoping_not_assessment(client, admin_auth, seed, part):
    change = await create_change(client, admin_auth, seed["project_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "in_assessment"}, headers=admin_auth)
    assert res.status_code == 400  # no longer a legal edge
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "scoping"}, headers=admin_auth)
    assert res.status_code == 200
    assert res.json()["status"] == "scoping"


@pytest.mark.asyncio
async def test_assessment_requires_proceed_meeting(client, admin_auth, seed, part,
                                                   session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    await client.post(f"/api/v1/changes/{change['id']}/transition",
                      json={"to_status": "scoping"}, headers=admin_auth)
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "in_assessment"}, headers=admin_auth)
    assert res.status_code == 400
    assert "proceed" in res.json()["detail"].lower()
    await record_proceed_meeting(session_factory, change["id"],
                                 actor_id=seed["admin_id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "in_assessment"}, headers=admin_auth)
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_internal_change_skips_quote_and_needs_internal_approval(
        client, admin_auth, seed, part, session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    await advance_to_assessment(client, admin_auth, session_factory, change["id"])
    # drive to costing directly in DB (assessment mechanics are not under test here)
    from sqlalchemy import update
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(
            ChangeRequest.id == change["id"]).values(status="costing"))
        await s.commit()
    # internal change (customer_relevant defaults False): quote is a hard no
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "quoted"}, headers=admin_auth)
    assert res.status_code == 400
    # approved blocked until internal approval exists
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "approved"}, headers=admin_auth)
    assert res.status_code == 400
    assert "internal" in res.json()["detail"].lower()
    async with session_factory() as s:
        from datetime import datetime
        await s.execute(update(ChangeRequest).where(
            ChangeRequest.id == change["id"]).values(
            internal_approved_by=seed["admin_id"],
            internal_approved_at=datetime.utcnow()))
        await s.commit()
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "approved"}, headers=admin_auth)
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_customer_change_cannot_bypass_quote(client, admin_auth, seed, part,
                                                   session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await client.patch(f"/api/v1/changes/{change['id']}",
                       json={"customer_relevant": True}, headers=admin_auth)
    from sqlalchemy import update
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(
            ChangeRequest.id == change["id"]).values(status="costing"))
        await s.commit()
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "approved"}, headers=admin_auth)
    assert res.status_code == 400  # customer branch must go through quote


@pytest.mark.asyncio
async def test_scoping_selection_filters_stage1_fanout(
        client, admin_auth, seed, part, session_factory):
    from sqlalchemy import select
    from app.models.change import ChangeAssessment
    from app.models.workflow import Department, WfInstance, WfInstanceTask
    # Seed the ECM Assessment routing standard so a real multi-dept template applies
    from app.services.wf_seed_service import seed_assessment_standard
    async with session_factory() as s:
        await seed_assessment_standard(s)
        await s.commit()
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    async with session_factory() as s:
        picked = [d for (d,) in await s.execute(
            select(Department.id).where(Department.name.in_(["Quality", "Logistics"])))]
    assert len(picked) == 2
    await advance_to_assessment(client, admin_auth, session_factory,
                                change["id"], dept_ids=picked)
    async with session_factory() as s:
        stage1 = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"],
            ChangeAssessment.stage_order == 1))).scalars().all()
        assert {a.department_id for a in stage1} == set(picked)
        # later stages keep template routing (PM/Sales exist beyond stage 1)
        later = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"],
            ChangeAssessment.stage_order > 1))).scalars().all()
        assert later, "stage >= 2 rows must not be filtered away"
        # engine stage-1 tasks are equally scoped
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == change["id"],
            WfInstance.status == "active"))).scalar_one()
        tasks = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id,
            WfInstanceTask.stage_order == 1))).scalars().all()
        assert {t.department_id for t in tasks} <= set(picked)
        assert tasks, "picked departments must have stage-1 tasks"
