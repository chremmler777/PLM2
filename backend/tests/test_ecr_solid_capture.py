"""ECR-solid §2 capture and §3 urgent proceed (switch SCOPING_V2).

- A customer change is complete with a typed customer file (or a filed
  customer mail) and the quote deadline; any attachment is not enough.
- An internal change is complete with "what is wrong today" (a number with
  its unit) and the target.
- Urgent (priority critical): need-by date, reason pick and evidence, or the
  create / edit is refused. Mother-plant changes keep their own SOP.
- Urgent proceed asks "Need-by realistic?"; anything but yes gives Sales
  "Tell customer: new date or start at risk?", answered with evidence.
"""
import pytest
from sqlalchemy import select

from app.models.change import ChangeRequest
from app.models.notification import Notification
from tests.conftest import login, make_department_member, satisfy_capture_gate

pytestmark = pytest.mark.asyncio

URGENT = {"priority": "critical", "release_due_date": "2026-10-30T12:00:00",
          "urgent_reason": "line_stop", "urgent_evidence": "Customer mail 2026-10-15 09:12"}


async def _user(client, session_factory, seed, key, dept=None):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=f"cp-{key}",
                 email=f"cp-{key}@test.io", full_name=f"CP {key}",
                 hashed_password=get_password_hash("cp-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        uid = u.id
    if dept:
        await make_department_member(session_factory, uid, dept)
    return uid, await login(client, f"cp-{key}@test.io")


async def _create(client, auth, seed, title, **body):
    return await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": title, "reason": "r",
        "change_type": "physical_part", "lead_id": seed["admin_id"], **body}, headers=auth)


async def _missing(session_factory, cid):
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        return await ChangeService.kickoff_missing(s, await s.get(ChangeRequest, cid))


async def test_customer_change_needs_a_typed_customer_file(
        client, admin_auth, seed, session_factory):
    cid = (await _create(client, admin_auth, seed, "cust", customer_relevant=True)).json()["id"]
    await client.patch(f"/api/v1/changes/{cid}", json={
        "description": "d", "required_by_date": "2026-12-01T12:00:00Z"}, headers=admin_auth)
    # an untyped file is not the customer's file
    r = await client.post(f"/api/v1/changes/{cid}/attachments",
                          files={"file": ("notes.txt", b"x", "text/plain")}, headers=admin_auth)
    assert r.status_code in (200, 201), r.text
    assert await _missing(session_factory, cid) == ["customer file"]
    r = await client.post(f"/api/v1/changes/{cid}/attachments",
                          files={"file": ("drawing.pdf", b"%PDF", "application/pdf")},
                          data={"kind": "customer_file"}, headers=admin_auth)
    assert r.status_code in (200, 201), r.text
    assert await _missing(session_factory, cid) == []


async def test_internal_change_needs_problem_and_target(
        client, admin_auth, seed, session_factory):
    cid = (await _create(client, admin_auth, seed, "int", customer_relevant=False)).json()["id"]
    await client.patch(f"/api/v1/changes/{cid}", json={"description": "d"}, headers=admin_auth)
    await client.post(f"/api/v1/changes/{cid}/attachments",
                      files={"file": ("photo.jpg", b"x", "image/jpeg")}, headers=admin_auth)
    assert await _missing(session_factory, cid) == ["what is wrong today", "target"]
    # a number without its unit is not an answer
    r = await client.patch(f"/api/v1/changes/{cid}", json={
        "problem_value": 3.5, "target_value": 1.0}, headers=admin_auth)
    assert r.status_code == 200, r.text
    assert await _missing(session_factory, cid) == ["what is wrong today"]
    r = await client.patch(f"/api/v1/changes/{cid}", json={"problem_unit": "% scrap"},
                           headers=admin_auth)
    assert r.status_code == 200, r.text
    assert await _missing(session_factory, cid) == []
    body = r.json()
    assert (body["problem_value"], body["problem_unit"], body["target_value"]) == (3.5, "% scrap", 1.0)


