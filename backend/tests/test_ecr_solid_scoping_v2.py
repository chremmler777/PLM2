"""ECR-solid C33 + C13 (spec §3, switch SCOPING_V2): scoping is triage.

A scoping flag is a QUESTION (blocks 'proceed', HARD #2) or a CHECK item
(default; the raised-for department checks it in its assessment, HARD #10 at
its own submit). Quick add asks for the department and what to check; a
question also for who answers and what the answer changes in the scope.
Several questions per department (one per asker + department + check-what);
'same as' / 'add to'; asker or PM switch the type. Answers are Confirmed
(evidence) or Assumed (value + unit, risk, confirmer + due -> a confirm
task). Proceed records the open check items as conditions. C13: 'Not yet'
(needs_info) closes nobody's question.
"""
import pytest
from sqlalchemy import select

from tests.conftest import (
    insert_legacy_concern, login, make_department_member, satisfy_capture_gate,
)


@pytest.fixture(autouse=True)
def _any_member_may_ask(monkeypatch):
    """These tests work the question mechanics with department askers; who
    may raise in scoping (PM / lead only since 2026-10-27) is tested in
    test_scoping_pm_questions.py."""
    from app.services import cm_switches
    monkeypatch.setattr(cm_switches, "SCOPING_QUESTIONS_PM_ONLY", False)
    # check items too (scoping takes questions only since 2026-10-27; the
    # refusal is tested in test_scoping_pm_questions.py)
    monkeypatch.setattr(cm_switches, "SCOPING_QUESTIONS_ONLY", False)

pytestmark = pytest.mark.asyncio


async def _user(client, session_factory, seed, key, dept=None):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=f"sv-{key}",
                 email=f"sv-{key}@test.io", full_name=f"SV {key}",
                 hashed_password=get_password_hash("sv-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        uid = u.id
    dept_id = (await make_department_member(session_factory, uid, dept)
               if dept else None)
    return uid, dept_id, await login(client, f"sv-{key}@test.io")


async def _scoping(client, auth, seed, suffix):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": f"sv {suffix}", "reason": "r",
        "change_type": "physical_part", "lead_id": seed["admin_id"]}, headers=auth)
    assert res.status_code == 200, res.text
    cid = res.json()["id"]
    part = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": f"ART-SV{suffix}",
        "name": "Part", "part_type": "internal_mfg"}, headers=auth)
    assert part.status_code in (200, 201), part.text
    pid = part.json()["id"]
    r = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                          json={"part_id": pid, "is_lead": True}, headers=auth)
    assert r.status_code == 200, r.text
    await satisfy_capture_gate(client, auth, cid)
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "scoping"}, headers=auth)
    assert res.status_code == 200, res.text
    return cid, pid


async def _meeting(client, auth, cid, rasic):
    res = await client.post(f"/api/v1/changes/{cid}/meetings", json={
        "channel": "meeting", "participants": [{"name": "Eva"}],
        "department_rasic": rasic, "cost_carrier": "customer"}, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _decide(client, auth, cid, mid, decision, reason=None):
    body = {"decision": decision, **({"reason": reason} if reason else {})}
    return await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                             json=body, headers=auth)


def _check(dept_id, note="Check the rib thickness", what="drawing", **extra):
    return {"kind": "needs_info", "note": note, "flag_type": "check",
            "department_id": dept_id, "check_what": what, **extra}


def _question(dept_id, note="Which resin lot?", what="material",
              answer_from="customer", effect="Decides whether Process assesses",
              **extra):
    return {"kind": "needs_info", "note": note, "flag_type": "question",
            "department_id": dept_id, "check_what": what,
            "answer_from": answer_from, "scope_effect": effect, **extra}


async def _raise(client, auth, cid, body):
    return await client.post(f"/api/v1/changes/{cid}/concerns", json=body,
                             headers=auth)


async def _file_mail(client, auth, cid):
    """A customer mail filed on the change; its attachment id."""
    up = await client.post(
        f"/api/v1/changes/{cid}/attachments",
        files={"file": ("mail.eml", b"customer says yes", "message/rfc822")},
        data={"kind": "customer_email"}, headers=auth)
    assert up.status_code in (200, 201), up.text
    return up.json()["id"]


async def _concerns(client, auth, cid):
    res = await client.get(f"/api/v1/changes/{cid}/concerns", headers=auth)
    assert res.status_code == 200, res.text
    return {c["id"]: c for c in res.json()}


# --- quick add: structure ----------------------------------------------------

