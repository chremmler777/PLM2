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
    assert detail.startswith("Checklist incomplete, unanswered: ")
    assert "Spare part required" in detail and "Scrap increase" in detail


async def test_empty_checklist_is_refused(client, admin_auth, tab):
    res = await _submit(client, admin_auth, tab, {"impacts": []})
    assert res.status_code == 400


async def test_keyed_row_without_answer_counts_as_unanswered(client, admin_auth, tab):
    impacts = answered(DEPT)
    del impacts[0]["answer"]
    res = await _submit(client, admin_auth, tab, {"impacts": impacts})
    assert res.status_code == 400
    assert "Work instruction / document update" in res.json()["detail"]


async def test_invalid_answer_is_refused(client, admin_auth, tab):
    impacts = answered(DEPT)
    impacts[0]["answer"] = "maybe"
    res = await _submit(client, admin_auth, tab, {"impacts": impacts})
    assert res.status_code == 400


async def test_complete_checklist_is_accepted_and_no_rows_are_kept(
        client, admin_auth, tab, session_factory):
    res = await _submit(client, admin_auth, tab,
                        {"impacts": answered(DEPT, yes={"tool_modification"})})
    assert res.status_code == 200, res.text
    stored = await _stored(session_factory, tab)
    assert len(stored["impacts"]) == 10
    tool = next(e for e in stored["impacts"] if e["key"] == "tool_modification")
    assert tool == {"key": "tool_modification", "answer": "yes", "impacted": True}
    assert sum(1 for e in stored["impacts"] if e["answer"] == "no") == 9


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


async def test_free_lines_alone_do_not_skip_the_gate(client, admin_auth, tab):
    """A new free line carries an answer — it is not a legacy row, so it
    cannot stand in for the keyed rows nobody answered."""
    res = await _submit(client, admin_auth, tab, {"impacts": [
        {"label": "Foo", "answer": "yes", "impacted": True}]})
    assert res.status_code == 400
    assert res.json()["detail"].startswith("Checklist incomplete")


async def test_rest_to_no_mark_is_kept(client, admin_auth, tab, session_factory):
    """Rows answered by "Rest → No" keep their mark so reviewers can tell."""
    impacts = answered(DEPT)
    impacts[3]["bulk"] = True
    res = await _submit(client, admin_auth, tab, {"impacts": impacts})
    assert res.status_code == 200, res.text
    stored = await _stored(session_factory, tab)
    assert stored["impacts"][3]["bulk"] is True
    assert sum(1 for e in stored["impacts"] if e.get("bulk")) == 1


async def test_an_answer_stored_on_the_old_checklist_resubmits_as_it_is(
        client, admin_auth, tab, session_factory):
    """Item 4: the 13 common items before 2026-09-25 are legacy keys. An
    assessment started on that checklist (its answers carry a key only the
    old set asked) is complete on the set it was started with; answering the
    new rows as well is accepted too."""
    from app.services import assessment_checklist as checklist
    old = [{"key": k[0], "answer": "no", "impacted": False}
           for k in checklist.LEGACY_ITEMS]
    res = await _submit(client, admin_auth, tab,
                        {"impacts": old + answered(DEPT)})
    assert res.status_code == 200, res.text
    stored = await _stored(session_factory, tab)
    assert {e["key"] for e in stored["impacts"]} >= {"cycle_time_change", "threed_change"}


async def test_an_in_flight_resubmit_on_the_full_legacy_set_passes(
        client, admin_auth, tab):
    """Review finding 3: a draft or resubmit carrying exactly the earlier
    13-item checklist is not refused for the rows the new checklist added."""
    from app.services import assessment_checklist as checklist
    old = [{"key": k[0], "answer": "no"} for k in checklist.LEGACY_ITEMS]
    res = await _submit(client, admin_auth, tab, {"impacts": old})
    assert res.status_code == 200, res.text


async def test_a_partial_legacy_set_names_the_legacy_rows_still_open(
        client, admin_auth, tab):
    from app.services import assessment_checklist as checklist
    old = [{"key": k[0], "answer": "no"} for k in checklist.LEGACY_ITEMS
           if k[0] != "matching_required"]
    res = await _submit(client, admin_auth, tab, {"impacts": old})
    assert res.status_code == 400
    assert "Matching/sampling required" in res.json()["detail"]
    # The new rows are not demanded of an assessment started on the old set.
    assert "Moldflow simulation" not in res.json()["detail"]


async def test_a_legacy_draft_on_the_row_marks_the_assessment_as_legacy():
    """Detection also reads what is stored on the row: a kept draft with a
    legacy-only key makes the old set the one the answer is judged by."""
    from app.services.change_service import ChangeService
    stored = {"draft": {"data": {"details": {"impacts": [
        {"key": "threed_change", "answer": "no"}]}}}}
    assert ChangeService._started_on_legacy_checklist("Tool Engineer", [], stored)
    assert not ChangeService._started_on_legacy_checklist(
        "Tool Engineer", answered(DEPT), {})


async def test_a_new_assessment_owes_the_new_checklist(client, admin_auth, tab):
    """No legacy key anywhere: the current department checklist is owed."""
    res = await _submit(client, admin_auth, tab, {"impacts": [
        {"key": "work_instruction_update", "answer": "no"}]})
    assert res.status_code == 400
    assert "Moldflow simulation" in res.json()["detail"]


async def test_every_department_list_is_well_formed():
    from app.services import assessment_checklist as checklist
    common = [i[0] for i in checklist.COMMON_ITEMS]
    assert len(common) == 4
    for dept in ("Development", "Tool Engineer", "Manufacturing Engineer",
                 "Process Engineer", "APQP", "Packaging Engineer", "Quality",
                 "Scheduling", "Sales", "Project Manager", "Finance"):
        keys = [i["key"] for i in checklist.items_for(dept)]
        assert keys[:4] == common, dept
        assert len(keys) > 4 and len(keys) == len(set(keys)), dept
    assert checklist.label_for("cycle_time_change", "Sales") == "Cycle time change"
    assert "cycle_time_change" in checklist.accepted_keys_for("Sales")
    assert "cycle_time_change" not in checklist.keys_for("Sales")
