"""R25/R37: an admin's own department rows do not sign a side or approve
internal spend (the hard3_blind rule the close-out uses for HARD #3, the
staffed departments and the notices). In a small plant's set-up the admin
account belongs to every department; without this it would sign PM and
Quality, or approve HARD #8, with no department on the record. An admin
who stands in acts as the department: then it signs and approves."""
from datetime import datetime, timedelta

import pytest

from app.models.workflow import UserDepartment
from tests.conftest import login
from tests.test_ecr_solid_tasks import _as, _create, _set, _tasks, team  # noqa: F401

pytestmark = pytest.mark.asyncio
ACTS = "X-Acts-As-Department"
_RELEASE_DUE = (datetime.utcnow() + timedelta(days=120)).isoformat()


async def _admin_everywhere(session_factory, seed, team):
    async with session_factory() as s:
        for name in ("Project Manager", "Quality"):
            s.add(UserDepartment(user_id=seed["admin_id"],
                                 department_id=team["dept"][name]))
        await s.commit()


async def _accepted(client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "sign me")
    await _set(session_factory, cid, status="quoted", customer_response="accepted",
               customer_response_at=datetime.utcnow(),
               lead_id=team["user"]["Project Manager"])
    return cid


async def test_admin_not_acting_signs_no_side(client, seed, team, session_factory):
    await _admin_everywhere(session_factory, seed, team)
    cid = await _accepted(client, seed, team, session_factory)
    admin = await login(client, "admin@test.io")
    for role in ("pm", "quality"):
        res = await client.post(f"/api/v1/changes/{cid}/sign-off",
                                json={"role": role}, headers=admin)
        assert res.status_code == 403, res.text
        assert "acts as the department" in res.json()["detail"]
    # NEGATIVE: no sign-off row in the admin's own tasks either
    assert await _tasks(client, admin, cid, "sign_off") == []


async def test_admin_acting_as_the_department_signs(client, seed, team, session_factory):
    await _admin_everywhere(session_factory, seed, team)
    cid = await _accepted(client, seed, team, session_factory)
    admin = await login(client, "admin@test.io")
    pm = {**admin, ACTS: str(team["dept"]["Project Manager"])}
    rows = await _tasks(client, pm, cid, "sign_off")
    assert [r["side"] for r in rows] == ["pm"]
    res = await client.post(f"/api/v1/changes/{cid}/sign-off",
                            json={"role": "pm"}, headers=pm)
    assert res.status_code != 403, res.text
    # a real member signs as before
    quality = await _as(client, "Quality")
    res = await client.post(f"/api/v1/changes/{cid}/sign-off",
                            json={"role": "quality"}, headers=quality)
    assert res.status_code != 403, res.text


async def _internal_in_costing(client, seed, team, session_factory):
    dev = await _as(client, "Development")
    cid = await _create(client, dev, seed, "internal spend", customer_relevant=False)
    await _set(session_factory, cid, status="costing",
               raised_by=team["user"]["Development"],
               lead_id=team["user"]["Development"])
    return cid


async def test_admin_not_acting_is_no_internal_approver(client, seed, team,
                                                         session_factory):
    await _admin_everywhere(session_factory, seed, team)
    cid = await _internal_in_costing(client, seed, team, session_factory)
    admin = await login(client, "admin@test.io")
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=admin)).json()
    assert st["can_approve_internal"] is False
    assert await _tasks(client, admin, cid, "internal_approval") == []
    res = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                            json={"note": "ok", "release_due_date": _RELEASE_DUE,
                                  "rationale": "quality"}, headers=admin)
    assert res.status_code == 403, res.text


async def test_admin_acting_as_pm_approves_internal_spend(client, seed, team,
                                                          session_factory):
    await _admin_everywhere(session_factory, seed, team)
    cid = await _internal_in_costing(client, seed, team, session_factory)
    admin = await login(client, "admin@test.io")
    pm = {**admin, ACTS: str(team["dept"]["Project Manager"])}
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=pm)).json()
    assert st["can_approve_internal"] is True
    assert len(await _tasks(client, pm, cid, "internal_approval")) == 1
    res = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                            json={"note": "ok", "release_due_date": _RELEASE_DUE,
                                  "rationale": "quality"}, headers=pm)
    assert res.status_code == 200, res.text
    # NEGATIVE: acting as another department is no approver
    other = await _internal_in_costing(client, seed, team, session_factory)
    q = {**admin, ACTS: str(team["dept"]["Quality"])}
    res = await client.post(f"/api/v1/changes/{other}/internal-approval",
                            json={"note": "ok", "release_due_date": _RELEASE_DUE,
                                  "rationale": "quality"}, headers=q)
    assert res.status_code == 403, res.text


async def test_internal_approval_notice_skips_the_admin_account(
        client, seed, team, session_factory):
    from app.models.change import ChangeRequest
    from app.services.change_service import ChangeService
    await _admin_everywhere(session_factory, seed, team)
    cid = await _internal_in_costing(client, seed, team, session_factory)
    async with session_factory() as s:
        ids = await ChangeService.internal_approver_ids(s, await s.get(ChangeRequest, cid))
    assert ids == {team["user"]["Project Manager"]}
