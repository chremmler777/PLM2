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
from datetime import datetime

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
    assert res.status_code == 400
    assert ("#%d check item 'Check the gate position': close it with what you found"
            % a["check"]) in res.json()["detail"]
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
    # R5/R37: the refusal names an exit that exists, not a send-back
    assert "risk on its assessment" in res.json()["detail"]
    assert "send" not in res.json()["detail"]
    # ... and the department can take it after its submit
    res = await client.post(_url(a, "/concerns"), json={
        "kind": "risk", "risk_type": "dimensional_issue", "severity": 2,
        "note": "Drawing is rev B, not C", "department_id": a["proc"]},
        headers=a["pe"])
    assert res.status_code == 200, res.text


async def test_a_consulted_department_owning_check_items_gets_the_task(
        client, assess, seed, session_factory):
    """R18: routed C (no submit owed), it still owns its check items: the
    task names them, and goes once they are closed."""
    a = assess
    shop_id, shop, shop_auth = await _user(client, session_factory, seed, "shop", "Toolshop")
    async with session_factory() as s:
        s.add(ChangeAssessment(change_id=a["cid"], department_id=shop, stage_order=1,
                               rasic_letter="C", status="active"))
        chk = ChangeConcern(change_id=a["cid"], kind="needs_info",
                            note="Check gate wear on tool", raised_by=a["raiser_id"],
                            department_id=shop, flag_type="check", check_what="other")
        s.add(chk)
        await s.commit()
        cid = chk.id
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=shop_auth)).json()
    row = next(t for t in tasks if t["kind"] == "assessment" and t["change_id"] == a["cid"])
    assert row["hint"] == "Close your check items (1)"
    # R5: the count for the UI, the department as owner; no assessment due
    # anywhere yet, so no date is invented
    assert row["checks_open"] == 1 and row["department_name"] == "Toolshop"
    assert row["due_date"] is None
    # the change's assessment due (an R row's) is the C row's and the item's due
    due = datetime(2026, 10, 22, 12, 0)
    async with session_factory() as s:
        for r in (await s.execute(select(ChangeAssessment).where(
                ChangeAssessment.change_id == a["cid"],
                ChangeAssessment.rasic_letter == "R"))).scalars():
            r.due_date = due
        await s.commit()
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=shop_auth)).json()
    row = next(t for t in tasks if t["kind"] == "assessment" and t["change_id"] == a["cid"])
    assert row["due_date"].startswith("2026-10-22")
    rows = {c["id"]: c for c in (await client.get(
        _url(a, "/concerns"), headers=shop_auth)).json()}
    assert rows[cid]["owner_due"].startswith("2026-10-22")
    acts = (await client.get(_url(a, "/my-actions"), headers=shop_auth)).json()
    assert any(x["kind"] == "assessment" and "check items" in x["label"]
               for x in acts["actions"])
    res = await client.post(_url(a, f"/concerns/{cid}/check"),
                            json={"outcome": "answered", "value": "0.5", "unit": "mm"},
                            headers=shop_auth)
    assert res.status_code == 200, res.text
    # negative: nothing left to close, no submit owed: no task
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=shop_auth)).json()
    assert not [t for t in tasks if t["kind"] == "assessment"
                and t["change_id"] == a["cid"]]


