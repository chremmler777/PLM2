"""Close-out, area 1 roles/security/visibility (R22-R25): negative tests.

Each test names the issue it pins (A1-xx)."""
import pytest
from sqlalchemy import select

from tests.conftest import lock_impact, to_scoping
from tests.test_change_scoping import create_change, add_item_and_lead
from tests.test_change_meetings import post_meeting
from tests.test_change_routing import (  # noqa: F401  (fixtures)
    departments, departments_member, ecr_template)


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


# ---- A1-02: when the lead cannot decide a routing change, PM decides -------

async def _user(client, session_factory, seed, key, dept=None, role="engineer"):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    from tests.conftest import login, make_department_member
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=f"rc-{key}",
                 email=f"rc-{key}@test.io", full_name=f"RC {key}",
                 hashed_password=get_password_hash("rc-secret-12"),
                 role=role, is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        uid = u.id
    if dept:
        await make_department_member(session_factory, uid, dept)
    return uid, await login(client, f"rc-{key}@test.io")


async def _pending_routing_change(client, seed, session_factory, departments):
    """In assessment, lead = engineer; the lead files an add (so the lead
    cannot decide it)."""
    from tests.test_change_routing import _api_change_in_assessment, _login
    eng = await _login(client)
    c = await _api_change_in_assessment(client, eng, seed, session_factory)
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": departments["Manufacturing Engineer"],
        "rasic_letter": "R", "stage_order": 1, "reason": "forgot MfgEng"}, headers=eng)
    assert res.status_code == 200, res.text
    return c["id"], eng


@pytest.mark.asyncio
async def test_a1_02_only_pm_or_admin_decides_when_the_lead_filed(
        client, seed, ecr_template, departments, departments_member, session_factory):
    cid, eng = await _pending_routing_change(client, seed, session_factory, departments)
    _, sales = await _user(client, session_factory, seed, "sales", "Sales")
    _, tools = await _user(client, session_factory, seed, "tools", "Toolshop")
    _, pm = await _user(client, session_factory, seed, "pm", "Project Manager")
    url = f"/api/v1/changes/{cid}/routing/deviation"
    for h in (sales, tools):
        res = await client.post(f"{url}/approve", headers=h)
        assert res.status_code == 403, res.text
        res = await client.post(f"{url}/reject", json={"reason": "no"}, headers=h)
        assert res.status_code == 403, res.text
        acts = (await client.get(f"/api/v1/changes/{cid}/my-actions", headers=h)).json()
        assert "routing_deviation_decision" not in [a["kind"] for a in acts["actions"]]
        st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=h)).json()
        assert st["routing_deviation"]["can_decide"] is False
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=pm)).json()
    assert st["routing_deviation"]["can_decide"] is True
    acts = (await client.get(f"/api/v1/changes/{cid}/my-actions", headers=pm)).json()
    assert "routing_deviation_decision" in [a["kind"] for a in acts["actions"]]
    # The proposing lead: 403, not 400.
    res = await client.post(f"{url}/approve", headers=eng)
    assert res.status_code == 403, res.text
    res = await client.post(f"{url}/approve", headers=pm)
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_a1_02_idle_lead_hands_the_decision_to_pm_not_to_anyone(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """The lead is read-only: the request was filed by somebody else, but
    Toolshop still may not decide it; a PM member may."""
    from tests.test_change_routing import _api_change_in_assessment, _login
    from app.models.change import ChangeRequest
    eng = await _login(client)
    c = await _api_change_in_assessment(client, eng, seed, session_factory)
    cid = c["id"]
    vid, viewer = await _user(client, session_factory, seed, "viewer", role="viewer")
    async with session_factory() as s:
        (await s.get(ChangeRequest, cid)).lead_id = vid
        await s.commit()
    res = await client.post(f"/api/v1/changes/{cid}/routing/deviation", json={
        "op": "add", "department_id": departments["Manufacturing Engineer"],
        "rasic_letter": "R", "stage_order": 1, "reason": "forgot"}, headers=eng)
    assert res.status_code == 200, res.text
    _, tools = await _user(client, session_factory, seed, "tools", "Toolshop")
    _, pm = await _user(client, session_factory, seed, "pm", "Project Manager")
    url = f"/api/v1/changes/{cid}/routing/deviation"
    assert (await client.post(f"{url}/approve", headers=tools)).status_code == 403
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=viewer)).json()
    assert st["routing_deviation"]["can_decide"] is False
    acts = (await client.get(f"/api/v1/changes/{cid}/my-actions", headers=viewer)).json()
    assert acts["actions"] == []
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=pm)).json()
    assert st["routing_deviation"]["can_decide"] is True
    assert (await client.post(f"{url}/approve", headers=pm)).status_code == 200