async def test_urgent_needs_need_by_reason_and_evidence(client, admin_auth, seed):
    for drop, word in (("release_due_date", "need-by"), ("urgent_reason", "reason"),
                       ("urgent_evidence", "evidence")):
        body = {k: v for k, v in URGENT.items() if k != drop}
        r = await _create(client, admin_auth, seed, f"urgent no {drop}",
                          customer_relevant=True, **body)
        assert r.status_code == 400 and word in r.json()["detail"], (drop, r.text)
    r = await _create(client, admin_auth, seed, "urgent weak", customer_relevant=True,
                      **{**URGENT, "urgent_evidence": "ok"})
    assert r.status_code == 400
    # a need-by in the past, junk evidence: refused
    for bad in ({"release_due_date": "2026-10-01T12:00:00"}, {"urgent_evidence": "asdfg"},
                {"urgent_evidence": "n/a n/a"}):
        r = await _create(client, admin_auth, seed, "urgent bad", customer_relevant=True,
                          **{**URGENT, **bad})
        assert r.status_code == 400, bad
    r = await _create(client, admin_auth, seed, "urgent ok", customer_relevant=True, **URGENT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["priority"] == "critical" and body["release_due_date"].startswith("2026-10-30")
    assert body["urgent_reason"] == "line_stop"


async def test_making_a_change_urgent_later_needs_the_same(client, admin_auth, seed):
    cid = (await _create(client, admin_auth, seed, "later", customer_relevant=True)).json()["id"]
    r = await client.patch(f"/api/v1/changes/{cid}", json={"priority": "critical"},
                           headers=admin_auth)
    assert r.status_code == 400 and "need-by" in r.json()["detail"]
    r = await client.patch(f"/api/v1/changes/{cid}", json=URGENT, headers=admin_auth)
    assert r.status_code == 200, r.text
    assert r.json()["release_due_date"].startswith("2026-10-30")


async def test_mother_plant_changes_keep_their_own_urgency(client, admin_auth, seed):
    r = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "mp", "reason": "r",
        "change_type": "physical_part", "priority": "critical", "origin": "mother_plant",
        "mother_plant_sop": "2027-01-15"}, headers=admin_auth)
    assert r.status_code == 200, r.text


async def _urgent_in_scoping(client, auth, seed, session_factory, *, customer=True,
                             lead_id=None):
    r = await _create(client, auth, seed, "urgent scoping", customer_relevant=customer,
                      **({"lead_id": lead_id} if lead_id else {}), **URGENT)
    cid = r.json()["id"]
    part = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": f"ART-CPU{cid}", "name": "Part",
        "part_type": "internal_mfg"}, headers=auth)
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": part.json()["id"], "is_lead": True}, headers=auth)
    await satisfy_capture_gate(client, auth, cid)
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "scoping"}, headers=auth)
    assert r.status_code == 200, r.text
    from app.models.workflow import Department
    async with session_factory() as s:
        dept = (await s.execute(select(Department.id).where(
            Department.name == "Tool Engineer"))).scalar_one_or_none()
    if dept is None:
        async with session_factory() as s:
            d = Department(name="Tool Engineer", flow_type="action", is_active=True)
            s.add(d)
            await s.commit()
            dept = d.id
    r = await client.post(f"/api/v1/changes/{cid}/meetings", json={
        "channel": "meeting", "participants": [{"name": "Eva"}],
        "department_rasic": {str(dept): "R"},
        "cost_carrier": "customer" if customer else "internal"}, headers=auth)
    assert r.status_code == 200, r.text
    return cid, r.json()["id"]


async def test_urgent_proceed_asks_whether_the_need_by_is_realistic(
        client, admin_auth, seed, session_factory):
    sally, sales = await _user(client, session_factory, seed, "s1", "Sales")
    _, tool = await _user(client, session_factory, seed, "t1", "Tool Engineer")
    cid, mid = await _urgent_in_scoping(client, admin_auth, seed, session_factory)
    async with session_factory() as s:
        (await s.get(ChangeRequest, cid)).sales_owner_id = sally
        await s.commit()
    url = f"/api/v1/changes/{cid}/meetings/{mid}/decide"
    # negatives: no answer; 'no' without a proposed date
    r = await client.post(url, json={"decision": "proceed"}, headers=admin_auth)
    assert r.status_code == 400 and "realistic" in r.json()["detail"]
    r = await client.post(url, json={"decision": "proceed", "need_by_check": "no"},
                          headers=admin_auth)
    assert r.status_code == 400 and "propose" in r.json()["detail"]
    r = await client.post(url, json={"decision": "proceed", "need_by_check": "at_risk"},
                          headers=admin_auth)
    assert r.status_code == 200, r.text
    rows = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
            if t["kind"] == "need_by_tell" and t["change_id"] == cid]
    assert len(rows) == 1
    async with session_factory() as s:
        notes = (await s.execute(select(Notification).where(
            Notification.user_id == sally,
            Notification.title.like("Tell customer%")))).scalars().all()
    assert len(notes) == 1
    tell = f"/api/v1/changes/{cid}/need-by/tell"
    assert (await client.post(tell, json={"ref": "Mail to buyer 10-15"},
                              headers=tool)).status_code == 403
    assert (await client.post(tell, json={"ref": "tbd"}, headers=sales)).status_code == 400
    r = await client.post(tell, json={"ref": "Mail to buyer 10-15"}, headers=sales)
    assert r.status_code == 200, r.text
    assert r.json()["need_by_told_ref"] == "Mail to buyer 10-15"
    rows = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
            if t["kind"] == "need_by_tell" and t["change_id"] == cid]
    assert rows == []


