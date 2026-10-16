"""Close-out, area 1 roles/security/visibility (R22-R25): negative tests.

Each test names the issue it pins (A1-xx)."""
import pytest
from sqlalchemy import select

from tests.conftest import lock_impact, to_scoping
from tests.test_change_scoping import create_change, add_item_and_lead
from tests.test_change_meetings import post_meeting


async def _depts(session_factory, **specs):
    """specs: key -> (name, is_active). Returns key -> id."""
    from app.models.workflow import Department
    out = {}
    async with session_factory() as s:
        rows = {}
        for key, (name, active) in specs.items():
            d = Department(name=name, flow_type="action", is_active=active)
            s.add(d); rows[key] = d
        await s.commit()
        out = {k: d.id for k, d in rows.items()}
    return out


# ---- A1-01: Management and retired departments are never routed ----------

@pytest.mark.asyncio
async def test_a1_01_scoping_refuses_management_and_retired_departments(
        client, admin_auth, seed, part, session_factory):
    from app.models.change import ChangeAssessment, ChangeMeeting
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    ids = await _depts(session_factory, dev=("Development", True),
                       mgmt=("Management", True), old=("Developer", False))
    await to_scoping(client, admin_auth, change["id"])
    cid = change["id"]
    # Create: Management R is refused with the routing-deviation wording.
    res = await post_meeting(client, admin_auth, cid,
                             department_rasic={ids["dev"]: "R", ids["mgmt"]: "R"})
    assert res.status_code == 400, res.text
    assert "gives OKs and books no hours" in res.text
    # A retired department is refused for any task letter.
    res = await post_meeting(client, admin_auth, cid,
                             department_rasic={ids["dev"]: "R", ids["old"]: "C"})
    assert res.status_code == 400 and "is retired" in res.text
    # The id-only path (every id is R) is refused the same way.
    res = await post_meeting(client, admin_auth, cid,
                             selected_department_ids=[ids["dev"], ids["mgmt"]])
    assert res.status_code == 400 and "never routed" in res.text
    # Management Informed is fine: notified, no task.
    res = await post_meeting(client, admin_auth, cid,
                             department_rasic={ids["dev"]: "R", ids["mgmt"]: "I"})
    assert res.status_code == 200, res.text
    mid = res.json()["id"]
    # Update refuses too.
    res = await client.patch(f"/api/v1/changes/{cid}/meetings/{mid}",
                             json={"department_rasic": {ids["dev"]: "R", ids["old"]: "R"}},
                             headers=admin_auth)
    assert res.status_code == 400 and "is retired" in res.text
    # A meeting stored before the rule (Management R) cannot proceed, and
    # proceeding creates no assessment.
    async with session_factory() as s:
        m = await s.get(ChangeMeeting, mid)
        m.department_rasic = {str(ids["dev"]): "R", str(ids["mgmt"]): "R"}
        m.selected_department_ids = [ids["dev"], ids["mgmt"]]
        await s.commit()
    await lock_impact(session_factory, cid)
    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                            json={"decision": "proceed"}, headers=admin_auth)
    assert res.status_code == 400 and "never routed" in res.text
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_a1_01_build_routing_skips_retired_and_management(
        session_factory, seed):
    """A template or an older proceed naming a retired department or
    Management for a task never yields an assessment nobody can submit."""
    from app.services.change_routing_service import ChangeRoutingService
    ids = await _depts(session_factory, dev=("Development", True),
                       mgmt=("Management", True), old=("Developer", False))
    stages = [{"stage_order": 1, "departments": [
        {"department_id": ids["dev"], "rasic_letter": "R"},
        {"department_id": ids["mgmt"], "rasic_letter": "R"},
        {"department_id": ids["old"], "rasic_letter": "R"}]}]
    async with session_factory() as s:
        kept = await ChangeRoutingService._drop_unroutable(s, stages)
    assert [d["department_id"] for d in kept[0]["departments"]] == [ids["dev"]]
