"""DECIDED BY CHRISTOPH 2026-10-19 (D2): Project Management owns the ECR
process from capture to close. The project's lead PM (the project team's
Project Manager responsible) leads every change on the project by default;
the hand-over to scoping, the follow-up and the escalation of an
implementation risk are the lead's rows. Sales keeps the customer-facing
commercial part (quote deadline, offer, customer answer) as the change's
Sales contact."""
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from app.auth.security import get_password_hash
from app.models.change import ChangeRequest
from app.models.entities import User
from app.models.workflow import Department, ProjectResponsible, UserDepartment
from tests.conftest import login

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def team(session_factory, seed):
    """Sales (the seed engineer joins it) and Project Manager (Pat)."""
    async with session_factory() as s:
        ids = {}
        for i, n in enumerate(("Sales", "Project Manager")):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i,
                           can_start_change=True)
            s.add(d); await s.flush(); ids[n] = d.id
        pat = User(organization_id=seed["org_id"], username="pat", email="pat@test.io",
                   full_name="Pat PM", hashed_password=get_password_hash("pat-secret-1"),
                   role="engineer", is_active=True, mfa_enabled=False)
        s.add(pat); await s.flush()
        s.add(UserDepartment(user_id=pat.id, department_id=ids["Project Manager"]))
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=ids["Sales"]))
        await s.commit()
        return {"dept": ids, "pat": pat.id}


async def _lead_pm(session_factory, seed, team):
    async with session_factory() as s:
        s.add(ProjectResponsible(project_id=seed["project_id"],
                                 department_id=team["dept"]["Project Manager"],
                                 user_id=team["pat"]))
        await s.commit()


async def _create(client, headers, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "d2", "reason": "r",
        "change_type": "physical_part", "customer_relevant": True}, headers=headers)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _rows(client, headers, kind, cid):
    res = await client.get("/api/v1/changes/my-tasks", headers=headers)
    assert res.status_code == 200, res.text
    return [t for t in res.json() if t["kind"] == kind and t["change_id"] == cid]


async def test_sales_started_change_is_led_by_the_project_lead_pm(
        client, seed, team, session_factory):
    await _lead_pm(session_factory, seed, team)
    sales = await login(client, "eng@test.io", admin=False)
    c = await _create(client, sales, seed)
    assert c["lead_id"] == team["pat"]
    # Sales keeps the commercial side as the Sales contact
    assert c["sales_owner_id"] == seed["engineer_id"]


async def test_hand_over_is_the_lead_pms_row_not_sales(
        client, seed, team, session_factory):
    await _lead_pm(session_factory, seed, team)
    sales = await login(client, "eng@test.io", admin=False)
    c = await _create(client, sales, seed)
    pat = await login(client, "pat@test.io", admin=False)
    [row] = await _rows(client, pat, "kickoff", c["id"])
    assert row["role"] == "main" and row["is_mine"]
    # NEGATIVE: the Sales raiser (and Sales contact) no longer owns it: a
    # backup row naming the lead PM
    [row] = await _rows(client, sales, "kickoff", c["id"])
    assert row["role"] == "backup"
    assert row["main_name"] == "Pat PM"
    assert not row["is_mine"]


async def test_no_lead_pm_sets_the_lead_refusal_names_the_default(
        client, seed, team, session_factory):
    sales = await login(client, "eng@test.io", admin=False)
    c = await _create(client, sales, seed)
    assert c["lead_id"] is None          # the project names no lead PM
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "scoping"}, headers=sales)
    assert res.status_code == 403
    detail = res.json()["detail"]
    assert "Project Management" in detail and "lead PM" in detail
    # Project Management's row is the one main row
    pat = await login(client, "pat@test.io", admin=False)
    [row] = await _rows(client, pat, "kickoff", c["id"])
    assert row["role"] == "main"
    assert "lead" in row["hint"].lower()


async def test_overdue_digest_names_the_lead_for_the_hand_over(
        client, seed, team, session_factory):
    from app.services.overdue_digest import overdue_lines
    await _lead_pm(session_factory, seed, team)
    sales = await login(client, "eng@test.io", admin=False)
    c = await _create(client, sales, seed)
    async with session_factory() as s:
        ch = await s.get(ChangeRequest, c["id"])
        ch.created_at = datetime.utcnow() - timedelta(days=20)
        await s.commit()
    from app.services import cm_switches
    if not cm_switches.on("RELEASE_V2"):
        pytest.skip("digest needs RELEASE_V2")
    async with session_factory() as s:
        lines = [x for x in await overdue_lines(s) if x.startswith(c["change_number"])]
    assert lines, "the late hand-over is in the digest"
    assert "Lead Pat PM: hand over to scoping" in lines[0]
    # NEGATIVE: not owed by Sales any more
    assert "Sales (" not in lines[0] and "Sales:" not in lines[0]
