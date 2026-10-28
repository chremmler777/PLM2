"""Scoping is a team task led by the PM (Christoph 2026-10-27).

Questions and check items are raised in the meeting by Project Management or
the change lead; a team member (e.g. Quality) gets a 403 that says to bring
the point to the meeting. Propose to cancel stays open to everyone. The
switch SCOPING_QUESTIONS_PM_ONLY off brings back "anyone may ask".
"""
import pytest

from tests.conftest import QUESTION
from tests.test_scoping_live_test_1 import _change_in_scoping, _user

pytestmark = pytest.mark.asyncio


async def _ask(client, auth, cid, dept_id):
    return await client.post(f"/api/v1/changes/{cid}/concerns", headers=auth, json={
        "kind": "needs_info", "note": "Which tolerance class?",
        "department_id": dept_id, **QUESTION})


async def test_team_member_may_not_ask_in_scoping_but_may_propose_to_cancel(
        client, admin_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "pmq1")
    _, quality_id, quality = await _user(client, session_factory, seed, "pmq-q", "Quality")

    res = await _ask(client, quality, cid, quality_id)
    assert res.status_code == 403, res.text
    assert "meeting" in res.json()["detail"]

    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=quality, json={
        "kind": "reject_proposal", "note": "Cannot be measured with our gauges"})
    assert res.status_code == 200, res.text


async def test_pm_asks_for_a_department(client, admin_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "pmq2")
    _, quality_id, _ = await _user(client, session_factory, seed, "pmq-q2", "Quality")
    _, _, pm = await _user(client, session_factory, seed, "pmq-pm", "Project Manager")

    res = await _ask(client, pm, cid, quality_id)
    assert res.status_code == 200, res.text
    assert res.json()["department_id"] == quality_id


async def test_switch_off_lets_anyone_ask(client, admin_auth, seed, session_factory,
                                          monkeypatch):
    from app.services import cm_switches
    monkeypatch.setattr(cm_switches, "SCOPING_QUESTIONS_PM_ONLY", False)
    cid = await _change_in_scoping(client, admin_auth, seed, "pmq3")
    _, quality_id, quality = await _user(client, session_factory, seed, "pmq-q3", "Quality")

    res = await _ask(client, quality, cid, quality_id)
    assert res.status_code == 200, res.text


async def test_proceed_waits_for_the_scope(client, admin_auth, seed, session_factory):
    """Christoph 2026-10-27: no proceed out of scoping without a written scope."""
    from tests.test_scoping_live_test_1 import _decide, _dept_ids, _meeting
    cid = await _change_in_scoping(client, admin_auth, seed, "pmq4")
    url = f"/api/v1/changes/{cid}/scope-definition"
    assert (await client.put(url, json={"scope_definition": " "},
                             headers=admin_auth)).status_code == 200
    mid = await _meeting(client, admin_auth, cid, await _dept_ids(session_factory))
    res = await _decide(client, admin_auth, cid, mid, "proceed")
    assert res.status_code == 400 and "No scope defined" in res.json()["detail"]
    nxt = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)).json()
    keys = [i["key"] for i in (nxt.get("next_step") or {}).get("items", [])]
    assert "scope_definition" in keys, nxt.get("next_step")
    assert (await client.put(url, json={"scope_definition": "Insert only"},
                             headers=admin_auth)).status_code == 200
    assert (await _decide(client, admin_auth, cid, mid, "proceed")).status_code == 200


async def test_scoping_takes_no_check_items(client, admin_auth, seed, session_factory):
    """Christoph 2026-10-27: blocking questions only; a check belongs in the
    department's assessment. A question cannot be switched to a check item."""
    cid = await _change_in_scoping(client, admin_auth, seed, "pmq5")
    _, quality_id, _ = await _user(client, session_factory, seed, "pmq-q5", "Quality")
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=admin_auth, json={
        "kind": "needs_info", "note": "Check the gauge", "department_id": quality_id,
        "flag_type": "check", "check_what": "other"})
    assert res.status_code == 400 and "questions only" in res.json()["detail"]
    qid = (await _ask(client, admin_auth, cid, quality_id)).json()["id"]
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{qid}/type",
                            headers=admin_auth, json={"flag_type": "check"})
    assert res.status_code == 400 and "questions only" in res.json()["detail"], res.text


async def test_pm_short_form_question_text_and_who_answers(
        client, admin_auth, seed, session_factory):
    """The PM's short form: question + who answers (+ part); no department,
    no topic, no 'what it changes'. Two questions, both block proceed."""
    from tests.test_scoping_live_test_1 import _decide, _dept_ids, _meeting
    cid = await _change_in_scoping(client, admin_auth, seed, "pmq6")
    for note in ("Both variants?", "Which colour?"):
        res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=admin_auth, json={
            "kind": "needs_info", "note": note, "flag_type": "question",
            "answer_from": "customer"})
        assert res.status_code == 200, res.text
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=admin_auth, json={
        "kind": "needs_info", "note": "both variants? ", "flag_type": "question",
        "answer_from": "customer"})
    assert res.status_code == 400 and "already asked" in res.json()["detail"]
    mid = await _meeting(client, admin_auth, cid, await _dept_ids(session_factory))
    res = await _decide(client, admin_auth, cid, mid, "proceed")
    assert res.status_code == 400


async def test_confirmed_without_proof_is_allowed_with_the_answer_in_words(
        client, admin_auth, seed, session_factory):
    """Christoph 2026-10-28: forcing the customer's mail is overboard; the
    form warns instead. No proof needs the answer in words; a reference that
    is given must still be a real one; the history says "no proof"."""
    cid = await _change_in_scoping(client, admin_auth, seed, "pmq7")
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=admin_auth, json={
        "kind": "needs_info", "note": "Both variants?", "flag_type": "question",
        "answer_from": "customer"})
    qid = res.json()["id"]
    url = f"/api/v1/changes/{cid}/concerns/{qid}/answer"
    res = await client.post(url, json={"answer_kind": "confirmed"}, headers=admin_auth)
    assert res.status_code == 400 and "in words" in res.json()["detail"]
    res = await client.post(url, json={"answer_kind": "confirmed", "mail_id": 999999,
                                       "note": "Yes"}, headers=admin_auth)
    assert res.status_code == 400
    res = await client.post(url, json={"answer_kind": "confirmed",
                                       "note": "Yes, LH and RH"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["answer_kind"] == "confirmed" and not res.json()["answer_ref"]
    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=admin_auth)).json()
    rows = log.get("items", log) if isinstance(log, dict) else log
    assert any("no proof attached" in (r.get("description") or r.get("summary") or str(r))
               for r in rows), rows[:3]


async def test_switch_on_brings_back_the_evidence_rule(
        client, admin_auth, seed, session_factory, monkeypatch):
    from app.services import cm_switches
    monkeypatch.setattr(cm_switches, "CONFIRM_EVIDENCE_REQUIRED", True)
    cid = await _change_in_scoping(client, admin_auth, seed, "pmq8")
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=admin_auth, json={
        "kind": "needs_info", "note": "Both variants?", "flag_type": "question",
        "answer_from": "customer"})
    url = f"/api/v1/changes/{cid}/concerns/{res.json()['id']}/answer"
    res = await client.post(url, json={"answer_kind": "confirmed", "note": "Yes"},
                            headers=admin_auth)
    assert res.status_code == 400 and "customer's" in res.json()["detail"]
