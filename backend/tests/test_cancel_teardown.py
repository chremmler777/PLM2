"""Cancelling a change kills its references.

The leak this pins shut: a cancelled change left its engine work running —
the change-scoped assessment instance and the ECN instances on its part
revisions kept their 'active' tasks, so task lists pointed at work nobody
would ever do, forever. Cancelling now cancels every active instance the
change spawned and waives their open tasks; the workflow task list also
refuses tasks of non-active instances outright.
"""
import pytest
from sqlalchemy import select

from app.models.workflow import WfInstance, WfInstanceTask, WfTemplate, Department
from app.models.change import ChangeRequest
from app.models.part import Part, PartRevision
from app.services.workflow_service import WorkflowService

pytestmark = pytest.mark.asyncio


async def _seed_change_with_engine_work(session_factory, seed):
    """A change carrying both producers: a change-scoped instance and an ECN
    instance on a part revision it originated — each with one active task."""
    async with session_factory() as s:
        t = WfTemplate(name="Teardown Test", created_by=seed["admin_id"])
        dept = Department(name="Teardown Dept", flow_type="action", is_active=True)
        s.add_all([t, dept])
        await s.flush()
        chg = ChangeRequest(change_number="C-KILL-1", title="x", reason="y",
                            change_type="physical_part",
                            project_id=seed["project_id"],
                            raised_by=seed["admin_id"], status="costing")
        s.add(chg)
        await s.flush()
        part = Part(project_id=seed["project_id"], part_number="KILL-1",
                    name="p", part_type="internal_mfg",
                    created_by=seed["admin_id"])
        s.add(part)
        await s.flush()
        rev = PartRevision(part_id=part.id, revision_name="ECR1.1",
                           phase="ecr", status="draft",
                           originating_change_id=chg.id,
                           created_by=seed["admin_id"])
        s.add(rev)
        await s.flush()
        scoped = WfInstance(template_id=t.id, change_id=chg.id, status="active",
                            current_stage_order=1, started_by=seed["admin_id"])
        ecn = WfInstance(template_id=t.id, part_revision_id=rev.id,
                         status="active", current_stage_order=1,
                         started_by=seed["admin_id"])
        s.add_all([scoped, ecn])
        await s.flush()
        s.add_all([
            WfInstanceTask(instance_id=scoped.id, stage_order=1, step_id=None,
                           department_id=dept.id, rasic_letter="R",
                           status="active", is_actionable=True),
            WfInstanceTask(instance_id=ecn.id, stage_order=1, step_id=None,
                           department_id=dept.id, rasic_letter="R",
                           status="active", is_actionable=True),
        ])
        await s.commit()
        return {"change_id": chg.id, "instance_ids": [scoped.id, ecn.id],
                "dept_id": dept.id}


async def test_cancelling_a_change_cancels_its_engine_work(
        client, admin_auth, seed, session_factory):
    ctx = await _seed_change_with_engine_work(session_factory, seed)

    res = await client.post(f"/api/v1/changes/{ctx['change_id']}/transition",
                            headers=admin_auth,
                            json={"to_status": "cancelled",
                                  "cancellation_reason": "customer pulled out"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "cancelled"

    async with session_factory() as s:
        instances = (await s.execute(select(WfInstance).where(
            WfInstance.id.in_(ctx["instance_ids"])))).scalars().all()
        assert [i.status for i in instances] == ["canceled", "canceled"]
        assert all(i.canceled_at is not None for i in instances)
        tasks = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id.in_(ctx["instance_ids"])))).scalars().all()
        assert [t.status for t in tasks] == ["waived", "waived"]

    # ...and the changelog says what happened to the engine work.
    log = await client.get(f"/api/v1/changes/{ctx['change_id']}/changelog",
                           headers=admin_auth)
    assert any(e["action"] == "engine_work_cancelled" for e in log.json())


async def test_task_list_refuses_tasks_of_dead_instances(
        session_factory, seed):
    """Defense for rows that predate the teardown: an orphaned active task on
    a canceled (or historically dead) instance must not surface."""
    ctx = await _seed_change_with_engine_work(session_factory, seed)
    async with session_factory() as s:
        # Simulate the historical leak: instance dead, task still 'active'.
        inst = await s.get(WfInstance, ctx["instance_ids"][1])
        inst.status = "canceled"
        await s.commit()

        rows = await WorkflowService.get_my_tasks(
            s, [ctx["dept_id"]], seed["admin_id"])
        assert [r for r in rows
                if r["instance_id"] in ctx["instance_ids"]] == []
