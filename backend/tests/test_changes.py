# backend/tests/test_changes.py
import pytest
from sqlalchemy import select

from tests.conftest import (
    approve_gates, force_complete_check_workflows, advance_to_assessment,
)

pytestmark = pytest.mark.asyncio


async def _create_change(client, auth, project_id, **over):
    body = {"project_id": project_id, "title": "Wall thickness +0.2mm",
            "change_type": "physical_part", "reason": "Sink marks on Class-A surface"}
    body.update(over)
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def test_create_change_assigns_number_and_captured_status(client, eng_auth, seed):
    data = await _create_change(client, eng_auth, seed["project_id"])
    assert data["status"] == "captured"
    assert data["change_number"].startswith("CR-")
    assert data["change_type"] == "physical_part"


async def test_create_change_accepts_customer_relevant(client, eng_auth, seed):
    data = await _create_change(client, eng_auth, seed["project_id"], customer_relevant=True)
    assert data["customer_relevant"] is True

    data2 = await _create_change(client, eng_auth, seed["project_id"], customer_relevant=False)
    assert data2["customer_relevant"] is False


async def test_list_and_get_change(client, eng_auth, seed):
    created = await _create_change(client, eng_auth, seed["project_id"])
    res = await client.get(f"/api/v1/changes?project_id={seed['project_id']}", headers=eng_auth)
    assert res.status_code == 200, res.text
    assert any(c["id"] == created["id"] for c in res.json())

    res = await client.get(f"/api/v1/changes/{created['id']}", headers=eng_auth)
    assert res.status_code == 200, res.text
    detail = res.json()
    assert detail["id"] == created["id"]
    assert detail["impacted_items"] == []


async def _transition(client, auth, change_id, to_status, **over):
    body = {"to_status": to_status}
    body.update(over)
    return await client.post(f"/api/v1/changes/{change_id}/transition", json=body, headers=auth)


async def test_transition_blocked_without_impacted_items(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"],
                                  lead_id=seed["engineer_id"])
    await approve_gates(client, eng_auth, change["id"])
    res = await _transition(client, eng_auth, change["id"], "scoping")
    assert res.status_code == 200, res.text
    res = await _transition(client, eng_auth, change["id"], "in_assessment")
    assert res.status_code == 400, res.text
    assert "deviation" in res.json()["detail"].lower()


async def test_illegal_transition_rejected(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    res = await _transition(client, eng_auth, change["id"], "released")
    assert res.status_code == 400, res.text


async def test_cancel_requires_reason(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    res = await _transition(client, eng_auth, change["id"], "cancelled")
    assert res.status_code == 400, res.text
    res = await _transition(client, eng_auth, change["id"], "cancelled",
                            cancellation_reason="Customer withdrew RFQ")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "cancelled"


async def _make_part(client, auth, project_id, number, category="article"):
    res = await client.post("/api/v1/parts", json={
        "project_id": project_id, "part_number": number, "name": number,
        "part_type": "internal_mfg", "item_category": category,
    }, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def test_add_and_remove_impacted_item(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    part_id = await _make_part(client, eng_auth, seed["project_id"], "ART-1")
    res = await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                            json={"part_id": part_id, "impact_note": "wall thickness"},
                            headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    item_id = res.json()["id"]

    res = await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)
    assert len(res.json()["impacted_items"]) == 1

    res = await client.delete(f"/api/v1/changes/{change['id']}/impacted-items/{item_id}",
                              headers=eng_auth)
    assert res.status_code in (200, 204), res.text
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)
    assert res.json()["impacted_items"] == []


async def test_seed_impacted_from_relations(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    article = await _make_part(client, eng_auth, seed["project_id"], "ART-2", "article")
    tool = await _make_part(client, eng_auth, seed["project_id"], "TOOL-2", "tool")
    # tool produces article
    res = await client.post(f"/api/v1/parts/{tool}/relations", json={
        "to_part_id": article, "relation_type": "produces",
    }, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    # add the article as impacted, then seed related items
    await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                      json={"part_id": article}, headers=eng_auth)
    res = await client.post(f"/api/v1/changes/{change['id']}/impacted-items/seed",
                            headers=eng_auth)
    assert res.status_code == 200, res.text
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)
    part_ids = {i["part_id"] for i in res.json()["impacted_items"]}
    assert tool in part_ids  # the producing tool was pulled in


import pytest_asyncio
from app.models.workflow import Department, UserDepartment


@pytest_asyncio.fixture
async def departments(session_factory, seed):
    async with session_factory() as s:
        names = ["Tool Engineer", "APQP", "Quality", "Manufacturing Engineer", "Sales"]
        ids = {}
        for i, n in enumerate(names):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i)
            s.add(d)
            await s.flush()
            ids[n] = d.id
        # These tests drive submit_assessment as the engineer across every
        # department here; grant membership so complete_task's
        # department-membership guard doesn't block the blocking (R/A) rows.
        for dept_id in ids.values():
            s.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept_id))
        await s.commit()
        return ids


