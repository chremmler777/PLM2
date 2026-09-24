"""Every checklist row is answered before a department can submit."""
import json
import pytest

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.workflow import Department
from tests.checklist_helpers import answered

pytestmark = pytest.mark.asyncio
DEPT = "Tool Engineer"


@pytest.fixture
async def tab(session_factory, seed):
    async with session_factory() as s:
        dept = Department(name=DEPT, flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        change = ChangeRequest(
            change_number="C-ANS-1", title="answers", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="in_assessment")
        s.add(change)
        await s.flush()
        a = ChangeAssessment(change_id=change.id, department_id=dept.id, stage_order=1)
        s.add(a)
        await s.commit()
        return {"change_id": change.id, "assessment_id": a.id, "department_id": dept.id}


async def _submit(client, auth, tab, details):
    return await client.post(f"/api/v1/changes/{tab['change_id']}/assessments",
                             json={"department_id": tab["department_id"],
                                   "verdict": "feasible", "details": details},
                             headers=auth)


async def _stored(session_factory, tab):
    async with session_factory() as s:
        a = await s.get(ChangeAssessment, tab["assessment_id"])
        return json.loads(a.details)


async def test_incomplete_checklist_is_refused_naming_the_rows(client, admin_auth, tab):
    impacts = answered(DEPT)[:-2]           # last two rows unanswered
    res = await _submit(client, admin_auth, tab, {"impacts": impacts})
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail.startswith("Checklist incomplete — unanswered: ")
    assert "Prototyping required" in detail and "Matching/sampling required" in detail


async def test_empty_checklist_is_refused(client, admin_auth, tab):
    res = await _submit(client, admin_auth, tab, {"impacts": []})
    assert res.status_code == 400


async def test_keyed_row_without_answer_counts_as_unanswered(client, admin_auth, tab):
    impacts = answered(DEPT)
    del impacts[0]["answer"]
    res = await _submit(client, admin_auth, tab, {"impacts": impacts})
    assert res.status_code == 400
    assert "Cycle time change" in res.json()["detail"]


async def test_invalid_answer_is_refused(client, admin_auth, tab):
    impacts = answered(DEPT)
    impacts[0]["answer"] = "maybe"
    res = await _submit(client, admin_auth, tab, {"impacts": impacts})
    assert res.status_code == 400


async def test_complete_checklist_is_accepted_and_no_rows_are_kept(
        client, admin_auth, tab, session_factory):
    res = await _submit(client, admin_auth, tab,
                        {"impacts": answered(DEPT, yes={"threed_change"})})
    assert res.status_code == 200, res.text
    stored = await _stored(session_factory, tab)
    assert len(stored["impacts"]) == 13
    three = next(e for e in stored["impacts"] if e["key"] == "threed_change")
    assert three == {"key": "threed_change", "answer": "yes", "impacted": True}
    assert sum(1 for e in stored["impacts"] if e["answer"] == "no") == 12


async def test_impacted_is_normalised_from_answer(client, admin_auth, tab, session_factory):
    impacts = answered(DEPT)
    impacts[0].update(answer="yes", impacted=False)      # contradicting client
    impacts[1].update(answer="no", impacted=True)
    res = await _submit(client, admin_auth, tab, {"impacts": impacts})
    assert res.status_code == 200, res.text
    stored = await _stored(session_factory, tab)
    assert stored["impacts"][0]["impacted"] is True
    assert stored["impacts"][1]["impacted"] is False


async def test_not_impacted_questionnaire_is_exempt(client, admin_auth, tab):
    res = await _submit(client, admin_auth, tab,
                        {"impacted": False, "impacts": [answered(DEPT)[0]]})
    assert res.status_code == 200, res.text


async def test_submit_without_details_is_unchanged(client, admin_auth, tab):
    res = await client.post(f"/api/v1/changes/{tab['change_id']}/assessments",
                            json={"department_id": tab["department_id"],
                                  "verdict": "feasible"}, headers=admin_auth)
    assert res.status_code == 200, res.text


async def test_legacy_only_rows_are_not_gated(client, admin_auth, tab):
    res = await _submit(client, admin_auth, tab,
                        {"impacts": [{"label": "Old free line", "impacted": True}]})
    assert res.status_code == 200, res.text


async def test_free_lines_are_yes(client, admin_auth, tab, session_factory):
    impacts = answered(DEPT) + [{"label": "Hot runner: zone 3", "answer": "yes",
                                 "impacted": True}]
    res = await _submit(client, admin_auth, tab, {"impacts": impacts})
    assert res.status_code == 200, res.text
    stored = await _stored(session_factory, tab)
    free = next(e for e in stored["impacts"] if e.get("label") == "Hot runner: zone 3")
    assert free["impacted"] is True and free["answer"] == "yes"
