"""ECR-solid spec §4 (switch ASSESSMENT_V2): check items first, C8 questions
in the assessment, HARD #10 at the department's own submit.

- A department closes its check item inline: Answered (number + unit, a
  reference or a file), Not relevant (checklist row / drawing ref / outside
  our scope + who / same as #n) or Assumed (value + unit, risk, confirm item).
  A free note no longer closes it; the raiser or the lead may reopen it.
- "Blocked? Ask a question": a department asks the customer, a supplier or
  our team from its own assessment. It holds only that department's submit;
  the Sales owner (customer / supplier) or the lead (our team) is told once;
  the asker hears the answer.
"""
import json

import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeConcern, ChangeRequest
from app.models.notification import Notification
from app.services import cm_switches
from tests.checklist_helpers import answered
from tests.conftest import login, make_department_member

pytestmark = pytest.mark.asyncio



async def _user(client, session_factory, seed, key, dept=None):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=f"ac-{key}",
                 email=f"ac-{key}@test.io", full_name=f"AC {key}",
                 hashed_password=get_password_hash("ac-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        uid = u.id
    dept_id = (await make_department_member(session_factory, uid, dept)
               if dept else None)
    return uid, dept_id, await login(client, f"ac-{key}@test.io")


@pytest.fixture
async def assess(client, session_factory, seed):
    """A change in assessment: Process Engineer and Tool Engineer routed,
    neither has submitted. Process owns an open check item raised in
    scoping by a Development colleague. A Sales owner is set."""
    raiser, dev, raiser_auth = await _user(client, session_factory, seed, "dev", "Development")
    pe_id, proc, pe = await _user(client, session_factory, seed, "pe", "Process Engineer")
    te_id, tool, te = await _user(client, session_factory, seed, "te", "Tool Engineer")
    sales_id, sales, sa = await _user(client, session_factory, seed, "sales", "Sales")
    lead_id, _, lead = await _user(client, session_factory, seed, "lead", "Project Manager")
    async with session_factory() as s:
        change = ChangeRequest(
            change_number="C-AC-1", title="assessment checks", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=raiser, lead_id=lead_id, sales_owner_id=sales_id,
            customer_relevant=True, status="in_assessment")
        s.add(change)
        await s.flush()
        for d in (proc, tool):
            s.add(ChangeAssessment(change_id=change.id, department_id=d,
                                   stage_order=1, rasic_letter="R"))
        check = ChangeConcern(change_id=change.id, kind="needs_info",
                              note="Check the gate position", raised_by=raiser,
                              department_id=proc, flag_type="check",
                              check_what="drawing")
        s.add(check)
        await s.commit()
        return {"cid": change.id, "check": check.id, "proc": proc, "tool": tool,
                "dev": dev, "pe": pe, "te": te, "sa": sa, "lead": lead,
                "raiser": raiser_auth, "sales_id": sales_id, "lead_id": lead_id,
                "pe_id": pe_id, "raiser_id": raiser}


def _url(a, tail=""):
    return f"/api/v1/changes/{a['cid']}{tail}"


async def _submit(client, auth, a, dept, ok=None):
    name = "Process Engineer" if dept == a["proc"] else "Tool Engineer"
    res = await client.post(_url(a, "/assessments"), json={
        "department_id": dept, "verdict": "feasible",
        "details": {"impacts": answered(name)}},
        headers=auth)
    if ok is not None:
        assert (res.status_code == 200) == ok, res.text
    return res


async def _close(client, auth, a, **body):
    return await client.post(_url(a, f"/concerns/{a['check']}/check"),
                             json=body, headers=auth)


# --- check items ------------------------------------------------------------

async def test_check_item_holds_own_submit_until_closed_with_evidence(client, assess):
    a = assess
    res = await _submit(client, a["pe"], a, a["proc"])
    assert res.status_code == 400 and "open concerns" in res.json()["detail"]
    # negative: evidence that says nothing, a value without unit, no pick
    for body, words in (({"outcome": "answered", "ref": "ok"}, "says nothing"),
                        ({"outcome": "answered", "value": "2.4"}, "unit"),
                        ({"outcome": "answered"}, "evidence"),
                        ({"outcome": "maybe"}, "Say what you found")):
        res = await _close(client, a["pe"], a, **body)
        assert res.status_code == 400 and words in res.json()["detail"], res.text
    res = await _close(client, a["pe"], a, outcome="answered", value="2.4", unit="mm",
                       ref="DRW-4471 rev C")
    assert res.status_code == 200, res.text
    row = res.json()
    assert row["check_outcome"] == "answered" and row["is_open"] is False
    assert row["resolution_note"] == "2.4 mm (DRW-4471 rev C)"
    await _submit(client, a["pe"], a, a["proc"], ok=True)


async def test_only_the_owning_department_closes_and_free_notes_are_refused(
        client, assess):
    a = assess
    # negative: Tool Engineer is not the owner
    res = await _close(client, a["te"], a, outcome="answered", ref="DRW-4471 rev C")
    assert res.status_code == 403, res.text
    # negative: Process may not close it with a bare note any more
    res = await client.post(_url(a, f"/concerns/{a['check']}/withdraw"),
                            json={"resolution_note": "checked"}, headers=a["pe"])
    assert res.status_code == 400 and "what you found" in res.json()["detail"]
    # negative: Sales does not "answer" a check item
    res = await client.post(_url(a, f"/concerns/{a['check']}/answer"),
                            json={"note": "fine"}, headers=a["sa"])
    assert res.status_code == 400 and "closed by the department" in res.json()["detail"]


async def test_not_relevant_needs_its_basis(client, assess):
    a = assess
    for body, words in (
            ({"outcome": "not_relevant"}, "say why"),
            ({"outcome": "not_relevant", "basis": "checklist_row",
              "checklist_key": "nope"}, "checklist row"),
            ({"outcome": "not_relevant", "basis": "outside_scope", "who": ""},
             "who owns it"),
            ({"outcome": "not_relevant", "basis": "same_as", "same_as_id": a["check"]},
             "another")):
        res = await _close(client, a["pe"], a, **body)
        assert res.status_code == 400 and words in res.json()["detail"], res.text
    res = await _close(client, a["pe"], a, outcome="not_relevant",
                       basis="outside_scope", who="Tool Engineer")
    assert res.status_code == 200, res.text
    assert res.json()["resolution_note"] == "outside our scope, owned by Tool Engineer"


async def test_assumed_close_leaves_a_confirm_item_for_the_sales_owner(
        client, assess, session_factory):
    a = assess
    res = await _close(client, a["pe"], a, outcome="assumed", value="2.4", unit="mm")
    assert res.status_code == 400 and "wrong" in res.json()["detail"]
    res = await _close(client, a["pe"], a, outcome="assumed", value="2.4", unit="mm",
                       assumed_risk="gate moves, re-cut the insert")
    assert res.status_code == 200, res.text
    assert res.json()["confirm_by_id"] == a["sales_id"]
    async with session_factory() as s:
        n = (await s.execute(select(Notification).where(
            Notification.user_id == a["sales_id"],
            Notification.kind == "confirm_assumption"))).scalars().all()
        assert len(n) == 1


async def test_raiser_or_lead_reopens_others_may_not(client, assess):
    a = assess
    res = await _close(client, a["pe"], a, outcome="answered", ref="DRW-4471 rev C")
    assert res.status_code == 200
    url = _url(a, f"/concerns/{a['check']}/reopen")
    # negative: Tool Engineer and the closer's colleague side are not raiser / lead
    assert (await client.post(url, json={"reason": "wrong drawing"},
                              headers=a["te"])).status_code == 403
    # negative: no reason
    res = await client.post(url, json={"reason": "no"}, headers=a["raiser"])
    assert res.status_code == 400
    res = await client.post(url, json={"reason": "that is rev B, not C"},
                            headers=a["raiser"])
    assert res.status_code == 200, res.text
    assert res.json()["is_open"] is True and res.json()["check_outcome"] is None
    # it holds the submit again
    assert (await _submit(client, a["pe"], a, a["proc"])).status_code == 400
    # the list tells who may close and reopen
    rows = {c["id"]: c for c in (await client.get(
        _url(a, "/concerns"), headers=a["pe"])).json()}
    assert rows[a["check"]]["can_check"] is True
    rows = {c["id"]: c for c in (await client.get(
        _url(a, "/concerns"), headers=a["te"])).json()}
    assert rows[a["check"]]["can_check"] is False


async def _own_check(session_factory, a, raiser_id):
    """A check item a Process member raised for Process (the C33 pattern)."""
    async with session_factory() as s:
        c = ChangeConcern(change_id=a["cid"], kind="needs_info",
                          note="Check our own cycle time", raised_by=raiser_id,
                          department_id=a["proc"], flag_type="check",
                          check_what="other")
        s.add(c)
        await s.commit()
        return c.id


async def test_no_free_note_close_for_the_author_in_the_department_or_pm(
        client, assess, session_factory):
    """R4: the structured close cannot be skipped by the raiser who sits in
    the owning department, nor by Project Management."""
    a = assess
    own = await _own_check(session_factory, a, a["pe_id"])
    url = _url(a, f"/concerns/{own}/withdraw")
    for auth in (a["pe"], a["lead"]):
        res = await client.post(url, json={"resolution_note": "ok"}, headers=auth)
        assert res.status_code == 400 and "what you found" in res.json()["detail"], res.text
    # PM closes it with evidence instead, and is served the form
    rows = {c["id"]: c for c in (await client.get(
        _url(a, "/concerns"), headers=a["lead"])).json()}
    assert rows[own]["can_check"] is True
    res = await client.post(_url(a, f"/concerns/{own}/check"),
                            json={"outcome": "answered", "value": "32", "unit": "s"},
                            headers=a["lead"])
    assert res.status_code == 200, res.text
    assert res.json()["settled_as"] == "pm"
    # the raiser reopens it
    res = await client.post(_url(a, f"/concerns/{own}/reopen"),
                            json={"reason": "cycle time was for the old tool"},
                            headers=a["pe"])
    assert res.status_code == 200, res.text


async def test_raiser_outside_the_department_drops_and_reopens_own_item(client, assess):
    a = assess
    res = await client.post(_url(a, f"/concerns/{a['check']}/withdraw"),
                            json={"resolution_note": "raised by mistake, was 4410"},
                            headers=a["raiser"])
    assert res.status_code == 200, res.text
    rows = {c["id"]: c for c in (await client.get(
        _url(a, "/concerns"), headers=a["raiser"])).json()}
    assert rows[a["check"]]["can_reopen"] is True
    res = await client.post(_url(a, f"/concerns/{a['check']}/reopen"),
                            json={"reason": "it was right after all"}, headers=a["raiser"])
    assert res.status_code == 200, res.text


async def test_served_flags_match_the_backend(client, assess):
    """R24: no answer button on a check item, no reopen after the submit."""
    a = assess
    for auth in (a["sa"], a["lead"], a["pe"]):
        rows = {c["id"]: c for c in (await client.get(
            _url(a, "/concerns"), headers=auth)).json()}
        assert rows[a["check"]]["can_answer"] is False
    await _close(client, a["pe"], a, outcome="answered", ref="DRW-4471 rev C")
    await _submit(client, a["pe"], a, a["proc"], ok=True)
    rows = {c["id"]: c for c in (await client.get(
        _url(a, "/concerns"), headers=a["raiser"])).json()}
    assert rows[a["check"]]["can_reopen"] is False
    res = await client.post(_url(a, f"/concerns/{a['check']}/reopen"),
                            json={"reason": "that is rev B, not C"}, headers=a["raiser"])
    assert res.status_code == 400 and "already submitted" in res.json()["detail"]


# --- C8: questions from the assessment ---------------------------------------

def _q(dept, **extra):
    return {"kind": "needs_info", "note": "Annual volume for 2027?",
            "department_id": dept, "check_what": "volume",
            "answer_from": "customer", **extra}


async def test_question_holds_only_own_submit_and_reaches_sales_owner(
        client, assess, session_factory):
    a = assess
    res = await client.post(_url(a, "/concerns"), json=_q(a["tool"]), headers=a["te"])
    assert res.status_code == 200, res.text
    qid = res.json()["id"]
    assert res.json()["flag_type"] == "question"
    # holds Tool Engineer's own submit (HARD #10), not Process'
    assert (await _submit(client, a["te"], a, a["tool"])).status_code == 400
    await _close(client, a["pe"], a, outcome="answered", ref="DRW-4471 rev C")
    await _submit(client, a["pe"], a, a["proc"], ok=True)
    async with session_factory() as s:
        told = (await s.execute(select(Notification).where(
            Notification.subject_key == f"ask:{qid}"))).scalars().all()
        assert [n.user_id for n in told] == [a["sales_id"]]
        assert told[0].kind == "task_new"
    # Sales sees it as an errand with the mail text
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=a["sa"])).json()
    rows = [t for t in tasks if t.get("kind") == "obtain_info"
            and t["change_id"] == a["cid"]]
    assert rows and "Annual volume" in (rows[0].get("customer_copy") or "")
    # answered in the asking department's bucket, not the read-only scoping tab
    assert rows[0]["target_tab"] == "assessments"
    # Sales answers (Assumed); the asker is told; Tool Engineer closes it
    res = await client.post(_url(a, f"/concerns/{qid}/answer"), json={
        "answer_kind": "assumed", "assumed_value": "120000", "assumed_unit": "pcs/yr",
        "assumed_risk": "lower volume, fewer cavities"}, headers=a["sa"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        heard = (await s.execute(select(Notification).where(
            Notification.subject_key == f"answered:{qid}"))).scalars().all()
        assert len(heard) == 1
    res = await client.post(_url(a, f"/concerns/{qid}/withdraw"),
                            json={"resolution_note": "120k pcs assumed, 2 cavities"},
                            headers=a["te"])
    assert res.status_code == 200, res.text
    await _submit(client, a["te"], a, a["tool"], ok=True)


async def test_question_for_our_team_goes_to_the_lead(client, assess, session_factory):
    a = assess
    res = await client.post(_url(a, "/concerns"),
                            json=_q(a["tool"], answer_from="our_team",
                                    check_what="schedule"), headers=a["te"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        told = (await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"ask:{res.json()['id']}"))).scalars().all()
        assert told == [a["lead_id"]]
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=a["lead"])).json()
    assert any(t.get("kind") == "obtain_info" and t["change_id"] == a["cid"]
               for t in tasks)


