"""ECR-solid §11 (lane L7, switch RELEASE_V2): release -> close.

An internal change closes with what it achieved beside its target (SOFT
rule 'achieved_missing', the run team may override); the lead, Project
Management or an admin record it with where the number comes from.
Closing tells the Sales owner (internal: the lead) and Process once,
never the closer. The header shows the concessions in force.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models.change_validation_issue import ValidationIssue
from app.models.notification import Notification
from app.models.workflow import Department, UserDepartment
from app.services import cm_switches
from tests.test_ecr_solid_gates import _change, admin, depts, people  # noqa: F401
from tests.conftest import login

pytestmark = pytest.mark.asyncio


async def _released(client, admin, seed, session_factory, *, customer=False, **values):
    return await _change(client, admin, seed, session_factory, "released",
                         customer=customer, **values)


async def _close(client, auth, cid):
    return await client.post(f"/api/v1/changes/{cid}/transition",
                             json={"to_status": "closed"}, headers=auth)


async def test_internal_close_asks_the_achieved_value(
        client, admin, seed, depts, people, session_factory):
    cid = await _released(client, admin, seed, session_factory,
                          problem_value=4.2, problem_unit="%", target_value=1.0)
    res = await _close(client, admin, cid)
    assert res.status_code == 400, res.text
    assert "Achieved value not entered (target 1 %, was 4.2 %)" in res.json()["detail"]
    assert res.headers.get("X-Deviation-Required") == "closed"   # SOFT
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin)).json()
    item = next(i for i in ch["next_step"]["items"] if i["key"] == "achieved")
    assert item["kind"] == "soft" and item["rule"] == "achieved_missing"
    # NEGATIVE: not a member of the run team; no source; a customer change
    url = f"/api/v1/changes/{cid}/achieved"
    res = await client.post(url, json={"value": 0.8, "ref": "SPC chart line 4, week 41"},
                            headers=people["Sales"][1])
    assert res.status_code == 403, res.text
    for ref in ("ok", ""):
        res = await client.post(url, json={"value": 0.8, "ref": ref}, headers=admin)
        assert res.status_code == 400, res.text
    lead = await login(client, "eng@test.io", admin=False)
    res = await client.post(url, json={"value": 0.8, "ref": "SPC chart line 4, week 41"},
                            headers=lead)
    assert res.status_code == 200, res.text
    assert res.json()["achieved_value"] == 0.8
    res = await _close(client, admin, cid)
    assert res.status_code == 200, res.text


async def test_negative_customer_change_has_no_achieved_value(
        client, admin, seed, depts, people, session_factory):
    cid = await _released(client, admin, seed, session_factory, customer=True,
                          sales_owner_id=people["Sales"][0], target_value=1.0)
    res = await client.post(f"/api/v1/changes/{cid}/achieved",
                            json={"value": 1, "ref": "report MR-2026-130"}, headers=admin)
    assert res.status_code == 400
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin)).json()
    assert not any(i["key"] == "achieved" for i in ch["next_step"]["items"])


async def test_close_tells_the_sales_owner_and_process_once(
        client, admin, seed, depts, people, session_factory):
    async with session_factory() as s:
        d = Department(name="Process Engineer", flow_type="action", is_active=True)
        s.add(d)
        await s.flush()
        s.add(UserDepartment(user_id=people["Quality"][0], department_id=d.id))
        await s.commit()
    cid = await _released(client, admin, seed, session_factory, customer=True,
                          sales_owner_id=people["Sales"][0])
    res = await _close(client, admin, cid)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        rows = (await s.execute(select(Notification).where(
            Notification.kind == "change_closed"))).scalars().all()
    assert sorted(r.user_id for r in rows) == sorted(
        [people["Sales"][0], people["Quality"][0]])


async def test_header_shows_the_concession_in_force(
        client, admin, seed, depts, session_factory):
    cid = await _change(client, admin, seed, session_factory, "in_validation", customer=False)
    until = date.today() + timedelta(days=30)
    async with session_factory() as s:
        s.add(ValidationIssue(change_id=cid, number=3, title="weight", created_by=1,
                              description="518 g", route="customer_concession",
                              status="accepted", customer_decision="accept_deviation",
                              concession_until=until))
        await s.commit()
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin)).json()
    assert [c["text"] for c in ch["active_concessions"]] == [
        f"Accepted under concession VI-3 until {until.isoformat()}"]


async def test_switch_off_closes_without_achieved_value(
        client, admin, seed, depts, session_factory, monkeypatch):
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    cid = await _released(client, admin, seed, session_factory, target_value=1.0)
    assert (await _close(client, admin, cid)).status_code == 200
