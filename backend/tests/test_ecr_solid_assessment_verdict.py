"""ECR-solid spec §4 verdict (switch ASSESSMENT_V2): nothing preselected;
impact yes -> each Yes says what changes and its evidence; impact no -> the
department's checklist with a reference per No row; Feasible if... names the
condition."""
import pytest

from app.models.change import ChangeAssessment, ChangeRequest
from app.services import cm_switches
from tests.checklist_helpers import answered
from tests.conftest import login, make_department_member

pytestmark = pytest.mark.asyncio
DEPT = "Tool Engineer"


@pytest.fixture
async def tab(client, session_factory, seed):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username="av-te", email="av-te@test.io",
                 full_name="AV te", hashed_password=get_password_hash("av-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        uid = u.id
    dept = await make_department_member(session_factory, uid, DEPT)
    async with session_factory() as s:
        change = ChangeRequest(
            change_number="C-AV-1", title="verdict", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"], status="in_assessment")
        s.add(change)
        await s.flush()
        s.add(ChangeAssessment(change_id=change.id, department_id=dept,
                               stage_order=1, rasic_letter="R"))
        await s.commit()
        cid = change.id
    return {"cid": cid, "dept": dept, "auth": await login(client, "av-te@test.io")}


async def _submit(client, tab, impacts, verdict="feasible", **extra):
    return await client.post(f"/api/v1/changes/{tab['cid']}/assessments", json={
        "department_id": tab["dept"], "verdict": verdict,
        "details": {"impacts": impacts}, **extra}, headers=tab["auth"])


async def test_impact_no_needs_a_reference_per_row(client, tab):
    # negative: every row No, none with a reference
    res = await _submit(client, tab, answered(DEPT, refs=False))
    assert res.status_code == 400
    assert "Impact no: give each No its reference" in res.json()["detail"]
    # negative: a reference that says nothing
    rows = answered(DEPT)
    rows[0]["ref"] = "ok"
    res = await _submit(client, tab, rows)
    assert res.status_code == 400 and "reference" in res.json()["detail"]
    res = await _submit(client, tab, answered(DEPT))
    assert res.status_code == 200, res.text


async def test_impact_yes_needs_what_and_evidence_per_yes(client, tab):
    rows = answered(DEPT, yes={"tool_modification"}, refs=False)
    res = await _submit(client, tab, rows)
    assert res.status_code == 400
    assert "Impact yes" in res.json()["detail"]
    # the No rows owe no reference once something is impacted
    rows = answered(DEPT, yes={"tool_modification"},
                    remarks={"tool_modification": "insert 3 re-cut, DRW-4471 rev C"},
                    refs=False)
    res = await _submit(client, tab, rows)
    assert res.status_code == 200, res.text


async def test_feasible_if_names_the_condition(client, tab):
    res = await _submit(client, tab, answered(DEPT), verdict="feasible_with_conditions")
    assert res.status_code == 400 and "say the condition" in res.json()["detail"]
    res = await _submit(client, tab, answered(DEPT), verdict="feasible_with_conditions",
                        conditions="if the tool is free in week 44")
    assert res.status_code == 200, res.text


async def test_switch_off_takes_the_bare_checklist(client, tab, monkeypatch):
    monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
    res = await _submit(client, tab, answered(DEPT, refs=False))
    assert res.status_code == 200, res.text