async def test_our_team_question_on_an_internal_change_is_the_leads_to_answer(
        client, assess, session_factory):
    """R5/R18: P3 makes the engineering raiser the lead of an internal
    change; the question routed to that lead is one they can answer."""
    a = assess
    async with session_factory() as s:
        c = await s.get(ChangeRequest, a["cid"])
        c.customer_relevant = False
        c.lead_id = a["raiser_id"]          # Development, not PM or Sales
        c.sales_owner_id = None
        await s.commit()
    res = await client.post(_url(a, "/concerns"),
                            json=_q(a["tool"], answer_from="our_team",
                                    check_what="schedule"), headers=a["te"])
    assert res.status_code == 200, res.text
    qid = res.json()["id"]
    async with session_factory() as s:
        told = (await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"ask:{qid}"))).scalars().all()
        assert told == [a["raiser_id"]]
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=a["raiser"])).json()
    assert any(t.get("kind") == "obtain_info" and t.get("concern_id") == qid
               for t in tasks)
    rows = {c["id"]: c for c in (await client.get(
        _url(a, "/concerns"), headers=a["raiser"])).json()}
    assert rows[qid]["can_answer"] is True
    res = await client.post(_url(a, f"/concerns/{qid}/answer"), json={
        "answer_kind": "assumed", "assumed_value": "KW 44", "assumed_unit": "n/a",
        "assumed_risk": "tool slot moves a week"}, headers=a["raiser"])
    assert res.status_code == 200, res.text
    # negative: Process (neither asker, lead, Sales nor PM) still may not
    rows = {c["id"]: c for c in (await client.get(
        _url(a, "/concerns"), headers=a["pe"])).json()}
    assert rows[qid]["can_answer"] is False