async def test_the_raiser_of_a_closed_check_item_reads_it_in_the_digest(
        client, assess, seed, session_factory):
    """R21: the raiser (here a Process colleague who is neither lead, change
    raiser nor Sales owner) is the one who may reopen it: the digest tells."""
    from app.services.change_digest import DIGEST_KIND, send_change_digest
    a = assess
    q_id, _, q_auth = await _user(client, session_factory, seed, "qa", "Quality")
    async with session_factory() as s:
        chk = ChangeConcern(change_id=a["cid"], kind="needs_info",
                            note="Check the rib", raised_by=q_id,
                            department_id=a["proc"], flag_type="check",
                            check_what="drawing")
        s.add(chk)
        await s.commit()
        cid = chk.id
    res = await client.post(_url(a, f"/concerns/{cid}/check"),
                            json={"outcome": "answered", "ref": "DRW-4471 rev C"},
                            headers=a["pe"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        await send_change_digest(s)
        await s.commit()
        got = (await s.execute(select(Notification.body).where(
            Notification.kind == DIGEST_KIND,
            Notification.user_id == q_id))).scalars().all()
    assert got and "C-AC-1" in got[0] and "closed" in got[0]


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
    # holds Tool Engineer's own submit (HARD #10), not Process', and says
    # who owes the next move
    res = await _submit(client, a["te"], a, a["tool"])
    assert res.status_code == 400 and "waiting for Sales to answer" in res.json()["detail"]
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
    # negative: a free note is no answer to a question that holds a submit
    res = await client.post(_url(a, f"/concerns/{qid}/answer"), json={"note": "ok"},
                            headers=a["sa"])
    assert res.status_code == 400 and "Confirmed" in res.json()["detail"]
    # Sales answers (Assumed); the asker is told; Tool Engineer closes it
    res = await client.post(_url(a, f"/concerns/{qid}/answer"), json={
        "answer_kind": "assumed", "assumed_value": "120000", "assumed_unit": "pcs/yr",
        "assumed_risk": "lower volume, fewer cavities"}, headers=a["sa"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        heard = (await s.execute(select(Notification).where(
            Notification.subject_key == f"answered:{qid}"))).scalars().all()
        assert len(heard) == 1
    res = await _submit(client, a["te"], a, a["tool"])
    assert res.status_code == 400 and "answered, settle it" in res.json()["detail"]
    # negative (R4): 'ok' does not settle it
    res = await client.post(_url(a, f"/concerns/{qid}/withdraw"),
                            json={"resolution_note": "ok"}, headers=a["te"])
    assert res.status_code == 400 and "settles it" in res.json()["detail"]
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


async def test_project_management_sees_a_customer_question_as_support(
        client, assess, session_factory, seed):
    """Christoph 2026-10-30: a customer/supplier question from the
    assessment is Sales' to ask, but Project Management sees it too: a
    support row naming the Sales contact, with the mail text."""
    a = assess
    _pm2_id, _, pm2 = await _user(client, session_factory, seed, "pm2", "Project Manager")
    cq = (await client.post(_url(a, "/concerns"), json=_q(a["tool"], answer_from="customer",
                                                          note="Grain K31 on the new rib?"),
                            headers=a["te"])).json()
    rows = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=pm2)).json()
            if t.get("kind") == "obtain_info" and t["change_id"] == a["cid"]]
    assert len(rows) == 1 and rows[0]["concern_id"] == cq["id"]
    assert rows[0]["role"] == "backup" and rows[0]["main_name"]
    assert "Grain K31 on the new rib?" in (rows[0].get("customer_copy") or "")
    # Sales keeps it as its own task
    rows = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=a["sa"])).json()
            if t.get("kind") == "obtain_info" and t["change_id"] == a["cid"]]
    assert len(rows) == 1 and rows[0]["role"] == "main"
    # negative: Process (neither Sales, PM nor lead) gets no row
    rows = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=a["pe"])).json()
            if t.get("kind") == "obtain_info" and t["change_id"] == a["cid"]]
    assert rows == []


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


async def test_assumed_check_item_is_confirmed_where_its_task_leads(
        client, assess, session_factory):
    """A3-01: the confirm item of an Assumed check item is done on the
    assessments tab (the check item's own bucket): the task and the notice
    lead there, the row is served can_confirm, and it confirms in costing."""
    a = assess
    res = await _close(client, a["pe"], a, outcome="assumed", value="2.4", unit="mm",
                       assumed_risk="gate moves, re-cut the insert")
    assert res.status_code == 200, res.text
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=a["sa"])).json()
    rows = [t for t in tasks if t.get("kind") == "confirm_assumption"
            and t["change_id"] == a["cid"]]
    assert rows and rows[0]["target_tab"] == "assessments"
    async with session_factory() as s:
        n = (await s.execute(select(Notification).where(
            Notification.user_id == a["sales_id"],
            Notification.kind == "confirm_assumption"))).scalars().one()
        assert "tab=assessments" in n.link
        change = await s.get(ChangeRequest, a["cid"])
        change.status = "costing"
        await s.commit()
    served = (await client.get(_url(a, "/concerns"), headers=a["sa"])).json()
    row = next(c for c in served if c["id"] == a["check"])
    assert row["can_confirm"] is True
    # negative: Tool Engineer is neither the confirmer nor may it answer
    served = (await client.get(_url(a, "/concerns"), headers=a["te"])).json()
    assert next(c for c in served if c["id"] == a["check"])["can_confirm"] is False
    res = await client.post(_url(a, f"/concerns/{a['check']}/confirm"),
                            json={"ref": "MAIL-2026-1015"}, headers=a["sa"])
    assert res.status_code == 200, res.text
    assert res.json()["answer_kind"] == "confirmed"