async def test_check_item_needs_department_and_what_question_needs_more(
        client, admin_auth, seed, session_factory):
    cid, pid = await _scoping(client, admin_auth, seed, "1")
    _, proc, pe = await _user(client, session_factory, seed, "pe1", "Process Engineer")
    # negative: no department, no check-what
    res = await _raise(client, pe, cid, _check(None))
    assert res.status_code == 400 and "Raised for" in res.json()["detail"]
    res = await _raise(client, pe, cid, _check(proc, what="vibes"))
    assert res.status_code == 400 and "what to check" in res.json()["detail"]
    # negative: a question without who answers / what it changes
    res = await _raise(client, pe, cid, _question(proc, answer_from=None))
    assert res.status_code == 400 and "who can answer" in res.json()["detail"]
    res = await _raise(client, pe, cid, _question(proc, effect=""))
    assert res.status_code == 400
    assert "decide the scope without it" in res.json()["detail"]
    # negative: a part outside the impacted set
    res = await _raise(client, pe, cid, _check(proc, part_id=pid + 999))
    assert res.status_code == 400 and "impacted set" in res.json()["detail"]
    # the quick add itself
    res = await _raise(client, pe, cid, _check(proc, part_id=pid))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["flag_type"] == "check" and body["check_what"] == "drawing"
    assert body["part_id"] == pid
    row = (await _concerns(client, pe, cid))[body["id"]]
    assert row["owner_department_names"] == ["Process Engineer"]
    assert row["part_number"] == "ART-SV1"


async def test_several_questions_per_department_one_per_pick(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "2")
    _, proc, pe = await _user(client, session_factory, seed, "pe2", "Process Engineer")
    first = await _raise(client, pe, cid, _question(proc, what="material"))
    assert first.status_code == 200, first.text
    other = await _raise(client, pe, cid, _question(proc, note="Cycle?", what="cycle_time"))
    assert other.status_code == 200, other.text
    # negative: the same pick again names the open one and offers add to / same as
    twin = await _raise(client, pe, cid, _question(proc, note="Resin again"))
    assert twin.status_code == 400
    assert f"#{first.json()['id']}" in twin.json()["detail"]
    assert "add to" in twin.json()["detail"]
    # check items are a list: no limit
    for n in range(2):
        assert (await _raise(client, pe, cid, _check(proc))).status_code == 200


# --- proceed: questions hold it, check items go along as conditions ---------

async def test_check_items_do_not_block_proceed_and_become_conditions(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "3")
    _, proc, pe = await _user(client, session_factory, seed, "pe3", "Process Engineer")
    mid = await _meeting(client, admin_auth, cid, {str(proc): "R"})
    q = (await _raise(client, pe, cid, _question(proc))).json()
    chk = (await _raise(client, pe, cid, _check(proc))).json()
    # negative: the open question holds proceed (HARD #2), named in the refusal
    res = await _decide(client, admin_auth, cid, mid, "proceed")
    assert res.status_code == 400
    assert "Which resin lot?" in res.json()["detail"]
    assert "Check the rib thickness" not in res.json()["detail"]
    # the asker closes the question; the check item stays open and goes along
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{q['id']}/withdraw",
                            json={"resolution_note": "Lot named by mail"}, headers=pe)
    assert res.status_code == 200, res.text
    res = await _decide(client, admin_auth, cid, mid, "proceed")
    assert res.status_code == 200, res.text
    conds = res.json()["go_conditions"]
    assert [c["id"] for c in conds] == [chk["id"]]
    assert conds[0]["department_id"] == proc
    rows = await _concerns(client, pe, cid)
    assert rows[chk["id"]]["is_open"] is True
    # owner + due: the department's assessment due (the row's own due here:
    # no engine template in the test database)
    from datetime import datetime
    from app.models.change import ChangeAssessment
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid,
            ChangeAssessment.department_id == proc))).scalar_one()
        row.due_date = datetime(2026, 11, 20, 12, 0)
        await s.commit()
    rows = await _concerns(client, pe, cid)
    assert rows[chk["id"]]["owner_due"].startswith("2026-11-20")
    # HARD #10: the department cannot submit over its own open check item
    res = await client.post(f"/api/v1/changes/{cid}/assessments",
                            json={"department_id": proc, "verdict": "feasible"},
                            headers=pe)
    assert res.status_code == 400 and "Check the rib thickness" in res.json()["detail"]
    # the raiser sits in the owning department: it closes the item with
    # what it found, like any colleague (R4: no free note in the assessment)
    res = await client.post(
        f"/api/v1/changes/{cid}/concerns/{chk['id']}/withdraw",
        json={"resolution_note": "Rib 2.4 mm per drawing 4711 rev C"}, headers=pe)
    assert res.status_code == 400 and "what you found" in res.json()["detail"]
    res = await client.post(
        f"/api/v1/changes/{cid}/concerns/{chk['id']}/check",
        json={"outcome": "answered", "value": "2.4", "unit": "mm",
              "ref": "drawing 4711 rev C"}, headers=pe)
    assert res.status_code == 200, res.text


