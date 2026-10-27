"""First live ECR test, scoping findings (2026-10-14).

1. A scoping question stays the ASKING department's task: that department
   (or, with none, its author), Sales and Project Management answer it, and
   all of them get the obtain_info task. Closing stays asker or PM.
2. 'proceed' over open flags is refused with every flag listed.
3. Development's impact confirm is parked behind a switch: 'proceed' locks the
   picked set on the decider's name and refuses an empty one.
4. The PM's scope definition: written in captured/scoping, audited, read only
   afterwards.
"""
import pytest
from sqlalchemy import select

from tests.conftest import (
    QUESTION, insert_legacy_concern, login, make_department_member, satisfy_capture_gate,
)


@pytest.fixture(autouse=True)
def _any_member_may_ask(monkeypatch):
    """These tests work the question mechanics with department askers; who
    may raise in scoping (PM / lead only since 2026-10-27) is tested in
    test_scoping_pm_questions.py."""
    from app.services import cm_switches
    monkeypatch.setattr(cm_switches, "SCOPING_QUESTIONS_PM_ONLY", False)

pytestmark = pytest.mark.asyncio
HEADER = "X-Acts-As-Department"


async def _user(client, session_factory, seed, key, dept=None):
    """A non-admin user (optionally in a department) and their auth."""
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=f"lt-{key}",
                 email=f"lt-{key}@test.io", full_name=f"LT {key}",
                 hashed_password=get_password_hash("lt-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        uid = u.id
    dept_id = (await make_department_member(session_factory, uid, dept)
               if dept else None)
    return uid, dept_id, await login(client, f"lt-{key}@test.io")


async def _change_in_scoping(client, auth, seed, suffix, with_part=True):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": f"lt {suffix}", "reason": "r",
        "change_type": "physical_part", "lead_id": seed["admin_id"]}, headers=auth)
    assert res.status_code == 200, res.text
    cid = res.json()["id"]
    if with_part:
        part = await client.post("/api/v1/parts", json={
            "project_id": seed["project_id"], "part_number": f"ART-LT{suffix}",
            "name": "Part", "part_type": "internal_mfg"}, headers=auth)
        assert part.status_code in (200, 201), part.text
        r = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                              json={"part_id": part.json()["id"], "is_lead": True},
                              headers=auth)
        assert r.status_code == 200, r.text
    await satisfy_capture_gate(client, auth, cid)
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "scoping"}, headers=auth)
    assert res.status_code == 200, res.text
    return cid


async def _dept_ids(session_factory):
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
        "selected_department_ids": dept_ids, "cost_carrier": "customer"}, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _decide(client, auth, cid, mid, decision, reason=None):
    body = {"decision": decision, **({"reason": reason} if reason else {})}
    return await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                             json=body, headers=auth)


async def _obtain_rows(client, auth, cid):
    res = await client.get("/api/v1/changes/my-tasks", headers=auth)
    assert res.status_code == 200, res.text
    return [t for t in res.json() if t["kind"] == "obtain_info" and t["change_id"] == cid]


async def _answer(client, auth, cid, concern_id, note="An answer"):
    # SCOPING_V2 (A2-02): a scoping question takes the answer form
    return await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                             json={"note": note, "answer_kind": "assumed",
                                   "assumed_value": "n/a",
                                   "assumed_risk": "rework if it is wrong"},
                             headers=auth)


# --- 1. questions stay the asking department's -----------------------------

async def test_department_question_is_the_asking_departments_task(
        client, admin_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "1")
    apqp_uid, apqp_id, apqp = await _user(client, session_factory, seed, "apqp", "APQP")
    _, _, apqp2 = await _user(client, session_factory, seed, "apqp2", "APQP")
    _, _, sales = await _user(client, session_factory, seed, "sales", "Sales")
    _, _, pm = await _user(client, session_factory, seed, "pm", "Project Manager")
    _, _, tool = await _user(client, session_factory, seed, "tool", "Tool Engineer")
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=apqp, json={
        "kind": "needs_info", "note": "Which tolerance class?", "department_id": apqp_id, **QUESTION})
    assert res.status_code == 200, res.text
    qid = res.json()["id"]

    # the task: asking department (any member), Sales and PM, never an outsider
    for auth in (apqp, apqp2, sales, pm):
        rows = await _obtain_rows(client, auth, cid)
        assert len(rows) == 1, rows
        assert rows[0]["asking_side"] == "APQP"
        assert rows[0]["department_id"] == apqp_id
    assert await _obtain_rows(client, tool, cid) == []

    # the card says who it waits on and who may answer
    def row(listing):
        return next(c for c in listing.json() if c["id"] == qid)
    mine = row(await client.get(f"/api/v1/changes/{cid}/concerns", headers=apqp2))
    assert mine["asking_department_name"] == "APQP" and mine["can_answer"] is True
    other = row(await client.get(f"/api/v1/changes/{cid}/concerns", headers=tool))
    assert other["can_answer"] is False

    assert (await _answer(client, tool, cid, qid)).status_code == 400
    for auth in (apqp2, sales, pm):
        assert (await _answer(client, auth, cid, qid)).status_code == 200
    # answered: the obtain_info task is gone; closing stays asker or PM
    assert await _obtain_rows(client, apqp, cid) == []
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{qid}/withdraw",
                            json={"resolution_note": "ok"}, headers=sales)
    assert res.status_code == 400