async def test_a_consulted_departments_open_check_item_holds_costing_and_closes_there(
        client, assess, seed, session_factory):
    """A3-02: a C department owes no submit, so its open check item is named
    on the SOFT assessments_open line (in_assessment -> costing) and on the
    C5 line in costing, where the department still closes it with evidence;
    a free note closes it in no status (R4)."""
    a = assess
    shop_id, shop, shop_auth = await _user(client, session_factory, seed, "shop2", "Toolshop")
    async with session_factory() as s:
        s.add(ChangeAssessment(change_id=a["cid"], department_id=shop, stage_order=1,
                               rasic_letter="C", status="active"))
        chk = ChangeConcern(change_id=a["cid"], kind="needs_info",
                            note="Check gate wear on tool", raised_by=a["raiser_id"],
                            department_id=shop, flag_type="check", check_what="other")
        s.add(chk)
        await s.commit()
        cid = chk.id
    await _close(client, a["pe"], a, outcome="answered", ref="DRW-4471 rev C")
    await _submit(client, a["pe"], a, a["proc"], ok=True)
    await _submit(client, a["te"], a, a["tool"], ok=True)
    ch = (await client.get(_url(a), headers=a["lead"])).json()
    item = next(i for i in ch["next_step"]["items"] if i["key"] == "assessments")
    assert item["rule"] == "assessments_open"
    assert f"Check items open: Toolshop #{cid}" in item["who"]
    res = await client.post(_url(a, "/transition"), json={"to_status": "costing"},
                            headers=a["lead"])
    assert res.status_code == 400 and f"Toolshop #{cid}" in res.json()["detail"], res.text
    async with session_factory() as s:
        change = await s.get(ChangeRequest, a["cid"])
        change.status = "costing"
        await s.commit()
    ch = (await client.get(_url(a), headers=a["lead"])).json()
    assert any(f"Check items open: Toolshop #{cid}" in (i.get("who") or "")
               for i in ch["next_step"]["items"]), ch["next_step"]
    # negative (R4): Project Management's free note is no close in costing
    res = await client.post(_url(a, f"/concerns/{cid}/withdraw"),
                            json={"resolution_note": "checked, fine"}, headers=a["lead"])
    assert res.status_code == 400 and "what you found" in res.json()["detail"], res.text
    served = {c["id"]: c for c in (await client.get(
        _url(a, "/concerns"), headers=shop_auth)).json()}
    assert served[cid]["can_check"] is True
    res = await client.post(_url(a, f"/concerns/{cid}/check"),
                            json={"outcome": "answered", "value": "0.5", "unit": "mm"},
                            headers=shop_auth)
    assert res.status_code == 200, res.text
    ch = (await client.get(_url(a), headers=a["lead"])).json()
    assert not any("Check items open" in (i.get("who") or "")
                   for i in ch["next_step"]["items"])


async def test_answered_by_a_file_counts_only_the_departments_own_file(
        client, assess):
    """A3-10a (R4): the raiser's attachment from raise time is the question,
    not the answer: only a file filed on the item by someone else after it
    was raised closes it as Answered."""
    a = assess
    up = lambda auth: client.post(_url(a, "/attachments"),
                                  files={"file": ("sketch.pdf", b"%PDF-1.4 s", "application/pdf")},
                                  data={"kind": "info_response", "concern_id": str(a["check"])},
                                  headers=auth)
    res = await up(a["raiser"])
    assert res.status_code in (200, 201), res.text
    res = await _close(client, a["pe"], a, outcome="answered")
    assert res.status_code == 400 and "evidence" in res.json()["detail"], res.text
    res = await up(a["pe"])
    assert res.status_code in (200, 201), res.text
    res = await _close(client, a["pe"], a, outcome="answered")
    assert res.status_code == 200, res.text