async def test_legacy_flag_without_type_still_blocks_proceed(
        client, admin_auth, seed, session_factory):
    """In-flight changes: an open flag from before C33 (flag_type NULL) is a
    question and holds proceed as it did."""
    cid, _ = await _scoping(client, admin_auth, seed, "4")
    _, proc, _pe = await _user(client, session_factory, seed, "pe4", "Process Engineer")
    mid = await _meeting(client, admin_auth, cid, {str(proc): "R"})
    await insert_legacy_concern(session_factory, cid, kind="needs_info",
                                note="Old open question", raised_by=seed["admin_id"])
    res = await _decide(client, admin_auth, cid, mid, "proceed")
    assert res.status_code == 400 and "Old open question" in res.json()["detail"]


async def test_switch_off_check_is_ignored_and_blocks(
        client, admin_auth, seed, session_factory, monkeypatch):
    from app.services import cm_switches
    monkeypatch.setattr(cm_switches, "SCOPING_V2", False)
    cid, _ = await _scoping(client, admin_auth, seed, "5")
    _, proc, pe = await _user(client, session_factory, seed, "pe5", "Process Engineer")
    mid = await _meeting(client, admin_auth, cid, {str(proc): "R"})
    res = await _raise(client, pe, cid, _check(proc))
    assert res.status_code == 200 and res.json()["flag_type"] is None
    res = await _decide(client, admin_auth, cid, mid, "proceed")
    assert res.status_code == 400


# --- switch type, same as / add to -------------------------------------------

async def test_asker_or_pm_switch_the_type_nobody_else(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "6")
    _, proc, pe = await _user(client, session_factory, seed, "pe6", "Process Engineer")
    _, _, tool = await _user(client, session_factory, seed, "te6", "Tool Engineer")
    _, _, pm = await _user(client, session_factory, seed, "pm6", "Project Manager")
    chk = (await _raise(client, pe, cid, _check(proc))).json()
    url = f"/api/v1/changes/{cid}/concerns/{chk['id']}/type"
    # negative: a bystander may not; a question without its structure is refused
    res = await client.post(url, json={"flag_type": "question",
                                       "answer_from": "customer",
                                       "scope_effect": "Adds the tool"}, headers=tool)
    assert res.status_code == 403
    res = await client.post(url, json={"flag_type": "question"}, headers=pe)
    assert res.status_code == 400 and "who can answer" in res.json()["detail"]
    res = await client.post(url, json={"flag_type": "question",
                                       "answer_from": "supplier",
                                       "scope_effect": "Decides whether Toolshop assesses"},
                            headers=pe)
    assert res.status_code == 200 and res.json()["flag_type"] == "question"
    # Project Management sorts it back
    res = await client.post(url, json={"flag_type": "check"}, headers=pm)
    assert res.status_code == 200 and res.json()["flag_type"] == "check"
    row = (await _concerns(client, pm, cid))[chk["id"]]
    assert row["can_switch"] is True
    assert (await _concerns(client, tool, cid))[chk["id"]]["can_switch"] is False


async def test_same_as_makes_my_department_co_owner(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "7")
    _, proc, pe = await _user(client, session_factory, seed, "pe7", "Process Engineer")
    _, tool_id, tool = await _user(client, session_factory, seed, "te7", "Tool Engineer")
    chk = (await _raise(client, pe, cid, _check(proc))).json()
    url = f"/api/v1/changes/{cid}/concerns/{chk['id']}/join"
    # negative: 'same as' only for your own department; nothing to add is refused
    res = await client.post(url, json={"department_id": proc}, headers=tool)
    assert res.status_code == 403
    res = await client.post(url, json={}, headers=tool)
    assert res.status_code == 400
    res = await client.post(url, json={"department_id": tool_id,
                                       "note": "and the slider"}, headers=tool)
    assert res.status_code == 200, res.text
    assert res.json()["co_department_ids"] == [tool_id]
    assert "and the slider" in res.json()["note"]
    row = (await _concerns(client, tool, cid))[chk["id"]]
    assert row["owner_department_names"] == ["Process Engineer", "Tool Engineer"]


