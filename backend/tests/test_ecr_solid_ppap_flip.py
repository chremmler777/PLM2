"""HARD #7 ppap_decision and the customer flip (spec §0, §3; SCOPING_V2).

An internal change proceeds only once Quality answered "parameters / tool /
material / cycle time changed on any part?": 'no' with its basis and a
reference, 'yes' with the parts. 'yes' flips the change to a customer change
(Sales owner = the project's Sales contact, lead = the project PM) and the
Sales owner answers "notification only" (mail / ref) or "offer needed" (quote
deadline); proceed waits for that answer.
"""
import pytest
from sqlalchemy import select

from tests.conftest import login, make_department_member, satisfy_capture_gate

pytestmark = pytest.mark.asyncio


async def _user(client, session_factory, seed, key, dept=None):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=f"pp-{key}",
                 email=f"pp-{key}@test.io", full_name=f"PP {key}",
                 hashed_password=get_password_hash("pp-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        uid = u.id
    dept_id = (await make_department_member(session_factory, uid, dept)
               if dept else None)
    return uid, dept_id, await login(client, f"pp-{key}@test.io")


async def _responsible(session_factory, seed, dept_id, uid):
    from app.models.workflow import ProjectResponsible
    async with session_factory() as s:
        s.add(ProjectResponsible(project_id=seed["project_id"],
                                 department_id=dept_id, user_id=uid))
        await s.commit()


async def _internal_in_scoping(client, auth, seed, suffix):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": f"pp {suffix}", "reason": "r",
        "change_type": "physical_part", "customer_relevant": False,
        "lead_id": seed["admin_id"]}, headers=auth)
    assert res.status_code == 200, res.text
    cid = res.json()["id"]
    part = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": f"ART-PP{suffix}",
        "name": "Part", "part_type": "internal_mfg"}, headers=auth)
    pid = part.json()["id"]
    r = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                          json={"part_id": pid, "is_lead": True}, headers=auth)
    assert r.status_code == 200, r.text
    await satisfy_capture_gate(client, auth, cid, answer_ppap=False)
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "scoping"}, headers=auth)
    assert res.status_code == 200, res.text
    return cid, pid


async def _meeting(client, auth, cid, dept_id, carrier="internal"):
    res = await client.post(f"/api/v1/changes/{cid}/meetings", json={
        "channel": "meeting", "participants": [{"name": "Eva"}],
        "department_rasic": {str(dept_id): "R"}, "cost_carrier": carrier},
        headers=auth)
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _proceed(client, auth, cid, mid):
    return await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                             json={"decision": "proceed"}, headers=auth)


async def _ppap(client, auth, cid, **body):
    return await client.post(f"/api/v1/changes/{cid}/ppap-decision", json=body,
                             headers=auth)


async def _tasks(client, auth, cid, kind):
    res = await client.get("/api/v1/changes/my-tasks", headers=auth)
    assert res.status_code == 200, res.text
    return [t for t in res.json() if t["kind"] == kind and t["change_id"] == cid]


async def test_internal_change_proceeds_only_after_quality_answers(
        client, admin_auth, seed, session_factory):
    cid, _ = await _internal_in_scoping(client, admin_auth, seed, "1")
    _, qid, quality = await _user(client, session_factory, seed, "q1", "Quality")
    _, _, tool = await _user(client, session_factory, seed, "t1", "Tool Engineer")
    mid = await _meeting(client, admin_auth, cid, qid)
    res = await _proceed(client, admin_auth, cid, mid)
    assert res.status_code == 400 and "HARD #7" in res.json()["detail"]
    # Quality sees it under Needs you; nobody else
    rows = await _tasks(client, quality, cid, "ppap_decision")
    assert len(rows) == 1 and rows[0]["needs_you"] is True
    assert await _tasks(client, tool, cid, "ppap_decision") == []
    # negatives: not Quality; 'no' without basis; 'no' with an empty reference
    assert (await _ppap(client, tool, cid, answer="no", basis="control_plan",
                        ref="CP-4711 rev 3")).status_code == 403
    assert (await _ppap(client, quality, cid, answer="no", ref="CP-4711")).status_code == 400
    res = await _ppap(client, quality, cid, answer="no", basis="control_plan", ref="ok")
    assert res.status_code == 400
    res = await _ppap(client, quality, cid, answer="no", basis="control_plan",
                      ref="CP-4711 rev 3")
    assert res.status_code == 200, res.text
    assert res.json()["ppap_decision"] == "no"
    assert res.json()["customer_relevant"] is False
    assert await _tasks(client, quality, cid, "ppap_decision") == []
    res = await _proceed(client, admin_auth, cid, mid)
    assert res.status_code == 200, res.text