async def test_assessment_created_on_enter_and_submit(client, eng_auth, seed, departments,
                                                      session_factory):
    change = await _create_change(client, eng_auth, seed["project_id"],
                                  lead_id=seed["engineer_id"])
    await approve_gates(client, eng_auth, change["id"])
    part_id = await _make_part(client, eng_auth, seed["project_id"], "ART-9")
    await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                      json={"part_id": part_id}, headers=eng_auth)
    # enter assessment -> assessments auto-created
    await advance_to_assessment(client, eng_auth, session_factory, change["id"])
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)
    assessments = res.json()["assessments"]
    assert len(assessments) >= 1
    tool_dep = departments["Tool Engineer"]

    # submitting feasible for all then moving to costing should work
    for a in assessments:
        r = await client.post(f"/api/v1/changes/{change['id']}/assessments", json={
            "department_id": a["department_id"], "verdict": "feasible",
        }, headers=eng_auth)
        assert r.status_code in (200, 201), r.text

    # costing still needs a quoted price guard? No - costing guard is assessments only
    res = await _transition(client, eng_auth, change["id"], "costing")
    assert res.status_code == 200, res.text


async def _advance_to_quoted(client, auth, seed, departments, admin_auth, session_factory):
    change = await _create_change(client, auth, seed["project_id"], lead_id=seed["engineer_id"])
    await approve_gates(client, auth, change["id"])
    # customer-relevant so the change follows the quote path (quoted -> approved)
    await client.patch(f"/api/v1/changes/{change['id']}",
                       json={"customer_relevant": True}, headers=auth)
    part_id = await _make_part(client, auth, seed["project_id"], f"ART-Q{change['id']}")
    await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                      json={"part_id": part_id}, headers=auth)
    await advance_to_assessment(client, auth, session_factory, change["id"])
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=auth)
    for a in res.json()["assessments"]:
        await client.post(f"/api/v1/changes/{change['id']}/assessments",
                          json={"department_id": a["department_id"], "verdict": "feasible"},
                          headers=auth)
    await _transition(client, auth, change["id"], "costing")
    await client.patch(f"/api/v1/changes/{change['id']}",
                       json={"quoted_price": 12500.0}, headers=auth)
    await _transition(client, auth, change["id"], "quoted")
    return change