# --- C13: 'Not yet' closes nobody's question ----------------------------------

async def test_not_yet_keeps_every_question_open(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "8")
    _, proc, pe = await _user(client, session_factory, seed, "pe8", "Process Engineer")
    _, tool_id, tool = await _user(client, session_factory, seed, "te8", "Tool Engineer")
    _, _, pm = await _user(client, session_factory, seed, "pm8", "Project Manager")
    mid = await _meeting(client, pm, cid, {str(proc): "R"})
    q1 = (await _raise(client, pe, cid, _question(proc))).json()
    q2 = (await _raise(client, tool, cid, _question(tool_id, note="Slider travel?",
                                                    what="tool"))).json()
    # with questions open, 'Not yet' needs no reason: they are the reason
    res = await _decide(client, pm, cid, mid, "needs_info")
    assert res.status_code == 200, res.text
    # each side with the due weekday of its question (spec §3 "Sales Thu")
    import re
    assert re.fullmatch(
        r"Not yet: waiting for 2 answers \(Process Engineer (Mon|Tue|Wed|Thu|Fri), "
        r"Tool Engineer (Mon|Tue|Wed|Thu|Fri)\)", res.json()["decision_reason"])
    rows = await _concerns(client, pm, cid)
    assert rows[q1["id"]]["is_open"] and rows[q2["id"]]["is_open"]
    assert rows[q1["id"]]["resolved_by_meeting_id"] is None
    # no extra question was raised for the decider
    assert len([r for r in rows.values() if r["is_open"]]) == 2
    # the lead's (PM's) row says what it waits on
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=pm)).json()
    wrap = next(t for t in tasks if t["kind"] == "scoping_wrapup" and t["change_id"] == cid)
    assert wrap["open_questions"] == 2
    assert [w.rsplit(" ", 1)[0] for w in wrap["waiting_on"]] == [
        "Process Engineer", "Tool Engineer"]


async def test_reject_still_closes_every_flag(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "9")
    _, proc, pe = await _user(client, session_factory, seed, "pe9", "Process Engineer")
    mid = await _meeting(client, admin_auth, cid, {str(proc): "R"})
    q = (await _raise(client, pe, cid, _question(proc))).json()
    c = (await _raise(client, pe, cid, _check(proc))).json()
    res = await _decide(client, admin_auth, cid, mid, "reject", "Not economical")
    assert res.status_code == 200, res.text
    rows = await _concerns(client, admin_auth, cid)
    assert not rows[q["id"]]["is_open"] and not rows[c["id"]]["is_open"]


# --- the answer form: Confirmed / Assumed -------------------------------------

