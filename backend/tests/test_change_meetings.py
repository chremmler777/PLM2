"""Meeting module: CRUD, PM authz, decide side effects."""
import pytest
from sqlalchemy import select

from tests.conftest import login, ENGINEER_PASSWORD, lock_impact, to_scoping
from tests.test_change_scoping import create_change, add_item_and_lead
from app.models.change import ChangeMeeting


async def post_meeting(client, auth, change_id, **overrides):
    body = {"participants": [{"name": "PM Jane"}, {"name": "Customer Rep"}],
            "notes": "Initial scope clarification",
            "selected_department_ids": [], **overrides}
    return await client.post(f"/api/v1/changes/{change_id}/meetings",
                             json=body, headers=auth)


@pytest.mark.asyncio
async def test_meeting_crud_and_needs_info(client, admin_auth, seed):
    change = await create_change(client, admin_auth, seed["project_id"])
    await to_scoping(client, admin_auth, change["id"])
    res = await post_meeting(client, admin_auth, change["id"])
    assert res.status_code == 200, res.text
    mid = res.json()["id"]
    res = await client.patch(f"/api/v1/changes/{change['id']}/meetings/{mid}",
                             json={"notes": "updated"}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["notes"] == "updated"
    # needs_info must say what is missing — that is what Sales then goes to get.
    res = await client.post(f"/api/v1/changes/{change['id']}/meetings/{mid}/decide",
                            json={"decision": "needs_info"}, headers=admin_auth)
    assert res.status_code == 400, res.text
    res = await client.post(f"/api/v1/changes/{change['id']}/meetings/{mid}/decide",
                            json={"decision": "needs_info",
                                  "reason": "Customer drawing missing"},
                            headers=admin_auth)
    assert res.status_code == 200 and res.json()["decision"] == "needs_info"
    assert res.json()["decision_reason"] == "Customer drawing missing"
    # decided meetings are immutable
    res = await client.patch(f"/api/v1/changes/{change['id']}/meetings/{mid}",
                             json={"notes": "nope"}, headers=admin_auth)
    assert res.status_code == 400
    # change unaffected by needs_info
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=admin_auth)
    assert res.json()["status"] == "scoping"
    # list shows the meeting
    res = await client.get(f"/api/v1/changes/{change['id']}/meetings", headers=admin_auth)
    assert len(res.json()) == 1