# ---- A1-03: read-only users are offered no write actions ------------------

@pytest.mark.asyncio
async def test_a1_03_viewer_lead_may_not_inform_the_team(session_factory):
    """A read-only lead of a mother-plant change gets no Send controls
    (MotherPlantService.may_send feeds can_send / can_inform)."""
    from types import SimpleNamespace
    from app.services.mother_plant_service import MotherPlantService
    viewer = SimpleNamespace(id=7, effective_role="viewer", acts_as_department_id=None)
    change = SimpleNamespace(lead_id=7)
    async with session_factory() as s:
        assert await MotherPlantService.may_send(s, change, viewer) is False


# ---- A1-04: who may ask for an override, and who is refused with 403 ------

@pytest.mark.asyncio
async def test_a1_04_override_ask_needs_the_step_or_the_run_team(
        client, eng_auth, admin_auth, seed, session_factory):
    from tests.test_change_deviations import _change
    c = await _change(client, eng_auth, seed)          # lead = the engineer
    cid = c["id"]
    _, tools = await _user(client, session_factory, seed, "tools4", "Toolshop")
    body = {"to_status": "in_assessment", "reason": "PPT only, drawing follows",
            "reason_code": "in_parallel"}
    url = f"/api/v1/changes/{cid}/deviations"
    # Toolshop may not take the step and is not on the run team: 403.
    res = await client.post(url, json=body, headers=tools)
    assert res.status_code == 403, res.text
    # The lead asks; a second ask by Toolshop is still 403, never
    # 'already pending' (permission first).
    dev = await client.post(url, json=body, headers=eng_auth)
    assert dev.status_code == 200, dev.text
    dev = dev.json()
    res = await client.post(url, json={**body, "guard_key": dev["guard_key"]},
                            headers=tools)
    assert res.status_code == 403, res.text
    # Deciding is the deciders' (run team here): Toolshop 403, the proposer 403.
    res = await client.post(f"{url}/{dev['id']}/decide",
                            json={"decision": "approved"}, headers=tools)
    assert res.status_code == 403, res.text
    res = await client.post(f"{url}/{dev['id']}/decide",
                            json={"decision": "approved"}, headers=eng_auth)
    assert res.status_code == 403, res.text
    # A plain 400 stays a 400: a rejection without a reason.
    res = await client.post(f"{url}/{dev['id']}/decide",
                            json={"decision": "rejected"}, headers=admin_auth)
    assert res.status_code == 400, res.text


# ---- A1-05: a stored engineer without an active department writes nothing --

@pytest.mark.asyncio
async def test_a1_05_engineer_whose_departments_are_retired_is_no_acting_lead(
        client, session_factory, seed):
    from sqlalchemy.orm import selectinload
    from app.models.change import ChangeRequest
    from app.models.entities import User
    from app.models.workflow import Department
    from app.services.change_service import ChangeService
    uid, _ = await _user(client, session_factory, seed, "gone", "Old Dept")
    placed, _ = await _user(client, session_factory, seed, "placed", "Quality")
    async with session_factory() as s:
        d = (await s.execute(select(Department).where(
            Department.name == "Old Dept"))).scalar_one()
        d.is_active = False
        for lead in (uid, placed, seed["admin_id"]):
            s.add(ChangeRequest(change_number=f"CR-A5-{lead}", project_id=seed["project_id"],
                                title="a5", change_type="physical_part", status="costing",
                                raised_by=lead, lead_id=lead))
        await s.commit()
    async with session_factory() as s:
        changes = (await s.execute(select(ChangeRequest).where(
            ChangeRequest.change_number.like("CR-A5-%"))
            .options(selectinload(ChangeRequest.lead)))).scalars().all()
        idle = await ChangeService.leadless_ids(s, changes)
        by_lead = {c.lead_id: c.id for c in changes}
        assert idle == {by_lead[uid]}
        users = [await s.get(User, i) for i in (uid, placed, seed["admin_id"])]
        assert [u.id for u in await ChangeService._writers(s, users)] == [
            placed, seed["admin_id"]]


# ---- A1-06: the HARD #8 fallback is a real Project Manager member ---------