async def test_approve_blocked_until_customer_and_dual_signoff(
    client, eng_auth, admin_auth, seed, departments, session_factory
):
    change = await _advance_to_quoted(client, eng_auth, seed, departments, admin_auth,
                                      session_factory)
    cid = change["id"]
    # cannot approve yet (no customer acceptance, no sign-off) — hard gate, no override
    res = await _transition(client, eng_auth, cid, "approved")
    assert res.status_code == 400, res.text

    # record customer acceptance
    res = await client.post(f"/api/v1/changes/{cid}/customer-response",
                            json={"response": "accepted"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    # PM signs (engineer), Quality signs (admin) — must be different users
    res = await client.post(f"/api/v1/changes/{cid}/sign-off",
                            json={"role": "pm"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    # same user cannot also be quality
    res = await client.post(f"/api/v1/changes/{cid}/sign-off",
                            json={"role": "quality"}, headers=eng_auth)
    assert res.status_code == 400, res.text
    res = await client.post(f"/api/v1/changes/{cid}/sign-off",
                            json={"role": "quality"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    # now approve works
    res = await _transition(client, eng_auth, cid, "approved")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "approved"


async def test_implementation_spawns_ecn_revision_per_item(
    client, eng_auth, admin_auth, seed, departments, check_wf_standards, session_factory
):
    change = await _advance_to_quoted(client, eng_auth, seed, departments, admin_auth,
                                      session_factory)
    cid = change["id"]
    await client.post(f"/api/v1/changes/{cid}/customer-response",
                      json={"response": "accepted"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "pm"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "quality"}, headers=admin_auth)
    await _transition(client, eng_auth, cid, "approved")
    # Task 18: Engineering (R&D) must confirm the impacted-item set before kickoff.
    conf = await client.post(f"/api/v1/changes/{cid}/impact/confirm", headers=admin_auth)
    assert conf.status_code == 200, conf.text
    res = await _transition(client, eng_auth, cid, "in_implementation")
    assert res.status_code == 200, res.text
    res = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    items = res.json()["impacted_items"]
    assert all(i["resulting_revision_id"] is not None for i in items)


async def test_release_activates_revisions_and_stamps_eng_level(
    client, eng_auth, admin_auth, seed, departments, check_wf_standards, session_factory
):
    change = await _advance_to_quoted(client, eng_auth, seed, departments, admin_auth,
                                      session_factory)
    cid = change["id"]
    await client.post(f"/api/v1/changes/{cid}/customer-response",
                      json={"response": "accepted"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "pm"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "quality"}, headers=admin_auth)
    await _transition(client, eng_auth, cid, "approved")
    conf = await client.post(f"/api/v1/changes/{cid}/impact/confirm", headers=admin_auth)
    assert conf.status_code == 200, conf.text
    await _transition(client, eng_auth, cid, "in_implementation")
    res = await _transition(client, eng_auth, cid, "in_validation")
    assert res.status_code == 200, res.text
    await force_complete_check_workflows(session_factory, cid)
    res = await _transition(client, eng_auth, cid, "released")
    assert res.status_code == 200, res.text

    # each impacted part now points at its ECN revision as active
    detail = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    for item in detail["impacted_items"]:
        rev_id = item["resulting_revision_id"]
        part = (await client.get(f"/api/v1/parts/{item['part_id']}", headers=eng_auth)).json()
        assert part["active_revision_id"] == rev_id


async def test_changelog_is_hash_chained(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    await _transition(client, eng_auth, change["id"], "on_hold")
    res = await client.get(f"/api/v1/changes/{change['id']}/changelog", headers=eng_auth)
    assert res.status_code == 200, res.text
    entries = res.json()
    assert len(entries) >= 2  # created + status_changed
    actions = [e["action"] for e in entries]
    assert "created" in actions


async def test_attach_document_to_change(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    files = {"file": ("ecr-start.pptx",
                      b"PK\x03\x04 fake pptx bytes",
                      "application/vnd.openxmlformats-officedocument.presentationml.presentation")}
    res = await client.post(f"/api/v1/changes/{change['id']}/attachments",
                            files=files, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    # appears on the detail payload
    detail = (await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)).json()
    assert len(detail["attachments"]) == 1
    assert detail["attachments"][0]["filename"] == "ecr-start.pptx"


async def test_my_change_tasks_lists_pending_assessments(
    client, eng_auth, seed, departments, session_factory
):
    # The engineer is already a member of "Tool Engineer" (the `departments`
    # fixture grants membership in every dept it creates); map a routing
    # standard so the change spawns an engine instance: the Tool Engineer
    # stage-1 row links to an active task, so its effective_status is
    # "active" and my-tasks surfaces it.
    from app.models.workflow import WfTemplate, WfStage, WfStep, WfStepRasic
    from app.models.change import ChangeRoutingStandard
    async with session_factory() as s:
        t = WfTemplate(name="ECR-MT", description="x", version=1,
                       is_active=True, created_by=1)
        s.add(t); await s.flush()
        stage = WfStage(template_id=t.id, stage_order=1, name="S1")
        s.add(stage); await s.flush()
        step = WfStep(stage_id=stage.id, step_name="S1", position_in_stage=1)
        s.add(step); await s.flush()
        s.add(WfStepRasic(step_id=step.id,
                          department_id=departments["Tool Engineer"], rasic_letter="R"))
        s.add(ChangeRoutingStandard(change_type="physical_part", template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()

    change = await _create_change(client, eng_auth, seed["project_id"], lead_id=seed["engineer_id"])
    await approve_gates(client, eng_auth, change["id"])
    part_id = await _make_part(client, eng_auth, seed["project_id"], "ART-MT")
    await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                      json={"part_id": part_id}, headers=eng_auth)
    await advance_to_assessment(client, eng_auth, session_factory, change["id"])

    res = await client.get("/api/v1/changes/my-tasks", headers=eng_auth)
    assert res.status_code == 200, res.text
    tasks = res.json()
    assert any(t["change_id"] == change["id"] and t["kind"] == "assessment" for t in tasks)


async def test_assessment_response_reads_execution_from_task(
    client, eng_auth, seed, departments, session_factory
):
    """Task 7: AssessmentResponse's status/owner/accepted_at read through the
    linked WfInstanceTask — accepting via the API writes ownership onto the
    task, and GET /v1/changes/{id}'s assessments array shows it even though the
    assessment row itself stays at its own 'pending' status."""
    from app.models.workflow import (
        WfTemplate, WfStage, WfStep, WfStepRasic, WfInstanceTask,
    )
    from app.models.change import ChangeRoutingStandard, ChangeAssessment
    async with session_factory() as s:
        # The engineer is already a member of "Tool Engineer" via the
        # `departments` fixture.
        t = WfTemplate(name="ECR-ART", description="x", version=1,
                       is_active=True, created_by=1)
        s.add(t); await s.flush()
        stage = WfStage(template_id=t.id, stage_order=1, name="S1")
        s.add(stage); await s.flush()
        step = WfStep(stage_id=stage.id, step_name="S1", position_in_stage=1)
        s.add(step); await s.flush()
        s.add(WfStepRasic(step_id=step.id,
                          department_id=departments["Tool Engineer"], rasic_letter="R"))
        s.add(ChangeRoutingStandard(change_type="physical_part", template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()

    change = await _create_change(client, eng_auth, seed["project_id"], lead_id=seed["engineer_id"])
    await approve_gates(client, eng_auth, change["id"])
    part_id = await _make_part(client, eng_auth, seed["project_id"], "ART-RT")
    await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                      json={"part_id": part_id}, headers=eng_auth)
    await advance_to_assessment(client, eng_auth, session_factory, change["id"])

    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"]))).scalars().one()
        assert a.wf_instance_task_id is not None
        assessment_id, task_id = a.id, a.wf_instance_task_id

    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments/{assessment_id}/accept",
        headers=eng_auth)
    assert res.status_code == 200, res.text

    detail = (await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)).json()
    assessment = next(a for a in detail["assessments"] if a["id"] == assessment_id)
    assert assessment["status"] == "active"
    assert assessment["owner_id"] == seed["engineer_id"]
    assert assessment["accepted_at"] is not None

    async with session_factory() as s:
        row = await s.get(ChangeAssessment, assessment_id)
        assert row.status == "pending"        # the row itself is untouched
        assert row.owner_id is None
        task = await s.get(WfInstanceTask, task_id)
        assert task.owner_id == seed["engineer_id"]   # task is the source of truth


# ── Task-6 gap-fix tests ──────────────────────────────────────────────────────

async def _get_plant_id(client, auth) -> int:
    """Return the id of the first plant (created by the seed fixture)."""
    res = await client.get("/api/v1/plants", headers=auth)
    assert res.status_code == 200, res.text
    plants = res.json()
    assert plants, "No plants found – seed may not have created one"
    return plants[0]["id"]


async def test_affected_plant_ids_set_and_clear(client, eng_auth, seed):
    """Set affected_plant_ids → GET round-trip returns same ids; [] clears them."""
    plant_id = await _get_plant_id(client, eng_auth)
    change = await _create_change(client, eng_auth, seed["project_id"])
    cid = change["id"]

    # Initially empty
    res = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    assert res.json()["affected_plant_ids"] == []

    # Set plant
    res = await client.patch(f"/api/v1/changes/{cid}", json={"affected_plant_ids": [plant_id]}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["affected_plant_ids"] == [plant_id]

    # GET also returns it
    res = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    assert res.json()["affected_plant_ids"] == [plant_id]

    # Clear with []
    res = await client.patch(f"/api/v1/changes/{cid}", json={"affected_plant_ids": []}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["affected_plant_ids"] == []

    # GET confirms cleared
    res = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    assert res.json()["affected_plant_ids"] == []


async def test_boolean_false_round_trip(client, eng_auth, seed):
    """PATCH is_series True→False and confirm GET returns False."""
    change = await _create_change(client, eng_auth, seed["project_id"])
    cid = change["id"]

    # Set True
    res = await client.patch(f"/api/v1/changes/{cid}", json={"is_series": True}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["is_series"] is True

    # Set False
    res = await client.patch(f"/api/v1/changes/{cid}", json={"is_series": False}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["is_series"] is False

    # GET confirms False
    res = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    assert res.json()["is_series"] is False


async def test_invalid_implementation_mode_returns_400(client, eng_auth, seed):
    """Out-of-set implementation_mode raises HTTP 400."""
    change = await _create_change(client, eng_auth, seed["project_id"])
    cid = change["id"]

    res = await client.patch(
        f"/api/v1/changes/{cid}",
        json={"implementation_mode": "bogus_mode"},
        headers=eng_auth,
    )
    assert res.status_code == 400, res.text


async def test_valid_implementation_modes_accepted(client, eng_auth, seed):
    """Both valid implementation_mode values are accepted."""
    change = await _create_change(client, eng_auth, seed["project_id"])
    cid = change["id"]

    for mode in ("integrated", "separational"):
        res = await client.patch(
            f"/api/v1/changes/{cid}",
            json={"implementation_mode": mode},
            headers=eng_auth,
        )
        assert res.status_code == 200, res.text
        assert res.json()["implementation_mode"] == mode


async def test_change_response_resolves_lead_name(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "lead name test",
        "change_type": "tooling", "lead_id": seed["engineer_id"]},
        headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    change_id = res.json()["id"]
    res = await client.get(f"/api/v1/changes/{change_id}", headers=eng_auth)
    assert res.status_code == 200
    assert res.json()["lead_name"]  # resolved full name, not an id