@pytest.mark.asyncio
async def test_proceed_kicks_off_assessment(client, admin_auth, seed, part,
                                            session_factory):
    from sqlalchemy import select
    from app.models.workflow import Department
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    async with session_factory() as s:
        # Fresh test DB has no departments seeded; create a couple so the
        # scoping meeting has real department ids to select.
        # Stage-1 assessors of the physical-part template: the scoping
        # selection has to match departments that actually assess.
        s.add_all([Department(name="Development", flow_type="action", is_active=True),
                   Department(name="Tool Engineer", flow_type="action", is_active=True)])
        await s.commit()
    async with session_factory() as s:
        dept_ids = [d for (d,) in await s.execute(select(Department.id))][:2]
    await to_scoping(client, admin_auth, change["id"])
    res = await post_meeting(client, admin_auth, change["id"],
                             selected_department_ids=dept_ids)
    mid = res.json()["id"]
    # proceed without departments is rejected on a fresh meeting
    res2 = await post_meeting(client, admin_auth, change["id"])
    res3 = await client.post(
        f"/api/v1/changes/{change['id']}/meetings/{res2.json()['id']}/decide",
        json={"decision": "proceed"}, headers=admin_auth)
    assert res3.status_code == 400
    # proceed with departments: scoping -> in_assessment in one call.
    # Entering assessment is hard-gated on the impact lock, so lock it first.
    await lock_impact(session_factory, change["id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/meetings/{mid}/decide",
                            json={"decision": "proceed"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=admin_auth)
    assert res.json()["status"] == "in_assessment"


@pytest.mark.asyncio
async def test_reject_decision_rejects_change(client, admin_auth, seed):
    change = await create_change(client, admin_auth, seed["project_id"])
    await to_scoping(client, admin_auth, change["id"])
    res = await post_meeting(client, admin_auth, change["id"])
    mid = res.json()["id"]
    res = await client.post(f"/api/v1/changes/{change['id']}/meetings/{mid}/decide",
                            json={"decision": "reject", "reason": "Not economical"},
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=admin_auth)
    assert res.json()["status"] == "rejected"
    # The meeting's reason is the change's rejection reason.
    assert res.json()["rejection_reason"] == "Not economical"


@pytest.mark.asyncio
async def test_meeting_create_accepts_tz_aware_date_stored_naive(
        client, admin_auth, seed, session_factory):
    """Frontend sends meeting_date as tz-aware ISO-8601 ("...Z"). On
    Postgres the meeting_date column is TIMESTAMP WITHOUT TIME ZONE, and
    asyncpg 500s if handed a tz-aware datetime. The schema layer must
    normalize this to naive UTC before it reaches the DB layer. SQLite
    doesn't itself enforce this, so we assert on the stored value's
    tzinfo directly rather than relying on the insert failing."""
    change = await create_change(client, admin_auth, seed["project_id"])
    await to_scoping(client, admin_auth, change["id"])
    res = await post_meeting(client, admin_auth, change["id"],
                             meeting_date="2026-07-07T12:00:00Z",
                             participants=[{"name": "X"}])
    assert res.status_code == 200, res.text
    mid = res.json()["id"]

    async with session_factory() as session:
        row = (await session.execute(
            select(ChangeMeeting).where(ChangeMeeting.id == mid)
        )).scalar_one()
        assert row.meeting_date.tzinfo is None
        assert row.meeting_date.hour == 12


@pytest.mark.asyncio
async def test_meeting_authz_pm_or_lead_or_admin(client, admin_auth, seed):
    # engineer is neither admin, lead, nor PM-department member
    change = await create_change(client, admin_auth, seed["project_id"])
    eng_auth = await login(client, "eng@test.io", ENGINEER_PASSWORD)
    res = await post_meeting(client, eng_auth, change["id"])
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_the_room_assigns_rasic_letters_and_routing_follows_them(
        client, admin_auth, seed, part, session_factory):
    """The meeting records a letter per department; stage 1 is built from it.
    Attendance is irrelevant: nobody in the participants list is routed for
    being there, and a department nobody attended for is routed all the same."""
    from app.models.workflow import Department
    from app.models.change import ChangeAssessment
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    async with session_factory() as s:
        dev = Department(name="Development", flow_type="action", is_active=True)
        te = Department(name="Tool Engineer", flow_type="action", is_active=True)
        q = Department(name="Quality", flow_type="action", is_active=True)
        s.add_all([dev, te, q]); await s.commit()
        ids = {"dev": dev.id, "te": te.id, "q": q.id}
    await to_scoping(client, admin_auth, change["id"])
    # "I" is accepted and stored as C; a bad letter is refused.
    res = await post_meeting(client, admin_auth, change["id"],
                             department_rasic={ids["dev"]: "X"})
    assert res.status_code == 400 and "RASIC" in res.text
    res = await post_meeting(client, admin_auth, change["id"],
                             participants=[{"name": "Only Quality attended"}],
                             department_rasic={ids["dev"]: "R", ids["te"]: "A", ids["q"]: "I"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["department_rasic"] == {str(ids["dev"]): "R", str(ids["te"]): "A", str(ids["q"]): "C"}
    assert sorted(body["selected_department_ids"]) == sorted(ids.values())
    mid = body["id"]
    # Editing the letters keeps the id list in step.
    res = await client.patch(f"/api/v1/changes/{change['id']}/meetings/{mid}",
                             json={"department_rasic": {ids["dev"]: "R", ids["q"]: "S"}},
                             headers=admin_auth)
    assert res.status_code == 200, res.text
    assert sorted(res.json()["selected_department_ids"]) == sorted([ids["dev"], ids["q"]])
    await lock_impact(session_factory, change["id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/meetings/{mid}/decide",
                            json={"decision": "proceed"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"],
            ChangeAssessment.stage_order == 1))).scalars().all()
        letters = {r.department_id: r.rasic_letter for r in rows}
    assert letters == {ids["dev"]: "R", ids["q"]: "S"}


@pytest.mark.asyncio
async def test_proceed_needs_somebody_responsible_when_letters_are_given(
        client, admin_auth, seed, part, session_factory):
    from app.models.workflow import Department
    change = await create_change(client, admin_auth, seed["project_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    async with session_factory() as s:
        q = Department(name="Quality", flow_type="action", is_active=True)
        s.add(q); await s.commit(); qid = q.id
    await to_scoping(client, admin_auth, change["id"])
    res = await post_meeting(client, admin_auth, change["id"], department_rasic={qid: "C"})
    mid = res.json()["id"]
    await lock_impact(session_factory, change["id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/meetings/{mid}/decide",
                            json={"decision": "proceed"}, headers=admin_auth)
    assert res.status_code == 400 and "Responsible or Accountable" in res.text


@pytest.mark.asyncio
async def test_recommended_departments_carry_the_standard_letter(
        client, admin_auth, seed, session_factory):
    """The picker starts from the template's opinion, letter included."""
    from tests.test_change_routing import departments as _d, ecr_template as _t  # noqa: F401
    change = await create_change(client, admin_auth, seed["project_id"])
    res = await client.get(f"/api/v1/changes/{change['id']}/recommended-departments",
                           headers=admin_auth)
    assert res.status_code == 200, res.text
    for row in res.json():
        assert row["rasic_letter"] in ("R", "A", "S", "C")