async def test_yes_flips_to_a_customer_change_and_proceed_waits_for_sales(
        client, admin_auth, seed, session_factory):
    cid, pid = await _internal_in_scoping(client, admin_auth, seed, "2")
    _, qid, quality = await _user(client, session_factory, seed, "q2", "Quality")
    sally, sales_id, sales = await _user(client, session_factory, seed, "s2", "Sales")
    pm_uid, pm_id, _pm = await _user(client, session_factory, seed, "pm2", "Project Manager")
    _, _, tool = await _user(client, session_factory, seed, "t2", "Tool Engineer")
    await _responsible(session_factory, seed, sales_id, sally)
    await _responsible(session_factory, seed, pm_id, pm_uid)
    mid = await _meeting(client, admin_auth, cid, qid, carrier="internal")
    # negative: 'yes' without parts, or with a part outside the set
    assert (await _ppap(client, quality, cid, answer="yes")).status_code == 400
    assert (await _ppap(client, quality, cid, answer="yes",
                        part_ids=[pid + 999])).status_code == 400
    res = await _ppap(client, quality, cid, answer="yes", part_ids=[pid])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["customer_relevant"] is True and body["origin"] == "customer"
    assert body["sales_owner_id"] == sally and body["lead_id"] == pm_uid
    assert body["customer_flip_at"] is not None and body["flip_answer"] is None
    # the open meeting's carrier followed, so proceed will not flip it back
    meetings = (await client.get(f"/api/v1/changes/{cid}/meetings", headers=admin_auth)).json()
    assert meetings[-1]["cost_carrier"] == "customer"
    # the Sales owner is told once, and owns the task
    from app.models.notification import Notification
    async with session_factory() as s:
        notes = (await s.execute(select(Notification).where(
            Notification.user_id == sally,
            Notification.title.like("Customer notification or offer needed?%")))).scalars().all()
    assert len(notes) == 1
    assert len(await _tasks(client, sales, cid, "customer_flip")) == 1
    res = await _proceed(client, admin_auth, cid, mid)
    assert res.status_code == 400 and "notification only, or offer" in res.json()["detail"]
    # negatives: not Sales; notification with an empty reference
    url = f"/api/v1/changes/{cid}/customer-flip/answer"
    assert (await client.post(url, json={"answer": "notification", "ref": "Mail 2026-10-15"},
                              headers=tool)).status_code == 403
    assert (await client.post(url, json={"answer": "notification", "ref": "tbd"},
                              headers=sales)).status_code == 400
    res = await client.post(url, json={"answer": "notification",
                                       "ref": "Mail to customer 2026-10-15"}, headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["flip_answer"] == "notification"
    assert await _tasks(client, sales, cid, "customer_flip") == []
    # notification only: no quote deadline owed, proceed goes through
    res = await _proceed(client, admin_auth, cid, mid)
    assert res.status_code == 200, res.text


async def test_offer_needed_sets_the_quote_deadline(
        client, admin_auth, seed, session_factory):
    cid, pid = await _internal_in_scoping(client, admin_auth, seed, "3")
    _, _, quality = await _user(client, session_factory, seed, "q3", "Quality")
    _, _, sales = await _user(client, session_factory, seed, "s3", "Sales")
    assert (await _ppap(client, quality, cid, answer="yes", part_ids=[pid])).status_code == 200
    url = f"/api/v1/changes/{cid}/customer-flip/answer"
    assert (await client.post(url, json={"answer": "offer"}, headers=sales)).status_code == 400
    res = await client.post(url, json={"answer": "offer",
                                       "quote_deadline": "2026-11-20T12:00:00"}, headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["required_by_date"].startswith("2026-11-20")


async def test_customer_change_owes_no_ppap_decision(
        client, admin_auth, seed, session_factory):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "pp cust", "reason": "r",
        "change_type": "physical_part", "customer_relevant": True,
        "lead_id": seed["admin_id"]}, headers=admin_auth)
    cid = res.json()["id"]
    _, _, quality = await _user(client, session_factory, seed, "q4", "Quality")
    res = await _ppap(client, quality, cid, answer="no", basis="control_plan",
                      ref="CP-4711 rev 3")
    assert res.status_code == 400 and "internal" in res.json()["detail"]


async def test_switch_off_no_gate(client, admin_auth, seed, session_factory, monkeypatch):
    from app.services import cm_switches
    monkeypatch.setattr(cm_switches, "SCOPING_V2", False)
    cid, _ = await _internal_in_scoping(client, admin_auth, seed, "5")
    _, qid, quality = await _user(client, session_factory, seed, "q5", "Quality")
    mid = await _meeting(client, admin_auth, cid, qid)
    assert await _tasks(client, quality, cid, "ppap_decision") == []
    res = await _proceed(client, admin_auth, cid, mid)
    assert res.status_code == 200, res.text
