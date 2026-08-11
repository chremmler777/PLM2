"""GET /changes/my-tasks covers every stage's responsible role, not just
pending assessments: a change parked in a stage is that role's open task."""
import pytest
from datetime import datetime, timedelta

from app.models.workflow import Department, UserDepartment
from tests.conftest import login, ENGINEER_PASSWORD, satisfy_capture_gate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def roles(session_factory, seed):
    """Sales / Project Manager / Development, each with its own member."""
    from app.models.entities import User
    from app.auth.security import get_password_hash
    async with session_factory() as s:
        depts = {}
        for name, starter in [("Sales", True), ("Project Manager", False),
                              ("Development", False)]:
            d = Department(name=name, flow_type="action", is_active=True,
                           can_start_change=starter)
            s.add(d)
            await s.flush()
            depts[name] = d.id
        users = {}
        for name, email in [("Sales", "sales@test.io"), ("Project Manager", "pm@test.io"),
                            ("Development", "dev@test.io")]:
            u = User(organization_id=seed["org_id"], username=email.split("@")[0],
                     email=email, full_name=name,
                     hashed_password=get_password_hash("role-secret-1"),
                     role="engineer", is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=depts[name]))
            users[name] = u.id
        await s.commit()
        return {"dept": depts, "user": users}


async def _auth(client, name):
    return await login(client, {"Sales": "sales@test.io",
                                "Project Manager": "pm@test.io",
                                "Development": "dev@test.io"}[name],
                       ENGINEER_PASSWORD)


async def _create(client, auth, seed, title, **over):
    body = {"project_id": seed["project_id"], "title": title, "reason": "r",
            "change_type": "physical_part"}
    body.update(over)
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _tasks(client, auth):
    res = await client.get("/api/v1/changes/my-tasks", headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def _set_status(session_factory, cid, **values):
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        for k, v in values.items():
            setattr(c, k, v)
        await s.commit()


async def test_sales_sees_kickoff_with_the_unmet_parts(client, seed, roles):
    sales = await _auth(client, "Sales")
    cid = await _create(client, sales, seed, "kickoff row", customer_relevant=True)
    rows = [t for t in await _tasks(client, sales) if t["kind"] == "kickoff"]
    assert len(rows) == 1
    row = rows[0]
    assert row["change_id"] == cid
    assert row["missing"] == ["description", "at least one attachment",
                              "required-by date"]
    # ...and it is not the PM's row
    assert not [t for t in await _tasks(client, sales)
                if t["kind"] == "scoping_wrapup"]

    # completing the capture empties the checklist
    await satisfy_capture_gate(client, sales, cid)
    row = [t for t in await _tasks(client, sales) if t["kind"] == "kickoff"][0]
    assert row["missing"] == []


async def test_pm_sees_scoping_wrapup_with_flags(client, seed, roles,
                                                 session_factory):
    sales = await _auth(client, "Sales")
    pm = await _auth(client, "Project Manager")
    cid = await _create(client, sales, seed, "wrapup row")
    await satisfy_capture_gate(client, sales, cid)
    await _set_status(session_factory, cid, status="scoping")

    rows = [t for t in await _tasks(client, pm) if t["kind"] == "scoping_wrapup"]
    assert len(rows) == 1
    assert rows[0]["change_id"] == cid
    assert rows[0]["impact_confirmed"] is False
    assert rows[0]["has_decision"] is False
    # the PM is not Sales -> no kickoff row for them
    assert not [t for t in await _tasks(client, pm) if t["kind"] == "kickoff"]


async def test_impact_confirm_row_disappears_once_locked(
        client, seed, roles, part, session_factory):
    sales = await _auth(client, "Sales")
    dev = await _auth(client, "Development")
    cid = await _create(client, sales, seed, "impact row")
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": part["part_id"], "is_lead": True}, headers=sales)
    await satisfy_capture_gate(client, sales, cid)
    await _set_status(session_factory, cid, status="scoping")

    rows = [t for t in await _tasks(client, dev) if t["kind"] == "impact_confirm"]
    assert len(rows) == 1 and rows[0]["change_id"] == cid

    res = await client.post(f"/api/v1/changes/{cid}/impact/confirm", headers=dev)
    assert res.status_code == 200, res.text
    assert not [t for t in await _tasks(client, dev) if t["kind"] == "impact_confirm"]


async def test_sales_chases_the_customer_response_until_it_lands(
        client, seed, roles, session_factory):
    sales = await _auth(client, "Sales")
    cid = await _create(client, sales, seed, "quote row", customer_relevant=True)
    await _set_status(session_factory, cid, status="quoted")

    rows = [t for t in await _tasks(client, sales) if t["kind"] == "customer_response"]
    assert len(rows) == 1 and rows[0]["change_id"] == cid

    due = (datetime.utcnow() + timedelta(days=45)).isoformat()
    res = await client.post(f"/api/v1/changes/{cid}/customer-response", json={
        "response": "accepted", "release_due_date": due}, headers=sales)
    assert res.status_code == 200, res.text
    assert not [t for t in await _tasks(client, sales)
                if t["kind"] == "customer_response"]


async def test_overdue_rows_sort_first(client, seed, roles, session_factory):
    sales = await _auth(client, "Sales")
    late = await _create(client, sales, seed, "late one", customer_relevant=True)
    soon = await _create(client, sales, seed, "soon one", customer_relevant=True)
    undated = await _create(client, sales, seed, "no date")
    await _set_status(session_factory, late,
                      required_by_date=datetime.utcnow() - timedelta(days=5))
    await _set_status(session_factory, soon,
                      required_by_date=datetime.utcnow() + timedelta(days=90))

    rows = [t for t in await _tasks(client, sales) if t["kind"] == "kickoff"]
    assert [r["change_id"] for r in rows] == [late, soon, undated]
    assert rows[0]["overdue"] is True
    assert rows[1]["overdue"] is False
    assert rows[2]["due_date"] is None


async def test_admin_acting_as_sales_sees_sales_work_only(
        client, admin_auth, seed, roles, session_factory):
    """Acts-as must reach this endpoint too: the department list comes from the
    effective actor, and so do the per-kind role checks."""
    sales = await _auth(client, "Sales")
    cid = await _create(client, sales, seed, "acting row")
    await satisfy_capture_gate(client, sales, cid)
    await _set_status(session_factory, cid, status="scoping")

    acting = {**admin_auth, "X-Acts-As-Department": str(roles["dept"]["Sales"])}
    kinds = {t["kind"] for t in await _tasks(client, acting)}
    # Sales does not wrap up scoping, and does not lock the impacted set
    assert "scoping_wrapup" not in kinds
    assert "impact_confirm" not in kinds


async def test_rows_carry_the_project_identity(client, seed, roles):
    sales = await _auth(client, "Sales")
    cid = await _create(client, sales, seed, "project on the row")
    row = [t for t in await _tasks(client, sales) if t["change_id"] == cid][0]
    assert row["project_id"] == seed["project_id"]
    assert row["project_number"] == "proj"      # Project.code
    assert row["project_name"] == "Project"