async def test_sales_is_not_tasked_with_an_our_team_question(client, assess):
    """R13: Sales' row counts customer and supplier questions only; a newer
    our-team question neither adds to it nor hides the mail text."""
    a = assess
    res = await client.post(_url(a, "/concerns"),
                            json=_q(a["tool"], answer_from="our_team",
                                    check_what="schedule"), headers=a["te"])
    assert res.status_code == 200, res.text
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=a["sa"])).json()
    assert not [t for t in tasks if t.get("kind") == "obtain_info"
                and t["change_id"] == a["cid"]]
    cq = (await client.post(_url(a, "/concerns"), json=_q(a["tool"], answer_from="supplier",
                                                          note="Hasco: insert lead time?"),
                            headers=a["te"])).json()
    await client.post(_url(a, "/concerns"),
                      json=_q(a["tool"], answer_from="our_team", check_what="schedule",
                              note="Free press slot in KW 45?"), headers=a["te"])
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=a["sa"])).json()
    rows = [t for t in tasks if t.get("kind") == "obtain_info"
            and t["change_id"] == a["cid"]]
    assert len(rows) == 1 and rows[0]["concern_id"] == cq["id"]
    assert rows[0]["question_count"] == 1
    # the supplier question carries its mail text too
    assert "Hasco: insert lead time?" in (rows[0].get("customer_copy") or "")
    assert "our change" in rows[0]["customer_copy"]


