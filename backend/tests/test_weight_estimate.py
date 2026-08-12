"""The part weight quoted at costing by the Tooling Engineer.

The rules under test: who may state it (the department that owns the tool, and
nobody else), when (while the change is in costing), that re-stating it is an
edit rather than an error, and that the number reaches both the places it is
read from — the change detail and the costing wrap-up Sales prices off.
"""
import pytest

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.entities import Project
from app.models.workflow import Department, UserDepartment
from tests.conftest import login

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def weighing(session_factory, seed):
    """A change in costing with the two departments that argue about weight:
    Tool Engineer, who makes the tool, and Development, who does not."""
    async with session_factory() as s:
        tool = Department(name="Tool Engineer", flow_type="action", is_active=True)
        dev = Department(name="Development", flow_type="action", is_active=True)
        s.add_all([tool, dev])
        await s.flush()
        change = ChangeRequest(
            change_number="C-WT-1", title="weight", reason="r",
            change_type="tooling", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"], status="costing")
        s.add(change)
        await s.flush()
        for dept in (tool, dev):
            s.add(ChangeAssessment(change_id=change.id, department_id=dept.id,
                                   stage_order=1, verdict="feasible"))
        await s.commit()
        return {"change_id": change.id, "tool": tool.id, "dev": dev.id}


async def _member(client, session_factory, seed, dept_id, email):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=email.split("@")[0],
                 email=email, full_name=email, role="engineer",
                 hashed_password=get_password_hash("member-secret-1"),
                 is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=dept_id))
        await s.commit()
        return await login(client, email)


def _url(weighing) -> str:
    return f"/api/v1/changes/{weighing['change_id']}/weight-estimate"


async def _set_status(session_factory, change_id, status):
    async with session_factory() as s:
        change = await s.get(ChangeRequest, change_id)
        change.status = status
        await s.commit()


# --- the estimate -----------------------------------------------------------

