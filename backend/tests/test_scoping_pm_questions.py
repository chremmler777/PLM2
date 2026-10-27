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