async def test_customer_question_confirmed_only_by_filed_customer_document(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "10")
    _, proc, pe = await _user(client, session_factory, seed, "pe10", "Process Engineer")
    _, _, sales = await _user(client, session_factory, seed, "sa10", "Sales")
    q = (await _raise(client, pe, cid, _question(proc))).json()
    url = f"/api/v1/changes/{cid}/concerns/{q['id']}/answer"
    # negative: a reference is not the customer's word
    res = await client.post(url, json={"answer_kind": "confirmed",
                                       "ref": "Call with Mr. X"}, headers=sales)
    assert res.status_code == 400 and "customer's" in res.json()["detail"]
    # negative: a mail id that is not a filed customer mail
    res = await client.post(url, json={"answer_kind": "confirmed", "mail_id": 999999},
                            headers=sales)
    assert res.status_code == 400
    mail = await _file_mail(client, sales, cid)
    res = await client.post(url, json={"answer_kind": "confirmed", "mail_id": mail,
                                       "note": "Lot 7"}, headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["answer_kind"] == "confirmed"


async def test_assumed_answer_owes_value_risk_and_a_confirm_task(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "11")
    _, proc, pe = await _user(client, session_factory, seed, "pe11", "Process Engineer")
    sales_uid, _, sales = await _user(client, session_factory, seed, "sa11", "Sales")
    _, _, tool = await _user(client, session_factory, seed, "te11", "Tool Engineer")
    q = (await _raise(client, pe, cid, _question(proc, what="volume",
                                                 note="Annual volume?"))).json()
    url = f"/api/v1/changes/{cid}/concerns/{q['id']}/answer"
    # negatives: no number, no unit, no risk
    for bad in ({"assumed_value": "lots", "assumed_unit": "pcs",
                 "assumed_risk": "Tool undersized"},
                {"assumed_value": "120000", "assumed_risk": "Tool undersized"},
                {"assumed_value": "120000", "assumed_unit": "pcs/yr"}):
        res = await client.post(url, json={"answer_kind": "assumed", **bad},
                                headers=sales)
        assert res.status_code == 400, bad
    res = await client.post(url, json={
        "answer_kind": "assumed", "assumed_value": "120000",
        "assumed_unit": "pcs/yr", "assumed_risk": "Second cavity needed above 150k",
        "confirm_by_id": sales_uid}, headers=sales)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["answer_kind"] == "assumed" and body["confirm_due"] is not None
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
    row = next(t for t in tasks if t["kind"] == "confirm_assumption"
               and t["change_id"] == cid)
    assert row["concern_id"] == q["id"] and row["due_date"]
    assert "120000 pcs/yr" in row["reason"]
    # negative: a bystander may not confirm it; the named confirmer may
    curl = f"/api/v1/changes/{cid}/concerns/{q['id']}/confirm"
    assert (await client.post(curl, json={"ref": "Mail 2026-10-12"},
                              headers=tool)).status_code == 403
    mail = await _file_mail(client, sales, cid)
    res = await client.post(curl, json={"mail_id": mail}, headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["answer_kind"] == "confirmed" and res.json()["confirmed_at"]
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
    assert not [t for t in tasks if t["kind"] == "confirm_assumption"
                and t["change_id"] == cid]


async def test_our_team_question_confirmed_by_reference(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "12")
    _, proc, pe = await _user(client, session_factory, seed, "pe12", "Process Engineer")
    q = (await _raise(client, pe, cid, _question(proc, answer_from="our_team"))).json()
    url = f"/api/v1/changes/{cid}/concerns/{q['id']}/answer"
    res = await client.post(url, json={"answer_kind": "confirmed", "ref": "ok"},
                            headers=pe)
    assert res.status_code == 400
    res = await client.post(url, json={"answer_kind": "confirmed",
                                       "ref": "Process sheet PS-3274 rev 4"}, headers=pe)
    assert res.status_code == 200, res.text
    assert res.json()["answer_ref"] == "Process sheet PS-3274 rev 4"


# --- L4 review: the confirm item, evidence, join rights, twins, mail copy -----

async def test_named_confirmer_confirms_after_the_question_closed_and_proceed(
        client, admin_auth, seed, session_factory):
    """The confirm item is no dead end: the named confirmer (a lead outside
    the asking department, Sales and PM) sees can_confirm and confirms after
    the question was closed and the change proceeded. A bad confirmer
    (inactive, other org, viewer) is refused."""
    from app.models.entities import User
    cid, _ = await _scoping(client, admin_auth, seed, "13")
    _, proc, pe = await _user(client, session_factory, seed, "pe13", "Process Engineer")
    lead_uid, _, lead = await _user(client, session_factory, seed, "dev13", "Development")
    _, _, pm = await _user(client, session_factory, seed, "pm13", "Project Manager")
    _, _, tool = await _user(client, session_factory, seed, "te13", "Tool Engineer")
    q = (await _raise(client, pe, cid, _question(proc, answer_from="our_team",
                                                 what="volume", note="Volume?"))).json()
    url = f"/api/v1/changes/{cid}/concerns/{q['id']}/answer"
    body = {"answer_kind": "assumed", "assumed_value": "90000", "assumed_unit": "pcs/yr",
            "assumed_risk": "Second cavity needed above 150k"}
    # negatives: an inactive user, a user without department (reads only)
    async with session_factory() as s:
        idle = User(organization_id=seed["org_id"], username="sv-idle13",
                    email="sv-idle13@test.io", full_name="Idle", hashed_password="x",
                    role="engineer", is_active=True)
        s.add(idle)
        await s.commit()
        idle_id = idle.id
    for bad in (seed["inactive_id"], idle_id):
        res = await client.post(url, json={**body, "confirm_by_id": bad}, headers=pe)
        assert res.status_code == 400 and "Who confirms" in res.json()["detail"], bad
    res = await client.post(url, json={**body, "confirm_by_id": lead_uid}, headers=pe)
    assert res.status_code == 200, res.text
    # the named confirmer is told once
    from app.models.notification import Notification
    async with session_factory() as s:
        notes = (await s.execute(select(Notification).where(
            Notification.user_id == lead_uid,
            Notification.kind == "confirm_assumption"))).scalars().all()
    assert len(notes) == 1
    # the asker closes the answered question; proceed
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{q['id']}/withdraw",
                            json={"resolution_note": "Assumed 90k, confirm later"},
                            headers=pe)
    assert res.status_code == 200, res.text
    mid = await _meeting(client, pm, cid, {str(proc): "R"})
    assert (await _decide(client, pm, cid, mid, "proceed")).status_code == 200
    rows = await _concerns(client, lead, cid)
    assert rows[q["id"]]["is_open"] is False and rows[q["id"]]["can_confirm"] is True
    assert (await _concerns(client, tool, cid))[q["id"]]["can_confirm"] is False
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{q['id']}/confirm",
                            json={"ref": "Sales forecast FC-2026-10"}, headers=lead)
    assert res.status_code == 200, res.text
    assert (await _concerns(client, lead, cid))[q["id"]]["can_confirm"] is False


