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
    assert res.status_code == 400 and "PPAP decision" in res.json()["detail"]
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
    # a past date is refused; an aware date is read as UTC (no 500)
    res = await client.post(url, json={"answer": "offer",
                                       "quote_deadline": "2020-01-10T12:00:00"}, headers=sales)
    assert res.status_code == 400 and "past" in res.json()["detail"]
    res = await client.post(url, json={"answer": "offer",
                                       "quote_deadline": "2026-11-20T12:00:00Z"}, headers=sales)
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


# ---------------------------------------------------------------------------
# L4 review: the room's cost carrier, notification only, flip past approval
# ---------------------------------------------------------------------------

async def _to_status(session_factory, cid, status, **values):
    from sqlalchemy import update
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == cid)
                        .values(status=status, **values))
        await s.commit()


async def test_customer_change_the_room_sets_internal_owes_ppap_and_proceeds(
        client, admin_auth, seed, session_factory):
    """The deadlock: a customer change whose scoping meeting says internal.
    Quality may answer before proceed, proceed names it with its owner, and
    after the answer proceed goes through and the change is internal."""
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "pp room", "reason": "r",
        "change_type": "physical_part", "customer_relevant": True,
        "lead_id": seed["admin_id"]}, headers=admin_auth)
    cid = res.json()["id"]
    part = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": "ART-PPROOM",
        "name": "Part", "part_type": "internal_mfg"}, headers=admin_auth)
    assert (await client.post(f"/api/v1/changes/{cid}/impacted-items",
                              json={"part_id": part.json()["id"], "is_lead": True},
                              headers=admin_auth)).status_code == 200
    await _to_status(session_factory, cid, "scoping")
    _, qid, quality = await _user(client, session_factory, seed, "q6", "Quality")
    _, _, pm = await _user(client, session_factory, seed, "pm6", "Project Manager")
    mid = await _meeting(client, admin_auth, cid, qid, carrier="internal")
    # the PM's row is not "Ready": it names the PPAP decision and Quality
    rows = await _tasks(client, pm, cid, "scoping_wrapup")
    assert len(rows) == 1 and rows[0]["open_questions"] == 0
    assert [h["key"] for h in rows[0]["holds"]] == ["ppap_decision"]
    assert rows[0]["holds"][0]["owner"].startswith("Quality")
    assert len(await _tasks(client, quality, cid, "ppap_decision")) == 1
    res = await _proceed(client, admin_auth, cid, mid)
    assert res.status_code == 400 and "PPAP decision" in res.json()["detail"]
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)).json()
    item = next(i for i in ch["next_step"]["items"] if i["key"] == "ppap_decision")
    assert item["who"].startswith("Quality, due ")
    res = await _ppap(client, quality, cid, answer="no", basis="process_sheet",
                      ref="PS-2231 rev 4")
    assert res.status_code == 200, res.text
    assert (await _tasks(client, pm, cid, "scoping_wrapup"))[0]["holds"] == []
    res = await _proceed(client, admin_auth, cid, mid)
    assert res.status_code == 200, res.text
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)).json()
    assert ch["status"] == "in_assessment" and ch["customer_relevant"] is False


async def test_proceed_names_every_hold_at_once(client, admin_auth, seed, session_factory):
    """No parts and no PPAP decision: one refusal names both."""
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "pp holds", "reason": "r",
        "change_type": "physical_part", "customer_relevant": False,
        "lead_id": seed["admin_id"]}, headers=admin_auth)
    cid = res.json()["id"]
    await _to_status(session_factory, cid, "scoping")
    _, qid, quality = await _user(client, session_factory, seed, "q7", "Quality")
    mid = await _meeting(client, admin_auth, cid, qid)
    res = await _proceed(client, admin_auth, cid, mid)
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "held by 2 things" in detail
    assert "PPAP decision" in detail and "No impacted parts picked" in detail
    # R18: the lead owns the empty set: a row of its own; Quality's 'yes'
    # says who adds the parts first
    assert len(await _tasks(client, admin_auth, cid, "pick_impacted")) == 1
    assert await _tasks(client, quality, cid, "pick_impacted") == []
    res = await _ppap(client, quality, cid, answer="yes", part_ids=[1])
    assert res.status_code == 400 and "No impacted parts yet" in res.json()["detail"]


