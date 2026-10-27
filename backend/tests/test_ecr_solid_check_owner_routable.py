"""A2-03 follow-through (R24, R37): one rule for a check item's owner.

Proceed routes an unrouted check-item owner as C. Management (OKs only, no
hours) and a retired department take no task letter, so neither may own a
check item: refused at the raise, at 'same as' and at 'make it a check
item'. A question may still be raised for Management. An item from before
the rule (or whose department retired since) is named at proceed with its
ids and the way out; the routable owner of the same meeting is still routed
C."""
import pytest
from sqlalchemy import select

from tests.test_ecr_solid_scoping_v2 import (
    _check, _decide, _meeting, _question, _raise, _scoping, _user,
)


@pytest.fixture(autouse=True)
def _any_member_may_ask(monkeypatch):
    """Department askers work the routing rules; who may raise in scoping
    (PM / lead only since 2026-10-27) is tested in test_scoping_pm_questions.py."""
    from app.services import cm_switches
    monkeypatch.setattr(cm_switches, "SCOPING_QUESTIONS_PM_ONLY", False)
    # check items too (scoping takes questions only since 2026-10-27; the
    # refusal is tested in test_scoping_pm_questions.py)
    monkeypatch.setattr(cm_switches, "SCOPING_QUESTIONS_ONLY", False)

pytestmark = pytest.mark.asyncio


async def _dept(session_factory, name, active=True):
    from app.models.workflow import Department
    async with session_factory() as s:
        d = (await s.execute(select(Department).where(Department.name == name))).scalar_one_or_none()
        if d is None:
            d = Department(name=name, flow_type="action", is_active=active)
            s.add(d)
        d.is_active = active
        await s.commit()
        return d.id


async def test_check_item_for_management_is_refused_at_the_raise(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "cor1")
    mgmt = await _dept(session_factory, "Management")
    _, proc, pe = await _user(client, session_factory, seed, "cor1pe", "Process Engineer")
    res = await _raise(client, pe, cid, _check(mgmt))
    assert res.status_code == 400, res.text
    assert "Management gives OKs and books no hours" in res.text
    assert "make it a question" in res.text
    # NEGATIVE: a question may still be raised for Management, and a check
    # item for a routable department goes through
    assert (await _raise(client, pe, cid, _question(mgmt))).status_code == 200
    assert (await _raise(client, pe, cid, _check(proc))).status_code == 200


async def test_a_question_for_management_cannot_become_a_check_item(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "cor2")
    mgmt = await _dept(session_factory, "Management")
    _, proc, pe = await _user(client, session_factory, seed, "cor2pe", "Process Engineer")
    q = (await _raise(client, pe, cid, _question(mgmt))).json()
    url = f"/api/v1/changes/{cid}/concerns/{q['id']}/type"
    res = await client.post(url, json={"flag_type": "check"}, headers=pe)
    assert res.status_code == 400, res.text
    assert "never routed" in res.text
    # NEGATIVE: moved to a routable department in the same step, it may
    res = await client.post(url, json={"flag_type": "check", "department_id": proc},
                            headers=pe)
    assert res.status_code == 200, res.text
    assert res.json()["flag_type"] == "check"


async def test_management_cannot_co_own_a_check_item_but_may_a_question(
        client, admin_auth, seed, session_factory):
    cid, _ = await _scoping(client, admin_auth, seed, "cor3")
    _, proc, pe = await _user(client, session_factory, seed, "cor3pe", "Process Engineer")
    _, mgmt, boss = await _user(client, session_factory, seed, "cor3mg", "Management")
    chk = (await _raise(client, pe, cid, _check(proc))).json()
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{chk['id']}/join",
                            json={"department_id": mgmt}, headers=boss)
    assert res.status_code == 400, res.text
    assert "never routed" in res.text
    q = (await _raise(client, pe, cid, _question(proc, note="Which tool steel?"))).json()
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{q['id']}/join",
                            json={"department_id": mgmt}, headers=boss)
    assert res.status_code == 200, res.text


async def test_an_old_check_item_owned_by_management_is_named_at_proceed(
        client, admin_auth, seed, session_factory):
    """An item from before the rule: proceed names it with its id and the
    way out; withdrawn, proceed goes and still routes the routable
    owner of the other item as C."""
    from app.models.change import ChangeConcern
    cid, _ = await _scoping(client, admin_auth, seed, "cor4")
    mgmt = await _dept(session_factory, "Management")
    _, proc, pe = await _user(client, session_factory, seed, "cor4pe", "Process Engineer")
    _, qual, _q = await _user(client, session_factory, seed, "cor4q", "Quality")
    mid = await _meeting(client, admin_auth, cid, {str(proc): "R"})
    good = (await _raise(client, pe, cid, _check(qual, note="Check the gauge"))).json()
    async with session_factory() as s:
        old = ChangeConcern(change_id=cid, kind="needs_info", note="Budget OK?",
                            raised_by=seed["admin_id"], department_id=mgmt,
                            flag_type="check", check_what="other")
        s.add(old)
        await s.commit()
        old_id = old.id
    res = await _decide(client, admin_auth, cid, mid, "proceed")
    assert res.status_code == 400, res.text
    assert f"#{old_id}" in res.text and "Make them questions or withdraw them" in res.text
    # NEGATIVE: the routable owner is not named
    assert f"#{good['id']}" not in res.text
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{old_id}/withdraw",
                            json={"resolution_note": "Budget is Management's OK, not a check"},
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    res = await _decide(client, admin_auth, cid, mid, "proceed")
    assert res.status_code == 200, res.text
    assert res.json()["department_rasic"][str(qual)] == "C"