async def test_customer_question_internal_note_is_not_confirmation(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "14")
    _, proc, pe = await _user(client, session_factory, seed, "pe14", "Process Engineer")
    _, _, sales = await _user(client, session_factory, seed, "sa14", "Sales")
    q = (await _raise(client, pe, cid, _question(proc))).json()
    up = await client.post(f"/api/v1/changes/{cid}/attachments",
                           files={"file": ("note.txt", b"we think lot 7", "text/plain")},
                           data={"kind": "info_response", "concern_id": str(q["id"])},
                           headers=pe)
    assert up.status_code in (200, 201), up.text
    url = f"/api/v1/changes/{cid}/concerns/{q['id']}/answer"
    res = await client.post(url, json={"answer_kind": "confirmed"}, headers=sales)
    assert res.status_code == 400 and "Assumed" in res.json()["detail"]
    up = await client.post(f"/api/v1/changes/{cid}/attachments",
                           files={"file": ("spec.pdf", b"%PDF lot 7", "application/pdf")},
                           data={"kind": "customer_file", "concern_id": str(q["id"])},
                           headers=sales)
    assert up.status_code in (200, 201), up.text
    res = await client.post(url, json={"answer_kind": "confirmed"}, headers=sales)
    assert res.status_code == 200, res.text


async def test_same_as_has_no_admin_shortcut_and_add_to_has_rights(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "15")
    _, proc, pe = await _user(client, session_factory, seed, "pe15", "Process Engineer")
    _, tool_id, tool = await _user(client, session_factory, seed, "te15", "Tool Engineer")
    _, _, sales = await _user(client, session_factory, seed, "sa15", "Sales")
    chk = (await _raise(client, pe, cid, _check(proc))).json()
    url = f"/api/v1/changes/{cid}/concerns/{chk['id']}/join"
    # a plain admin binds no other department's submit
    res = await client.post(url, json={"department_id": tool_id}, headers=admin_auth)
    assert res.status_code == 403
    # a bystander cannot rewrite someone else's item
    res = await client.post(url, json={"note": "and the gate"}, headers=tool)
    assert res.status_code == 403
    q = (await _raise(client, pe, cid, _question(proc, answer_from="our_team"))).json()
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{q['id']}/answer",
                            json={"answer_kind": "confirmed", "ref": "Process sheet PS-1 rev 2"},
                            headers=pe)
    assert res.status_code == 200, res.text
    # an answered question is not rewritten
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{q['id']}/join",
                            json={"note": "and also the colour"}, headers=sales)
    assert res.status_code == 400 and "already answered" in res.json()["detail"]


async def test_make_it_a_question_keeps_one_per_pick(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "16")
    _, proc, pe = await _user(client, session_factory, seed, "pe16", "Process Engineer")
    q = (await _raise(client, pe, cid, _question(proc))).json()
    chk = (await _raise(client, pe, cid, _check(proc, what="material"))).json()
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{chk['id']}/type", json={
        "flag_type": "question", "answer_from": "customer",
        "scope_effect": "Decides whether Process assesses"}, headers=pe)
    assert res.status_code == 400 and f"#{q['id']}" in res.json()["detail"]


async def test_customer_question_carries_the_mail_copy(
        client, admin_auth, seed, session_factory):
    cid, pid = await _scoping(client, admin_auth, seed, "17")
    _, proc, pe = await _user(client, session_factory, seed, "pe17", "Process Engineer")
    _, _, sales = await _user(client, session_factory, seed, "sa17", "Sales")
    q = (await _raise(client, pe, cid, _question(proc, part_id=pid))).json()
    mine = (await _raise(client, pe, cid, _question(
        proc, what="tool", answer_from="our_team", note="Slider?"))).json()
    rows = await _concerns(client, sales, cid)
    copy = rows[q["id"]]["customer_copy"]
    assert "Which resin lot?" in copy and "ART-SV17" in copy
    assert "Decides whether Process assesses" in copy
    assert rows[mine["id"]]["customer_copy"] is None
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
    row = next(t for t in tasks if t["kind"] == "obtain_info" and t["change_id"] == cid)
    assert row["customer_copy"] is None or "Hello" in row["customer_copy"]