async def test_an_assumed_answer_the_asker_confirms_is_one_action(
        client, assess, session_factory):
    """A3-13: the asker named to confirm an Assumed answer gets ONE row,
    'Confirm the assumption <value> by <date>', and confirming settles the
    question too; the answerer reads its due; the notice's hold sentence
    names the asking department while its submit is open."""
    from app.models.entities import User
    a = assess
    async with session_factory() as s:
        te_id = (await s.execute(select(User.id).where(
            User.email == "ac-te@test.io"))).scalar_one()
    res = await client.post(_url(a, "/concerns"), json=_q(a["tool"]), headers=a["te"])
    qid = res.json()["id"]
    async with session_factory() as s:
        body = (await s.execute(select(Notification.body).where(
            Notification.subject_key == f"ask:{qid}"))).scalar_one()
    assert "It holds Tool Engineer's assessment" in body
    served = {c["id"]: c for c in (await client.get(
        _url(a, "/concerns"), headers=a["sa"])).json()}
    assert served[qid]["answer_due"] is not None
    res = await client.post(_url(a, f"/concerns/{qid}/answer"), json={
        "answer_kind": "assumed", "assumed_value": "120000", "assumed_unit": "pcs/yr",
        "assumed_risk": "lower volume, fewer cavities", "confirm_by_id": te_id},
        headers=a["sa"])
    assert res.status_code == 200, res.text
    tasks = [t for t in (await client.get("/api/v1/changes/my-tasks",
                                          headers=a["te"])).json()
             if t["change_id"] == a["cid"]
             and t["kind"] in ("close_question", "confirm_assumption")]
    assert [t["kind"] for t in tasks] == ["confirm_assumption"], tasks
    assert tasks[0]["kind_label"].startswith("Confirm the assumption 120000 pcs/yr")
    mail = await client.post(_url(a, "/attachments"),
                             files={"file": ("volume.eml", b"From: c\n\n120k", "message/rfc822")},
                             data={"kind": "customer_email"}, headers=a["sa"])
    assert mail.status_code in (200, 201), mail.text
    res = await client.post(_url(a, f"/concerns/{qid}/confirm"),
                            json={"mail_id": mail.json()["id"]}, headers=a["te"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        q = await s.get(ChangeConcern, qid)
        assert q.answer_kind == "confirmed" and q.withdrawn_at is not None


async def test_a_sales_confirmer_leaves_the_asker_only_the_settle(client, assess):
    """A3-13 negative: confirmed by Sales (default), the asker's one action
    is to settle the answered question; no confirm row for the asker."""
    a = assess
    res = await client.post(_url(a, "/concerns"), json=_q(a["tool"]), headers=a["te"])
    qid = res.json()["id"]
    res = await client.post(_url(a, f"/concerns/{qid}/answer"), json={
        "answer_kind": "assumed", "assumed_value": "120000", "assumed_unit": "pcs/yr",
        "assumed_risk": "lower volume, fewer cavities"}, headers=a["sa"])
    assert res.status_code == 200, res.text
    kinds = [t["kind"] for t in (await client.get("/api/v1/changes/my-tasks",
                                                  headers=a["te"])).json()
             if t["change_id"] == a["cid"]
             and t["kind"] in ("close_question", "confirm_assumption")]
    assert kinds == ["close_question"]


async def test_a_question_after_the_submit_holds_nothing_in_its_notice(
        client, assess, session_factory):
    """A3-13 negative: asked after the department submitted, the notice does
    not claim it holds that department's assessment."""
    a = assess
    await _close(client, a["pe"], a, outcome="answered", ref="DRW-4471 rev C")
    await _submit(client, a["pe"], a, a["proc"], ok=True)
    res = await client.post(_url(a, "/concerns"), json=_q(a["proc"]), headers=a["pe"])
    if res.status_code != 200:
        assert res.status_code == 400, res.text      # refused outright: nothing to word
        return
    async with session_factory() as s:
        body = (await s.execute(select(Notification.body).where(
            Notification.subject_key == f"ask:{res.json()['id']}"))).scalar_one()
    assert "It holds" not in body