async def test_notification_only_goes_on_as_internal(
        client, admin_auth, seed, session_factory):
    """'Notification only': the customer is told, the money stays ours: the
    change goes on as internal (internal approval), no Sales owner, the
    room's carrier follows, so proceed does not flip it back."""
    cid, pid = await _internal_in_scoping(client, admin_auth, seed, "8")
    _, qid, quality = await _user(client, session_factory, seed, "q8", "Quality")
    sally, sales_id, sales = await _user(client, session_factory, seed, "s8", "Sales")
    await _responsible(session_factory, seed, sales_id, sally)
    mid = await _meeting(client, admin_auth, cid, qid, carrier="internal")
    assert (await _ppap(client, quality, cid, answer="yes", part_ids=[pid])).status_code == 200
    res = await client.post(f"/api/v1/changes/{cid}/customer-flip/answer",
                            json={"answer": "notification",
                                  "ref": "Mail to customer 2026-10-15"}, headers=sales)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["customer_relevant"] is False and body["origin"] == "internal"
    assert body["sales_owner_id"] is None and body["flip_ref"] == "Mail to customer 2026-10-15"
    meetings = (await client.get(f"/api/v1/changes/{cid}/meetings", headers=admin_auth)).json()
    assert meetings[-1]["cost_carrier"] == "internal"
    res = await _proceed(client, admin_auth, cid, mid)
    assert res.status_code == 200, res.text
    # the money path is the internal one: costing -> approved by internal approval
    await _to_status(session_factory, cid, "costing")
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)).json()
    assert ch["customer_relevant"] is False
    assert ch["next_step"]["to"] == "approved"
    assert any(i["key"] == "internal_approval" for i in ch["next_step"]["items"])


async def _flip_at(session_factory, cid, status):
    from app.models.change import ChangeRequest
    from app.services.ppap_decision_service import PpapDecisionService
    await _to_status(session_factory, cid, status)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await PpapDecisionService.flip(s, change, 1, "customer index C on part")
        await s.commit()


async def test_flip_past_approval_opens_the_price_only_with_offer_needed(
        client, admin_auth, seed, session_factory):
    _, _, sales = await _user(client, session_factory, seed, "s9", "Sales")
    url = "/api/v1/changes/{}/customer-flip/answer"
    # notification only: no price is open, the close is not held
    cid, _ = await _internal_in_scoping(client, admin_auth, seed, "9a")
    await _flip_at(session_factory, cid, "approved")
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)).json()
    assert ch["customer_relevant"] is True and ch["price_open"] is False
    res = await client.post(url.format(cid), json={
        "answer": "notification", "ref": "Mail to customer 2026-10-15"}, headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["price_open"] is False
    # offer needed: a supplement is owed, the price stays open (HARD #9)
    cid2, _ = await _internal_in_scoping(client, admin_auth, seed, "9b")
    await _flip_at(session_factory, cid2, "approved")
    res = await client.post(url.format(cid2), json={
        "answer": "offer", "quote_deadline": "2026-11-20T12:00:00"}, headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["price_open"] is True


async def test_lead_cannot_drop_a_flip(client, admin_auth, seed, session_factory):
    """L4 review 2: after Quality's 'yes' neither the lead's PATCH nor the
    room's cost carrier takes the change back to internal (HARD #7: the
    customer must be told); only Sales' 'notification only' does."""
    cid, pid = await _internal_in_scoping(client, admin_auth, seed, "10")
    _, qid, quality = await _user(client, session_factory, seed, "q10", "Quality")
    _, _, sales = await _user(client, session_factory, seed, "s10", "Sales")
    mid = await _meeting(client, admin_auth, cid, qid, carrier="internal")
    assert (await _ppap(client, quality, cid, answer="yes", part_ids=[pid])).status_code == 200
    res = await client.patch(f"/api/v1/changes/{cid}",
                             json={"customer_relevant": False}, headers=admin_auth)
    assert res.status_code == 400 and "notification only" in res.json()["detail"]
    res = await client.patch(f"/api/v1/changes/{cid}/meetings/{mid}",
                             json={"cost_carrier": "internal"}, headers=admin_auth)
    assert res.status_code == 400 and "notification only" in res.json()["detail"]
    res = await client.post(f"/api/v1/changes/{cid}/meetings", json={
        "channel": "meeting", "participants": [{"name": "Eva"}],
        "department_rasic": {str(qid): "R"}, "cost_carrier": "internal"},
        headers=admin_auth)
    assert res.status_code == 400
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)).json()
    assert ch["customer_relevant"] is True and ch["customer_flip_at"] is not None
    res = await _proceed(client, admin_auth, cid, mid)
    assert res.status_code == 400 and "notification only, or offer" in res.json()["detail"]
    # offer needed: still a customer change, the lead still may not undo it
    res = await client.post(f"/api/v1/changes/{cid}/customer-flip/answer", json={
        "answer": "offer", "quote_deadline": "2026-11-20T12:00:00"}, headers=sales)
    assert res.status_code == 200, res.text
    res = await client.patch(f"/api/v1/changes/{cid}",
                             json={"customer_relevant": False}, headers=admin_auth)
    assert res.status_code == 400


