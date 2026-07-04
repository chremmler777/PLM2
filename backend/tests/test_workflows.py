"""End-to-end multi-department workflow tests.

Builds a two-stage RASIC template (Engineering -> Quality, with Sales
informed) and drives instances through approval, rejection, and queue
visibility per department.
"""
import pytest_asyncio

from app.models.workflow import (
    Department, WfTemplate, WfStage, WfStep, WfStepRasic, UserDepartment)


@pytest_asyncio.fixture
async def wf_template(session_factory, seed):
    """Two-stage template: S1 'Feasibility' (Engineering R, Sales I),
    S2 'Release' (Quality A, Sales I). Returns ids."""
    async with session_factory() as s:
        eng = Department(name="Engineering", flow_type="action", sort_order=1)
        quality = Department(name="Quality", flow_type="action", sort_order=2)
        sales = Department(name="Sales", flow_type="info", sort_order=3)
        s.add_all([eng, quality, sales])
        await s.flush()

        template = WfTemplate(name="Release Flow", is_active=True, created_by=seed["admin_id"])
        s.add(template)
        await s.flush()

        s1 = WfStage(template_id=template.id, stage_order=1, name="Feasibility")
        s2 = WfStage(template_id=template.id, stage_order=2, name="Release")
        s.add_all([s1, s2])
        await s.flush()

        step1 = WfStep(stage_id=s1.id, step_name="Check design", position_in_stage=1)
        step2 = WfStep(stage_id=s2.id, step_name="Final release", position_in_stage=1)
        s.add_all([step1, step2])
        await s.flush()

        s.add_all([
            WfStepRasic(step_id=step1.id, department_id=eng.id, rasic_letter="R"),
            WfStepRasic(step_id=step1.id, department_id=sales.id, rasic_letter="I"),
            WfStepRasic(step_id=step2.id, department_id=quality.id, rasic_letter="A"),
            WfStepRasic(step_id=step2.id, department_id=sales.id, rasic_letter="I"),
        ])
        await s.commit()

        return {
            "template_id": template.id,
            "eng_id": eng.id,
            "quality_id": quality.id,
            "sales_id": sales.id,
        }


async def _start(client, auth, revision_id, template_id):
    res = await client.post(
        f"/api/v1/workflow-instances/revisions/{revision_id}/start",
        json={"template_id": template_id},
        headers=auth,
    )
    assert res.status_code == 201, res.text
    return res.json()


def _tasks_by_dept(instance, dept_id, stage=None):
    return [
        t for t in instance["tasks"]
        if t["department_id"] == dept_id and (stage is None or t["stage_order"] == stage)
    ]


async def _grant(session_factory, user_id, *dept_ids):
    """Direct-DB membership grant for tests that complete tasks as a
    non-admin — complete_task's department-membership guard requires it."""
    async with session_factory() as s:
        s.add_all([UserDepartment(user_id=user_id, department_id=d) for d in dept_ids])
        await s.commit()


async def test_full_approval_chain_across_departments(
        client, eng_auth, part, wf_template, seed, session_factory):
    await _grant(session_factory, seed["engineer_id"],
                 wf_template["eng_id"], wf_template["quality_id"])
    rid = part["revision_id"]
    inst = await _start(client, eng_auth, rid, wf_template["template_id"])

    assert inst["status"] == "active"
    assert inst["current_stage_order"] == 1

    # Stage 1: Engineering is actionable, Sales only informed
    eng_tasks = _tasks_by_dept(inst, wf_template["eng_id"], stage=1)
    sales_tasks = _tasks_by_dept(inst, wf_template["sales_id"], stage=1)
    assert len(eng_tasks) == 1 and eng_tasks[0]["is_actionable"] is True
    assert eng_tasks[0]["status"] == "active"
    assert sales_tasks[0]["is_actionable"] is False
    assert sales_tasks[0]["status"] == "noted"

    # Engineering approves -> auto-advance to stage 2 with Quality active
    res = await client.post(
        f"/api/v1/workflow-instances/{inst['id']}/tasks/{eng_tasks[0]['id']}/complete",
        json={"decision": "approved", "notes": "design ok"},
        headers=eng_auth,
    )
    assert res.status_code == 200, res.text
    inst = res.json()
    assert inst["status"] == "active"
    assert inst["current_stage_order"] == 2
    quality_tasks = _tasks_by_dept(inst, wf_template["quality_id"], stage=2)
    assert quality_tasks[0]["status"] == "active"

    # Quality approves -> workflow completed
    res = await client.post(
        f"/api/v1/workflow-instances/{inst['id']}/tasks/{quality_tasks[0]['id']}/complete",
        json={"decision": "approved"},
        headers=eng_auth,
    )
    inst = res.json()
    assert inst["status"] == "completed"
    assert inst["completed_at"] is not None