async def test_realistic_need_by_gives_sales_nothing(client, admin_auth, seed, session_factory):
    _, sales = await _user(client, session_factory, seed, "s2", "Sales")
    cid, mid = await _urgent_in_scoping(client, admin_auth, seed, session_factory)
    r = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                          json={"decision": "proceed", "need_by_check": "yes"}, headers=admin_auth)
    assert r.status_code == 200, r.text
    rows = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
            if t["kind"] == "need_by_tell"]
    assert rows == []


async def test_start_at_risk_off_offers_no_start_before_po(
        client, admin_auth, seed, session_factory, monkeypatch):
    """§2/§3 with §7a switched off: an urgent customer change has no 'start
    at risk' answer; the change serves the switch for "No start before PO"."""
    from app.services import cm_switches
    monkeypatch.setattr(cm_switches, "START_AT_RISK", False)
    cid, mid = await _urgent_in_scoping(client, admin_auth, seed, session_factory)
    assert (await client.get(f"/api/v1/changes/{cid}",
                             headers=admin_auth)).json()["start_at_risk_on"] is False
    url = f"/api/v1/changes/{cid}/meetings/{mid}/decide"
    r = await client.post(url, json={"decision": "proceed", "need_by_check": "at_risk"},
                          headers=admin_auth)
    assert r.status_code == 400 and "no start before PO" in r.json()["detail"]
    r = await client.post(url, json={"decision": "proceed", "need_by_check": "yes"},
                          headers=admin_auth)
    assert r.status_code == 200, r.text


async def test_switch_off_no_capture_rules(client, admin_auth, seed, session_factory, monkeypatch):
    from app.services import cm_switches
    monkeypatch.setattr(cm_switches, "SCOPING_V2", False)
    r = await _create(client, admin_auth, seed, "off", customer_relevant=True, priority="critical")
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert "customer file" not in await _missing(session_factory, cid)


async def test_internal_urgent_not_realistic_tells_the_lead_not_sales(
        client, admin_auth, seed, session_factory):
    """An internal change has no customer and no Sales owner: 'start at
    risk' is not offered, 'no' is recorded and the lead is told; Sales gets
    no task and no notice (R33)."""
    sally, sales = await _user(client, session_factory, seed, "s4", "Sales")
    lead_id, _ = await _user(client, session_factory, seed, "l4", "Development")
    cid, mid = await _urgent_in_scoping(client, admin_auth, seed, session_factory,
                                        customer=False, lead_id=lead_id)
    url = f"/api/v1/changes/{cid}/meetings/{mid}/decide"
    r = await client.post(url, json={"decision": "proceed", "need_by_check": "at_risk"},
                          headers=admin_auth)
    assert r.status_code == 400 and "start at risk" not in r.json()["detail"]
    # the proposed date lies after today and after the need-by
    for early in ("2026-10-01T12:00:00", "2026-10-30T12:00:00"):
        r = await client.post(url, json={"decision": "proceed", "need_by_check": "no",
                                         "need_by_proposed": early}, headers=admin_auth)
        assert r.status_code == 400 and "propose a date after" in r.json()["detail"], early
    r = await client.post(url, json={"decision": "proceed", "need_by_check": "no",
                                     "need_by_proposed": "2026-11-20T12:00:00"},
                          headers=admin_auth)
    assert r.status_code == 200, r.text
    rows = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
            if t["kind"] == "need_by_tell"]
    assert rows == []
    async with session_factory() as s:
        to_sales = (await s.execute(select(Notification).where(
            Notification.user_id == sally, Notification.kind == "need_by_tell"))).scalars().all()
        to_lead = (await s.execute(select(Notification).where(
            Notification.user_id == lead_id,
            Notification.title.like("Urgent need-by not realistic%")))).scalars().all()
    assert to_sales == [] and len(to_lead) == 1


async def test_release_date_moves_on_a_legacy_critical_change(
        client, admin_auth, seed, session_factory):
    """A critical change past capture without urgent reason and evidence (in
    flight before §2) can still move its release deadline."""
    from datetime import datetime
    cid = (await _create(client, admin_auth, seed, "legacy", customer_relevant=True)).json()["id"]
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.priority = "critical"
        c.status = "approved"
        c.release_due_date = datetime(2026, 11, 1, 12)
        await s.commit()
    r = await client.patch(f"/api/v1/changes/{cid}", json={
        "release_due_date": "2026-11-15T12:00:00",
        "release_due_reason": "Tool trial moved, mail 2026-10-15"}, headers=admin_auth)
    assert r.status_code == 200, r.text
    assert r.json()["release_due_date"].startswith("2026-11-15")
    # making the urgency itself move still asks for reason and evidence
    r = await client.patch(f"/api/v1/changes/{cid}", json={"urgent_reason": "other"},
                           headers=admin_auth)
    assert r.status_code == 400