# --- L4 review 2: add-to rights served, untyped raise, confirm rules ---------

async def test_can_add_to_matches_the_join_rights_and_untyped_raise_is_refused(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "18")
    _, proc, pe = await _user(client, session_factory, seed, "pe18", "Process Engineer")
    _, _, tool = await _user(client, session_factory, seed, "te18", "Tool Engineer")
    _, _, sales = await _user(client, session_factory, seed, "sa18", "Sales")
    chk = (await _raise(client, pe, cid, _check(proc))).json()
    assert (await _concerns(client, pe, cid))[chk["id"]]["can_add_to"] is True
    assert (await _concerns(client, tool, cid))[chk["id"]]["can_add_to"] is False
    q = (await _raise(client, pe, cid, _question(proc, answer_from="our_team"))).json()
    assert (await _concerns(client, sales, cid))[q["id"]]["can_add_to"] is True
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{q['id']}/answer",
                            json={"answer_kind": "confirmed", "ref": "Process sheet PS-1 rev 2"},
                            headers=pe)
    assert res.status_code == 200, res.text
    # answered: nobody adds to it any more
    assert (await _concerns(client, sales, cid))[q["id"]]["can_add_to"] is False
    # a new scoping raise names its type (R2/R3)
    res = await _raise(client, pe, cid, {"kind": "needs_info", "note": "Gate position?",
                                         "department_id": proc})
    assert res.status_code == 400 and "check item" in res.json()["detail"]


async def test_confirmer_by_department_not_stored_role_and_not_on_ended_change(
        client, admin_auth, seed, session_factory):
    """A colleague just given a department (stored role still 'viewer' until
    the next login) may be named to confirm; an ended change's assumption
    is not rewritten."""
    from sqlalchemy import update
    from app.models.change import ChangeRequest
    from app.models.entities import User
    cid, _ = await _scoping(client, admin_auth, seed, "19")
    _, proc, pe = await _user(client, session_factory, seed, "pe19", "Process Engineer")
    new_uid, _, _new = await _user(client, session_factory, seed, "dev19", "Development")
    async with session_factory() as s:
        await s.execute(update(User).where(User.id == new_uid).values(role="viewer"))
        await s.commit()
    q = (await _raise(client, pe, cid, _question(proc, answer_from="our_team",
                                                 what="volume", note="Volume?"))).json()
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{q['id']}/answer", json={
        "answer_kind": "assumed", "assumed_value": "90000", "assumed_unit": "pcs/yr",
        "assumed_risk": "Second cavity needed above 150k", "confirm_by_id": new_uid},
        headers=pe)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == cid)
                        .values(status="cancelled"))
        await s.commit()
    assert (await _concerns(client, pe, cid))[q["id"]]["can_confirm"] is False
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{q['id']}/confirm",
                            json={"ref": "Sales forecast FC-2026-10"}, headers=pe)
    assert res.status_code == 400 and "cancelled" in res.json()["detail"]


async def test_confirm_item_for_the_sales_owner_shows_to_all_of_sales(
        client, admin_auth, seed, session_factory):
    """[R3] Sales tasks show to all of Sales with the owner's name: another
    Sales member sees the Sales owner's confirm item, and may confirm it."""
    cid, _ = await _scoping(client, admin_auth, seed, "20")
    _, proc, pe = await _user(client, session_factory, seed, "pe20", "Process Engineer")
    owner_uid, _, _owner = await _user(client, session_factory, seed, "sa20", "Sales")
    _, _, other = await _user(client, session_factory, seed, "sb20", "Sales")
    _, _, tool = await _user(client, session_factory, seed, "te20", "Tool Engineer")
    res = await client.patch(f"/api/v1/changes/{cid}", json={
        "customer_relevant": True, "sales_owner_id": owner_uid}, headers=admin_auth)
    assert res.status_code == 200, res.text
    q = (await _raise(client, pe, cid, _question(proc, answer_from="our_team",
                                                 what="volume", note="Volume?"))).json()
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{q['id']}/answer", json={
        "answer_kind": "assumed", "assumed_value": "90000", "assumed_unit": "pcs/yr",
        "assumed_risk": "Second cavity needed above 150k", "confirm_by_id": owner_uid},
        headers=pe)
    assert res.status_code == 200, res.text

    async def rows(auth):
        tasks = (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()
        return [t for t in tasks if t["kind"] == "confirm_assumption" and t["change_id"] == cid]
    got = await rows(other)
    assert len(got) == 1 and got[0]["main_name"] == "SV sa20"
    assert await rows(tool) == []
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{q['id']}/confirm",
                            json={"ref": "Sales forecast FC-2026-10"}, headers=other)
    assert res.status_code == 200, res.text


