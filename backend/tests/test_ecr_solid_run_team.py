"""ECR-solid C1: the mid-flow hops are the run team's (lead, PM member,
admin). A plain department member is refused (403) and does not see the
button; the switch COMMERCIAL_V2 brings the old (open) behaviour back."""
import pytest
import pytest_asyncio
from sqlalchemy import update

from app.models.change import ChangeRequest
from app.models.workflow import Department, UserDepartment
from app.services import cm_switches
from tests.conftest import login

pytestmark = pytest.mark.asyncio
ACTS = "X-Acts-As-Department"

# (from, to) and the body each hop needs
HOPS = [
    ("quoted", "approved", {}),
    ("costing", "approved", {}),
    ("approved", "in_implementation", {}),
    ("in_implementation", "in_validation", {}),
    ("rejected", "scoping", {"reopen_reason": "customer came back"}),
    ("on_hold", "in_assessment", {}),
    ("on_hold", "approved", {}),
]


@pytest_asyncio.fixture
async def depts(session_factory, seed):
    ids = {}
    async with session_factory() as s:
        for i, n in enumerate(("Development", "Project Manager", "Sales")):
            d = Department(name=n, flow_type="action", is_active=True,
                           sort_order=i, can_start_change=(n == "Sales"))
            s.add(d); await s.flush(); ids[n] = d.id
        # the engineer (the change lead below) writes through Development
        s.add(UserDepartment(user_id=seed["engineer_id"],
                             department_id=ids["Development"]))
        await s.commit()
    return ids


@pytest_asyncio.fixture
async def admin(client):
    return await login(client, "admin@test.io")


async def _change_at(client, admin, seed, session_factory, status, lead=True):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "c1", "reason": "r",
        "change_type": "physical_part", "customer_relevant": status != "costing",
        **({"lead_id": seed["engineer_id"]} if lead else {})}, headers=admin)
    assert res.status_code in (200, 201), res.text
    cid = res.json()["id"]
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == cid)
                        .values(status=status))
        await s.commit()
    return cid


@pytest.mark.parametrize("frm,to,body", HOPS)
async def test_department_member_refused(client, admin, seed, depts,
                                         session_factory, frm, to, body):
    cid = await _change_at(client, admin, seed, session_factory, frm)
    dev = {**admin, ACTS: str(depts["Development"])}
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": to, **body}, headers=dev)
    assert res.status_code == 403, res.text
    assert "change lead, Project Management or an admin" in res.json()["detail"]
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=dev)).json()
    assert st["can_transition"][to] is False


@pytest.mark.parametrize("frm,to,body", HOPS)
async def test_run_team_passes_the_role_gate(client, admin, seed, depts,
                                             session_factory, frm, to, body):
    cid = await _change_at(client, admin, seed, session_factory, frm)
    pm = {**admin, ACTS: str(depts["Project Manager"])}
    lead = await login(client, "eng@test.io", admin=False)
    for who in (pm, lead):
        res = await client.post(f"/api/v1/changes/{cid}/transition",
                                json={"to_status": to, **body}, headers=who)
        # Other gates (signatures, plan, impact lock) may still say 400 or
        # 409: the role gate is what this test is about.
        assert res.status_code != 403, (who, res.text)


async def test_sales_cannot_resume_a_hold(client, admin, seed, depts, session_factory):
    """A hold put on because there is no PO is not lifted by anyone."""
    cid = await _change_at(client, admin, seed, session_factory, "on_hold")
    sales = {**admin, ACTS: str(depts["Sales"])}
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "quoted"}, headers=sales)
    assert res.status_code == 403
    assert "resume" in res.json()["detail"]


async def test_lead_acting_as_department_loses_the_hop(client, admin, seed, depts,
                                                       session_factory):
    """C32: acting as a department drops the personal lead right."""
    cid = await _change_at(client, admin, seed, session_factory, "approved", lead=False)
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == cid)
                        .values(lead_id=seed["admin_id"]))
        await s.commit()
    dev = {**admin, ACTS: str(depts["Development"])}
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "in_implementation"}, headers=dev)
    assert res.status_code == 403


@pytest.mark.parametrize("frm,to,body", HOPS)
async def test_switch_off_restores_open_hops(client, admin, seed, depts,
                                             session_factory, monkeypatch,
                                             frm, to, body):
    monkeypatch.setattr(cm_switches, "COMMERCIAL_V2", False)
    cid = await _change_at(client, admin, seed, session_factory, frm)
    dev = {**admin, ACTS: str(depts["Development"])}
    pm = {**admin, ACTS: str(depts["Project Manager"])}
    # the button follows the run team's again (other gates, e.g. a missing
    # acceptance, may still hide it for both)
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=dev)).json()
    st_pm = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=pm)).json()
    assert st["can_transition"][to] == st_pm["can_transition"][to]
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": to, **body}, headers=dev)
    assert res.status_code != 403, res.text