async def test_question_without_department_is_the_authors(
        client, admin_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "2")
    uid, _, author = await _user(client, session_factory, seed, "author")
    _, _, other = await _user(client, session_factory, seed, "other")
    qid = await insert_legacy_concern(session_factory, cid, kind="needs_info",
                                      note="Is the drawing final?", raised_by=uid)
    rows = await _obtain_rows(client, author, cid)
    assert len(rows) == 1 and rows[0]["asking_side"] == "LT author"
    assert rows[0]["is_mine"] is True
    assert await _obtain_rows(client, other, cid) == []
    assert (await _answer(client, other, cid, qid)).status_code == 400
    assert (await _answer(client, author, cid, qid)).status_code == 200


async def test_acting_as_is_exactly_that_department(
        client, admin_auth, seed, session_factory):
    """An admin who asked a question personally loses the author right while
    acting as a department, and gains that department's right."""
    from app.models.workflow import Department
    cid = await _change_in_scoping(client, admin_auth, seed, "3")
    apqp_id = await make_department_member(session_factory, seed["engineer_id"], "APQP")
    async with session_factory() as s:
        tool = Department(name="Tool Engineer", flow_type="action", is_active=True)
        s.add(tool)
        await s.commit()
        tool_id = tool.id
    own = await insert_legacy_concern(session_factory, cid, kind="needs_info",
                                      note="Own question", raised_by=seed["admin_id"])
    apqp_q = await insert_legacy_concern(session_factory, cid, kind="needs_info",
                                         note="APQP question", raised_by=seed["engineer_id"],
                                         department_id=apqp_id)
    as_tool = {**admin_auth, HEADER: str(tool_id)}
    as_apqp = {**admin_auth, HEADER: str(apqp_id)}
    assert (await _answer(client, as_tool, cid, own)).status_code == 400
    assert (await _answer(client, as_tool, cid, apqp_q)).status_code == 400
    assert (await _answer(client, as_apqp, cid, apqp_q)).status_code == 200


async def test_meeting_question_belongs_to_the_deciders_department(
        client, admin_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "4")
    depts = await _dept_ids(session_factory)
    pm_uid, pm_dept, pm = await _user(client, session_factory, seed, "pmd", "Project Manager")
    _, _, pm2 = await _user(client, session_factory, seed, "pmd2", "Project Manager")
    _, _, tool = await _user(client, session_factory, seed, "toold", "Tool Engineer")
    mid = await _meeting(client, pm, cid, depts)
    res = await _decide(client, pm, cid, mid, "needs_info", "Send us the CAD")
    assert res.status_code == 200, res.text
    q = next(c for c in (await client.get(f"/api/v1/changes/{cid}/concerns",
                                          headers=pm2)).json() if c["is_open"])
    assert q["department_id"] == pm_dept and q["raised_by"] == pm_uid
    assert q["asking_department_name"] == "Project Manager"
    assert q["can_answer"] is True
    rows = await _obtain_rows(client, pm2, cid)
    assert len(rows) == 1 and rows[0]["asking_side"] == "Project Manager"
    assert (await _answer(client, tool, cid, q["id"])).status_code == 400


# --- 2. proceed over open flags: refused, each flag listed ------------------

async def test_proceed_refusal_lists_every_open_flag(
        client, admin_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "5")
    depts = await _dept_ids(session_factory)
    _, apqp_id, apqp = await _user(client, session_factory, seed, "apqp5", "APQP")
    await client.post(f"/api/v1/changes/{cid}/concerns", headers=apqp, json={
        "kind": "needs_info", "note": "Tolerance?", "department_id": apqp_id, **QUESTION})
    await client.post(f"/api/v1/changes/{cid}/concerns", headers=admin_auth, json={
        "kind": "reject_proposal", "note": "Too costly"})
    mid = await _meeting(client, admin_auth, cid, depts)
    res = await _decide(client, admin_auth, cid, mid, "proceed")
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "2 open question(s) or cancel vote(s)" in detail
    assert "question by LT apqp5 (APQP): Tolerance?" in detail
    assert "cancel vote by" in detail and "Too costly" in detail
    # C33/C13 (SCOPING_V2): 'Not yet' answers nothing; a question the scope
    # does not hang on is made a check item
    assert "made a check item" in detail