async def test_check_item_for_an_unrouted_department_is_routed_c_at_proceed(
        client, admin_auth, seed, session_factory):
    """§3 "Not routed" is SOFT (A2-03, frozen spec: HARD is exactly #1-#10):
    a check item raised for a department the meeting does not route (or
    routes as I only) does not hold proceed. Proceed routes that department
    as C (the spec's preselected pick), logged, so the item leaves with an
    owner, a due and a task (R18). The PM's row holds nothing for it; the
    checklist lists it as the lead's to-do (pick R or reassign instead)."""
    cid, _ = await _scoping(client, admin_auth, seed, "21")
    _, proc, pe = await _user(client, session_factory, seed, "pe21", "Process Engineer")
    _, qual, _quality = await _user(client, session_factory, seed, "q21", "Quality")
    _, _, pm = await _user(client, session_factory, seed, "pm21", "Project Manager")
    mid = await _meeting(client, admin_auth, cid, {str(proc): "R", str(qual): "I"})
    chk = (await _raise(client, pe, cid, _check(qual, note="Check the gauge"))).json()
    rows = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=pm)).json()
            if t["kind"] == "scoping_wrapup" and t["change_id"] == cid]
    assert rows[0]["holds"] == []
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)).json()
    item = next(i for i in ch["next_step"]["items"] if i["key"] == "unrouted_checks")
    assert item["kind"] == "todo"
    res = await _decide(client, admin_auth, cid, mid, "proceed")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["department_rasic"][str(qual)] == "C"
    assert [c["id"] for c in body["go_conditions"]] == [chk["id"]]
    from app.models.change import ChangeAssessment, ChangeChangelog
    async with session_factory() as s:
        depts = {a.department_id for a in (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid))).scalars()}
        log = (await s.execute(select(ChangeChangelog.action_description).where(
            ChangeChangelog.change_id == cid,
            ChangeChangelog.action == "unrouted_checks_routed"))).scalars().all()
    assert qual in depts
    assert log and "Quality" in log[0] and "as C" in log[0]


async def test_unrouted_check_item_no_hold_with_switch_off(
        client, admin_auth, seed, session_factory, monkeypatch):
    from app.models.change import ChangeConcern
    from app.services import cm_switches
    from app.services.meeting_service import MeetingService
    monkeypatch.setattr(cm_switches, "SCOPING_V2", False)
    c = ChangeConcern(kind="needs_info", flag_type="check", department_id=6, note="x",
                      raised_by=1)

    class _M:
        decision = None
        department_rasic = {"4": "R"}
        selected_department_ids = [4]

    class _C:
        concerns = [c]
        meetings = [_M()]
    assert MeetingService.unrouted_check_owners(_C()) == {}


async def test_f8_customer_question_is_the_sales_contacts_task(
        client, admin_auth, seed, session_factory):
    """F8 (test 2026-10-26): raised at scoping, a customer question tells the
    Sales contact and is their task (mine), with the mail copy."""
    from app.models.change import ChangeRequest
    from app.models.notification import Notification
    from sqlalchemy import select
    cid, pid = await _scoping(client, admin_auth, seed, "f8")
    _, proc, pe = await _user(client, session_factory, seed, "pef8", "Process Engineer")
    karl, _sales, karl_auth = await _user(client, session_factory, seed, "karl8", "Sales")
    async with session_factory() as s:
        (await s.get(ChangeRequest, cid)).sales_owner_id = karl
        await s.commit()
    res = await _raise(client, pe, cid, _question(proc))
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        told = (await s.execute(select(Notification.kind).where(
            Notification.user_id == karl))).scalars().all()
    assert told.count("task_new") == 1
    rows = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=karl_auth)).json()
            if t["change_id"] == cid and t["kind"] == "obtain_info"]
    assert len(rows) == 1 and rows[0]["mine"] is True and rows[0]["customer_copy"]
    assert rows[0].get("role", "main") == "main"