async def test_rejection_stops_workflow(
        client, eng_auth, part, wf_template, seed, session_factory):
    await _grant(session_factory, seed["engineer_id"], wf_template["eng_id"])
    rid = part["revision_id"]
    inst = await _start(client, eng_auth, rid, wf_template["template_id"])
    eng_task = _tasks_by_dept(inst, wf_template["eng_id"], stage=1)[0]

    res = await client.post(
        f"/api/v1/workflow-instances/{inst['id']}/tasks/{eng_task['id']}/complete",
        json={"decision": "rejected", "notes": "tolerances wrong"},
        headers=eng_auth,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"


async def test_duplicate_active_workflow_rejected(client, eng_auth, part, wf_template):
    rid = part["revision_id"]
    await _start(client, eng_auth, rid, wf_template["template_id"])
    res = await client.post(
        f"/api/v1/workflow-instances/revisions/{rid}/start",
        json={"template_id": wf_template["template_id"]},
        headers=eng_auth,
    )
    assert res.status_code == 400


async def test_department_queues_see_their_tasks(client, eng_auth, part, wf_template):
    rid = part["revision_id"]
    await _start(client, eng_auth, rid, wf_template["template_id"])

    # Engineering queue has the stage-1 task; Quality queue is empty until stage 2
    res = await client.get(
        f"/api/v1/workflow-instances/my-tasks?department_id={wf_template['eng_id']}",
        headers=eng_auth,
    )
    eng_queue = res.json()
    assert len(eng_queue) == 1
    assert eng_queue[0]["revision_id"] == rid
    assert eng_queue[0]["stage_name"] == "Feasibility"

    res = await client.get(
        f"/api/v1/workflow-instances/my-tasks?department_id={wf_template['quality_id']}",
        headers=eng_auth,
    )
    assert res.json() == []

    # Open-task badge counts the one actionable task
    res = await client.get("/api/v1/workflow-instances/open-task-count", headers=eng_auth)
    assert res.json()["count"] == 1


async def test_informed_task_cannot_be_completed(client, eng_auth, part, wf_template):
    rid = part["revision_id"]
    inst = await _start(client, eng_auth, rid, wf_template["template_id"])
    sales_task = _tasks_by_dept(inst, wf_template["sales_id"], stage=1)[0]

    res = await client.post(
        f"/api/v1/workflow-instances/{inst['id']}/tasks/{sales_task['id']}/complete",
        json={"decision": "approved"},
        headers=eng_auth,
    )
    assert res.status_code == 400


async def test_my_tasks_scoped_by_membership(client, eng_auth, admin_auth, part, wf_template, seed):
    """Without department_id, my-tasks uses the user's department memberships."""
    rid = part["revision_id"]
    await _start(client, eng_auth, rid, wf_template["template_id"])

    # No memberships -> empty queue and zero badge
    res = await client.get("/api/v1/workflow-instances/my-tasks", headers=eng_auth)
    assert res.json() == []

    # Admin assigns the engineer to Engineering
    res = await client.put(
        f"/api/v1/users/{seed['engineer_id']}/departments",
        json={"department_ids": [wf_template["eng_id"]]},
        headers=admin_auth,
    )
    assert res.status_code == 200
    assert [d["name"] for d in res.json()] == ["Engineering"]

    # Queue and badge now show the stage-1 Engineering task
    res = await client.get("/api/v1/workflow-instances/my-tasks", headers=eng_auth)
    assert len(res.json()) == 1
    assert res.json()[0]["department_name"] == "Engineering"

    res = await client.get("/api/v1/workflow-instances/open-task-count", headers=eng_auth)
    assert res.json()["count"] == 1

    # /me reports the membership
    res = await client.get("/api/v1/auth/me", headers=eng_auth)
    assert [d["name"] for d in res.json()["departments"]] == ["Engineering"]


async def test_set_departments_validates_ids(client, admin_auth, seed):
    res = await client.put(
        f"/api/v1/users/{seed['engineer_id']}/departments",
        json={"department_ids": [9999]},
        headers=admin_auth,
    )
    assert res.status_code == 400


async def test_workflow_notifications_fan_out(client, eng_auth, admin_auth, part, wf_template, seed):
    """Department members get notified on new stage tasks; the starter on completion."""
    rid = part["revision_id"]

    # Engineer is a member of Engineering; admin a member of Quality
    await client.put(
        f"/api/v1/users/{seed['engineer_id']}/departments",
        json={"department_ids": [wf_template["eng_id"]]},
        headers=admin_auth,
    )
    await client.put(
        f"/api/v1/users/{seed['admin_id']}/departments",
        json={"department_ids": [wf_template["quality_id"]]},
        headers=admin_auth,
    )

    inst = await _start(client, eng_auth, rid, wf_template["template_id"])

    # Stage-1 task notification reaches the engineer
    res = await client.get("/api/v1/notifications", headers=eng_auth)
    titles = [n["title"] for n in res.json()]
    assert any(t.startswith("Workflow task:") for t in titles)
    res = await client.get("/api/v1/notifications/unread-count", headers=eng_auth)
    assert res.json()["count"] >= 1

    # Approve stage 1 -> stage-2 notification reaches the admin (Quality member)
    eng_task = _tasks_by_dept(inst, wf_template["eng_id"], stage=1)[0]
    await client.post(
        f"/api/v1/workflow-instances/{inst['id']}/tasks/{eng_task['id']}/complete",
        json={"decision": "approved"},
        headers=eng_auth,
    )
    res = await client.get("/api/v1/notifications", headers=admin_auth)
    assert any(n["title"].startswith("Workflow task:") for n in res.json())

    # Approve stage 2 -> completion notification reaches the starter (engineer)
    res = await client.get(
        f"/api/v1/workflow-instances/revisions/{rid}/current", headers=eng_auth
    )
    quality_task = [
        t for t in res.json()["instance"]["tasks"]
        if t["stage_order"] == 2 and t["is_actionable"] and t["status"] == "active"
    ][0]
    await client.post(
        f"/api/v1/workflow-instances/{inst['id']}/tasks/{quality_task['id']}/complete",
        json={"decision": "approved"},
        headers=admin_auth,
    )
    res = await client.get("/api/v1/notifications", headers=eng_auth)
    assert any(n["title"].startswith("Workflow completed:") for n in res.json())

    # Mark all read clears the badge
    await client.post("/api/v1/notifications/read-all", headers=eng_auth)
    res = await client.get("/api/v1/notifications/unread-count", headers=eng_auth)
    assert res.json()["count"] == 0
