"""Closing the needs-info loop: a decision raises a Team flag, Sales gets the
task, and the question/answer documents are linked to each other."""
import pytest

from tests.conftest import login, satisfy_capture_gate

pytestmark = pytest.mark.asyncio


async def _change_in_scoping(client, auth, seed, suffix):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": f"ni {suffix}", "reason": "r",
        "change_type": "physical_part", "lead_id": seed["admin_id"]}, headers=auth)
    assert res.status_code == 200, res.text
    cid = res.json()["id"]
    await satisfy_capture_gate(client, auth, cid)
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "scoping"}, headers=auth)
    assert res.status_code == 200, res.text
    return cid


async def _upload(client, auth, cid, name, **form):
    return await client.post(
        f"/api/v1/changes/{cid}/attachments",
        files={"file": (name, b"x", "text/plain")}, data=form, headers=auth)


# --- part 1: classification -------------------------------------------------

async def test_attachment_defaults_to_general(client, admin_auth, seed):
    cid = await _change_in_scoping(client, admin_auth, seed, "1")
    res = await _upload(client, admin_auth, cid, "any.txt")
    assert res.status_code in (200, 201), res.text
    assert res.json()["kind"] == "general"
    assert res.json()["responds_to_id"] is None


async def test_response_links_back_to_its_request(client, admin_auth, seed):
    cid = await _change_in_scoping(client, admin_auth, seed, "2")
    q = (await _upload(client, admin_auth, cid, "question.pdf",
                       kind="info_request")).json()
    assert q["kind"] == "info_request"
    a = await _upload(client, admin_auth, cid, "answer.pdf",
                      kind="info_response", responds_to_id=q["id"])
    assert a.status_code in (200, 201), a.text
    assert a.json()["responds_to_id"] == q["id"]

    detail = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)).json()
    by_name = {x["filename"]: x for x in detail["attachments"]}
    assert by_name["answer.pdf"]["kind"] == "info_response"
    assert by_name["answer.pdf"]["responds_to_id"] == q["id"]


async def test_link_validations(client, admin_auth, seed):
    cid = await _change_in_scoping(client, admin_auth, seed, "3")
    other = await _change_in_scoping(client, admin_auth, seed, "4")
    q = (await _upload(client, admin_auth, cid, "q.pdf", kind="info_request")).json()
    general = (await _upload(client, admin_auth, cid, "g.pdf")).json()

    # unknown kind
    res = await _upload(client, admin_auth, cid, "x.pdf", kind="nonsense")
    assert res.status_code == 400 and "kind" in res.json()["detail"]
    # only an info_response may link
    res = await _upload(client, admin_auth, cid, "x.pdf", kind="general",
                        responds_to_id=q["id"])
    assert res.status_code == 400
    # the target must be an info_request
    res = await _upload(client, admin_auth, cid, "x.pdf", kind="info_response",
                        responds_to_id=general["id"])
    assert res.status_code == 400
    # ...on THIS change
    res = await _upload(client, admin_auth, other, "x.pdf", kind="info_response",
                        responds_to_id=q["id"])
    assert res.status_code == 400


# --- part 2: the decision raises the Team flag itself -----------------------

async def _departments(session_factory):
    from sqlalchemy import select
    from app.models.workflow import Department
    from app.services.wf_seed_service import seed_assessment_standard
    async with session_factory() as s:
        await seed_assessment_standard(s)
        await s.commit()
    async with session_factory() as s:
        return [d for (d,) in await s.execute(select(Department.id).limit(1))]


async def _meeting(client, auth, cid, dept_ids):
    res = await client.post(f"/api/v1/changes/{cid}/meetings", json={
        "channel": "meeting", "participants": [{"name": "Eva"}],
        "selected_department_ids": dept_ids}, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _decide(client, auth, cid, mid, decision, reason=None):
    body = {"decision": decision}
    if reason:
        body["reason"] = reason
    return await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                             json=body, headers=auth)


async def test_needs_info_decision_raises_one_team_flag(
        client, admin_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "5")
    depts = await _departments(session_factory)
    mid = await _meeting(client, admin_auth, cid, depts)
    res = await _decide(client, admin_auth, cid, mid, "needs_info",
                        "Customer drawing missing")
    assert res.status_code == 200, res.text

    concerns = (await client.get(f"/api/v1/changes/{cid}/concerns",
                                 headers=admin_auth)).json()
    open_ = [c for c in concerns if c["is_open"]]
    assert len(open_) == 1
    assert open_[0]["kind"] == "needs_info"
    assert open_[0]["department_id"] is None          # a Team flag
    assert open_[0]["note"] == "Customer drawing missing"
    assert open_[0]["raised_by"] == seed["admin_id"]  # the decider owns it

    # ...and it behaves like any other open concern: proceed is blocked
    mid2 = await _meeting(client, admin_auth, cid, depts)
    blocked = await _decide(client, admin_auth, cid, mid2, "proceed")
    assert blocked.status_code == 400
    assert "open concern" in blocked.json()["detail"]

    # a second needs_info from the same decider is the same question, not a new one
    res = await _decide(client, admin_auth, cid, mid2, "needs_info", "Still missing")
    assert res.status_code == 200, res.text
    concerns = (await client.get(f"/api/v1/changes/{cid}/concerns",
                                 headers=admin_auth)).json()
    assert len([c for c in concerns if c["is_open"]]) == 1


# --- part 3: Sales owns going and getting it -------------------------------

async def _sales_member(client, session_factory, seed):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    from app.models.workflow import Department, UserDepartment
    from sqlalchemy import select
    async with session_factory() as s:
        dept = (await s.execute(select(Department).where(
            Department.name == "Sales"))).scalar_one_or_none()
        if dept is None:
            dept = Department(name="Sales", flow_type="action", is_active=True)
            s.add(dept)
            await s.flush()
        u = User(organization_id=seed["org_id"], username="salesperson",
                 email="salesperson@test.io", full_name="Sales Person",
                 hashed_password=get_password_hash("sales-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=dept.id))
        await s.commit()
        return await login(client, "salesperson@test.io")


async def test_obtain_info_row_appears_for_sales_and_clears_on_a_decision(
        client, admin_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "6")
    depts = await _departments(session_factory)
    sales = await _sales_member(client, session_factory, seed)

    async def rows():
        res = await client.get("/api/v1/changes/my-tasks", headers=sales)
        assert res.status_code == 200, res.text
        return [t for t in res.json()
                if t["kind"] == "obtain_info" and t["change_id"] == cid]

    assert await rows() == []

    mid = await _meeting(client, admin_auth, cid, depts)
    await _decide(client, admin_auth, cid, mid, "needs_info", "Send us the CAD")
    got = await rows()
    assert len(got) == 1
    assert got[0]["reason"] == "Send us the CAD"
    assert got[0]["project_number"] == "proj"

    # a follow-up decision closes the loop; the row goes away
    concerns = (await client.get(f"/api/v1/changes/{cid}/concerns",
                                 headers=admin_auth)).json()
    open_id = next(c["id"] for c in concerns if c["is_open"])
    await client.delete(f"/api/v1/changes/{cid}/concerns/{open_id}",
                        headers=admin_auth)
    mid2 = await _meeting(client, admin_auth, cid, depts)
    res = await _decide(client, admin_auth, cid, mid2, "reject", "Not economical")
    assert res.status_code == 200, res.text
    assert await rows() == []