async def test_back_to_internal_without_a_flip_is_the_leads(
        client, admin_auth, seed, session_factory):
    """No flip: an internal change a starter made customer goes back by the
    lead's PATCH as before."""
    cid, _ = await _internal_in_scoping(client, admin_auth, seed, "10b")
    res = await client.patch(f"/api/v1/changes/{cid}",
                             json={"customer_relevant": True}, headers=admin_auth)
    assert res.status_code == 200, res.text
    res = await client.patch(f"/api/v1/changes/{cid}",
                             json={"customer_relevant": False}, headers=admin_auth)
    assert res.status_code == 200, res.text


async def test_notification_only_restores_the_lead_and_owes_ppap_again(
        client, admin_auth, seed, session_factory):
    """A flip from a customer index (no PPAP decision yet), then 'notification
    only': the raiser leads again, the change is internal, the PPAP decision
    is owed again (HARD #7) and Quality is told."""
    cid, _ = await _internal_in_scoping(client, admin_auth, seed, "11")
    q_uid, qid, _quality = await _user(client, session_factory, seed, "q11", "Quality")
    sally, sales_id, sales = await _user(client, session_factory, seed, "s11", "Sales")
    pm_uid, pm_id, _pm = await _user(client, session_factory, seed, "pm11", "Project Manager")
    await _responsible(session_factory, seed, sales_id, sally)
    await _responsible(session_factory, seed, pm_id, pm_uid)
    mid = await _meeting(client, admin_auth, cid, qid, carrier="internal")
    await _flip_at(session_factory, cid, "scoping")
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)).json()
    assert ch["lead_id"] == pm_uid and ch["customer_relevant"] is True
    res = await client.post(f"/api/v1/changes/{cid}/customer-flip/answer", json={
        "answer": "notification", "ref": "Mail to customer 2026-10-15"}, headers=sales)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["lead_id"] == seed["admin_id"]
    assert body["customer_relevant"] is False and body["origin"] == "internal"
    assert body["sales_owner_id"] is None and body["ppap_decision"] is None
    res = await _proceed(client, admin_auth, cid, mid)
    assert res.status_code == 400 and "PPAP decision" in res.json()["detail"]
    from app.models.notification import Notification
    async with session_factory() as s:
        told = [u for (u,) in await s.execute(select(Notification.user_id).where(
            Notification.title.like("PPAP decision needed%"),
            Notification.link.like(f"/changes/{cid}?%")))]
    assert q_uid in told


async def test_direct_hop_refused_without_ppap_decision(
        client, admin_auth, seed, session_factory):
    """HARD #7 on scoping -> in_assessment by the transition endpoint: an
    admin with an override reason is refused too."""
    cid, _ = await _internal_in_scoping(client, admin_auth, seed, "12")
    for body in ({"to_status": "in_assessment"},
                 {"to_status": "in_assessment", "deviation_reason": "urgent customer line stop",
                  "deviation_reason_code": "in_parallel"}):
        res = await client.post(f"/api/v1/changes/{cid}/transition", json=body,
                                headers=admin_auth)
        assert res.status_code == 400, res.text
        assert "PPAP decision" in res.json()["detail"]


async def test_flip_in_capture_keeps_the_lead_on_the_kickoff_row(
        client, admin_auth, seed, session_factory):
    """A change that flips while captured (a customer index) still owes its
    capture: the lead keeps 'Hand over to scoping' as main owner; Sales sees
    it with the lead named (R18)."""
    dev_uid, _, dev = await _user(client, session_factory, seed, "d13", "Development")
    _, _, sales = await _user(client, session_factory, seed, "s13", "Sales")
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "pp kick", "reason": "r",
        "change_type": "physical_part", "customer_relevant": False,
        "lead_id": dev_uid}, headers=admin_auth)
    assert res.status_code == 200, res.text
    cid = res.json()["id"]
    await _flip_at(session_factory, cid, "captured")
    rows = await _tasks(client, dev, cid, "kickoff")
    assert len(rows) == 1 and rows[0]["role"] == "main"
    rows = await _tasks(client, sales, cid, "kickoff")
    assert len(rows) == 1 and rows[0]["main_name"] == "PP d13"