async def test_question_refusals(client, assess, monkeypatch):
    a = assess
    # negative: for another department, without who answers, as a check item
    res = await client.post(_url(a, "/concerns"), json=_q(a["proc"]), headers=a["te"])
    assert res.status_code == 400 and "own department" in res.json()["detail"]
    res = await client.post(_url(a, "/concerns"),
                            json=_q(a["tool"], answer_from=None), headers=a["te"])
    assert res.status_code == 400 and "who can answer" in res.json()["detail"]
    res = await client.post(_url(a, "/concerns"),
                            json=_q(a["tool"], flag_type="check"), headers=a["te"])
    assert res.status_code == 400 and "scoping" in res.json()["detail"]
    # negative: nothing left to hold once the department submitted
    await _submit(client, a["te"], a, a["tool"], ok=True)
    res = await client.post(_url(a, "/concerns"), json=_q(a["tool"]), headers=a["te"])
    assert res.status_code == 400 and "no open assessment" in res.json()["detail"]


async def test_switch_off_keeps_the_risk_only_register(client, assess, monkeypatch):
    monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
    a = assess
    res = await client.post(_url(a, "/concerns"), json=_q(a["tool"]), headers=a["te"])
    assert res.status_code == 400 and "belong to scoping" in res.json()["detail"]
    res = await _close(client, a["pe"], a, outcome="answered", ref="DRW-4471 rev C")
    assert res.status_code == 400
    # the old way still closes it: a member with a resolution note
    res = await client.post(_url(a, f"/concerns/{a['check']}/withdraw"),
                            json={"resolution_note": "checked against DRW-4471"},
                            headers=a["pe"])
    assert res.status_code == 200, res.text