async def test_tool_engineer_quotes_the_weight_during_costing(
        client, session_factory, seed, weighing):
    auth = await _member(client, session_factory, seed, weighing["tool"],
                         "wtool@test.io")
    res = await client.put(_url(weighing), json={"weight_g": 842.5}, headers=auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["estimated_part_weight_g"] == 842.5
    assert body["estimated_weight_by_name"] == "wtool@test.io"
    assert body["estimated_weight_at"] is not None
    # The validated half exists and stays empty until validation fills it.
    assert body["validated_part_weight_g"] is None
    assert body["validated_weight_at"] is None


async def test_a_department_that_does_not_own_the_tool_may_not_quote_it(
        client, session_factory, seed, weighing):
    auth = await _member(client, session_factory, seed, weighing["dev"],
                         "wdev@test.io")
    res = await client.put(_url(weighing), json={"weight_g": 100.0}, headers=auth)
    assert res.status_code == 403
    assert "Tool Engineer" in res.json()["detail"]


async def test_the_weight_is_quoted_in_costing_only(
        client, admin_auth, session_factory, seed, weighing):
    auth = await _member(client, session_factory, seed, weighing["tool"],
                         "wtool2@test.io")
    await _set_status(session_factory, weighing["change_id"], "in_assessment")

    res = await client.put(_url(weighing), json={"weight_g": 100.0}, headers=auth)
    assert res.status_code == 400
    assert "costing" in res.json()["detail"]
    # Admins fill numbers in after the fact and are not held to the window.
    late = await client.put(_url(weighing), json={"weight_g": 100.0},
                            headers=admin_auth)
    assert late.status_code == 200, late.text


async def test_a_weight_must_be_a_real_number(client, admin_auth, weighing):
    for value in (0, -5):
        res = await client.put(_url(weighing), json={"weight_g": value},
                               headers=admin_auth)
        assert res.status_code == 422, res.text


# --- editing ----------------------------------------------------------------

async def test_re_quoting_overwrites_and_both_values_survive_in_the_changelog(
        client, session_factory, seed, weighing):
    auth = await _member(client, session_factory, seed, weighing["tool"],
                         "wtool3@test.io")
    await client.put(_url(weighing), json={"weight_g": 800.0}, headers=auth)
    res = await client.put(_url(weighing), json={"weight_g": 910.25}, headers=auth)
    assert res.status_code == 200, res.text
    assert res.json()["estimated_part_weight_g"] == 910.25

    log = (await client.get(
        f"/api/v1/changes/{weighing['change_id']}/changelog", headers=auth)).json()
    entries = [e for e in log if e["action"] == "weight_estimated"]
    assert len(entries) == 2
    assert "800" in entries[0]["action_description"]
    # The correction says what it replaced, so the delta discussion at
    # validation is against a value nobody has to reconstruct.
    assert "910.25" in entries[1]["action_description"]
    assert "was 800 g" in entries[1]["action_description"]


async def test_null_withdraws_the_estimate_and_says_so(
        client, session_factory, seed, weighing):
    """The frontend clears the field on blur. An empty field means "I no
    longer stand behind that number", not "0 g"."""
    auth = await _member(client, session_factory, seed, weighing["tool"],
                         "wtool5@test.io")
    await client.put(_url(weighing), json={"weight_g": 640.0}, headers=auth)

    res = await client.put(_url(weighing), json={"weight_g": None}, headers=auth)
    assert res.status_code == 200, res.text
    body = res.json()
    # Nobody vouches for an absent value, so the stamp goes with it.
    assert body["estimated_part_weight_g"] is None
    assert body["estimated_weight_by"] is None
    assert body["estimated_weight_at"] is None

    log = (await client.get(
        f"/api/v1/changes/{weighing['change_id']}/changelog", headers=auth)).json()
    cleared = [e for e in log if e["action"] == "weight_estimate_cleared"]
    assert len(cleared) == 1
    assert "was 640 g" in cleared[0]["action_description"]

    # And it can be quoted again afterwards.
    again = await client.put(_url(weighing), json={"weight_g": 655.0}, headers=auth)
    assert again.json()["estimated_part_weight_g"] == 655.0


async def test_clearing_an_empty_estimate_writes_no_history(
        client, session_factory, seed, weighing):
    auth = await _member(client, session_factory, seed, weighing["tool"],
                         "wtool6@test.io")
    res = await client.put(_url(weighing), json={"weight_g": None}, headers=auth)
    assert res.status_code == 200, res.text
    log = (await client.get(
        f"/api/v1/changes/{weighing['change_id']}/changelog", headers=auth)).json()
    assert [e for e in log if e["action"].startswith("weight_")] == []


# --- where it is read -------------------------------------------------------

async def test_the_estimate_is_served_on_the_detail_and_the_summation(
        client, admin_auth, session_factory, seed, weighing):
    auth = await _member(client, session_factory, seed, weighing["tool"],
                         "wtool4@test.io")
    await client.put(_url(weighing), json={"weight_g": 1234.5}, headers=auth)

    detail = await client.get(f"/api/v1/changes/{weighing['change_id']}",
                              headers=admin_auth)
    assert detail.status_code == 200, detail.text
    assert detail.json()["estimated_part_weight_g"] == 1234.5
    assert detail.json()["estimated_weight_by_name"] == "wtool4@test.io"

    # Sales prices the weight change off the same wrap-up as the costs.
    summation = await client.get(
        f"/api/v1/changes/{weighing['change_id']}/summation", headers=admin_auth)
    assert summation.status_code == 200, summation.text
    assert summation.json()["part_weight_estimate_g"] == 1234.5


async def test_an_unquoted_weight_is_absent_rather_than_zero(
        client, admin_auth, weighing):
    """Nobody has weighed anything yet, and 0 g would read as a claim."""
    summation = await client.get(
        f"/api/v1/changes/{weighing['change_id']}/summation", headers=admin_auth)
    assert summation.json()["part_weight_estimate_g"] is None
    detail = await client.get(f"/api/v1/changes/{weighing['change_id']}",
                              headers=admin_auth)
    assert detail.json()["estimated_part_weight_g"] is None