@pytest.mark.asyncio
async def test_a1_06_internal_fallback_has_no_admin_shortcut(
        client, session_factory, seed):
    from app.models.change import ChangeRequest
    from app.models.entities import User
    from app.services.change_service import ChangeService
    pm, _ = await _user(client, session_factory, seed, "pm6", "Project Manager")
    async with session_factory() as s:
        c = ChangeRequest(change_number="CR-A6", project_id=seed["project_id"],
                          title="a6", change_type="physical_part", status="costing",
                          customer_relevant=False, raised_by=seed["engineer_id"],
                          lead_id=seed["engineer_id"])
        s.add(c)
        await s.commit()
        assert await ChangeService.change_approvers(s, c) == []
        admin = await s.get(User, seed["admin_id"])
        assert await ChangeService.is_internal_approver(s, admin, c) is False
        pm_user = await s.get(User, pm)
        assert await ChangeService.is_internal_approver(s, pm_user, c) is True
        # acting as Project Manager is not membership on this 4-eyes step
        from app.models.workflow import Department
        pm_dept = (await s.execute(select(Department).where(
            Department.name == "Project Manager"))).scalar_one()
        admin.acts_as_department_id = pm_dept.id
        assert await ChangeService.is_internal_approver(s, admin, c) is False
        # never the raiser
        c.raised_by = pm
        assert await ChangeService.is_internal_approver(s, pm_user, c) is False


# ---- A1-07: change sign-offs need real membership, like the override OK ---

@pytest.mark.asyncio
async def test_a1_07_admin_outside_quality_cannot_sign_the_change(
        client, eng_auth, admin_auth, seed, session_factory):
    from tests.test_change_deviations import _change
    c = await _change(client, eng_auth, seed)
    url = f"/api/v1/changes/{c['id']}/sign-off"
    for role in ("quality", "pm"):
        res = await client.post(url, json={"role": role}, headers=admin_auth)
        assert res.status_code == 403, res.text
    _, q = await _user(client, session_factory, seed, "q7", "Quality")
    res = await client.post(url, json={"role": "quality"}, headers=q)
    assert res.status_code != 403, res.text     # refused later for the status, not the role


# ---- A1-08: Management reads the extra cost of validation issues ----------

@pytest.mark.asyncio
async def test_a1_08_management_sees_extra_cost_toolshop_does_not(
        client, session_factory, seed):
    from tests.test_validation_issues import _make, _raised, _auth, _url
    vi = await _make(session_factory, seed, management=True)
    iid = (await _raised(client, vi))["id"]
    pm = await _auth(client, vi, "pm")
    r = await client.post(_url(vi, f"/{iid}/cost"), headers=pm,
                          json={"extra_cost": 5000, "cost_bearer": "internal"})
    assert r.status_code == 200, r.text
    boss = await _auth(client, vi, "boss")
    seen = (await client.get(_url(vi), headers=boss)).json()[0]
    assert seen["extra_cost"] == 5000 and seen["cost_visible"] is True
    # reading is not recording: Management gets no "cost" action
    assert "cost" not in seen["next_acts"]
    tool = await _auth(client, vi, "tool")
    seen = (await client.get(_url(vi), headers=tool)).json()[0]
    assert seen["extra_cost"] is None and seen["cost_visible"] is False


# ---- A1-09: a manual flip moves the lead; the way back is not the raiser's -

@pytest.mark.asyncio
async def test_a1_09_manual_flip_moves_lead_and_raiser_cannot_flip_back(
        client, admin_auth, seed, session_factory):
    from app.models.change import ChangeRequest
    from app.models.workflow import Department, ProjectResponsible
    eng_id, eng = await _user(client, session_factory, seed, "eng9", "Development")
    sales_id, sales = await _user(client, session_factory, seed, "sales9", "Sales")
    pm_id, _ = await _user(client, session_factory, seed, "pm9", "Project Manager")
    async with session_factory() as s:
        sales_dept = (await s.execute(select(Department).where(
            Department.name == "Sales"))).scalar_one()
        sales_dept.can_start_change = True
        pm_dept = (await s.execute(select(Department).where(
            Department.name == "Project Manager"))).scalar_one()
        s.add(ProjectResponsible(project_id=seed["project_id"],
                                 department_id=pm_dept.id, user_id=pm_id))
        c = ChangeRequest(change_number="CR-A9", project_id=seed["project_id"],
                          title="a9", change_type="physical_part", status="scoping",
                          customer_relevant=False, origin="internal",
                          raised_by=eng_id, lead_id=eng_id)
        s.add(c)
        await s.commit()
        cid = c.id
    url = f"/api/v1/changes/{cid}"
    # Sales makes it a customer change: the project PM leads it now.
    res = await client.patch(url, json={"customer_relevant": True}, headers=sales)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        assert c.customer_relevant is True and c.lead_id == pm_id
        # the engineering raiser leads it again (e.g. no PM picked it up) ...
        c.lead_id = eng_id
        await s.commit()
    # ... and still may not take the customer off by PATCH (403).
    res = await client.patch(url, json={"customer_relevant": False}, headers=eng)
    assert res.status_code == 403, res.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cid)).customer_relevant is True
    # An admin may.
    res = await client.patch(url, json={"customer_relevant": False}, headers=admin_auth)
    assert res.status_code == 200, res.text
