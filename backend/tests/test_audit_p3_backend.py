"""Audit 2026-10-29 P3 items with a backend side (Christoph 2026-11-02: fix
the P3 items):

- P3-12 a change's own routing past its first stage sends no stage FYIs
  (Summation & Budget, Customer activities); the first stage still does;
- P3-13 entering costing tells each department that owes its costing;
- P3-15 an unowned assessment row names the project team's responsible;
- P3-16 concerns say whether they were raised before assessment;
- P3-21 a change's check workflow done notice has a kind and names the change
  and the part number."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.models import ProjectResponsible
from app.models.change import (
    ChangeAssessment, ChangeChangelog, ChangeConcern, ChangeRequest,
)
from app.models.entities import User
from app.models.notification import Notification
from app.models.part import PartRevision
from app.models.workflow import (
    Department, UserDepartment, WfInstance, WfStage, WfStep, WfStepRasic, WfTemplate,
)
from app.services.workflow_service import WorkflowService
from tests.conftest import login
from tests.test_workflows import _start, _tasks_by_dept, wf_template  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _change(session, seed, number, **kw):
    c = ChangeRequest(change_number=number, title="x", reason="y",
                      change_type="physical_part", project_id=seed["project_id"],
                      raised_by=seed["admin_id"], **kw)
    session.add(c)
    await session.flush()
    return c


async def _fyi_stage(session_factory, seed, stage_order):
    async with session_factory() as s:
        r = Department(name=f"R{stage_order}", flow_type="action")
        i = Department(name=f"I{stage_order}", flow_type="info")
        s.add_all([r, i]); await s.flush()
        tmpl = WfTemplate(name=f"T{stage_order}", created_by=1)
        s.add(tmpl); await s.flush()
        stage = WfStage(template_id=tmpl.id, stage_order=stage_order, name="Summation & Budget")
        s.add(stage); await s.flush()
        step = WfStep(stage_id=stage.id, step_name="Step", position_in_stage=1)
        s.add(step); await s.flush()
        s.add_all([WfStepRasic(step_id=step.id, department_id=r.id, rasic_letter="R"),
                   WfStepRasic(step_id=step.id, department_id=i.id, rasic_letter="I"),
                   UserDepartment(user_id=seed["engineer_id"], department_id=i.id)])
        chg = await _change(s, seed, f"C-FYI-{stage_order}")
        inst = WfInstance(template_id=tmpl.id, change_id=chg.id, status="active",
                          current_stage_order=stage_order, started_by=seed["admin_id"])
        s.add(inst); await s.commit()
        stage = (await s.execute(select(WfStage).where(WfStage.id == stage.id).options(
            selectinload(WfStage.steps).selectinload(WfStep.rasic_assignments)))).scalar_one()
        await WorkflowService._create_stage_tasks(s, inst, stage)
        await s.commit()
        return (await s.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.kind == "fyi_stage"))).scalars().all()


async def test_p3_12_no_fyi_for_later_change_routing_stages(session_factory, seed):
    assert await _fyi_stage(session_factory, seed, 2) == []


async def test_p3_12_first_stage_still_informs(session_factory, seed):
    assert len(await _fyi_stage(session_factory, seed, 1)) == 1


async def test_p3_13_costing_open_tells_owing_departments_once(session_factory, seed, monkeypatch):
    from app.services import cm_switches, task_notices
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        d = Department(name="Toolshop", flow_type="action", is_active=True)
        s.add(d); await s.flush()
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=d.id))
        chg = await _change(s, seed, "C-COST-1", status="costing")
        await s.commit()

        async def pending(session, change):
            return [d.id]
        monkeypatch.setattr(ChangeService, "costing_pending_department_ids",
                            staticmethod(pending))
        assert await task_notices.on_costing(s, chg, seed["admin_id"]) == 1
        assert await task_notices.on_costing(s, chg, seed["admin_id"]) == 0   # once
        await s.commit()
        rows = (await s.execute(select(Notification).where(
            Notification.kind == "task_new",
            Notification.user_id == seed["engineer_id"]))).scalars().all()
        assert len(rows) == 1 and rows[0].title == "Your costing: C-COST-1"
        assert rows[0].link.endswith("?tab=costing")
        monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
        assert await task_notices.on_costing(s, chg, seed["admin_id"]) == 0


async def test_p3_15_and_16_responsible_and_raised_in_scoping(client, session_factory, seed):
    admin = await login(client, "admin@test.io")
    async with session_factory() as s:
        dev = Department(name="Development", flow_type="action", is_active=True)
        apqp = Department(name="APQP", flow_type="action", is_active=True)
        s.add_all([dev, apqp]); await s.flush()
        u = (await s.get(User, seed["engineer_id"]))
        s.add(UserDepartment(user_id=u.id, department_id=dev.id))
        s.add(ProjectResponsible(project_id=seed["project_id"], department_id=dev.id,
                                 user_id=u.id))
        chg = await _change(s, seed, "C-P3-15", status="in_assessment")
        s.add_all([ChangeAssessment(change_id=chg.id, department_id=dev.id, stage_order=1,
                                    verdict="pending"),
                   ChangeAssessment(change_id=chg.id, department_id=apqp.id, stage_order=1,
                                    verdict="pending")])
        entered = datetime.utcnow() - timedelta(hours=1)
        s.add(ChangeChangelog(change_id=chg.id, action="status_changed", action_description="x",
                              performed_by=seed["admin_id"], performed_at=entered,
                              field_name="status", old_value='"scoping"',
                              new_value='"in_assessment"'))
        s.add_all([
            ChangeConcern(change_id=chg.id, kind="reject_proposal", note="cancel it",
                          department_id=apqp.id, raised_by=seed["admin_id"],
                          raised_at=entered - timedelta(hours=1)),
            ChangeConcern(change_id=chg.id, kind="risk", note="rib", department_id=apqp.id,
                          raised_by=seed["admin_id"], raised_at=entered + timedelta(minutes=5)),
        ])
        await s.commit()
        cid, dev_id, apqp_id = chg.id, dev.id, apqp.id
    res = await client.get(f"/api/v1/changes/{cid}", headers=admin)
    assert res.status_code == 200, res.text
    by = {a["department_id"]: a for a in res.json()["assessments"]}
    assert by[dev_id]["responsible_name"] == u.full_name
    assert by[apqp_id]["responsible_name"] is None          # no team responsible
    res = await client.get(f"/api/v1/changes/{cid}/concerns", headers=admin)
    flags = {c["note"]: c["raised_in_scoping"] for c in res.json()}
    assert flags == {"cancel it": True, "rib": False}


async def test_p3_21_check_workflow_done_names_the_change(
        client, eng_auth, admin_auth, part, wf_template, seed, session_factory):
    await client.put(f"/api/v1/users/{seed['engineer_id']}/departments",
                     json={"department_ids": [wf_template["eng_id"]]}, headers=admin_auth)
    await client.put(f"/api/v1/users/{seed['admin_id']}/departments",
                     json={"department_ids": [wf_template["quality_id"]]}, headers=admin_auth)
    async with session_factory() as s:
        chg = await _change(s, seed, "C-WF-21")
        await s.execute(update(PartRevision).where(PartRevision.id == part["revision_id"])
                        .values(originating_change_id=chg.id))
        await s.commit()
        cid = chg.id
    inst = await _start(client, eng_auth, part["revision_id"], wf_template["template_id"])
    t1 = _tasks_by_dept(inst, wf_template["eng_id"], stage=1)[0]
    await client.post(f"/api/v1/workflow-instances/{inst['id']}/tasks/{t1['id']}/complete",
                      json={"decision": "approved"}, headers=eng_auth)
    cur = (await client.get(f"/api/v1/workflow-instances/revisions/{part['revision_id']}/current",
                            headers=eng_auth)).json()
    t2 = [t for t in cur["instance"]["tasks"] if t["stage_order"] == 2
          and t["is_actionable"] and t["status"] == "active"][0]
    await client.post(f"/api/v1/workflow-instances/{inst['id']}/tasks/{t2['id']}/complete",
                      json={"decision": "approved"}, headers=admin_auth)
    async with session_factory() as s:
        rows = (await s.execute(select(Notification).where(
            Notification.kind == "workflow_completed"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].title.startswith("Check workflow done: ") and "(C-WF-21)" in rows[0].title
    assert rows[0].link == f"/changes/{cid}?tab=release"
    assert "Workflow completed" not in rows[0].title