# --- 3. the impact lock happens at proceed ----------------------------------

async def test_proceed_locks_the_impacted_set_on_the_decider(
        client, admin_auth, seed, session_factory):
    from app.models.change import ChangeChangelog, ChangeRequest
    cid = await _change_in_scoping(client, admin_auth, seed, "6")
    depts = await _dept_ids(session_factory)
    detail = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)).json()
    assert detail["impact_confirm_step"] is False
    assert detail["impact_confirmed_at"] is None
    mid = await _meeting(client, admin_auth, cid, depts)
    res = await _decide(client, admin_auth, cid, mid, "proceed")
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        assert c.status == "in_assessment"
        assert c.impact_confirmed_at is not None
        assert c.impact_confirmed_by == seed["admin_id"]
        log = (await s.execute(select(ChangeChangelog.action).where(
            ChangeChangelog.change_id == cid))).scalars().all()
    assert "impact_locked" in log


async def test_proceed_refuses_an_empty_impacted_set(
        client, admin_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "7", with_part=False)
    mid = await _meeting(client, admin_auth, cid, await _dept_ids(session_factory))
    res = await _decide(client, admin_auth, cid, mid, "proceed")
    assert res.status_code == 400
    assert "No impacted parts picked" in res.json()["detail"]


async def test_no_confirm_task_and_confirm_refused_while_switched_off(
        client, admin_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "8")
    uid, _, dev = await _user(client, session_factory, seed, "dev8", "Development")
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=dev)).json()
    assert not any(t["kind"] == "impact_confirm" and t["change_id"] == cid for t in tasks)
    acts = (await client.get(f"/api/v1/changes/{cid}/my-actions", headers=dev)).json()
    assert not any(a["kind"] == "impact_confirm" for a in acts["actions"])
    res = await client.post(f"/api/v1/changes/{cid}/impact/confirm", headers=dev)
    assert res.status_code == 400 and "proceed" in res.json()["detail"]


async def test_an_edit_after_the_lock_keeps_the_set_locked(
        client, admin_auth, seed, session_factory):
    from app.models.change import ChangeRequest
    cid = await _change_in_scoping(client, admin_auth, seed, "9")
    mid = await _meeting(client, admin_auth, cid, await _dept_ids(session_factory))
    assert (await _decide(client, admin_auth, cid, mid, "proceed")).status_code == 200
    part = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": "ART-LT9b",
        "name": "Part", "part_type": "internal_mfg"}, headers=admin_auth)
    # C16 (ASSESSMENT_V2): an edit after the lock says why
    r = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                          json={"part_id": part.json()["id"]}, headers=admin_auth)
    assert r.status_code == 400 and "say why it changes" in r.json()["detail"]
    r = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                          json={"part_id": part.json()["id"],
                                "reason": "Customer added the mirror part"},
                          headers=admin_auth)
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cid)).impact_confirmed_at is not None


# --- 4. scope definition ----------------------------------------------------

async def test_pm_defines_the_scope_in_scoping_read_only_afterwards(
        client, admin_auth, seed, session_factory):
    from app.models.change import ChangeChangelog
    cid = await _change_in_scoping(client, admin_auth, seed, "10")
    _, _, pm = await _user(client, session_factory, seed, "pm10", "Project Manager")
    _, _, tool = await _user(client, session_factory, seed, "tool10", "Tool Engineer")
    url = f"/api/v1/changes/{cid}/scope-definition"
    res = await client.put(url, json={"scope_definition": "Tool insert only"}, headers=tool)
    assert res.status_code == 403
    res = await client.put(url, json={"scope_definition": "  Tool insert only  "}, headers=pm)
    assert res.status_code == 200, res.text
    assert res.json()["scope_definition"] == "Tool insert only"
    # unchanged text writes nothing; a change is audited
    await client.put(url, json={"scope_definition": "Tool insert only"}, headers=pm)
    await client.put(url, json={"scope_definition": "Tool insert + gauge"}, headers=admin_auth)
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == cid,
            ChangeChangelog.action == "scope_defined"))).scalars().all()
    # (the first row is satisfy_capture_gate's: proceed needs a scope)
    assert [r.action_description for r in rows] == [
        "Scope defined", "Scope changed", "Scope changed"]
    got = (await client.get(f"/api/v1/changes/{cid}", headers=tool)).json()
    assert got["scope_definition"] == "Tool insert + gauge"

    mid = await _meeting(client, admin_auth, cid, await _dept_ids(session_factory))
    assert (await _decide(client, admin_auth, cid, mid, "proceed")).status_code == 200
    res = await client.put(url, json={"scope_definition": "late"}, headers=pm)
    assert res.status_code == 400 and "read only" in res.json()["detail"]
